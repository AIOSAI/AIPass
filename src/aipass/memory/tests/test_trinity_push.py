# =================== AIPass ====================
# Name: test_trinity_push.py
# Description: Red-first pins for the trinity push — the archive-verify-prune law above all
# Version: 1.2.1
# Created: 2026-08-27
# Modified: 2026-09-15
# =============================================

"""Trinity push — the pins that make the prune lane safe to run.

THE ONE LAW under test
----------------------
``vectorize -> verify -> prune`` is an ORDER, and every step of it can fail.
The tests in :class:`TestNothingIsPrunedWithoutProof` exist because the cheap
implementation of this lane — store, assume, delete — is exactly the shape
that deleted four months of @ai_mail's mail into a collection that had never
been created.  A store call's own success flag is the writer's opinion; the
read-back is the evidence.  If the evidence is missing, mismatched, or simply
never arrives, NOTHING may leave the live file.

Every test here was written against the behaviour required, not the behaviour
found: the whole module is new, so "red first" means each pin fails against a
push that skips its step (see the mutation notes in the class docstrings).
"""

import copy
import json
import tempfile
from pathlib import Path

import pytest

from aipass.memory.apps.handlers.rollover import todo_roll
from aipass.memory.apps.handlers.templates import trinity_push as tp


_MEMORY_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _backlogs_stay_in_tmp(tmp_path, monkeypatch):
    """No pin in this file may reach the repo's real .backup/todo/: an unrouted backlog lands under tmp_path."""
    real = todo_roll.backlog_path_for

    def scratch(branch_dir, backup_root=None):
        return real(branch_dir, tmp_path / ".backup" if backup_root is None else backup_root)

    monkeypatch.setattr(todo_roll, "backlog_path_for", scratch)


# =============================================================================
# DOUBLES
# =============================================================================


class FakeStore:
    """A vector store whose read-back can be made to lie in specific ways.

    It implements the two calls SEPARATELY — ``vectorize_and_store`` records
    what it was given, ``get_by_ids`` answers from its own shelf. That
    separation is the point: a double whose read-back echoed the store call
    could never catch a push that trusts the store's success flag.
    """

    def __init__(self, mode: str = "honest"):
        self.mode = mode
        # One shelf PER db_path: two chroma databases are two stores, and a
        # single shared shelf would let the global destination "verify"
        # against vectors only the local destination ever received.
        self.shelves: dict[str, dict[str, str]] = {}
        self.store_calls: list[dict] = []
        self.readback_calls: list[tuple] = []

    def _shelf(self, db_path) -> dict:
        return self.shelves.setdefault(str(db_path), {})

    @property
    def shelf(self) -> dict:
        """Every shelf merged — for tests that only use one destination."""
        merged: dict[str, str] = {}
        for shelf in self.shelves.values():
            merged.update(shelf)
        return merged

    def vectorize_and_store_subprocess(self, branch, memory_type, texts, metadatas, db_path=None):
        self.store_calls.append(
            {"branch": branch, "memory_type": memory_type, "texts": list(texts), "metadatas": list(metadatas)}
        )
        if self.mode == "store_refuses":
            return {"success": False, "error": "embedding refused"}

        shelf = self._shelf(db_path)
        ids = [f"{branch}_{memory_type}_{index:04d}" for index, _ in enumerate(texts)]
        if self.mode != "never_lands":
            for vector_id, text in zip(ids, texts):
                # `corrupt` puts something DIFFERENT on the shelf: the vector
                # exists, so a presence-only check would pass it.
                shelf[vector_id] = ("CORRUPTED " + text) if self.mode == "corrupt" else text
        if self.mode == "loses_one" and ids:
            shelf.pop(ids[0], None)
        return {"success": True, "collection": f"{branch.lower()}_{memory_type.lower()}", "ids": ids}

    def get_by_ids_subprocess(self, collection_name, ids, db_path=None):
        self.readback_calls.append((collection_name, tuple(ids)))
        if self.mode == "readback_fails":
            return {"success": False, "error": "collection not found"}
        shelf = self._shelf(db_path)
        return {"success": True, "documents": {i: shelf[i] for i in ids if i in shelf}}


def _entry(number: int, **fields) -> dict:
    """A canonical session entry with optional overrides."""
    base = {"number": number, "date": "2026-08-27", "summary": f"session {number}", "status": "completed"}
    base.update(fields)
    return base


_NUMBER = {"type": "int", "required": True}
_DATE = {"type": "str", "required": True, "max_chars": 10}
_TAGS = {"type": "list[str]", "required": False, "max_items": 10, "max_chars": 120}


def _fields(**text: dict) -> dict:
    """A closed field map in the shape of entry_limits.entry_types.<type>.fields."""
    return {"number": _NUMBER, "date": _DATE, **text}


def _config(max_chars: int = 300, todos_count: int = 10) -> dict:
    """Minimal config with the four entry types the standard names and the todo pad size.

    Each type carries its closed ``fields`` map, because that map is the only
    source of an entry's shape since 1.2.0 of the push: without it the push
    falls back to the module-level rules cache, and a test then passes or fails
    on whether an earlier test on the same xdist worker happened to warm that
    cache from the real config (macOS run 35050261305, class-scoped worker).
    """
    return {
        "rollover": {
            "defaults": {
                "local": {
                    "sessions": {"count": 15, "auto_compact_cap": 3},
                    "key_learnings": {"count": 15},
                    "todos": {"count": todos_count},
                },
                "observations": {"observations": {"count": 15}},
            },
            "per_branch": {},
        },
        "entry_limits": {
            "entry_types": {
                "sessions": {
                    "container": "sessions",
                    "field": "summary",
                    "max_chars": max_chars,
                    "kind": "list",
                    "fields": _fields(
                        summary={"type": "str", "required": True, "max_chars": max_chars},
                        status={"type": "str", "required": True, "max_chars": 40},
                        tags=_TAGS,
                    ),
                },
                "key_learnings": {
                    "container": "key_learnings",
                    "field": "value",
                    "max_chars": 200,
                    "kind": "list",
                    "fields": _fields(
                        key={"type": "str", "required": True, "max_chars": 80},
                        value={"type": "str", "required": True, "max_chars": 200},
                    ),
                },
                "todos": {
                    "container": "todos",
                    "field": "task",
                    "max_chars": 100,
                    "kind": "list",
                    "fields": _fields(
                        task={"type": "str", "required": True, "max_chars": 100},
                        priority={"type": "str", "required": False, "max_chars": 10},
                    ),
                },
                "observations": {
                    "container": "observations",
                    "field": "note",
                    "max_chars": 300,
                    "kind": "list",
                    "fields": _fields(
                        note={"type": "str", "required": True, "max_chars": 300},
                        tags={**_TAGS, "required": True},
                    ),
                },
            },
            "per_branch": {},
        },
    }


def _seedgo_renders_the_retired_todos_tab() -> bool:
    """True while seedgo's trinity checker still expects the pre-DPLAN-0345 todos tab.

    A changed mirror signature counts as landed: the checker pin then runs strict.
    """
    from aipass.seedgo.apps.handlers.aipass_standards import trinity_groups

    try:
        line = trinity_groups.expected_meta_line("todos", "guinea", _config(), "prose")
    except TypeError:
        return False
    return "rollover OFF" in line


def _scope(root: Path) -> dict:
    """A one-branch scope, so push() tests never depend on the live registry."""
    return {"branches": [{"name": root.name, "path": root}], "error": None}


def _branch(tmp_path: Path, name: str, local: dict, observations: dict | None = None) -> Path:
    """Mint a branch directory with .trinity files on disk."""
    root = tmp_path / name
    trinity = root / ".trinity"
    trinity.mkdir(parents=True)
    (trinity / "local.json").write_text(json.dumps(local), encoding="utf-8")
    (trinity / "observations.json").write_text(
        json.dumps(observations if observations is not None else {"observations": []}), encoding="utf-8"
    )
    return root


# =============================================================================
# THE LAW
# =============================================================================


