# =================== AIPass ====================
# Name: test_edit_gate_trinity.py
# Version: 1.3.0
# Description: Tests for edit_gate .trinity char-limit + rollover-budget checks (FPLAN-0270 Phase 4)
# Branch: hooks
# Created: 2026-06-13
# Modified: 2026-08-27
# =============================================

"""Tests for edit_gate .trinity character-limit check (Write/Edit/MultiEdit)."""

import importlib
import json
import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

from aipass.hooks.apps.handlers.security import edit_gate
from aipass.hooks.apps.modules import cadence


_TEST_LIMITS_WARN = {
    "enabled": True,
    "enforce": False,
    "entry_types": {
        "key_learnings": {
            "file": "local.json",
            "container": "key_learnings",
            "kind": "dict",
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
        "todos": {
            "file": "local.json",
            "container": "todos",
            "kind": "list",
            "field": "task",
            "max_chars": 200,
        },
        "observations": {
            "file": "observations.json",
            "container": "observations",
            "kind": "list",
            "field": "note",
            "max_chars": 600,
        },
    },
}

_TEST_LIMITS_ENFORCE = {**_TEST_LIMITS_WARN, "enforce": True}

_TEST_LIMITS_DISABLED = {**_TEST_LIMITS_WARN, "enabled": False}


def _make_trinity_path(tmp_path, branch="hooks", filename="local.json"):
    """Build a .trinity file path with proper src/aipass/<branch>/.trinity/ structure."""
    trinity_dir = tmp_path / "src" / "aipass" / branch / ".trinity"
    trinity_dir.mkdir(parents=True, exist_ok=True)
    return str(trinity_dir / filename)


def _hook_data(file_path, content=None, tool_name="Write", cwd=None, **extra_input):
    """Build a hook_data dict for edit_gate.handle()."""
    tool_input = {"file_path": file_path}
    if content is not None:
        tool_input["content"] = content
    tool_input.update(extra_input)
    data = {
        "tool_name": tool_name,
        "tool_input": tool_input,
    }
    if cwd:
        data["cwd"] = cwd
    return data


def _mock_entry_limits(limits):
    """Create a mock module with controlled limits and real changed_entries."""
    el = importlib.import_module("aipass.memory.apps.handlers.json.entry_limits")
    mock_module = MagicMock()
    mock_module.load_entry_limits.return_value = limits
    mock_module.changed_entries = el.changed_entries
    return mock_module


_ROLLOVER_CONFIG_10 = {
    "rollover": {
        "defaults": {
            "local": {
                "sessions": {"count": 20},
                "key_learnings": {"count": 25},
                "todos": {"count": 10},
            },
            "observations": {
                "observations": {"count": 15},
            },
        },
        "per_branch": {},
    },
}


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


# Captured BEFORE any patch: the routers below fall through to the real
# importer, and calling importlib.import_module by name there re-enters the
# patch and recurses until the stack dies ("maximum recursion depth exceeded"
# surfacing as a fail-open advisory). Any module the handler imports that the
# router does not name would hit it.
_REAL_IMPORT_MODULE = importlib.import_module


def _mock_importlib_modules(limits, rollover_cfg=None):
    """Return a side_effect for importlib.import_module supporting both modules."""
    el_real = _REAL_IMPORT_MODULE("aipass.memory.apps.handlers.json.entry_limits")

    entry_limits_mock = MagicMock()
    entry_limits_mock.load_entry_limits.return_value = limits
    entry_limits_mock.changed_entries = el_real.changed_entries

    config_loader_mock = MagicMock()
    cfg = rollover_cfg if rollover_cfg is not None else _ROLLOVER_CONFIG_10
    config_loader_mock.load.return_value = cfg
    config_loader_mock.section.side_effect = lambda name: cfg.get(name, {})

    def side_effect(name):
        if "entry_limits" in name:
            return entry_limits_mock
        if "config_loader" in name:
            return config_loader_mock
        return _REAL_IMPORT_MODULE(name)

    return side_effect


class TestTrinityWriteClean:
    """Write to .trinity with entries under cap -> allowed."""

    def test_clean_write_local_json(self, tmp_path):
        """All entries under cap in local.json -> allowed."""
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps(
            {
                "key_learnings": {"learn_1": "short"},
                "sessions": [{"summary": "short session"}],
                "todos": [{"task": "short todo"}],
            }
        )

        with patch("importlib.import_module", return_value=_mock_entry_limits(_TEST_LIMITS_WARN)):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 0
        assert result["stdout"] == ""

    def test_clean_write_observations_json(self, tmp_path):
        """All entries under cap in observations.json -> allowed."""
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "hooks", "observations.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"observations": [{"note": "short observation"}]})

        with patch("importlib.import_module", return_value=_mock_entry_limits(_TEST_LIMITS_WARN)):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 0
        assert result["stdout"] == ""


class TestTrinityWriteOverLimitEnforced:
    """Write with over-limit entry + enforce=True -> blocked."""

    def test_block_over_limit_key_learning(self, tmp_path):
        """key_learning value 201 chars vs 200 cap -> blocked."""
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"key_learnings": {"learn_1": "x" * 201}})

        with patch("importlib.import_module", return_value=_mock_entry_limits(_TEST_LIMITS_ENFORCE)):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 2
        parsed = json.loads(result["stdout"])
        assert parsed["decision"] == "block"
        assert "key_learnings" in parsed["reason"]
        assert "201" in parsed["reason"]
        assert "200" in parsed["reason"]

    def test_block_over_limit_session_summary(self, tmp_path):
        """Session summary 301 chars vs 300 cap -> blocked."""
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"sessions": [{"summary": "x" * 301}]})

        with patch("importlib.import_module", return_value=_mock_entry_limits(_TEST_LIMITS_ENFORCE)):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 2
        parsed = json.loads(result["stdout"])
        assert parsed["decision"] == "block"
        assert "sessions" in parsed["reason"]

    def test_block_over_limit_todo(self, tmp_path):
        """Todo task 201 chars vs 200 cap -> blocked."""
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"todos": [{"task": "x" * 201}]})

        with patch("importlib.import_module", return_value=_mock_entry_limits(_TEST_LIMITS_ENFORCE)):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 2
        parsed = json.loads(result["stdout"])
        assert parsed["decision"] == "block"
        assert "todos" in parsed["reason"]

    def test_block_over_limit_observation(self, tmp_path):
        """Observation note 601 chars vs 600 cap -> blocked."""
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "hooks", "observations.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"observations": [{"note": "x" * 601}]})

        with patch("importlib.import_module", return_value=_mock_entry_limits(_TEST_LIMITS_ENFORCE)):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 2
        parsed = json.loads(result["stdout"])
        assert parsed["decision"] == "block"
        assert "observations" in parsed["reason"]

    def test_block_reason_includes_over_by(self, tmp_path):
        """Block reason includes the +over_by amount."""
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"key_learnings": {"k1": "x" * 210}})

        with patch("importlib.import_module", return_value=_mock_entry_limits(_TEST_LIMITS_ENFORCE)):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        parsed = json.loads(result["stdout"])
        assert "+10" in parsed["reason"]


class TestTrinityWriteOverLimitWarnOnly:
    """Write with over-limit entry + enforce=False -> allowed + warning logged."""

    def test_allow_over_limit_warn_only(self, tmp_path):
        """Over-limit with enforce=False -> exit_code 0, empty stdout."""
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"key_learnings": {"learn_1": "x" * 250}})

        with patch("importlib.import_module", return_value=_mock_entry_limits(_TEST_LIMITS_WARN)):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 0
        assert result["stdout"] == ""

    def test_warn_logs_over_limit_entries(self, tmp_path, caplog):
        """Over-limit with enforce=False -> warning logged with warn-only message."""
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"key_learnings": {"k1": "x" * 250}})

        with patch("importlib.import_module", return_value=_mock_entry_limits(_TEST_LIMITS_WARN)):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 0
        assert "warn only" in caplog.text


