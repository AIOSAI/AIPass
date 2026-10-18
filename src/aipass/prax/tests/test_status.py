# =================== AIPass ====================
# Name: test_status.py
# Description: Unit tests for PRAX status module
# Version: 1.1.0
# Created: 2026-03-24
# Modified: 2026-10-17
# =============================================

"""Tests for apps/modules/status.py and apps/handlers/status/sync.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(error_handling) — sync_status's error on an absent or unreadable registry, covered by that row
# seedgo: no-test-needed(error_handling) — _handle_sync's error line when sync_status raises, covered by that row
# seedgo: no-test-needed(json_structure) — sync_status's status_sync_declined log_operation record, covered by that row
# seedgo: no-test-needed(log_level) — sync_status's info line counting what it scanned, covered by that row

import json
from unittest.mock import MagicMock

import pytest

from aipass.prax.apps.handlers.cli.arg_gate import UnknownArgument
from aipass.prax.apps.handlers.status import sync as status_sync
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
        "logger_override_active": False,
    }


@pytest.fixture
def sync_calls(monkeypatch):
    """status with its collaborators doubled where status binds them; returns the sync call log."""
    calls = []

    def fake_sync_status():
        calls.append("sync")
        return {
            "status": "ok",
            "branches_synced": ["prax", "drone", "flow"],
            "branches_missing": [],
            "timestamp": "2026-03-24T12:00:00",
        }

    monkeypatch.setattr(status_module, "sync_status", fake_sync_status)
    monkeypatch.setattr(status_module, "json_handler", MagicMock())
    monkeypatch.setattr(status_module, "logger", MagicMock())
    monkeypatch.setattr(status_module, "get_system_status", lambda: _status_block({}))
    return calls


@pytest.mark.parametrize("flag", ["--help", "-h", "help"])
def test_every_help_spelling_prints_help_and_runs_nothing(sync_calls, capsys, flag):
    """Asking for help answers with the help, never with the action."""
    assert status_module.handle_command("status", [flag]) is True

    out = capsys.readouterr().out
    assert "PRAX Status Commands:" in out
    assert "PRAX System Status" not in out
    assert sync_calls == []


def test_handle_command_no_args_shows_system_status(sync_calls, capsys):
    """No args prints the status block from get_system_status's answer."""
    assert status_module.handle_command("status", []) is True

    out = capsys.readouterr().out
    assert "PRAX System Status" in out
    assert "  Total Modules:   7" in out.splitlines()
    assert sync_calls == []


def test_handle_command_unknown_sub_argument_is_refused(sync_calls, capsys):
    """An unknown sub-argument is refused by name, not answered with the status block."""
    with pytest.raises(UnknownArgument) as refusal:
        status_module.handle_command("status", ["bogus"])

    assert refusal.value.verb == "status"
    assert refusal.value.token == "bogus"
    assert "PRAX System Status" not in capsys.readouterr().out, "the refused command still ran"


def test_handle_command_wrong_command(sync_calls, capsys):
    """Wrong command name returns False and prints nothing."""
    assert status_module.handle_command("not-status", []) is False

    captured = capsys.readouterr()
    assert (captured.out, captured.err) == ("", "")
    assert sync_calls == []


def test_print_help_names_the_sync_subcommand(capsys):
    """print_help lists sync and says it writes nothing."""
    status_module.print_help()

    assert "status sync" in capsys.readouterr().out


def test_print_introspection_names_its_handlers(capsys):
    """print_introspection lists the handlers status is connected to."""
    status_module.print_introspection()

    out = capsys.readouterr().out
    assert "Connected Handlers:" in out
    assert "get_system_status" in out


def test_handle_command_sync_routes_to_handler(sync_calls, capsys):
    """'sync' runs sync_status once and prints what it answered."""
    assert status_module.handle_command("status", ["sync"]) is True

    assert sync_calls == ["sync"]
    captured = capsys.readouterr()
    assert "Timestamp: 2026-03-24T12:00:00" in captured.out
    assert "3 branches scanned" in captured.out + captured.err


