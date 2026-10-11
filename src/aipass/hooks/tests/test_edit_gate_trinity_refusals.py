# =================== AIPass ====================
# Name: test_edit_gate_trinity_refusals.py
# Description: edit_gate's .trinity refusals: renamed fields, carried vs authored, field shapes, passport, logging
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-08
# =============================================

"""Tests for apps/handlers/security/edit_gate.py: what a .trinity refusal names, and what it carries."""

# The caps on Write and Edit are test_edit_gate_trinity_write.py and
# test_edit_gate_trinity_edit.py; the advisories and budgets are test_edit_gate_trinity.py.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that edit_gate.py parses and its imports resolve
# seedgo: no-test-needed(stdlib) — json.loads' parsing of the proposed content; the gate's reading of it is pinned

import json
import logging
from pathlib import Path

from aipass.hooks.apps.handlers.security.edit_gate import handle
from aipass.hooks.tests.support_edit_gate_trinity import (
    _TEST_LIMITS_ENFORCE,
    _TEST_LIMITS_WARN,
    _fence_real,
    _hook_data,
    _imports_via_seam,
    _make_trinity_path,
    _mock_entry_limits,
    _mock_importlib_modules,
)


# ---------------------------------------------------------------------------
# B3 — the renamed-field dodge (DPLAN-0318 trinity standard, MASTER_LIST §2)
# ---------------------------------------------------------------------------
#
# The cap check reads ONE canonical field name per entry type, taken from
# @memory's memory.config.json entry_limits (file/container/field). When a
# branch renamed that field — `learning` instead of `value` in ai_mail, api and
# this branch — the extractor found no such key, answered "" and the entry
# measured as ZERO characters. Three branches ran 2.7x over cap for the two
# months AFTER the gate landed, and the gate reported compliance every time.
#
# `""` and "cannot read this" are different answers and must stay different.
# An entry whose canonical field is MISSING is refused by NAME, never measured
# as empty. The asymmetry mirrors @memory's entry_limits 1.3.0: only NEW or
# EDITED entries are refused. Nine-plus branches carry legacy shapes until the
# fleet reset wipes them, and bricking every memory write fleet-wide tonight
# would cost more than the drift does.


_LIMITS_LIST_ENFORCE = {
    "enabled": True,
    "enforce": True,
    "entry_types": {
        "key_learnings": {
            "file": "local.json",
            "container": "key_learnings",
            "kind": "list",
            "field": "value",
            "max_chars": 200,
        },
        "sessions": {
            "file": "local.json",
            "container": "sessions",
            "kind": "list",
            "field": "summary",
            "max_chars": 300,
        },
    },
}

_LIMITS_LIST_WARN = {**_LIMITS_LIST_ENFORCE, "enforce": False}


class TestRenamedFieldDodge:
    """An entry whose canonical field was renamed must not measure as empty."""

    def test_renamed_field_over_cap_is_blocked(self, tmp_path):
        """`learning` where the config says `value`: 500 chars read as 0 and passed.

        This is B3 exactly as it shipped — the species this branch's own
        local.json carries.
        """
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"key_learnings": [{"number": 1, "date": "2026-08-25", "learning": "x" * 500}]})

        with _imports_via_seam(_fence_real(_mock_entry_limits(_LIMITS_LIST_ENFORCE))):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 2, "renamed field dodged the cap"
        parsed = json.loads(result["stdout"])
        assert parsed["decision"] == "block"
        assert "key_learnings" in parsed["reason"]
        assert "value" in parsed["reason"], "refusal must name the field it could not find"

    def test_missing_field_is_blocked(self, tmp_path):
        """Canonical field absent with no replacement at all — same refusal."""
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"sessions": [{"number": 9, "date": "2026-08-25"}]})

        with _imports_via_seam(_fence_real(_mock_entry_limits(_LIMITS_LIST_ENFORCE))):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 2, "missing field dodged the cap"
        parsed = json.loads(result["stdout"])
        assert "summary" in parsed["reason"]

    def test_renamed_field_under_cap_is_still_blocked(self, tmp_path):
        """The refusal is about UNREADABILITY, not length.

        A short renamed field is still a field the gate cannot measure, and
        letting it through because it happens to be small is how the shape
        spreads.
        """
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"key_learnings": [{"number": 1, "learning": "short"}]})

        with _imports_via_seam(_fence_real(_mock_entry_limits(_LIMITS_LIST_ENFORCE))):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 2

    def test_canonical_field_still_passes(self, tmp_path):
        """Guard against over-refusal: the correct shape must stay allowed."""
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"key_learnings": [{"number": 1, "date": "2026-08-25", "value": "fine"}]})

        with _imports_via_seam(_fence_real(_mock_entry_limits(_LIMITS_LIST_ENFORCE))):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 0

    def test_empty_string_is_not_a_missing_field(self, tmp_path):
        """`""` means there is no text — compliant. Only an ABSENT key refuses."""
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"key_learnings": [{"number": 1, "value": ""}]})

        with _imports_via_seam(_fence_real(_mock_entry_limits(_LIMITS_LIST_ENFORCE))):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 0


