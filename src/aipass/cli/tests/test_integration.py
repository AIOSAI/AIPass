# =================== AIPass ====================
# Name: tests/test_integration.py
# Description: Integration tests for CLI main() flow
# Version: 2.0.0
# Created: 2026-03-29
# Modified: 2026-03-30
# =============================================

"""Integration tests for CLI main() entry point."""

import subprocess
import sys
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest
from rich.console import Console

from aipass.cli import cli_entry
from aipass.cli.apps import cli as cli_module
from aipass.cli.apps.cli import main
from aipass.cli.apps.modules import display


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
        with (
            patch.object(cli_module, "CONSOLE", cons),
            patch.object(display, "CONSOLE", cons),
            patch("sys.argv", ["cli"]),
        ):
            result = main()
        assert result == 0

    def test_main_help_flag_returns_zero(self):
        """--help returns 0."""
        cons, _get_output = _make_capture_console()
        err_cons, _get_err = _make_capture_console()
        with (
            patch.object(cli_module, "CONSOLE", cons),
            patch.object(display, "CONSOLE", cons),
            patch.object(display, "err_console", err_cons),
            patch.object(display, "_TRIGGER", None),
            patch.object(display, "_TRIGGER_LOADED", True),
            patch("sys.argv", ["cli", "--help"]),
        ):
            result = main()
        assert result == 0

    def test_main_version_flag_returns_zero(self):
        """--version returns 0."""
        cons, get_output = _make_capture_console()
        with (
            patch.object(cli_module, "CONSOLE", cons),
            patch.object(display, "CONSOLE", cons),
            patch("sys.argv", ["cli", "--version"]),
        ):
            result = main()
        assert result == 0
        output = get_output()
        assert "CLI v" in output

    def test_main_unknown_command_returns_one(self):
        """Unknown command returns 1."""
        cons, _get_output = _make_capture_console()
        err_cons, get_err = _make_capture_console()
        with (
            patch.object(cli_module, "CONSOLE", cons),
            patch.object(display, "CONSOLE", cons),
            patch.object(display, "err_console", err_cons),
            patch("sys.argv", ["cli", "nonexistent_cmd_xyz"]),
        ):
            result = main()
        assert result == 1
        err_output = get_err()
        assert "Unknown command" in err_output

    def test_main_aipass_init_help_returns_zero(self):
        """'aipass init --help' returns 0."""
        cons, _get_output = _make_capture_console()
        err_cons, _get_err = _make_capture_console()
        with (
            patch.object(cli_module, "CONSOLE", cons),
            patch.object(display, "CONSOLE", cons),
            patch.object(display, "err_console", err_cons),
            patch.object(display, "_TRIGGER", None),
            patch.object(display, "_TRIGGER_LOADED", True),
            patch("sys.argv", ["cli", "aipass", "init", "--help"]),
        ):
            result = main()
        assert result == 0

    def test_main_display_demo_returns_zero(self):
        """'display demo' returns 0."""
        cons, _get_output = _make_capture_console()
        err_cons, _get_err = _make_capture_console()
        with (
            patch.object(cli_module, "CONSOLE", cons),
            patch.object(display, "CONSOLE", cons),
            patch.object(display, "err_console", err_cons),
            patch.object(display, "_TRIGGER", None),
            patch.object(display, "_TRIGGER_LOADED", True),
            patch("aipass.cli.apps.handlers.json.json_handler.log_operation"),
            patch("sys.argv", ["cli", "display", "demo"]),
        ):
            result = main()
        assert result == 0


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
            cwd=str(Path(__file__).resolve().parents[3]),
        )
        assert result.returncode == 0

    def test_cli_entry_callable(self):
        """cli_entry() is the console_scripts entry point — verify it's callable."""
        cons, _get_output = _make_capture_console()
        with (
            patch.object(cli_module, "CONSOLE", cons),
            patch.object(display, "CONSOLE", cons),
            patch("sys.argv", ["aipass", "--version"]),
            pytest.raises(SystemExit) as exc_info,
        ):
            cli_entry()
        assert exc_info.value.code == 0