class TestNothingIsPrunedWithoutProof:
    """Verification failure means the live file is left exactly as found.

    Mutations these bite:
      M1  apply_plan prunes before calling archive_prunes      -> all fail
      M2  archive_prunes returns verified=True unconditionally -> all fail
      M3  _verify_ingestion checks presence but not content    -> corrupt fails
      M4  _verify_ingestion ignores missing ids                -> loses_one fails
    """

    def _plan(self, tmp_path):
        local = {"sessions": [_entry(2), _entry(1, extra="drift")]}
        root = _branch(tmp_path, "guinea", local)
        return tp.plan_branch("guinea", root, _config()), root

    def test_the_honest_path_archives_then_prunes(self, tmp_path):
        plan, root = self._plan(tmp_path)
        store = FakeStore("honest")

        result = tp.apply_plan(plan, store, [("global", None)])

        assert result["refused"] is False
        assert result["pruned"] == 1
        on_disk = json.loads((root / ".trinity" / "local.json").read_text(encoding="utf-8"))
        assert [entry["number"] for entry in on_disk["sessions"] if "extra" not in entry] == [3, 2]

    def test_a_store_that_refuses_prunes_nothing(self, tmp_path):
        plan, root = self._plan(tmp_path)
        before = (root / ".trinity" / "local.json").read_text(encoding="utf-8")

        result = tp.apply_plan(plan, FakeStore("store_refuses"), [("global", None)])

        assert result["refused"] is True
        assert result["pruned"] == 0
        assert (root / ".trinity" / "local.json").read_text(encoding="utf-8") == before

    def test_a_vector_that_never_landed_prunes_nothing(self, tmp_path):
        """The store SAID success and returned ids; the shelf is empty."""
        plan, root = self._plan(tmp_path)
        before = (root / ".trinity" / "local.json").read_text(encoding="utf-8")

        result = tp.apply_plan(plan, FakeStore("never_lands"), [("global", None)])

        assert result["refused"] is True
        assert (root / ".trinity" / "local.json").read_text(encoding="utf-8") == before
        assert "could not be verified" in result["errors"][-1]

    def test_a_vector_read_back_with_different_content_prunes_nothing(self, tmp_path):
        """Presence is not proof — the archived text must be the entry."""
        plan, root = self._plan(tmp_path)
        before = (root / ".trinity" / "local.json").read_text(encoding="utf-8")

        result = tp.apply_plan(plan, FakeStore("corrupt"), [("global", None)])

        assert result["refused"] is True
        assert (root / ".trinity" / "local.json").read_text(encoding="utf-8") == before

    def test_one_missing_vector_out_of_many_prunes_nothing(self, tmp_path):
        local = {"sessions": [_entry(number, extra="drift") for number in (3, 2, 1)]}
        root = _branch(tmp_path, "guinea", local)
        plan = tp.plan_branch("guinea", root, _config())
        before = (root / ".trinity" / "local.json").read_text(encoding="utf-8")

        result = tp.apply_plan(plan, FakeStore("loses_one"), [("global", None)])

        assert result["refused"] is True
        assert (root / ".trinity" / "local.json").read_text(encoding="utf-8") == before

    def test_a_failing_read_back_call_prunes_nothing(self, tmp_path):
        plan, root = self._plan(tmp_path)
        before = (root / ".trinity" / "local.json").read_text(encoding="utf-8")

        result = tp.apply_plan(plan, FakeStore("readback_fails"), [("global", None)])

        assert result["refused"] is True
        assert (root / ".trinity" / "local.json").read_text(encoding="utf-8") == before

    def test_every_destination_must_verify_not_just_the_first(self, tmp_path):
        """A local store that works does not license a global store that does not."""
        plan, _ = self._plan(tmp_path)

        class HalfHonest(FakeStore):
            def __init__(self):
                super().__init__("honest")
                self.seen = 0

            def vectorize_and_store_subprocess(self, branch, memory_type, texts, metadatas, db_path=None):
                self.seen += 1
                self.mode = "honest" if self.seen == 1 else "never_lands"
                return super().vectorize_and_store_subprocess(branch, memory_type, texts, metadatas, db_path)

        local_db = str(Path(tempfile.gettempdir()) / "x")
        result = tp.apply_plan(plan, HalfHonest(), [("local", local_db), ("global", None)])

        assert result["refused"] is True
        assert result["pruned"] == 0

    def test_an_absent_vector_and_a_corrupted_one_get_different_reasons(self, tmp_path):
        """Both refuse — but the repair differs, so the reason must too.

        "read back with different content" sends someone hunting for an
        encoding bug; "absent on read-back" says the write never landed. This
        branch learned the cost of one message for two faults the hard way:
        `unmeasurable` covering a MISSING field read as a shape problem for
        two months while 42 renamed keys measured as zero.
        """
        plan, _ = self._plan(tmp_path)

        absent = tp.apply_plan(plan, FakeStore("never_lands"), [("global", None)])
        corrupt = tp.apply_plan(plan, FakeStore("corrupt"), [("global", None)])

        assert "absent on read-back" in absent["errors"][-1]
        assert "different content" in corrupt["errors"][-1]
        assert absent["errors"][-1] != corrupt["errors"][-1]

    def test_a_partially_absent_archive_says_absent_not_mismatched(self, tmp_path):
        local = {"sessions": [_entry(number, extra="drift") for number in (3, 2, 1)]}
        root = _branch(tmp_path, "guinea", local)
        plan = tp.plan_branch("guinea", root, _config())

        result = tp.apply_plan(plan, FakeStore("loses_one"), [("global", None)])

        assert "absent on read-back" in result["errors"][-1]

    def test_the_read_back_is_a_separate_call_from_the_store(self, tmp_path):
        """Structural pin: verification that never calls the store back is not verification."""
        plan, _ = self._plan(tmp_path)
        store = FakeStore("honest")

        tp.apply_plan(plan, store, [("global", None)])

        assert store.readback_calls, "nothing was read back — the success flag was taken on trust"


class TestArchivedContentIsTheEntry:
    """Verbatim means verbatim: no transform, no summary, no re-shaping."""

    def test_the_archived_document_round_trips_to_the_original_entry(self):
        entry = {"number": 7, "date": "2026-01-01", "note": ["a", {"b": 2}], "session": 12}
        prune = {"entry": entry, "file_key": "observations", "container": "observations", "number": 7, "reason": "x"}

        assert json.loads(tp.archive_text(prune)) == entry

    def test_metadata_carries_the_entry_identity_and_the_reason(self):
        entry = _entry(9, extra="drift")
        prune = {
            "entry": entry,
            "file_key": "local",
            "container": "sessions",
            "number": 9,
            "reason": "extra field(s) extra",
        }

        meta = tp._archive_metadata("guinea", prune, "2026-08-27T10:00:00")

        assert meta["entry_number"] == 9
        assert meta["entry_date"] == "2026-08-27"
        assert meta["archived_by"] == "trinity_push"
        assert "extra" in meta["prune_reason"]

    def test_metadata_values_stay_scalars(self):
        """ChromaDB takes scalars only — a list here fails the store at run time."""
        prune = {
            "entry": _entry(1),
            "file_key": "local",
            "container": "sessions",
            "number": 1,
            "reason": "r",
        }

        meta = tp._archive_metadata("guinea", prune, "2026-08-27T10:00:00")

        assert all(isinstance(value, (str, int, float, bool)) for value in meta.values())


# =============================================================================
# WHAT COUNTS AS CANONICAL
# =============================================================================


