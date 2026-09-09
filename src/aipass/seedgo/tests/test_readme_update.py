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
    """print_introspection names the module and both handlers it is wired to.

    Was `assert console.print.called or header.called` — an OR that passes on
    either half, so a version that printed nothing but touched the header
    still passed. These are the lines the function actually emits, measured
    2026-09-07; `console`/`header` are the fixture mocks the module binds.
    """
    from aipass.seedgo.apps.modules.readme_update import console, header, print_introspection

    assert print_introspection() is None

    lines = [call.args[0] for call in console.print.call_args_list if call.args]
    assert "[bold cyan]readme_update Module[/bold cyan]" in lines
    assert "  [cyan]handlers/readme/[/cyan]" in lines
    assert "  [cyan]handlers/json/[/cyan]" in lines
    assert "  [dim]- aipass.cli (console, header)[/dim]" in lines
    assert header.call_args_list == []


def test_print_help_runs():
    """print_help prints the command list under the 'README Auto-Update' header.

    Was `assert console.print.called or header.called` — an OR that passes on
    either half. Both halves are real here, so both are pinned separately,
    against the strings measured 2026-09-07.
    """
    from aipass.seedgo.apps.modules.readme_update import console, header, print_help

    assert print_help() is None

    lines = [call.args[0] for call in console.print.call_args_list if call.args]
    header.assert_called_once_with("README Auto-Update")
    assert "[yellow]COMMANDS:[/yellow]" in lines
    assert "[yellow]AUTO-GENERATED SECTIONS:[/yellow]" in lines
    assert "  LAST_UPDATED  Timestamp" in lines
    assert "[dim]Commands: readme, --help[/dim]" in lines


# ---------------------------------------------------------------------------
# Tests — display helpers
# ---------------------------------------------------------------------------


def test_print_target_error_not_found():
    """_print_target_error names the unresolved branch, on the error channel.

    Was a bare call that asserted nothing (no_oracle): it could not tell the
    branch name being reported from it being swallowed. Measured 2026-09-07 —
    this arm routes to cli's error(), and prints nothing on console.
    """
    from aipass.seedgo.apps.modules.readme_update import _print_target_error, console, display_error

    _print_target_error("not_found:some_branch")

    reported = [call.args[0] for call in display_error.call_args_list if call.args]
    assert reported == ["Branch 'some_branch' not found in registry"]
    assert console.print.call_args_list == []


def test_print_result_empty():
    """Nothing updated, nothing missing, no errors: _print_result says nothing.

    Silence is the design here, and this pins it. Was a bare call that
    asserted nothing (no_oracle). Measured 2026-09-07: outside check mode
    every section falls to the else arm, which prints only when is_check is
    True — so an empty result really does emit zero lines on either channel.
    """
    from aipass.seedgo.apps.modules.readme_update import _print_result, console, display_error

    _print_result({"updated": [], "missing_markers": [], "errors": []})

    assert console.print.call_args_list == []
    assert display_error.call_args_list == []


def test_print_result_with_errors():
    """_print_result reports the error and stops: it does not also list sections.

    Was a bare call that asserted nothing (no_oracle). "TREE" is in `updated`
    on purpose: without the early return after the errors, console would carry
    "  [green]Updated[/green] Directory Tree" (measured 2026-09-07), so the
    console-silence assertion is what pins the return.
    """
    from aipass.seedgo.apps.modules.readme_update import _print_result, console, display_error

    _print_result({"updated": ["TREE"], "missing_markers": [], "errors": ["Something went wrong"]})

    reported = [call.args[0] for call in display_error.call_args_list if call.args]
    assert reported == ["Something went wrong"]
    assert console.print.call_args_list == []