class TestRenamedFieldLegacyAsymmetry:
    """Only NEW or EDITED entries are refused — untouched legacy shapes pass."""

    def test_untouched_legacy_entry_is_carried_not_refused(self, tmp_path):
        """REVERSED BACK (2026-08-30) — and the round trip is the record.

        Written the night B3 landed, flipped on 08-27 because the push had cured
        the fleet (22/22), flipped back now because @memory measured that drift
        RECURS and that refusing carried debt deadlocks their rollover. The
        08-27 premise was a temporary state treated as permanent. A write is
        refused for what it AUTHORS, never for what it CARRIES — the NEW
        canonical entry on top is judged; the untouched legacy one is not.
        """
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        legacy = {"number": 1, "date": "2026-08-01", "learning": "x" * 500}
        Path(file_path).write_text(json.dumps({"key_learnings": [legacy]}), encoding="utf-8")

        # Same legacy entry, plus a NEW canonical one on top.
        content = json.dumps({"key_learnings": [{"number": 2, "date": "2026-08-25", "value": "new and legal"}, legacy]})

        with _imports_via_seam(_fence_real(_mock_entry_limits(_LIMITS_LIST_ENFORCE))):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 0, "a write was refused for a drifted entry it did not author"

    def test_editing_a_legacy_entry_refuses_it(self, tmp_path):
        """Touch the drifted entry and you own its shape."""
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        legacy = {"number": 1, "date": "2026-08-01", "learning": "x" * 500}
        Path(file_path).write_text(json.dumps({"key_learnings": [legacy]}), encoding="utf-8")

        edited = json.dumps({"key_learnings": [{"number": 1, "date": "2026-08-01", "learning": "y" * 500}]})

        with _imports_via_seam(_fence_real(_mock_entry_limits(_LIMITS_LIST_ENFORCE))):
            result = handle(_hook_data(file_path, edited, cwd=cwd))

        assert result["exit_code"] == 2, "an edited legacy entry kept its exemption"

    def test_new_legacy_shaped_entry_is_refused(self, tmp_path):
        """Carrying one legacy entry must not license adding ten more."""
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        legacy = {"number": 1, "date": "2026-08-01", "learning": "x" * 500}
        Path(file_path).write_text(json.dumps({"key_learnings": [legacy]}), encoding="utf-8")

        content = json.dumps({"key_learnings": [{"number": 2, "date": "2026-08-25", "learning": "z" * 500}, legacy]})

        with _imports_via_seam(_fence_real(_mock_entry_limits(_LIMITS_LIST_ENFORCE))):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 2, "a NEW entry in the legacy shape inherited the exemption"


class TestUnreadableFieldWarnMode:
    """enforce=False keeps the refusal advisory, and says why in the log."""

    def test_warn_mode_allows_but_logs_field_name(self, tmp_path, caplog):
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"key_learnings": [{"number": 1, "learning": "x" * 500}]})

        with caplog.at_level(logging.WARNING):
            with _imports_via_seam(_fence_real(_mock_entry_limits(_LIMITS_LIST_WARN))):
                result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 0
        assert "value" in caplog.text


class TestUnmeasurableReasonIsRendered:
    """@memory's unmeasurable refusal must not render as '0/300 chars (+0)'.

    A refusal that prints zeros reads like a bug in the gate. The reason it
    carries is the whole point of refusing loudly.
    """

    def test_non_string_field_reason_reaches_the_agent(self, tmp_path):
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"sessions": [{"number": 1, "summary": [{"title": "a", "detail": "b"}]}]})

        with _imports_via_seam(_fence_real(_mock_entry_limits(_LIMITS_LIST_ENFORCE))):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 2
        reason = json.loads(result["stdout"])["reason"]
        assert "list" in reason, "refusal did not say what it found"
        assert "0/300 chars (+0)" not in reason, "refusal rendered as a zero-length measurement"