class TestTrinityWriteNonTrinity:
    """Write to non-.trinity file -> passes through unchanged."""

    def test_non_trinity_py_passthrough(self):
        """Write to a .py file -> no .trinity check, passes to diagnostics gate."""
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        result = handle(
            {
                "tool_name": "Write",
                "tool_input": {
                    "file_path": "/home/patrick/Projects/AIPass/src/aipass/hooks/apps/test.py",
                    "content": "print('hello')",
                },
                "cwd": "/home/patrick/Projects/AIPass/src/aipass/hooks",
            }
        )
        assert result["exit_code"] == 0

    def test_non_trinity_json_passthrough(self):
        """Write to a non-.trinity .json file -> allowed."""
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        result = handle(
            {
                "tool_name": "Write",
                "tool_input": {
                    "file_path": "/home/patrick/Projects/AIPass/src/aipass/hooks/apps/config.json",
                    "content": '{"key": "value"}',
                },
                "cwd": "/home/patrick/Projects/AIPass/src/aipass/hooks",
            }
        )
        assert result["exit_code"] == 0

    def test_trinity_passport_passthrough(self, tmp_path):
        """passport.json is in .trinity but NOT in _TRINITY_MEMORY_FILES."""
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        trinity_dir = tmp_path / "src" / "aipass" / "hooks" / ".trinity"
        trinity_dir.mkdir(parents=True, exist_ok=True)
        file_path = str(trinity_dir / "passport.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")

        result = handle(
            {
                "tool_name": "Write",
                "tool_input": {"file_path": file_path, "content": '{"identity": {}}'},
                "cwd": cwd,
            }
        )
        assert result["exit_code"] == 0


class TestTrinityWriteFailOpen:
    """Invalid or unparseable content -> fail-open (allowed)."""

    def test_invalid_json_content(self, tmp_path):
        """Non-JSON content -> JSONDecodeError caught, fail-open."""
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")

        with patch("importlib.import_module", return_value=_mock_entry_limits(_TEST_LIMITS_ENFORCE)):
            result = handle(_hook_data(file_path, "not valid json {{{", cwd=cwd))

        assert result["exit_code"] == 0
        assert result["stdout"] == ""

    def test_empty_content(self, tmp_path):
        """Empty content string -> JSONDecodeError caught, fail-open."""
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")

        with patch("importlib.import_module", return_value=_mock_entry_limits(_TEST_LIMITS_ENFORCE)):
            result = handle(_hook_data(file_path, "", cwd=cwd))

        assert result["exit_code"] == 0

    def test_import_failure_fail_open(self, tmp_path):
        """importlib.import_module raises ImportError -> caught, fail-open."""
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"key_learnings": {"k1": "x" * 500}})

        with patch("importlib.import_module", side_effect=ImportError("no module")):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 0


class TestTrinityWriteCharNotByte:
    """Character vs byte boundary: em-dash is 3 bytes / 1 char."""

    def test_em_dash_at_cap_allowed(self, tmp_path):
        """200 em-dashes = 200 chars (600 bytes) = exactly at cap -> allowed."""
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"key_learnings": {"k1": "—" * 200}})

        with patch("importlib.import_module", return_value=_mock_entry_limits(_TEST_LIMITS_ENFORCE)):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 0

    def test_em_dash_over_cap_blocked(self, tmp_path):
        """201 em-dashes = 201 chars (603 bytes) = over cap -> blocked."""
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"key_learnings": {"k1": "—" * 201}})

        with patch("importlib.import_module", return_value=_mock_entry_limits(_TEST_LIMITS_ENFORCE)):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 2
        parsed = json.loads(result["stdout"])
        assert parsed["decision"] == "block"


class TestTrinityEditClean:
    """Edit to .trinity with entries under cap -> allowed."""

    def test_edit_clean_entry(self, tmp_path):
        """Edit changes a key_learning to a short value -> allowed."""
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        existing = {"key_learnings": {"k1": "old value"}}
        Path(file_path).write_text(json.dumps(existing), encoding="utf-8")

        with patch("importlib.import_module", return_value=_mock_entry_limits(_TEST_LIMITS_ENFORCE)):
            result = handle(
                _hook_data(
                    file_path,
                    tool_name="Edit",
                    cwd=cwd,
                    old_string='"old value"',
                    new_string='"new short value"',
                )
            )

        assert result["exit_code"] == 0
        assert result["stdout"] == ""


class TestTrinityEditOverLimit:
    """Edit producing over-limit entry -> blocked (enforce) or warned."""

    def test_edit_over_limit_enforce_blocks(self, tmp_path):
        """Edit pushes key_learning over 200 cap, enforce=True -> blocked."""
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        existing = {"key_learnings": {"k1": "short"}}
        Path(file_path).write_text(json.dumps(existing), encoding="utf-8")

        with patch("importlib.import_module", return_value=_mock_entry_limits(_TEST_LIMITS_ENFORCE)):
            result = handle(
                _hook_data(
                    file_path,
                    tool_name="Edit",
                    cwd=cwd,
                    old_string='"short"',
                    new_string='"' + "x" * 250 + '"',
                )
            )

        assert result["exit_code"] == 2
        parsed = json.loads(result["stdout"])
        assert parsed["decision"] == "block"
        assert "key_learnings" in parsed["reason"]

    def test_edit_over_limit_warn_allows(self, tmp_path, caplog):
        """Edit pushes key_learning over cap, enforce=False -> allowed + warn."""
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        existing = {"key_learnings": {"k1": "short"}}
        Path(file_path).write_text(json.dumps(existing), encoding="utf-8")

        with patch("importlib.import_module", return_value=_mock_entry_limits(_TEST_LIMITS_WARN)):
            result = handle(
                _hook_data(
                    file_path,
                    tool_name="Edit",
                    cwd=cwd,
                    old_string='"short"',
                    new_string='"' + "x" * 250 + '"',
                )
            )

        assert result["exit_code"] == 0
        assert "warn only" in caplog.text

    def test_edit_modifies_entry_to_exceed_cap(self, tmp_path):
        """Edit modifies existing entry from under cap to over cap -> blocked."""
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        existing = {"key_learnings": {"k1": "a" * 100}}
        Path(file_path).write_text(json.dumps(existing), encoding="utf-8")

        with patch("importlib.import_module", return_value=_mock_entry_limits(_TEST_LIMITS_ENFORCE)):
            result = handle(
                _hook_data(
                    file_path,
                    tool_name="Edit",
                    cwd=cwd,
                    old_string='"' + "a" * 100 + '"',
                    new_string='"' + "b" * 250 + '"',
                )
            )

        assert result["exit_code"] == 2
        parsed = json.loads(result["stdout"])
        assert parsed["decision"] == "block"


class TestTrinityEditFailOpen:
    """Edit fail-open: old_string not found, invalid JSON result."""

    def test_edit_old_string_not_found_fail_open(self, tmp_path):
        """old_string absent from file -> _resolve_after_text returns None -> allow."""
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        existing = {"key_learnings": {"k1": "hello"}}
        Path(file_path).write_text(json.dumps(existing), encoding="utf-8")

        with patch("importlib.import_module", return_value=_mock_entry_limits(_TEST_LIMITS_ENFORCE)):
            result = handle(
                _hook_data(
                    file_path,
                    tool_name="Edit",
                    cwd=cwd,
                    old_string="NONEXISTENT",
                    new_string="x" * 500,
                )
            )

        assert result["exit_code"] == 0

    def test_edit_producing_invalid_json_fail_open(self, tmp_path):
        """Edit breaks JSON structure -> JSONDecodeError caught -> allow."""
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        existing = {"key_learnings": {"k1": "hello"}}
        Path(file_path).write_text(json.dumps(existing), encoding="utf-8")

        with patch("importlib.import_module", return_value=_mock_entry_limits(_TEST_LIMITS_ENFORCE)):
            result = handle(
                _hook_data(
                    file_path,
                    tool_name="Edit",
                    cwd=cwd,
                    old_string='"hello"',
                    new_string='"hello',
                )
            )

        assert result["exit_code"] == 0

    def test_edit_nonexistent_file_allows(self, tmp_path):
        """Edit to a .trinity file that doesn't exist yet -> allow."""
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")

        with patch("importlib.import_module", return_value=_mock_entry_limits(_TEST_LIMITS_ENFORCE)):
            result = handle(
                _hook_data(
                    file_path,
                    tool_name="Edit",
                    cwd=cwd,
                    old_string="anything",
                    new_string="x" * 500,
                )
            )

        assert result["exit_code"] == 0


