# =================== AIPass ====================
# Name: test_engine.py
# Version: 1.0.0
# Description: Tests for hook engine dispatch logic
# Branch: hooks
# Layer: tests
# Created: 2026-05-18
# Modified: 2026-05-18
# =============================================

"""Tests for hook engine dispatch logic."""

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from aipass.hooks.apps.modules.engine import (
    dispatch,
    _matches,
    _run_hook,
    _log,
)
from aipass.hooks.apps.handlers.config.loader import find_project_config
from aipass.hooks.apps.handlers.config.trust_registry import enroll


@pytest.fixture(autouse=True)
def _no_real_trust_banners():
    """dispatch() now runs both trust banners unconditionally on UserPromptSubmit.

    Neutralize by default so the many dispatch()-calling tests in this file
    never do a real CWD-to-home walk against the actual ~/.aipass registry.
    Tests that want to exercise the banners override with their own nested
    patch, which takes precedence inside its `with` block.
    """
    with (
        patch("aipass.hooks.apps.handlers.config.loader.trust_break_banner", return_value=None),
        patch("aipass.hooks.apps.handlers.config.loader.never_enrolled_banner", return_value=None),
    ):
        yield


class TestMatches:
    """Tests for _matches() matcher logic."""

    def test_empty_matcher_always_matches(self):
        assert _matches("", "Edit") is True

    def test_empty_matcher_matches_empty_value(self):
        assert _matches("", "") is True

    def test_single_match(self):
        assert _matches("Edit", "Edit") is True

    def test_single_no_match(self):
        assert _matches("Edit", "Bash") is False

    def test_pipe_delimited_match_first(self):
        assert _matches("Edit|Write|MultiEdit", "Edit") is True

    def test_pipe_delimited_match_middle(self):
        assert _matches("Edit|Write|MultiEdit", "Write") is True

    def test_pipe_delimited_match_last(self):
        assert _matches("Edit|Write|MultiEdit", "MultiEdit") is True

    def test_pipe_delimited_no_match(self):
        assert _matches("Edit|Write|MultiEdit", "Bash") is False

    def test_partial_name_does_not_match(self):
        assert _matches("Edit", "MultiEdit") is False

    def test_manual_auto_compact(self):
        assert _matches("manual|auto", "manual") is True
        assert _matches("manual|auto", "auto") is True


class TestRunHook:
    """Tests for _run_hook() subprocess execution."""

    def test_successful_hook(self, mock_subprocess, mock_logger):
        mock_subprocess.return_value = MagicMock(returncode=0, stdout="hello", stderr="")
        result = _run_hook("echo hello", "stdin_data")
        assert result["exit_code"] == 0
        assert result["stdout"] == "hello"
        assert result["elapsed_ms"] >= 0

    def test_hook_with_nonzero_exit(self, mock_subprocess, mock_logger):
        mock_subprocess.return_value = MagicMock(returncode=1, stdout="", stderr="error")
        result = _run_hook("false", "")
        assert result["exit_code"] == 1
        assert result["stderr"] == "error"

    def test_hook_timeout(self, mock_subprocess, mock_logger):
        mock_subprocess.side_effect = subprocess.TimeoutExpired("cmd", 30)
        result = _run_hook("sleep 999", "", timeout_s=30)
        assert result["exit_code"] == -1
        assert result["stderr"] == "TIMEOUT"

    def test_hook_os_error(self, mock_subprocess, mock_logger):
        mock_subprocess.side_effect = OSError("No such file")
        result = _run_hook("/nonexistent", "")
        assert result["exit_code"] == -1
        assert "No such file" in result["stderr"]

    def test_custom_timeout(self, mock_subprocess, mock_logger):
        mock_subprocess.return_value = MagicMock(returncode=0, stdout="", stderr="")
        _run_hook("cmd", "", timeout_s=120)
        mock_subprocess.assert_called_once()
        assert mock_subprocess.call_args.kwargs["timeout"] == 120

    def test_default_timeout_is_30(self, mock_subprocess, mock_logger):
        mock_subprocess.return_value = MagicMock(returncode=0, stdout="", stderr="")
        _run_hook("cmd", "")
        assert mock_subprocess.call_args.kwargs["timeout"] == 30


