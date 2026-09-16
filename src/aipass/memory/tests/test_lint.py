# ===================AIPASS====================
# META DATA HEADER
# Name: tests/test_lint.py
# Date: 2026-06-13
# Version: 1.0.0
# Category: memory/tests
# =============================================

"""
Tests for Phase 2 of FPLAN-0270: check_entry validator + lint handler.

Covers:
  - check_entry boundary checks (at-cap, cap+1, larger over)
  - Character-not-byte counting (em-dash, tree glyphs)
  - Unknown entry_type handling
  - Dict container measurement (plain string + dict-with-field)
  - List container measurement + missing-field refusal
  - Lint handler finds violations with correct counts
  - Lint handler is read-only (files unchanged after scan)
"""

import importlib
import json
import sys
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Helpers: fresh-import modules under test with mocks already in place
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _fresh_lint_modules(monkeypatch):
    """Drop cached modules so each test gets a fresh import.

    Evicted with ``monkeypatch.delitem``, not a bare ``sys.modules.pop``: a
    bare pop is one-way and the eviction outlives the test, which is how two
    receipt tests went red on a single xdist worker on a single run.
    """
    for name in (
        "aipass.memory.apps.handlers.json",
        "aipass.memory.apps.handlers.json.json_handler",
        "aipass.memory.apps.handlers.json.entry_limits",
        "aipass.memory.apps.handlers.json.lint_handler",
        "aipass.memory.apps.modules.lint",
    ):
        monkeypatch.delitem(sys.modules, name, raising=False)
    yield


def _get_entry_limits():
    """Import and return the entry_limits module."""
    return importlib.import_module("aipass.memory.apps.handlers.json.entry_limits")


