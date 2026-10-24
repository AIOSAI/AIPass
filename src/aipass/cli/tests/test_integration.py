# =================== AIPass ====================
# Name: tests/test_integration.py
# Description: Integration tests for CLI main() flow
# Version: 2.2.0
# Created: 2026-03-29
# Modified: 2026-10-23
# =============================================

"""Tests for apps/cli.py main() — the routed flow end to end."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(help_flag_safety) — that each module's handle_command calls wants_help before acting

from unittest.mock import patch

import pytest

from aipass.cli.apps import cli as cli_module
from aipass.cli.apps.cli import main
from aipass.cli.apps.modules import display
from aipass.cli.apps.modules import templates

from .conftest import make_capture_console


def _make_capture_console():
    """Return (console, get_output) for capturing Rich output."""
    return make_capture_console(highlight=False)


class TestMainFlow:
    """Integration tests for the main() entry point."""

    def test_main_no_args_returns_zero(self):
        """No args shows introspection and returns 0."""
        cons, _get_output = _make_capture_console()
        with (
            patch.object(cli_module, "console", cons),
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
            patch.object(cli_module, "console", cons),
            patch.object(display, "CONSOLE", cons),
            patch.object(display, "err_console", err_cons),
            patch("sys.argv", ["cli", "--help"]),
        ):
            result = main()
        assert result == 0

    def test_main_version_flag_returns_zero(self):
        """--version returns 0."""
        cons, get_output = _make_capture_console()
        with (
            patch.object(cli_module, "console", cons),
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
            patch.object(cli_module, "console", cons),
            patch.object(display, "CONSOLE", cons),
            patch.object(display, "err_console", err_cons),
            patch("sys.argv", ["cli", "nonexistent_cmd_xyz"]),
        ):
            result = main()
        assert result == 1
        err_output = get_err()
        assert "Unknown command" in err_output

    def test_main_display_demo_returns_zero(self):
        """'display demo' returns 0."""
        cons, _get_output = _make_capture_console()
        err_cons, _get_err = _make_capture_console()
        with (
            patch.object(cli_module, "console", cons),
            patch.object(display, "CONSOLE", cons),
            patch.object(display, "err_console", err_cons),
            patch("sys.argv", ["cli", "display", "demo"]),
        ):
            result = main()
        assert result == 0


class TestBareDemo:
    """A bare `demo` has one owner, whatever order the modules are discovered in."""

    @pytest.mark.parametrize("order", [(templates, display), (display, templates)])
    def test_bare_demo_runs_the_display_demo_and_not_the_templates_demo(self, capsys, order):
        handled = cli_module.route_command("demo", [], list(order))
        out, _err = capsys.readouterr()
        assert handled is True
        assert "CLI Display Module - Demo" in out
        assert "CLI Templates Module - Demo" not in out
