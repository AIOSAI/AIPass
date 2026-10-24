# =================== AIPass ====================
# Name: test_sweep.py
# Description: Tests for stale log sweep in log_audit
# Version: 1.4.0
# Created: 2026-07-10
# Modified: 2026-10-23
# =============================================

"""Tests for apps/handlers/logging/log_watchdog.py's sweep_stale_logs and apps/modules/log_audit.py's sweep route."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(error_handling) — _file_age_days answering 0.0 when the stat fails, covered by that row
# seedgo: no-test-needed(error_handling) — _sweep_directory's warning when an unlink fails, covered by that row
# seedgo: no-test-needed(json_structure) — sweep_stale_logs' log_sweep log_operation record, covered by that row

import os
import sys
import time
from pathlib import Path
from types import ModuleType
from unittest.mock import patch, MagicMock

import pytest

from aipass.prax.apps.handlers.logging import log_watchdog as lw
from aipass.prax.apps.modules import log_audit


def _make_old_file(path: Path, age_days: int) -> None:
    """Create a file and backdate its mtime."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("stale log content\n", encoding="utf-8")
    old_time = time.time() - (age_days * 86400)
    os.utime(path, (old_time, old_time))


def _stub_sweep(monkeypatch):
    """Replace the watchdog's sweep on the real module; _run_sweep imports it from there at call time."""
    sweep = MagicMock(
        return_value={
            "max_age_days": 30,
            "files_removed": 1,
            "total_reclaimed_kb": 12.5,
            "removed": [
                {"path": "/fake/logs/old.log", "name": "old.log", "age_days": 45.2, "size_kb": 12.5},
            ],
        }
    )
    monkeypatch.setattr(lw, "sweep_stale_logs", sweep)
    _stood_where_log_audit_looks(lw)
    return sweep


def _stood_where_log_audit_looks(module, modules=sys.modules):
    """Fail before the route runs when the stubbed module is not the one log_audit will find.

    _run_sweep resolves the watchdog through sys.modules; an orphaned stub sends it to the real one, which deletes live logs.
    """
    if modules.get(module.__name__) is not module:
        pytest.fail(f"{module.__name__} in sys.modules is not the module the stub stands on")


def test_the_guard_fails_when_sys_modules_holds_another_watchdog():
    """A different object under the watchdog's name stops the test before the route (test side only)."""
    name = lw.__name__
    with pytest.raises(pytest.fail.Exception, match="not the module the stub stands on"):
        _stood_where_log_audit_looks(lw, {name: ModuleType(name)})
    with pytest.raises(pytest.fail.Exception, match="not the module the stub stands on"):
        _stood_where_log_audit_looks(lw, {})
    _stood_where_log_audit_looks(lw, {name: lw})


class TestSweepIntegration:
    """Integration: sweep across system_logs and branch logs."""

    def test_deletes_old_system_log(self, tmp_path):
        """Verify sweep deletes old files from system_logs/."""
        sys_logs = tmp_path / "system_logs"
        sys_logs.mkdir()
        _make_old_file(sys_logs / "old_module.log", 45)

        with (
            patch.object(lw, "_get_system_logs_dir", return_value=sys_logs),
            patch.object(lw, "_get_ecosystem_root", return_value=tmp_path / "src" / "aipass"),
            patch.object(lw, "json_handler", MagicMock()),
        ):
            result = lw.sweep_stale_logs()

        assert result["files_removed"] == 1
        assert not (sys_logs / "old_module.log").exists()

    def test_deletes_old_branch_jsonl(self, tmp_path):
        """Verify sweep deletes old .jsonl files from branch logs/."""
        eco = tmp_path / "src" / "aipass"
        branch_logs = eco / "testbranch" / "logs"
        branch_logs.mkdir(parents=True)
        _make_old_file(branch_logs / "ops.jsonl", 35)

        with (
            patch.object(lw, "_get_system_logs_dir", return_value=tmp_path / "system_logs"),
            patch.object(lw, "_get_ecosystem_root", return_value=eco),
            patch.object(lw, "json_handler", MagicMock()),
        ):
            result = lw.sweep_stale_logs()

        assert result["files_removed"] == 1
        assert not (branch_logs / "ops.jsonl").exists()

    def test_keeps_fresh_files(self, tmp_path):
        """Verify sweep leaves files younger than 30 days untouched."""
        sys_logs = tmp_path / "system_logs"
        sys_logs.mkdir()
        fresh = sys_logs / "recent.log"
        fresh.write_text("fresh content\n", encoding="utf-8")

        with (
            patch.object(lw, "_get_system_logs_dir", return_value=sys_logs),
            patch.object(lw, "_get_ecosystem_root", return_value=tmp_path / "src" / "aipass"),
            patch.object(lw, "json_handler", MagicMock()),
        ):
            result = lw.sweep_stale_logs()

        assert result["files_removed"] == 0
        assert fresh.exists()

    def test_deletes_rotation_siblings(self, tmp_path):
        """Verify sweep also removes stale .log.1 rotation backups."""
        sys_logs = tmp_path / "system_logs"
        sys_logs.mkdir()
        _make_old_file(sys_logs / "module.log", 40)
        _make_old_file(sys_logs / "module.log.1", 40)

        with (
            patch.object(lw, "_get_system_logs_dir", return_value=sys_logs),
            patch.object(lw, "_get_ecosystem_root", return_value=tmp_path / "src" / "aipass"),
            patch.object(lw, "json_handler", MagicMock()),
        ):
            result = lw.sweep_stale_logs()

        assert result["files_removed"] == 2
        assert not (sys_logs / "module.log").exists()
        assert not (sys_logs / "module.log.1").exists()

    def test_deletes_every_numbered_backup(self, tmp_path):
        """backup_count is 3, so .log.2/.log.3 and branch .jsonl.3 are swept too."""
        sys_logs = tmp_path / "system_logs"
        logs = tmp_path / "src" / "aipass" / "hooks" / "logs"
        for path in (sys_logs / "m.log.2", sys_logs / "m.log.3", logs / "e.jsonl.3", logs / "e.log.2"):
            _make_old_file(path, 40)

        with (
            patch.object(lw, "_get_system_logs_dir", return_value=sys_logs),
            patch.object(lw, "_get_ecosystem_root", return_value=tmp_path / "src" / "aipass"),
            patch.object(lw, "json_handler", MagicMock()),
        ):
            result = lw.sweep_stale_logs()

        assert result["files_removed"] == 4

    def test_returns_structured_summary(self, tmp_path):
        """Verify sweep returns summary with counts and reclaimed size."""
        sys_logs = tmp_path / "system_logs"
        sys_logs.mkdir()
        _make_old_file(sys_logs / "stale.log", 60)

        with (
            patch.object(lw, "_get_system_logs_dir", return_value=sys_logs),
            patch.object(lw, "_get_ecosystem_root", return_value=tmp_path / "src" / "aipass"),
            patch.object(lw, "json_handler", MagicMock()),
        ):
            result = lw.sweep_stale_logs()

        assert result["max_age_days"] == 30
        assert result["files_removed"] == 1
        assert result["total_reclaimed_kb"] >= 0
        assert len(result["removed"]) == 1
        entry = result["removed"][0]
        assert entry["name"] == "stale.log"
        assert entry["age_days"] > 50