class TestTrinityEditReplaceAll:
    """Edit with replace_all=True vs False."""

    def test_replace_all_true(self, tmp_path):
        """replace_all=True replaces all occurrences -> checks result."""
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        existing = {"key_learnings": {"k1": "aaa", "k2": "aaa"}}
        Path(file_path).write_text(json.dumps(existing), encoding="utf-8")

        with patch("importlib.import_module", return_value=_mock_entry_limits(_TEST_LIMITS_ENFORCE)):
            result = handle(
                _hook_data(
                    file_path,
                    tool_name="Edit",
                    cwd=cwd,
                    old_string='"aaa"',
                    new_string='"' + "x" * 250 + '"',
                    replace_all=True,
                )
            )

        assert result["exit_code"] == 2
        parsed = json.loads(result["stdout"])
        assert parsed["decision"] == "block"

    def test_replace_all_false_single(self, tmp_path):
        """replace_all=False replaces first occurrence only -> one entry over."""
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        existing = {"key_learnings": {"k1": "aaa", "k2": "bbb"}}
        Path(file_path).write_text(json.dumps(existing), encoding="utf-8")

        with patch("importlib.import_module", return_value=_mock_entry_limits(_TEST_LIMITS_ENFORCE)):
            result = handle(
                _hook_data(
                    file_path,
                    tool_name="Edit",
                    cwd=cwd,
                    old_string='"aaa"',
                    new_string='"' + "x" * 250 + '"',
                    replace_all=False,
                )
            )

        assert result["exit_code"] == 2


class TestTrinityEditCharNotByte:
    """Character vs byte boundary via Edit tool."""

    def test_em_dash_edit_at_cap_allowed(self, tmp_path):
        """Edit producing 200 em-dashes (200 chars, 600 bytes) -> at cap -> allowed."""
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        existing = {"key_learnings": {"k1": "short"}}
        Path(file_path).write_text(json.dumps(existing), encoding="utf-8")

        with patch("importlib.import_module", return_value=_mock_entry_limits(_TEST_LIMITS_ENFORCE)):
            result = handle(
                _hook_data(
                    file_path,
                    tool_name="Edit",
                    cwd=cwd,
                    old_string='"short"',
                    new_string='"' + "—" * 200 + '"',
                )
            )

        assert result["exit_code"] == 0

    def test_em_dash_edit_over_cap_blocked(self, tmp_path):
        """Edit producing 201 em-dashes (201 chars, 603 bytes) -> over cap -> blocked."""
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        existing = {"key_learnings": {"k1": "short"}}
        Path(file_path).write_text(json.dumps(existing), encoding="utf-8")

        with patch("importlib.import_module", return_value=_mock_entry_limits(_TEST_LIMITS_ENFORCE)):
            result = handle(
                _hook_data(
                    file_path,
                    tool_name="Edit",
                    cwd=cwd,
                    old_string='"short"',
                    new_string='"' + "—" * 201 + '"',
                )
            )

        assert result["exit_code"] == 2


class TestTrinityMultiEdit:
    """MultiEdit: sequential edits, ordering, over-limit detection."""

    def test_multiedit_clean(self, tmp_path):
        """MultiEdit with both edits under cap -> allowed."""
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        existing = {"key_learnings": {"k1": "aaa", "k2": "bbb"}}
        Path(file_path).write_text(json.dumps(existing), encoding="utf-8")

        edits = [
            {"old_string": '"aaa"', "new_string": '"new_a"'},
            {"old_string": '"bbb"', "new_string": '"new_b"'},
        ]
        with patch("importlib.import_module", return_value=_mock_entry_limits(_TEST_LIMITS_ENFORCE)):
            result = handle(
                {
                    "tool_name": "MultiEdit",
                    "tool_input": {"file_path": file_path, "edits": edits},
                    "cwd": cwd,
                }
            )

        assert result["exit_code"] == 0

    def test_multiedit_over_limit_blocked(self, tmp_path):
        """MultiEdit where second edit produces over-limit entry -> blocked."""
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        existing = {"key_learnings": {"k1": "aaa", "k2": "bbb"}}
        Path(file_path).write_text(json.dumps(existing), encoding="utf-8")

        edits = [
            {"old_string": '"aaa"', "new_string": '"short"'},
            {"old_string": '"bbb"', "new_string": '"' + "x" * 250 + '"'},
        ]
        with patch("importlib.import_module", return_value=_mock_entry_limits(_TEST_LIMITS_ENFORCE)):
            result = handle(
                {
                    "tool_name": "MultiEdit",
                    "tool_input": {"file_path": file_path, "edits": edits},
                    "cwd": cwd,
                }
            )

        assert result["exit_code"] == 2
        parsed = json.loads(result["stdout"])
        assert parsed["decision"] == "block"

    def test_multiedit_ordering_dependent(self, tmp_path):
        """MultiEdit where edit 2 depends on edit 1's output -> applied sequentially."""
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        existing = {"key_learnings": {"k1": "alpha"}}
        Path(file_path).write_text(json.dumps(existing), encoding="utf-8")

        edits = [
            {"old_string": '"alpha"', "new_string": '"beta"'},
            {"old_string": '"beta"', "new_string": '"gamma"'},
        ]
        with patch("importlib.import_module", return_value=_mock_entry_limits(_TEST_LIMITS_ENFORCE)):
            result = handle(
                {
                    "tool_name": "MultiEdit",
                    "tool_input": {"file_path": file_path, "edits": edits},
                    "cwd": cwd,
                }
            )

        assert result["exit_code"] == 0

    def test_multiedit_old_string_not_found_fail_open(self, tmp_path):
        """MultiEdit where an old_string is missing -> fail-open."""
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        existing = {"key_learnings": {"k1": "hello"}}
        Path(file_path).write_text(json.dumps(existing), encoding="utf-8")

        edits = [
            {"old_string": '"hello"', "new_string": '"world"'},
            {"old_string": '"NONEXISTENT"', "new_string": '"' + "x" * 500 + '"'},
        ]
        with patch("importlib.import_module", return_value=_mock_entry_limits(_TEST_LIMITS_ENFORCE)):
            result = handle(
                {
                    "tool_name": "MultiEdit",
                    "tool_input": {"file_path": file_path, "edits": edits},
                    "cwd": cwd,
                }
            )

        assert result["exit_code"] == 0

    def test_multiedit_replace_all_in_edit(self, tmp_path):
        """MultiEdit with replace_all=True in one edit -> replaces all occurrences."""
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        existing = {"key_learnings": {"k1": "zzz", "k2": "zzz"}}
        Path(file_path).write_text(json.dumps(existing), encoding="utf-8")

        edits = [
            {"old_string": '"zzz"', "new_string": '"' + "x" * 250 + '"', "replace_all": True},
        ]
        with patch("importlib.import_module", return_value=_mock_entry_limits(_TEST_LIMITS_ENFORCE)):
            result = handle(
                {
                    "tool_name": "MultiEdit",
                    "tool_input": {"file_path": file_path, "edits": edits},
                    "cwd": cwd,
                }
            )

        assert result["exit_code"] == 2


class TestTrinityEditUnrelatedFieldOnFatFile:
    """REVERSED TWICE, and the second reversal restores the original answer.

    Written as "THE critical no-false-reject test", flipped to expect a block on
    2026-08-27 when the fleet had converged, flipped back on 2026-08-30. The
    round trip is the lesson, not an embarrassment: the 08-27 premise was that
    drift had been cured fleet-wide, and a clause justified by a temporary state
    has to be re-read when that state ends. @memory measured that it had ended —
    drift RECURS (@ai_mail carried three over-cap learnings the same evening,
    @seedgo one) — and that refusing carried debt deadlocks the archiver:
    a file cannot get smaller because it is too big.

    So the rule is @memory's entry_limits 1.6.0 rule, and this gate now keeps
    the same one: a write is refused for what it AUTHORS, never for what it
    CARRIES. Blocking an unrelated edit over a fat entry the agent did not write
    was never a standard worth having — it is unsatisfiable by any allowed
    action, which is the species this branch has now fixed three times.
    """

    def test_unrelated_edit_on_fat_file_is_allowed(self, tmp_path):
        """Fat legacy sessions + key_learnings, edit touches only a todo -> ALLOWED."""
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")

        fat_sessions = [{"summary": "x" * 300} for _ in range(13)]
        fat_learnings = {f"k{i}": "y" * 500 for i in range(10)}
        existing = {
            "key_learnings": fat_learnings,
            "sessions": fat_sessions,
            "todos": [{"task": "old todo"}],
        }
        Path(file_path).write_text(json.dumps(existing), encoding="utf-8")

        with patch("importlib.import_module", return_value=_mock_entry_limits(_TEST_LIMITS_ENFORCE)):
            result = handle(
                _hook_data(
                    file_path,
                    tool_name="Edit",
                    cwd=cwd,
                    old_string='"old todo"',
                    new_string='"new todo"',
                )
            )

        assert result["exit_code"] == 0, "an unrelated edit was refused for entries this write did not author"
        assert result["stdout"] == "", "an allowed write must not print a refusal"

    def test_unrelated_edit_plus_new_over_limit_blocked(self, tmp_path):
        """Fat file, but Edit ALSO adds a new over-limit entry -> blocked."""
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")

        existing = {
            "key_learnings": {"old_fat": "y" * 500},
            "todos": [{"task": "old todo"}],
        }
        Path(file_path).write_text(json.dumps(existing), encoding="utf-8")

        with patch("importlib.import_module", return_value=_mock_entry_limits(_TEST_LIMITS_ENFORCE)):
            result = handle(
                _hook_data(
                    file_path,
                    tool_name="Edit",
                    cwd=cwd,
                    old_string='"old todo"',
                    new_string='"' + "z" * 250 + '"',
                )
            )

        assert result["exit_code"] == 2


