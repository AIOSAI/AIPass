"""Tests for the log_events module (apps/modules/log_events.py)."""

# =================== META ====================
# Name: test_log_events.py
# Description: Unit tests for log_events module
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
    """Mock heavy infrastructure imports before log_events module loads."""

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

    # -- watchers.log_watcher handler ---------------------------------------
    mock_log_watcher = MagicMock()
    mock_log_watcher.start_log_watcher = MagicMock(return_value=MagicMock())
    mock_log_watcher.stop_log_watcher = MagicMock()
    mock_log_watcher.is_log_watcher_active = MagicMock(return_value=False)
    mock_log_watcher.SYSTEM_LOGS_DIR = "/fake/system_logs"
    monkeypatch.setitem(sys.modules, "aipass.trigger.apps.handlers.watchers", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.trigger.apps.handlers.watchers.log_watcher", mock_log_watcher)

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
    monkeypatch.delitem(sys.modules, "aipass.trigger.apps.modules.log_events", raising=False)


def _import_module():
    """Import log_events module fresh (after mocks are in place)."""
    import aipass.trigger.apps.modules.log_events as mod

    return mod


def _get_log_watcher():
    """Return the mocked watchers.log_watcher handler from sys.modules."""
    return sys.modules["aipass.trigger.apps.handlers.watchers.log_watcher"]


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
# Tests -- start()
# ---------------------------------------------------------------------------


def test_start_success_returns_true():
    """start() returns True when start_log_watcher returns an observer."""
    mod = _import_module()
    result = mod.start()
    assert result is True


def test_start_calls_start_log_watcher():
    """start() calls start_log_watcher handler."""
    mod = _import_module()
    mod.start()
    watcher = _get_log_watcher()
    watcher.start_log_watcher.assert_called_once()


def test_start_failure_returns_false():
    """start() returns False when start_log_watcher returns None."""
    mod = _import_module()
    watcher = _get_log_watcher()
    watcher.start_log_watcher.return_value = None
    result = mod.start()
    assert result is False


# ---------------------------------------------------------------------------
# Tests -- stop()
# ---------------------------------------------------------------------------


def test_stop_calls_stop_log_watcher():
    """stop() calls stop_log_watcher handler."""
    mod = _import_module()
    mod.stop()
    watcher = _get_log_watcher()
    watcher.stop_log_watcher.assert_called_once()


# ---------------------------------------------------------------------------
# Tests -- status()
# ---------------------------------------------------------------------------


def test_status_returns_dict_with_correct_shape():
    """status() returns dict with 'active' and 'log_dir' keys."""
    mod = _import_module()
    result = mod.status()
    assert isinstance(result, dict)
    assert "active" in result
    assert "log_dir" in result


def test_status_active_reflects_handler():
    """status() 'active' value comes from is_log_watcher_active."""
    mod = _import_module()
    watcher = _get_log_watcher()
    watcher.is_log_watcher_active.return_value = True
    result = mod.status()
    assert result["active"] is True


def test_status_log_dir_is_string():
    """status() 'log_dir' is a string representation of SYSTEM_LOGS_DIR."""
    mod = _import_module()
    result = mod.status()
    assert result["log_dir"] == "/fake/system_logs"


# ---------------------------------------------------------------------------
# Tests -- handle_command routing
# ---------------------------------------------------------------------------


def test_handle_command_start_success():
    """handle_command('start', []) starts watcher and returns True."""
    mod = _import_module()
    result = mod.handle_command("start", [])
    assert result is True
    watcher = _get_log_watcher()
    watcher.start_log_watcher.assert_called_once()


def test_handle_command_start_not_started_is_reported_without_the_error_channel():
    """handle_command('start', []) explains the ruling instead of erroring.

    Rewritten 2026-08-14. It previously asserted error("Failed to start log
    watcher"), which pinned the pre-ruling behaviour: with the centralized
    observer now withdrawn by decision, that assertion would have made the
    correct implementation look like a regression, and the error() channel
    would have kept telling operators a decision was a fault.
    """
    mod = _import_module()
    watcher = _get_log_watcher()
    watcher.start_log_watcher.return_value = None
    result = mod.handle_command("start", [])
    assert result is True
    cli_modules = sys.modules["aipass.cli.apps.modules"]
    cli_modules.error.assert_not_called()
    printed = " ".join(str(c) for c in _get_console().print.call_args_list) + " ".join(
        str(c) for c in cli_modules.warning.call_args_list
    )
    assert "one owner" in printed and "branch_log_events" in printed


def test_handle_command_stop():
    """handle_command('stop', []) stops watcher and returns True."""
    mod = _import_module()
    result = mod.handle_command("stop", [])
    assert result is True
    watcher = _get_log_watcher()
    watcher.stop_log_watcher.assert_called_once()


def test_handle_command_status():
    """handle_command('status', []) displays status and returns True."""
    mod = _import_module()
    result = mod.handle_command("status", [])
    assert result is True
    console = _get_console()
    printed = _get_print_str_args(console)
    output = "\n".join(printed)
    assert "Active:" in output
    assert "Log dir:" in output


def test_handle_command_logs_operation():
    """handle_command logs the operation via json_handler."""
    mod = _import_module()
    mod.handle_command("start", [])
    jh = _get_json_handler()
    jh.log_operation.assert_called_with("log_watcher_command", {"command": "start"})


def test_handle_command_unknown_returns_false():
    """handle_command with unrecognized command returns False."""
    mod = _import_module()
    result = mod.handle_command("explode", [])
    assert result is False


# ---------------------------------------------------------------------------
# Tests -- handle_command module-name routing
# ---------------------------------------------------------------------------


def test_handle_command_module_name_routes_to_subcommand():
    """handle_command('log_events', ['start']) recurses to start."""
    mod = _import_module()
    result = mod.handle_command("log_events", ["start"])
    assert result is True
    watcher = _get_log_watcher()
    watcher.start_log_watcher.assert_called_once()


def test_handle_command_module_name_no_args_shows_introspection():
    """handle_command('log_events', []) calls print_introspection."""
    mod = _import_module()
    with patch.object(mod, "print_introspection") as mock_intro:
        result = mod.handle_command("log_events", [])
    assert result is True
    mock_intro.assert_called_once()


def test_handle_command_module_name_help_flag():
    """handle_command('log_events', ['--help']) calls print_help."""
    mod = _import_module()
    with patch.object(mod, "print_help") as mock_help:
        result = mod.handle_command("log_events", ["--help"])
    assert result is True
    mock_help.assert_called_once()


def test_handle_command_module_name_h_flag():
    """handle_command('log_events', ['-h']) calls print_help."""
    mod = _import_module()
    with patch.object(mod, "print_help") as mock_help:
        result = mod.handle_command("log_events", ["-h"])
    assert result is True
    mock_help.assert_called_once()


def test_handle_command_module_name_help_word():
    """handle_command('log_events', ['help']) calls print_help."""
    mod = _import_module()
    with patch.object(mod, "print_help") as mock_help:
        result = mod.handle_command("log_events", ["help"])
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
    watcher.start_log_watcher.assert_not_called()


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
    assert "log_events Module" in output
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


# ---------------------------------------------------------------------------
# help_flag_safety canary — a help flag ANYWHERE explains, never executes
# ---------------------------------------------------------------------------


def test_help_flag_past_position_zero_does_not_run_the_verb(monkeypatch):
    """A flag one position later must not let the subcommand run.

    Read-only `status` is the probe; it is mocked, so a missing gate shows up
    as a call that should never have happened rather than as real work.
    """
    mod = _import_module()

    ran = MagicMock()
    monkeypatch.setattr(mod, "status", ran)
    printed = MagicMock()
    monkeypatch.setattr(mod, "print_help", printed)

    result = mod.handle_command("status", ["extra", "--help"])

    assert result is True
    printed.assert_called_once()
    ran.assert_not_called()


def test_help_flag_survives_module_name_routing(monkeypatch):
    """`log_events status extra -h` — flag survives the route hop."""
    mod = _import_module()

    ran = MagicMock()
    monkeypatch.setattr(mod, "status", ran)
    printed = MagicMock()
    monkeypatch.setattr(mod, "print_help", printed)

    result = mod.handle_command("log_events", ["status", "extra", "-h"])

    assert result is True
    printed.assert_called_once()
    ran.assert_not_called()


# ---------------------------------------------------------------------------
# system_logs ownership — the CLI must explain, not cry failure
# ---------------------------------------------------------------------------


def test_start_command_names_the_owner_instead_of_reporting_failure():
    """`log_events start` declining is a ruling, not a fault.

    start_log_watcher() now always returns None because branch_log_events owns
    system_logs (Patrick, 2026-08-14). Printing "Failed to start log watcher"
    would read as a broken watcher and send whoever typed it hunting a bug
    that is a decision.
    """
    mod = _import_module()
    watcher = _get_log_watcher()
    watcher.start_log_watcher.return_value = None

    result = mod.handle_command("start", [])

    assert result is True
    cli_modules = sys.modules["aipass.cli.apps.modules"]
    printed = " ".join(str(c) for c in cli_modules.error.call_args_list) + " ".join(
        str(c) for c in _get_console().print.call_args_list
    )
    assert "branch_log_events" in printed, f"Expected the owner named, got: {printed[:300]}"
    assert "Failed to start" not in printed, "Declining by ruling must not read as a failure"


def test_declining_to_start_is_not_logged_as_an_error():
    """A chosen behaviour must not enter my own error lane.

    This module's log is read by my branch watcher, which feeds error_detected
    and the escalation digest. Logging the by-ruling decline at ERROR would
    mint a signature for a decision on every service start and mail the
    operator about it (compass #273).
    """
    mod = _import_module()
    watcher = _get_log_watcher()
    watcher.start_log_watcher.return_value = None

    mod.start()

    logger = sys.modules["aipass.prax.apps.modules.logger"].system_logger
    logger.error.assert_not_called()
    assert logger.info.called
