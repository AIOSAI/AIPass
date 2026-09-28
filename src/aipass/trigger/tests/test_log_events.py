# =================== META ====================
# Name: test_log_events.py
# Description: Unit tests for log_events module
# Version: 1.0.0
# Created: 2026-04-03
# Modified: 2026-09-27
# =============================================

"""Tests for the log_events module (apps/modules/log_events.py)."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(behaviour) — the watcher in apps/handlers/log_watcher.py that it drives; its own tests cover it

import pytest
from unittest.mock import MagicMock, call, patch

from aipass.cli.apps.modules import display
from aipass.trigger.apps.modules import log_events

# The mocks the autouse fixture set on the real module, read by the helpers below.
_MOCKS: dict = {}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _mock_infrastructure(monkeypatch, tmp_path):
    """Patch every name log_events reaches outside with, on the real module.

    The logger is patched because this module's log is read by the live branch
    watcher; the watcher functions are patched so no test starts a real
    filesystem observer.
    """
    mod = log_events
    mock_logger = MagicMock()
    monkeypatch.setattr(mod, "logger", mock_logger)

    # -- trigger json handler -----------------------------------------------
    mock_json_handler = MagicMock()
    mock_json_handler.log_operation = MagicMock(return_value=True)
    monkeypatch.setattr(mod, "json_handler", mock_json_handler)

    # -- watchers.log_watcher handler ---------------------------------------
    mock_log_watcher = MagicMock()
    mock_log_watcher.start_log_watcher = MagicMock(return_value=MagicMock())
    mock_log_watcher.stop_log_watcher = MagicMock()
    mock_log_watcher.is_log_watcher_active = MagicMock(return_value=False)
    for name in ("start_log_watcher", "stop_log_watcher", "is_log_watcher_active"):
        monkeypatch.setattr(mod, name, getattr(mock_log_watcher, name))
    log_dir = tmp_path / "system_logs"
    monkeypatch.setattr(mod, "SYSTEM_LOGS_DIR", log_dir)

    # The CLI console and rich are real: output is read with capsys, and a
    # refusal through error() is read from cli's own failure flag.
    _MOCKS.clear()
    _MOCKS.update(watcher=mock_log_watcher, json_handler=mock_json_handler, logger=mock_logger, log_dir=log_dir)


def _import_module():
    """Return the real log_events module the fixture patched."""
    return log_events


def _get_log_watcher():
    """Return the mock whose attributes stand in for the watcher functions."""
    return _MOCKS["watcher"]


def _get_json_handler():
    """Return the mocked json_handler."""
    return _MOCKS["json_handler"]


# ---------------------------------------------------------------------------
# Tests -- start()
# ---------------------------------------------------------------------------


def test_start_success_returns_true():
    """start() returns True when start_log_watcher returns an observer."""
    mod = _import_module()
    result = mod.start()
    assert result is True


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
    assert watcher.stop_log_watcher.call_args_list == [call()]


# ---------------------------------------------------------------------------
# Tests -- status()
# ---------------------------------------------------------------------------


def test_status_returns_dict_with_correct_shape():
    """status() returns dict with 'active' and 'log_dir' keys.

    Mutant run: status() reporting active as a constant False reddens this.
    """
    mod = _import_module()
    _get_log_watcher().is_log_watcher_active.return_value = True
    result = mod.status()
    assert result == {"active": True, "log_dir": str(mod.SYSTEM_LOGS_DIR)}


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
    assert result["log_dir"] == str(_MOCKS["log_dir"])


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


def test_handle_command_start_not_started_refuses_through_the_error_channel(capsys):
    """handle_command('start', []) refuses through error(), never warning().

    Rewritten TWICE, and the middle version is the lesson. On 2026-08-14 this
    asserted error() was NOT called, on the reasoning that a withdrawn observer
    is a decision rather than a fault. True, and beside the point: the channel
    is also the exit code. warning() leaves cli's failure flag unset, main()
    resolves to 0, and `start && <next>` proceeds with no watcher — so this
    test was not silent about the defect, it was agreeing with it. The cure is
    to rewrite the assertion, not to add a second one beside it.

    Read on the real channels since 2026-09-27: error() writes stderr and
    marks the command failed; warning() would write stderr and leave it unset.
    Mutant run: the refusal sent through warning() instead of error() reddens this.
    """
    mod = _import_module()
    watcher = _get_log_watcher()
    watcher.start_log_watcher.return_value = None
    result = mod.handle_command("start", [])
    assert result is True
    captured = capsys.readouterr()
    assert display.command_failed() is True
    assert "⚠" not in captured.err
    assert "one owner" in captured.err, f"the refusal must name the reason, got: {captured.err}"
    assert "branch_log_events" in captured.out + captured.err


def test_handle_command_stop():
    """handle_command('stop', []) stops watcher and returns True."""
    mod = _import_module()
    result = mod.handle_command("stop", [])
    assert result is True
    watcher = _get_log_watcher()
    watcher.stop_log_watcher.assert_called_once()


def test_handle_command_status(capsys):
    """handle_command('status', []) displays status and returns True."""
    mod = _import_module()
    result = mod.handle_command("status", [])
    assert result is True
    output = capsys.readouterr().out
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


def test_print_introspection_outputs_module_name(capsys):
    """print_introspection prints module name and handler info."""
    mod = _import_module()
    mod.print_introspection()
    output = capsys.readouterr().out
    assert "log_events Module" in output
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


def test_start_command_names_the_owner_and_says_it_is_a_ruling_not_a_failure(capsys):
    """`log_events start` declining is a ruling, and it still exits non-zero.

    start_log_watcher() always returns None because branch_log_events owns
    system_logs (the owner, 2026-08-14). Both halves of that are pinned here and
    they used to be treated as one: the wording must not read as a broken
    watcher ("Failed to start" sends the reader hunting a bug that is a
    decision), AND the refusal must travel on the channel that reaches the
    shell. Rewritten 2026-09-08 — the old version asserted the wording while
    the exit code said the watcher was running. Mutant run: the refusal sent
    through warning() instead of error() reddens this.
    """
    mod = _import_module()
    watcher = _get_log_watcher()
    watcher.start_log_watcher.return_value = None

    result = mod.handle_command("start", [])

    assert result is True
    captured = capsys.readouterr()
    assert display.command_failed() is True
    message = captured.err
    printed = captured.out + captured.err
    assert "branch_log_events" in printed, f"Expected the owner named, got: {printed[:300]}"
    assert "Failed to start" not in printed, "Declining by ruling must not read as a failure"
    assert "not failed" in message, f"the refusal must say which it is, got: {message}"


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

    logger = _MOCKS["logger"]
    logger.error.assert_not_called()
    assert logger.info.called