class TestTrinityEditUnchangedLegacy:
    """REVERSED BACK (2026-08-30): an untouched over-limit entry is carried, not refused.

    "Unchanged" does not mean "legacy" and it does not mean "written and not yet
    caught" either — it means THIS WRITE DID NOT AUTHOR IT, which is the only
    thing a write gate can honestly judge. Detection of drift already on disk
    belongs to drone @memory lint, which reads whole files; a PreToolUse gate
    sees only the next write and is structurally blind to drift that arrived
    through Bash — as this gate's own refusal text says out loud.
    """

    def test_edit_unchanged_over_limit_is_allowed(self, tmp_path):
        """Over-limit key_learning untouched by the Edit -> carried, allowed."""
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        existing = {
            "key_learnings": {"old_fat": "x" * 500, "k2": "short"},
            "todos": [{"task": "my todo"}],
        }
        Path(file_path).write_text(json.dumps(existing), encoding="utf-8")

        with patch("importlib.import_module", return_value=_mock_entry_limits(_TEST_LIMITS_ENFORCE)):
            result = handle(
                _hook_data(
                    file_path,
                    tool_name="Edit",
                    cwd=cwd,
                    old_string='"short"',
                    new_string='"still short"',
                )
            )

        assert result["exit_code"] == 0, "a write was refused for an entry it did not author"


class TestTrinityWriteDisabled:
    """Feature disabled via enabled:false -> passthrough."""

    def test_disabled_allows_over_limit(self, tmp_path):
        """enabled=False -> size check skipped, over-limit entry allowed."""
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"key_learnings": {"k1": "x" * 500}})

        with patch("importlib.import_module", return_value=_mock_entry_limits(_TEST_LIMITS_DISABLED)):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 0


class TestTrinityWriteUnchangedLegacy:
    """REVERSED BACK (2026-08-30): rollover-safety is universal, not todos-only.

    This is the exact shape that broke @memory's lane in production: the
    extractor removed a tail, wrote the SMALLER document back, and the write was
    refused over an entry in the head it never touched — failing identically
    every 20 minutes for three hours. The archiver is always on the losing side
    of that trade. Carrying an over-cap entry forward while adding a clean one
    is a write that authored nothing over cap, and it is allowed.
    """

    def test_unchanged_over_limit_is_allowed(self, tmp_path):
        """Over-limit entry identical in before/after -> carried, allowed."""
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")

        existing = {"key_learnings": {"old_fat": "x" * 500}}
        Path(file_path).write_text(json.dumps(existing), encoding="utf-8")

        after = {"key_learnings": {"old_fat": "x" * 500, "new_clean": "short"}}
        content = json.dumps(after)

        with patch("importlib.import_module", return_value=_mock_entry_limits(_TEST_LIMITS_ENFORCE)):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 0, "a rollover-shaped write was refused for what it carried"

    def test_changed_legacy_blocked(self, tmp_path):
        """Legacy entry modified (text changed, still over-limit) -> blocked."""
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")

        existing = {"key_learnings": {"old_fat": "x" * 500}}
        Path(file_path).write_text(json.dumps(existing), encoding="utf-8")

        after = {"key_learnings": {"old_fat": "y" * 500}}
        content = json.dumps(after)

        with patch("importlib.import_module", return_value=_mock_entry_limits(_TEST_LIMITS_ENFORCE)):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 2
        parsed = json.loads(result["stdout"])
        assert parsed["decision"] == "block"


class TestTrinityTodosCountAdvisory:
    """Non-blocking advisory when todos exceed rollover count limit."""

    def test_todos_over_limit_advisory_write(self, tmp_path):
        """Write with 11 todos (limit 10) -> exit_code 0 + advisory stdout."""
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"todos": [{"task": f"todo {i}"} for i in range(11)]})

        with patch("importlib.import_module", side_effect=_mock_importlib_modules(_TEST_LIMITS_WARN)):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 0
        assert "todos over limit" in result["stdout"]
        assert "11/10" in result["stdout"]

    def test_todos_under_limit_no_advisory(self, tmp_path):
        """Write with 5 todos (limit 10) -> exit_code 0, empty stdout."""
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"todos": [{"task": f"todo {i}"} for i in range(5)]})

        with patch("importlib.import_module", side_effect=_mock_importlib_modules(_TEST_LIMITS_WARN)):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 0
        assert result["stdout"] == ""

    def test_todos_at_limit_no_advisory(self, tmp_path):
        """Write with exactly 10 todos (limit 10) -> no advisory."""
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"todos": [{"task": f"todo {i}"} for i in range(10)]})

        with patch("importlib.import_module", side_effect=_mock_importlib_modules(_TEST_LIMITS_WARN)):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 0
        assert result["stdout"] == ""

    def test_todos_advisory_via_edit(self, tmp_path):
        """Edit that adds a todo pushing count over limit -> advisory."""
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        existing = {"todos": [{"task": f"todo {i}"} for i in range(10)]}
        Path(file_path).write_text(json.dumps(existing), encoding="utf-8")
        new_todos = [{"task": f"todo {i}"} for i in range(11)]

        with patch(
            "importlib.import_module",
            side_effect=_mock_importlib_modules(_TEST_LIMITS_WARN),
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
        assert "todos over limit" in result["stdout"]
        assert "11/10" in result["stdout"]

    def test_todos_advisory_never_blocks(self, tmp_path):
        """Even with enforce=True, todos count advisory has exit_code 0."""
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"todos": [{"task": f"todo {i}"} for i in range(15)]})

        with patch(
            "importlib.import_module",
            side_effect=_mock_importlib_modules(_TEST_LIMITS_ENFORCE),
        ):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 0
        assert "todos over limit" in result["stdout"]
        assert "15/10" in result["stdout"]

    def test_todos_advisory_observations_json_skip(self, tmp_path):
        """observations.json never triggers todos advisory."""
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "hooks", "observations.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps(
            {
                "observations": [{"note": "obs"}],
                "todos": [{"task": f"t{i}"} for i in range(20)],
            }
        )

        with patch(
            "importlib.import_module",
            side_effect=_mock_importlib_modules(_TEST_LIMITS_WARN),
        ):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 0
        assert result["stdout"] == ""

    def test_todos_advisory_config_loader_failure_silent(self, tmp_path):
        """config_loader import fails -> no advisory, no crash, save allowed."""
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"todos": [{"task": f"todo {i}"} for i in range(15)]})

        el_real = importlib.import_module("aipass.memory.apps.handlers.json.entry_limits")
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

        with patch("importlib.import_module", side_effect=_side_effect):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 0
        assert result["stdout"] == ""

    def test_char_limit_blocks_before_advisory(self, tmp_path):
        """Char-limit block takes priority over todos advisory."""
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps(
            {
                "key_learnings": {"k1": "x" * 250},
                "todos": [{"task": f"todo {i}"} for i in range(15)],
            }
        )

        with patch(
            "importlib.import_module",
            side_effect=_mock_importlib_modules(_TEST_LIMITS_ENFORCE),
        ):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 2
        parsed = json.loads(result["stdout"])
        assert parsed["decision"] == "block"

    def test_todos_advisory_logs_warning(self, tmp_path, caplog):
        """Advisory emits a logger.warning with the over-limit message."""
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"todos": [{"task": f"todo {i}"} for i in range(12)]})

        with patch(
            "importlib.import_module",
            side_effect=_mock_importlib_modules(_TEST_LIMITS_WARN),
        ):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 0
        assert "todos over limit" in caplog.text
        assert "12/10" in caplog.text

    def test_todos_advisory_per_branch_override(self, tmp_path):
        """per_branch override sets limit to 5 for hooks -> 6 todos triggers advisory."""
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"todos": [{"task": f"todo {i}"} for i in range(6)]})

        rollover_cfg = {
            "rollover": {
                "defaults": {"local": {"todos": {"count": 10}}},
                "per_branch": {"hooks": {"local": {"todos": {"count": 5}}}},
            },
        }

        with patch(
            "importlib.import_module",
            side_effect=_mock_importlib_modules(_TEST_LIMITS_WARN, rollover_cfg),
        ):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 0
        assert "6/5" in result["stdout"]

    def test_no_todos_container_no_advisory(self, tmp_path):
        """local.json with no todos key -> no advisory."""
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"key_learnings": {"k1": "short"}})

        with patch(
            "importlib.import_module",
            side_effect=_mock_importlib_modules(_TEST_LIMITS_WARN),
        ):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 0
        assert result["stdout"] == ""