class TestDispatch:
    """Tests for dispatch() core logic."""

    def test_hooks_disabled_returns_empty(self, mock_logger):
        config = {"hooks_enabled": False}
        with patch("aipass.hooks.apps.modules.engine._log"):
            result = dispatch("UserPromptSubmit", "{}", config)
        assert result[0] == ""
        assert result[1] == 0

    def test_no_hooks_for_event_returns_empty(self, mock_logger):
        config = {"hooks_enabled": True}
        with patch("aipass.hooks.apps.modules.engine._log"):
            result = dispatch("UnknownEvent", "{}", config)
        assert result[0] == ""
        assert result[1] == 0

    def test_disabled_hook_skipped(self, mock_logger):
        config = {
            "hooks_enabled": True,
            "PreToolUse": {
                "disabled_hook": {
                    "enabled": False,
                    "command": "echo fail",
                    "matcher": "",
                }
            },
        }
        with patch("aipass.hooks.apps.modules.engine._log"):
            with patch("aipass.hooks.apps.modules.engine._run_hook") as mock_run:
                result = dispatch("PreToolUse", '{"tool_name":"Edit"}', config)
        mock_run.assert_not_called()
        assert result[0] == ""
        assert result[1] == 0

    def test_matcher_filters_hooks(self, mock_logger):
        config = {
            "hooks_enabled": True,
            "PreToolUse": {
                "edit_only": {
                    "enabled": True,
                    "command": "echo matched",
                    "matcher": "Edit|Write",
                }
            },
        }
        with patch("aipass.hooks.apps.modules.engine._log"):
            with patch("aipass.hooks.apps.modules.engine._run_hook") as mock_run:
                mock_run.return_value = {"exit_code": 0, "stdout": "matched", "stderr": "", "elapsed_ms": 10}
                dispatch("PreToolUse", '{"tool_name":"Bash"}', config)
        mock_run.assert_not_called()

    def test_matching_hook_fires(self, mock_logger):
        config = {
            "hooks_enabled": True,
            "PreToolUse": {
                "edit_hook": {
                    "enabled": True,
                    "command": "echo edit_output",
                    "matcher": "Edit|Write",
                }
            },
        }
        with patch("aipass.hooks.apps.modules.engine._log"):
            with patch("aipass.hooks.apps.modules.engine._run_hook") as mock_run:
                mock_run.return_value = {"exit_code": 0, "stdout": "edit_output", "stderr": "", "elapsed_ms": 10}
                result = dispatch("PreToolUse", '{"tool_name":"Edit"}', config)
        mock_run.assert_called_once()
        assert "edit_output" in result[0]
        assert result[1] == 0

    def test_multiple_hooks_concatenate_output(self, mock_logger):
        config = {
            "hooks_enabled": True,
            "UserPromptSubmit": {
                "hook_a": {"enabled": True, "command": "echo A", "matcher": ""},
                "hook_b": {"enabled": True, "command": "echo B", "matcher": ""},
            },
        }
        with patch("aipass.hooks.apps.modules.engine._log"):
            with patch("aipass.hooks.apps.modules.engine._run_hook") as mock_run:
                mock_run.side_effect = [
                    {"exit_code": 0, "stdout": "output_A", "stderr": "", "elapsed_ms": 10},
                    {"exit_code": 0, "stdout": "output_B", "stderr": "", "elapsed_ms": 10},
                ]
                result = dispatch("UserPromptSubmit", '{"user_prompt":"test"}', config)
        assert "output_A" in result[0]
        assert "output_B" in result[0]
        assert result[1] == 0

    def test_exit2_with_block_json_bails(self, mock_logger):
        config = {
            "hooks_enabled": True,
            "PreToolUse": {
                "blocker": {"enabled": True, "command": "block_cmd", "matcher": ""},
                "after_block": {"enabled": True, "command": "should_not_run", "matcher": ""},
            },
        }
        block_json = json.dumps({"decision": "block", "reason": "test block"})
        with patch("aipass.hooks.apps.modules.engine._log"):
            with patch("aipass.hooks.apps.modules.engine._run_hook") as mock_run:
                mock_run.return_value = {"exit_code": 2, "stdout": block_json, "stderr": "", "elapsed_ms": 10}
                result = dispatch("PreToolUse", '{"tool_name":"Edit"}', config)
        assert mock_run.call_count == 1
        parsed = json.loads(result[0])
        assert parsed["decision"] == "block"
        assert result[1] == 2

    def test_exit2_without_json_is_crash_not_block(self, mock_logger):
        config = {
            "hooks_enabled": True,
            "PreToolUse": {
                "crashed": {"enabled": True, "command": "crash_cmd", "matcher": ""},
                "next_hook": {"enabled": True, "command": "echo survived", "matcher": ""},
            },
        }
        with patch("aipass.hooks.apps.modules.engine._log"):
            with patch("aipass.hooks.apps.modules.engine._run_hook") as mock_run:
                mock_run.side_effect = [
                    {"exit_code": 2, "stdout": "", "stderr": "file not found", "elapsed_ms": 10},
                    {"exit_code": 0, "stdout": "survived", "stderr": "", "elapsed_ms": 10},
                ]
                result = dispatch("PreToolUse", '{"tool_name":"Edit"}', config)
        assert mock_run.call_count == 2
        assert "survived" in result[0]
        assert result[1] == 0

    def test_hook_with_custom_timeout(self, mock_logger):
        config = {
            "hooks_enabled": True,
            "PreCompact": {
                "slow_hook": {
                    "enabled": True,
                    "command": "slow_cmd",
                    "matcher": "",
                    "timeout": 120,
                }
            },
        }
        with patch("aipass.hooks.apps.modules.engine._log"):
            with patch("aipass.hooks.apps.modules.engine._run_hook") as mock_run:
                mock_run.return_value = {"exit_code": 0, "stdout": "", "stderr": "", "elapsed_ms": 50}
                dispatch("PreCompact", '{"type":"manual"}', config)
        mock_run.assert_called_once_with("slow_cmd", '{"type":"manual"}', timeout_s=120)

    def test_empty_command_skipped(self, mock_logger):
        config = {
            "hooks_enabled": True,
            "Stop": {
                "no_command": {"enabled": True, "command": "", "matcher": ""},
            },
        }
        with patch("aipass.hooks.apps.modules.engine._log"):
            with patch("aipass.hooks.apps.modules.engine._run_hook") as mock_run:
                dispatch("Stop", "{}", config)
        mock_run.assert_not_called()

    def test_malformed_stdin_does_not_crash(self, mock_logger):
        config = {
            "hooks_enabled": True,
            "UserPromptSubmit": {
                "hook": {"enabled": True, "command": "echo ok", "matcher": ""},
            },
        }
        with patch("aipass.hooks.apps.modules.engine._log"):
            with patch("aipass.hooks.apps.modules.engine._run_hook") as mock_run:
                mock_run.return_value = {"exit_code": 0, "stdout": "ok", "stderr": "", "elapsed_ms": 5}
                result = dispatch("UserPromptSubmit", "not json at all{{{", config)
        assert "ok" in result[0]
        assert result[1] == 0

    def test_trust_break_banner_short_circuits_presence_gate_dispatch(self, mock_logger):
        """A hash-mismatch banner must reach the user even though presence_gate's own hook_def is empty."""
        config = {"hooks_enabled": True, "UserPromptSubmit": {"presence_gate": {}}}
        with (
            patch("aipass.hooks.apps.modules.engine._log"),
            patch(
                "aipass.hooks.apps.handlers.config.loader.trust_break_banner",
                return_value="# TRUST BREAK — ALL AIPASS HOOKS DISABLED",
            ),
            patch("aipass.hooks.apps.modules.engine._run_hook") as mock_run,
        ):
            result = dispatch("UserPromptSubmit", "{}", config)
        mock_run.assert_not_called()
        assert result == ("# TRUST BREAK — ALL AIPASS HOOKS DISABLED", 0)

    def test_no_trust_break_falls_through_to_normal_dispatch(self, mock_logger):
        config = {"hooks_enabled": True, "UserPromptSubmit": {"presence_gate": {}}}
        with (
            patch("aipass.hooks.apps.modules.engine._log"),
            patch("aipass.hooks.apps.handlers.config.loader.trust_break_banner", return_value=None),
        ):
            result = dispatch("UserPromptSubmit", "{}", config)
        assert result == ("", 0)

    def test_never_enrolled_banner_short_circuits_dispatch(self, mock_logger):
        """A never-enrolled nudge must reach the user and skip normal hook dispatch."""
        config = {"hooks_enabled": True, "UserPromptSubmit": {"presence_gate": {}}}
        with (
            patch("aipass.hooks.apps.modules.engine._log"),
            patch("aipass.hooks.apps.handlers.config.loader.trust_break_banner", return_value=None),
            patch(
                "aipass.hooks.apps.handlers.config.loader.never_enrolled_banner",
                return_value="# HOOKS ARE OFF — not yet enrolled",
            ),
            patch("aipass.hooks.apps.modules.engine._run_hook") as mock_run,
        ):
            result = dispatch("UserPromptSubmit", "{}", config)
        mock_run.assert_not_called()
        assert result == ("# HOOKS ARE OFF — not yet enrolled", 0)

    def test_no_never_enrolled_nudge_falls_through_to_normal_dispatch(self, mock_logger):
        config = {"hooks_enabled": True, "UserPromptSubmit": {"presence_gate": {}}}
        with (
            patch("aipass.hooks.apps.modules.engine._log"),
            patch("aipass.hooks.apps.handlers.config.loader.trust_break_banner", return_value=None),
            patch("aipass.hooks.apps.handlers.config.loader.never_enrolled_banner", return_value=None),
        ):
            result = dispatch("UserPromptSubmit", "{}", config)
        assert result == ("", 0)

    def test_trust_break_takes_precedence_over_never_enrolled_nudge(self, mock_logger):
        """Both can't fire for the same project in practice, but trust_break must win if they did."""
        config = {"hooks_enabled": True, "UserPromptSubmit": {"presence_gate": {}}}
        with (
            patch("aipass.hooks.apps.modules.engine._log"),
            patch(
                "aipass.hooks.apps.handlers.config.loader.trust_break_banner",
                return_value="# TRUST BREAK — ALL AIPASS HOOKS DISABLED",
            ) as mock_trust_banner,
            patch("aipass.hooks.apps.handlers.config.loader.never_enrolled_banner") as mock_nudge,
        ):
            result = dispatch("UserPromptSubmit", "{}", config)
        mock_trust_banner.assert_called_once()
        mock_nudge.assert_not_called()
        assert result == ("# TRUST BREAK — ALL AIPASS HOOKS DISABLED", 0)

    def test_trust_break_check_runs_unconditionally_for_user_prompt_submit(self, mock_logger):
        """The check runs for every UserPromptSubmit dispatch, not just presence_gate-filtered calls."""
        config = {
            "hooks_enabled": True,
            "UserPromptSubmit": {"other_hook": {"enabled": True, "command": "echo hi", "matcher": ""}},
        }
        with (
            patch("aipass.hooks.apps.modules.engine._log"),
            patch("aipass.hooks.apps.handlers.config.loader.trust_break_banner") as mock_banner,
            patch("aipass.hooks.apps.handlers.config.loader.never_enrolled_banner", return_value=None),
            patch("aipass.hooks.apps.modules.engine._run_hook") as mock_run,
        ):
            mock_banner.return_value = None
            mock_run.return_value = {"exit_code": 0, "stdout": "hi", "stderr": "", "elapsed_ms": 5}
            dispatch("UserPromptSubmit", "{}", config)
        mock_banner.assert_called_once()

    def test_trust_break_check_skipped_for_non_prompt_events(self, mock_logger):
        config = {"hooks_enabled": True, "PreToolUse": {"presence_gate": {}}}
        with (
            patch("aipass.hooks.apps.modules.engine._log"),
            patch("aipass.hooks.apps.handlers.config.loader.trust_break_banner") as mock_banner,
        ):
            dispatch("PreToolUse", "{}", config)
        mock_banner.assert_not_called()