class TestTheShapeGate:
    """An entry carries over untouched only if it is canonical in shape AND size."""

    def test_a_canonical_session_carries_over(self):
        assert tp.is_canonical("sessions", _entry(1))

    def test_tags_are_optional_on_sessions_and_allowed(self):
        assert tp.is_canonical("sessions", _entry(1, tags=["a", "b"]))

    def test_an_extra_field_is_a_violation(self):
        problems = tp.entry_problems("sessions", _entry(1, findings=[]))
        assert any("extra field" in problem for problem in problems)

    def test_a_renamed_field_is_named_by_its_absence(self):
        entry = {"number": 1, "date": "2026-08-27", "learning": "text"}
        problems = tp.entry_problems("key_learnings", entry)
        assert any("missing 'key'" in problem for problem in problems)
        assert any("missing 'value'" in problem for problem in problems)

    def test_a_list_shaped_note_is_a_violation(self):
        entry = {"number": 1, "date": "2026-08-27", "note": [{"a": 1}], "tags": []}
        assert any("must be str" in problem for problem in tp.entry_problems("observations", entry))

    def test_a_bool_number_is_not_an_int(self):
        """bool is an int subclass — the checker rejects it and so must this."""
        assert not tp.is_canonical("sessions", _entry(1) | {"number": True})

    def test_an_over_cap_entry_is_non_canonical(self):
        """Shape and size are different scan groups; the push must clear both."""
        cap = {"field": "summary", "max_chars": 300}
        entry = _entry(1, summary="x" * 301)

        assert tp.is_canonical("sessions", entry) is True
        assert tp.is_canonical("sessions", entry, cap) is False
        assert any("over its 300-char cap" in problem for problem in tp.entry_problems("sessions", entry, cap))

    def test_an_entry_exactly_at_cap_survives(self):
        cap = {"field": "summary", "max_chars": 300}
        assert tp.is_canonical("sessions", _entry(1, summary="x" * 300), cap)

    def test_caps_come_from_the_shared_resolver(self):
        """Same resolver as the write gate — the push cannot prune on a number the gate does not enforce."""
        caps = tp.resolve_caps(_config(max_chars=123), "guinea")
        assert caps["sessions"]["max_chars"] == 123


# =============================================================================
# THE FRAME
# =============================================================================


class TestTheMachineFrame:
    """document_metadata is a CLOSED set and the prose comes from the templates."""

    def test_non_standard_keys_are_pruned_from_document_metadata(self):
        current = {"created": "2026-01-01", "status": {"health": "healthy"}, "invented": 1}

        meta = tp.build_doc_metadata(current, "local", "guinea")

        assert set(meta) == set(tp.DOC_META_FIELDS)
        assert "status" not in meta
        assert "invented" not in meta

    def test_created_is_the_one_field_that_survives(self):
        meta = tp.build_doc_metadata({"created": "2026-01-01"}, "local", "guinea")
        assert meta["created"] == "2026-01-01"

    def test_a_missing_created_does_not_invent_a_false_history(self):
        meta = tp.build_doc_metadata({}, "local", "guinea")
        assert meta["created"] == tp._today()

    def test_managed_by_is_the_exact_branch_directory_name(self):
        """Patrick's ruling, and what seedgo's checker compares against."""
        assert tp.build_doc_metadata({}, "local", "ai_mail")["managed_by"] == "ai_mail"
        assert tp.build_doc_metadata({}, "local", "aipass_site")["managed_by"] == "aipass_site"

    def test_document_name_takes_the_file_suffix(self):
        assert tp.build_doc_metadata({}, "local", "guinea")["document_name"] == "guinea.LOCAL"
        assert tp.build_doc_metadata({}, "observations", "guinea")["document_name"] == "guinea.OBSERVATIONS"

    def test_usage_is_the_gold_template_text_byte_for_byte(self):
        template = json.loads((_MEMORY_ROOT / "templates" / "LOCAL.template.json").read_text(encoding="utf-8"))

        meta = tp.build_doc_metadata({}, "local", "guinea")

        assert meta["_usage"] == template["document_metadata"]["_usage"]

    def test_guidelines_are_overwritten_with_the_template_verbatim(self):
        template = json.loads((_MEMORY_ROOT / "templates" / "OBSERVATIONS.template.json").read_text(encoding="utf-8"))
        before = {"guidelines": {"purpose": "a per-branch wording nobody agreed"}, "observations": []}

        frame = tp.build_frame(before, "observations", "guinea", {"observations": []}, _config())

        assert frame["guidelines"] == template["guidelines"]

    def test_top_level_keys_are_exactly_the_canonical_set_in_order(self):
        before = {"sessions": [], "active_tasks": {"stray": 1}, "narrative": "x"}

        frame = tp.build_frame(before, "local", "guinea", {"sessions": []}, _config())

        assert list(frame) == tp._KEY_ORDER["local"]

    def test_the_frame_report_names_what_it_prunes(self):
        before = {"document_metadata": {"status": {}, "weird": 1}, "active_tasks": {}, "sessions": []}
        after = tp.build_frame(before, "local", "guinea", {"sessions": []}, _config())

        changes = tp._frame_changes(before, after, "local")

        assert any("status" in change and "prune" in change for change in changes)
        assert any("active_tasks" in change for change in changes)

    def test_the_gold_templates_spell_the_branch_placeholder_as_spawn_does(self):
        """spawn renders {{BRANCH}} lowercase; gold must match or spawn-templates reverts spawn."""
        from aipass.memory.apps.handlers.monitor import detector

        assert sorted(path.name for path in detector._TEMPLATE_MAP.values()) == [
            "LOCAL.template.json",
            "OBSERVATIONS.template.json",
        ]
        for path in detector._TEMPLATE_MAP.values():
            text = path.read_text(encoding="utf-8")
            assert "{{BRANCHNAME}}" not in text, path.name
            assert "{{BRANCH}}" in text, path.name
            tags = tp._template_tags(json.loads(text), "guinea")
            assert tags[-1] == "guinea", path.name
            assert not [tag for tag in tags if "{{" in tag], path.name


# =============================================================================
# THE NOTE
# =============================================================================


class TestTheNote:
    """One canonical session entry, or none at all."""

    def test_the_note_is_itself_canonical(self):
        note = tp.build_note(12, [_entry(4)])
        assert tp.is_canonical("sessions", note)

    def test_the_note_fits_the_cap_it_announces(self):
        note = tp.build_note(999, [])
        assert tp.is_canonical("sessions", note, {"field": "summary", "max_chars": 300})

    def test_the_note_continues_the_numbering(self):
        assert tp.build_note(3, [_entry(9), _entry(4)])["number"] == 10

    def test_the_note_numbers_from_one_on_an_empty_file(self):
        assert tp.build_note(3, [])["number"] == 1

    def test_the_note_names_the_recall_verb(self):
        """The note promises a way back; if the verb is wrong the promise is a lie."""
        assert "drone @memory search" in tp.build_note(5, [])["summary"]

    def test_no_note_when_nothing_was_pruned(self, tmp_path):
        root = _branch(tmp_path, "clean", {"sessions": [_entry(1)]})
        plan = tp.plan_branch("clean", root, _config())

        result = tp.apply_plan(plan, FakeStore("honest"), [("global", None)])

        assert result["pruned"] == 0
        assert result["noted"] is False
        on_disk = json.loads((root / ".trinity" / "local.json").read_text(encoding="utf-8"))
        assert len(on_disk["sessions"]) == 1

    def test_a_note_that_is_not_canonical_is_refused_not_written(self, tmp_path, monkeypatch):
        """The push must not author, in its own hand, the violation it removes.

        If the note ever drifted past its own cap, writing it would leave the
        branch failing the checker on the ONE entry the push wrote itself.
        """
        root = _branch(tmp_path, "guinea", {"sessions": [_entry(1, extra="drift")]})
        plan = tp.plan_branch("guinea", root, _config())
        monkeypatch.setattr(tp, "build_note", lambda *args, **kwargs: {"number": 2, "summary": "x" * 400})

        result = tp.apply_plan(plan, FakeStore("honest"), [("global", None)])

        assert result["noted"] is False
        assert any("not canonical" in message for message in result["errors"])
        sessions = json.loads((root / ".trinity" / "local.json").read_text(encoding="utf-8"))["sessions"]
        assert all("x" * 400 not in entry.get("summary", "") for entry in sessions)

    def test_the_note_lands_on_top_of_the_branchs_own_sessions(self, tmp_path):
        root = _branch(tmp_path, "guinea", {"sessions": [_entry(2), _entry(1, extra="drift")]})
        plan = tp.plan_branch("guinea", root, _config())

        tp.apply_plan(plan, FakeStore("honest"), [("global", None)])

        sessions = json.loads((root / ".trinity" / "local.json").read_text(encoding="utf-8"))["sessions"]
        assert sessions[0]["tags"] == ["system_push"]
        assert sessions[0]["number"] == 3


