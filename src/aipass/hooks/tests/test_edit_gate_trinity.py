# =================== AIPass ====================
# Name: test_edit_gate_trinity.py
# Version: 1.9.0
# Description: Tests for edit_gate .trinity char-limit + rollover-budget checks (FPLAN-0270 Phase 4)
# Branch: hooks
# Created: 2026-06-13
# Modified: 2026-10-08
# =============================================

"""Tests for apps/handlers/security/edit_gate.py's .trinity character-limit check (Write/Edit/MultiEdit)."""

# Here: the advisories and budgets (todo count, newest-first, section counts,
# snapshots, the throttle). The Write lane is test_edit_gate_trinity_write.py,
# the Edit lane test_edit_gate_trinity_edit.py, the shell tripwire
# test_edit_gate_trinity_tripwire.py, the refusal wording test_edit_gate_trinity_refusals.py.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(documentation) — that edit_gate's functions carry docstrings
# seedgo: no-test-needed(ruff) — that edit_gate.py parses and its imports resolve
# seedgo: no-test-needed(stdlib) — json.loads' parsing of the proposed content; the gate's reading of it is pinned

import importlib
import json
import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from aipass.hooks.apps.handlers.security import edit_gate
from aipass.hooks.apps.handlers.security.edit_gate import handle
from aipass.hooks.apps.modules import cadence
from aipass.hooks.tests.support_edit_gate_trinity import (
    _TEST_LIMITS_DISABLED,
    _TEST_LIMITS_ENFORCE,
    _TEST_LIMITS_WARN,
    _fence_real,
    _hook_data,
    _imports_via_seam,
    _make_trinity_path,
    _mock_entry_limits,
    _mock_importlib_modules,
)
from aipass.memory.apps.modules import door_entry_limits as memory_entry_limits