class TestNoDuplicateViolationLines:
    """One defect, one line — even when two checkers both find it.

    @memory's entry_limits 1.4.0 closed the missing-field hole in their
    extractor on the same night this gate grew its own check, so both now
    report the same entry. Two identical lines in a refusal read as two
    problems and cost the agent a hunt for the second one.

    The independent check is KEPT rather than deleted. A gate that outsources
    all of its measurement inherits its supplier's blind spots silently — which
    is exactly how this bug survived two months. The union is the safe
    direction for a gate (strictly more refusals, never fewer); the dedupe just
    stops it being said twice.
    """

    def test_missing_field_reported_once(self, tmp_path):
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"key_learnings": [{"number": 1, "learning": "x" * 500}]})

        with _imports_via_seam(_fence_real(_mock_entry_limits(_LIMITS_LIST_ENFORCE))):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 2
        reason = json.loads(result["stdout"])["reason"]
        assert reason.count("no 'value' field") == 1, f"violation reported {reason.count(chr(39) + 'value' + chr(39))}x"

    def test_distinct_entries_both_survive_dedupe(self, tmp_path):
        """Dedupe must key on container too — two types can share key '0'."""
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps(
            {
                "key_learnings": [{"number": 1, "learning": "x" * 500}],
                "sessions": [{"number": 1, "chronicle": "y" * 500}],
            }
        )

        with _imports_via_seam(_fence_real(_mock_entry_limits(_LIMITS_LIST_ENFORCE))):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        reason = json.loads(result["stdout"])["reason"]
        assert "no 'value' field" in reason
        assert "no 'summary' field" in reason, "dedupe swallowed a distinct container's violation"

    def test_over_cap_and_missing_field_both_reported(self, tmp_path):
        """Different species on different entries must both reach the agent."""
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"key_learnings": [{"number": 2, "value": "x" * 201}, {"number": 1, "learning": "short"}]})

        with _imports_via_seam(_fence_real(_mock_entry_limits(_LIMITS_LIST_ENFORCE))):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        reason = json.loads(result["stdout"])["reason"]
        assert "201/200" in reason
        assert "no 'value' field" in reason


# ---------------------------------------------------------------------------
# Authored vs carried — the on-disk pass is universal (2026-08-30)
# ---------------------------------------------------------------------------
#
# I narrowed the exemption to todos on 08-27 on two beliefs: the fleet had
# converged, so the clause protected nothing real; and "unchanged and over cap
# passes" hid new drift. @memory disproved both from the outside — their
# rollover lane failed identically every 20 minutes for three hours because the
# extractor removed a tail, wrote the SMALLER document back, and a write gate
# refused the whole file over an entry in the head it never touched. The
# archiver is always on the losing side of that trade: the file cannot get
# smaller because it is too big.
#
# So the rule is @memory's, and it is universal: a write is refused for what it
# AUTHORS, never for what it CARRIES. My own refusal text is the other half of
# the evidence — writes made through Bash are not checked, so a write gate is
# structurally blind to how drift ARRIVES and was never the thing that could
# detect it. That job is drone @memory lint, which reads the file.
#
# Carried drift is REPORTED at INFO, never refused. Identity is the raw entry,
# never its index: a prepend shifts every position down, and an index-keyed
# diff would call the whole file newly authored on exactly the write that
# authored nothing.


_LIMITS_TODOS = {
    "enabled": True,
    "enforce": True,
    "entry_types": {
        "key_learnings": {
            "file": "local.json",
            "container": "key_learnings",
            "kind": "list",
            "field": "value",
            "max_chars": 200,
        },
        "todos": {
            "file": "local.json",
            "container": "todos",
            "kind": "list",
            "field": "task",
            "max_chars": 150,
        },
    },
}


def _write_before(file_path, payload):
    Path(file_path).write_text(json.dumps(payload), encoding="utf-8")


