# =================== AIPass ====================
# Name: test_engine_contracts.py
# Description: The hook engine's contracts and resilience: bad config, log writes, fixtures, CLI routing, paths
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-17
# =============================================

"""Tests for apps/modules/engine.py: its contracts and error resilience."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(stdlib) — subprocess.run's process spawn and timeout mechanics; the tests stub it at the edge

import importlib
import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from aipass.hooks.apps import hooks as entry
from aipass.hooks.apps.hooks import handle_command, print_help
from aipass.hooks.apps.modules import engine
from aipass.hooks.apps.modules.engine import (
    BRANCH_ROOT,
    HELP_COMMANDS as eng_cmds,
    dispatch,
    _run_hook,
    _log,
)
from aipass.hooks.apps.modules.hooksound import HELP_COMMANDS as hs_cmds
from aipass.hooks.apps.modules.hookstatus import HELP_COMMANDS as hst_cmds
from aipass.hooks.apps.handlers.config import trust_registry
from aipass.hooks.apps.handlers.config.diagnostics import LOG_FILE
from aipass.hooks.apps.handlers.config.loader import find_project_config
from aipass.hooks.apps.handlers.config.trust_registry import enroll

pytestmark = pytest.mark.usefixtures("_no_real_trust_banners")


class TestErrorResilience:
    """Tests for error handling edge cases."""

    # Both enrol first: unenrolled, find_project_config returns None before the parse they are named for.
    def test_corrupt_hooks_json(self, temp_test_dir, mock_logger):
        config_dir = temp_test_dir / ".aipass"
        config_dir.mkdir()
        (config_dir / "hooks.json").write_text("{invalid json!!!", encoding="utf-8")
        enroll(str(temp_test_dir))
        with (
            patch(
                "aipass.hooks.apps.handlers.config.loader._search_bounds",
                return_value=(temp_test_dir, temp_test_dir.parent),
            ),
            patch("aipass.hooks.apps.handlers.config.loader.logger") as loader_logger,
        ):
            config = find_project_config()
        assert config is None
        assert "bad config" in loader_logger.error.call_args[0][0]

    def test_empty_hooks_json(self, temp_test_dir, mock_logger):
        config_dir = temp_test_dir / ".aipass"
        config_dir.mkdir()
        (config_dir / "hooks.json").write_text("", encoding="utf-8")
        enroll(str(temp_test_dir))
        with (
            patch(
                "aipass.hooks.apps.handlers.config.loader._search_bounds",
                return_value=(temp_test_dir, temp_test_dir.parent),
            ),
            patch("aipass.hooks.apps.handlers.config.loader.logger") as loader_logger,
        ):
            config = find_project_config()
        assert config is None
        assert "bad config" in loader_logger.error.call_args[0][0]

    def test_a_registry_bootstrap_lands_in_the_sandbox(self, temp_test_dir, tmp_path, monkeypatch, mock_logger):
        """seedgo's runtime probe, 2026-09-14: this class created ~/.aipass/trusted_projects.json.

        The sandbox is checked BEFORE the call, so a run without the guard fails without touching the live file.
        """
        registry = trust_registry.REGISTRY_PATH
        assert registry != Path.home() / ".aipass" / "trusted_projects.json"
        assert not registry.exists()
        install = tmp_path / "install"
        (install / ".aipass").mkdir(parents=True)
        (install / ".aipass" / "hooks.json").write_text("{}", encoding="utf-8")
        monkeypatch.setenv("AIPASS_HOME", str(install))
        (temp_test_dir / ".aipass").mkdir()
        (temp_test_dir / ".aipass" / "hooks.json").write_text("{invalid json!!!", encoding="utf-8")

        with patch(
            "aipass.hooks.apps.handlers.config.loader._search_bounds",
            return_value=(temp_test_dir, temp_test_dir.parent),
        ):
            find_project_config()

        assert list(json.loads(registry.read_text(encoding="utf-8"))["projects"]) == [str(install.resolve())]

    def test_log_write_failure_does_not_crash(self, tmp_path, mock_logger):
        """A failed log write is reported and swallowed, never raised.

        A bare-Mock LOG_FILE leaks a real MagicMock/LOG_FILE/ dir into the CWD: use a real tmp path.
        """
        # A directory where the log file should be makes the platform itself refuse the append.
        log_file = tmp_path / "engine.jsonl"
        log_file.mkdir()
        with pytest.raises(OSError) as raised:
            open(log_file, "a", encoding="utf-8").close()
        # The report goes through diagnostics' own logger; mock_logger patches engine's and is blind here.
        with (
            patch("aipass.hooks.apps.handlers.config.diagnostics._get_log_file", return_value=log_file),
            patch("aipass.hooks.apps.handlers.config.diagnostics.logger") as diag_logger,
        ):
            _log({"event": "Test"})

        assert log_file.is_dir() and list(log_file.iterdir()) == []
        assert diag_logger.error.call_count == 1
        template, reported = diag_logger.error.call_args[0]
        assert "log write failed" in template
        assert reported.strerror == raised.value.strerror

    def test_no_mock_named_directory_survives_in_the_branch_root(self):
        """A Mock handed to a filesystem call names a directory after its repr.

        A property of the TREE, not one call site: the next leak comes from a different test.
        """
        root = Path(__file__).resolve().parent.parent
        leaked = sorted(p.name for p in root.iterdir() if "mock" in p.name.lower())
        assert leaked == [], f"a mock repr reached a filesystem call: {leaked}"


class TestDataStructureContracts:
    """Tests for config and log data structures."""

    def test_config_has_hooks_enabled_key(self, sample_hooks_config):
        assert "hooks_enabled" in sample_hooks_config

    def test_log_entry_has_required_fields(self, temp_test_dir, mock_logger):
        log_file = temp_test_dir / "test.jsonl"
        with patch("aipass.hooks.apps.handlers.config.diagnostics._get_log_file", return_value=log_file):
            _log({"ts": 123.0, "event": "Test", "action": "check"})
        entry = json.loads(log_file.read_text(encoding="utf-8").strip())
        assert "ts" in entry
        assert "event" in entry


class TestExceptionContracts:
    """Tests for expected exceptions and error paths."""

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
        """The fixture is the logger engine's own functions see, not a detached mock."""
        assert dispatch.__globals__["logger"] is mock_logger

    def test_mock_subprocess_fixture(self, mock_subprocess):
        mock_subprocess.return_value = MagicMock(returncode=0, stdout="", stderr="")
        _run_hook("test", "")
        mock_subprocess.assert_called_once()
        assert mock_subprocess.call_args.args == ("test",)  # the fixture stands where _run_hook spawns

    def test_hooks_config_file_fixture(self, hooks_config_file):
        assert hooks_config_file.exists()
        config = json.loads(hooks_config_file.read_text(encoding="utf-8"))
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
        (config_dir / "hooks.json").write_text('{"hooks_enabled": true}', encoding="utf-8")
        sub_dir = temp_test_dir / "deep" / "nested" / "path"
        sub_dir.mkdir(parents=True)
        reg_path = temp_test_dir / "registry.json"
        with patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path):
            enroll(str(temp_test_dir))
        with (
            patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path),
            patch(
                "aipass.hooks.apps.handlers.config.loader._search_bounds",
                return_value=(sub_dir, temp_test_dir.parent),
            ),
        ):
            config = find_project_config()
        assert config is not None
        assert config["hooks_enabled"] is True

    def test_log_no_overwrite_on_append(self, temp_test_dir, mock_logger):
        log_file = temp_test_dir / "test.jsonl"
        log_file.write_text('{"existing": true}\n', encoding="utf-8")
        with patch("aipass.hooks.apps.handlers.config.diagnostics._get_log_file", return_value=log_file):
            _log({"event": "new"})
        lines = log_file.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2
        assert json.loads(lines[0])["existing"] is True

    def test_dispatch_returns_tuple(self, mock_logger):
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

    def test_temp_test_dir_exists(self, temp_test_dir):
        assert temp_test_dir.exists()
        assert temp_test_dir.is_dir()

    def test_autouse_mock_subprocess(self, mock_subprocess):
        mock_subprocess.return_value = MagicMock(returncode=0, stdout="x", stderr="")
        result = _run_hook("test_cmd", "input")
        assert result["stdout"] == "x"

    def test_reimport_after_mock(self, mock_logger):
        assert hasattr(engine, "dispatch")