def _advisory_context(result):
    """The todo-count advisory as the model receives it: PreToolUse additionalContext.

    Plain stdout on a PreToolUse exit 0 never reaches the model (measured on
    @canary, 2026-09-15). Never a decision: the advisory must not block, allow or ask.
    """
    assert result["exit_code"] == 0
    doc = json.loads(result["stdout"])
    assert set(doc) == {"hookSpecificOutput"}
    assert set(doc["hookSpecificOutput"]) == {"hookEventName", "additionalContext"}
    assert doc["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
    return doc["hookSpecificOutput"]["additionalContext"]


# The real fleet shape: regular sessions capped at 15, auto-compact snapshots
# budgeted separately at 3. Mirrors memory.config.json defaults.
_ROLLOVER_CONFIG_FLEET = {
    "rollover": {
        "defaults": {
            "local": {
                "sessions": {"count": 15, "auto_compact_cap": 3},
                "key_learnings": {"count": 15},
            },
            "observations": {
                "observations": {"count": 15},
            },
        },
        "per_branch": {},
    },
}


class TestTrinityTodosCountAdvisory:
    """Non-blocking advisory when todos exceed rollover count limit."""

    def test_todos_over_limit_advisory_write(self, tmp_path):
        """Write with 11 todos (limit 10) -> exit_code 0 + advisory stdout."""
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"todos": [{"task": f"todo {i}"} for i in range(11)]})

        with _imports_via_seam(_mock_importlib_modules(_TEST_LIMITS_WARN)):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 0
        assert "todos over limit" in _advisory_context(result)
        assert "11/10" in _advisory_context(result)

    def test_todos_under_limit_no_advisory(self, tmp_path):
        """Write with 5 todos (limit 10) -> exit_code 0, empty stdout."""
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"todos": [{"task": f"todo {i}"} for i in range(5)]})

        with _imports_via_seam(_mock_importlib_modules(_TEST_LIMITS_WARN)):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 0
        assert result["stdout"] == ""

    def test_todos_at_limit_no_advisory(self, tmp_path):
        """Write with exactly 10 todos (limit 10) -> no advisory."""
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"todos": [{"task": f"todo {i}"} for i in range(10)]})

        with _imports_via_seam(_mock_importlib_modules(_TEST_LIMITS_WARN)):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 0
        assert result["stdout"] == ""

    def test_todos_advisory_via_edit(self, tmp_path):
        """Edit that adds a todo pushing count over limit -> advisory."""
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        existing = {"todos": [{"task": f"todo {i}"} for i in range(10)]}
        Path(file_path).write_text(json.dumps(existing), encoding="utf-8")
        new_todos = [{"task": f"todo {i}"} for i in range(11)]

        with _imports_via_seam(
            _mock_importlib_modules(_TEST_LIMITS_WARN),
        ):
            result = handle(
                _hook_data(
                    file_path,
                    tool_name="Edit",
                    cwd=cwd,
                    old_string=json.dumps(existing["todos"]),
                    new_string=json.dumps(new_todos),
                )
            )

        assert result["exit_code"] == 0
        assert "todos over limit" in _advisory_context(result)
        assert "11/10" in _advisory_context(result)

    def test_todos_advisory_never_blocks(self, tmp_path):
        """Even with enforce=True, todos count advisory has exit_code 0."""
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"todos": [{"task": f"todo {i}"} for i in range(15)]})

        with _imports_via_seam(
            _mock_importlib_modules(_TEST_LIMITS_ENFORCE),
        ):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 0
        assert "todos over limit" in _advisory_context(result)
        assert "15/10" in _advisory_context(result)

    def test_todos_advisory_observations_json_skip(self, tmp_path):
        """observations.json never triggers todos advisory."""
        file_path = _make_trinity_path(tmp_path, "hooks", "observations.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps(
            {
                "observations": [{"note": "obs"}],
                "todos": [{"task": f"t{i}"} for i in range(20)],
            }
        )

        with _imports_via_seam(
            _mock_importlib_modules(_TEST_LIMITS_WARN),
        ):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 0
        assert result["stdout"] == ""

    def test_todos_advisory_config_loader_failure_silent(self, tmp_path):
        """config_loader import fails -> no advisory, no crash, save allowed."""
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"todos": [{"task": f"todo {i}"} for i in range(15)]})

        el_real = memory_entry_limits
        entry_limits_mock = MagicMock()
        entry_limits_mock.load_entry_limits.return_value = _TEST_LIMITS_WARN
        entry_limits_mock.changed_entries = el_real.changed_entries

        def _side_effect(name):
            """Route importlib calls, failing config_loader."""
            if "entry_limits" in name:
                return entry_limits_mock
            if "config_loader" in name:
                raise ImportError("no config_loader")
            return importlib.import_module(name)

        with _imports_via_seam(_side_effect):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 0
        assert result["stdout"] == ""

    def test_char_limit_blocks_before_advisory(self, tmp_path):
        """Char-limit block takes priority over todos advisory."""
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps(
            {
                "key_learnings": {"k1": "x" * 250},
                "todos": [{"task": f"todo {i}"} for i in range(15)],
            }
        )

        with _imports_via_seam(
            _mock_importlib_modules(_TEST_LIMITS_ENFORCE),
        ):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 2
        parsed = json.loads(result["stdout"])
        assert parsed["decision"] == "block"

    def test_todos_advisory_logs_warning(self, tmp_path, caplog):
        """Advisory emits a logger.warning with the over-limit message."""
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"todos": [{"task": f"todo {i}"} for i in range(12)]})

        with _imports_via_seam(
            _mock_importlib_modules(_TEST_LIMITS_WARN),
        ):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 0
        assert "todos over limit" in caplog.text
        assert "12/10" in caplog.text

    def test_todos_advisory_per_branch_override(self, tmp_path):
        """per_branch override sets limit to 5 for hooks -> 6 todos triggers advisory."""
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"todos": [{"task": f"todo {i}"} for i in range(6)]})

        rollover_cfg = {
            "rollover": {
                "defaults": {"local": {"todos": {"count": 10}}},
                "per_branch": {"hooks": {"local": {"todos": {"count": 5}}}},
            },
        }

        with _imports_via_seam(
            _mock_importlib_modules(_TEST_LIMITS_WARN, rollover_cfg),
        ):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 0
        assert "6/5" in _advisory_context(result)

    def test_the_advisory_names_the_roll_and_the_backlog(self, tmp_path):
        """DPLAN-0345: over the pad is legal on disk; the oldest roll off, and it says where."""
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"todos": [{"task": f"todo {i}"} for i in range(13)]})

        with _imports_via_seam(_mock_importlib_modules(_TEST_LIMITS_WARN)):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        stdout = _advisory_context(result)
        assert "13/10" in stdout
        assert "the oldest 3 roll off at the next rollover" in stdout
        assert "drone @memory rollover run --branch @hooks" in stdout
        assert ".backup/todo/hooks/backlog.json" in stdout
        assert "drone @memory todo backlog @hooks" in stdout
        assert "do not auto-roll" not in stdout

    def test_a_per_branch_block_without_todos_reads_memorys_default(self, tmp_path):
        """The count is memory's resolver's, not a second reader's.

        A per_branch local block that carries no todos count falls back to the
        CONFIGURED default in memory (get_todos_count). The old read here took
        the per_branch block and a hardcoded 10, so with a default of 8 it stayed
        silent at 9 while memory's roll moved one.
        """
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"todos": [{"task": f"todo {i}"} for i in range(9)]})
        rollover_cfg = {
            "rollover": {
                "defaults": {"local": {"sessions": {"count": 15}, "todos": {"count": 8}}},
                "per_branch": {"hooks": {"local": {"sessions": {"count": 15}}}},
            },
        }

        with _imports_via_seam(
            _mock_importlib_modules(_TEST_LIMITS_WARN, rollover_cfg),
        ):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert "9/8" in _advisory_context(result)
        assert "the oldest 1 roll off" in _advisory_context(result)

    def test_no_usable_count_promises_no_roll(self, tmp_path):
        """No usable count: memory rolls nothing, so the fallback 10 must not claim a roll."""
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"todos": [{"task": f"todo {i}"} for i in range(11)]})
        rollover_cfg = {"rollover": {"defaults": {"local": {"todos": {"count": "ten"}}}, "per_branch": {}}}

        with _imports_via_seam(
            _mock_importlib_modules(_TEST_LIMITS_WARN, rollover_cfg),
        ):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert "11/10" in _advisory_context(result)
        assert "nothing rolls" in _advisory_context(result)
        assert "roll off" not in _advisory_context(result)

    def test_no_todos_container_no_advisory(self, tmp_path):
        """local.json with no todos key -> no advisory."""
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"key_learnings": {"k1": "short"}})

        with _imports_via_seam(
            _mock_importlib_modules(_TEST_LIMITS_WARN),
        ):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 0
        assert result["stdout"] == ""