class TestCarriedDriftIsNotRefused:
    """Untouched drift is CARRIED everywhere — reported, never refused."""

    def test_untouched_drifted_key_learning_is_carried_not_refused(self, tmp_path):
        """REVERSED BACK (2026-08-30): the on-disk pass is universal, not todos-only.

        "Unchanged" means this write did not author it — the only thing a write
        gate can honestly judge. Reading whole files for drift already on disk
        is drone @memory lint's job, and it is the only component that can
        actually see drift that arrived through Bash.
        """
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        legacy = {"number": 1, "date": "2026-08-01", "learning": "x" * 500}
        _write_before(file_path, {"key_learnings": [legacy], "todos": []})

        content = json.dumps(
            {"key_learnings": [{"number": 2, "date": "2026-08-27", "value": "clean"}, legacy], "todos": []}
        )

        with _imports_via_seam(_fence_real(_mock_entry_limits(_LIMITS_TODOS))):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 0, "a write was refused for a drifted entry it did not author"
        assert result["stdout"] == "", "carried drift must be reported in the log, never in a block"

    def test_untouched_drifted_todo_still_passes(self, tmp_path):
        """THE CAUTION: a drifted todo must not brick a write to another section.

        67 todos were restored by mail after the push defect and owners
        reshape them on their own schedule. Blocking every write until they do
        would make the exemption brick the branch it protects.
        """
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        drifted_todo = {"priority": "medium", "status": "open", "chore": "reshape me"}
        _write_before(file_path, {"key_learnings": [], "todos": [drifted_todo]})

        content = json.dumps(
            {
                "key_learnings": [{"number": 1, "date": "2026-08-27", "value": "a clean new learning"}],
                "todos": [drifted_todo],
            }
        )

        with _imports_via_seam(_fence_real(_mock_entry_limits(_LIMITS_TODOS))):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 0, "a drifted todo blocked a write to a different section"

    def test_new_drifted_todo_still_refused(self, tmp_path):
        """The exemption covers what is ALREADY ON DISK, never a fresh one."""
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        drifted_todo = {"priority": "medium", "status": "open", "chore": "reshape me"}
        _write_before(file_path, {"todos": [drifted_todo]})

        content = json.dumps({"todos": [{"priority": "low", "status": "open", "chore": "brand new"}, drifted_todo]})

        with _imports_via_seam(_fence_real(_mock_entry_limits(_LIMITS_TODOS))):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 2, "a NEW drifted todo inherited the on-disk exemption"

    def test_editing_a_drifted_todo_refuses_it(self, tmp_path):
        """Touch it and you own its shape — same rule as everywhere else."""
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        _write_before(file_path, {"todos": [{"priority": "medium", "status": "open", "chore": "old text"}]})

        content = json.dumps({"todos": [{"priority": "medium", "status": "open", "chore": "new text"}]})

        with _imports_via_seam(_fence_real(_mock_entry_limits(_LIMITS_TODOS))):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 2, "an edited drifted todo kept its exemption"