class TestCliRouting:
    """Additional CLI routing tests for print_help and output capture."""

    def test_print_help_writes_output(self, capsys):
        print_help()
        captured = capsys.readouterr()
        assert "HOOKS" in captured.out
        assert "drone @hooks" in captured.out

    def test_print_help_surfaces_subcommands(self, capsys):
        print_help()
        captured = capsys.readouterr()
        assert "hooksound on" in captured.out
        assert "hooksound off" in captured.out
        assert "status" in captured.out
        assert "log" in captured.out

    def test_print_help_has_examples_section(self, capsys):
        print_help()
        captured = capsys.readouterr()
        assert "EXAMPLES" in captured.out
        assert "drone @hooks status" in captured.out
        assert "drone @hooks hooksound off" in captured.out

    def test_print_help_has_usage_section(self, capsys):
        print_help()
        captured = capsys.readouterr()
        assert "USAGE" in captured.out
        assert "drone @hooks <command>" in captured.out

    def test_help_commands_auto_discovered(self, capsys):
        print_help()
        captured = capsys.readouterr()
        # A floor per module, not in total and not exact: a module that stops declaring HELP_COMMANDS reds.
        assert min(len(hs_cmds), len(hst_cmds), len(eng_cmds)) >= 1
        commands = hs_cmds + hst_cmds + eng_cmds
        for cmd, _ in commands:
            assert cmd in captured.out

    def test_output_capture_status(self, capsys):
        with (
            patch("aipass.hooks.apps.modules.hookstatus.find_project_config", return_value=None),
            patch(
                "aipass.hooks.apps.modules.hookstatus.config_unavailable_reason",
                return_value="No .aipass/hooks.json found — run from an AIPass project directory.",
            ),
        ):
            with pytest.raises(SystemExit) as exit_info:
                handle_command("status", [])

        # Exit 1, not 0: showing nothing and reporting success is the defect.
        assert exit_info.value.code == 1
        captured = capsys.readouterr()
        assert "No .aipass/hooks.json" in captured.err

    def test_version_output(self, capsys):
        """Read from the header, never hardcoded."""
        import re

        versions = re.findall(r"^# Version:\s*(\S+)", Path(entry.__file__).read_text(encoding="utf-8"), re.MULTILINE)
        assert len(versions) == 1, f"apps/hooks.py needs one '# Version:' header line, has {versions}"

        with patch("sys.argv", ["hooks", "--version"]):
            entry.main()
        captured = capsys.readouterr()
        assert versions[0] in captured.out


