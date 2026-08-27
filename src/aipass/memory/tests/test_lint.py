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
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Helpers: fresh-import modules under test with mocks already in place
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _fresh_lint_modules():
    """Drop cached modules so each test gets a fresh import."""
    sys.modules.pop("aipass.memory.apps.handlers.json", None)
    sys.modules.pop("aipass.memory.apps.handlers.json.json_handler", None)
    sys.modules.pop("aipass.memory.apps.handlers.json.entry_limits", None)
    sys.modules.pop("aipass.memory.apps.handlers.json.lint_handler", None)
    sys.modules.pop("aipass.memory.apps.modules.lint", None)
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
        registry = [{"name": "memory", "path": "/tmp/memory"}]

        with patch.object(lint, "_read_registry", return_value=registry):
            with patch.object(lint, "error") as errored:
                with patch.object(lint, "run_lint") as scanned:
                    lint._execute_lint(branch_filter="nosuchbrnach")

        errored.assert_called_once()
        assert "nosuchbrnach" in str(errored.call_args)
        scanned.assert_not_called()

    def test_unknown_branch_does_not_report_success(self) -> None:
        lint = self._lint_module()
        registry = [{"name": "memory", "path": "/tmp/memory"}]

        with patch.object(lint, "_read_registry", return_value=registry):
            with patch.object(lint, "error"):
                with patch.object(lint, "success") as succeeded:
                    lint._execute_lint(branch_filter="nosuchbrnach")

        succeeded.assert_not_called()

    def test_known_branch_still_scans(self) -> None:
        """The guard must not block a real branch."""
        lint = self._lint_module()
        registry = [{"name": "memory", "path": "/tmp/memory"}]

        with patch.object(lint, "_read_registry", return_value=registry):
            with patch.object(lint, "run_lint", return_value={"success": True, "violations": []}) as scanned:
                with patch.object(lint, "_display_results"):
                    lint._execute_lint(branch_filter="memory")

        scanned.assert_called_once()

    def test_known_branch_match_is_case_insensitive(self) -> None:
        """run_lint matches case-insensitively, so the guard must too."""
        lint = self._lint_module()
        registry = [{"name": "memory", "path": "/tmp/memory"}]

        with patch.object(lint, "_read_registry", return_value=registry):
            with patch.object(lint, "run_lint", return_value={"success": True, "violations": []}) as scanned:
                with patch.object(lint, "_display_results"):
                    lint._execute_lint(branch_filter="MEMORY")

        scanned.assert_called_once()

    def test_no_filter_scans_everything(self) -> None:
        lint = self._lint_module()
        registry = [{"name": "memory", "path": "/tmp/memory"}]

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
