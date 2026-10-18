# =================== AIPass ====================
# Name: test_edit_gate_trinity_refusals.py
# Description: edit_gate's .trinity refusals: renamed fields, carried vs authored, field shapes, passport, logging
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-17
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


# An entry whose canonical field is MISSING is refused by NAME, never measured as "" (zero chars);
# only NEW or EDITED entries are refused, as @memory's entry_limits does.


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
        """`learning` where the config says `value`: 500 chars read as 0 and passed."""
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
        """The refusal is about UNREADABILITY, not length."""
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
        """A write is refused for what it AUTHORS, never for what it CARRIES."""
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        legacy = {"number": 1, "date": "2026-08-01", "learning": "x" * 500}
        Path(file_path).write_text(json.dumps({"key_learnings": [legacy]}), encoding="utf-8")

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
    """@memory's unmeasurable refusal must not render as '0/300 chars (+0)'."""

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

    The gate's own check stays beside @memory's: the union refuses more, the dedupe says it once.
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


# A write is refused for what it AUTHORS, never for what it CARRIES: carried drift is logged at
# INFO (drone @memory lint owns it). Identity is the raw entry, never its index.


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
        """The on-disk pass is universal, not todos-only."""
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
        """THE CAUTION: a drifted todo must not brick a write to another section."""
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

    With @memory's half silent, only this gate's checker can refuse, so deleting it fails these.
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

        Skip AND refuse in one call: no blanket answer satisfies it.
        """
        legacy = {"number": 1, "date": "2026-08-01", "learning": "carried"}
        fresh = {"number": 2, "date": "2026-08-30", "learning": "authored in the same shape"}

        hits = self._refused_lines(tmp_path, {"key_learnings": [legacy]}, {"key_learnings": [fresh, legacy]})

        assert len(hits) == 1, f"expected exactly the authored entry to be refused, got {hits}"
        assert hits[0].startswith("  key_learnings [0]: "), "the refusal named the carried entry's position"

    def test_a_prepend_does_not_reauthor_the_whole_file(self, tmp_path):
        """Identity is the entry text, never its index: a prepend shifts every position."""
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
    """@memory publishes unknown_field and field_over_cap; this gate renders them, never as "unmeasurable".

    The allow-list comes from @memory's fields_for, never a copy.
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
        """A capped non-canonical field is measured and rendered with its numbers."""
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
    """The passport row: size only, the numbers are @memory's.

    @spawn owns passport.json's schema, so this gate judges only file size and string size.
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
        """The refusal has to say WHICH string."""
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
    """Every memory-lane refusal is logged, not only the WARN-mode cap."""

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
