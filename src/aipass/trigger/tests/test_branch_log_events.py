"""Tests for the branch_log_events module (apps/modules/branch_log_events.py)."""

# =================== META ====================
# Name: test_branch_log_events.py
# Description: Unit tests for branch_log_events module
# Version: 1.0.0
# Created: 2026-04-03
# Modified: 2026-04-03
# =============================================

import sys
import pytest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _mock_infrastructure(monkeypatch):
    """Mock heavy infrastructure imports before branch_log_events module loads."""

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

    # -- trigger core (trigger object with .fire method) --------------------
    mock_trigger = MagicMock()
    mock_trigger.fire = MagicMock()
    core_mod = MagicMock()
    core_mod.trigger = mock_trigger
    monkeypatch.setitem(sys.modules, "aipass.trigger.apps.modules.core", core_mod)

    # -- log_watcher handler ------------------------------------------------
    mock_log_watcher = MagicMock()
    mock_log_watcher.set_event_callback = MagicMock()
    mock_log_watcher.start_branch_log_watcher = MagicMock(return_value=MagicMock())
    mock_log_watcher.stop_branch_log_watcher = MagicMock()
    mock_log_watcher.is_branch_log_watcher_active = MagicMock(return_value=False)
    mock_log_watcher.get_watcher_status = MagicMock(
        return_value={
            "active": True,
            "watchdog_available": True,
            "seen_hashes_count": 0,
            "aipass_root": "/fake/path",
        }
    )
    mock_log_watcher.clear_seen_hashes = MagicMock()
    monkeypatch.setitem(sys.modules, "aipass.trigger.apps.handlers.log_watcher", mock_log_watcher)

    # -- trigger config -----------------------------------------------------
    from aipass.trigger.apps.config import atomic_write_json

    mock_config = MagicMock()
    mock_config.TRIGGER_ROOT = "/fake/trigger"
    mock_config.AIPASS_PKG_ROOT = "/fake/aipass"
    mock_config.atomic_write_json = atomic_write_json
    monkeypatch.setitem(sys.modules, "aipass.trigger.apps.config", mock_config)

    # -- CLI console --------------------------------------------------------
    mock_console = MagicMock()
    cli_modules = MagicMock()
    cli_modules.console = mock_console
    monkeypatch.setitem(sys.modules, "aipass.cli", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.cli.apps", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.cli.apps.modules", cli_modules)

    cli_display = MagicMock()
    cli_display.console = mock_console
    monkeypatch.setitem(sys.modules, "aipass.cli.apps.modules.display", cli_display)

    # -- rich (for print_help Panel) ----------------------------------------
    monkeypatch.setitem(sys.modules, "rich", MagicMock())
    monkeypatch.setitem(sys.modules, "rich.panel", MagicMock())
    monkeypatch.setitem(sys.modules, "rich.console", MagicMock())

    # -- Force re-import so mocks take effect -------------------------------
    monkeypatch.delitem(sys.modules, "aipass.trigger.apps.modules.branch_log_events", raising=False)


def _import_module():
    """Import branch_log_events module fresh (after mocks are in place)."""
    import aipass.trigger.apps.modules.branch_log_events as mod

    return mod


def _get_log_watcher():
    """Return the mocked log_watcher handler from sys.modules."""
    return sys.modules["aipass.trigger.apps.handlers.log_watcher"]


def _get_console():
    """Return the mocked console from sys.modules."""
    return sys.modules["aipass.cli.apps.modules"].console


def _get_json_handler():
    """Return the mocked json_handler from sys.modules."""
    return sys.modules["aipass.trigger.apps.handlers.json.json_handler"]


def _get_core_trigger():
    """Return the mocked trigger object from sys.modules."""
    return sys.modules["aipass.trigger.apps.modules.core"].trigger


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
# Tests -- start()
# ---------------------------------------------------------------------------


def test_start_success_returns_true():
    """start() returns True when start_branch_log_watcher returns an observer."""
    mod = _import_module()
    result = mod.start()
    assert result is True


def test_start_sets_event_callback():
    """start() calls set_event_callback with trigger.fire."""
    mod = _import_module()
    mod.start()
    watcher = _get_log_watcher()
    trigger = _get_core_trigger()
    watcher.set_event_callback.assert_called_once_with(trigger.fire)