class TestTrinityNewestFirst:
    """DPLAN-0278: sessions[]/key_learnings[] must be inserted at index 0, number = max+1."""

    def test_clean_prepend_allowed(self, tmp_path):
        """New session inserted at index 0 with number = max+1 -> allowed."""
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        existing = {"sessions": [{"number": 5, "summary": "old"}]}
        Path(file_path).write_text(json.dumps(existing), encoding="utf-8")

        after = {"sessions": [{"number": 6, "summary": "new"}, {"number": 5, "summary": "old"}]}
        content = json.dumps(after)

        with _imports_via_seam(_fence_real(_mock_entry_limits(_TEST_LIMITS_WARN))):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 0
        assert result["stdout"] == ""

    def test_tail_append_blocked(self, tmp_path):
        """New session appended after the existing tail entry -> blocked."""
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        existing = {"sessions": [{"number": 5, "summary": "old"}]}
        Path(file_path).write_text(json.dumps(existing), encoding="utf-8")

        after = {"sessions": [{"number": 5, "summary": "old"}, {"number": 6, "summary": "new"}]}
        content = json.dumps(after)

        with _imports_via_seam(_fence_real(_mock_entry_limits(_TEST_LIMITS_WARN))):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 2
        parsed = json.loads(result["stdout"])
        assert parsed["decision"] == "block"
        assert "newest-first" in parsed["reason"]

    def test_number_not_greater_than_max_blocked(self, tmp_path):
        """New entry prepended at index 0 but number <= max existing -> blocked."""
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        existing = {"sessions": [{"number": 5, "summary": "old"}]}
        Path(file_path).write_text(json.dumps(existing), encoding="utf-8")

        after = {"sessions": [{"number": 5, "summary": "duplicate number"}, {"number": 5, "summary": "old"}]}
        content = json.dumps(after)

        with _imports_via_seam(_fence_real(_mock_entry_limits(_TEST_LIMITS_WARN))):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 2
        parsed = json.loads(result["stdout"])
        assert parsed["decision"] == "block"
        assert "number" in parsed["reason"]

    def test_key_learnings_tail_append_blocked(self, tmp_path):
        """key_learnings appended after the tail -> blocked."""
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        existing = {"key_learnings": [{"number": 10, "key": "old", "value": "v"}]}
        Path(file_path).write_text(json.dumps(existing), encoding="utf-8")

        after = {
            "key_learnings": [
                {"number": 10, "key": "old", "value": "v"},
                {"number": 11, "key": "new", "value": "v2"},
            ]
        }
        content = json.dumps(after)

        with _imports_via_seam(_fence_real(_mock_entry_limits(_TEST_LIMITS_WARN))):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 2
        parsed = json.loads(result["stdout"])
        assert parsed["decision"] == "block"

    def test_first_write_no_before_file_skips_check(self, tmp_path):
        """No existing file (first write) -> nothing to compare against, allowed."""
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"sessions": [{"number": 1, "summary": "first"}]})

        with _imports_via_seam(_fence_real(_mock_entry_limits(_TEST_LIMITS_WARN))):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 0

    def test_shrinking_array_skips_check(self, tmp_path):
        """Rollover-style shrink (fewer entries after) -> not treated as an append, allowed."""
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        existing = {"sessions": [{"number": 6, "summary": "keep"}, {"number": 5, "summary": "drop"}]}
        Path(file_path).write_text(json.dumps(existing), encoding="utf-8")

        after = {"sessions": [{"number": 6, "summary": "keep"}]}
        content = json.dumps(after)

        with _imports_via_seam(_fence_real(_mock_entry_limits(_TEST_LIMITS_WARN))):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 0

    def test_newest_first_checked_even_when_limits_disabled(self, tmp_path):
        """Tail-append still blocked even with enabled=False (independent gate)."""
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        existing = {"sessions": [{"number": 5, "summary": "old"}]}
        Path(file_path).write_text(json.dumps(existing), encoding="utf-8")

        after = {"sessions": [{"number": 5, "summary": "old"}, {"number": 6, "summary": "new"}]}
        content = json.dumps(after)

        with _imports_via_seam(_fence_real(_mock_entry_limits(_TEST_LIMITS_DISABLED))):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 2

    def test_unrelated_field_edit_no_new_entries_allowed(self, tmp_path):
        """Edit that doesn't add any new numbered entries -> newest-first check no-ops."""
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        existing = {"sessions": [{"number": 5, "summary": "old"}], "todos": [{"task": "old todo"}]}
        Path(file_path).write_text(json.dumps(existing), encoding="utf-8")

        with _imports_via_seam(_fence_real(_mock_entry_limits(_TEST_LIMITS_WARN))):
            result = handle(
                _hook_data(
                    file_path,
                    tool_name="Edit",
                    cwd=cwd,
                    old_string='"old todo"',
                    new_string='"new todo"',
                )
            )

        assert result["exit_code"] == 0


