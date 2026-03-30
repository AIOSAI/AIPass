# =================== AIPass ====================
# Name: test_discovery.py
# Description: Tests for module and command discovery
# Version: 1.0.0
# Created: 2026-03-14
# Modified: 2026-03-14
# =============================================

"""Tests for module and command discovery.

Covers handler-layer functions (scan_modules_directory, parse_help_for_commands,
get_help, get_module_introspective) and orchestration-layer functions
(discover_modules, get_help, get_system_help) from the discovery module.
"""

import subprocess
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from aipass.drone.apps.handlers.discovery_handler import (
    HelpResult,
    scan_modules_directory,
    parse_help_for_commands,
    get_help as handler_get_help,
    get_entry_point,
    discover_modules as handler_discover_modules,
)
from aipass.drone.apps.handlers.exceptions import (
    BranchNotFoundError,
    CommandExecutionError,
)
from aipass.drone.apps.handlers.module_registry_handler import (
    get_module_introspective,
)


# =============================================================================
# scan_modules_directory tests
# =============================================================================

class TestScanModulesDirectory:
    """Tests for scan_modules_directory()."""

    def test_finds_py_files(self, temp_test_dir: Path):
        """Should return stems of .py files in apps/modules/."""
        modules_dir = temp_test_dir / "apps" / "modules"
        modules_dir.mkdir(parents=True)
        (modules_dir / "alpha.py").write_text("# alpha", encoding="utf-8")
        (modules_dir / "beta.py").write_text("# beta", encoding="utf-8")
        (modules_dir / "gamma.py").write_text("# gamma", encoding="utf-8")

        result = scan_modules_directory(str(temp_test_dir))

        assert result == ["alpha", "beta", "gamma"]

    def test_skips_init_and_main(self, temp_test_dir: Path):
        """Should exclude __init__.py and __main__.py from results."""
        modules_dir = temp_test_dir / "apps" / "modules"
        modules_dir.mkdir(parents=True)
        (modules_dir / "__init__.py").write_text("", encoding="utf-8")
        (modules_dir / "__main__.py").write_text("", encoding="utf-8")
        (modules_dir / "real_module.py").write_text("# code", encoding="utf-8")

        result = scan_modules_directory(str(temp_test_dir))

        assert "__init__" not in result
        assert "__main__" not in result
        assert result == ["real_module"]

    def test_ignores_pycache_and_non_py(self, temp_test_dir: Path):
        """Should ignore __pycache__ directories and non-.py files."""
        modules_dir = temp_test_dir / "apps" / "modules"
        modules_dir.mkdir(parents=True)
        (modules_dir / "__pycache__").mkdir()
        (modules_dir / "__pycache__" / "cached.pyc").write_bytes(b"\x00")
        (modules_dir / "notes.txt").write_text("not python", encoding="utf-8")
        (modules_dir / "data.json").write_text("{}", encoding="utf-8")
        (modules_dir / "valid.py").write_text("# ok", encoding="utf-8")

        result = scan_modules_directory(str(temp_test_dir))

        assert result == ["valid"]

    def test_returns_empty_for_empty_directory(self, temp_test_dir: Path):
        """Should return empty list when apps/modules/ exists but has no .py files."""
        modules_dir = temp_test_dir / "apps" / "modules"
        modules_dir.mkdir(parents=True)

        result = scan_modules_directory(str(temp_test_dir))

        assert result == []

    def test_returns_empty_when_no_modules_dir(self, temp_test_dir: Path):
        """Should return empty list when apps/modules/ does not exist."""
        result = scan_modules_directory(str(temp_test_dir))

        assert result == []

    def test_results_are_sorted(self, temp_test_dir: Path):
        """Returned module names should be sorted alphabetically."""
        modules_dir = temp_test_dir / "apps" / "modules"
        modules_dir.mkdir(parents=True)
        for name in ["zebra", "apple", "mango"]:
            (modules_dir / f"{name}.py").write_text("", encoding="utf-8")

        result = scan_modules_directory(str(temp_test_dir))

        assert result == sorted(result)
        assert result == ["apple", "mango", "zebra"]


# =============================================================================
# parse_help_for_commands tests
# =============================================================================