def _get_lint_handler():
    """Import and return the lint_handler module."""
    return importlib.import_module("aipass.memory.apps.handlers.json.lint_handler")


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_limits(entry_types: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build a limits dict matching the shape returned by load_entry_limits."""
    if entry_types is None:
        entry_types = {
            "key_learnings": {
                "file": "local.json",
                "container": "key_learnings",
                "kind": "dict",
                "field": "value",
                "max_chars": 10,
            },
        }
    return {"enabled": True, "enforce": False, "entry_types": entry_types}


# ===========================================================================
# 1. check_entry tests
# ===========================================================================


class TestCheckEntryAtCap:
    """length == cap is OK (not over)."""

    def test_at_cap_is_ok(self) -> None:
        mod = _get_entry_limits()
        limits = _make_limits()
        text = "a" * 10  # exactly at cap

        result = mod.check_entry("key_learnings", text, limits)

        assert result["ok"] is True
        assert result["length"] == 10
        assert result["cap"] == 10
        assert result["over_by"] == 0
        assert result["entry_type"] == "key_learnings"


class TestCheckEntryCapPlusOne:
    """length == cap+1 is OVER."""

    def test_cap_plus_one_is_over(self) -> None:
        mod = _get_entry_limits()
        limits = _make_limits()
        text = "a" * 11  # one over cap

        result = mod.check_entry("key_learnings", text, limits)

        assert result["ok"] is False
        assert result["length"] == 11
        assert result["cap"] == 10
        assert result["over_by"] == 1


class TestCheckEntryLargerOver:
    """over_by calculation correct for strings well over cap."""

    def test_over_by_large(self) -> None:
        mod = _get_entry_limits()
        limits = _make_limits()
        text = "a" * 25  # 15 over cap of 10

        result = mod.check_entry("key_learnings", text, limits)

        assert result["ok"] is False
        assert result["length"] == 25
        assert result["over_by"] == 15


class TestCheckEntryCharNotByte:
    """Em-dash is 3 bytes UTF-8 but 1 character -- count chars not bytes."""

    def test_em_dash_counts_as_one_char(self) -> None:
        mod = _get_entry_limits()
        # "a—b" is 3 characters, not 5 bytes
        text = "a—b"
        assert len(text) == 3
        assert len(text.encode("utf-8")) == 5  # prove multi-byte

        limits = _make_limits()
        result = mod.check_entry("key_learnings", text, limits)

        assert result["length"] == 3  # chars, not bytes
        assert result["ok"] is True

    def test_tree_glyph_counts_as_one_char(self) -> None:
        mod = _get_entry_limits()
        # tree glyph is multi-byte UTF-8 but one character
        text = "a└b"
        assert len(text) == 3
        assert len(text.encode("utf-8")) == 5

        limits = _make_limits()
        result = mod.check_entry("key_learnings", text, limits)

        assert result["length"] == 3


class TestCheckEntryUnknownType:
    """Unknown entry_type returns ok=True, cap=0."""

    def test_unknown_type_always_ok(self) -> None:
        mod = _get_entry_limits()
        limits = _make_limits()

        result = mod.check_entry("nonexistent_type", "any text", limits)

        assert result["ok"] is True
        assert result["cap"] == 0
        assert result["over_by"] == 0
        assert result["entry_type"] == "nonexistent_type"
        assert result["length"] == len("any text")


# ===========================================================================
# 2. Container handling tests
# ===========================================================================


class TestDictContainerStringValue:
    """Dict container where value is a plain string (key_learnings style)."""

    def test_dict_string_value_measured(self, tmp_path: Path) -> None:
        handler = _get_lint_handler()

        # Build a branch with a dict container whose values are plain strings
        trinity = tmp_path / "branch" / ".trinity"
        trinity.mkdir(parents=True)
        local_data = {
            "key_learnings": {
                "learn1": "short",  # 5 chars, under cap of 10
                "learn2": "this is way too long for the cap",  # over
            },
        }
        (trinity / "local.json").write_text(json.dumps(local_data), encoding="utf-8")

        limits = _make_limits()
        violations = handler._lint_branch("test", str(tmp_path / "branch"), limits)

        assert len(violations) == 1
        assert violations[0]["key"] == "learn2"
        assert violations[0]["container"] == "key_learnings"


class TestDictContainerDictValue:
    """Dict container where value is a dict with a field key."""

    def test_dict_with_field_measured(self, tmp_path: Path) -> None:
        handler = _get_lint_handler()

        trinity = tmp_path / "branch" / ".trinity"
        trinity.mkdir(parents=True)
        local_data = {
            "key_learnings": {
                "learn1": {"value": "ok", "meta": "x"},  # 2 chars
                "learn2": {"value": "this exceeds the limit!!", "meta": "y"},  # over
            },
        }
        (trinity / "local.json").write_text(json.dumps(local_data), encoding="utf-8")

        limits = _make_limits(
            {
                "key_learnings": {
                    "file": "local.json",
                    "container": "key_learnings",
                    "kind": "dict",
                    "field": "value",
                    "max_chars": 10,
                },
            }
        )
        violations = handler._lint_branch("test", str(tmp_path / "branch"), limits)

        assert len(violations) == 1
        assert violations[0]["key"] == "learn2"


class TestListContainer:
    """List container (sessions/observations style)."""

    def test_list_items_measured(self, tmp_path: Path) -> None:
        handler = _get_lint_handler()

        trinity = tmp_path / "branch" / ".trinity"
        trinity.mkdir(parents=True)
        obs_data = {
            "observations": [
                {"note": "short"},  # 5 chars
                {"note": "this observation is way too long for the cap"},  # over
            ],
        }
        (trinity / "observations.json").write_text(json.dumps(obs_data), encoding="utf-8")

        limits = _make_limits(
            {
                "obs": {
                    "file": "observations.json",
                    "container": "observations",
                    "kind": "list",
                    "field": "note",
                    "max_chars": 10,
                },
            }
        )
        violations = handler._lint_branch("test", str(tmp_path / "branch"), limits)

        assert len(violations) == 1
        assert violations[0]["key"] == "[1]"
        assert violations[0]["entry_type"] == "obs"


class TestListContainerMissingField:
    """A missing canonical field is REPORTED, not skipped (reversed 2026-08-26).

    This class used to pin the opposite: an item lacking the field was dropped
    on the reading that shape belongs to the trinity checker, not to a char-cap
    scanner. @hooks proved what that boundary cost — the write gate refuses
    those entries, so lint could tell a branch it was compliant and the branch
    would then be blocked on its next write for a shape lint had already seen.
    An audit that stays quiet about a shape the gate blocks is not a narrower
    audit, it is a wrong one. The no-crash guarantee the old name promised is
    kept: the scan completes and names every entry it cannot measure.
    """

    def test_missing_field_is_reported(self, tmp_path: Path) -> None:
        handler = _get_lint_handler()

        trinity = tmp_path / "branch" / ".trinity"
        trinity.mkdir(parents=True)
        obs_data = {
            "observations": [
                {"note": "short"},  # has field
                {"other_key": "no note here"},  # missing field
                {"note": "also short"},  # has field
            ],
        }
        (trinity / "observations.json").write_text(json.dumps(obs_data), encoding="utf-8")

        limits = _make_limits(
            {
                "obs": {
                    "file": "observations.json",
                    "container": "observations",
                    "kind": "list",
                    "field": "note",
                    "max_chars": 100,
                },
            }
        )

        # The two measurable notes are within cap; the third has no 'note' field
        # at all, so its cap cannot be applied and it is named rather than passed.
        violations = handler._lint_branch("test", str(tmp_path / "branch"), limits)
        assert len(violations) == 1
        assert violations[0]["key"] == "[1]"
        assert violations[0]["reason"] == "missing_field"
        assert violations[0]["field"] == "note"
        assert violations[0]["found_type"] == "missing"


# ===========================================================================
# 3. Lint handler integration tests
# ===========================================================================


class TestLintHandlerFindsViolations:
    """Lint handler finds planted violations with correct counts."""

    def test_finds_violations(self, tmp_path: Path) -> None:
        handler = _get_lint_handler()

        # Create a branch with planted over-limit entries
        trinity = tmp_path / "branch_a" / ".trinity"
        trinity.mkdir(parents=True)

        local_data = {
            "key_learnings": {
                "ok_entry": "fine",
                "bad_entry": "x" * 15,  # 15 chars, cap 10 -> over by 5
            },
        }
        (trinity / "local.json").write_text(json.dumps(local_data), encoding="utf-8")

        branches = [{"name": "branch_a", "path": str(tmp_path / "branch_a")}]
        limits = _make_limits()

        # Monkeypatch load_entry_limits to return our test limits
        with patch.object(handler, "load_entry_limits", return_value=limits):
            result = handler.run_lint(branches)

        assert result["success"] is True
        assert result["total_violations"] == 1
        assert result["branches_scanned"] == 1

        v = result["violations"][0]
        assert v["branch"] == "branch_a"
        assert v["key"] == "bad_entry"
        assert v["over_by"] == 5
        assert v["length"] == 15
        assert v["cap"] == 10


class TestLintHandlerReadOnly:
    """Lint handler must be strictly read-only -- files unchanged after scan."""

    def test_files_unchanged_after_lint(self, tmp_path: Path) -> None:
        handler = _get_lint_handler()

        # Create branch with violations
        trinity = tmp_path / "branch_b" / ".trinity"
        trinity.mkdir(parents=True)

        local_data = {
            "key_learnings": {
                "big": "x" * 50,
            },
        }
        local_path = trinity / "local.json"
        local_content = json.dumps(local_data, indent=2)
        local_path.write_text(local_content, encoding="utf-8")

        obs_data = {
            "observations": [
                {"note": "y" * 50},
            ],
        }
        obs_path = trinity / "observations.json"
        obs_content = json.dumps(obs_data, indent=2)
        obs_path.write_text(obs_content, encoding="utf-8")

        # Read content before lint
        local_before = local_path.read_text(encoding="utf-8")
        obs_before = obs_path.read_text(encoding="utf-8")

        branches = [{"name": "branch_b", "path": str(tmp_path / "branch_b")}]
        limits = _make_limits(
            {
                "key_learnings": {
                    "file": "local.json",
                    "container": "key_learnings",
                    "kind": "dict",
                    "field": "value",
                    "max_chars": 10,
                },
                "observations": {
                    "file": "observations.json",
                    "container": "observations",
                    "kind": "list",
                    "field": "note",
                    "max_chars": 10,
                },
            }
        )

        with patch.object(handler, "load_entry_limits", return_value=limits):
            handler.run_lint(branches)

        # Assert files are UNCHANGED
        local_after = local_path.read_text(encoding="utf-8")
        obs_after = obs_path.read_text(encoding="utf-8")

        assert local_before == local_after, "local.json was modified by lint!"
        assert obs_before == obs_after, "observations.json was modified by lint!"


class TestUnknownBranchIsAnError:
    """A branch that is not in the registry must not report a clean bill of health.

    'lint @nosuchbrnach' used to print a green 'No violations found across
    @nosuchbrnach (0 scanned)' — a typo read as proof the branch was clean.
    """

    def _lint_module(self):
        return importlib.import_module("aipass.memory.apps.modules.lint")

    def test_unknown_branch_calls_error(self) -> None:
        lint = self._lint_module()
        registry = [{"name": "memory", "path": str(Path(tempfile.gettempdir()) / "memory")}]

        with patch.object(lint, "_read_registry", return_value=registry):
            with patch.object(lint, "error") as errored:
                with patch.object(lint, "run_lint") as scanned:
                    lint._execute_lint(branch_filter="nosuchbrnach")

        errored.assert_called_once()
        assert "nosuchbrnach" in str(errored.call_args)
        scanned.assert_not_called()

    def test_unknown_branch_does_not_report_success(self) -> None:
        lint = self._lint_module()
        registry = [{"name": "memory", "path": str(Path(tempfile.gettempdir()) / "memory")}]

        with patch.object(lint, "_read_registry", return_value=registry):
            with patch.object(lint, "error"):
                with patch.object(lint, "success") as succeeded:
                    lint._execute_lint(branch_filter="nosuchbrnach")

        succeeded.assert_not_called()

    def test_known_branch_still_scans(self) -> None:
        """The guard must not block a real branch."""
        lint = self._lint_module()
        registry = [{"name": "memory", "path": str(Path(tempfile.gettempdir()) / "memory")}]

        with patch.object(lint, "_read_registry", return_value=registry):
            with patch.object(lint, "run_lint", return_value={"success": True, "violations": []}) as scanned:
                with patch.object(lint, "_display_results"):
                    lint._execute_lint(branch_filter="memory")

        scanned.assert_called_once()

    def test_known_branch_match_is_case_insensitive(self) -> None:
        """run_lint matches case-insensitively, so the guard must too."""
        lint = self._lint_module()
        registry = [{"name": "memory", "path": str(Path(tempfile.gettempdir()) / "memory")}]

        with patch.object(lint, "_read_registry", return_value=registry):
            with patch.object(lint, "run_lint", return_value={"success": True, "violations": []}) as scanned:
                with patch.object(lint, "_display_results"):
                    lint._execute_lint(branch_filter="MEMORY")

        scanned.assert_called_once()

    def test_no_filter_scans_everything(self) -> None:
        lint = self._lint_module()
        registry = [{"name": "memory", "path": str(Path(tempfile.gettempdir()) / "memory")}]

        with patch.object(lint, "_read_registry", return_value=registry):
            with patch.object(lint, "run_lint", return_value={"success": True, "violations": []}) as scanned:
                with patch.object(lint, "_display_results"):
                    lint._execute_lint(branch_filter=None)

        scanned.assert_called_once()


class TestLintHelpFlag:
    """A trailing help flag must print help, never scan."""

    def _lint_module(self):
        return importlib.import_module("aipass.memory.apps.modules.lint")

    def test_run_help_prints_help(self) -> None:
        lint = self._lint_module()
        with patch.object(lint, "print_help") as helped:
            with patch.object(lint, "_execute_lint") as scanned:
                assert lint.handle_command("lint", ["run", "--help"]) is True
        helped.assert_called_once()
        scanned.assert_not_called()

    def test_branch_help_prints_help(self) -> None:
        lint = self._lint_module()
        with patch.object(lint, "print_help") as helped:
            with patch.object(lint, "_execute_lint") as scanned:
                assert lint.handle_command("lint", ["@memory", "-h"]) is True
        helped.assert_called_once()
        scanned.assert_not_called()

    def test_plain_run_still_scans(self) -> None:
        lint = self._lint_module()
        with patch.object(lint, "_execute_lint") as scanned:
            assert lint.handle_command("lint", ["run"]) is True
        scanned.assert_called_once()


# ===========================================================================
# The exit seam — a refusal that exits 0 is half a refusal
# ===========================================================================


class TestTheEmptyRegistryRefusalReachesTheExitCode:
    """The fleet refusal sweep, 2026-09-07: an empty registry exited 0.

    "No branches found in registry" is a refusal — nothing was linted and the
    caller must not read that as a clean bill of health. It printed through
    `warning()`, which marks nothing, so the entry point returned 0. Through
    `error()` the process failure flag is set and `resolve_exit` returns 2.
    """

    def _lint_module(self):
        return importlib.import_module("aipass.memory.apps.modules.lint")

    def test_an_empty_registry_exits_two(self, capsys):
        from aipass.cli.apps.modules import reset_command_state, resolve_exit

        lint = self._lint_module()
        reset_command_state()
        # The name the module actually binds: _read_registry is imported from
        # the monitor detector into lint's own namespace, so patch it there.
        with patch.object(lint, "_read_registry", return_value=[]):
            assert lint.handle_command("lint", ["run"]) is True
        assert resolve_exit(True) == 2, "lint found no branches but would exit 0"
        captured = capsys.readouterr()
        assert "No branches found" in captured.out + captured.err


# ===========================================================================
# 4. Fields mode — the closed-shape inventory (FPLAN-0593 / DPLAN-0347)
#
# One capped field per entry type is what let a 917-char `status` ride past
# every gate while the fleet median was 9. These pin the second measurement:
# every string field listed by chars, everything outside the shape flagged,
# and the canonical field left to the mode that already owns it.
# ===========================================================================


_BUDGETS = {"passport.json": {"max_chars": 6000, "max_string_chars": 600}}


def _shape_limits() -> dict[str, Any]:
    """Limits carrying a closed field shape, same form as memory.config.json."""
    return {
        "enabled": True,
        "enforce": False,
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
                    "tags": {"type": "list[str]", "required": False, "max_items": 3, "max_chars": 120},
                },
            },
        },
    }


def _session(**overrides: Any) -> dict[str, Any]:
    """A session entry that matches the shape, with fields swapped in per test."""
    entry = {"number": 1, "date": "2026-09-15", "summary": "a fine summary", "status": "complete", "tags": ["one"]}
    entry.update(overrides)
    return entry


def _plant(tmp_path: Path, name: str, sessions: list[Any], passport: Any = None) -> list[dict[str, str]]:
    """Write a throwaway branch tree under tmp_path and return its registry rows."""
    trinity = tmp_path / name / ".trinity"
    trinity.mkdir(parents=True)
    (trinity / "local.json").write_text(json.dumps({"sessions": sessions}, indent=2), encoding="utf-8")
    if passport is not None:
        (trinity / "passport.json").write_text(json.dumps(passport, indent=2), encoding="utf-8")
    return [{"name": name, "path": str(tmp_path / name)}]


def _run_fields(handler, branches: list[dict[str, str]], limits: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run the fields mode against test limits and test budgets — never the live config."""
    with patch.object(handler, "load_entry_limits", return_value=limits or _shape_limits()):
        with patch.object(handler, "load_file_budgets", return_value=_BUDGETS):
            return handler.run_lint_fields(branches)


def _flags_for(result: dict[str, Any], field: str) -> list[dict[str, Any]]:
    """Every flag naming *field*."""
    return [v for v in result["violations"] if v.get("field") == field]


class TestFieldsModeFlagsTheClosedShape:
    """A field outside the shape is named, whichever way it is outside it."""

    def test_unknown_field_is_flagged(self, tmp_path: Path) -> None:
        handler = _get_lint_handler()
        branches = _plant(tmp_path, "alpha", [_session(mood="great")])

        result = _run_fields(handler, branches)

        hits = _flags_for(result, "mood")
        assert len(hits) == 1
        assert hits[0]["reason"] == "unknown_field"
        assert hits[0]["branch"] == "alpha"
        assert hits[0]["file"] == "local.json"
        assert hits[0]["length"] == 5

    def test_field_over_its_cap_is_flagged(self, tmp_path: Path) -> None:
        handler = _get_lint_handler()
        branches = _plant(tmp_path, "alpha", [_session(status="s" * 60)])

        result = _run_fields(handler, branches)

        hits = _flags_for(result, "status")
        assert len(hits) == 1
        assert hits[0]["reason"] == "field_over_cap"
        assert hits[0]["length"] == 60
        assert hits[0]["cap"] == 40
        assert hits[0]["over_by"] == 20
        assert hits[0]["units"] == "chars"

    def test_list_over_max_items_is_flagged(self, tmp_path: Path) -> None:
        handler = _get_lint_handler()
        branches = _plant(tmp_path, "alpha", [_session(tags=["a", "b", "c", "d", "e"])])

        result = _run_fields(handler, branches)

        hits = [v for v in _flags_for(result, "tags") if v["units"] == "items"]
        assert len(hits) == 1
        assert hits[0]["length"] == 5
        assert hits[0]["cap"] == 3
        assert hits[0]["over_by"] == 2

    def test_missing_required_field_is_flagged(self, tmp_path: Path) -> None:
        entry = _session()
        del entry["status"]
        handler = _get_lint_handler()
        branches = _plant(tmp_path, "alpha", [entry])

        result = _run_fields(handler, branches)

        hits = _flags_for(result, "status")
        assert len(hits) == 1
        assert hits[0]["reason"] == "missing_field"

    def test_a_clean_branch_flags_nothing(self, tmp_path: Path) -> None:
        handler = _get_lint_handler()
        branches = _plant(tmp_path, "alpha", [_session(), _session(number=2)])

        result = _run_fields(handler, branches)

        assert result["success"] is True
        assert result["violations"] == []
        assert result["branches_scanned"] == 1


class TestFieldsModeIsAnInventory:
    """Every string field is LISTED by chars, not only the ones in breach."""

    def test_every_string_field_is_measured(self, tmp_path: Path) -> None:
        handler = _get_lint_handler()
        branches = _plant(tmp_path, "alpha", [_session()])

        result = _run_fields(handler, branches)

        measured = {(r["field"], r["units"]): r for r in result["fields"]}
        # date, summary, status, tags-as-items, tags-as-chars. `number` is an
        # int and has no characters to list.
        assert set(measured) == {
            ("date", "chars"),
            ("summary", "chars"),
            ("status", "chars"),
            ("tags", "items"),
            ("tags", "chars"),
        }
        assert measured[("status", "chars")]["length"] == len("complete")
        assert measured[("status", "chars")]["cap"] == 40
        assert measured[("tags", "items")]["length"] == 1
        assert result["total_fields"] == 5

    def test_summary_rows_carry_max_p95_and_flag_counts(self, tmp_path: Path) -> None:
        handler = _get_lint_handler()
        sessions = [_session(status="s" * n) for n in (5, 5, 5, 5, 5, 5, 5, 5, 5, 60)]
        branches = _plant(tmp_path, "alpha", sessions)

        result = _run_fields(handler, branches)

        row = next(r for r in result["summary"] if r["field"] == "status" and r["units"] == "chars")
        assert row["count"] == 10
        assert row["max"] == 60
        assert row["p95"] == 60  # nearest-rank: a real entry's length, never an average
        assert row["flagged"] == 1
        assert row["worst_over"] == 20
        assert row["branch"] == "alpha"

    def test_worst_first_ordering_matches_the_original_mode(self, tmp_path: Path) -> None:
        handler = _get_lint_handler()
        branches = _plant(tmp_path, "alpha", [_session(status="s" * 45, tags=["t" * 200])])

        result = _run_fields(handler, branches)

        overs = [v["over_by"] for v in result["violations"]]
        assert overs == sorted(overs, reverse=True)


class TestTheCanonicalFieldIsNotReportedTwice:
    """The canonical field is inventoried here and JUDGED by `lint run` — never both.

    check_fields skips it by contract; this pins that the fields mode does not
    quietly re-derive its cap, which would make one fat summary two findings.
    """

    def test_over_cap_canonical_field_is_listed_but_not_flagged(self, tmp_path: Path) -> None:
        handler = _get_lint_handler()
        branches = _plant(tmp_path, "alpha", [_session(summary="x" * 500)])

        result = _run_fields(handler, branches)

        assert _flags_for(result, "summary") == []
        listed = next(r for r in result["fields"] if r["field"] == "summary")
        assert listed["length"] == 500
        assert listed["cap"] == 300
        assert listed["canonical"] is True

    def test_the_original_mode_still_owns_that_violation(self, tmp_path: Path) -> None:
        handler = _get_lint_handler()
        branches = _plant(tmp_path, "alpha", [_session(summary="x" * 500)])

        with patch.object(handler, "load_entry_limits", return_value=_shape_limits()):
            canonical = handler.run_lint(branches)

        assert canonical["total_violations"] == 1
        assert canonical["violations"][0]["over_by"] == 200


class TestThePassportRow:
    """passport.json is measured by SIZE only — @spawn owns its schema."""

    def test_a_string_over_600_is_flagged(self, tmp_path: Path) -> None:
        handler = _get_lint_handler()
        passport = {"identity": {"purpose": "p" * 700}}
        branches = _plant(tmp_path, "alpha", [_session()], passport=passport)

        result = _run_fields(handler, branches)

        hits = [v for v in result["violations"] if v["entry_type"] == "passport.json"]
        assert len(hits) == 1
        assert hits[0]["reason"] == "field_over_cap"
        assert hits[0]["key"] == "identity.purpose"
        assert hits[0]["length"] == 700
        assert hits[0]["cap"] == 600
        assert hits[0]["branch"] == "alpha"

    def test_a_file_over_6000_is_flagged(self, tmp_path: Path) -> None:
        handler = _get_lint_handler()
        passport = {"identity": {"purpose": "p" * 7000}}
        branches = _plant(tmp_path, "alpha", [_session()], passport=passport)

        result = _run_fields(handler, branches)

        reasons = {v["reason"] for v in result["violations"] if v["entry_type"] == "passport.json"}
        assert "file_over_budget" in reasons
        row = result["passport"][0]
        assert row["cap"] == 6000
        assert row["string_cap"] == 600
        assert row["length"] > 6000
        assert row["oversized_strings"] == 1

    def test_a_passport_within_budget_is_reported_clean(self, tmp_path: Path) -> None:
        handler = _get_lint_handler()
        branches = _plant(tmp_path, "alpha", [_session()], passport={"identity": {"purpose": "small"}})

        result = _run_fields(handler, branches)

        assert result["violations"] == []
        assert result["passport"][0]["oversized_strings"] == 0
        assert result["passport"][0]["length"] > 0

    def test_a_branch_without_a_passport_gets_no_row(self, tmp_path: Path) -> None:
        handler = _get_lint_handler()
        branches = _plant(tmp_path, "alpha", [_session()])

        result = _run_fields(handler, branches)

        assert result["passport"] == []


class TestFieldsModeIsReadOnly:
    """The fields mode never writes, truncates or deletes — content AND mtime."""

    def test_nothing_on_disk_moves(self, tmp_path: Path) -> None:
        handler = _get_lint_handler()
        passport = {"identity": {"purpose": "p" * 700}}
        branches = _plant(
            tmp_path,
            "alpha",
            [_session(mood="great", status="s" * 60, tags=["a", "b", "c", "d"])],
            passport=passport,
        )

        tree = sorted(p for p in (tmp_path / "alpha" / ".trinity").iterdir())
        before = {p: (p.read_text(encoding="utf-8"), p.stat().st_mtime_ns) for p in tree}

        result = _run_fields(handler, branches)
        assert result["violations"], "the scan must have found something to report"

        after = {p: (p.read_text(encoding="utf-8"), p.stat().st_mtime_ns) for p in tree}
        assert after == before, "lint fields modified a file"
        still_there = sorted(p for p in (tmp_path / "alpha" / ".trinity").iterdir())
        assert still_there == tree, "lint fields added or removed a file"


class TestFieldsModeRouting:
    """`lint fields` is ADDITIVE — the old spellings route exactly where they did."""

    def _lint_module(self):
        return importlib.import_module("aipass.memory.apps.modules.lint")

    def test_fields_routes_to_the_fields_mode(self) -> None:
        lint = self._lint_module()
        with patch.object(lint, "_execute_lint_fields") as fields:
            with patch.object(lint, "_execute_lint") as canonical:
                assert lint.handle_command("lint", ["fields"]) is True
        fields.assert_called_once_with(None)
        canonical.assert_not_called()

    def test_fields_takes_a_branch_filter(self) -> None:
        lint = self._lint_module()
        with patch.object(lint, "_execute_lint_fields") as fields:
            assert lint.handle_command("lint", ["fields", "@devpulse"]) is True
        fields.assert_called_once_with("devpulse")

    def test_fields_help_still_prints_help(self) -> None:
        lint = self._lint_module()
        with patch.object(lint, "print_help") as helped:
            with patch.object(lint, "_execute_lint_fields") as fields:
                assert lint.handle_command("lint", ["fields", "--help"]) is True
        helped.assert_called_once()
        fields.assert_not_called()

    def test_an_unknown_fields_argument_is_refused(self) -> None:
        lint = self._lint_module()
        with patch.object(lint, "error") as errored:
            with patch.object(lint, "_execute_lint_fields") as fields:
                assert lint.handle_command("lint", ["fields", "bogus"]) is True
        errored.assert_called_once()
        fields.assert_not_called()

    def test_the_old_spellings_still_reach_the_old_mode(self) -> None:
        lint = self._lint_module()
        for args, expected in ((["run"], None), (["@devpulse"], "devpulse"), (["run", "@devpulse"], "devpulse")):
            with patch.object(lint, "_execute_lint") as canonical:
                with patch.object(lint, "_execute_lint_fields") as fields:
                    assert lint.handle_command("lint", args) is True
            canonical.assert_called_once_with(expected)
            fields.assert_not_called()

    def test_bare_lint_still_introspects(self) -> None:
        lint = self._lint_module()
        with patch.object(lint, "print_introspection") as introspected:
            with patch.object(lint, "_execute_lint_fields") as fields:
                assert lint.handle_command("lint", []) is True
        introspected.assert_called_once()
        fields.assert_not_called()


class TestTheOriginalOutputIsUnchanged:
    """A regression pin on the ORIGINAL mode's rendering, character for character.

    The fields mode shares the module's console helpers and the registry
    bridge, so the way it could break `lint run` is by changing what that
    prints. This is the tripwire.
    """

    def _lint_module(self):
        return importlib.import_module("aipass.memory.apps.modules.lint")

    def test_violation_rendering_is_byte_for_byte(self, capsys) -> None:
        lint = self._lint_module()
        result = {
            "success": True,
            "violations": [
                {
                    "branch": "alpha",
                    "file": "local.json",
                    "container": "key_learnings",
                    "key": "k1",
                    "length": 15,
                    "cap": 10,
                    "over_by": 5,
                    "entry_type": "key_learnings",
                },
            ],
            "total_violations": 1,
            "branches_scanned": 2,
            "branches_skipped": 1,
        }

        lint._display_results(result, None)

        captured = capsys.readouterr()
        lines = [line.rstrip() for line in captured.out.splitlines() if line.strip()]
        assert lines == [
            "  alpha",
            "    ! local.json:key_learnings/k1 (key_learnings) 15/10 chars +5 over",
            "Scanned 2 branch(es), skipped 1",
        ]
        assert "1 violation(s) found" in captured.err

    def test_the_clean_line_is_unchanged(self, capsys) -> None:
        lint = self._lint_module()
        result = {"success": True, "violations": [], "total_violations": 0, "branches_scanned": 22}

        lint._display_results(result, "memory")

        captured = capsys.readouterr()
        assert "No violations found across @memory (22 scanned)" in captured.out


class TestFieldsModeDisplay:
    """A clean fleet must SAY it is clean — an empty screen proves nothing ran."""

    def _lint_module(self):
        return importlib.import_module("aipass.memory.apps.modules.lint")

    def _summary_row(self, **overrides: Any) -> dict[str, Any]:
        row = {
            "branch": "alpha",
            "file": "local.json",
            "entry_type": "sessions",
            "field": "status",
            "units": "chars",
            "cap": 40,
            "canonical": False,
            "count": 3,
            "max": 12,
            "p95": 12,
            "flagged": 0,
            "worst_over": 0,
        }
        row.update(overrides)
        return row

    def test_clean_fleet_prints_the_success_line(self, capsys) -> None:
        lint = self._lint_module()
        passport = {
            "branch": "alpha",
            "file": "passport.json",
            "length": 1797,
            "cap": 6000,
            "string_cap": 600,
            "oversized_strings": 0,
        }
        result = {
            "success": True,
            "summary": [self._summary_row()],
            "violations": [],
            "passport": [passport],
            "total_fields": 3,
            "branches_scanned": 22,
            "branches_skipped": 0,
        }

        lint._display_field_results(result, None)

        out = capsys.readouterr().out
        assert "No fields outside the shape across all branches (22 scanned)" in out
        assert "alpha" in out
        assert "status" in out
        assert "1797/6000 chars" in out

    def test_a_flagged_field_is_obvious(self, capsys) -> None:
        lint = self._lint_module()
        result = {
            "success": True,
            "summary": [self._summary_row(max=917, flagged=1, worst_over=877)],
            "violations": [
                {
                    "branch": "alpha",
                    "file": "local.json",
                    "container": "sessions",
                    "key": "[2]",
                    "entry_type": "sessions",
                    "field": "status",
                    "units": "chars",
                    "reason": "field_over_cap",
                    "length": 917,
                    "cap": 40,
                    "over_by": 877,
                },
            ],
            "passport": [],
            "total_fields": 3,
            "branches_scanned": 1,
            "branches_skipped": 0,
        }

        lint._display_field_results(result, "alpha")

        captured = capsys.readouterr()
        assert "outside shape" in captured.out
        assert "917/40" in captured.out
        assert "+877 over" in captured.out
        assert "1 field(s) outside the shape" in captured.err

    def test_an_empty_scan_says_so(self, capsys) -> None:
        lint = self._lint_module()
        result = {
            "success": True,
            "summary": [],
            "violations": [],
            "passport": [],
            "total_fields": 0,
            "branches_scanned": 0,
            "branches_skipped": 0,
        }

        lint._display_field_results(result, None)

        captured = capsys.readouterr()
        assert "No .trinity fields to measure" in captured.out + captured.err

    def test_the_fields_mode_reaches_the_display(self) -> None:
        lint = self._lint_module()
        registry = [{"name": "memory", "path": str(Path(tempfile.gettempdir()) / "memory")}]

        with patch.object(lint, "_read_registry", return_value=registry):
            with patch.object(lint, "run_lint_fields", return_value={"success": True}) as scanned:
                with patch.object(lint, "_display_field_results") as displayed:
                    lint._execute_lint_fields(branch_filter="memory")

        scanned.assert_called_once()
        displayed.assert_called_once()

    def test_an_unknown_branch_is_refused_in_fields_mode_too(self) -> None:
        lint = self._lint_module()
        registry = [{"name": "memory", "path": str(Path(tempfile.gettempdir()) / "memory")}]

        with patch.object(lint, "_read_registry", return_value=registry):
            with patch.object(lint, "error") as errored:
                with patch.object(lint, "run_lint_fields") as scanned:
                    lint._execute_lint_fields(branch_filter="nosuchbrnach")

        errored.assert_called_once()
        scanned.assert_not_called()