class TestTrinityLegacyNumberSchema:
    """A branch whose sessions[] use the legacy 'session_number' key must still be able
    to write memory. The guard exists to stop newest-first violations, and a schema it
    cannot read is not a violation (reported by VERA, Vera-Studio)."""

    def test_legacy_session_number_prepend_allowed(self, tmp_path):
        """Legacy schema, correct newest-first prepend -> allowed (was hard-blocked)."""
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        existing = {"sessions": [{"session_number": 5, "summary": "old"}]}
        Path(file_path).write_text(json.dumps(existing), encoding="utf-8")

        after = {
            "sessions": [
                {"session_number": 6, "summary": "new"},
                {"session_number": 5, "summary": "old"},
            ]
        }
        content = json.dumps(after)

        with _imports_via_seam(_fence_real(_mock_entry_limits(_TEST_LIMITS_WARN))):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 0
        assert result["stdout"] == ""

    def test_legacy_session_number_tail_append_blocked(self, tmp_path):
        """The ordering check is schema-independent — legacy tail append still blocks."""
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        existing = {"sessions": [{"session_number": 5, "summary": "old"}]}
        Path(file_path).write_text(json.dumps(existing), encoding="utf-8")

        after = {
            "sessions": [
                {"session_number": 5, "summary": "old"},
                {"session_number": 6, "summary": "new"},
            ]
        }
        content = json.dumps(after)

        with _imports_via_seam(_fence_real(_mock_entry_limits(_TEST_LIMITS_WARN))):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 2
        assert json.loads(result["stdout"])["decision"] == "block"

    def test_legacy_number_not_greater_than_max_blocked(self, tmp_path):
        """Monotonicity is enforced within the legacy schema too, not just skipped."""
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        existing = {"sessions": [{"session_number": 5, "summary": "old"}]}
        Path(file_path).write_text(json.dumps(existing), encoding="utf-8")

        after = {
            "sessions": [
                {"session_number": 5, "summary": "dupe"},
                {"session_number": 5, "summary": "old"},
            ]
        }
        content = json.dumps(after)

        with _imports_via_seam(_fence_real(_mock_entry_limits(_TEST_LIMITS_WARN))):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 2
        assert "must be greater than the max existing" in json.loads(result["stdout"])["reason"]

    def test_number_key_wins_over_session_number(self, tmp_path):
        """When both keys are present, 'number' is authoritative — session_number is ignored."""
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        # session_number 100 would block a new entry numbered 6; number 5 must win.
        existing = {"sessions": [{"number": 5, "session_number": 100, "summary": "old"}]}
        Path(file_path).write_text(json.dumps(existing), encoding="utf-8")

        after = {
            "sessions": [
                {"number": 6, "summary": "new"},
                {"number": 5, "session_number": 100, "summary": "old"},
            ]
        }
        content = json.dumps(after)

        with _imports_via_seam(_fence_real(_mock_entry_limits(_TEST_LIMITS_WARN))):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 0

    def test_cross_schema_migration_allowed(self, tmp_path):
        """Legacy existing entries, modern 'number' on the new one -> allowed."""
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        existing = {"sessions": [{"session_number": 5, "summary": "old"}]}
        Path(file_path).write_text(json.dumps(existing), encoding="utf-8")

        after = {"sessions": [{"number": 6, "summary": "new"}, {"session_number": 5, "summary": "old"}]}
        content = json.dumps(after)

        with _imports_via_seam(_fence_real(_mock_entry_limits(_TEST_LIMITS_WARN))):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 0

    def test_wholly_unnumbered_array_passes_through(self, tmp_path):
        """No recognized ordinal anywhere -> monotonicity can't be judged, so don't block."""
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        existing = {"sessions": [{"summary": "old"}]}
        Path(file_path).write_text(json.dumps(existing), encoding="utf-8")

        after = {"sessions": [{"summary": "new"}, {"summary": "old"}]}
        content = json.dumps(after)

        with _imports_via_seam(_fence_real(_mock_entry_limits(_TEST_LIMITS_WARN))):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 0

    def test_unnumbered_array_still_ordering_checked(self, tmp_path):
        """Pass-through covers the number check only — tail appends still block."""
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        existing = {"sessions": [{"summary": "old"}]}
        Path(file_path).write_text(json.dumps(existing), encoding="utf-8")

        after = {"sessions": [{"summary": "old"}, {"summary": "new"}]}
        content = json.dumps(after)

        with _imports_via_seam(_fence_real(_mock_entry_limits(_TEST_LIMITS_WARN))):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 2
        assert "newest-first" in json.loads(result["stdout"])["reason"]

    def test_unnumbered_new_entry_against_numbered_existing_blocked(self, tmp_path):
        """Dropping the ordinal when the file has one is a real violation — block, and
        name the accepted keys so there is a path to comply."""
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        existing = {"sessions": [{"number": 5, "summary": "old"}]}
        Path(file_path).write_text(json.dumps(existing), encoding="utf-8")

        after = {"sessions": [{"summary": "new"}, {"number": 5, "summary": "old"}]}
        content = json.dumps(after)

        with _imports_via_seam(_fence_real(_mock_entry_limits(_TEST_LIMITS_WARN))):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 2
        reason = json.loads(result["stdout"])["reason"]
        assert "no ordinal" in reason
        assert "session_number" in reason

    def test_key_learnings_legacy_schema_prepend_allowed(self, tmp_path):
        """The alias applies to every newest-first array, not just sessions."""
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        existing = {"key_learnings": [{"session_number": 5, "value": "old"}]}
        Path(file_path).write_text(json.dumps(existing), encoding="utf-8")

        after = {
            "key_learnings": [
                {"session_number": 6, "value": "new"},
                {"session_number": 5, "value": "old"},
            ]
        }
        content = json.dumps(after)

        with _imports_via_seam(_fence_real(_mock_entry_limits(_TEST_LIMITS_WARN))):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 0