class TestTrinityNewestFirst:
    """DPLAN-0278: sessions[]/key_learnings[] must be inserted at index 0, number = max+1."""

    def test_clean_prepend_allowed(self, tmp_path):
        """New session inserted at index 0 with number = max+1 -> allowed."""
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        existing = {"sessions": [{"number": 5, "summary": "old"}]}
        Path(file_path).write_text(json.dumps(existing), encoding="utf-8")

        after = {"sessions": [{"number": 6, "summary": "new"}, {"number": 5, "summary": "old"}]}
        content = json.dumps(after)

        with patch("importlib.import_module", return_value=_mock_entry_limits(_TEST_LIMITS_WARN)):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 0
        assert result["stdout"] == ""

    def test_tail_append_blocked(self, tmp_path):
        """New session appended after the existing tail entry -> blocked."""
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        existing = {"sessions": [{"number": 5, "summary": "old"}]}
        Path(file_path).write_text(json.dumps(existing), encoding="utf-8")

        after = {"sessions": [{"number": 5, "summary": "old"}, {"number": 6, "summary": "new"}]}
        content = json.dumps(after)

        with patch("importlib.import_module", return_value=_mock_entry_limits(_TEST_LIMITS_WARN)):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 2
        parsed = json.loads(result["stdout"])
        assert parsed["decision"] == "block"
        assert "newest-first" in parsed["reason"]

    def test_number_not_greater_than_max_blocked(self, tmp_path):
        """New entry prepended at index 0 but number <= max existing -> blocked."""
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        existing = {"sessions": [{"number": 5, "summary": "old"}]}
        Path(file_path).write_text(json.dumps(existing), encoding="utf-8")

        after = {"sessions": [{"number": 5, "summary": "duplicate number"}, {"number": 5, "summary": "old"}]}
        content = json.dumps(after)

        with patch("importlib.import_module", return_value=_mock_entry_limits(_TEST_LIMITS_WARN)):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 2
        parsed = json.loads(result["stdout"])
        assert parsed["decision"] == "block"
        assert "number" in parsed["reason"]

    def test_key_learnings_tail_append_blocked(self, tmp_path):
        """key_learnings appended after the tail -> blocked."""
        from aipass.hooks.apps.handlers.security.edit_gate import handle

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

        with patch("importlib.import_module", return_value=_mock_entry_limits(_TEST_LIMITS_WARN)):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 2
        parsed = json.loads(result["stdout"])
        assert parsed["decision"] == "block"

    def test_first_write_no_before_file_skips_check(self, tmp_path):
        """No existing file (first write) -> nothing to compare against, allowed."""
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"sessions": [{"number": 1, "summary": "first"}]})

        with patch("importlib.import_module", return_value=_mock_entry_limits(_TEST_LIMITS_WARN)):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 0

    def test_shrinking_array_skips_check(self, tmp_path):
        """Rollover-style shrink (fewer entries after) -> not treated as an append, allowed."""
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        existing = {"sessions": [{"number": 6, "summary": "keep"}, {"number": 5, "summary": "drop"}]}
        Path(file_path).write_text(json.dumps(existing), encoding="utf-8")

        after = {"sessions": [{"number": 6, "summary": "keep"}]}
        content = json.dumps(after)

        with patch("importlib.import_module", return_value=_mock_entry_limits(_TEST_LIMITS_WARN)):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 0

    def test_newest_first_checked_even_when_limits_disabled(self, tmp_path):
        """Tail-append still blocked even with enabled=False (independent gate)."""
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        existing = {"sessions": [{"number": 5, "summary": "old"}]}
        Path(file_path).write_text(json.dumps(existing), encoding="utf-8")

        after = {"sessions": [{"number": 5, "summary": "old"}, {"number": 6, "summary": "new"}]}
        content = json.dumps(after)

        with patch("importlib.import_module", return_value=_mock_entry_limits(_TEST_LIMITS_DISABLED)):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 2

    def test_unrelated_field_edit_no_new_entries_allowed(self, tmp_path):
        """Edit that doesn't add any new numbered entries -> newest-first check no-ops."""
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        existing = {"sessions": [{"number": 5, "summary": "old"}], "todos": [{"task": "old todo"}]}
        Path(file_path).write_text(json.dumps(existing), encoding="utf-8")

        with patch("importlib.import_module", return_value=_mock_entry_limits(_TEST_LIMITS_WARN)):
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
        from aipass.hooks.apps.handlers.security.edit_gate import handle

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

        with patch("importlib.import_module", return_value=_mock_entry_limits(_TEST_LIMITS_WARN)):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 0
        assert result["stdout"] == ""

    def test_legacy_session_number_tail_append_blocked(self, tmp_path):
        """The ordering check is schema-independent — legacy tail append still blocks."""
        from aipass.hooks.apps.handlers.security.edit_gate import handle

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

        with patch("importlib.import_module", return_value=_mock_entry_limits(_TEST_LIMITS_WARN)):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 2
        assert json.loads(result["stdout"])["decision"] == "block"

    def test_legacy_number_not_greater_than_max_blocked(self, tmp_path):
        """Monotonicity is enforced within the legacy schema too, not just skipped."""
        from aipass.hooks.apps.handlers.security.edit_gate import handle

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

        with patch("importlib.import_module", return_value=_mock_entry_limits(_TEST_LIMITS_WARN)):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 2
        assert "must be greater than the max existing" in json.loads(result["stdout"])["reason"]

    def test_number_key_wins_over_session_number(self, tmp_path):
        """When both keys are present, 'number' is authoritative — session_number is ignored."""
        from aipass.hooks.apps.handlers.security.edit_gate import handle

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

        with patch("importlib.import_module", return_value=_mock_entry_limits(_TEST_LIMITS_WARN)):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 0

    def test_cross_schema_migration_allowed(self, tmp_path):
        """Legacy existing entries, modern 'number' on the new one -> allowed."""
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        existing = {"sessions": [{"session_number": 5, "summary": "old"}]}
        Path(file_path).write_text(json.dumps(existing), encoding="utf-8")

        after = {"sessions": [{"number": 6, "summary": "new"}, {"session_number": 5, "summary": "old"}]}
        content = json.dumps(after)

        with patch("importlib.import_module", return_value=_mock_entry_limits(_TEST_LIMITS_WARN)):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 0

    def test_wholly_unnumbered_array_passes_through(self, tmp_path):
        """No recognized ordinal anywhere -> monotonicity can't be judged, so don't block."""
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        existing = {"sessions": [{"summary": "old"}]}
        Path(file_path).write_text(json.dumps(existing), encoding="utf-8")

        after = {"sessions": [{"summary": "new"}, {"summary": "old"}]}
        content = json.dumps(after)

        with patch("importlib.import_module", return_value=_mock_entry_limits(_TEST_LIMITS_WARN)):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 0

    def test_unnumbered_array_still_ordering_checked(self, tmp_path):
        """Pass-through covers the number check only — tail appends still block."""
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        existing = {"sessions": [{"summary": "old"}]}
        Path(file_path).write_text(json.dumps(existing), encoding="utf-8")

        after = {"sessions": [{"summary": "old"}, {"summary": "new"}]}
        content = json.dumps(after)

        with patch("importlib.import_module", return_value=_mock_entry_limits(_TEST_LIMITS_WARN)):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 2
        assert "newest-first" in json.loads(result["stdout"])["reason"]

    def test_unnumbered_new_entry_against_numbered_existing_blocked(self, tmp_path):
        """Dropping the ordinal when the file has one is a real violation — block, and
        name the accepted keys so there is a path to comply."""
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        existing = {"sessions": [{"number": 5, "summary": "old"}]}
        Path(file_path).write_text(json.dumps(existing), encoding="utf-8")

        after = {"sessions": [{"summary": "new"}, {"number": 5, "summary": "old"}]}
        content = json.dumps(after)

        with patch("importlib.import_module", return_value=_mock_entry_limits(_TEST_LIMITS_WARN)):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 2
        reason = json.loads(result["stdout"])["reason"]
        assert "no ordinal" in reason
        assert "session_number" in reason

    def test_key_learnings_legacy_schema_prepend_allowed(self, tmp_path):
        """The alias applies to every newest-first array, not just sessions."""
        from aipass.hooks.apps.handlers.security.edit_gate import handle

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

        with patch("importlib.import_module", return_value=_mock_entry_limits(_TEST_LIMITS_WARN)):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 0