class TestParseHelpForCommands:
    """Tests for parse_help_for_commands()."""

    def test_extracts_commands_from_commands_section(self):
        """Should extract command names from a 'Commands:' section."""
        help_text = (
            "Usage: tool [OPTIONS] COMMAND\n"
            "\n"
            "Commands:\n"
            "  init        Initialize a project\n"
            "  build       Build the project\n"
            "  deploy      Deploy to production\n"
            "\n"
            "Options:\n"
            "  --help      Show this message\n"
        )

        result = parse_help_for_commands(help_text)

        assert "init" in result
        assert "build" in result
        assert "deploy" in result

    def test_extracts_from_subcommands_section(self):
        """Should recognize 'Subcommands:' as a section marker."""
        help_text = (
            "MyTool v1.0\n"
            "\n"
            "Subcommands:\n"
            "  status      Show status\n"
            "  config      Configure settings\n"
            "\n"
        )

        result = parse_help_for_commands(help_text)

        assert "status" in result
        assert "config" in result

    def test_extracts_from_available_commands_section(self):
        """Should recognize 'Available Commands:' as a section marker."""
        help_text = (
            "Usage: app\n"
            "\n"
            "Available Commands:\n"
            "  run         Run the app\n"
            "  test        Run tests\n"
            "\n"
        )

        result = parse_help_for_commands(help_text)

        assert "run" in result
        assert "test" in result

    def test_skips_options_flags(self):
        """Should not include lines starting with - as commands."""
        help_text = (
            "Commands:\n"
            "  start       Start the server\n"
            "  -v          Verbose mode\n"
            "  --debug     Debug mode\n"
        )

        result = parse_help_for_commands(help_text)

        assert "start" in result
        assert "-v" not in result
        assert "--debug" not in result

    def test_empty_string_returns_empty_list(self):
        """Empty help text should return empty list."""
        result = parse_help_for_commands("")

        assert result == []

    def test_no_commands_section_returns_empty(self):
        """Help text without a commands section should return empty list."""
        help_text = (
            "Usage: tool [OPTIONS]\n"
            "\n"
            "Options:\n"
            "  --help      Show help\n"
            "  --version   Show version\n"
        )

        result = parse_help_for_commands(help_text)

        assert result == []

    def test_section_ends_at_blank_line(self):
        """Commands section should end at the first blank line after it."""
        help_text = (
            "Commands:\n"
            "  alpha       First command\n"
            "  beta        Second command\n"
            "\n"
            "Not a command section anymore:\n"
            "  gamma       Should not appear\n"
        )

        result = parse_help_for_commands(help_text)

        assert "alpha" in result
        assert "beta" in result
        # "gamma" is in a new section after the blank line ended the Commands
        # section, and "Not a command section anymore:" is not a recognized marker
        assert "gamma" not in result


# =============================================================================
# get_entry_point tests
# =============================================================================

class TestGetEntryPoint:
    """Tests for get_entry_point()."""

    def test_returns_path_when_entry_exists(self, temp_test_dir: Path):
        """Should return the entry point Path when apps/{name}.py exists."""
        apps_dir = temp_test_dir / "apps"
        apps_dir.mkdir(parents=True)
        entry = apps_dir / "mybranch.py"
        entry.write_text("# entry", encoding="utf-8")

        result = get_entry_point(str(temp_test_dir), "mybranch")

        assert result is not None
        assert result == entry

    def test_returns_none_when_missing(self, temp_test_dir: Path):
        """Should return None when the entry point file does not exist."""
        result = get_entry_point(str(temp_test_dir), "nonexistent")

        assert result is None


# =============================================================================
# handler get_help tests
# =============================================================================