class TestFindProjectConfig:
    """Tests for find_project_config() CWD walk."""

    def test_finds_config_in_cwd(self, hooks_config_file, temp_test_dir, mock_logger):
        reg_path = temp_test_dir / "registry.json"
        with patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path):
            enroll(str(temp_test_dir))
        with (
            patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path),
            patch("aipass.hooks.apps.handlers.config.loader.Path.cwd", return_value=temp_test_dir),
        ):
            config = find_project_config()
        assert config is not None
        assert config["hooks_enabled"] is True

    def test_returns_none_when_no_config(self, temp_test_dir, mock_logger):
        with patch("aipass.hooks.apps.modules.engine.Path.cwd", return_value=temp_test_dir):
            with patch("aipass.hooks.apps.modules.engine.Path.home", return_value=temp_test_dir.parent):
                config = find_project_config()
        assert config is None

    def test_expands_aipass_home(self, temp_test_dir, mock_logger):
        config_dir = temp_test_dir / ".aipass"
        config_dir.mkdir()
        config = {
            "hooks_enabled": True,
            "Stop": {"sound": {"enabled": True, "command": "python3 $AIPASS_HOME/hook.py", "matcher": ""}},
        }
        (config_dir / "hooks.json").write_text(json.dumps(config))
        reg_path = temp_test_dir / "registry.json"
        with patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path):
            enroll(str(temp_test_dir))
        with (
            patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path),
            patch("aipass.hooks.apps.handlers.config.loader.Path.cwd", return_value=temp_test_dir),
            patch("aipass.hooks.apps.handlers.config.loader.AIPASS_HOME", "/test/path"),
        ):
            result = find_project_config()
        assert result is not None
        assert "/test/path/hook.py" in result["Stop"]["sound"]["command"]


class TestLog:
    """Tests for _log() JSONL diagnostics."""

    def test_writes_jsonl_entry(self, temp_test_dir, mock_logger):
        log_file = temp_test_dir / "test.jsonl"
        with patch("aipass.hooks.apps.handlers.config.diagnostics._get_log_file", return_value=log_file):
            _log({"event": "Test", "action": "test_write"})
        lines = log_file.read_text().strip().split("\n")
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["event"] == "Test"
        assert entry["action"] == "test_write"

    def test_creates_parent_directory(self, temp_test_dir, mock_logger):
        log_file = temp_test_dir / "subdir" / "test.jsonl"
        with patch("aipass.hooks.apps.handlers.config.diagnostics._get_log_file", return_value=log_file):
            _log({"event": "Test"})
        assert log_file.exists()

    def test_appends_multiple_entries(self, temp_test_dir, mock_logger):
        log_file = temp_test_dir / "test.jsonl"
        with patch("aipass.hooks.apps.handlers.config.diagnostics._get_log_file", return_value=log_file):
            _log({"event": "A"})
            _log({"event": "B"})
        lines = log_file.read_text().strip().split("\n")
        assert len(lines) == 2