class TestSweepCommand:
    """Test the 'sweep' subcommand routing in handle_command."""

    def test_sweep_subcommand_routes(self, monkeypatch, tmp_path):
        """Verify 'drone @prax log-audit sweep' routes to _run_sweep and emits its exact summary strings."""
        monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path / "logs"))
        sweep = _stub_sweep(monkeypatch)
        console, warning, logger, json_handler = MagicMock(), MagicMock(), MagicMock(), MagicMock()
        monkeypatch.setattr(log_audit, "console", console)
        monkeypatch.setattr(log_audit, "warning", warning)
        monkeypatch.setattr(log_audit, "logger", logger)
        monkeypatch.setattr(log_audit, "json_handler", json_handler)

        result = log_audit.handle_command("log-audit", ["sweep"])

        assert result is True
        sweep.assert_called_once_with()
        printed = [call.args[0] for call in console.print.call_args_list]
        assert printed == [
            "\n[bold cyan]Sweeping stale logs (>30 days)...[/bold cyan]",
            "\n  Removed 1 file(s), reclaimed 12.5 KB\n",
        ]
        warning.assert_called_once_with("DELETED old.log: 45.2 days old, 12.5 KB")
        json_handler.log_operation.assert_called_once_with("log_audit_executed", {"mode": "sweep"})
        logger.info.assert_called_once_with("[log-audit] Sweep removed %d stale files", 1)


class TestTruncateAndHome:
    """The watchdog's truncate and the system_logs home it watches."""

    def test_truncate_keeps_the_tail_and_leaves_no_temp(self, tmp_path):
        """The last N lines survive behind a marker, written by replace, not in place."""
        log = tmp_path / "big.log"
        log.write_text("".join(f"line {i}\n" for i in range(50)), encoding="utf-8")

        assert lw.truncate_log_file(log, keep_lines=5) == (50, 6)
        lines = log.read_text(encoding="utf-8").splitlines()
        assert lines[0].startswith("--- LOG TRUNCATED")
        assert lines[1:] == [f"line {i}" for i in range(45, 50)]
        assert [p.name for p in tmp_path.iterdir()] == ["big.log"]

    def test_a_failed_write_leaves_the_log_whole(self, tmp_path, monkeypatch):
        """A crash before the replace never leaves the log empty or short."""
        log = tmp_path / "big.log"
        original = "".join(f"line {i}\n" for i in range(50))
        log.write_text(original, encoding="utf-8")
        monkeypatch.setattr(lw.os, "replace", MagicMock(side_effect=OSError("disk full")))

        assert lw.truncate_log_file(log, keep_lines=5) == (0, 0)
        assert log.read_text(encoding="utf-8") == original

    def test_system_logs_home_honours_the_test_log_dir(self, tmp_path, monkeypatch):
        """The watchdog watches where the loggers write, AIPASS_TEST_LOG_DIR included."""
        monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path))

        assert lw._get_system_logs_dir() == tmp_path / "system"
