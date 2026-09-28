# =================== AIPass ====================
# Name: test_status.py
# Description: Unit tests for PRAX status module
# Version: 1.1.0
# Created: 2026-03-24
# Modified: 2026-09-27
# =============================================

"""Tests for apps/modules/status.py and apps/handlers/status/sync.py."""

# Tests for prax status module command routing, help text, and introspection.
#
# All module imports happen inside test functions so that conftest's
# autouse mock_prax_infrastructure fixture injects sys.modules mocks first.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(error_handling) — sync_status's error on an absent or unreadable registry, covered by that row
# seedgo: no-test-needed(error_handling) — _handle_sync's error line when sync_status raises, covered by that row
# seedgo: no-test-needed(json_structure) — sync_status's status_sync_declined log_operation record, covered by that row
# seedgo: no-test-needed(log_level) — sync_status's info line counting what it scanned, covered by that row

import json
import sys
from unittest.mock import MagicMock

import pytest


# =============================================
# HELPERS
# =============================================


def _ensure_sync_mock(monkeypatch):
    """Inject a mock for the sync handler before importing status module."""
    mock_sync_mod = MagicMock()
    mock_sync_mod.sync_status = MagicMock(
        return_value={
            "status": "ok",
            "branches_synced": ["prax", "drone", "flow"],
            "branches_missing": [],
            "timestamp": "2026-03-24T12:00:00",
        }
    )
    monkeypatch.setitem(
        sys.modules,
        "aipass.prax.apps.handlers.status.sync",
        mock_sync_mod,
    )
    return mock_sync_mod


def _fresh_import():
    """Force re-import of the status module to pick up current sys.modules."""
    mod_name = "aipass.prax.apps.modules.status"
    sys.modules.pop(mod_name, None)
    from aipass.prax.apps.modules.status import (
        handle_command,
        print_help,
        print_introspection,
    )

    return handle_command, print_help, print_introspection


# =============================================
# TESTS
# =============================================


def test_handle_command_help(mock_prax_infrastructure, monkeypatch):
    """--help flag returns True and prints help text."""
    _ensure_sync_mock(monkeypatch)
    handle_command, _, _ = _fresh_import()

    result = handle_command("status", ["--help"])
    assert result is True
    mock_prax_infrastructure.console.print.assert_called()


def test_handle_command_help_h_flag(mock_prax_infrastructure, monkeypatch):
    """-h flag also triggers help."""
    _ensure_sync_mock(monkeypatch)
    handle_command, _, _ = _fresh_import()

    result = handle_command("status", ["-h"])
    assert result is True
    calls = [str(c) for c in mock_prax_infrastructure.console.print.call_args_list]
    assert any("status" in c.lower() for c in calls)


def test_handle_command_help_word(mock_prax_infrastructure, monkeypatch):
    """'help' subcommand triggers help."""
    _ensure_sync_mock(monkeypatch)
    handle_command, _, _ = _fresh_import()

    result = handle_command("status", ["help"])
    assert result is True
    calls = [str(c) for c in mock_prax_infrastructure.console.print.call_args_list]
    assert any("status" in c.lower() for c in calls)


def test_handle_command_no_args_shows_system_status(mock_prax_infrastructure, monkeypatch):
    """No args shows system status and returns True."""
    _ensure_sync_mock(monkeypatch)
    handle_command, _, _ = _fresh_import()

    result = handle_command("status", [])
    assert result is True
    # System status prints "PRAX System Status"
    calls = [str(c) for c in mock_prax_infrastructure.console.print.call_args_list]
    assert any("System Status" in c for c in calls)


def test_handle_command_unknown_sub_argument_is_refused(mock_prax_infrastructure, monkeypatch):
    """An unknown sub-argument is refused by name — the quietest swallow of the set.

    `status bogus` printed the normal status block with no complaint and exited
    0, so a typo'd subcommand was indistinguishable from the real thing
    (@devpulse's fleet CLI sweep, 2026-09-07).
    """
    from aipass.prax.apps.handlers.cli.arg_gate import UnknownArgument

    _ensure_sync_mock(monkeypatch)
    handle_command, _, _ = _fresh_import()

    with pytest.raises(UnknownArgument) as refusal:
        handle_command("status", ["bogus"])

    assert refusal.value.verb == "status"
    assert refusal.value.token == "bogus"
    calls = [str(c) for c in mock_prax_infrastructure.console.print.call_args_list]
    assert not any("System Status" in c for c in calls), "the refused command still ran"