class TestHooksEntryPoint:
    """Tests for hooks.py CLI routing."""

    def test_help_returns_zero(self):
        from aipass.hooks.apps.hooks import main

        with patch("sys.argv", ["hooks", "--help"]):
            assert main() == 0

    def test_version_returns_zero(self):
        from aipass.hooks.apps.hooks import main

        with patch("sys.argv", ["hooks", "--version"]):
            assert main() == 0

    def test_no_args_shows_help(self):
        from aipass.hooks.apps.hooks import main

        with patch("sys.argv", ["hooks"]):
            assert main() == 0

    def test_unknown_command_returns_one(self):
        from aipass.hooks.apps.hooks import main

        with patch("sys.argv", ["hooks", "nonexistent_command"]):
            assert main() == 1

    def test_print_introspection_prints_output(self, capsys):
        from aipass.hooks.apps.hooks import print_introspection

        print_introspection()
        captured = capsys.readouterr()
        assert "HOOKS" in captured.out
        assert "Discovered Modules" in captured.out

    def test_handle_command_returns_bool(self):
        from aipass.hooks.apps.hooks import handle_command

        result = handle_command("nonexistent", [])
        assert result is False

    def test_status_command_returns_true(self):
        from aipass.hooks.apps.hooks import handle_command

        with patch("aipass.hooks.apps.handlers.config.loader.find_project_config", return_value=None):
            result = handle_command("status", [])
        assert result is True

    def test_log_command_returns_true(self):
        from aipass.hooks.apps.hooks import handle_command

        result = handle_command("log", [])
        assert result is True

    def test_short_help_flag(self):
        from aipass.hooks.apps.hooks import main

        with patch("sys.argv", ["hooks", "-h"]):
            assert main() == 0

    def test_help_word(self):
        from aipass.hooks.apps.hooks import main

        with patch("sys.argv", ["hooks", "help"]):
            assert main() == 0


class TestErrorResilience:
    """Tests for error handling edge cases."""

    def test_missing_hooks_json_file(self, temp_test_dir, mock_logger):
        with patch("aipass.hooks.apps.modules.engine.Path.cwd", return_value=temp_test_dir):
            with patch("aipass.hooks.apps.modules.engine.Path.home", return_value=temp_test_dir.parent):
                config = find_project_config()
        assert config is None

    def test_corrupt_hooks_json(self, temp_test_dir, mock_logger):
        config_dir = temp_test_dir / ".aipass"
        config_dir.mkdir()
        (config_dir / "hooks.json").write_text("{invalid json!!!")
        with patch("aipass.hooks.apps.modules.engine.Path.cwd", return_value=temp_test_dir):
            config = find_project_config()
        assert config is None

    def test_empty_hooks_json(self, temp_test_dir, mock_logger):
        config_dir = temp_test_dir / ".aipass"
        config_dir.mkdir()
        (config_dir / "hooks.json").write_text("")
        with patch("aipass.hooks.apps.modules.engine.Path.cwd", return_value=temp_test_dir):
            config = find_project_config()
        assert config is None

    def test_log_write_failure_does_not_crash(self, tmp_path, mock_logger):
        # A bare-Mock LOG_FILE leaks a real MagicMock/LOG_FILE/ dir into the CWD
        # via append_jsonl's Path(...).parent.mkdir — use a real tmp path.
        log_file = tmp_path / "engine.jsonl"
        with patch("builtins.open", side_effect=OSError("disk full")):
            with patch("aipass.hooks.apps.handlers.config.diagnostics._get_log_file", return_value=log_file):
                _log({"event": "Test"})


class TestDataStructureContracts:
    """Tests for config and log data structures."""

    def test_config_has_hooks_enabled_key(self, sample_hooks_config):
        assert "hooks_enabled" in sample_hooks_config

    def test_config_event_values_are_dicts(self, sample_hooks_config):
        for key, val in sample_hooks_config.items():
            if key == "hooks_enabled":
                continue
            assert isinstance(val, dict)

    def test_log_entry_has_required_fields(self, temp_test_dir, mock_logger):
        log_file = temp_test_dir / "test.jsonl"
        with patch("aipass.hooks.apps.handlers.config.diagnostics._get_log_file", return_value=log_file):
            _log({"ts": 123.0, "event": "Test", "action": "check"})
        entry = json.loads(log_file.read_text().strip())
        assert "ts" in entry
        assert "event" in entry


class TestExceptionContracts:
    """Tests for expected exceptions and error paths."""

    def test_dispatch_with_none_config_event_returns_empty(self, mock_logger):
        with patch("aipass.hooks.apps.modules.engine._log"):
            result = dispatch("Stop", "{}", {"hooks_enabled": True})
        assert result == ("", 0)

    def test_run_hook_timeout_returns_negative_exit(self, mock_subprocess, mock_logger):
        mock_subprocess.side_effect = subprocess.TimeoutExpired("cmd", 30)
        result = _run_hook("cmd", "")
        assert result["exit_code"] == -1

    def test_run_hook_os_error_returns_negative_exit(self, mock_subprocess, mock_logger):
        mock_subprocess.side_effect = OSError("not found")
        result = _run_hook("cmd", "")
        assert result["exit_code"] == -1


class TestInfrastructureMocking:
    """Tests verifying mock infrastructure works correctly."""

    def test_mock_logger_fixture(self, mock_logger):
        assert mock_logger is not None

    def test_mock_subprocess_fixture(self, mock_subprocess):
        assert mock_subprocess is not None
        mock_subprocess.return_value = MagicMock(returncode=0, stdout="", stderr="")
        _run_hook("test", "")
        mock_subprocess.assert_called_once()

    def test_hooks_config_file_fixture(self, hooks_config_file):
        assert hooks_config_file.exists()
        config = json.loads(hooks_config_file.read_text())
        assert config["hooks_enabled"] is True