class TestOverBudgetSeverity:
    """Compass #273 (Patrick, 2026-08-14): severity follows design intent.

    Over-budget is not wrong behaviour, it is behaviour we chose to have — the
    message itself says nothing is lost, because @memory's rollover archives the
    overflow at the next PreCompact. Logged as WARNING it entered @trigger's
    escalation lane: 8 signatures, 579 occurrences, 10 of the 62 digests the lane
    has ever sent. The level is a field, not prose; the text stays as it is.
    """

    def _over_budget_records(self, caplog):
        return [r for r in caplog.records if "over the rollover budget" in r.getMessage()]

    def test_over_budget_logs_at_info_not_warning(self, tmp_path, caplog):
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"sessions": [{"summary": "s"} for _ in range(21)]})

        with caplog.at_level(logging.INFO):
            with patch("importlib.import_module", side_effect=_mock_importlib_modules(_TEST_LIMITS_WARN)):
                result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 0
        records = self._over_budget_records(caplog)
        assert records, "the operator line must still be emitted — this is a level change, not a mute"
        assert all(r.levelno == logging.INFO for r in records)
        assert not [r for r in records if r.levelno >= logging.WARNING]

    def test_auto_compact_snapshot_class_also_logs_at_info(self, tmp_path, caplog):
        """All three call sites are one class — a fix that misses one keeps 1/3 of the lane."""
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"sessions": _regular_sessions(10) + _snapshot_sessions(5)})

        with caplog.at_level(logging.INFO):
            with patch(
                "importlib.import_module",
                side_effect=_mock_importlib_modules(_TEST_LIMITS_WARN, _ROLLOVER_CONFIG_FLEET),
            ):
                handle(_hook_data(file_path, content, cwd=cwd))

        records = self._over_budget_records(caplog)
        assert records
        assert all(r.levelno == logging.INFO for r in records)

    def test_generic_section_class_also_logs_at_info(self, tmp_path, caplog):
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "hooks", "observations.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"observations": [{"note": "n"} for _ in range(16)]})

        with caplog.at_level(logging.INFO):
            with patch("importlib.import_module", side_effect=_mock_importlib_modules(_TEST_LIMITS_WARN)):
                handle(_hook_data(file_path, content, cwd=cwd))

        records = self._over_budget_records(caplog)
        assert records
        assert all(r.levelno == logging.INFO for r in records)

    def test_the_emitter_is_not_named_after_the_severity_it_no_longer_uses(self):
        """The function name is a severity claim in prose: leaving it invites a re-raise."""
        from aipass.hooks.apps.handlers.security import edit_gate

        assert hasattr(edit_gate, "_note_over_budget")
        assert not hasattr(edit_gate, "_warn_over_budget")

    def test_the_over_limit_entry_class_stays_at_warning(self, tmp_path, caplog):
        """Guard on the reclass: ONE class moves, not the file.

        The over-limit entry advisory (edit_gate.py:181) is a different animal —
        it names a cap the author must act on, and nothing archives it for them.
        It stays WARNING. If a future edit mutes this file wholesale, this fails.
        """
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"sessions": [{"summary": "x" * 5000}]})

        with caplog.at_level(logging.INFO):
            with patch("importlib.import_module", side_effect=_mock_importlib_modules(_TEST_LIMITS_WARN)):
                handle(_hook_data(file_path, content, cwd=cwd))

        over_limit = [r for r in caplog.records if "over-limit .trinity entry" in r.getMessage()]
        assert over_limit
        assert all(r.levelno == logging.WARNING for r in over_limit)


class TestSectionCountGuard:
    """Soft count guard: warn (never block) when rolling sections exceed count cap."""

    def test_sessions_over_count_warns(self, tmp_path, caplog):
        """21 sessions vs 20 cap -> warning logged, write still allowed."""
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"sessions": [{"summary": "s"} for _ in range(21)]})

        with patch("importlib.import_module", side_effect=_mock_importlib_modules(_TEST_LIMITS_WARN)):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 0
        assert "@hooks .trinity/local.json — sessions has 21 entries, 1 over the rollover budget of 20" in caplog.text

    def test_key_learnings_over_count_warns(self, tmp_path, caplog):
        """26 key_learnings vs 25 cap -> warning logged."""
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"key_learnings": [{"value": "v"} for _ in range(26)]})

        with patch("importlib.import_module", side_effect=_mock_importlib_modules(_TEST_LIMITS_WARN)):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 0
        assert "key_learnings has 26 entries, 1 over the rollover budget of 25" in caplog.text

    def test_observations_over_count_warns(self, tmp_path, caplog):
        """16 observations vs 15 cap -> warning logged."""
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "hooks", "observations.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"observations": [{"note": "n"} for _ in range(16)]})

        with patch("importlib.import_module", side_effect=_mock_importlib_modules(_TEST_LIMITS_WARN)):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 0
        assert (
            "@hooks .trinity/observations.json — observations has 16 entries, 1 over the rollover budget of 15"
            in caplog.text
        )

    def test_under_count_no_warning(self, tmp_path, caplog):
        """10 sessions vs 20 cap -> no warning."""
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"sessions": [{"summary": "s"} for _ in range(10)]})

        with patch("importlib.import_module", side_effect=_mock_importlib_modules(_TEST_LIMITS_WARN)):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 0
        assert "over the rollover budget" not in caplog.text

    def test_at_count_no_warning(self, tmp_path, caplog):
        """Exactly 20 sessions vs 20 cap -> no warning (only > triggers)."""
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"sessions": [{"summary": "s"} for _ in range(20)]})

        with patch("importlib.import_module", side_effect=_mock_importlib_modules(_TEST_LIMITS_WARN)):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 0
        assert "over the rollover budget" not in caplog.text

    def test_count_guard_never_blocks(self, tmp_path):
        """Even with enforce=True char limits, count guard only warns — exit_code always 0."""
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"sessions": [{"summary": "s"} for _ in range(30)]})

        with patch("importlib.import_module", side_effect=_mock_importlib_modules(_TEST_LIMITS_WARN)):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 0

    def test_per_branch_count_override(self, tmp_path, caplog):
        """per_branch overrides default count -> 6 sessions vs 5 cap warns."""
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"sessions": [{"summary": "s"} for _ in range(6)]})

        rollover_cfg = {
            "rollover": {
                "defaults": {"local": {"sessions": {"count": 20}}},
                "per_branch": {"hooks": {"local": {"sessions": {"count": 5}}}},
            },
        }

        with patch("importlib.import_module", side_effect=_mock_importlib_modules(_TEST_LIMITS_WARN, rollover_cfg)):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 0
        assert "sessions has 6 entries, 1 over the rollover budget of 5" in caplog.text

    def test_config_loader_import_failure_silent(self, tmp_path, caplog):
        """config_loader import always fails -> no count warning, no crash, write allowed."""
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"sessions": [{"summary": "s"} for _ in range(30)]})

        el_real = importlib.import_module("aipass.memory.apps.handlers.json.entry_limits")
        entry_limits_mock = MagicMock()
        entry_limits_mock.load_entry_limits.return_value = _TEST_LIMITS_WARN
        entry_limits_mock.changed_entries = el_real.changed_entries

        def _side_effect(name):
            if "entry_limits" in name:
                return entry_limits_mock
            if "config_loader" in name:
                raise ImportError("no config_loader")
            return importlib.import_module(name)

        with patch("importlib.import_module", side_effect=_side_effect):
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
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"sessions": _regular_sessions(14) + _snapshot_sessions(2)})

        with patch(
            "importlib.import_module",
            side_effect=_mock_importlib_modules(_TEST_LIMITS_WARN, _ROLLOVER_CONFIG_FLEET),
        ):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 0
        assert "over the rollover budget" not in caplog.text

    def test_regular_sessions_over_budget_still_warns(self, tmp_path, caplog):
        """17 regular + 2 snapshots -> one warning about the 17, snapshots untouched."""
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"sessions": _regular_sessions(17) + _snapshot_sessions(2)})

        with patch(
            "importlib.import_module",
            side_effect=_mock_importlib_modules(_TEST_LIMITS_WARN, _ROLLOVER_CONFIG_FLEET),
        ):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 0
        assert "sessions has 17 entries, 2 over the rollover budget of 15" in caplog.text
        assert "auto-compact" not in caplog.text

    def test_snapshots_over_their_own_budget_warns(self, tmp_path, caplog):
        """Snapshots have a budget too — 5 against a cap of 3 is genuinely over."""
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"sessions": _regular_sessions(10) + _snapshot_sessions(5)})

        with patch(
            "importlib.import_module",
            side_effect=_mock_importlib_modules(_TEST_LIMITS_WARN, _ROLLOVER_CONFIG_FLEET),
        ):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 0
        assert "sessions (auto-compact snapshots) has 5 entries, 2 over the rollover budget of 3" in caplog.text

    def test_both_over_warn_separately(self, tmp_path, caplog):
        """Two independent budgets means two distinct lines, not one blurred count."""
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"sessions": _regular_sessions(20) + _snapshot_sessions(6)})

        with patch(
            "importlib.import_module",
            side_effect=_mock_importlib_modules(_TEST_LIMITS_WARN, _ROLLOVER_CONFIG_FLEET),
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
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        sessions = _regular_sessions(14) + _snapshot_sessions(2) + ["a bare string", None]
        content = json.dumps({"sessions": sessions})

        with patch(
            "importlib.import_module",
            side_effect=_mock_importlib_modules(_TEST_LIMITS_WARN, _ROLLOVER_CONFIG_FLEET),
        ):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 0
        assert "sessions has 16 entries, 1 over the rollover budget of 15" in caplog.text

    def test_split_applies_without_auto_compact_cap(self, tmp_path, caplog):
        """No auto_compact_cap configured -> snapshots still excluded from the regular count.

        The extractor's regular filter is unconditional. A config carrying only
        `count` must not resurrect the combined-array count.
        """
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"sessions": _regular_sessions(14) + _snapshot_sessions(2)})

        rollover_cfg = {
            "rollover": {
                "defaults": {"local": {"sessions": {"count": 15}}},
                "per_branch": {},
            },
        }

        with patch("importlib.import_module", side_effect=_mock_importlib_modules(_TEST_LIMITS_WARN, rollover_cfg)):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 0
        assert "over the rollover budget" not in caplog.text

    def test_key_learnings_are_not_split(self, tmp_path, caplog):
        """Only sessions carries a snapshot budget — key_learnings counts every entry.

        The extractor does not split key_learnings, so neither may this guard.
        """
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        learnings = [{"value": f"v{i}"} for i in range(15)] + [{"value": "odd one", "status": "auto-compact"}]
        content = json.dumps({"key_learnings": learnings})

        with patch(
            "importlib.import_module",
            side_effect=_mock_importlib_modules(_TEST_LIMITS_WARN, _ROLLOVER_CONFIG_FLEET),
        ):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 0
        assert "key_learnings has 16 entries, 1 over the rollover budget of 15" in caplog.text