def test_handle_command_wrong_command(mock_prax_infrastructure, monkeypatch):
    """Wrong command name returns False with no console side effects."""
    _ensure_sync_mock(monkeypatch)
    handle_command, _, _ = _fresh_import()

    result = handle_command("not-status", [])
    assert result is False
    mock_prax_infrastructure.console.print.assert_not_called()


def test_print_help_runs(mock_prax_infrastructure, monkeypatch):
    """print_help executes without error and includes sync subcommand."""
    _ensure_sync_mock(monkeypatch)
    _, print_help, _ = _fresh_import()

    print_help()
    mock_prax_infrastructure.console.print.assert_called()
    calls = [str(c) for c in mock_prax_infrastructure.console.print.call_args_list]
    assert any("sync" in c.lower() for c in calls)


def test_print_introspection_runs(mock_prax_infrastructure, monkeypatch):
    """print_introspection executes without error."""
    _ensure_sync_mock(monkeypatch)
    _, _, print_introspection = _fresh_import()

    print_introspection()
    calls = [str(c) for c in mock_prax_infrastructure.console.print.call_args_list]
    assert any("Connected Handlers" in c for c in calls)


def test_handle_command_sync_routes_to_handler(mock_prax_infrastructure, monkeypatch):
    """'sync' subcommand routes to sync_status handler and shows results."""
    mock_sync_mod = _ensure_sync_mock(monkeypatch)
    handle_command, _, _ = _fresh_import()

    result = handle_command("status", ["sync"])
    assert result is True
    mock_sync_mod.sync_status.assert_called_once()
    # Verify handler result influenced console output (synced branch count)
    calls = [str(c) for c in mock_prax_infrastructure.console.print.call_args_list]
    assert any("sync" in c.lower() for c in calls)


# =============================================
# The Last Scan line (DPLAN-0339 step 4)
# =============================================


def _format_last_scan():
    """The formatter, freshly imported like every other symbol in this file."""
    mod_name = "aipass.prax.apps.modules.status"
    sys.modules.pop(mod_name, None)
    from aipass.prax.apps.modules.status import _format_last_scan as fn

    return fn


def test_last_scan_never_run_says_how_to_run_it(mock_prax_infrastructure, monkeypatch):
    """An empty block is a real answer: this registry has never been scanned."""
    _ensure_sync_mock(monkeypatch)

    assert _format_last_scan()({}) == "never — run: drone @prax discover run"


def test_last_scan_shows_the_stamp_and_both_deltas(mock_prax_infrastructure, monkeypatch):
    """The line that replaced `File Watcher`, which reported the calling
    process and therefore read Inactive on every run while discovery was
    healthy."""
    _ensure_sync_mock(monkeypatch)

    line = _format_last_scan()({"timestamp": "2026-09-12T07:57:47+00:00", "added": 1245, "removed": 55})

    assert line == "2026-09-12T07:57:47+00:00 (+1245 / -55)"


def test_last_scan_survives_a_block_missing_its_counts(mock_prax_infrastructure, monkeypatch):
    """A registry written by an older prax has a timestamp and no deltas; the
    status command must still print a line rather than raise."""
    _ensure_sync_mock(monkeypatch)

    assert _format_last_scan()({"timestamp": "2026-09-12T07:57:47+00:00"}) == "2026-09-12T07:57:47+00:00 (+? / -?)"


# =============================================
# The decommissioned STATUS flow (@devpulse ruling 2026-09-15)
# =============================================


class TestSyncDoesNotResurrectTheRootFile:
    """TDPLAN-0007 decommissioned the STATUS flow and the fleet deleted the file.

    The trigger registration was unwired; the CLI subcommand was not, so
    `status sync` still walked every branch and wrote STATUS.md back to the repo
    root — the 2026-08-13 audit recreated it by running the command, and prax's
    own docs carried it as an open defect. @devpulse ruled on 2026-09-15: stop.
    The engine stays revivable (the scan, the registry read and the parse are
    untouched); what it must not do is write.
    """

    def _sync_module(self, monkeypatch, repo_root):
        import aipass.prax.apps.handlers.status.sync as sync

        monkeypatch.setattr(sync, "_find_repo_root", lambda: repo_root)
        monkeypatch.setattr(sync, "json_handler", MagicMock())
        return sync

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