class TestInitProvisioning:
    """Tests for initialization and directory setup."""

    def test_log_auto_creates_directory(self, temp_test_dir, mock_logger):
        log_file = temp_test_dir / "new_dir" / "engine.jsonl"
        with patch("aipass.hooks.apps.handlers.config.diagnostics._get_log_file", return_value=log_file):
            _log({"event": "init_test"})
        assert log_file.parent.exists()

    def test_config_walks_up_from_subdirectory(self, temp_test_dir, mock_logger):
        config_dir = temp_test_dir / ".aipass"
        config_dir.mkdir()
        (config_dir / "hooks.json").write_text('{"hooks_enabled": true}')
        sub_dir = temp_test_dir / "deep" / "nested" / "path"
        sub_dir.mkdir(parents=True)
        reg_path = temp_test_dir / "registry.json"
        with patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path):
            enroll(str(temp_test_dir))
        with (
            patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path),
            patch("aipass.hooks.apps.handlers.config.loader.Path.cwd", return_value=sub_dir),
        ):
            config = find_project_config()
        assert config is not None
        assert config["hooks_enabled"] is True

    def test_log_no_overwrite_on_append(self, temp_test_dir, mock_logger):
        log_file = temp_test_dir / "test.jsonl"
        log_file.write_text('{"existing": true}\n')
        with patch("aipass.hooks.apps.handlers.config.diagnostics._get_log_file", return_value=log_file):
            _log({"event": "new"})
        lines = log_file.read_text().strip().split("\n")
        assert len(lines) == 2
        assert json.loads(lines[0])["existing"] is True

    def test_dispatch_returns_tuple(self, mock_logger):
        with patch("aipass.hooks.apps.modules.engine._log"):
            result = dispatch("Stop", "{}", {"hooks_enabled": True})
        assert isinstance(result, tuple)
        assert isinstance(result[0], str)
        assert isinstance(result[1], int)
        assert result == ("", 0)


class TestConftest:
    """Tests verifying conftest fixtures and mock infrastructure."""

    def test_sample_hooks_config_has_events(self, sample_hooks_config):
        assert "UserPromptSubmit" in sample_hooks_config
        assert "PreToolUse" in sample_hooks_config

    def test_sample_data_structure(self, sample_hooks_config):
        hook = sample_hooks_config["UserPromptSubmit"]["test_hook"]
        assert "enabled" in hook
        assert "command" in hook
        assert "matcher" in hook

    def test_hooks_config_file_is_valid_json(self, hooks_config_file):
        content = json.loads(hooks_config_file.read_text())
        assert isinstance(content, dict)

    def test_temp_test_dir_exists(self, temp_test_dir):
        assert temp_test_dir.exists()
        assert temp_test_dir.is_dir()

    def test_mock_logger_is_mock(self, mock_logger):
        mock_logger.info("test")
        mock_logger.info.assert_called_once()

    def test_autouse_mock_subprocess(self, mock_subprocess):
        mock_subprocess.return_value = MagicMock(returncode=0, stdout="x", stderr="")
        result = _run_hook("test_cmd", "input")
        assert result["stdout"] == "x"

    def test_sys_modules_mock_logger(self, mock_logger):
        mock_logger.error("error msg")
        mock_logger.error.assert_called_with("error msg")

    def test_reimport_after_mock(self, mock_logger):
        from aipass.hooks.apps.modules import engine

        assert hasattr(engine, "dispatch")


class TestCliRouting:
    """Additional CLI routing tests for print_help and output capture."""

    def test_print_help_writes_output(self, capsys):
        from aipass.hooks.apps.hooks import print_help

        print_help()
        captured = capsys.readouterr()
        assert "HOOKS" in captured.out
        assert "drone @hooks" in captured.out

    def test_print_help_surfaces_subcommands(self, capsys):
        from aipass.hooks.apps.hooks import print_help

        print_help()
        captured = capsys.readouterr()
        assert "hooksound on" in captured.out
        assert "hooksound off" in captured.out
        assert "status" in captured.out
        assert "log" in captured.out

    def test_print_help_has_examples_section(self, capsys):
        from aipass.hooks.apps.hooks import print_help

        print_help()
        captured = capsys.readouterr()
        assert "EXAMPLES" in captured.out
        assert "drone @hooks status" in captured.out
        assert "drone @hooks hooksound off" in captured.out

    def test_print_help_has_usage_section(self, capsys):
        from aipass.hooks.apps.hooks import print_help

        print_help()
        captured = capsys.readouterr()
        assert "USAGE" in captured.out
        assert "drone @hooks <command>" in captured.out

    def test_help_commands_auto_discovered(self, capsys):
        from aipass.hooks.apps.hooks import print_help
        from aipass.hooks.apps.modules.hooksound import HELP_COMMANDS as hs_cmds
        from aipass.hooks.apps.modules.hookstatus import HELP_COMMANDS as hst_cmds
        from aipass.hooks.apps.modules.engine import HELP_COMMANDS as eng_cmds

        print_help()
        captured = capsys.readouterr()
        for cmd, _ in hs_cmds + hst_cmds + eng_cmds:
            assert cmd in captured.out

    def test_output_capture_status(self, capsys):
        from aipass.hooks.apps.hooks import handle_command

        with patch("aipass.hooks.apps.modules.hookstatus.find_project_config", return_value=None):
            handle_command("status", [])
        captured = capsys.readouterr()
        assert "No .aipass/hooks.json" in captured.err

    def test_version_output(self, capsys):
        from aipass.hooks.apps.hooks import main

        with patch("sys.argv", ["hooks", "--version"]):
            main()
        captured = capsys.readouterr()
        assert "1.1.0" in captured.out


class TestConfigDataContracts:
    """Additional data structure contract tests."""

    def test_config_keys_are_strings(self, sample_hooks_config):
        for key in sample_hooks_config:
            assert isinstance(key, str)

    def test_hook_def_has_command_key(self, sample_hooks_config):
        hook = sample_hooks_config["UserPromptSubmit"]["test_hook"]
        assert "command" in hook
        assert isinstance(hook["command"], str)

    def test_data_keys_in_log_entry(self, temp_test_dir, mock_logger):
        log_file = temp_test_dir / "test.jsonl"
        with patch("aipass.hooks.apps.handlers.config.diagnostics._get_log_file", return_value=log_file):
            _log({"ts": 1.0, "event": "Test", "hook": "test_hook", "exit_code": 0})
        entry = json.loads(log_file.read_text().strip())
        assert "ts" in entry
        assert "event" in entry
        assert "hook" in entry
        assert "exit_code" in entry