class TestSectionCountWording:
    """The line an operator reads must name whose file it is and promise only what happens."""

    def test_warning_names_the_branch_and_file(self, tmp_path, caplog):
        """The module tag is always captured_edit_gate — the line itself must say whose memory it is."""
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "devpulse", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "devpulse")
        content = json.dumps({"sessions": _regular_sessions(17)})

        with patch(
            "importlib.import_module",
            side_effect=_mock_importlib_modules(_TEST_LIMITS_WARN, _ROLLOVER_CONFIG_FLEET),
        ):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 0
        assert "@devpulse .trinity/local.json" in caplog.text

    def test_warning_promises_only_what_rollover_does(self, tmp_path, caplog):
        """Names the actor, the count it archives, and where the entries go."""
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"sessions": _regular_sessions(18)})

        with patch(
            "importlib.import_module",
            side_effect=_mock_importlib_modules(_TEST_LIMITS_WARN, _ROLLOVER_CONFIG_FLEET),
        ):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 0
        assert "The @memory rollover hook archives the 3 oldest at the next PreCompact" in caplog.text
        assert "drone @memory search" in caplog.text

    def test_todos_never_claim_a_rollover_trim(self, tmp_path, caplog):
        """todos do not roll. Only the advisory speaks for them, and it says prune.

        A `count` under local.todos used to reach the generic loop and promise a
        trim at the next PreCompact — a trim that has never existed for todos.
        """
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"todos": [{"task": f"t{i}"} for i in range(11)]})

        with patch("importlib.import_module", side_effect=_mock_importlib_modules(_TEST_LIMITS_WARN)):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 0
        assert "todos do not auto-roll" in result["stdout"]
        assert "over the rollover budget" not in caplog.text


class TestTodosAdvisoryIsThrottled:
    """Patrick's ruling 2026-08-19: a GENTLE reminder roughly every 10 turns,
    not one per qualifying edit. Being over the cap is a standing condition, so
    per-edit emission wrote 209 identical lines from one seat and tripped
    @trigger's repeat-signature escalation."""

    @staticmethod
    def _over_cap():
        return {"todos": [{"task": f"todo {i}"} for i in range(12)]}

    def _advisory(self, turn):
        with (
            patch("importlib.import_module", side_effect=_mock_importlib_modules(_TEST_LIMITS_WARN)),
            patch.object(cadence, "current_turn", return_value=turn),
        ):
            return edit_gate._todos_count_advisory(self._over_cap(), "hooks")

    def test_first_edit_still_advises(self):
        assert "todos over limit" in self._advisory(1)

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
        with (
            patch("importlib.import_module", side_effect=_mock_importlib_modules(_TEST_LIMITS_WARN)),
            patch.object(cadence, "current_turn", return_value=1),
        ):
            assert edit_gate._todos_count_advisory({"todos": [{"task": "one"}]}, "hooks") == ""
        assert "todos over limit" in self._advisory(1)


class TestThrottleScopeGuard:
    """ONLY the todos count advisory softens. Hard blocks stay hard."""

    def test_entry_limit_block_is_not_throttled(self, tmp_path):
        """A block that goes quiet on the second edit would let over-cap
        entries through — the opposite of what the ruling asked for."""
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"todos": [{"task": "x" * 500}]})

        results = []
        for turn in (1, 2, 3):
            with (
                patch("importlib.import_module", side_effect=_mock_importlib_modules(_TEST_LIMITS_ENFORCE)),
                patch.object(cadence, "current_turn", return_value=turn),
            ):
                results.append(handle(_hook_data(file_path, content, cwd=cwd)))
        assert all(r["exit_code"] == 2 for r in results), "a hard block went quiet under the throttle"


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
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"key_learnings": [{"number": 1, "date": "2026-08-25", "learning": "x" * 500}]})

        with patch("importlib.import_module", return_value=_mock_entry_limits(_LIMITS_LIST_ENFORCE)):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 2, "renamed field dodged the cap"
        parsed = json.loads(result["stdout"])
        assert parsed["decision"] == "block"
        assert "key_learnings" in parsed["reason"]
        assert "value" in parsed["reason"], "refusal must name the field it could not find"

    def test_missing_field_is_blocked(self, tmp_path):
        """Canonical field absent with no replacement at all — same refusal."""
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"sessions": [{"number": 9, "date": "2026-08-25"}]})

        with patch("importlib.import_module", return_value=_mock_entry_limits(_LIMITS_LIST_ENFORCE)):
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
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"key_learnings": [{"number": 1, "learning": "short"}]})

        with patch("importlib.import_module", return_value=_mock_entry_limits(_LIMITS_LIST_ENFORCE)):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 2

    def test_canonical_field_still_passes(self, tmp_path):
        """Guard against over-refusal: the correct shape must stay allowed."""
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"key_learnings": [{"number": 1, "date": "2026-08-25", "value": "fine"}]})

        with patch("importlib.import_module", return_value=_mock_entry_limits(_LIMITS_LIST_ENFORCE)):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 0

    def test_empty_string_is_not_a_missing_field(self, tmp_path):
        """`""` means there is no text — compliant. Only an ABSENT key refuses."""
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"key_learnings": [{"number": 1, "value": ""}]})

        with patch("importlib.import_module", return_value=_mock_entry_limits(_LIMITS_LIST_ENFORCE)):
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
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        legacy = {"number": 1, "date": "2026-08-01", "learning": "x" * 500}
        Path(file_path).write_text(json.dumps({"key_learnings": [legacy]}), encoding="utf-8")

        # Same legacy entry, plus a NEW canonical one on top.
        content = json.dumps({"key_learnings": [{"number": 2, "date": "2026-08-25", "value": "new and legal"}, legacy]})

        with patch("importlib.import_module", return_value=_mock_entry_limits(_LIMITS_LIST_ENFORCE)):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 0, "a write was refused for a drifted entry it did not author"

    def test_editing_a_legacy_entry_refuses_it(self, tmp_path):
        """Touch the drifted entry and you own its shape."""
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        legacy = {"number": 1, "date": "2026-08-01", "learning": "x" * 500}
        Path(file_path).write_text(json.dumps({"key_learnings": [legacy]}), encoding="utf-8")

        edited = json.dumps({"key_learnings": [{"number": 1, "date": "2026-08-01", "learning": "y" * 500}]})

        with patch("importlib.import_module", return_value=_mock_entry_limits(_LIMITS_LIST_ENFORCE)):
            result = handle(_hook_data(file_path, edited, cwd=cwd))

        assert result["exit_code"] == 2, "an edited legacy entry kept its exemption"

    def test_new_legacy_shaped_entry_is_refused(self, tmp_path):
        """Carrying one legacy entry must not license adding ten more."""
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        legacy = {"number": 1, "date": "2026-08-01", "learning": "x" * 500}
        Path(file_path).write_text(json.dumps({"key_learnings": [legacy]}), encoding="utf-8")

        content = json.dumps({"key_learnings": [{"number": 2, "date": "2026-08-25", "learning": "z" * 500}, legacy]})

        with patch("importlib.import_module", return_value=_mock_entry_limits(_LIMITS_LIST_ENFORCE)):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 2, "a NEW entry in the legacy shape inherited the exemption"