# =============================================================================
# SCOPE AND REFUSAL
# =============================================================================


class TestScope:
    """Fleet mode covers a named list, and an unknown branch is an error."""

    def test_the_fleet_scope_holds_the_core_citizens(self, live_fleet):
        """Split from the resident half on 2026-08-27, and the split is the point.

        The core citizens ship with any installation, so this runs on every
        lane that has a registry at all — including the Windows e2e job, where
        it is the only half that was ever a claim about the software.
        """
        names = {item["name"] for item in tp.resolve_scope()["branches"]}
        assert {"memory", "canary", "hooks"} <= names

    def test_the_fleet_scope_holds_the_named_residents(self, live_residents):
        """The other half — true only where the residents are actually installed."""
        names = {item["name"] for item in tp.resolve_scope()["branches"]}
        assert {"baud", "earmark", "finch", "aipass_site"} <= names

    def test_on_hold_projects_are_not_swept_in(self, live_fleet):
        """marketstand is 'active' inside a directory named (on _hold) — a glob would take it.

        Guarded although it passes on a clean checkout: an EMPTY scope also
        contains no marketstand, and passing for that reason measures nothing.
        """
        names = {item["name"] for item in tp.resolve_scope()["branches"]}
        assert "marketstand" not in names

    def test_this_lane_owns_no_resident_resolution_of_its_own(self):
        """INVERTED 2026-08-28, deliberately, and worth saying why.

        This test used to assert the opposite ruling: that the resident list
        was explicit and `glob("projects` appeared nowhere. DPLAN-0319 replaced
        the named list with a glob made safe by passport classification, so the
        old assertion now pins a design that was retired on purpose — the
        dangerous kind of green.

        What survives is the part that was really being protected: this lane
        must not resolve residents itself. It asks registry_scope, which globs
        AND classifies, instead of carrying a second answer.
        """
        source = (_MEMORY_ROOT / "apps" / "handlers" / "templates" / "trinity_push.py").read_text(encoding="utf-8")
        assert 'glob("projects' not in source, "the push lane grew its own discovery"
        assert "registry_scope.fleet_branches(" in source

    def test_a_single_branch_resolves_with_or_without_the_at_sign(self, live_fleet):
        assert tp.resolve_scope("@canary")["branches"][0]["name"] == "canary"
        assert tp.resolve_scope("canary")["branches"][0]["name"] == "canary"

    def test_an_unknown_branch_is_an_error_not_an_empty_run(self):
        """Silence would read as 'nothing to do' for a name that was mistyped."""
        result = tp.resolve_scope("wizard")
        assert result["branches"] == []
        assert "Unknown branch" in result["error"]

    def test_the_branch_name_is_the_directory_not_the_registry_label(self, live_fleet):
        """The checker compares managed_by to the directory name; BACKUP vs backup would fail it."""
        names = {item["name"] for item in tp.resolve_scope()["branches"]}
        assert "backup" in names
        assert "BACKUP" not in names


class TestRefusalIsLoud:
    """A branch that cannot be read is refused by name, never skipped."""

    def test_an_unreadable_local_file_refuses_the_whole_branch(self, tmp_path):
        root = _branch(tmp_path, "broken", {"sessions": []})
        (root / ".trinity" / "local.json").write_text("{not json", encoding="utf-8")

        plan = tp.plan_branch("broken", root, _config())

        assert plan["errors"]
        assert "broken" in plan["errors"][0]

    def test_a_refused_branch_writes_nothing_at_all(self, tmp_path):
        root = _branch(tmp_path, "broken", {"sessions": [_entry(1, extra="x")]})
        (root / ".trinity" / "observations.json").write_text("[]", encoding="utf-8")
        plan = tp.plan_branch("broken", root, _config())
        before = (root / ".trinity" / "local.json").read_text(encoding="utf-8")

        result = tp.apply_plan(plan, FakeStore("honest"), [("global", None)])

        assert result["refused"] is True
        assert (root / ".trinity" / "local.json").read_text(encoding="utf-8") == before

    def test_a_section_of_the_wrong_type_refuses_rather_than_reframing(self, tmp_path):
        """Rebuilding a frame around a section we could not read would delete it."""
        root = _branch(tmp_path, "odd", {"sessions": {"not": "a list"}})

        plan = tp.plan_branch("odd", root, _config())

        assert any("must be a list" in message for message in plan["errors"])

    def test_a_missing_trinity_directory_is_reported(self, tmp_path):
        plan = tp.plan_branch("ghost", tmp_path / "ghost", _config())
        assert any("no .trinity" in message for message in plan["errors"])


class TestStraysAreReportedNeverDeleted:
    """Deleting another branch's files is outside this lane's mandate."""

    def test_strays_are_listed(self, tmp_path):
        root = _branch(tmp_path, "messy", {"sessions": []})
        (root / ".trinity" / "mystery_file.json").write_text("{}", encoding="utf-8")

        plan = tp.plan_branch("messy", root, _config())

        assert "mystery_file.json" in plan["strays"]

    def test_strays_survive_the_push(self, tmp_path):
        root = _branch(tmp_path, "messy", {"sessions": [_entry(1, extra="x")]})
        stray = root / ".trinity" / "mystery_file.json"
        stray.write_text("{}", encoding="utf-8")
        plan = tp.plan_branch("messy", root, _config())

        tp.apply_plan(plan, FakeStore("honest"), [("global", None)])

        assert stray.is_file()

    def test_a_known_migration_backup_is_not_a_stray(self, tmp_path):
        """An accounted-for artifact of a NAMED migration is not unexplained.

        54 of these across 22 branches made every branch report strays on every
        run forever, which is a line that can never be cleared: the push may not
        delete them and does not need them gone. @spawn and @devpulse both read
        that permanent line as "this branch is out of push scope" on 2026-09-07
        and held the first real bump back on it. `.pre_v2_backup` is @spawn's
        migrate-passports, `.pre_v3_backup` is this branch's own v3 rollover.
        """
        root = _branch(tmp_path, "migrated", {"sessions": []})
        trinity = root / ".trinity"
        for name in ("local.json.pre_v3_backup", "observations.json.pre_v3_backup", "passport.json.pre_v2_backup"):
            (trinity / name).write_text("{}", encoding="utf-8")

        plan = tp.plan_branch("migrated", root, _config())

        assert plan["strays"] == []

    def test_a_known_backup_still_survives_the_push(self, tmp_path):
        """Excluded from the report is not excluded from existing — still never deleted."""
        root = _branch(tmp_path, "migrated", {"sessions": [_entry(1, extra="x")]})
        backup = root / ".trinity" / "passport.json.pre_v2_backup"
        backup.write_text("{}", encoding="utf-8")
        plan = tp.plan_branch("migrated", root, _config())

        tp.apply_plan(plan, FakeStore("honest"), [("global", None)])

        assert backup.is_file()


# =============================================================================
# DRY RUN
# =============================================================================


class TestDryRunWritesNothing:
    """The report is the artifact; the disk is untouched."""

    def test_a_dry_run_leaves_every_file_byte_identical(self, tmp_path, monkeypatch):
        root = _branch(tmp_path, "guinea", {"sessions": [_entry(2), _entry(1, extra="drift")]})
        before = (root / ".trinity" / "local.json").read_bytes()
        monkeypatch.setattr(tp, "resolve_scope", lambda branch=None: _scope(root))
        monkeypatch.setattr(tp.config_loader, "load", _config)

        result = tp.push(branch="guinea", dry_run=True, store_client=FakeStore("honest"))

        assert result["dry_run"] is True
        assert result["branches"][0]["pruned"] == 1
        assert (root / ".trinity" / "local.json").read_bytes() == before

    def test_a_dry_run_never_touches_the_vector_store(self, tmp_path, monkeypatch):
        root = _branch(tmp_path, "guinea", {"sessions": [_entry(1, extra="drift")]})
        store = FakeStore("honest")
        monkeypatch.setattr(tp, "resolve_scope", lambda branch=None: _scope(root))
        monkeypatch.setattr(tp.config_loader, "load", _config)

        tp.push(branch="guinea", dry_run=True, store_client=store)

        assert store.store_calls == []

    def test_a_dry_run_never_stamps_a_receipt(self, tmp_path, monkeypatch):
        root = _branch(tmp_path, "guinea", {"sessions": [_entry(1, extra="drift")]})
        monkeypatch.setattr(tp, "resolve_scope", lambda branch=None: _scope(root))
        monkeypatch.setattr(tp.config_loader, "load", _config)

        tp.push(branch="guinea", dry_run=True, store_client=FakeStore("honest"))

        assert not (root / ".trinity" / ".template_version.json").exists()

    def test_the_dry_run_reports_the_reason_per_entry(self, tmp_path, monkeypatch):
        root = _branch(tmp_path, "guinea", {"sessions": [_entry(1, findings=[])]})
        monkeypatch.setattr(tp, "resolve_scope", lambda branch=None: _scope(root))
        monkeypatch.setattr(tp.config_loader, "load", _config)

        result = tp.push(branch="guinea", dry_run=True, store_client=FakeStore("honest"))

        prune = result["branches"][0]["prunes"][0]
        assert prune["container"] == "sessions"
        assert prune["number"] == 1
        assert "findings" in prune["reason"]