class TestPathContracts:
    """Tests for path-returning functions."""

    def test_paths_return_path(self):
        from aipass.hooks.apps.modules.engine import BRANCH_ROOT
        from aipass.hooks.apps.handlers.config.diagnostics import LOG_FILE

        assert isinstance(BRANCH_ROOT, Path)
        assert isinstance(LOG_FILE, Path)


class TestErrorResilienceExtended:
    """Additional error resilience tests."""

    def test_dispatch_with_empty_stdin(self, mock_logger):
        config = {
            "hooks_enabled": True,
            "Stop": {"hook": {"enabled": True, "command": "echo ok", "matcher": ""}},
        }
        with patch("aipass.hooks.apps.modules.engine._log"):
            with patch("aipass.hooks.apps.modules.engine._run_hook") as mock_run:
                mock_run.return_value = {"exit_code": 0, "stdout": "ok", "stderr": "", "elapsed_ms": 5}
                result = dispatch("Stop", "", config)
        assert "ok" in result[0]
        assert result[1] == 0

    def test_config_with_nonexistent_dir(self, temp_test_dir, mock_logger):
        nonexistent = temp_test_dir / "does_not_exist"
        with patch("aipass.hooks.apps.modules.engine.Path.cwd", return_value=nonexistent):
            with patch("aipass.hooks.apps.modules.engine.Path.home", return_value=temp_test_dir):
                config = find_project_config()
        assert config is None

    def test_missing_file_in_log_path(self, temp_test_dir, mock_logger):
        missing = temp_test_dir / "missing" / "nonexistent.jsonl"
        with patch("aipass.hooks.apps.handlers.config.diagnostics._get_log_file", return_value=missing):
            _log({"event": "test_missing"})
        assert missing.exists()

    def test_empty_file_config(self, temp_test_dir, mock_logger):
        config_dir = temp_test_dir / ".aipass"
        config_dir.mkdir()
        empty_file = config_dir / "hooks.json"
        empty_file.write_text("")
        with patch("aipass.hooks.apps.modules.engine.Path.cwd", return_value=temp_test_dir):
            config = find_project_config()
        assert config is None


class TestMockInfrastructure:
    """Tests verifying sys.modules mocking and reimport patterns."""

    def test_sys_modules_mock(self):
        import sys

        assert "aipass.hooks.apps.modules.engine" in sys.modules

    def test_reimport_after_mock(self, mock_logger):
        import importlib
        from aipass.hooks.apps.modules import engine

        importlib.reload(engine)
        assert hasattr(engine, "dispatch")
        assert hasattr(engine, "_matches")
        assert hasattr(engine, "_run_hook")


class TestLayerATrustEnforcement:
    """DPLAN-0244 Layer A: engine refuses command-type from project config, enforces handler namespace."""

    def test_command_type_refused_from_project_config(self, mock_logger):
        config = {
            "hooks_enabled": True,
            "_source": "project",
            "PreToolUse": {
                "evil_cmd": {
                    "enabled": True,
                    "command": "echo PWNED",
                    "matcher": "",
                }
            },
        }
        with patch("aipass.hooks.apps.modules.engine._log") as mock_log:
            with patch("aipass.hooks.apps.modules.engine._run_hook") as mock_run:
                result = dispatch("PreToolUse", '{"tool_name":"Edit"}', config)
        mock_run.assert_not_called()
        assert result == ("", 0)
        log_calls = [c[0][0] for c in mock_log.call_args_list]
        assert any(e.get("action") == "refused_command_type" for e in log_calls if isinstance(e, dict))

    def test_handler_namespace_enforced(self, mock_logger):
        from aipass.hooks.apps.modules.engine import _run_handler

        result = _run_handler("evil.payload.handle", {})
        assert result["exit_code"] == -1
        assert "namespace refused" in result["stderr"]

    def test_handler_aipass_namespace_allowed(self, mock_logger):
        from aipass.hooks.apps.modules.engine import _run_handler

        mock_handler = MagicMock(return_value={"exit_code": 0, "stdout": "ok"})
        mock_module = MagicMock()
        mock_module.handle = mock_handler
        with patch("importlib.import_module", return_value=mock_module):
            result = _run_handler("aipass.hooks.apps.handlers.notification.stop_sound.handle", {})
        assert result["exit_code"] == 0

    def test_command_type_allowed_from_default_config(self, mock_logger):
        config = {
            "hooks_enabled": True,
            "_source": "default",
            "Stop": {
                "cmd_hook": {
                    "enabled": True,
                    "command": "echo allowed",
                    "matcher": "",
                }
            },
        }
        with patch("aipass.hooks.apps.modules.engine._log"):
            with patch("aipass.hooks.apps.modules.engine._run_hook") as mock_run:
                mock_run.return_value = {
                    "exit_code": 0,
                    "stdout": "allowed",
                    "stderr": "",
                    "elapsed_ms": 5,
                }
                result = dispatch("Stop", "{}", config)
        mock_run.assert_called_once()
        assert "allowed" in result[0]

    def test_mixed_config_partial_refusal(self, mock_logger):
        config = {
            "hooks_enabled": True,
            "_source": "project",
            "UserPromptSubmit": {
                "good_handler": {
                    "enabled": True,
                    "handler": "aipass.hooks.apps.handlers.notification.stop_sound.handle",
                    "matcher": "",
                },
                "evil_cmd": {
                    "enabled": True,
                    "command": "echo PWNED",
                    "matcher": "",
                },
            },
        }
        mock_handler_func = MagicMock(return_value={"exit_code": 0, "stdout": "handler_ok"})
        mock_module = MagicMock()
        mock_module.handle = mock_handler_func
        with patch("aipass.hooks.apps.modules.engine._log"):
            with patch("importlib.import_module", return_value=mock_module):
                with patch("aipass.hooks.apps.modules.engine._run_hook") as mock_run:
                    result = dispatch("UserPromptSubmit", "{}", config)
        mock_run.assert_not_called()
        assert "handler_ok" in result[0]
        assert result[1] == 0

    def test_source_overwrite_not_merge(self, temp_test_dir, mock_logger):
        config_dir = temp_test_dir / ".aipass"
        config_dir.mkdir()
        hostile_config = {
            "hooks_enabled": True,
            "_source": "provider",
            "SessionStart": {
                "evil": {
                    "enabled": True,
                    "command": "echo PWNED",
                    "matcher": "",
                }
            },
        }
        (config_dir / "hooks.json").write_text(json.dumps(hostile_config))
        reg_path = temp_test_dir / "registry.json"
        with patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path):
            enroll(str(temp_test_dir))
        with (
            patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path),
            patch("aipass.hooks.apps.handlers.config.loader.Path.cwd", return_value=temp_test_dir),
        ):
            loaded = find_project_config()
        assert loaded is not None
        assert loaded["_source"] == "project"
        with patch("aipass.hooks.apps.modules.engine._log"):
            with patch("aipass.hooks.apps.modules.engine._run_hook") as mock_run:
                result = dispatch("SessionStart", "{}", loaded)
        mock_run.assert_not_called()
        assert result == ("", 0)

    def test_command_without_source_defaults_allowed(self, mock_logger):
        config = {
            "hooks_enabled": True,
            "Stop": {
                "cmd_hook": {
                    "enabled": True,
                    "command": "echo ok",
                    "matcher": "",
                }
            },
        }
        with patch("aipass.hooks.apps.modules.engine._log"):
            with patch("aipass.hooks.apps.modules.engine._run_hook") as mock_run:
                mock_run.return_value = {
                    "exit_code": 0,
                    "stdout": "ok",
                    "stderr": "",
                    "elapsed_ms": 5,
                }
                result = dispatch("Stop", "{}", config)
        mock_run.assert_called_once()
        assert "ok" in result[0]


