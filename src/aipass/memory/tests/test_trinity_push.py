# =================== AIPass ====================
# Name: test_trinity_push.py
# Description: Red-first pins for the trinity push — the archive-verify-prune law above all
# Version: 1.0.0
# Created: 2026-08-27
# Modified: 2026-08-27
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
from pathlib import Path

import pytest

from aipass.memory.apps.handlers.templates import trinity_push as tp


_MEMORY_ROOT = Path(__file__).resolve().parents[1]


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


def _config(max_chars: int = 300) -> dict:
    """Minimal config with the four entry types the standard names."""
    return {
        "rollover": {
            "defaults": {
                "local": {"sessions": {"count": 15, "auto_compact_cap": 3}, "key_learnings": {"count": 15}},
                "observations": {"observations": {"count": 15}},
            },
            "per_branch": {},
        },
        "entry_limits": {
            "entry_types": {
                "sessions": {"container": "sessions", "field": "summary", "max_chars": max_chars, "kind": "list"},
                "key_learnings": {"container": "key_learnings", "field": "value", "max_chars": 200, "kind": "list"},
                "todos": {"container": "todos", "field": "task", "max_chars": 150, "kind": "list"},
                "observations": {"container": "observations", "field": "note", "max_chars": 300, "kind": "list"},
            },
            "per_branch": {},
        },
    }


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

        result = tp.apply_plan(plan, HalfHonest(), [("local", "/tmp/x"), ("global", None)])

        assert result["refused"] is True
        assert result["pruned"] == 0

    def test_an_absent_vector_and_a_corrupted_one_get_DIFFERENT_reasons(self, tmp_path):
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

    def test_the_resident_list_is_explicit_not_a_glob(self):
        source = (_MEMORY_ROOT / "apps" / "handlers" / "templates" / "trinity_push.py").read_text(encoding="utf-8")
        assert 'glob("projects' not in source
        assert len(tp.RESIDENT_REGISTRIES) == 4

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
        (root / ".trinity" / "local.json.pre_v3_backup").write_text("{}", encoding="utf-8")

        plan = tp.plan_branch("messy", root, _config())

        assert "local.json.pre_v3_backup" in plan["strays"]

    def test_strays_survive_the_push(self, tmp_path):
        root = _branch(tmp_path, "messy", {"sessions": [_entry(1, extra="x")]})
        stray = root / ".trinity" / "local.json.pre_v3_backup"
        stray.write_text("{}", encoding="utf-8")
        plan = tp.plan_branch("messy", root, _config())

        tp.apply_plan(plan, FakeStore("honest"), [("global", None)])

        assert stray.is_file()


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
        assert failing == [], f"{failing}: {[c.get('message') for c in result['checks'] if c['score'] < 100]}"

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
        registry = [{"name": "alpha", "path": "/tmp/alpha"}, {"name": "beta", "path": "/tmp/beta"}]
        monkeypatch.setattr(tab_renderer, "_refresh_one_file", lambda *a, **k: (visited.append(a[1]), (0, 1, []))[1])
        from aipass.memory.apps.handlers.monitor import detector

        monkeypatch.setattr(detector, "_read_registry", lambda: registry, raising=False)

        tab_renderer.refresh_all_tabs(branches=["alpha"])

        assert set(visited) == {"alpha"}

    def test_an_unscoped_refresh_still_visits_everyone(self, monkeypatch):
        """The fleet-wide behaviour is still available — for lanes that mean it."""
        from aipass.memory.apps.handlers.tracking import tab_renderer

        visited = []
        registry = [{"name": "alpha", "path": "/tmp/alpha"}, {"name": "beta", "path": "/tmp/beta"}]
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
# THE ONE SPECIES THAT IS NEVER ARCHIVED
# =============================================================================