class TestHandlerGetHelp:
    """Tests for discovery_handler.get_help()."""

    def test_returns_help_result_for_valid_entry(self, temp_test_dir: Path):
        """Should return HelpResult when entry point exists and subprocess runs."""
        apps_dir = temp_test_dir / "apps"
        apps_dir.mkdir(parents=True)
        entry = apps_dir / "testbranch.py"
        entry.write_text("# entry", encoding="utf-8")

        mock_result = MagicMock()
        mock_result.stdout = b"Usage: testbranch\n\nCommands:\n  run   Run it\n  stop  Stop it\n"
        mock_result.stderr = b""

        with patch("aipass.drone.apps.handlers.discovery_handler.subprocess.run", return_value=mock_result):
            result = handler_get_help(str(temp_test_dir), "testbranch")

        assert isinstance(result, HelpResult)
        assert result.branch == "testbranch"
        assert result.command is None
        assert "run" in result.commands_found
        assert "stop" in result.commands_found

    def test_returns_help_for_specific_command(self, temp_test_dir: Path):
        """Should pass command argument through and set it on result."""
        apps_dir = temp_test_dir / "apps"
        apps_dir.mkdir(parents=True)
        (apps_dir / "testbranch.py").write_text("# entry", encoding="utf-8")

        mock_result = MagicMock()
        mock_result.stdout = b"Help for the run command\n"
        mock_result.stderr = b""

        with patch("aipass.drone.apps.handlers.discovery_handler.subprocess.run", return_value=mock_result):
            result = handler_get_help(str(temp_test_dir), "testbranch", command="run")

        assert result.command == "run"
        assert "Help for the run command" in result.text

    def test_raises_when_entry_point_missing(self, temp_test_dir: Path):
        """Should raise CommandExecutionError when no entry point exists."""
        with pytest.raises(CommandExecutionError, match="Entry point not found"):
            handler_get_help(str(temp_test_dir), "nonexistent")

    def test_raises_on_timeout(self, temp_test_dir: Path):
        """Should raise CommandExecutionError when subprocess times out."""
        apps_dir = temp_test_dir / "apps"
        apps_dir.mkdir(parents=True)
        (apps_dir / "slowbranch.py").write_text("# entry", encoding="utf-8")

        with patch(
            "aipass.drone.apps.handlers.discovery_handler.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="test", timeout=10),
        ):
            with pytest.raises(CommandExecutionError, match="timed out"):
                handler_get_help(str(temp_test_dir), "slowbranch")

    def test_raises_on_oserror(self, temp_test_dir: Path):
        """Should raise CommandExecutionError when subprocess raises OSError."""
        apps_dir = temp_test_dir / "apps"
        apps_dir.mkdir(parents=True)
        (apps_dir / "broken.py").write_text("# entry", encoding="utf-8")

        with patch(
            "aipass.drone.apps.handlers.discovery_handler.subprocess.run",
            side_effect=OSError("No such file or directory"),
        ):
            with pytest.raises(CommandExecutionError, match="OS error"):
                handler_get_help(str(temp_test_dir), "broken")

    def test_falls_back_to_stderr(self, temp_test_dir: Path):
        """When stdout is empty, should use stderr for help text."""
        apps_dir = temp_test_dir / "apps"
        apps_dir.mkdir(parents=True)
        (apps_dir / "testbranch.py").write_text("# entry", encoding="utf-8")

        mock_result = MagicMock()
        mock_result.stdout = b""
        mock_result.stderr = b"Usage printed to stderr\n"

        with patch("aipass.drone.apps.handlers.discovery_handler.subprocess.run", return_value=mock_result):
            result = handler_get_help(str(temp_test_dir), "testbranch")

        assert "Usage printed to stderr" in result.text


# =============================================================================
# handler discover_modules tests
# =============================================================================

class TestHandlerDiscoverModules:
    """Tests for discovery_handler.discover_modules()."""

    def test_uses_help_parsing_when_entry_point_exists(self, temp_test_dir: Path):
        """Should prefer parsed help text when entry point exists and returns commands."""
        apps_dir = temp_test_dir / "apps"
        apps_dir.mkdir(parents=True)
        (apps_dir / "mybranch.py").write_text("# entry", encoding="utf-8")

        modules_dir = apps_dir / "modules"
        modules_dir.mkdir()
        (modules_dir / "fallback.py").write_text("", encoding="utf-8")

        mock_result = MagicMock()
        mock_result.stdout = b"Commands:\n  alpha   Do alpha\n  beta    Do beta\n"
        mock_result.stderr = b""

        with patch("aipass.drone.apps.handlers.discovery_handler.subprocess.run", return_value=mock_result):
            result = handler_discover_modules(str(temp_test_dir), "mybranch")

        assert "alpha" in result
        assert "beta" in result
        # fallback module should NOT appear when help parsing succeeded
        assert "fallback" not in result

    def test_falls_back_to_scan_when_no_entry_point(self, temp_test_dir: Path):
        """Should fall back to scan_modules_directory when no entry point."""
        modules_dir = temp_test_dir / "apps" / "modules"
        modules_dir.mkdir(parents=True)
        (modules_dir / "scanner.py").write_text("", encoding="utf-8")
        (modules_dir / "parser.py").write_text("", encoding="utf-8")

        result = handler_discover_modules(str(temp_test_dir), "nonexistent")

        assert result == ["parser", "scanner"]

    def test_falls_back_to_scan_on_timeout(self, temp_test_dir: Path):
        """Should fall back to scan_modules_directory when subprocess times out."""
        apps_dir = temp_test_dir / "apps"
        apps_dir.mkdir(parents=True)
        (apps_dir / "mybranch.py").write_text("# entry", encoding="utf-8")

        modules_dir = apps_dir / "modules"
        modules_dir.mkdir()
        (modules_dir / "fallback_timeout.py").write_text("", encoding="utf-8")

        with patch(
            "aipass.drone.apps.handlers.discovery_handler.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="test", timeout=10),
        ):
            result = handler_discover_modules(str(temp_test_dir), "mybranch")

        assert result == ["fallback_timeout"]

    def test_falls_back_to_scan_when_help_empty(self, temp_test_dir: Path):
        """Should fall back to scan when help text yields no commands."""
        apps_dir = temp_test_dir / "apps"
        apps_dir.mkdir(parents=True)
        (apps_dir / "mybranch.py").write_text("# entry", encoding="utf-8")

        modules_dir = apps_dir / "modules"
        modules_dir.mkdir()
        (modules_dir / "fallback_cmd.py").write_text("", encoding="utf-8")

        mock_result = MagicMock()
        mock_result.stdout = b"No commands here, just text.\n"
        mock_result.stderr = b""

        with patch("aipass.drone.apps.handlers.discovery_handler.subprocess.run", return_value=mock_result):
            result = handler_discover_modules(str(temp_test_dir), "mybranch")

        assert result == ["fallback_cmd"]