class TestUnreadableFieldWarnMode:
    """enforce=False keeps the refusal advisory, and says why in the log."""

    def test_warn_mode_allows_but_logs_field_name(self, tmp_path, caplog):
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"key_learnings": [{"number": 1, "learning": "x" * 500}]})

        with caplog.at_level(logging.WARNING):
            with patch("importlib.import_module", return_value=_mock_entry_limits(_LIMITS_LIST_WARN)):
                result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 0
        assert "value" in caplog.text


class TestUnmeasurableReasonIsRendered:
    """@memory's unmeasurable refusal must not render as '0/300 chars (+0)'.

    A refusal that prints zeros reads like a bug in the gate. The reason it
    carries is the whole point of refusing loudly.
    """

    def test_non_string_field_reason_reaches_the_agent(self, tmp_path):
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"sessions": [{"number": 1, "summary": [{"title": "a", "detail": "b"}]}]})

        with patch("importlib.import_module", return_value=_mock_entry_limits(_LIMITS_LIST_ENFORCE)):
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
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"key_learnings": [{"number": 1, "learning": "x" * 500}]})

        with patch("importlib.import_module", return_value=_mock_entry_limits(_LIMITS_LIST_ENFORCE)):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 2
        reason = json.loads(result["stdout"])["reason"]
        assert reason.count("no 'value' field") == 1, f"violation reported {reason.count(chr(39) + 'value' + chr(39))}x"

    def test_distinct_entries_both_survive_dedupe(self, tmp_path):
        """Dedupe must key on container too — two types can share key '0'."""
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps(
            {
                "key_learnings": [{"number": 1, "learning": "x" * 500}],
                "sessions": [{"number": 1, "chronicle": "y" * 500}],
            }
        )

        with patch("importlib.import_module", return_value=_mock_entry_limits(_LIMITS_LIST_ENFORCE)):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        reason = json.loads(result["stdout"])["reason"]
        assert "no 'value' field" in reason
        assert "no 'summary' field" in reason, "dedupe swallowed a distinct container's violation"

    def test_over_cap_and_missing_field_both_reported(self, tmp_path):
        """Different species on different entries must both reach the agent."""
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"key_learnings": [{"number": 2, "value": "x" * 201}, {"number": 1, "learning": "short"}]})

        with patch("importlib.import_module", return_value=_mock_entry_limits(_LIMITS_LIST_ENFORCE)):
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
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        legacy = {"number": 1, "date": "2026-08-01", "learning": "x" * 500}
        _write_before(file_path, {"key_learnings": [legacy], "todos": []})

        content = json.dumps(
            {"key_learnings": [{"number": 2, "date": "2026-08-27", "value": "clean"}, legacy], "todos": []}
        )

        with patch("importlib.import_module", return_value=_mock_entry_limits(_LIMITS_TODOS)):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 0, "a write was refused for a drifted entry it did not author"
        assert result["stdout"] == "", "carried drift must be reported in the log, never in a block"

    def test_untouched_drifted_todo_still_passes(self, tmp_path):
        """THE CAUTION: a drifted todo must not brick a write to another section.

        67 todos were restored by mail after the push defect and owners
        reshape them on their own schedule. Blocking every write until they do
        would make the exemption brick the branch it protects.
        """
        from aipass.hooks.apps.handlers.security.edit_gate import handle

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

        with patch("importlib.import_module", return_value=_mock_entry_limits(_LIMITS_TODOS)):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 0, "a drifted todo blocked a write to a different section"

    def test_new_drifted_todo_still_refused(self, tmp_path):
        """The exemption covers what is ALREADY ON DISK, never a fresh one."""
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        drifted_todo = {"priority": "medium", "status": "open", "chore": "reshape me"}
        _write_before(file_path, {"todos": [drifted_todo]})

        content = json.dumps({"todos": [{"priority": "low", "status": "open", "chore": "brand new"}, drifted_todo]})

        with patch("importlib.import_module", return_value=_mock_entry_limits(_LIMITS_TODOS)):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 2, "a NEW drifted todo inherited the on-disk exemption"

    def test_editing_a_drifted_todo_refuses_it(self, tmp_path):
        """Touch it and you own its shape — same rule as everywhere else."""
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        _write_before(file_path, {"todos": [{"priority": "medium", "status": "open", "chore": "old text"}]})

        content = json.dumps({"todos": [{"priority": "medium", "status": "open", "chore": "new text"}]})

        with patch("importlib.import_module", return_value=_mock_entry_limits(_LIMITS_TODOS)):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 2, "an edited drifted todo kept its exemption"


class TestAuthoredVsCarriedUnit:
    """Unit-level, because handle() cannot see this half fail.

    Mutation found the gap (2026-08-30): making _missing_field_violations
    return NOTHING left all 115 end-to-end tests green. The union in
    _evaluate_limits adds @memory's real changed_entries, which refuses a new
    missing-field entry through its own lane — so every through-handle() test
    that proves "authored drift is refused" passes for the wrong reason and
    would keep passing if this checker were deleted outright. The overlap is
    deliberate; a test suite that cannot tell the two halves apart is not.
    """

    def test_a_new_missing_field_entry_is_refused(self):
        """The authored half, isolated from @memory's overlapping refusal."""
        before = {"key_learnings": []}
        after = {"key_learnings": [{"number": 1, "date": "2026-08-30", "learning": "renamed field"}]}

        hits = edit_gate._missing_field_violations(before, after, _LIMITS_TODOS)

        assert len(hits) == 1, "a newly authored entry with no 'value' field was not refused"
        assert hits[0]["reason"] == "missing_field"
        assert hits[0]["field"] == "value"
        assert hits[0]["key"] == "0", "keys are rendered as strings — @memory's six-key contract"

    def test_an_identical_on_disk_entry_is_carried(self):
        """Byte-identical to disk: this write did not author it."""
        legacy = {"number": 1, "date": "2026-08-01", "learning": "renamed field"}

        hits = edit_gate._missing_field_violations(
            {"key_learnings": [legacy]}, {"key_learnings": [legacy]}, _LIMITS_TODOS
        )

        assert hits == [], "a write was refused for an entry it carried unchanged"

    def test_carrying_one_does_not_license_authoring_another(self):
        """The mixed case names the new entry and only the new entry.

        This is the test the two survivors could not have been caught without:
        it needs the checker to both skip AND refuse in the same call, so no
        blanket answer — refuse everything, refuse nothing — satisfies it.
        """
        legacy = {"number": 1, "date": "2026-08-01", "learning": "carried"}
        fresh = {"number": 2, "date": "2026-08-30", "learning": "authored in the same shape"}

        hits = edit_gate._missing_field_violations(
            {"key_learnings": [legacy]}, {"key_learnings": [fresh, legacy]}, _LIMITS_TODOS
        )

        assert len(hits) == 1, f"expected exactly the authored entry to be refused, got {hits}"
        assert hits[0]["key"] == "0", "the refusal named the carried entry's position, not the authored one"

    def test_a_prepend_does_not_reauthor_the_whole_file(self):
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

        hits = edit_gate._missing_field_violations(
            {"key_learnings": carried}, {"key_learnings": [clean_head, *carried]}, _LIMITS_TODOS
        )

        assert hits == [], f"a prepend re-authored entries it only shifted: {hits}"
