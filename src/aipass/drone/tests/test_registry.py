# =================== AIPass ====================
# Name: test_registry.py
# Description: Tests for the registry module orchestrator
# Version: 1.0.2
# Created: 2026-04-26
# Modified: 2026-09-27
# =============================================

"""Tests for apps/modules/registry.py: introspection, help, and the load, branches and lookup commands."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that the module under test parses and imports

from unittest.mock import patch

import pytest

from aipass.cli.apps.modules import display
from aipass.drone.apps.modules.registry import handle_command, print_help, print_introspection

_REG = "aipass.drone.apps.modules.registry"


# ===========================================================================
# print_introspection
# ===========================================================================


class TestPrintIntrospection:
    """print_introspection() output."""

    def test_prints_module_info(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Prints registry module info to stdout."""

        print_introspection()
        captured = capsys.readouterr()
        assert "registry" in captured.out.lower()
        assert "handler" in captured.out.lower()

    def test_fallback_console(self, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
        """Falls back to rich.Console when CLI console unavailable; mutant killed: the fallback arm removed.

        @cli's display without its ``console`` export is the edge: ``from ... import
        console`` then raises ImportError, with no sys.modules entry replaced.
        """
        monkeypatch.delattr(display, "console")
        with patch(f"{_REG}.logger") as log:
            print_introspection()
        captured = capsys.readouterr()
        assert "registry" in captured.out.lower()
        log.warning.assert_called_once_with("CLI console not available, using fallback")


# ===========================================================================
# print_help
# ===========================================================================


class TestPrintHelp:
    """print_help() output."""

    def test_prints_help(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Prints help text with command list."""

        print_help()
        captured = capsys.readouterr()
        assert "load" in captured.out
        assert "branches" in captured.out
        assert "lookup" in captured.out


# ===========================================================================
# handle_command — introspection and help
# ===========================================================================


class TestHandleCommandIntrospection:
    """handle_command() introspection and help paths."""

    def test_no_command_no_args_introspection(self) -> None:
        """No command + no args triggers introspection."""

        with patch(f"{_REG}.print_introspection") as mock_intro:
            result = handle_command()
        assert result is True
        mock_intro.assert_called_once()

    def test_help_flag_command(self) -> None:
        """--help as command triggers print_help."""

        with patch(f"{_REG}.print_help") as mock_help:
            result = handle_command("--help")
        assert result is True
        mock_help.assert_called_once()

    def test_h_flag_command(self) -> None:
        """-h as command triggers print_help."""

        with patch(f"{_REG}.print_help") as mock_help:
            result = handle_command("-h")
        assert result is True
        mock_help.assert_called_once()

    def test_help_in_args(self) -> None:
        """--help in args triggers print_help."""

        with patch(f"{_REG}.print_help") as mock_help:
            result = handle_command("load", ["--help"])
        assert result is True
        mock_help.assert_called_once()


# ===========================================================================
# handle_command — load
# ===========================================================================


class TestHandleCommandLoad:
    """handle_command('load') path."""

    def test_load_success(self) -> None:
        """load logs the branch count it read; mutant killed: the count logged as 0."""

        mock_registry = {"branches": {"drone": {}, "seedgo": {}}}
        with patch(f"{_REG}.load_registry", return_value=mock_registry), patch(f"{_REG}.logger") as log:
            result = handle_command("load", [])
        assert result is True
        log.info.assert_called_once_with("Registry loaded: %d branches", 2)

    def test_load_empty_registry(self) -> None:
        """load with an empty registry logs zero branches; mutant killed: the count never logged."""

        with patch(f"{_REG}.load_registry", return_value={}), patch(f"{_REG}.logger") as log:
            result = handle_command("load", [])
        assert result is True
        log.info.assert_called_once_with("Registry loaded: %d branches", 0)


# ===========================================================================
# handle_command — branches
# ===========================================================================


class TestHandleCommandBranches:
    """handle_command('branches') path."""

    def test_branches_no_filter(self) -> None:
        """branches with no args lists all branches."""

        mock_branches = [{"name": "drone"}, {"name": "seedgo"}]
        with patch(f"{_REG}.get_all_branches", return_value=mock_branches) as mock_gab:
            result = handle_command("branches", [])
        assert result is True
        mock_gab.assert_called_once_with(branch_type=None)

    def test_branches_with_type_filter(self) -> None:
        """branches with type arg filters by type."""

        with patch(f"{_REG}.get_all_branches", return_value=[]) as mock_gab:
            result = handle_command("branches", ["library"])
        assert result is True
        mock_gab.assert_called_once_with(branch_type="library")


# ===========================================================================
# handle_command — lookup
# ===========================================================================


class TestHandleCommandLookup:
    """handle_command('lookup') path."""

    def test_lookup_no_args(self) -> None:
        """lookup with no args returns False."""

        result = handle_command("lookup", [])
        assert result is False

    def test_lookup_found(self) -> None:
        """lookup logs the branch record it found; mutant killed: the name logged instead of the record."""

        mock_branch = {"name": "drone", "profile": "library"}
        with patch(f"{_REG}.get_branch_by_name", return_value=mock_branch), patch(f"{_REG}.logger") as log:
            result = handle_command("lookup", ["drone"])
        assert result is True
        log.info.assert_called_once_with("Branch: %s", mock_branch)

    def test_lookup_not_found(self) -> None:
        """lookup with missing branch returns False."""

        with patch(f"{_REG}.get_branch_by_name", return_value=None):
            result = handle_command("lookup", ["ghost"])
        assert result is False


# ===========================================================================
# handle_command — unknown
# ===========================================================================


class TestHandleCommandUnknown:
    """handle_command() unknown command path."""

    def test_unknown_command(self) -> None:
        """Unknown command returns False."""

        result = handle_command("nonexistent", ["arg"])
        assert result is False

    def test_none_command_with_args(self) -> None:
        """None command with args (no --help) falls through to unknown."""

        result = handle_command(None, ["some_arg"])
        assert result is False