# =============================================================================
# orchestration layer: discovery.discover_modules tests
# =============================================================================

class TestOrchestrationDiscoverModules:
    """Tests for discovery.discover_modules() orchestration."""

    @patch("aipass.drone.apps.modules.discovery.resolve_branch")
    @patch("aipass.drone.apps.handlers.discovery_handler.discover_modules")
    def test_resolves_and_delegates(self, mock_handler_discover, mock_resolve):
        """Should resolve branch path then delegate to handler."""
        from aipass.drone.apps.modules.discovery import discover_modules

        mock_resolve.return_value = "/fake/path/to/branch"
        mock_handler_discover.return_value = ["cmd_a", "cmd_b"]

        result = discover_modules("@testbranch")

        mock_resolve.assert_called_once_with("@testbranch")
        mock_handler_discover.assert_called_once_with("/fake/path/to/branch", "testbranch")
        assert result == ["cmd_a", "cmd_b"]

    @patch("aipass.drone.apps.modules.discovery.resolve_branch")
    def test_raises_on_invalid_branch(self, mock_resolve):
        """Should propagate BranchNotFoundError for unknown branches."""
        from aipass.drone.apps.modules.discovery import discover_modules

        mock_resolve.side_effect = BranchNotFoundError("Branch '@nope' not found")

        with pytest.raises(BranchNotFoundError):
            discover_modules("@nope")


# =============================================================================
# orchestration layer: discovery.get_help tests
# =============================================================================

class TestOrchestrationGetHelp:
    """Tests for discovery.get_help() orchestration."""

    @patch("aipass.drone.apps.modules.discovery.resolve_branch")
    @patch("aipass.drone.apps.handlers.discovery_handler.get_help")
    def test_returns_help_result(self, mock_handler_help, mock_resolve):
        """Should return HelpResult for a valid branch."""
        from aipass.drone.apps.modules.discovery import get_help

        mock_resolve.return_value = "/fake/branch"
        mock_handler_help.return_value = HelpResult(
            branch="valid",
            command=None,
            text="Some help text",
            commands_found=["run"],
        )

        result = get_help("@valid")

        assert isinstance(result, HelpResult)
        assert result.branch == "valid"
        assert result.text == "Some help text"

    @patch("aipass.drone.apps.modules.discovery.resolve_branch")
    def test_raises_on_invalid_branch(self, mock_resolve):
        """Should propagate BranchNotFoundError for unknown branches."""
        from aipass.drone.apps.modules.discovery import get_help

        mock_resolve.side_effect = BranchNotFoundError("not found")

        with pytest.raises(BranchNotFoundError):
            get_help("@nonexistent")


# =============================================================================
# orchestration layer: discovery.get_system_help tests
# =============================================================================

class TestOrchestrationGetSystemHelp:
    """Tests for discovery.get_system_help() orchestration."""

    @patch("aipass.drone.apps.modules.discovery.list_branches")
    @patch("aipass.drone.apps.handlers.discovery_handler.get_system_help")
    def test_aggregates_across_branches(self, mock_sys_help, mock_list):
        """Should pass active branches to handler and return results."""
        from aipass.drone.apps.modules.discovery import get_system_help

        mock_list.return_value = ["@alpha", "@beta"]
        mock_sys_help.return_value = {
            "alpha": HelpResult(branch="alpha", command=None, text="alpha help", commands_found=[]),
            "beta": HelpResult(branch="beta", command=None, text="beta help", commands_found=[]),
        }

        result = get_system_help()

        mock_list.assert_called_once_with(status="active")
        assert "alpha" in result
        assert "beta" in result