# =============================================================================
# WHAT THE PUSH PRODUCES
# =============================================================================


class TestThePushedFileIsCanonical:
    """The output is measured by the standard's own checker, not by opinion."""

    def test_a_pushed_branch_satisfies_the_trinity_checker(self, tmp_path):
        pytest.importorskip("aipass.seedgo.apps.handlers.aipass_standards.trinity_check")
        from aipass.seedgo.apps.handlers.aipass_standards import trinity_check

        local = {
            "document_metadata": {"created": "2026-01-01", "status": {"health": "healthy"}},
            "sessions": [_entry(2), _entry(1, findings=["drift"])],
            "key_learnings": [],
            "todos": [],
            "active_tasks": {"stray": True},
        }
        observations = {
            "document_metadata": {"created": "2026-01-01"},
            "observations": [{"number": 1, "date": "2026-08-27", "note": "n", "tags": []}],
        }
        root = _branch(tmp_path, "guinea", local, observations)
        (root / ".trinity" / "passport.json").write_text("{}", encoding="utf-8")
        (root / ".trinity" / "README.md").write_text("# Identity & Memory\n", encoding="utf-8")

        plan = tp.plan_branch("guinea", root, _config())
        tp.apply_plan(plan, FakeStore("honest"), [("global", None)])

        result = trinity_check.check_branch(str(root))
        failing = [check["name"] for check in result["checks"] if check["score"] < 100]
        messages = [str(check.get("message")) for check in result["checks"] if check["score"] < 100]
        if failing == ["Meta lines & _usage"] and _seedgo_renders_the_retired_todos_tab():
            # DPLAN-0345 landing order: memory rows 3-4 and seedgo row 6 go in ONE
            # commit. Until seedgo's mirror renders the pad tab, the ONLY allowed
            # miss is the todos_meta byte-match; anything else stays red, and the
            # moment the mirror lands this pin runs strict again on its own.
            assert all("todos_meta" in message and "_usage does not" not in message for message in messages), messages
            pytest.xfail("seedgo's todos tab mirror (DPLAN-0345 row 6) not landed - docs/todos_v2_shape_contract.md")
        assert failing == [], f"{failing}: {messages}"

    def test_canonical_entries_carry_over_byte_identical(self, tmp_path):
        keeper = _entry(2, tags=["a"])
        root = _branch(tmp_path, "guinea", {"sessions": [keeper, _entry(1, extra="drift")]})
        plan = tp.plan_branch("guinea", root, _config())

        tp.apply_plan(plan, FakeStore("honest"), [("global", None)])

        sessions = json.loads((root / ".trinity" / "local.json").read_text(encoding="utf-8"))["sessions"]
        assert copy.deepcopy(keeper) in sessions

    def test_the_receipt_is_stamped_by_the_push_lane(self, tmp_path):
        root = _branch(tmp_path, "guinea", {"sessions": [_entry(1, extra="drift")]})
        plan = tp.plan_branch("guinea", root, _config())

        tp.apply_plan(plan, FakeStore("honest"), [("global", None)])

        stamped = json.loads((root / ".trinity" / ".template_version.json").read_text(encoding="utf-8"))
        assert stamped["stamped_by"] == "memory push"


# =============================================================================
# THE SCOPED TAB REFRESH
# =============================================================================


class TestRefreshIsScopable:
    """One citizen's rollover must not rewrite the whole fleet's files."""

    def test_refresh_all_tabs_accepts_a_branch_list(self):
        from aipass.memory.apps.handlers.tracking import tab_renderer

        import inspect

        assert "branches" in inspect.signature(tab_renderer.refresh_all_tabs).parameters

    def test_a_scoped_refresh_only_visits_the_named_branch(self, monkeypatch):
        from aipass.memory.apps.handlers.tracking import tab_renderer

        visited = []
        tmp = Path(tempfile.gettempdir())
        registry = [{"name": "alpha", "path": str(tmp / "alpha")}, {"name": "beta", "path": str(tmp / "beta")}]
        monkeypatch.setattr(tab_renderer, "_refresh_one_file", lambda *a, **k: (visited.append(a[1]), (0, 1, []))[1])
        from aipass.memory.apps.handlers.monitor import detector

        monkeypatch.setattr(detector, "_read_registry", lambda: registry, raising=False)

        tab_renderer.refresh_all_tabs(branches=["alpha"])

        assert set(visited) == {"alpha"}

    def test_an_unscoped_refresh_still_visits_everyone(self, monkeypatch):
        """The fleet-wide behaviour is still available — for lanes that mean it."""
        from aipass.memory.apps.handlers.tracking import tab_renderer

        visited = []
        tmp = Path(tempfile.gettempdir())
        registry = [{"name": "alpha", "path": str(tmp / "alpha")}, {"name": "beta", "path": str(tmp / "beta")}]
        monkeypatch.setattr(tab_renderer, "_refresh_one_file", lambda *a, **k: (visited.append(a[1]), (0, 1, []))[1])
        from aipass.memory.apps.handlers.monitor import detector

        monkeypatch.setattr(detector, "_read_registry", lambda: registry, raising=False)

        tab_renderer.refresh_all_tabs()

        assert set(visited) == {"alpha", "beta"}

    def test_rollover_passes_the_branches_it_rolled(self):
        """Source pin: the rollover lane must not call the refresh unscoped again."""
        source = (_MEMORY_ROOT / "apps" / "modules" / "rollover.py").read_text(encoding="utf-8")
        assert "refresh_all_tabs(branches=rolled)" in source

    def test_the_orchestrator_reports_the_branch_it_rolled(self):
        """Without this field the caller cannot scope anything."""
        source = (_MEMORY_ROOT / "apps" / "handlers" / "rollover" / "orchestrator.py").read_text(encoding="utf-8")
        assert '"branch": branch_str,' in source


# =============================================================================
# THE CLI GATE
# =============================================================================


class TestTheFleetGate:
    """A fleet write needs --confirm; a dry-run and a single branch do not."""

    def test_a_bare_fleet_push_is_refused(self, monkeypatch):
        from aipass.memory.apps.modules import push as push_module

        ran = []
        monkeypatch.setattr(push_module, "_run_push", lambda *a, **k: ran.append(a))

        push_module.handle_command("push", ["--confirm-not"])
        assert ran == []

        push_module.handle_command("push", [])
        assert ran == []

    def test_a_fleet_push_without_confirm_never_reaches_the_engine(self, monkeypatch):
        from aipass.memory.apps.modules import push as push_module

        ran = []
        monkeypatch.setattr(push_module, "_run_push", lambda *a, **k: ran.append(a))

        push_module.handle_command("push", ["--branch"])  # missing value
        push_module.handle_command("push", [])  # introspection

        assert ran == []

    def test_confirm_lets_a_fleet_push_through(self, monkeypatch):
        from aipass.memory.apps.modules import push as push_module

        ran = []
        monkeypatch.setattr(push_module, "_run_push", lambda branch, dry: ran.append((branch, dry)))

        push_module.handle_command("push", ["--confirm"])

        assert ran == [(None, False)]

    def test_a_single_branch_push_does_not_need_confirm(self, monkeypatch):
        from aipass.memory.apps.modules import push as push_module

        ran = []
        monkeypatch.setattr(push_module, "_run_push", lambda branch, dry: ran.append((branch, dry)))

        push_module.handle_command("push", ["--branch", "@canary"])

        assert ran == [("@canary", False)]

    def test_a_help_flag_anywhere_beats_the_push(self, monkeypatch):
        """The lesson from `rollover push --help` performing the reset it was asked to describe."""
        from aipass.memory.apps.modules import push as push_module

        ran = []
        monkeypatch.setattr(push_module, "_run_push", lambda *a, **k: ran.append(a))

        for args in (["--help"], ["--branch", "@canary", "--help"], ["--confirm", "--help"], ["help"]):
            push_module.handle_command("push", args)

        assert ran == []

    def test_the_entry_point_no_longer_aliases_push_to_the_config_reset(self):
        """`push` fired a fleet-wide per_branch reset from a bare word. It must not again."""
        source = (_MEMORY_ROOT / "apps" / "memory.py").read_text(encoding="utf-8")
        assert 'route_command("rollover", ["push"], modules)' not in source