class TestOverBudgetSeverity:
    """Compass #273 (the owner, 2026-08-14): severity follows design intent.

    Over-budget is not wrong behaviour, it is behaviour we chose to have — the
    message itself says nothing is lost, because @memory's rollover archives the
    overflow at the next PreCompact. Logged as WARNING it entered @trigger's
    escalation lane: 8 signatures, 579 occurrences, 10 of the 62 digests the lane
    has ever sent. The level is a field, not prose; the text stays as it is.
    """

    def _over_budget_records(self, caplog):
        return [r for r in caplog.records if "over the rollover budget" in r.getMessage()]

    def test_over_budget_logs_at_info_not_warning(self, tmp_path, caplog):
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"sessions": [{"summary": "s"} for _ in range(21)]})

        with caplog.at_level(logging.INFO):
            with _imports_via_seam(_mock_importlib_modules(_TEST_LIMITS_WARN)):
                result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 0
        records = self._over_budget_records(caplog)
        assert records, "the operator line must still be emitted — this is a level change, not a mute"
        assert all(r.levelno == logging.INFO for r in records)
        assert not [r for r in records if r.levelno >= logging.WARNING]

    def test_auto_compact_snapshot_class_also_logs_at_info(self, tmp_path, caplog):
        """All three call sites are one class — a fix that misses one keeps 1/3 of the lane."""
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"sessions": _regular_sessions(10) + _snapshot_sessions(5)})

        with caplog.at_level(logging.INFO):
            with _imports_via_seam(
                _mock_importlib_modules(_TEST_LIMITS_WARN, _ROLLOVER_CONFIG_FLEET),
            ):
                handle(_hook_data(file_path, content, cwd=cwd))

        records = self._over_budget_records(caplog)
        assert records
        assert all(r.levelno == logging.INFO for r in records)

    def test_generic_section_class_also_logs_at_info(self, tmp_path, caplog):
        file_path = _make_trinity_path(tmp_path, "hooks", "observations.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"observations": [{"note": "n"} for _ in range(16)]})

        with caplog.at_level(logging.INFO):
            with _imports_via_seam(_mock_importlib_modules(_TEST_LIMITS_WARN)):
                handle(_hook_data(file_path, content, cwd=cwd))

        records = self._over_budget_records(caplog)
        assert records
        assert all(r.levelno == logging.INFO for r in records)

    def test_the_emitter_is_not_named_after_the_severity_it_no_longer_uses(self):
        """The function name is a severity claim in prose: leaving it invites a re-raise."""
        assert hasattr(edit_gate, "_note_over_budget")
        assert not hasattr(edit_gate, "_warn_over_budget")

    def test_the_over_limit_entry_class_stays_at_warning(self, tmp_path, caplog):
        """Guard on the reclass: ONE class moves, not the file.

        The over-limit entry advisory (edit_gate.py:181) is a different animal —
        it names a cap the author must act on, and nothing archives it for them.
        It stays WARNING. If a future edit mutes this file wholesale, this fails.
        """
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"sessions": [{"summary": "x" * 5000}]})

        with caplog.at_level(logging.INFO):
            with _imports_via_seam(_mock_importlib_modules(_TEST_LIMITS_WARN)):
                handle(_hook_data(file_path, content, cwd=cwd))

        over_limit = [r for r in caplog.records if "over-limit .trinity entry" in r.getMessage()]
        assert over_limit
        assert all(r.levelno == logging.WARNING for r in over_limit)