class TestRunHandlerTimeout:
    """DPLAN-0256 backlog #1: handler-type hooks had no engine-side timeout — a hung
    handler could stall the whole event. _run_handler now runs the handler on a
    daemon thread and joins with a timeout instead of calling it inline."""

    def test_handler_completes_within_timeout(self, mock_logger):
        from aipass.hooks.apps.modules.engine import _run_handler

        mock_handler = MagicMock(return_value={"exit_code": 0, "stdout": "ok"})
        mock_module = MagicMock()
        mock_module.handle = mock_handler
        with patch("importlib.import_module", return_value=mock_module):
            result = _run_handler("aipass.hooks.apps.handlers.notification.stop_sound.handle", {}, timeout_s=1)
        assert result["exit_code"] == 0
        assert result["stdout"] == "ok"

    def test_handler_exceeding_timeout_returns_timeout_marker(self, mock_logger):
        import time as time_module

        from aipass.hooks.apps.modules.engine import _run_handler

        def _slow_handler(_data):
            time_module.sleep(1.3)
            return {"exit_code": 0, "stdout": "too late"}

        mock_module = MagicMock()
        mock_module.handle = _slow_handler
        with patch("importlib.import_module", return_value=mock_module):
            result = _run_handler("aipass.hooks.apps.handlers.fake.handle", {}, timeout_s=1)
        assert result["exit_code"] == -1
        assert result["stderr"] == "TIMEOUT"

    def test_handler_timeout_does_not_block_caller(self, mock_logger):
        """Regression: the caller must return promptly even if the handler thread never finishes."""
        import time as time_module

        from aipass.hooks.apps.modules.engine import _run_handler

        def _hangs_much_longer_than_timeout(_data):
            time_module.sleep(3)
            return {"exit_code": 0, "stdout": "should never see this"}

        mock_module = MagicMock()
        mock_module.handle = _hangs_much_longer_than_timeout
        with patch("importlib.import_module", return_value=mock_module):
            start = time_module.monotonic()
            result = _run_handler("aipass.hooks.apps.handlers.fake.handle", {}, timeout_s=1)
            elapsed = time_module.monotonic() - start
        assert elapsed < 2.0
        assert result["stderr"] == "TIMEOUT"

    def test_default_handler_timeout_is_30(self):
        import inspect

        from aipass.hooks.apps.modules.engine import _run_handler

        sig = inspect.signature(_run_handler)
        assert sig.parameters["timeout_s"].default == 30

    def test_handler_exception_still_surfaces_as_error_not_timeout(self, mock_logger):
        from aipass.hooks.apps.modules.engine import _run_handler

        def _boom(_data):
            raise RuntimeError("handler blew up")

        mock_module = MagicMock()
        mock_module.handle = _boom
        with patch("importlib.import_module", return_value=mock_module):
            result = _run_handler("aipass.hooks.apps.handlers.fake.handle", {}, timeout_s=1)
        assert result["exit_code"] == -1
        assert "handler blew up" in result["stderr"]
        assert result["stderr"] != "TIMEOUT"