# =============================================================================
# TODOS GO TO THE BACKLOG FILE, NEVER TO VECTORS (DPLAN-0345)
# =============================================================================


class TestTodosMoveToTheBacklog:
    """A todo that leaves the pad lands in .backup/todo/<branch>/backlog.json as it was.

    The canonical todo is ``{number, date, task, priority?}`` with ``task``
    inside its entry_limits cap. Anything else moves with reason
    ``non-canonical``; past the pad size the oldest canonical ones move with
    reason ``overflow``. The pad is written only after the backlog append read
    back json-equal. Every pin runs on a scratch fleet under ``tmp_path``.

    Mutation notes - each pin dies against a specific wrong implementation:
    ``status`` kept in ENTRY_RULES (shape, status move), the task shortened on
    the way (over-cap), a canonical todo moved (within count), the newest
    rolled instead of the oldest (overflow), the pad written before or despite
    the read-back (mismatch), a dry run that appends (dry run), a second push
    that moves again (idempotence), a todo sent to vectors (vectors).
    """

    BRANCH = "guinea"

    @staticmethod
    def _legacy(number: int, task: str = "fix drone help") -> dict:
        """A pre-DPLAN-0345 todo: canonical then, carries status now."""
        return {"number": number, "date": "2026-09-01", "task": task, "priority": "high", "status": "open"}

    @staticmethod
    def _todo(number: int, task: str = "Check on seedgo's errors in logs") -> dict:
        return {"number": number, "date": "2026-09-15", "task": task, "priority": "medium"}

    def _backlog(self, tmp_path: Path) -> Path:
        return tmp_path / ".backup" / "todo" / self.BRANCH / "backlog.json"

    def _push(self, monkeypatch, tmp_path, root, dry_run, todos_count=10, store=None):
        monkeypatch.setattr(tp, "resolve_scope", lambda branch=None: _scope(root))
        monkeypatch.setattr(tp.config_loader, "load", lambda: _config(todos_count=todos_count))
        monkeypatch.setattr(tp, "_destinations", lambda name: [("global", None)])
        return tp.push(
            branch=self.BRANCH,
            dry_run=dry_run,
            store_client=store or FakeStore("honest"),
            backup_root=tmp_path / ".backup",
        )

    @staticmethod
    def _pad(root: Path) -> list:
        return json.loads((root / ".trinity" / "local.json").read_text(encoding="utf-8"))["todos"]

    def _records(self, tmp_path: Path) -> list:
        return json.loads(self._backlog(tmp_path).read_text(encoding="utf-8"))["entries"]

    @staticmethod
    def _same(left, right) -> bool:
        return json.dumps(left, sort_keys=True) == json.dumps(right, sort_keys=True)

    # -- the shape ---------------------------------------------------------------

    def test_the_canonical_todo_shape_has_no_status(self):
        # Read from the config now, not from a literal in trinity_push
        # (FPLAN-0593): the shape has one home and this is where the push
        # picks it up. A `status` key reappearing in memory.config.json would
        # fail here, which is the point.
        assert tp.entry_rules("todos") == {
            "required": {"number": "int", "date": "str", "task": "str"},
            "optional": {"priority": "str"},
        }
        assert tp.is_canonical("todos", self._todo(1), {"field": "task", "max_chars": 100})
        assert tp.is_canonical("todos", {"number": 1, "date": "2026-09-15", "task": "fix drone help"})
        assert not tp.is_canonical("todos", self._legacy(1))

    def test_a_todo_with_several_defects_counts_once_under_the_stated_order(self):
        cap = {"field": "task", "max_chars": 100}
        raw = [
            {"number": 1, "date": "d", "task": "x" * 150, "status": "open", "extra": 1},
            {"number": 2, "date": "d", "task": "y" * 150, "extra": 1},
            {"number": 3, "task": "z", "extra": 1},
            {"number": 4, "date": "d", "task": "w", "extra": 1},
            {"number": "5", "date": "d", "task": "v"},
            "remember the milk",
        ]
        split = tp.plan_todos(raw, cap, 10)

        assert [move["defect"] for move in split["moves"]] == [
            tp.DEFECT_STATUS,
            tp.DEFECT_OVER_CAP,
            tp.DEFECT_MISSING,
            tp.DEFECT_UNKNOWN,
            tp.DEFECT_TYPE,
            tp.DEFECT_NOT_OBJECT,
        ]
        assert split["reasons"] == {
            "status present": 1,
            "task over 100": 1,
            "missing field": 1,
            "unknown field": 1,
            "wrong type": 1,
            "not an object": 1,
        }
        # The stated order is the checked order: a string is "not an object", never "missing field".
        assert tp.DEFECT_ORDER[0] == tp.DEFECT_NOT_OBJECT
        assert list(split["reasons"]) == [
            "not an object",
            "status present",
            "task over 100",
            "missing field",
            "unknown field",
            "wrong type",
        ]
        assert split["kept"] == []

    def test_no_pin_here_reaches_the_real_backlog(self, tmp_path):
        """An earlier run of these pins wrote .backup/todo/guinea/ at the repo root; the autouse guard stops it."""
        assert todo_roll.backlog_path_for(self.BRANCH).is_relative_to(tmp_path)
        assert tp.plan_branch(self.BRANCH, tmp_path / "absent", _config())["backlog"].is_relative_to(tmp_path)

    # -- the push, for real, on a scratch fleet ------------------------------------

    def test_a_status_bearing_todo_moves_json_equal_and_the_pad_empties(self, tmp_path, monkeypatch):
        todos = [self._legacy(2, "open - 23:19 wake-back log " * 3), self._legacy(1)]
        root = _branch(tmp_path, self.BRANCH, {"todos": copy.deepcopy(todos)})

        result = self._push(monkeypatch, tmp_path, root, dry_run=False)

        assert result["success"], result["errors"]
        assert self._pad(root) == []
        records = self._records(tmp_path)
        assert [record["reason"] for record in records] == ["non-canonical", "non-canonical"]
        assert all(self._same(record["entry"], todo) for record, todo in zip(records, todos, strict=True))
        document = json.loads(self._backlog(tmp_path).read_text(encoding="utf-8"))
        assert document["document_metadata"] == {"managed_by": "memory", "branch": self.BRANCH, "high_water": 2}

    def test_an_over_cap_task_lands_in_the_backlog_unshortened(self, tmp_path, monkeypatch):
        long_task = {"number": 1, "date": "2026-09-15", "task": "t" * 101, "priority": "low"}
        root = _branch(tmp_path, self.BRANCH, {"todos": [copy.deepcopy(long_task)]})

        self._push(monkeypatch, tmp_path, root, dry_run=False)

        assert self._pad(root) == []
        [record] = self._records(tmp_path)
        assert len(record["entry"]["task"]) == 101
        assert self._same(record["entry"], long_task)

    def test_a_todo_missing_a_field_moves(self, tmp_path, monkeypatch):
        """canary's real shape on 2026-09-15: a task and nothing else."""
        root = _branch(tmp_path, self.BRANCH, {"todos": [{"task": "fix drone help"}]})

        result = self._push(monkeypatch, tmp_path, root, dry_run=False)

        assert result["branches"][0]["todo_reasons"] == {"missing field": 1}
        assert self._pad(root) == []
        assert self._records(tmp_path)[0]["entry"] == {"task": "fix drone help"}

    def test_a_todo_that_is_not_even_an_object_moves_rather_than_vanishing(self, tmp_path, monkeypatch):
        root = _branch(tmp_path, self.BRANCH, {"todos": ["remember the milk"]})

        self._push(monkeypatch, tmp_path, root, dry_run=False)

        assert self._pad(root) == []
        assert self._records(tmp_path)[0]["entry"] == "remember the milk"

    def test_canonical_todos_within_the_count_stay_byte_identical(self, tmp_path, monkeypatch):
        todos = [self._todo(3), self._todo(2), self._todo(1)]
        root = _branch(tmp_path, self.BRANCH, {"todos": copy.deepcopy(todos)})

        result = self._push(monkeypatch, tmp_path, root, dry_run=False, todos_count=3)

        assert result["branches"][0]["todos_moved"] == 0
        assert self._pad(root) == todos
        assert not self._backlog(tmp_path).exists()

    def test_canonical_overflow_rolls_the_oldest_by_number(self, tmp_path, monkeypatch):
        todos = [self._todo(5), self._todo(1), self._todo(4), self._todo(2), self._todo(3)]
        root = _branch(tmp_path, self.BRANCH, {"todos": copy.deepcopy(todos)})

        result = self._push(monkeypatch, tmp_path, root, dry_run=False, todos_count=3)

        assert [todo["number"] for todo in self._pad(root)] == [5, 4, 3]
        records = self._records(tmp_path)
        assert [(record["reason"], record["entry"]["number"]) for record in records] == [
            ("overflow", 1),
            ("overflow", 2),
        ]
        assert result["branches"][0]["todo_reasons"] == {"overflow": 2}

    def test_a_backlog_that_does_not_read_back_refuses_the_branch_and_leaves_local_json(self, tmp_path, monkeypatch):
        from aipass.memory.apps.handlers.rollover import todo_roll

        root = _branch(tmp_path, self.BRANCH, {"todos": [self._legacy(1)], "sessions": [_entry(1)]})
        before = (root / ".trinity" / "local.json").read_bytes()
        real_write = todo_roll.write_memory_file

        def tampering_write(path, document):
            altered = copy.deepcopy(document)
            altered["entries"][-1]["entry"]["task"] = "shortened"
            return real_write(path, altered)

        monkeypatch.setattr(todo_roll, "write_memory_file", tampering_write)

        result = self._push(monkeypatch, tmp_path, root, dry_run=False)

        entry = result["branches"][0]
        assert entry["refused"] is True
        assert entry["todos_moved"] == 0
        assert any("not verified" in message for message in entry["errors"])
        assert (root / ".trinity" / "local.json").read_bytes() == before
        assert not (root / ".trinity" / ".template_version.json").exists()

    def test_the_backlog_is_appended_never_overwritten(self, tmp_path, monkeypatch):
        backlog = self._backlog(tmp_path)
        backlog.parent.mkdir(parents=True)
        earlier = {"rolled": "2026-09-14T23:00:00+00:00", "reason": "overflow", "entry": self._todo(7)}
        backlog.write_text(
            json.dumps({"document_metadata": {"managed_by": "memory", "branch": self.BRANCH}, "entries": [earlier]}),
            encoding="utf-8",
        )
        root = _branch(tmp_path, self.BRANCH, {"todos": [self._legacy(1)]})

        dry = self._push(monkeypatch, tmp_path, root, dry_run=True)
        self._push(monkeypatch, tmp_path, root, dry_run=False)

        assert dry["branches"][0]["backlog_exists"] is True
        records = self._records(tmp_path)
        assert records[0] == earlier
        assert [record["entry"]["number"] for record in records] == [7, 1]

    def test_the_rendered_tab_derives_next_number_from_pad_and_backlog(self, tmp_path, monkeypatch):
        backlog = self._backlog(tmp_path)
        backlog.parent.mkdir(parents=True)
        backlog.write_text(
            json.dumps(
                {
                    "document_metadata": {"managed_by": "memory", "branch": self.BRANCH},
                    "entries": [{"rolled": "r", "reason": "overflow", "entry": self._todo(40)}],
                }
            ),
            encoding="utf-8",
        )
        root = _branch(tmp_path, self.BRANCH, {"todos": [self._legacy(12), self._todo(3)]})

        self._push(monkeypatch, tmp_path, root, dry_run=False)

        meta = json.loads((root / ".trinity" / "local.json").read_text(encoding="utf-8"))["todos_meta"]
        assert meta.startswith(
            f"⟦ pad of 10 · oldest roll to .backup/todo/{self.BRANCH}/backlog.json · task ≤100 chars"
            " · draft to 80 · next #41 ⟧ "
        )

    _TAB = (
        "⟦ pad of 10 · oldest roll to .backup/todo/guinea/backlog.json · task ≤100 chars · draft to 80"
        " · next #{} ⟧ One line of what to do."
    )

    def test_the_push_raises_high_water_to_the_pad_as_found_and_reads_it_back(self, tmp_path, monkeypatch):
        """The kept #9 reaches high_water, not only the moved #4: delete #9 later and 9 stays spent."""
        root = _branch(tmp_path, self.BRANCH, {"todos": [self._todo(9), self._legacy(4)]})

        result = self._push(monkeypatch, tmp_path, root, dry_run=False)

        assert result["success"], result["errors"]
        assert [todo["number"] for todo in self._pad(root)] == [9]
        back = todo_roll.read_backlog(self._backlog(tmp_path))
        assert [record["entry"]["number"] for record in back["entries"]] == [4]
        assert todo_roll.high_water_of(back["document"]) == 9

    def test_the_tab_the_branch_last_rendered_is_a_floor_the_push_keeps(self, tmp_path, monkeypatch):
        """A tab that said next #30, then #29 deleted by hand: the push renders #30 again, never #4."""
        local = {"todos_meta": self._TAB.format(30), "todos": [self._legacy(2), self._todo(3)]}
        root = _branch(tmp_path, self.BRANCH, local)

        self._push(monkeypatch, tmp_path, root, dry_run=False)

        meta = json.loads((root / ".trinity" / "local.json").read_text(encoding="utf-8"))["todos_meta"]
        assert "· draft to 80 · next #30 ⟧ " in meta, meta

    def test_a_frame_built_without_context_keeps_the_tab_floor(self):
        """The normalizer's door: build_frame derives the context itself and reads the old tab too."""
        before = {"todos_meta": self._TAB.format(30), "todos": [self._todo(3)], "sessions": [], "key_learnings": []}
        entries = {"todos": [self._todo(3)]}

        assert "· next #30 ⟧ " in tp.build_frame(before, "local", self.BRANCH, entries, _config())["todos_meta"]
        del before["todos_meta"]
        assert "· next #4 ⟧ " in tp.build_frame(before, "local", self.BRANCH, entries, _config())["todos_meta"]

    def test_overflow_survivors_keep_their_order_on_the_pad(self):
        """Only the oldest leave; what stays is never re-sorted - the push reshapes nothing."""
        split = tp.plan_todos([self._todo(n) for n in (3, 5, 1, 4, 2)], {"field": "task", "max_chars": 100}, 3)

        assert [todo["number"] for todo in split["kept"]] == [3, 5, 4]
        assert [move["entry"]["number"] for move in split["moves"]] == [1, 2]

    # -- the dry run and the second push ------------------------------------------

    def test_a_dry_run_writes_nothing_and_prints_the_branch_and_fleet_lines(self, tmp_path, monkeypatch):
        from aipass.memory.apps.handlers.templates import push_report

        todos = [self._legacy(2), {"task": "fix drone help"}]
        root = _branch(tmp_path, self.BRANCH, {"todos": todos})
        local_before = (root / ".trinity" / "local.json").read_bytes()
        obs_before = (root / ".trinity" / "observations.json").read_bytes()
        chars = len(json.dumps(todos, ensure_ascii=False))

        result = self._push(monkeypatch, tmp_path, root, dry_run=True)
        lines = push_report.render(result, "@guinea")

        assert (root / ".trinity" / "local.json").read_bytes() == local_before
        assert (root / ".trinity" / "observations.json").read_bytes() == obs_before
        assert not (tmp_path / ".backup").exists()
        assert f"   todos 2 seen · 2 to backlog ({chars:,} chars) · 0 stay on the pad of 10" in lines
        assert "     reasons: status present 1, missing field 1" in lines
        assert any(line.startswith("     backlog ") and "does not exist yet" in line for line in lines)
        assert f"TODOS TO BACKLOG: 2 across 1 branches, {chars:,} chars" in lines

    def test_a_second_push_after_the_migration_moves_nothing(self, tmp_path, monkeypatch):
        from aipass.memory.apps.handlers.templates import push_report

        root = _branch(tmp_path, self.BRANCH, {"todos": [self._legacy(2), self._legacy(1)]})
        self._push(monkeypatch, tmp_path, root, dry_run=False)
        after_first = self._backlog(tmp_path).read_bytes()
        sessions_after_first = json.loads((root / ".trinity" / "local.json").read_text(encoding="utf-8"))["sessions"]

        again = self._push(monkeypatch, tmp_path, root, dry_run=True)
        self._push(monkeypatch, tmp_path, root, dry_run=False)

        assert again["branches"][0]["todos_to_backlog"] == 0
        assert "TODOS TO BACKLOG: 0 across 0 branches, 0 chars" in push_report.render(again, "FLEET")
        assert self._backlog(tmp_path).read_bytes() == after_first
        sessions = json.loads((root / ".trinity" / "local.json").read_text(encoding="utf-8"))["sessions"]
        assert len(sessions) == len(sessions_after_first)

    def test_the_executed_report_counts_what_moved(self, tmp_path, monkeypatch):
        from aipass.memory.apps.handlers.templates import push_report

        root = _branch(tmp_path, self.BRANCH, {"todos": [self._legacy(1), self._todo(2)]})
        result = self._push(monkeypatch, tmp_path, root, dry_run=False)
        rendered = push_report.render(result, "@guinea")

        assert any(line.startswith("   todos 2 seen · 1 of 1 moved to backlog") for line in rendered)
        assert any(line.startswith("TODOS TO BACKLOG: 1 across 1 branches, ") for line in rendered)

    def test_a_clean_desk_and_an_emptied_one_do_not_render_the_same(self, tmp_path, monkeypatch):
        """@ai_mail, 2026-08-27: 'an empty todos[] reads as a clean desk'."""
        from aipass.memory.apps.handlers.templates import push_report

        def rendered(sub: str, todos: list) -> str:
            root = _branch(tmp_path / sub, self.BRANCH, {"todos": todos})
            plan = tp.plan_branch(self.BRANCH, root, _config(), backlog_path=tmp_path / sub / "backlog.json")
            entry = tp._dry_entry(plan)
            return "\n".join(push_report.render({"dry_run": True, "scope": 1, "errors": [], "branches": [entry]}, "@g"))

        empty = rendered("empty", [])
        clean = rendered("clean", [self._todo(1), self._todo(2)])

        assert empty != clean
        assert "todos 0 seen" in empty
        assert "todos 2 seen · 0 to backlog" in clean

    # -- what stays the same ---------------------------------------------------------

    def test_a_moved_todo_never_reaches_vectors_while_sessions_still_prune(self, tmp_path, monkeypatch):
        root = _branch(
            tmp_path,
            self.BRANCH,
            {"todos": [self._legacy(1, "do not archive me")], "sessions": [_entry(1, findings=["drift"])]},
        )
        store = FakeStore("honest")

        result = self._push(monkeypatch, tmp_path, root, dry_run=False, store=store)

        entry = result["branches"][0]
        assert entry["pruned"] == 1
        assert entry["todos_moved"] == 1
        sent = [text for call in store.store_calls for text in call["texts"]]
        assert sent and all("do not archive me" not in text for text in sent)
        assert all(meta["array_field"] == "sessions" for call in store.store_calls for meta in call["metadatas"])

    def test_the_note_names_the_backlog_and_stays_canonical(self, tmp_path, monkeypatch):
        root = _branch(tmp_path, self.BRANCH, {"todos": [self._legacy(9)], "sessions": [_entry(1)]})

        result = self._push(monkeypatch, tmp_path, root, dry_run=False)

        assert result["branches"][0]["noted"] is True
        note = json.loads((root / ".trinity" / "local.json").read_text(encoding="utf-8"))["sessions"][0]
        assert tp.is_canonical("sessions", note, {"field": "summary", "max_chars": 300})
        assert "1 todo(s) #9 moved to " in note["summary"]
        assert f"todo/{self.BRANCH}/backlog.json" in note["summary"]
        assert "nothing reshaped" in note["summary"]

    def test_the_note_drops_the_names_before_it_busts_its_own_cap(self):
        moves = [{"index": index, "number": index, "reason": "non-canonical"} for index in range(40)]
        backlog = ".backup/todo/ai_mail/backlog.json"

        note = tp.build_note(12, [], moved=moves, max_chars=300, backlog=backlog)

        assert tp.is_canonical("sessions", note, {"field": "summary", "max_chars": 300})
        assert f"40 todo(s) moved to {backlog}" in note["summary"]