class TestSectionCountGuard:
    """Soft count guard: warn (never block) when rolling sections exceed count cap."""

    def test_sessions_over_count_warns(self, tmp_path, caplog):
        """21 sessions vs 20 cap -> warning logged, write still allowed."""
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"sessions": [{"summary": "s"} for _ in range(21)]})

        with _imports_via_seam(_mock_importlib_modules(_TEST_LIMITS_WARN)):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 0
        assert "@hooks .trinity/local.json — sessions has 21 entries, 1 over the rollover budget of 20" in caplog.text

    def test_key_learnings_over_count_warns(self, tmp_path, caplog):
        """26 key_learnings vs 25 cap -> warning logged."""
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"key_learnings": [{"value": "v"} for _ in range(26)]})

        with _imports_via_seam(_mock_importlib_modules(_TEST_LIMITS_WARN)):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 0
        assert "key_learnings has 26 entries, 1 over the rollover budget of 25" in caplog.text

    def test_observations_over_count_warns(self, tmp_path, caplog):
        """16 observations vs 15 cap -> warning logged."""
        file_path = _make_trinity_path(tmp_path, "hooks", "observations.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"observations": [{"note": "n"} for _ in range(16)]})

        with _imports_via_seam(_mock_importlib_modules(_TEST_LIMITS_WARN)):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 0
        assert (
            "@hooks .trinity/observations.json — observations has 16 entries, 1 over the rollover budget of 15"
            in caplog.text
        )

    def test_under_count_no_warning(self, tmp_path, caplog):
        """10 sessions vs 20 cap -> no warning."""
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"sessions": [{"summary": "s"} for _ in range(10)]})

        with _imports_via_seam(_mock_importlib_modules(_TEST_LIMITS_WARN)):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 0
        assert "over the rollover budget" not in caplog.text

    def test_at_count_no_warning(self, tmp_path, caplog):
        """Exactly 20 sessions vs 20 cap -> no warning (only > triggers)."""
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"sessions": [{"summary": "s"} for _ in range(20)]})

        with _imports_via_seam(_mock_importlib_modules(_TEST_LIMITS_WARN)):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 0
        assert "over the rollover budget" not in caplog.text

    def test_count_guard_never_blocks(self, tmp_path):
        """Even with enforce=True char limits, count guard only warns — exit_code always 0."""
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"sessions": [{"summary": "s"} for _ in range(30)]})

        with _imports_via_seam(_mock_importlib_modules(_TEST_LIMITS_WARN)):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 0

    def test_per_branch_count_override(self, tmp_path, caplog):
        """per_branch overrides default count -> 6 sessions vs 5 cap warns."""
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"sessions": [{"summary": "s"} for _ in range(6)]})

        rollover_cfg = {
            "rollover": {
                "defaults": {"local": {"sessions": {"count": 20}}},
                "per_branch": {"hooks": {"local": {"sessions": {"count": 5}}}},
            },
        }

        with _imports_via_seam(_mock_importlib_modules(_TEST_LIMITS_WARN, rollover_cfg)):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 0
        assert "sessions has 6 entries, 1 over the rollover budget of 5" in caplog.text

    def test_config_loader_import_failure_silent(self, tmp_path, caplog):
        """config_loader import always fails -> no count warning, no crash, write allowed."""
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"sessions": [{"summary": "s"} for _ in range(30)]})

        el_real = memory_entry_limits
        entry_limits_mock = MagicMock()
        entry_limits_mock.load_entry_limits.return_value = _TEST_LIMITS_WARN
        entry_limits_mock.changed_entries = el_real.changed_entries

        def _side_effect(name):
            if "entry_limits" in name:
                return entry_limits_mock
            if "config_loader" in name:
                raise ImportError("no config_loader")
            return importlib.import_module(name)

        with _imports_via_seam(_side_effect):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 0
        assert "over the rollover budget" not in caplog.text


def _regular_sessions(n):
    """n ordinary session entries."""
    return [{"summary": f"s{i}"} for i in range(n)]


def _snapshot_sessions(n):
    """n auto-compact snapshot entries, as pre_compact_prep stamps them."""
    return [{"summary": f"snap{i}", "status": "auto-compact"} for i in range(n)]


