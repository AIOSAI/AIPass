# =================== META ====================
# Name: test_branch_log_events.py
# Description: Unit tests for branch_log_events module
# Version: 1.0.0
# Created: 2026-04-03
# Modified: 2026-09-27
# =============================================

"""Tests for the branch_log_events module (apps/modules/branch_log_events.py)."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(behaviour) — the watcher in apps/handlers/log_watcher.py that it starts; its own tests cover it

import sys
import pytest
from unittest.mock import MagicMock, call, patch

from aipass.cli.apps.modules import display


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

    # The CLI console and rich are real: output is read with capsys, and a
    # refusal through error() is read from cli's own failure flag.

    # -- Force re-import so mocks take effect -------------------------------
    monkeypatch.delitem(sys.modules, "aipass.trigger.apps.modules.branch_log_events", raising=False)


def _import_module():
    """Import branch_log_events module fresh (after mocks are in place)."""
    import aipass.trigger.apps.modules.branch_log_events as mod

    return mod


def _get_log_watcher():
    """Return the mocked log_watcher handler from sys.modules."""
    return sys.modules["aipass.trigger.apps.handlers.log_watcher"]


def _get_json_handler():
    """Return the mocked json_handler from sys.modules."""
    return sys.modules["aipass.trigger.apps.handlers.json.json_handler"]


def _get_core_trigger():
    """Return the mocked trigger object from sys.modules."""
    return sys.modules["aipass.trigger.apps.modules.core"].trigger


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
    assert watcher.stop_branch_log_watcher.call_args_list == [call()]


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


# ---------------------------------------------------------------------------
# Tests -- reset_hashes()
# ---------------------------------------------------------------------------


def test_reset_hashes_calls_clear_seen_hashes():
    """reset_hashes() calls clear_seen_hashes."""
    mod = _import_module()
    mod.reset_hashes()
    watcher = _get_log_watcher()
    assert watcher.clear_seen_hashes.call_args_list == [call()]


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


def test_handle_command_start_failure_prints_error(capsys):
    """A watcher that fails to start is reported through error(), which fails the command.

    Mutant run: the failure sent through warning() instead of error() reddens this.
    """
    mod = _import_module()
    watcher = _get_log_watcher()
    watcher.start_branch_log_watcher.return_value = None
    result = mod.handle_command("start", [])
    assert result is True
    err = capsys.readouterr().err
    assert display.command_failed() is True
    assert "Failed to start" in err, f"Expected failure message on stderr: {err}"


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


def test_print_introspection_outputs_module_name(capsys):
    """print_introspection prints module name and handler info."""
    mod = _import_module()
    mod.print_introspection()
    output = capsys.readouterr().out
    assert "branch_log_events Module" in output
    assert "Connected Handlers:" in output
    assert "log_watcher.py" in output


# ---------------------------------------------------------------------------
# Tests -- print_help output
# ---------------------------------------------------------------------------


def test_print_help_outputs_commands(capsys):
    """print_help prints command reference."""
    mod = _import_module()
    mod.print_help()
    output = capsys.readouterr().out
    assert "start" in output
    assert "stop" in output
    assert "status" in output
    assert "reset" in output


# ---------------------------------------------------------------------------
# Tests -- handle_command status output content
# ---------------------------------------------------------------------------


def test_handle_command_status_prints_all_fields(capsys):
    """handle_command('status', []) prints active, watchdog, hashes, root."""
    mod = _import_module()
    mod.handle_command("status", [])
    output = capsys.readouterr().out
    assert "Active:" in output
    assert "Watchdog available:" in output
    assert "Seen error hashes:" in output
    assert "AIPASS root:" in output


# ---------------------------------------------------------------------------
# help_flag_safety canary — a help flag ANYWHERE explains, never executes
# ---------------------------------------------------------------------------


def test_help_flag_past_position_zero_does_not_run_the_verb(monkeypatch):
    """A flag one position later must not let the subcommand run.

    Probed with the read-only `status` verb deliberately: if the gate is
    missing, the canary reads state instead of starting or resetting a
    watcher. status() is mocked, so the assertion is that it is never reached.
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
    """`branch_log_events status extra -h` — flag survives the route hop."""
    mod = _import_module()

    ran = MagicMock()
    monkeypatch.setattr(mod, "status", ran)
    printed = MagicMock()
    monkeypatch.setattr(mod, "print_help", printed)

    result = mod.handle_command("branch_log_events", ["status", "extra", "-h"])

    assert result is True
    printed.assert_called_once()
    ran.assert_not_called()
