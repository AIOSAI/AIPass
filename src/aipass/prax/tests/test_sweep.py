# =================== AIPass ====================
# Name: test_sweep.py
# Description: Tests for stale log sweep in log_audit
# Version: 1.3.0
# Created: 2026-07-10
# Modified: 2026-09-29
# =============================================

"""Tests for apps/handlers/logging/log_watchdog.py's sweep_stale_logs and apps/modules/log_audit.py's sweep route."""

# Tests for sweep_stale_logs — the 30-day stale log cleanup policy.
#
# Verifies: age-based deletion, pattern matching (.log, .jsonl, .1 siblings),
# directory scanning across system_logs/ and branch logs/.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(error_handling) — _file_age_days answering 0.0 when the stat fails, covered by that row
# seedgo: no-test-needed(error_handling) — _sweep_directory's warning when an unlink fails, covered by that row
# seedgo: no-test-needed(json_structure) — sweep_stale_logs' log_sweep log_operation record, covered by that row

import os
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

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
    return sweep


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
        """Verify 'drone @prax log-audit sweep' routes to _run_sweep.

        log_audit is the real module, imported at the top; its console, warning,
        logger and json_handler are replaced where log_audit binds them. The
        recorders' calls ARE the output, and they are what this pins — the exact
        strings _run_sweep emits for the summary the watchdog returns.
        """
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