class TestAuthoredVsCarriedUnit:
    """The authored half alone: @memory's changed_entries answers nothing here.

    Mutation found the gap (2026-08-30): making _missing_field_violations
    return NOTHING left all 115 end-to-end tests green. The union in
    _evaluate_limits adds @memory's real changed_entries, which refuses a new
    missing-field entry through its own lane — so every through-handle() test
    that proves "authored drift is refused" passes for the wrong reason and
    would keep passing if this checker were deleted outright. The overlap is
    deliberate; a test suite that cannot tell the two halves apart is not.
    These go through handle() with @memory's half (another branch, the edge)
    standing in silent, so only this gate's own checker can refuse (fleet green leg 9).
    """

    @staticmethod
    def _refused_lines(tmp_path, before: dict, after: dict) -> list[str]:
        """The missing-field lines of handle()'s refusal for writing `after` over `before`; [] when allowed."""
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        _write_before(file_path, before)
        memory_half = _mock_entry_limits(_LIMITS_TODOS)
        memory_half.changed_entries = lambda *args, **kwargs: []
        with _imports_via_seam(_fence_real(memory_half)):
            result = handle(_hook_data(file_path, json.dumps(after), cwd=str(tmp_path / "src" / "aipass" / "hooks")))
        if result == {"stdout": "", "exit_code": 0}:
            return []
        assert result["exit_code"] == 2
        reason = json.loads(result["stdout"])["reason"]
        return [line for line in reason.splitlines() if "field —" in line]

    def test_a_new_missing_field_entry_is_refused(self, tmp_path):
        """The authored half, isolated from @memory's overlapping refusal."""
        before = {"key_learnings": []}
        after = {"key_learnings": [{"number": 1, "date": "2026-08-30", "learning": "renamed field"}]}

        hits = self._refused_lines(tmp_path, before, after)

        # The key renders as "0", a string: @memory's six-key contract.
        assert hits == [
            "  key_learnings [0]: no 'value' field — cannot be measured against its 200-char cap. "
            "Rename the field to 'value' (the canonical name)."
        ], "a newly authored entry with no 'value' field was not refused"

    def test_an_identical_on_disk_entry_is_carried(self, tmp_path):
        """Byte-identical to disk: this write did not author it."""
        legacy = {"number": 1, "date": "2026-08-01", "learning": "renamed field"}

        hits = self._refused_lines(tmp_path, {"key_learnings": [legacy]}, {"key_learnings": [legacy]})

        assert hits == [], "a write was refused for an entry it carried unchanged"

    def test_carrying_one_does_not_license_authoring_another(self, tmp_path):
        """The mixed case names the new entry and only the new entry.

        This is the test the two survivors could not have been caught without:
        it needs the checker to both skip AND refuse in the same call, so no
        blanket answer — refuse everything, refuse nothing — satisfies it.
        """
        legacy = {"number": 1, "date": "2026-08-01", "learning": "carried"}
        fresh = {"number": 2, "date": "2026-08-30", "learning": "authored in the same shape"}

        hits = self._refused_lines(tmp_path, {"key_learnings": [legacy]}, {"key_learnings": [fresh, legacy]})

        assert len(hits) == 1, f"expected exactly the authored entry to be refused, got {hits}"
        assert hits[0].startswith("  key_learnings [0]: "), "the refusal named the carried entry's position"

    def test_a_prepend_does_not_reauthor_the_whole_file(self, tmp_path):
        """Identity is the entry text, never its index.

        A prepend shifts every position down. An index-keyed diff reads the
        entire file as newly authored on exactly the write that authored
        nothing new below the head.
        """
        carried = [
            {"number": 1, "date": "2026-08-01", "learning": "a"},
            {"number": 2, "date": "2026-08-02", "learning": "b"},
        ]
        clean_head = {"number": 3, "date": "2026-08-30", "value": "measurable"}

        hits = self._refused_lines(tmp_path, {"key_learnings": carried}, {"key_learnings": [clean_head, *carried]})

        assert hits == [], f"a prepend re-authored entries it only shifted: {hits}"


_TEST_LIMITS_FIELDS = {
    "enabled": True,
    "enforce": True,
    "entry_types": {
        "sessions": {
            "file": "local.json",
            "container": "sessions",
            "kind": "list",
            "field": "summary",
            "max_chars": 300,
            "fields": {
                "number": {"type": "int", "required": True},
                "date": {"type": "str", "required": True, "max_chars": 10},
                "summary": {"type": "str", "required": True, "max_chars": 300},
                "status": {"type": "str", "required": True, "max_chars": 40},
                "tags": {"type": "list[str]", "required": False, "max_items": 10, "max_chars": 120},
            },
        },
    },
}


def _session(**over):
    entry = {"number": 1, "date": "2026-09-15", "summary": "a session", "status": "completed", "tags": ["one"]}
    entry.update(over)
    return entry


class TestMemorysNewRefusalReasonsRender:
    """FPLAN-0593 row 6: @memory 1.11.0 publishes unknown_field and field_over_cap; this gate renders them.

    Both arrive in the same six-key shape as the canonical cap, plus `field` and
    `units`. The catch-all that used to swallow every reason called them
    "unmeasurable — expected a string", which is the opposite of what happened:
    a 917-char status was measured exactly, and a field outside the shape was
    never a measurement at all. The closed shape is @memory's to publish and
    this gate's to render — the allow-list comes from fields_for, never a copy.
    """

    def _refuse(self, tmp_path, entry):
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"sessions": [entry]})
        with _imports_via_seam(_mock_importlib_modules(_TEST_LIMITS_FIELDS)):
            return handle(_hook_data(file_path, content, cwd=cwd))

    def test_an_unknown_field_names_the_shape_it_broke(self, tmp_path):
        result = self._refuse(tmp_path, _session(mood="great"))

        assert result["exit_code"] == 2
        reason = json.loads(result["stdout"])["reason"]
        assert "field 'mood' is not part of the entry shape" in reason
        assert "allowed: number, date, summary, status, tags" in reason
        assert "unmeasurable" not in reason, "an unknown field was never a measurement"

    def test_a_field_over_its_cap_is_rendered_with_its_numbers(self, tmp_path):
        """devpulse's 917-char status is the entry this shape exists for (S464 in a field nobody capped)."""
        result = self._refuse(tmp_path, _session(status="s" * 917))

        reason = json.loads(result["stdout"])["reason"]
        assert "'status' is 917/40 chars (+877 over)" in reason

    def test_a_list_over_its_item_count_says_items_not_chars(self, tmp_path):
        result = self._refuse(tmp_path, _session(tags=[f"t{n}" for n in range(11)]))

        reason = json.loads(result["stdout"])["reason"]
        assert "'tags' is 11/10 items (+1 over)" in reason

    def test_a_legal_entry_still_writes(self, tmp_path):
        assert self._refuse(tmp_path, _session()) == {"stdout": "", "exit_code": 0}