# =============================================================================
# THE SHAPE COMES FROM THE CONFIG (FPLAN-0593)
# =============================================================================


class TestEntryRulesReadTheConfig:
    """ENTRY_RULES was a second copy of a contract that lives in memory.config.json.

    Three copies of one shape — here, the config, and @seedgo's trinity_groups
    — is three chances for a push to prune an entry the write gate would have
    accepted. These pin that this module now derives its split rather than
    holding one.
    """

    def test_every_section_derives_a_required_and_optional_split(self):
        for section in ("sessions", "key_learnings", "todos", "observations"):
            rules = tp.entry_rules(section)
            assert rules is not None, section
            assert set(rules) == {"required", "optional"}
            assert "number" in rules["required"] and "date" in rules["required"]

    def test_an_unknown_section_stays_unknown(self):
        assert tp.entry_rules("nope") is None
        assert tp.entry_problems("nope", {"number": 1}) == ["unknown section 'nope'"]

    def test_a_resolved_type_definition_wins_over_the_global_config(self):
        """The push hands its own caps in, so a per_branch override is honoured."""
        cap_spec = {
            "field": "task",
            "max_chars": 100,
            "fields": {
                "number": {"type": "int", "required": True},
                "date": {"type": "str", "required": True},
                "task": {"type": "str", "required": True},
                "colour": {"type": "str", "required": False},
            },
        }
        rules = tp.entry_rules("todos", cap_spec)
        assert rules is not None
        assert rules["optional"] == {"colour": "str"}
        entry = {"number": 1, "date": "2026-09-15", "task": "t", "colour": "red"}
        assert tp.entry_problems("todos", entry, cap_spec) == []
        # …and without that override the same entry is out of shape.
        assert any("colour" in p for p in tp.entry_problems("todos", entry))

    def test_the_todo_defect_walker_reads_the_same_derived_shape(self):
        cap_spec = {
            "field": "task",
            "max_chars": 100,
            "fields": {
                "number": {"type": "int", "required": True},
                "date": {"type": "str", "required": True},
                "task": {"type": "str", "required": True},
                "colour": {"type": "str", "required": False},
            },
        }
        entry = {"number": 1, "date": "2026-09-15", "task": "t", "colour": "red"}
        assert tp.todo_defect(entry, cap_spec) is None
        assert tp.todo_defect(entry, {"field": "task", "max_chars": 100}) == tp.DEFECT_UNKNOWN

    def test_the_global_fallback_is_cached_not_re_read_per_entry(self):
        """734 entries must not be 734 config reads; the push path never touches it."""
        tp._RULES_CACHE.clear()
        assert tp.entry_rules("todos") is not None
        assert set(tp._RULES_CACHE) == {"sessions", "key_learnings", "todos", "observations"}