def test_start_calls_start_branch_log_watcher():
    """start() calls start_branch_log_watcher."""
    mod = _import_module()
    mod.start()
    watcher = _get_log_watcher()
    watcher.start_branch_log_watcher.assert_called_once()


def test_start_failure_returns_false():
    """start() returns False when start_branch_log_watcher returns None."""
    mod = _import_module()
    watcher = _get_log_watcher()
    watcher.start_branch_log_watcher.return_value = None
    result = mod.start()
    assert result is False


# ---------------------------------------------------------------------------
# Tests -- stop()
# ---------------------------------------------------------------------------


def test_stop_calls_stop_branch_log_watcher():
    """stop() calls stop_branch_log_watcher."""
    mod = _import_module()
    mod.stop()
    watcher = _get_log_watcher()
    watcher.stop_branch_log_watcher.assert_called_once()


# ---------------------------------------------------------------------------
# Tests -- status()
# ---------------------------------------------------------------------------


def test_status_returns_dict_from_handler():
    """status() returns the dict from get_watcher_status."""
    mod = _import_module()
    result = mod.status()
    assert isinstance(result, dict)
    assert result["active"] is True
    assert result["watchdog_available"] is True
    assert result["seen_hashes_count"] == 0
    assert result["aipass_root"] == "/fake/path"


def test_status_calls_get_watcher_status():
    """status() delegates to get_watcher_status handler."""
    mod = _import_module()
    mod.status()
    watcher = _get_log_watcher()
    watcher.get_watcher_status.assert_called_once()


# ---------------------------------------------------------------------------
# Tests -- reset_hashes()
# ---------------------------------------------------------------------------


def test_reset_hashes_calls_clear_seen_hashes():
    """reset_hashes() calls clear_seen_hashes."""
    mod = _import_module()
    mod.reset_hashes()
    watcher = _get_log_watcher()
    watcher.clear_seen_hashes.assert_called_once()


# ---------------------------------------------------------------------------
# Tests -- handle_command routing
# ---------------------------------------------------------------------------


def test_handle_command_start_success():
    """handle_command('start', []) starts watcher and returns True."""
    mod = _import_module()
    result = mod.handle_command("start", [])
    assert result is True
    watcher = _get_log_watcher()
    watcher.start_branch_log_watcher.assert_called_once()


def test_handle_command_start_failure_prints_error():
    """handle_command('start', []) prints failure when watcher fails to start."""
    mod = _import_module()
    watcher = _get_log_watcher()
    watcher.start_branch_log_watcher.return_value = None
    result = mod.handle_command("start", [])
    assert result is True
    console = _get_console()
    printed = _get_print_str_args(console)
    assert any("Failed to start" in s for s in printed), f"Expected failure message in printed args: {printed}"


def test_handle_command_stop():
    """handle_command('stop', []) stops watcher and returns True."""
    mod = _import_module()
    result = mod.handle_command("stop", [])
    assert result is True
    watcher = _get_log_watcher()
    watcher.stop_branch_log_watcher.assert_called_once()


def test_handle_command_status():
    """handle_command('status', []) displays status and returns True."""
    mod = _import_module()
    result = mod.handle_command("status", [])
    assert result is True
    watcher = _get_log_watcher()
    watcher.get_watcher_status.assert_called_once()


def test_handle_command_reset():
    """handle_command('reset', []) clears hashes and returns True."""
    mod = _import_module()
    result = mod.handle_command("reset", [])
    assert result is True
    watcher = _get_log_watcher()
    watcher.clear_seen_hashes.assert_called_once()


def test_handle_command_logs_operation():
    """handle_command logs the operation via json_handler."""
    mod = _import_module()
    mod.handle_command("start", [])
    jh = _get_json_handler()
    jh.log_operation.assert_called_with("watcher_command", {"command": "start"})


def test_handle_command_unknown_returns_false():
    """handle_command with unrecognized command returns False."""
    mod = _import_module()
    result = mod.handle_command("explode", [])
    assert result is False


# ---------------------------------------------------------------------------
# Tests -- handle_command module-name routing
# ---------------------------------------------------------------------------