class TestPassportFileBudget:
    """FPLAN-0593 row 6, the passport row: size only, the numbers are @memory's.

    @spawn owns passport.json's schema, so this gate never judges its fields —
    only how big the file is (6,000) and whether any one string is oversized
    (600). Until today a passport was the one .trinity file any lane could write
    at any size, and the identity block renders from it on every cadence beat.
    """

    def _write(self, tmp_path, doc, limits=_TEST_LIMITS_ENFORCE):
        file_path = _make_trinity_path(tmp_path, "hooks", "passport.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        with _imports_via_seam(_mock_importlib_modules(limits)):
            return handle(_hook_data(file_path, json.dumps(doc), cwd=cwd))

    def test_a_passport_over_its_file_budget_is_refused(self, tmp_path):
        result = self._write(tmp_path, {"identity": {"purpose": "p" * 7000}})

        assert result["exit_code"] == 2
        reason = json.loads(result["stdout"])["reason"]
        assert "passport.json: the whole file is" in reason
        assert "/6000 chars" in reason

    def test_one_oversized_string_is_named_by_its_path(self, tmp_path):
        """aipass carries identity.purpose at 869 today; the refusal has to say WHICH string."""
        result = self._write(tmp_path, {"identity": {"purpose": "p" * 700, "role": "r"}})

        reason = json.loads(result["stdout"])["reason"]
        assert "'identity.purpose' is 700/600 chars (+100 over)" in reason
        assert "the whole file is" not in reason, "a 700-char string is not a 6,000-char file"

    def test_a_passport_inside_its_budget_writes(self, tmp_path):
        assert self._write(tmp_path, {"identity": {"role": "hook_infrastructure"}}) == {"stdout": "", "exit_code": 0}

    def test_warn_mode_allows_and_logs(self, tmp_path, caplog):
        result = self._write(tmp_path, {"identity": {"purpose": "p" * 7000}}, limits=_TEST_LIMITS_WARN)

        assert result == {"stdout": "", "exit_code": 0}
        assert "file_over_budget" in caplog.text


class TestTrinityRefusalsAreLogged:
    """The memory-lane refusals that blocked silently until 2026-09-22.

    The cap refusal only logged in WARN mode — the branch that returns the block
    skipped _log_violation entirely — and newest-first and the unparseable guard
    never logged at all. Measured from a live block on 2026-09-22 04:37:29 that
    left no line in edit_gate.log.
    """

    def test_enforced_cap_refusal_is_logged(self, tmp_path, caplog):
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"sessions": [{"summary": "k" * 301}]})
        with _imports_via_seam(_fence_real(_mock_entry_limits(_TEST_LIMITS_ENFORCE))):
            result = handle(_hook_data(file_path, content, cwd=cwd))
        assert result["exit_code"] == 2
        assert "refused" in caplog.text
        assert "Unwritable .trinity entries" in caplog.text

    def test_newest_first_refusal_is_logged(self, tmp_path, caplog):
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        Path(file_path).write_text(json.dumps({"sessions": [{"number": 5, "summary": "old"}]}), encoding="utf-8")
        after = {"sessions": [{"number": 5, "summary": "old"}, {"number": 6, "summary": "new"}]}
        with _imports_via_seam(_fence_real(_mock_entry_limits(_TEST_LIMITS_WARN))):
            result = handle(_hook_data(file_path, json.dumps(after), cwd=cwd))
        assert result["exit_code"] == 2
        assert "refused" in caplog.text
        assert "newest-first" in caplog.text

    def test_unparseable_refusal_is_logged(self, tmp_path, caplog):
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        Path(file_path).write_text(json.dumps({"sessions": []}), encoding="utf-8")
        with _imports_via_seam(_fence_real(_mock_entry_limits(_TEST_LIMITS_WARN))):
            result = handle(_hook_data(file_path, "{not json", cwd=cwd))
        assert result["exit_code"] == 2
        assert "refused" in caplog.text
        assert "unparseable" in caplog.text
