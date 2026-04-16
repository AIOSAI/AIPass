"""Tests for readme_update module."""

# =================== META ====================
# Name: test_readme_update.py
# Description: Unit tests for the readme_update module
# Version: 1.0.0
# Created: 2026-03-24
# Modified: 2026-03-24
# =============================================

import pytest
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _mock_infrastructure(monkeypatch):
    """Mock heavy infrastructure imports for readme_update."""
    import sys

    mock_logger = MagicMock()
    mock_console = MagicMock()
    mock_header = MagicMock()
    mock_error = MagicMock()
    mock_warning = MagicMock()
    mock_json_handler = MagicMock()

    # -- prax ---------------------------------------------------------------
    prax_mod = MagicMock()
    prax_mod.logger = mock_logger
    monkeypatch.setitem(sys.modules, "aipass.prax", prax_mod)

    # -- cli ----------------------------------------------------------------
    cli_mod = MagicMock()
    cli_mod.console = mock_console
    cli_mod.header = mock_header
    monkeypatch.setitem(sys.modules, "aipass.cli", cli_mod)

    cli_apps = MagicMock()
    monkeypatch.setitem(sys.modules, "aipass.cli.apps", cli_apps)

    cli_modules = MagicMock()
    cli_modules.error = mock_error
    cli_modules.warning = mock_warning
    monkeypatch.setitem(sys.modules, "aipass.cli.apps.modules", cli_modules)

    # -- seedgo json handler ------------------------------------------------
    json_pkg = MagicMock()
    json_pkg.json_handler = mock_json_handler
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.json", json_pkg)
    json_mod = MagicMock()
    json_mod.log_operation = mock_json_handler.log_operation
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.json.json_handler", json_mod)

    # -- readme ops handler -------------------------------------------------
    readme_pkg = MagicMock()
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.readme", readme_pkg)
    readme_ops_mod = MagicMock()
    readme_ops_mod.load_generator = MagicMock(return_value=None)
    readme_ops_mod.resolve_targets = MagicMock(return_value=([], "no_args"))
    readme_ops_mod.SECTION_NAMES = {
        "TREE": "Directory Tree",
        "MODULES": "Module List",
        "COMMANDS": "Commands",
        "HEADER": "Branch Header",
        "LAST_UPDATED": "Last Updated",
    }
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.readme.readme_ops", readme_ops_mod)

    # Force re-import
    monkeypatch.delitem(sys.modules, "aipass.seedgo.apps.modules.readme_update", raising=False)


# ---------------------------------------------------------------------------
# Tests — handle_command
# ---------------------------------------------------------------------------


def test_handle_command_wrong_command_returns_false():
    """handle_command returns False for unrecognised commands."""
    from aipass.seedgo.apps.modules.readme_update import handle_command

    assert handle_command("wrong_command", []) is False


def test_handle_command_accepts_readme_name():
    """handle_command recognises 'readme' as its command."""
    from aipass.seedgo.apps.modules.readme_update import handle_command

    result = handle_command("readme", [])
    assert result is True


def test_handle_command_accepts_readme_update_name():
    """handle_command recognises 'readme_update' as its command."""
    from aipass.seedgo.apps.modules.readme_update import handle_command

    result = handle_command("readme_update", [])
    assert result is True


def test_handle_command_no_args_shows_introspection():
    """No args triggers introspection (returns True)."""
    from aipass.seedgo.apps.modules.readme_update import handle_command

    result = handle_command("readme", [])
    assert result is True


def test_handle_command_help_flag():
    """--help flag is handled without error."""
    from aipass.seedgo.apps.modules.readme_update import handle_command

    result = handle_command("readme", ["--help"])
    assert result is True


def test_handle_command_h_flag():
    """-h flag is handled without error."""
    from aipass.seedgo.apps.modules.readme_update import handle_command

    result = handle_command("readme", ["-h"])
    assert result is True


def test_handle_command_unknown_subcommand():
    """Unknown subcommand returns True (error displayed to user)."""
    from aipass.seedgo.apps.modules.readme_update import handle_command

    result = handle_command("readme", ["bogus_subcommand"])
    assert result is True


def test_handle_command_update_subcommand():
    """'update' subcommand is routed without crashing."""
    from aipass.seedgo.apps.modules.readme_update import handle_command

    result = handle_command("readme", ["update"])
    assert result is True


def test_handle_command_check_subcommand():
    """'check' subcommand is routed without crashing."""
    from aipass.seedgo.apps.modules.readme_update import handle_command

    result = handle_command("readme", ["check"])
    assert result is True


# ---------------------------------------------------------------------------
# Tests — introspection / help
# ---------------------------------------------------------------------------


def test_print_introspection_runs():
    """print_introspection produces console output."""
    import sys
    from aipass.seedgo.apps.modules.readme_update import print_introspection

    mock_cli = sys.modules["aipass.cli"]
    mock_cli.console.reset_mock()
    mock_cli.header.reset_mock()
    result = print_introspection()
    assert result is None
    assert mock_cli.console.print.called or mock_cli.header.called, "print_introspection should produce console output"


def test_print_help_runs():
    """print_help produces console output."""
    import sys
    from aipass.seedgo.apps.modules.readme_update import print_help

    mock_cli = sys.modules["aipass.cli"]
    mock_cli.console.reset_mock()
    mock_cli.header.reset_mock()
    result = print_help()
    assert result is None
    assert mock_cli.console.print.called or mock_cli.header.called, "print_help should produce console output"


# ---------------------------------------------------------------------------
# Tests — display helpers
# ---------------------------------------------------------------------------


def test_print_target_error_no_args():
    """_print_target_error handles 'no_args' code without raising."""
    from aipass.seedgo.apps.modules.readme_update import _print_target_error

    _print_target_error("no_args")


def test_print_target_error_no_branches():
    """_print_target_error handles 'no_branches' code without raising."""
    from aipass.seedgo.apps.modules.readme_update import _print_target_error

    _print_target_error("no_branches")


def test_print_target_error_not_found():
    """_print_target_error handles 'not_found:xyz' code without raising."""
    from aipass.seedgo.apps.modules.readme_update import _print_target_error

    _print_target_error("not_found:some_branch")


def test_print_result_empty():
    """_print_result handles empty result dict without raising."""
    from aipass.seedgo.apps.modules.readme_update import _print_result

    _print_result({"updated": [], "missing_markers": [], "errors": []})


def test_print_result_with_errors():
    """_print_result displays errors without raising."""
    from aipass.seedgo.apps.modules.readme_update import _print_result

    _print_result({"updated": [], "missing_markers": [], "errors": ["Something went wrong"]})