class TestDispatchHandlerTimeout:
    """Dispatch-level wiring for DPLAN-0256 backlog #1 — hooks.json timeout fields
    are honored for handler-type hooks, a sane default applies when absent, and a
    timeout fails loud (log + sound) without ever silently swallowing or stalling
    the rest of the event."""

    def test_handler_timeout_propagates_hook_def_value(self, mock_logger):
        config = {
            "hooks_enabled": True,
            "UserPromptSubmit": {
                "slow_handler": {
                    "enabled": True,
                    "handler": "aipass.hooks.apps.handlers.fake.handle",
                    "matcher": "",
                    "timeout": 5,
                }
            },
        }
        with (
            patch("aipass.hooks.apps.modules.engine._log"),
            patch("aipass.hooks.apps.modules.engine._run_handler") as mock_run,
        ):
            mock_run.return_value = {"exit_code": 0, "stdout": "ok", "stderr": "", "elapsed_ms": 5}
            dispatch("UserPromptSubmit", "{}", config)
        mock_run.assert_called_once_with("aipass.hooks.apps.handlers.fake.handle", {}, timeout_s=5)

    def test_handler_default_timeout_is_30_when_unset(self, mock_logger):
        config = {
            "hooks_enabled": True,
            "UserPromptSubmit": {
                "no_timeout_handler": {
                    "enabled": True,
                    "handler": "aipass.hooks.apps.handlers.fake.handle",
                    "matcher": "",
                }
            },
        }
        with (
            patch("aipass.hooks.apps.modules.engine._log"),
            patch("aipass.hooks.apps.modules.engine._run_handler") as mock_run,
        ):
            mock_run.return_value = {"exit_code": 0, "stdout": "ok", "stderr": "", "elapsed_ms": 5}
            dispatch("UserPromptSubmit", "{}", config)
        mock_run.assert_called_once_with("aipass.hooks.apps.handlers.fake.handle", {}, timeout_s=30)

    def test_timeout_logs_speaks_and_lets_dispatch_continue(self, mock_logger):
        config = {
            "hooks_enabled": True,
            "UserPromptSubmit": {
                "hung_handler": {
                    "enabled": True,
                    "handler": "aipass.hooks.apps.handlers.fake.handle",
                    "matcher": "",
                },
                "next_handler": {
                    "enabled": True,
                    "handler": "aipass.hooks.apps.handlers.fake2.handle",
                    "matcher": "",
                },
            },
        }
        with (
            patch("aipass.hooks.apps.modules.engine._log") as mock_log,
            patch("aipass.hooks.apps.modules.engine._run_handler") as mock_run,
            patch("aipass.hooks.apps.sound.speak") as mock_speak,
        ):
            mock_run.side_effect = [
                {"exit_code": -1, "stdout": "", "stderr": "TIMEOUT", "elapsed_ms": 30000},
                {"exit_code": 0, "stdout": "survived", "stderr": "", "elapsed_ms": 5},
            ]
            result = dispatch("UserPromptSubmit", "{}", config)
        assert "survived" in result[0]
        assert result[1] == 0
        mock_speak.assert_called_once()
        log_calls = [c[0][0] for c in mock_log.call_args_list]
        assert any(e.get("action") == "timeout" for e in log_calls if isinstance(e, dict))

    def test_timed_out_handler_produces_no_output(self, mock_logger):
        config = {
            "hooks_enabled": True,
            "UserPromptSubmit": {
                "hung_handler": {
                    "enabled": True,
                    "handler": "aipass.hooks.apps.handlers.fake.handle",
                    "matcher": "",
                },
            },
        }
        with (
            patch("aipass.hooks.apps.modules.engine._log"),
            patch("aipass.hooks.apps.modules.engine._run_handler") as mock_run,
            patch("aipass.hooks.apps.sound.speak"),
        ):
            mock_run.return_value = {"exit_code": -1, "stdout": "", "stderr": "TIMEOUT", "elapsed_ms": 30000}
            result = dispatch("UserPromptSubmit", "{}", config)
        assert result == ("", 0)

    def test_command_type_timeout_also_fails_loud(self, mock_logger):
        """The fail-loud path is shared by both hook types — command-type timeouts already
        existed (subprocess timeout=), but were silent past the generic per-hook log line."""
        config = {
            "hooks_enabled": True,
            "PreToolUse": {
                "slow_cmd": {"enabled": True, "command": "sleep 999", "matcher": ""},
            },
        }
        with (
            patch("aipass.hooks.apps.modules.engine._log") as mock_log,
            patch("aipass.hooks.apps.modules.engine._run_hook") as mock_run,
            patch("aipass.hooks.apps.sound.speak") as mock_speak,
        ):
            mock_run.return_value = {"exit_code": -1, "stdout": "", "stderr": "TIMEOUT", "elapsed_ms": 30000}
            result = dispatch("PreToolUse", '{"tool_name":"Edit"}', config)
        assert result == ("", 0)
        mock_speak.assert_called_once()
        log_calls = [c[0][0] for c in mock_log.call_args_list]
        assert any(e.get("action") == "timeout" for e in log_calls if isinstance(e, dict))


class TestJsonHandlerNotApplicable:
    """Hooks uses JSONL logging, not json_handler. These verify the log equivalent."""

    def test_log_default_factory(self, temp_test_dir, mock_logger):
        log_file = temp_test_dir / "factory.jsonl"
        assert not log_file.exists()
        with patch("aipass.hooks.apps.handlers.config.diagnostics._get_log_file", return_value=log_file):
            _log({"event": "factory_test"})
        assert log_file.exists()

    def test_log_validate_json_output(self, temp_test_dir, mock_logger):
        log_file = temp_test_dir / "validate.jsonl"
        with patch("aipass.hooks.apps.handlers.config.diagnostics._get_log_file", return_value=log_file):
            _log({"event": "A", "ts": 1.0})
            _log({"event": "B", "ts": 2.0})
        for line in log_file.read_text().strip().split("\n"):
            entry = json.loads(line)
            assert isinstance(entry, dict)

    def test_log_get_path(self):
        from aipass.hooks.apps.handlers.config.diagnostics import LOG_FILE

        assert LOG_FILE.name == "engine.jsonl"
        assert "logs" in str(LOG_FILE)

    def test_log_ensure_exists(self, temp_test_dir, mock_logger):
        log_file = temp_test_dir / "new_dir" / "ensure.jsonl"
        with patch("aipass.hooks.apps.handlers.config.diagnostics._get_log_file", return_value=log_file):
            _log({"ensure": True})
        assert log_file.parent.exists()

    def test_log_save_entry(self, temp_test_dir, mock_logger):
        log_file = temp_test_dir / "save.jsonl"
        with patch("aipass.hooks.apps.handlers.config.diagnostics._get_log_file", return_value=log_file):
            _log({"saved": True, "value": 42})
        entry = json.loads(log_file.read_text().strip())
        assert entry["saved"] is True
        assert entry["value"] == 42

    def test_log_load_entry(self, temp_test_dir, mock_logger):
        log_file = temp_test_dir / "load.jsonl"
        log_file.write_text('{"loaded": true}\n')
        lines = log_file.read_text().strip().split("\n")
        entry = json.loads(lines[0])
        assert entry["loaded"] is True

    def test_log_operation_recorded(self, temp_test_dir, mock_logger):
        log_file = temp_test_dir / "ops.jsonl"
        with patch("aipass.hooks.apps.handlers.config.diagnostics._get_log_file", return_value=log_file):
            _log({"event": "PreToolUse", "hook": "test", "exit_code": 0})
        entry = json.loads(log_file.read_text().strip())
        assert entry["event"] == "PreToolUse"

    def test_log_ensure_module(self):
        from aipass.hooks.apps.modules import engine

        assert hasattr(engine, "_log")
        assert callable(engine._log)
