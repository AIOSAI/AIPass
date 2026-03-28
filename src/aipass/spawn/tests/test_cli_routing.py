# =================== AIPass ====================
# Name: test_cli_routing.py
# Description: Tests for CLI routing and help output
# Version: 1.0.0
# Created: 2026-03-27
# Modified: 2026-03-27
# =============================================

"""Tests for spawn CLI routing, help output, and introspection."""

import sys
import pytest
from unittest.mock import patch, MagicMock
from io import StringIO


class TestCliRouting:
    """Tests for spawn.py main() CLI routing."""

    def test_no_args_triggers_introspection(self):
        """main() with no args calls print_introspection."""
        from aipass.spawn.apps.spawn import main
        with patch("aipass.spawn.apps.spawn.sys") as mock_sys:
            mock_sys.argv = ["spawn"]
            with patch("aipass.spawn.apps.spawn.print_introspection") as mock_intro:
                result = main()
        assert result == 0
        mock_intro.assert_called_once()

    def test_help_flag(self):
        """main() with --help calls print_help."""
        from aipass.spawn.apps.spawn import main
        with patch("aipass.spawn.apps.spawn.sys") as mock_sys:
            mock_sys.argv = ["spawn", "--help"]
            with patch("aipass.spawn.apps.spawn.print_help") as mock_help:
                result = main()
        assert result == 0
        mock_help.assert_called_once()

    def test_short_help(self):
        """main() with -h calls print_help."""
        from aipass.spawn.apps.spawn import main
        with patch("aipass.spawn.apps.spawn.sys") as mock_sys:
            mock_sys.argv = ["spawn", "-h"]
            with patch("aipass.spawn.apps.spawn.print_help") as mock_help:
                result = main()
        assert result == 0
        mock_help.assert_called_once()

    def test_help_word(self):
        """main() with 'help' command calls print_help."""
        from aipass.spawn.apps.spawn import main
        with patch("aipass.spawn.apps.spawn.sys") as mock_sys:
            mock_sys.argv = ["spawn", "help"]
            with patch("aipass.spawn.apps.spawn.print_help") as mock_help:
                result = main()
        assert result == 0
        mock_help.assert_called_once()

    def test_unknown_command(self):
        """main() with unknown command returns 1."""
        from aipass.spawn.apps.spawn import main
        with patch("aipass.spawn.apps.spawn.sys") as mock_sys:
            mock_sys.argv = ["spawn", "nonexistent_command"]
            with patch("aipass.spawn.apps.spawn.error") as mock_error:
                result = main()
        assert result == 1
        mock_error.assert_called_once()

    def test_command_returns_int(self):
        """main() always returns an integer exit code."""
        from aipass.spawn.apps.spawn import main
        with patch("aipass.spawn.apps.spawn.sys") as mock_sys:
            mock_sys.argv = ["spawn"]
            with patch("aipass.spawn.apps.spawn.print_introspection"):
                result = main()
        assert isinstance(result, int)


class TestPrintHelp:
    """Tests for print_help output."""

    def test_print_help_runs(self):
        """print_help executes without error."""
        from aipass.spawn.apps.spawn import print_help
        with patch("aipass.spawn.apps.spawn.console") as mock_console:
            with patch("aipass.spawn.apps.spawn.header"):
                with patch("aipass.spawn.apps.spawn.warning"):
                    print_help()
        assert mock_console.print.called


class TestPrintIntrospection:
    """Tests for print_introspection output."""

    def test_print_introspection_runs(self):
        """print_introspection executes without error."""
        from aipass.spawn.apps.spawn import print_introspection
        with patch("aipass.spawn.apps.spawn.console") as mock_console:
            print_introspection()
        assert mock_console.print.called

    def test_output_capture(self):
        """Verify print_introspection mentions connected modules."""
        from aipass.spawn.apps.spawn import print_introspection
        calls = []
        with patch("aipass.spawn.apps.spawn.console") as mock_console:
            mock_console.print.side_effect = lambda *a, **kw: calls.append(str(a))
            print_introspection()
        output = " ".join(calls)
        assert "core.py" in output