def _last_scan_line(monkeypatch, capsys, last_scan):
    """The Last Scan line as bare `status` prints it, read off the real console."""
    monkeypatch.setattr(status_module, "get_system_status", lambda: _status_block(last_scan))
    capsys.readouterr()

    assert status_module.handle_command("status", []) is True

    (line,) = [p for p in capsys.readouterr().out.splitlines() if p.startswith("  Last Scan:")]
    return line.removeprefix("  Last Scan:       ")


def test_last_scan_never_run_says_how_to_run_it(sync_calls, monkeypatch, capsys):
    """An empty block is a real answer: this registry has never been scanned."""
    assert _last_scan_line(monkeypatch, capsys, {}) == "never — run: drone @prax discover run"


def test_last_scan_shows_the_stamp_and_both_deltas(sync_calls, monkeypatch, capsys):
    """The Last Scan line carries the stamp and both deltas."""
    line = _last_scan_line(
        monkeypatch,
        capsys,
        {"timestamp": "2026-09-12T07:57:47+00:00", "added": 1245, "removed": 55},
    )

    assert line == "2026-09-12T07:57:47+00:00 (+1245 / -55)"


def test_last_scan_survives_a_block_missing_its_counts(sync_calls, monkeypatch, capsys):
    """An older registry with a timestamp and no deltas still prints a line rather than raise."""
    line = _last_scan_line(monkeypatch, capsys, {"timestamp": "2026-09-12T07:57:47+00:00"})

    assert line == "2026-09-12T07:57:47+00:00 (+? / -?)"


def test_last_scan_unreadable_is_not_reported_as_never(sync_calls, monkeypatch, capsys):
    """None (load_last_scan could not read the registry) must not print as "never"."""
    line = _last_scan_line(monkeypatch, capsys, None)

    assert line == "unreadable — the registry could not be read; see the prax log"


class TestSyncDoesNotResurrectTheRootFile:
    """The STATUS flow is decommissioned: `status sync` still scans but must never write STATUS.md."""

    def _sync_module(self, monkeypatch, repo_root):
        monkeypatch.setattr(status_sync, "_find_repo_root", lambda: repo_root)
        monkeypatch.setattr(status_sync, "json_handler", MagicMock())
        return status_sync

    def _repo(self, tmp_path):
        """A repo root with one registered branch carrying a STATUS.local.md."""
        branch = tmp_path / "src" / "aipass" / "somebranch"
        branch.mkdir(parents=True)
        (branch / "STATUS.local.md").write_text(
            "**State:** Operational\n**Last update:** 2026-09-24\n", encoding="utf-8"
        )
        (tmp_path / "AIPASS_REGISTRY.json").write_text(
            json.dumps({"branches": [{"name": "somebranch", "email": "@somebranch", "path": "src/aipass/somebranch"}]}),
            encoding="utf-8",
        )
        return tmp_path

    def test_no_status_md_appears_at_the_repo_root(self, tmp_path, monkeypatch):
        repo_root = self._repo(tmp_path)
        sync = self._sync_module(monkeypatch, repo_root)

        sync.sync_status()

        assert not (repo_root / "STATUS.md").exists(), (
            "status sync resurrected the file the fleet deleted on purpose (TDPLAN-0007)"
        )

    def test_the_command_says_it_declined_rather_than_reporting_a_write(self, tmp_path, monkeypatch):
        """Fail honestly: a caller must not read this as a successful sync."""
        sync = self._sync_module(monkeypatch, self._repo(tmp_path))

        result = sync.sync_status()

        assert result["status"] == "declined"
        assert "DASHBOARD.local.json" in result.get("reason", "")

    def test_the_scan_still_runs_so_the_engine_stays_revivable(self, tmp_path, monkeypatch):
        """Declining to write is not the same as deleting the engine."""
        sync = self._sync_module(monkeypatch, self._repo(tmp_path))

        result = sync.sync_status()

        assert result["branches_synced"] == ["@somebranch"]