class TestTodosAreReportedNeverArchived:
    """A todo is OPEN WORK, and archiving open work IS losing it.

    Sessions and key_learnings and observations are RECORDS — a record in a
    vector is still a record, recallable by search whenever it is wanted.  A
    todo is a debt, and a debt only works if it resurfaces unbidden on the
    next load.  Vectorized, it never does: the agent opens a clean file, sees
    nothing owed, and silently forgets what it promised.  @spawn's three open
    todos went that way in the fleet push before anyone noticed the shape rule
    had quietly outranked the standard's own "todos NEVER roll".

    So the prune lane is closed to ``todos``: a non-canonical todo is REPORTED
    for reshape-in-place — named in the report and in the in-file note — and
    left byte-identical in the file.  Reshaping it mechanically is not on the
    table either, for the reason the module already gives about everything
    else: the canonical shape needs ``priority`` and ``status``, and a machine
    that invents someone else's priority has transformed their open work, not
    preserved it.

    Mutation notes — each pin dies against a specific wrong implementation:
    routing todos back into ``prunes`` (1, 2, 4, 6), dropping them from the
    file while still reporting them (3), counting them as clean carry-over
    (5), letting the enumeration bust the note's own cap (8), or leaving the
    report silent about them (9, 10).
    """

    @staticmethod
    def _drifted_todo(task: str = "restore the fleet") -> dict:
        """@spawn's real shape: task + added, no number/date/priority/status."""
        return {"task": task, "added": "2026-08-20"}

    def test_a_non_canonical_todo_is_reported_for_reshape_not_pruned(self, tmp_path):
        root = _branch(tmp_path, "guinea", {"todos": [self._drifted_todo()]})

        plan = tp.plan_branch("guinea", root, _config())

        assert plan["prunes"] == []
        assert len(plan["reshapes"]) == 1
        assert plan["reshapes"][0]["container"] == "todos"

    def test_a_non_canonical_session_still_prunes_in_the_very_same_file(self, tmp_path):
        """The exemption is one container wide, not a hole in the prune lane."""
        root = _branch(
            tmp_path,
            "guinea",
            {"todos": [self._drifted_todo()], "sessions": [_entry(1, findings=["drift"])]},
        )

        plan = tp.plan_branch("guinea", root, _config())

        assert [prune["container"] for prune in plan["prunes"]] == ["sessions"]
        assert [item["container"] for item in plan["reshapes"]] == ["todos"]

    def test_the_todo_is_still_in_the_file_byte_identical_after_the_push(self, tmp_path):
        todo = self._drifted_todo()
        root = _branch(tmp_path, "guinea", {"todos": [todo], "sessions": [_entry(1, findings=["drift"])]})
        plan = tp.plan_branch("guinea", root, _config())

        tp.apply_plan(plan, FakeStore("honest"), [("global", None)])

        on_disk = json.loads((root / ".trinity" / "local.json").read_text(encoding="utf-8"))
        assert on_disk["todos"] == [copy.deepcopy(todo)]

    def test_the_todo_never_reaches_the_vector_store(self, tmp_path):
        """Reported, not archived — nothing about it is sent to be embedded."""
        root = _branch(
            tmp_path,
            "guinea",
            {"todos": [self._drifted_todo("do not archive me")], "sessions": [_entry(1, findings=["drift"])]},
        )
        plan = tp.plan_branch("guinea", root, _config())
        store = FakeStore("honest")

        tp.apply_plan(plan, store, [("global", None)])

        sent = [text for call in store.store_calls for text in call["texts"]]
        assert sent, "the drifted session should still have been archived"
        assert all("do not archive me" not in text for text in sent)

    def test_a_todo_awaiting_reshape_is_not_counted_as_clean_carry_over(self, tmp_path):
        """`carried` means canonical. Counting a debt as carried hides it."""
        root = _branch(tmp_path, "guinea", {"todos": [self._drifted_todo()], "sessions": [_entry(1)]})

        plan = tp.plan_branch("guinea", root, _config())

        assert plan["carried"] == 1
        assert len(plan["reshapes"]) == 1

    def test_an_over_cap_todo_is_also_reshape_not_prune(self, tmp_path):
        """Size is the other scan group, and it prunes everything BUT todos."""
        long_todo = {
            "number": 1,
            "date": "2026-08-27",
            "task": "x" * 400,
            "priority": "high",
            "status": "open",
        }
        root = _branch(tmp_path, "guinea", {"todos": [long_todo]})

        plan = tp.plan_branch("guinea", root, _config())

        assert plan["prunes"] == []
        assert len(plan["reshapes"]) == 1
        assert "over its 150-char cap" in plan["reshapes"][0]["reason"]

    def test_a_todo_that_is_not_even_an_object_is_still_kept(self, tmp_path):
        """Unparseable open work is still open work — never quietly deleted."""
        root = _branch(tmp_path, "guinea", {"todos": ["remember the milk"]})
        plan = tp.plan_branch("guinea", root, _config())

        tp.apply_plan(plan, FakeStore("honest"), [("global", None)])

        on_disk = json.loads((root / ".trinity" / "local.json").read_text(encoding="utf-8"))
        assert on_disk["todos"] == ["remember the milk"]

    def test_a_canonical_todo_carries_over_and_is_never_reported(self, tmp_path):
        todo = {"number": 1, "date": "2026-08-27", "task": "ship it", "priority": "high", "status": "open"}
        root = _branch(tmp_path, "guinea", {"todos": [todo]})

        plan = tp.plan_branch("guinea", root, _config())

        assert plan["reshapes"] == []
        assert plan["carried"] == 1

    def test_the_note_names_the_todos_that_stayed(self):
        reshapes = [
            {"container": "todos", "index": 0, "number": 7, "reason": "missing 'priority'"},
            {"container": "todos", "index": 1, "number": None, "reason": "missing 'number'"},
        ]
        summary = tp.build_note(3, [], reshapes=reshapes, max_chars=300)["summary"]

        assert "todo" in summary
        assert "#7" in summary
        assert "[1]" in summary

    def test_the_note_drops_the_names_before_it_busts_its_own_cap(self):
        """40 named todos will not fit 300 chars; the count still must."""
        reshapes = [
            {"container": "todos", "index": index, "number": index, "reason": "missing 'priority'"}
            for index in range(40)
        ]
        cap = {"field": "summary", "max_chars": 300}

        note = tp.build_note(12, [], reshapes=reshapes, max_chars=300)

        assert tp.is_canonical("sessions", note, cap)
        assert "40 todo" in note["summary"]

    def test_the_dry_run_report_names_every_todo_awaiting_reshape(self, tmp_path):
        from aipass.memory.apps.handlers.templates import push_report

        root = _branch(tmp_path, "guinea", {"todos": [self._drifted_todo()]})
        plan = tp.plan_branch("guinea", root, _config())
        rendered = "\n".join(
            push_report.render(
                {"dry_run": True, "scope": 1, "errors": [], "branches": [tp._dry_entry(plan)]}, "@guinea"
            )
        )

        assert "reshape" in rendered.lower()
        assert "todos[0]" in rendered

    def test_the_executed_report_names_them_too(self, tmp_path):
        from aipass.memory.apps.handlers.templates import push_report

        root = _branch(tmp_path, "guinea", {"todos": [self._drifted_todo()]})
        plan = tp.plan_branch("guinea", root, _config())
        applied = tp.apply_plan(plan, FakeStore("honest"), [("global", None)])
        rendered = "\n".join(
            push_report.render({"dry_run": False, "scope": 1, "errors": [], "branches": [applied]}, "@guinea")
        )

        assert "reshape" in rendered.lower()
        assert "todos[0]" in rendered

    # -- @ai_mail's catch: silence about todos is the shape the defect wore ---

    @staticmethod
    def _canonical_todo(number: int) -> dict:
        return {"number": number, "date": "2026-08-27", "task": "ship it", "priority": "high", "status": "open"}

    def test_the_plan_counts_every_todo_it_saw_not_only_the_drifted_ones(self, tmp_path):
        root = _branch(tmp_path, "guinea", {"todos": [self._canonical_todo(1), self._drifted_todo()]})

        plan = tp.plan_branch("guinea", root, _config())

        assert plan["todos_seen"] == 2
        assert len(plan["reshapes"]) == 1

    def test_a_clean_desk_and_an_emptied_one_do_not_render_the_same(self, tmp_path):
        """@ai_mail, 2026-08-27: 'an empty todos[] reads as a clean desk'.

        That is exactly how the archived-todos defect stayed invisible for a
        morning — the branch saw a zero and had no way to tell "I owe nothing"
        from "something took what I owed". The report states the count it saw
        EVERY run, so the two answers can never render identically again.
        """
        from aipass.memory.apps.handlers.templates import push_report

        def rendered(todos):
            root = _branch(tmp_path / str(len(todos)), "guinea", {"todos": todos})
            plan = tp.plan_branch("guinea", root, _config())
            return "\n".join(
                push_report.render(
                    {"dry_run": True, "scope": 1, "errors": [], "branches": [tp._dry_entry(plan)]}, "@guinea"
                )
            )

        empty = rendered([])
        clean = rendered([self._canonical_todo(1), self._canonical_todo(2)])

        assert empty != clean
        assert "todos 0" in empty
        assert "todos 2" in clean

    def test_the_executed_report_states_the_count_with_nothing_to_reshape(self, tmp_path):
        """Nothing to reshape is a MEASUREMENT, and it has to be spoken."""
        from aipass.memory.apps.handlers.templates import push_report

        contents = {"todos": [self._canonical_todo(1)], "sessions": [_entry(1, findings=["d"])]}
        root = _branch(tmp_path, "guinea", contents)
        plan = tp.plan_branch("guinea", root, _config())
        applied = tp.apply_plan(plan, FakeStore("honest"), [("global", None)])
        rendered = "\n".join(
            push_report.render({"dry_run": False, "scope": 1, "errors": [], "branches": [applied]}, "@guinea")
        )

        assert "todos 1" in rendered
        assert "0 left to reshape" in rendered

    def test_the_written_note_fits_the_branchs_own_cap_end_to_end(self, tmp_path):
        """The cap must reach build_note through apply_plan, not just in unit calls.

        Written after a surviving mutation: cutting the resolved cap on the
        wire (``build_note(..., None)``) left every direct-call pin green,
        because they hand build_note a cap themselves. The damage only shows
        end to end — an un-stepped-down enumeration busts 300 chars, the
        canonical-note guard refuses it, and the branch is told NOTHING about
        entries that really did move. A note refused is a promise unkept.
        """
        todos = [self._drifted_todo(f"task {index}") for index in range(30)]
        root = _branch(tmp_path, "guinea", {"todos": todos, "sessions": [_entry(1, findings=["drift"])]})
        plan = tp.plan_branch("guinea", root, _config())

        result = tp.apply_plan(plan, FakeStore("honest"), [("global", None)])

        assert result["noted"] is True, result["errors"]
        written = json.loads((root / ".trinity" / "local.json").read_text(encoding="utf-8"))["sessions"][0]
        assert tp.is_canonical("sessions", written, {"field": "summary", "max_chars": 300})
        assert "30 todo" in written["summary"]