class TestSessionSnapshotBudget:
    """Auto-compact snapshots never count against the regular session budget.

    The extractor has budgeted them separately for a while; this guard counted
    the combined array, so a branch sitting legally at 14 regular + 2 snapshots
    warned 16/15 on every .trinity write and rollover — correctly — archived
    nothing. The warning could never be satisfied, and it promised a trim that
    could never arrive. The two must agree on what counts.
    """

    def test_live_fleet_state_warns_nothing(self, tmp_path, caplog):
        """14 regular + 2 snapshots = 16 total, both budgets under cap -> silence.

        This is the exact state that emailed devpulse ten digests an hour.
        """
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"sessions": _regular_sessions(14) + _snapshot_sessions(2)})

        with _imports_via_seam(
            _mock_importlib_modules(_TEST_LIMITS_WARN, _ROLLOVER_CONFIG_FLEET),
        ):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 0
        assert "over the rollover budget" not in caplog.text

    def test_regular_sessions_over_budget_still_warns(self, tmp_path, caplog):
        """17 regular + 2 snapshots -> one warning about the 17, snapshots untouched."""
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"sessions": _regular_sessions(17) + _snapshot_sessions(2)})

        with _imports_via_seam(
            _mock_importlib_modules(_TEST_LIMITS_WARN, _ROLLOVER_CONFIG_FLEET),
        ):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 0
        assert "sessions has 17 entries, 2 over the rollover budget of 15" in caplog.text
        assert "auto-compact" not in caplog.text

    def test_snapshots_over_their_own_budget_warns(self, tmp_path, caplog):
        """Snapshots have a budget too — 5 against a cap of 3 is genuinely over."""
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"sessions": _regular_sessions(10) + _snapshot_sessions(5)})

        with _imports_via_seam(
            _mock_importlib_modules(_TEST_LIMITS_WARN, _ROLLOVER_CONFIG_FLEET),
        ):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 0
        assert "sessions (auto-compact snapshots) has 5 entries, 2 over the rollover budget of 3" in caplog.text

    def test_both_over_warn_separately(self, tmp_path, caplog):
        """Two independent budgets means two distinct lines, not one blurred count."""
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"sessions": _regular_sessions(20) + _snapshot_sessions(6)})

        with _imports_via_seam(
            _mock_importlib_modules(_TEST_LIMITS_WARN, _ROLLOVER_CONFIG_FLEET),
        ):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 0
        assert "sessions (auto-compact snapshots) has 6 entries, 3 over the rollover budget of 3" in caplog.text
        assert "sessions has 20 entries, 5 over the rollover budget of 15" in caplog.text

    def test_split_matches_extractor_on_junk_entries(self, tmp_path, caplog):
        """Non-dict junk counts as regular here and in the extractor alike.

        The extractor treats anything that is not a dict with
        status == "auto-compact" as a regular entry. Splitting differently would
        put the two back out of step in a subtler way.
        """
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        sessions = _regular_sessions(14) + _snapshot_sessions(2) + ["a bare string", None]
        content = json.dumps({"sessions": sessions})

        with _imports_via_seam(
            _mock_importlib_modules(_TEST_LIMITS_WARN, _ROLLOVER_CONFIG_FLEET),
        ):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 0
        assert "sessions has 16 entries, 1 over the rollover budget of 15" in caplog.text

    def test_split_applies_without_auto_compact_cap(self, tmp_path, caplog):
        """No auto_compact_cap configured -> snapshots still excluded from the regular count.

        The extractor's regular filter is unconditional. A config carrying only
        `count` must not resurrect the combined-array count.
        """
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"sessions": _regular_sessions(14) + _snapshot_sessions(2)})

        rollover_cfg = {
            "rollover": {
                "defaults": {"local": {"sessions": {"count": 15}}},
                "per_branch": {},
            },
        }

        with _imports_via_seam(_mock_importlib_modules(_TEST_LIMITS_WARN, rollover_cfg)):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 0
        assert "over the rollover budget" not in caplog.text

    def test_key_learnings_are_not_split(self, tmp_path, caplog):
        """Only sessions carries a snapshot budget — key_learnings counts every entry.

        The extractor does not split key_learnings, so neither may this guard.
        """
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        learnings = [{"value": f"v{i}"} for i in range(15)] + [{"value": "odd one", "status": "auto-compact"}]
        content = json.dumps({"key_learnings": learnings})

        with _imports_via_seam(
            _mock_importlib_modules(_TEST_LIMITS_WARN, _ROLLOVER_CONFIG_FLEET),
        ):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 0
        assert "key_learnings has 16 entries, 1 over the rollover budget of 15" in caplog.text