class TestConfigDataContracts:
    """Additional data structure contract tests."""

    def test_data_keys_in_log_entry(self, temp_test_dir, mock_logger):
        log_file = temp_test_dir / "test.jsonl"
        with patch("aipass.hooks.apps.handlers.config.diagnostics._get_log_file", return_value=log_file):
            _log({"ts": 1.0, "event": "Test", "hook": "test_hook", "exit_code": 0})
        entry = json.loads(log_file.read_text(encoding="utf-8").strip())
        assert "ts" in entry
        assert "event" in entry
        assert "hook" in entry
        assert "exit_code" in entry


class TestPathContracts:
    """Tests for path-returning functions."""

    def test_paths_return_path(self):
        """BRANCH_ROOT resolves to this branch, not to whatever the cwd was.

        A type check is blind to a BRANCH_ROOT pointing at the caller's directory; a landmark under it is not.
        """
        assert BRANCH_ROOT.name == "hooks"
        assert (BRANCH_ROOT / "apps" / "modules" / "engine.py").is_file()
        assert LOG_FILE == BRANCH_ROOT / "logs" / "engine.jsonl"


class TestErrorResilienceExtended:
    """Additional error resilience tests."""

    def test_dispatch_with_empty_stdin(self, mock_logger):
        config = {
            "hooks_enabled": True,
            "Stop": {"hook": {"enabled": True, "command": "echo ok", "matcher": ""}},
        }
        with patch("aipass.hooks.apps.modules.engine._run_hook") as mock_run:
            mock_run.return_value = {"exit_code": 0, "stdout": "ok", "stderr": "", "elapsed_ms": 5}
            result = dispatch("Stop", "", config)
        assert "ok" in result[0]
        assert result[1] == 0

    def test_config_with_nonexistent_dir(self, temp_test_dir, mock_logger):
        nonexistent = temp_test_dir / "does_not_exist"
        with patch(
            "aipass.hooks.apps.handlers.config.loader._search_bounds",
            return_value=(nonexistent, temp_test_dir),
        ):
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
        empty_file.write_text("", encoding="utf-8")
        with patch(
            "aipass.hooks.apps.handlers.config.loader._search_bounds",
            return_value=(temp_test_dir, temp_test_dir.parent),
        ):
            config = find_project_config()
        assert config is None


class TestMockInfrastructure:
    """Tests verifying sys.modules mocking and reimport patterns."""

    def test_sys_modules_mock(self):
        import sys

        assert "aipass.hooks.apps.modules.engine" in sys.modules

    def test_reimport_after_mock(self, mock_logger):
        importlib.reload(engine)
        assert hasattr(engine, "dispatch")
        assert hasattr(engine, "_matches")
        assert hasattr(engine, "_run_hook")