def test_handle_command_module_name_routes_to_subcommand():
    """handle_command('branch_log_events', ['start']) recurses to start."""
    mod = _import_module()
    result = mod.handle_command("branch_log_events", ["start"])
    assert result is True
    watcher = _get_log_watcher()
    watcher.start_branch_log_watcher.assert_called_once()


def test_handle_command_module_name_no_args_shows_introspection():
    """handle_command('branch_log_events', []) calls print_introspection."""
    mod = _import_module()
    with patch.object(mod, "print_introspection") as mock_intro:
        result = mod.handle_command("branch_log_events", [])
    assert result is True
    mock_intro.assert_called_once()


def test_handle_command_module_name_help_flag():
    """handle_command('branch_log_events', ['--help']) calls print_help."""
    mod = _import_module()
    with patch.object(mod, "print_help") as mock_help:
        result = mod.handle_command("branch_log_events", ["--help"])
    assert result is True
    mock_help.assert_called_once()


def test_handle_command_module_name_h_flag():
    """handle_command('branch_log_events', ['-h']) calls print_help."""
    mod = _import_module()
    with patch.object(mod, "print_help") as mock_help:
        result = mod.handle_command("branch_log_events", ["-h"])
    assert result is True
    mock_help.assert_called_once()


def test_handle_command_module_name_help_word():
    """handle_command('branch_log_events', ['help']) calls print_help."""
    mod = _import_module()
    with patch.object(mod, "print_help") as mock_help:
        result = mod.handle_command("branch_log_events", ["help"])
    assert result is True
    mock_help.assert_called_once()


# ---------------------------------------------------------------------------
# Tests -- handle_command help flags on direct subcommands
# ---------------------------------------------------------------------------


def test_handle_command_subcommand_help_flag():
    """handle_command('start', ['--help']) shows help instead of starting."""
    mod = _import_module()
    with patch.object(mod, "print_help") as mock_help:
        result = mod.handle_command("start", ["--help"])
    assert result is True
    mock_help.assert_called_once()
    watcher = _get_log_watcher()
    watcher.start_branch_log_watcher.assert_not_called()


def test_handle_command_direct_help_flag():
    """handle_command('--help', []) shows help and returns True."""
    mod = _import_module()
    with patch.object(mod, "print_help") as mock_help:
        result = mod.handle_command("--help", [])
    assert result is True
    mock_help.assert_called_once()


def test_handle_command_direct_h_flag():
    """handle_command('-h', []) shows help and returns True."""
    mod = _import_module()
    with patch.object(mod, "print_help") as mock_help:
        result = mod.handle_command("-h", [])
    assert result is True
    mock_help.assert_called_once()


def test_handle_command_direct_help_word():
    """handle_command('help', []) shows help and returns True."""
    mod = _import_module()
    with patch.object(mod, "print_help") as mock_help:
        result = mod.handle_command("help", [])
    assert result is True
    mock_help.assert_called_once()


# ---------------------------------------------------------------------------
# Tests -- print_introspection output
# ---------------------------------------------------------------------------


def test_print_introspection_outputs_module_name():
    """print_introspection prints module name and handler info."""
    mod = _import_module()
    mod.print_introspection()
    console = _get_console()
    printed = _get_print_str_args(console)
    output = "\n".join(printed)
    assert "branch_log_events Module" in output
    assert "Connected Handlers:" in output
    assert "log_watcher.py" in output


# ---------------------------------------------------------------------------
# Tests -- print_help output
# ---------------------------------------------------------------------------


def test_print_help_outputs_commands():
    """print_help prints command reference."""
    mod = _import_module()
    mod.print_help()
    console = _get_console()
    printed = _get_print_str_args(console)
    output = "\n".join(printed)
    assert "start" in output
    assert "stop" in output
    assert "status" in output
    assert "reset" in output


# ---------------------------------------------------------------------------
# Tests -- handle_command status output content
# ---------------------------------------------------------------------------


def test_handle_command_status_prints_all_fields():
    """handle_command('status', []) prints active, watchdog, hashes, root."""
    mod = _import_module()
    mod.handle_command("status", [])
    console = _get_console()
    printed = _get_print_str_args(console)
    output = "\n".join(printed)
    assert "Active:" in output
    assert "Watchdog available:" in output
    assert "Seen error hashes:" in output
    assert "AIPASS root:" in output