# =============================================================================
# get_module_introspective tests
# =============================================================================

class TestGetModuleIntrospective:
    """Tests for module_registry_handler.get_module_introspective()."""

    @patch("aipass.drone.apps.handlers.module_registry_handler._INTERNAL_MODULES", {"testmod": "fake.module.path"})
    @patch("aipass.drone.apps.handlers.module_registry_handler._EXTERNAL_MODULES", {})
    def test_returns_introspective_output(self):
        """Should call get_introspective() on the internal module adapter."""
        fake_mod = types.ModuleType("fake.module.path")
        fake_mod.get_introspective = lambda: "Introspective info for testmod"  # type: ignore[attr-defined]

        with patch("aipass.drone.apps.handlers.module_registry_handler.importlib.import_module", return_value=fake_mod):
            result = get_module_introspective("testmod")

        assert result == "Introspective info for testmod"

    @patch("aipass.drone.apps.handlers.module_registry_handler._INTERNAL_MODULES", {"testmod": "fake.module.path"})
    @patch("aipass.drone.apps.handlers.module_registry_handler._EXTERNAL_MODULES", {})
    def test_falls_back_to_help(self):
        """Should fall back to get_help(None) if get_introspective is missing."""
        fake_mod = types.ModuleType("fake.module.path")
        # Only attach get_help, no get_introspective
        fake_mod.get_help = lambda cmd: "Help fallback text"  # type: ignore[attr-defined]

        with patch("aipass.drone.apps.handlers.module_registry_handler.importlib.import_module", return_value=fake_mod):
            result = get_module_introspective("testmod")

        assert result == "Help fallback text"

    def test_returns_empty_for_unknown_module(self):
        """Should return empty string for unregistered module name."""
        result = get_module_introspective("totally_unknown_module_xyz")

        assert result == ""


# =============================================================================
# handle_command routing tests
# =============================================================================

class TestHandleCommand:
    """Tests for discovery.handle_command() routing."""

    @patch("aipass.drone.apps.modules.discovery.discover_modules")
    def test_modules_command_requires_arg(self, mock_discover):
        """'modules' command with no args should return False."""
        from aipass.drone.apps.modules.discovery import handle_command

        result = handle_command("modules", [])

        assert result is False
        mock_discover.assert_not_called()

    @patch("aipass.drone.apps.modules.discovery.discover_modules", return_value=["cmd1"])
    def test_modules_command_succeeds(self, mock_discover):
        """'modules' command with a target should return True."""
        from aipass.drone.apps.modules.discovery import handle_command

        result = handle_command("modules", ["@mybranch"])

        assert result is True
        mock_discover.assert_called_once_with("@mybranch")

    def test_help_command_requires_arg(self):
        """'help' command with no args should return False."""
        from aipass.drone.apps.modules.discovery import handle_command

        result = handle_command("help", [])

        assert result is False

    @patch("aipass.drone.apps.modules.discovery.get_help")
    def test_help_command_with_branch(self, mock_get_help):
        """'help' command with a branch target should return True."""
        from aipass.drone.apps.modules.discovery import handle_command

        mock_get_help.return_value = HelpResult(
            branch="branch", command=None, text="help text", commands_found=[],
        )

        result = handle_command("help", ["@branch"])

        assert result is True
        mock_get_help.assert_called_once_with("@branch", None)

    @patch("aipass.drone.apps.modules.discovery.get_help")
    def test_help_command_with_subcommand(self, mock_get_help):
        """'help' command with branch and subcommand passes command through."""
        from aipass.drone.apps.modules.discovery import handle_command

        mock_get_help.return_value = HelpResult(
            branch="branch", command="subcmd", text="subcmd help", commands_found=[],
        )

        result = handle_command("help", ["@branch", "subcmd"])

        assert result is True
        mock_get_help.assert_called_once_with("@branch", "subcmd")

    @patch("aipass.drone.apps.modules.discovery.get_system_help")
    def test_system_command(self, mock_sys_help):
        """'system' command with no args should return True."""
        from aipass.drone.apps.modules.discovery import handle_command

        mock_sys_help.return_value = {
            "alpha": HelpResult(branch="alpha", command=None, text="alpha help", commands_found=[]),
        }

        result = handle_command("system", [])

        assert result is True
        mock_sys_help.assert_called_once()

    def test_unknown_command_returns_false(self):
        """Unknown command should return False."""
        from aipass.drone.apps.modules.discovery import handle_command

        result = handle_command("nonexistent_command", [])

        assert result is False
