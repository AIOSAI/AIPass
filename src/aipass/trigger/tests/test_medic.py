"""Tests for the medic toggle module (apps/modules/medic.py)."""

# =================== META ====================
# Name: test_medic.py
# Description: Unit tests for medic module handle_command
# Version: 1.1.0
# Created: 2026-03-24
# Modified: 2026-03-24
# =============================================

import sys
import pytest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _mock_infrastructure(monkeypatch):
    """Mock heavy infrastructure imports before medic module loads."""

    mock_logger = MagicMock()

    # -- prax logger --------------------------------------------------------
    prax_logger_mod = MagicMock()
    prax_logger_mod.system_logger = mock_logger
    monkeypatch.setitem(sys.modules, "aipass.prax", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.prax.apps", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.prax.apps.modules", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.prax.apps.modules.logger", prax_logger_mod)

    # -- trigger json handler -----------------------------------------------
    mock_json_handler = MagicMock()
    mock_json_handler.log_operation = MagicMock(return_value=True)
    json_pkg = MagicMock()
    json_pkg.json_handler = mock_json_handler
    monkeypatch.setitem(sys.modules, "aipass.trigger.apps.handlers.json", json_pkg)
    json_mod = MagicMock()
    json_mod.log_operation = mock_json_handler.log_operation
    monkeypatch.setitem(sys.modules, "aipass.trigger.apps.handlers.json.json_handler", json_mod)

    # -- medic_state handler ------------------------------------------------
    medic_state_mod = MagicMock()
    medic_state_mod.is_enabled = MagicMock(return_value=True)
    medic_state_mod.set_enabled = MagicMock(return_value=True)
    medic_state_mod.get_muted_branches = MagicMock(return_value=[])
    medic_state_mod.mute_branch = MagicMock(return_value=True)
    medic_state_mod.unmute_branch = MagicMock(return_value=True)
    medic_state_mod.get_suppression_stats = MagicMock(return_value={
        "suppressed_count": 0,
        "last_suppressed": "never",
    })
    medic_state_mod.get_rate_limit_stats = MagicMock(return_value={
        "rate_limited_count": 0,
        "last_rate_limited": "never",
    })
    monkeypatch.setitem(sys.modules, "aipass.trigger.apps.handlers.medic_state", medic_state_mod)

    # -- CLI console (lazy import inside handle_command) --------------------
    mock_console = MagicMock()
    cli_modules = MagicMock()
    cli_modules.console = mock_console
    monkeypatch.setitem(sys.modules, "aipass.cli", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.cli.apps", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.cli.apps.modules", cli_modules)

    # display submodule (used in print_introspection)
    cli_display = MagicMock()
    cli_display.console = mock_console
    monkeypatch.setitem(sys.modules, "aipass.cli.apps.modules.display", cli_display)

    # -- rich.panel (used in on/off/help) -----------------------------------
    monkeypatch.setitem(sys.modules, "rich", MagicMock())
    monkeypatch.setitem(sys.modules, "rich.panel", MagicMock())
    monkeypatch.setitem(sys.modules, "rich.console", MagicMock())

    # -- Force re-import so mocks take effect -------------------------------
    monkeypatch.delitem(sys.modules, "aipass.trigger.apps.modules.medic", raising=False)


def _import_medic():
    """Import medic module fresh (after mocks are in place)."""
    import aipass.trigger.apps.modules.medic as medic
    return medic


def _get_medic_state():
    """Return the mocked medic_state module from sys.modules."""
    return sys.modules["aipass.trigger.apps.handlers.medic_state"]


def _get_console():
    """Return the mocked console from sys.modules."""
    return sys.modules["aipass.cli.apps.modules"].console


def _get_json_handler():
    """Return the mocked json_handler from sys.modules."""
    return sys.modules["aipass.trigger.apps.handlers.json.json_handler"]


def _get_print_str_args(console):
    """Extract all string positional arguments passed to console.print().

    Returns a flat list of strings -- only positional args that are actual
    str instances (ignoring MagicMock objects like Panel).
    """
    result = []
    for call in console.print.call_args_list:
        for arg in call.args:
            if isinstance(arg, str):
                result.append(arg)
    return result


# ---------------------------------------------------------------------------
# Tests -- handle_command "on"
# ---------------------------------------------------------------------------

def test_handle_command_on_enables_medic():
    """handle_command('on', []) calls set_enabled(True), prints Panel, returns True."""
    medic = _import_medic()

    with patch.object(medic, "_systemctl", return_value=True):
        with patch.object(medic, "_is_service_active", return_value=True):
            result = medic.handle_command("on", [])

    assert result is True
    state = _get_medic_state()
    state.set_enabled.assert_called_with(True)
    # Verify console.print was called (Panel is a mock object, but it was called)
    console = _get_console()
    assert console.print.call_count >= 1, "console.print should be called with success Panel"


def test_handle_command_on_starts_service_when_inactive():
    """handle_command('on', []) starts the systemd service when it is not running."""
    medic = _import_medic()

    with patch.object(medic, "_systemctl", return_value=True) as mock_ctl:
        with patch.object(medic, "_is_service_active", side_effect=[False, True]):
            medic.handle_command("on", [])

    mock_ctl.assert_called_with("start")


def test_handle_command_on_logs_operation():
    """handle_command('on', []) logs the medic_toggled operation."""
    medic = _import_medic()

    with patch.object(medic, "_systemctl", return_value=True):
        with patch.object(medic, "_is_service_active", return_value=True):
            medic.handle_command("on", [])

    jh = _get_json_handler()
    jh.log_operation.assert_called_with("medic_toggled", {"command": "on"})


def test_handle_command_on_failure_prints_error():
    """When set_enabled returns False, 'on' prints the exact failure message."""
    medic = _import_medic()
    state = _get_medic_state()
    state.set_enabled.return_value = False

    with patch.object(medic, "_systemctl", return_value=True):
        with patch.object(medic, "_is_service_active", return_value=False):
            result = medic.handle_command("on", [])

    assert result is True
    console = _get_console()
    printed = _get_print_str_args(console)
    expected_msg = "[red]Failed to enable Medic[/red] - check trigger_config.json"
    assert expected_msg in printed, (
        f"Expected exact error message '{expected_msg}' in printed args: {printed}"
    )


# ---------------------------------------------------------------------------
# Tests -- handle_command "off"
# ---------------------------------------------------------------------------

def test_handle_command_off_disables_medic():
    """handle_command('off', []) calls set_enabled(False), prints Panel, returns True."""
    medic = _import_medic()

    with patch.object(medic, "_systemctl", return_value=True):
        with patch.object(medic, "_is_service_active", return_value=False):
            result = medic.handle_command("off", [])

    assert result is True
    state = _get_medic_state()
    state.set_enabled.assert_called_with(False)
    # Verify console.print was called (Panel is a mock object for success output)
    console = _get_console()
    assert console.print.call_count >= 1, "console.print should be called with success Panel"


def test_handle_command_off_stops_active_service():
    """handle_command('off', []) stops the service when it is active."""
    medic = _import_medic()

    with patch.object(medic, "_systemctl", return_value=True) as mock_ctl:
        with patch.object(medic, "_is_service_active", return_value=True):
            medic.handle_command("off", [])

    mock_ctl.assert_called_with("stop")


def test_handle_command_off_failure_prints_error():
    """When set_enabled returns False, 'off' prints the exact failure message."""
    medic = _import_medic()
    state = _get_medic_state()
    state.set_enabled.return_value = False

    with patch.object(medic, "_systemctl", return_value=True):
        with patch.object(medic, "_is_service_active", return_value=False):
            result = medic.handle_command("off", [])

    assert result is True
    console = _get_console()
    printed = _get_print_str_args(console)
    expected_msg = "[red]Failed to disable Medic[/red] - check trigger_config.json"
    assert expected_msg in printed, (
        f"Expected exact error message '{expected_msg}' in printed args: {printed}"
    )


# ---------------------------------------------------------------------------
# Tests -- handle_command "status"
# ---------------------------------------------------------------------------

def test_handle_command_status_returns_current_state():
    """handle_command('status', []) displays state info and returns True."""
    medic = _import_medic()

    with patch.object(medic, "_is_service_active", return_value=True):
        result = medic.handle_command("status", [])

    assert result is True
    state = _get_medic_state()
    state.is_enabled.assert_called_once()
    state.get_muted_branches.assert_called_once()
    state.get_suppression_stats.assert_called_once()
    state.get_rate_limit_stats.assert_called_once()


def test_handle_command_status_shows_enabled():
    """When medic is enabled, status output includes the ENABLED state line."""
    medic = _import_medic()

    with patch.object(medic, "_is_service_active", return_value=True):
        medic.handle_command("status", [])

    console = _get_console()
    printed = _get_print_str_args(console)
    state_line = "  State:           [green]ENABLED[/green]"
    assert state_line in printed, (
        f"Expected state line '{state_line}' in printed args: {printed}"
    )


def test_handle_command_status_shows_disabled():
    """When medic is disabled, status output includes the DISABLED state line."""
    medic = _import_medic()
    state = _get_medic_state()
    state.is_enabled.return_value = False

    with patch.object(medic, "_is_service_active", return_value=False):
        medic.handle_command("status", [])

    console = _get_console()
    printed = _get_print_str_args(console)
    state_line = "  State:           [yellow]DISABLED[/yellow]"
    assert state_line in printed, (
        f"Expected state line '{state_line}' in printed args: {printed}"
    )


def test_handle_command_status_shows_muted_branches():
    """When branches are muted, status lists them in the muted branches line."""
    medic = _import_medic()
    state = _get_medic_state()
    state.get_muted_branches.return_value = ["speakeasy", "api"]

    with patch.object(medic, "_is_service_active", return_value=True):
        medic.handle_command("status", [])

    console = _get_console()
    printed = _get_print_str_args(console)
    # Source builds: "  Muted branches:  @speakeasy, @api"
    muted_line = "  Muted branches:  @speakeasy, @api"
    assert muted_line in printed, (
        f"Expected muted line '{muted_line}' in printed args: {printed}"
    )


def test_handle_command_status_suppression_hint_when_disabled():
    """When medic is disabled, status prints the exact suppression hint."""
    medic = _import_medic()
    state = _get_medic_state()
    state.is_enabled.return_value = False

    with patch.object(medic, "_is_service_active", return_value=False):
        medic.handle_command("status", [])

    console = _get_console()
    printed = _get_print_str_args(console)
    hint = "  [dim]All error dispatch suppressed. Errors logged to medic_suppressed.log[/dim]"
    assert hint in printed, (
        f"Expected suppression hint '{hint}' in printed args: {printed}"
    )


# ---------------------------------------------------------------------------
# Tests -- handle_command "mute"
# ---------------------------------------------------------------------------

def test_handle_command_mute_branch():
    """handle_command('mute', ['@speakeasy']) mutes the branch."""
    medic = _import_medic()
    result = medic.handle_command("mute", ["@speakeasy"])

    assert result is True
    state = _get_medic_state()
    state.mute_branch.assert_called_once_with("speakeasy")


def test_handle_command_mute_branch_without_at():
    """handle_command('mute', ['speakeasy']) handles names without @ prefix."""
    medic = _import_medic()
    medic.handle_command("mute", ["speakeasy"])

    state = _get_medic_state()
    state.mute_branch.assert_called_once_with("speakeasy")


def test_handle_command_mute_prints_confirmation():
    """Successful mute prints the exact confirmation message with the branch name."""
    medic = _import_medic()
    medic.handle_command("mute", ["@api"])

    console = _get_console()
    printed = _get_print_str_args(console)
    expected = "  [yellow]Muted[/yellow] @api — errors logged but not dispatched"
    assert expected in printed, (
        f"Expected mute confirmation '{expected}' in printed args: {printed}"
    )


def test_handle_command_mute_failure_prints_error():
    """When mute_branch returns False, the exact error message is printed."""
    medic = _import_medic()
    state = _get_medic_state()
    state.mute_branch.return_value = False

    medic.handle_command("mute", ["@api"])

    console = _get_console()
    printed = _get_print_str_args(console)
    expected = "  [red]Failed to mute[/red] @api — check trigger_config.json"
    assert expected in printed, (
        f"Expected mute failure message '{expected}' in printed args: {printed}"
    )


def test_handle_command_mute_without_branch_name():
    """handle_command('mute', []) prints the exact usage error when no branch given."""
    medic = _import_medic()
    result = medic.handle_command("mute", [])

    assert result is True
    console = _get_console()
    printed = _get_print_str_args(console)
    expected = "[red]Missing branch name[/red] - usage: medic mute @branch"
    assert expected in printed, (
        f"Expected usage error '{expected}' in printed args: {printed}"
    )
    # Should NOT have called mute_branch
    state = _get_medic_state()
    state.mute_branch.assert_not_called()


# ---------------------------------------------------------------------------
# Tests -- handle_command "unmute"
# ---------------------------------------------------------------------------

def test_handle_command_unmute_branch():
    """handle_command('unmute', ['@speakeasy']) unmutes the branch."""
    medic = _import_medic()
    result = medic.handle_command("unmute", ["@speakeasy"])

    assert result is True
    state = _get_medic_state()
    state.unmute_branch.assert_called_once_with("speakeasy")


def test_handle_command_unmute_prints_confirmation():
    """Successful unmute prints the exact confirmation message."""
    medic = _import_medic()
    medic.handle_command("unmute", ["@flow"])

    console = _get_console()
    printed = _get_print_str_args(console)
    expected = "  [green]Unmuted[/green] @flow — dispatch resumed"
    assert expected in printed, (
        f"Expected unmute confirmation '{expected}' in printed args: {printed}"
    )


def test_handle_command_unmute_already_unmuted():
    """Unmuting a branch that is not muted prints the exact failure message."""
    medic = _import_medic()
    state = _get_medic_state()
    state.unmute_branch.return_value = False

    result = medic.handle_command("unmute", ["@nonexistent"])

    assert result is True
    console = _get_console()
    printed = _get_print_str_args(console)
    expected = "  [red]Failed to unmute[/red] @nonexistent — check trigger_config.json"
    assert expected in printed, (
        f"Expected unmute failure message '{expected}' in printed args: {printed}"
    )


def test_handle_command_unmute_without_branch_name():
    """handle_command('unmute', []) prints the exact usage error when no branch given."""
    medic = _import_medic()
    result = medic.handle_command("unmute", [])

    assert result is True
    console = _get_console()
    printed = _get_print_str_args(console)
    expected = "[red]Missing branch name[/red] - usage: medic unmute @branch"
    assert expected in printed, (
        f"Expected usage error '{expected}' in printed args: {printed}"
    )
    state = _get_medic_state()
    state.unmute_branch.assert_not_called()


# ---------------------------------------------------------------------------
# Tests -- handle_command "--help"
# ---------------------------------------------------------------------------

def test_handle_command_help_flag():
    """handle_command('medic', ['--help']) calls print_help and returns True."""
    medic = _import_medic()

    with patch.object(medic, "print_help") as mock_help:
        result = medic.handle_command("medic", ["--help"])

    assert result is True
    mock_help.assert_called_once()


def test_handle_command_help_word():
    """handle_command('medic', ['help']) also triggers help."""
    medic = _import_medic()

    with patch.object(medic, "print_help") as mock_help:
        result = medic.handle_command("medic", ["help"])

    assert result is True
    mock_help.assert_called_once()


def test_handle_command_subcommand_help():
    """handle_command('on', ['--help']) shows help instead of enabling."""
    medic = _import_medic()

    with patch.object(medic, "print_help") as mock_help:
        result = medic.handle_command("on", ["--help"])

    assert result is True
    mock_help.assert_called_once()
    # set_enabled should NOT have been called
    state = _get_medic_state()
    state.set_enabled.assert_not_called()


# ---------------------------------------------------------------------------
# Tests -- handle_command with no args (introspection)
# ---------------------------------------------------------------------------

def test_handle_command_no_args_shows_introspection():
    """handle_command('medic', []) calls print_introspection and returns True."""
    medic = _import_medic()

    with patch.object(medic, "print_introspection") as mock_intro:
        result = medic.handle_command("medic", [])

    assert result is True
    mock_intro.assert_called_once()


# ---------------------------------------------------------------------------
# Tests -- handle_command routing / unknown commands
# ---------------------------------------------------------------------------

def test_handle_command_unknown_returns_false():
    """handle_command with an unknown subcommand returns False."""
    medic = _import_medic()
    result = medic.handle_command("explode", [])
    assert result is False


def test_handle_command_medic_routes_to_subcommand():
    """handle_command('medic', ['status']) recursively routes to status."""
    medic = _import_medic()
    state = _get_medic_state()

    with patch.object(medic, "_is_service_active", return_value=True):
        result = medic.handle_command("medic", ["status"])

    assert result is True
    state.is_enabled.assert_called_once()


def test_handle_command_medic_routes_mute_with_args():
    """handle_command('medic', ['mute', '@speakeasy']) routes correctly."""
    medic = _import_medic()
    result = medic.handle_command("medic", ["mute", "@speakeasy"])

    assert result is True
    state = _get_medic_state()
    state.mute_branch.assert_called_once_with("speakeasy")


# ---------------------------------------------------------------------------
# Tests -- _extract_branch_name helper
# ---------------------------------------------------------------------------

def test_extract_branch_name_strips_at():
    """_extract_branch_name removes leading @ and lowercases."""
    medic = _import_medic()
    assert medic._extract_branch_name("@Speakeasy") == "speakeasy"


def test_extract_branch_name_from_path():
    """_extract_branch_name extracts the last path component."""
    medic = _import_medic()
    assert medic._extract_branch_name("src/aipass/speakeasy") == "speakeasy"


def test_extract_branch_name_plain():
    """_extract_branch_name handles a plain name."""
    medic = _import_medic()
    assert medic._extract_branch_name("api") == "api"


# ---------------------------------------------------------------------------
# Contract gap tests
# ---------------------------------------------------------------------------

def test_handle_command_none_command_returns_false():
    """handle_command(None, []) returns False -- None is not a recognized command."""
    medic = _import_medic()
    from typing import Any
    none_cmd: Any = None
    result = medic.handle_command(none_cmd, [])
    assert result is False


def test_handle_command_case_sensitive_medic():
    """handle_command('MEDIC', []) returns False -- command routing is case-sensitive."""
    medic = _import_medic()
    result = medic.handle_command("MEDIC", [])
    assert result is False


def test_handle_command_on_extra_args_ignored():
    """handle_command('on', ['extra', 'args']) -- extra args are ignored, medic enables."""
    medic = _import_medic()

    with patch.object(medic, "_systemctl", return_value=True):
        with patch.object(medic, "_is_service_active", return_value=True):
            result = medic.handle_command("on", ["extra", "args"])

    assert result is True
    state = _get_medic_state()
    state.set_enabled.assert_called_with(True)
