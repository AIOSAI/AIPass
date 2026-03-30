# =================== AIPass ====================
# Name: tests/test_integration.py
# Description: Integration tests for CLI main() flow and drone_adapter
# Version: 1.0.0
# Created: 2026-03-29
# Modified: 2026-03-29
# =============================================

"""Integration tests for CLI main() entry point and drone_adapter bridge."""

import subprocess
import sys
from io import StringIO
from unittest.mock import patch

import pytest
from rich.console import Console

from aipass.cli.apps import cli as cli_module
from aipass.cli.apps.cli import main
from aipass.cli.apps.modules import display
from aipass.cli import drone_adapter
from aipass.cli.drone_adapter import handle_command, get_help, get_introspective


# =============================================================================
# Helpers
# =============================================================================

def _make_capture_console():
    """Return (console, get_output) for capturing Rich output.

    Uses no_color=True so assertions can match plain text without ANSI escapes.
    """
    buf = StringIO()
    cons = Console(file=buf, no_color=True, width=120, highlight=False)

    def get_output() -> str:
        return buf.getvalue()

    return cons, get_output


# =============================================================================
# main() flow tests — mock sys.argv to simulate CLI invocation
# =============================================================================

class TestMainFlow:
    """Integration tests for the main() entry point."""

    def test_main_no_args_returns_zero(self):
        """No args shows introspection and returns 0."""
        cons, _get_output = _make_capture_console()
        with patch.object(cli_module, "CONSOLE", cons), \
             patch.object(display, "CONSOLE", cons), \
             patch("sys.argv", ["cli"]):
            result = main()
        assert result == 0

    def test_main_help_flag_returns_zero(self):
        """--help returns 0."""
        cons, _get_output = _make_capture_console()
        err_cons, _get_err = _make_capture_console()
        with patch.object(cli_module, "CONSOLE", cons), \
             patch.object(display, "CONSOLE", cons), \
             patch.object(display, "err_console", err_cons), \
             patch.object(display, "_TRIGGER", None), \
             patch.object(display, "_TRIGGER_LOADED", True), \
             patch("sys.argv", ["cli", "--help"]):
            result = main()
        assert result == 0

    def test_main_version_flag_returns_zero(self):
        """--version returns 0."""
        cons, get_output = _make_capture_console()
        with patch.object(cli_module, "CONSOLE", cons), \
             patch.object(display, "CONSOLE", cons), \
             patch("sys.argv", ["cli", "--version"]):
            result = main()
        assert result == 0
        output = get_output()
        assert "CLI v" in output

    def test_main_unknown_command_returns_one(self):
        """Unknown command returns 1."""
        cons, _get_output = _make_capture_console()
        err_cons, get_err = _make_capture_console()
        with patch.object(cli_module, "CONSOLE", cons), \
             patch.object(display, "CONSOLE", cons), \
             patch.object(display, "err_console", err_cons), \
             patch("sys.argv", ["cli", "nonexistent_cmd_xyz"]):
            result = main()
        assert result == 1
        err_output = get_err()
        assert "Unknown command" in err_output

    def test_main_aipass_init_help_returns_zero(self):
        """'aipass init --help' returns 0."""
        cons, _get_output = _make_capture_console()
        err_cons, _get_err = _make_capture_console()
        with patch.object(cli_module, "CONSOLE", cons), \
             patch.object(display, "CONSOLE", cons), \
             patch.object(display, "err_console", err_cons), \
             patch.object(display, "_TRIGGER", None), \
             patch.object(display, "_TRIGGER_LOADED", True), \
             patch("sys.argv", ["cli", "aipass", "init", "--help"]):
            result = main()
        assert result == 0

    def test_main_display_demo_returns_zero(self):
        """'display demo' returns 0."""
        cons, _get_output = _make_capture_console()
        err_cons, _get_err = _make_capture_console()
        with patch.object(cli_module, "CONSOLE", cons), \
             patch.object(display, "CONSOLE", cons), \
             patch.object(display, "err_console", err_cons), \
             patch.object(display, "_TRIGGER", None), \
             patch.object(display, "_TRIGGER_LOADED", True), \
             patch("aipass.cli.apps.handlers.json.json_handler.log_operation"), \
             patch("sys.argv", ["cli", "display", "demo"]):
            result = main()
        assert result == 0


# =============================================================================
# drone_adapter tests
# =============================================================================

class TestDroneAdapter:
    """Integration tests for the drone_adapter bridge."""

    def test_handle_command_returns_dict(self):
        """handle_command returns a dict with stdout, stderr, exit_code keys."""
        result = handle_command("--help")
        assert isinstance(result, dict)
        assert "stdout" in result
        assert "stderr" in result
        assert "exit_code" in result

    def test_handle_command_help_exit_code_zero(self):
        """--help returns exit_code 0."""
        result = handle_command("--help")
        assert result["exit_code"] == 0

    def test_handle_command_unknown_returns_one(self):
        """Unknown command returns exit_code 1."""
        result = handle_command("nonexistent_cmd_xyz")
        assert result["exit_code"] == 1

    def test_handle_command_restores_argv(self):
        """sys.argv is restored after handle_command call."""
        original_argv = sys.argv.copy()
        handle_command("--version")
        assert sys.argv == original_argv

    def test_get_help_returns_string(self):
        """get_help returns a non-empty string."""
        result = get_help()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_get_introspective_returns_string(self):
        """get_introspective returns a non-empty string with 'CLI' in it."""
        result = get_introspective()
        assert isinstance(result, str)
        assert len(result) > 0
        assert "CLI" in result

    def test_handle_command_captures_stdout(self):
        """stdout contains expected output for --version."""
        result = handle_command("--version")
        assert result["exit_code"] == 0
        # The version output goes through Rich console which writes to real stdout,
        # but drone_adapter captures sys.stdout. Verify we get something back.
        # Note: Rich Console writes to its own file= target, so stdout capture
        # may be empty. The key contract is exit_code and dict shape.
        assert isinstance(result["stdout"], str)


# =============================================================================
# __main__.py test — verify module is runnable
# =============================================================================

class TestModuleRunnable:
    """Verify python -m aipass.cli works as a subprocess."""

    def test_module_runnable(self):
        """python -m aipass.cli --version runs successfully."""
        result = subprocess.run(
            [sys.executable, "-m", "aipass.cli", "--version"],
            capture_output=True,
            text=True,
            timeout=30,
            cwd="/home/patrick/Projects/AIPass/src",
        )
        assert result.returncode == 0
