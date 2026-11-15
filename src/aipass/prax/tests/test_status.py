# =================== AIPass ====================
# Name: test_status.py
# Description: Unit tests for PRAX status module
# Version: 1.2.0
# Created: 2026-03-24
# Modified: 2026-11-14
# =============================================

"""Tests for apps/modules/status.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# sentry: no-test-needed(cli) — the __main__ block's direct-run help, covered by that row

from unittest.mock import MagicMock

import pytest

from aipass.prax.apps.handlers.cli.arg_gate import UnknownArgument
from aipass.prax.apps.modules import status as status_module


def _status_block(last_scan):
    """What get_system_status answers, with the Last Scan block the test names."""
    return {
        "total_modules": 7,
        "individual_loggers": 0,
        "system_logs_dir": "system",
        "module_logs_dir": "module",
        "registry_file": "registry",
        "last_scan": last_scan,
    }


@pytest.fixture
def status_world(monkeypatch):
    """status with its collaborators doubled where status binds them."""
    monkeypatch.setattr(status_module, "json_handler", MagicMock())
    monkeypatch.setattr(status_module, "get_system_status", lambda: _status_block({}))


@pytest.mark.parametrize("flag", ["--help", "-h", "help"])
def test_every_help_spelling_prints_help_and_runs_nothing(status_world, capsys, flag):
    """Asking for help answers with the help, never with the action."""
    assert status_module.handle_command("status", [flag]) is True

    out = capsys.readouterr().out
    assert "PRAX Status Commands:" in out
    assert "PRAX System Status" not in out


def test_handle_command_no_args_shows_system_status(status_world, capsys):
    """No args prints the status block from get_system_status's answer."""
    assert status_module.handle_command("status", []) is True

    out = capsys.readouterr().out
    assert "PRAX System Status" in out
    assert "  Total Modules:   7" in out.splitlines()


def test_handle_command_unknown_sub_argument_is_refused(status_world, capsys):
    """An unknown sub-argument is refused by name, not answered with the status block."""
    with pytest.raises(UnknownArgument) as refusal:
        status_module.handle_command("status", ["bogus"])

    assert refusal.value.verb == "status"
    assert refusal.value.token == "bogus"
    assert "PRAX System Status" not in capsys.readouterr().out, "the refused command still ran"


def test_handle_command_wrong_command(status_world, capsys):
    """Wrong command name returns False and prints nothing."""
    assert status_module.handle_command("not-status", []) is False

    captured = capsys.readouterr()
    assert (captured.out, captured.err) == ("", "")


def test_print_introspection_names_its_handlers(capsys):
    """print_introspection lists the handlers status is connected to."""
    status_module.print_introspection()

    out = capsys.readouterr().out
    assert "Connected Handlers:" in out
    assert "get_system_status" in out


def test_the_retired_sync_verb_is_refused_by_name(status_world, capsys):
    """STATUS.local.md is retired: `status sync` is an unknown argument, not a scan."""
    with pytest.raises(UnknownArgument) as refusal:
        status_module.handle_command("status", ["sync"])

    assert refusal.value.token == "sync"
    assert "Syncing" not in capsys.readouterr().out


def _last_scan_line(monkeypatch, capsys, last_scan):
    """The Last Scan line as bare `status` prints it, read off the real console."""
    monkeypatch.setattr(status_module, "get_system_status", lambda: _status_block(last_scan))
    capsys.readouterr()

    assert status_module.handle_command("status", []) is True

    (line,) = [p for p in capsys.readouterr().out.splitlines() if p.startswith("  Last Scan:")]
    return line.removeprefix("  Last Scan:       ")


def test_last_scan_never_run_says_how_to_run_it(status_world, monkeypatch, capsys):
    """An empty block is a real answer: this registry has never been scanned."""
    assert _last_scan_line(monkeypatch, capsys, {}) == "never — run: drone @prax discover run"


def test_last_scan_shows_the_stamp_and_both_deltas(status_world, monkeypatch, capsys):
    """The Last Scan line carries the stamp and both deltas."""
    line = _last_scan_line(
        monkeypatch,
        capsys,
        {"timestamp": "2026-09-12T07:57:47+00:00", "added": 1245, "removed": 55},
    )

    assert line == "2026-09-12T07:57:47+00:00 (+1245 / -55)"


def test_last_scan_survives_a_block_missing_its_counts(status_world, monkeypatch, capsys):
    """An older registry with a timestamp and no deltas still prints a line rather than raise."""
    line = _last_scan_line(monkeypatch, capsys, {"timestamp": "2026-09-12T07:57:47+00:00"})

    assert line == "2026-09-12T07:57:47+00:00 (+? / -?)"


def test_last_scan_unreadable_is_not_reported_as_never(status_world, monkeypatch, capsys):
    """None (load_last_scan could not read the registry) must not print as "never"."""
    line = _last_scan_line(monkeypatch, capsys, None)

    assert line == "unreadable — the registry could not be read; see the prax log"