class TestSectionCountWording:
    """The line an operator reads must name whose file it is and promise only what happens."""

    def test_warning_names_the_branch_and_file(self, tmp_path, caplog):
        """The module tag is always captured_edit_gate — the line itself must say whose memory it is."""
        file_path = _make_trinity_path(tmp_path, "devpulse", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "devpulse")
        content = json.dumps({"sessions": _regular_sessions(17)})

        with _imports_via_seam(
            _mock_importlib_modules(_TEST_LIMITS_WARN, _ROLLOVER_CONFIG_FLEET),
        ):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 0
        assert "@devpulse .trinity/local.json" in caplog.text

    def test_warning_promises_only_what_rollover_does(self, tmp_path, caplog):
        """Names the actor, the count it archives, and where the entries go."""
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"sessions": _regular_sessions(18)})

        with _imports_via_seam(
            _mock_importlib_modules(_TEST_LIMITS_WARN, _ROLLOVER_CONFIG_FLEET),
        ):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 0
        assert "The @memory rollover hook archives the 3 oldest at the next PreCompact" in caplog.text
        assert "drone @memory search" in caplog.text

    def test_todos_over_the_pad_name_the_backlog_not_vectors(self, tmp_path, caplog):
        """todos roll now (DPLAN-0345) - to a backlog FILE, never to vectors.

        Until then they skipped this loop, because a trim claim was false. Now
        the claim is true, so the note is logged, but the vector clause ("recall
        them with drone @memory search") would be the false one for todos.
        """
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"todos": [{"task": f"t{i}"} for i in range(11)]})

        with (
            caplog.at_level(logging.INFO),
            _imports_via_seam(_mock_importlib_modules(_TEST_LIMITS_WARN)),
        ):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 0
        notes = [r.getMessage() for r in caplog.records if "todos has 11 entries" in r.getMessage()]
        assert len(notes) == 1
        assert "1 over the pad of 10" in notes[0]
        assert ".backup/todo/hooks/backlog.json" in notes[0]
        assert "drone @memory todo backlog @hooks" in notes[0]
        assert "drone @memory search" not in notes[0]


class TestTodosAdvisoryIsThrottled:
    """The owner's ruling 2026-08-19: a GENTLE reminder roughly every 10 turns,
    not one per qualifying edit. Being over the cap is a standing condition, so
    per-edit emission wrote 209 identical lines from one seat and tripped
    @trigger's repeat-signature escalation."""

    # Read through handle()'s answer to a Write of the todos (fleet green leg 9): the advisory
    # the model gets, or "" where the call is let through with nothing to say.

    @pytest.fixture(autouse=True)
    def _seat(self, tmp_path):
        self.file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        self.cwd = str(tmp_path / "src" / "aipass" / "hooks")

    @staticmethod
    def _over_cap():
        return {"todos": [{"task": f"todo {i}"} for i in range(12)]}

    def _written(self, doc, turn):
        with (
            _imports_via_seam(_mock_importlib_modules(_TEST_LIMITS_WARN)),
            patch.object(cadence, "current_turn", return_value=turn),
        ):
            result = handle(_hook_data(self.file_path, json.dumps(doc), cwd=self.cwd))
        if result == {"stdout": "", "exit_code": 0}:
            return ""
        return _advisory_context(result)

    def _advisory(self, turn):
        return self._written(self._over_cap(), turn)

    def test_first_edit_still_advises(self):
        advisory = self._advisory(1)
        assert "todos over limit" in advisory
        assert "12/10" in advisory

    def test_the_next_edit_in_the_same_turn_is_silent(self):
        self._advisory(1)
        assert self._advisory(1) == ""

    def test_twenty_edits_in_one_turn_produce_one_advisory(self):
        """The measured shape of the defect."""
        emitted = [self._advisory(4) for _ in range(20)]
        assert sum(1 for e in emitted if e) == 1

    def test_it_returns_after_about_ten_turns(self):
        self._advisory(1)
        assert self._advisory(1 + cadence.ADVISORY_PERIOD) != ""

    def test_the_log_line_throttles_with_the_stdout_line(self, caplog):
        """Escalation feeds on log repetition — silencing only stdout fixes
        nothing, which is why the warning lives behind the same gate."""
        self._advisory(1)
        caplog.clear()
        with caplog.at_level(logging.WARNING):
            assert self._advisory(2) == ""
        assert "todos over limit" not in caplog.text

    def test_the_warning_is_still_emitted_when_it_does_fire(self, caplog):
        with caplog.at_level(logging.WARNING):
            assert self._advisory(1) != ""
        assert "todos over limit" in caplog.text

    def test_under_cap_is_silent_and_spends_no_throttle(self):
        """A quiet branch must not burn its one emission on nothing — the next
        real over-cap edit has to advise immediately."""
        assert self._written({"todos": [{"task": "one"}]}, 1) == ""
        assert "todos over limit" in self._advisory(1)


class TestThrottleScopeGuard:
    """ONLY the todos count advisory softens. Hard blocks stay hard."""

    def test_entry_limit_block_is_not_throttled(self, tmp_path):
        """A block that goes quiet on the second edit would let over-cap
        entries through — the opposite of what the ruling asked for."""
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"todos": [{"task": "x" * 500}]})

        results = []
        for turn in (1, 2, 3):
            with (
                _imports_via_seam(_mock_importlib_modules(_TEST_LIMITS_ENFORCE)),
                patch.object(cadence, "current_turn", return_value=turn),
            ):
                results.append(handle(_hook_data(file_path, content, cwd=cwd)))
        assert all(r["exit_code"] == 2 for r in results), "a hard block went quiet under the throttle"
