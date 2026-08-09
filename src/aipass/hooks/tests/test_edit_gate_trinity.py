# =================== AIPass ====================
# Name: test_edit_gate_trinity.py
# Version: 1.1.0
# Description: Tests for edit_gate .trinity char-limit + rollover-budget checks (FPLAN-0270 Phase 4)
# Branch: hooks
# Created: 2026-06-13
# Modified: 2026-08-08
# =============================================

"""Tests for edit_gate .trinity character-limit check (Write/Edit/MultiEdit)."""

import importlib
import json
from pathlib import Path
from unittest.mock import MagicMock, patch


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


def _mock_importlib_modules(limits, rollover_cfg=None):
    """Return a side_effect for importlib.import_module supporting both modules."""
    el_real = importlib.import_module("aipass.memory.apps.handlers.json.entry_limits")

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
        return importlib.import_module(name)

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
    """THE critical no-false-reject test: unrelated edit on a file with legacy fat entries."""

    def test_unrelated_edit_on_fat_file_allowed(self, tmp_path):
        """File has 4000-char sessions + 500-char key_learnings (all legacy).
        Edit only touches a small todo. enforce=True. MUST be ALLOWED."""
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

        assert result["exit_code"] == 0
        assert result["stdout"] == ""

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
    """Edit that doesn't change legacy over-limit entries -> allowed."""

    def test_edit_unchanged_legacy_allowed(self, tmp_path):
        """Legacy over-limit key_learning unchanged by Edit -> allowed."""
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

        assert result["exit_code"] == 0


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
    """Unchanged legacy over-limit entry in Write -> not blocked (rollover-safe)."""

    def test_unchanged_legacy_allowed(self, tmp_path):
        """Legacy over-limit entry unchanged between before/after -> allowed."""
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")

        existing = {"key_learnings": {"old_fat": "x" * 500}}
        Path(file_path).write_text(json.dumps(existing), encoding="utf-8")

        after = {"key_learnings": {"old_fat": "x" * 500, "new_clean": "short"}}
        content = json.dumps(after)

        with patch("importlib.import_module", return_value=_mock_entry_limits(_TEST_LIMITS_ENFORCE)):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 0

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
