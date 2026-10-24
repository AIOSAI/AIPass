# =================== AIPass ====================
# Name: test_logging_handlers.py
# Description: Tests for prax logging handler modules
# Version: 1.5.0
# Created: 2026-04-25
# Modified: 2026-10-23
# =============================================

"""Tests for apps/handlers/logging/direct.py and its sibling modules under apps/handlers/logging/."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(through_the_command) — log_watchdog's sweep_stale_logs(), covered by tests/test_sweep.py
# seedgo: no-test-needed(through_the_command) — setup_individual_logger(), covered by tests/test_logging.py
# seedgo: no-test-needed(through_the_command) — append_jsonl() in jsonl_writer.py, covered by tests/test_jsonl_writer.py

import logging
import os
import sys
from pathlib import Path
from unittest.mock import ANY, patch

import pytest

from aipass.prax.apps.handlers.logging import direct, introspection, log_watchdog
from aipass.prax.apps.handlers.logging import setup as logging_setup


class TestDirectLog:
    """direct_log() on the real body, into a logger whose files live under tmp_path."""

    def test_direct_log_writes_the_line(self, monkeypatch, tmp_path):
        """direct_log writes the message into the caller's system and local logs, both under tmp_path."""
        logs, cache, message = tmp_path / "logs", {}, "direct_log reached its file"
        monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(logs))
        monkeypatch.setattr(direct, "_direct_loggers", cache)
        try:
            direct.direct_log("warning", message)
        finally:
            for built in cache.values():
                for handler in list(built.handlers):
                    handler.close()
                    built.removeHandler(handler)

        written = sorted(logs.rglob("*.log"))
        assert len(written) == 2
        for log_file in written:
            assert message in log_file.read_text(encoding="utf-8")

    def test_racing_first_lines_build_one_handler_set(self, monkeypatch, tmp_path):
        """Threads logging their first direct line at once must not stack duplicate handlers."""
        import threading

        monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path / "logs"))
        cache = {}
        monkeypatch.setattr(direct, "_direct_loggers", cache)
        real_config = direct.load_log_config
        barrier = threading.Barrier(8)

        def slow_config():
            # Widens the window between clearing the shared logger's handlers and adding them.
            threading.Event().wait(0.01)
            return real_config()

        monkeypatch.setattr(direct, "load_log_config", slow_config)

        def first_line():
            barrier.wait()
            direct.direct_log("info", "first line")

        threads = [threading.Thread(target=first_line) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        try:
            handlers = [h for built in cache.values() for h in built.handlers]
            assert len(handlers) == 2
        finally:
            for built in cache.values():
                for handler in list(built.handlers):
                    handler.close()
                    built.removeHandler(handler)

    # The only route to an unwritable log home is a permission bit: Windows has
    # none to set, and root writes through it.
    @pytest.mark.skipif(
        os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0),
        reason="needs a POSIX permission bit that binds the writer",
    )
    def test_an_unwritable_log_home_degrades_to_log_handler_failed_and_never_raises(
        self, monkeypatch, tmp_path, caplog
    ):
        """A direct logger's first line never raises PermissionError into its caller."""
        locked, cache = tmp_path / "locked", {}
        locked.mkdir()
        monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(locked))
        monkeypatch.setattr(direct, "_direct_loggers", cache)
        locked.chmod(0o500)
        try:
            with caplog.at_level(logging.ERROR, logger=direct.logger.name):
                direct.direct_log("info", "a line with nowhere to go")
        finally:
            locked.chmod(0o700)

        failed = [r.getMessage() for r in caplog.records if r.getMessage().startswith("Log handler failed")]
        assert len(failed) == 2  # both tiers, central and local
        assert list(locked.iterdir()) == []


class TestSafeRotatingFileHandlerDoRollover:
    """Tests for setup.py SafeRotatingFileHandler, which direct.py and setup.py both build; it takes its file."""

    def test_do_rollover_success(self, mock_prax_infrastructure, tmp_path):
        """doRollover delegates to parent class on success."""
        log_file = tmp_path / "test.log"
        log_file.write_text("line1\nline2\n", encoding="utf-8")
        handler = logging_setup.SafeRotatingFileHandler(str(log_file), maxBytes=10, backupCount=1)
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="A" * 100,
            args=(),
            exc_info=None,
        )
        handler.emit(record)
        handler.close()

        # Both halves pinned, so an emit that silently skipped the rollover cannot read green.
        backup = tmp_path / "test.log.1"
        assert backup.read_text(encoding="utf-8") == "line1\nline2\n"
        assert log_file.read_text(encoding="utf-8") == "A" * 100 + "\n"

    def test_do_rollover_os_error_suppressed(self, mock_prax_infrastructure, tmp_path):
        """A failed rotation is swallowed and logged — PermissionError is an OSError, one clause catches both."""
        log_file = tmp_path / "test_os.log"
        log_file.write_text("data\n", encoding="utf-8")
        handler = logging_setup.SafeRotatingFileHandler(str(log_file), maxBytes=10, backupCount=1)
        # The stand-in's own error, so naming it is ours to do: the very object is handed on.
        failure = OSError("disk error")

        with (
            patch(
                "logging.handlers.RotatingFileHandler.doRollover",
                side_effect=failure,
            ),
            patch.object(logging_setup, "logger") as mock_logger,
        ):
            handler.doRollover()

        mock_logger.warning.assert_called_once_with("Log rotation skipped (file locked): %s", failure)
        handler.close()

    def test_a_rotation_by_another_process_is_followed_not_repeated(self, mock_prax_infrastructure, tmp_path):
        """Another writer rotated first: this handler writes to the new file and leaves the backup alone."""
        log_file = tmp_path / "shared.log"
        log_file.write_text("old\n", encoding="utf-8")
        handler = logging_setup.SafeRotatingFileHandler(str(log_file), maxBytes=50, backupCount=1)
        handler.emit(logging.makeLogRecord({"msg": "mine before"}))
        # The other process's rotation: rename aside, start a fresh file.
        os.replace(log_file, tmp_path / "shared.log.1")
        log_file.write_text("theirs\n", encoding="utf-8")

        handler.emit(logging.makeLogRecord({"msg": "mine after"}))
        handler.close()

        assert (tmp_path / "shared.log.1").read_text(encoding="utf-8") == "old\nmine before\n"
        assert log_file.read_text(encoding="utf-8") == "theirs\nmine after\n"

    def test_the_size_check_reads_the_file_on_disk(self, mock_prax_infrastructure, tmp_path):
        """Lines another process appended count toward the limit, not just this handler's own."""
        log_file = tmp_path / "grown.log"
        handler = logging_setup.SafeRotatingFileHandler(str(log_file), maxBytes=40, backupCount=1)
        handler.emit(logging.makeLogRecord({"msg": "a"}))
        with open(log_file, "a", encoding="utf-8") as other:
            other.write("x" * 40 + "\n")

        handler.emit(logging.makeLogRecord({"msg": "b"}))
        handler.close()

        assert (tmp_path / "grown.log.1").read_text(encoding="utf-8") == "a\n" + "x" * 40 + "\n"
        assert log_file.read_text(encoding="utf-8") == "b\n"


class TestGetCallingModulePath:
    """Tests for introspection.py get_calling_module_path()."""

    def test_returns_this_test_files_path(self, mock_prax_infrastructure):
        """The first non-prax-internal frame is this test file, so that is the path."""
        result = introspection.get_calling_module_path()
        assert isinstance(result, str)
        assert result == __file__
        assert Path(result).name == "test_logging_handlers.py"

    def test_returns_none_when_no_external_caller(self, mock_prax_infrastructure):
        """Returns None when _find_external_caller_path returns None."""
        with patch.object(introspection, "_find_external_caller_path", return_value=None):
            result = introspection.get_calling_module_path()
            assert result is None

    def test_returns_path_when_external_caller_found(self, mock_prax_infrastructure):
        """Returns the path from _find_external_caller_path when found."""
        fake_path = str(Path.home() / "src" / "aipass" / "flow" / "apps" / "flow.py")
        with patch.object(introspection, "_find_external_caller_path", return_value=fake_path):
            result = introspection.get_calling_module_path()
            assert result == fake_path


class TestGetOversizedFiles:
    """Tests for log_watchdog.py get_oversized_files()."""

    def test_returns_empty_when_no_oversized(self, mock_prax_infrastructure, tmp_path):
        """Returns empty list when no files exceed threshold."""
        lw = _import_watchdog(tmp_path)

        logs_dir = tmp_path / "system_logs"
        logs_dir.mkdir()
        small_log = logs_dir / "small.log"
        small_log.write_text("line1\nline2\nline3\n", encoding="utf-8")

        with patch.object(lw, "_get_system_logs_dir", return_value=logs_dir):
            result = lw.get_oversized_files(threshold=100)
            assert result == []

    def test_returns_oversized_files(self, mock_prax_infrastructure, tmp_path):
        """Returns files that exceed the threshold."""
        lw = _import_watchdog(tmp_path)

        logs_dir = tmp_path / "system_logs"
        logs_dir.mkdir()
        big_log = logs_dir / "big.log"
        big_log.write_text(
            "\n".join(f"line {i}" for i in range(200)) + "\n",
            encoding="utf-8",
        )

        with patch.object(lw, "_get_system_logs_dir", return_value=logs_dir):
            result = lw.get_oversized_files(threshold=100)
            assert len(result) == 1
            assert result[0]["name"] == "big.log"
            assert result[0]["lines"] >= 100

    def test_nonexistent_dir_returns_empty(self, mock_prax_infrastructure, tmp_path):
        """Returns empty list when system_logs dir does not exist."""
        lw = _import_watchdog(tmp_path)

        nonexistent = tmp_path / "does_not_exist"
        with patch.object(lw, "_get_system_logs_dir", return_value=nonexistent):
            result = lw.get_oversized_files()
            assert result == []


class TestTruncateLogFile:
    """Tests for log_watchdog.py truncate_log_file()."""

    def test_truncates_oversized_file(self, mock_prax_infrastructure, tmp_path):
        """Truncates file to keep_lines and adds truncation marker."""
        lw = _import_watchdog(tmp_path)

        log_file = tmp_path / "truncate_me.log"
        lines = [f"line {i}\n" for i in range(500)]
        log_file.write_text("".join(lines), encoding="utf-8")

        original, new = lw.truncate_log_file(log_file, keep_lines=100)
        assert original == 500
        assert new == 101  # 100 kept lines + 1 marker

        content = log_file.read_text(encoding="utf-8")
        assert "LOG TRUNCATED by PRAX watchdog" in content

    def test_no_truncation_when_under_limit(self, mock_prax_infrastructure, tmp_path):
        """File under limit is not modified."""
        lw = _import_watchdog(tmp_path)

        log_file = tmp_path / "small.log"
        lines = [f"line {i}\n" for i in range(50)]
        log_file.write_text("".join(lines), encoding="utf-8")

        original, new = lw.truncate_log_file(log_file, keep_lines=100)
        assert original == 50
        assert new == 50

    def test_truncate_handles_os_error(self, mock_prax_infrastructure, tmp_path):
        """Returns (0, 0) on OSError."""
        lw = _import_watchdog(tmp_path)

        nonexistent = tmp_path / "does_not_exist.log"
        original, new = lw.truncate_log_file(nonexistent, keep_lines=100)
        assert original == 0
        assert new == 0


def _import_watchdog(tmp_path):
    """The log_watchdog module bound at the top."""
    return log_watchdog


class TestScanBranchLogFiles:
    """Tests for log_watchdog.py scan_branch_log_files()."""

    def test_detects_large_jsonl(self, mock_prax_infrastructure, tmp_path):
        """Flags .jsonl files exceeding size threshold as critical."""
        lw = _import_watchdog(tmp_path)

        eco = tmp_path / "src" / "aipass"
        branch_logs = eco / "hooks" / "logs"
        branch_logs.mkdir(parents=True)

        big_jsonl = branch_logs / "engine.jsonl"
        big_jsonl.write_text(
            "\n".join(f'{{"line": {i}, "padding": "{" " * 200}}}' for i in range(10000)) + "\n",
            encoding="utf-8",
        )

        with patch.object(lw, "_get_ecosystem_root", return_value=eco):
            with patch.object(lw, "BRANCH_WARN_SIZE_MB", 0.5):
                results = lw.scan_branch_log_files()
                assert len(results) == 1
                assert results[0]["name"] == "engine.jsonl"
                assert results[0]["branch"] == "hooks"
                assert not results[0]["has_rotation"]
                assert results[0]["status"] in ("warning", "critical")

    def test_ignores_small_rotated_logs(self, mock_prax_infrastructure, tmp_path):
        """Small .log files with rotation siblings are status ok."""
        lw = _import_watchdog(tmp_path)

        eco = tmp_path / "src" / "aipass"
        branch_logs = eco / "backup" / "logs"
        branch_logs.mkdir(parents=True)

        small_log = branch_logs / "client.log"
        small_log.write_text("line1\nline2\n", encoding="utf-8")
        rotation = branch_logs / "client.log.1"
        rotation.write_text("old line\n", encoding="utf-8")

        with patch.object(lw, "_get_ecosystem_root", return_value=eco):
            results = lw.scan_branch_log_files()
            assert len(results) == 1
            assert results[0]["name"] == "client.log"
            assert results[0]["has_rotation"] is True
            assert results[0]["status"] == "ok"

    def test_empty_ecosystem_returns_empty(self, mock_prax_infrastructure, tmp_path):
        """Returns empty when ecosystem root does not exist."""
        lw = _import_watchdog(tmp_path)

        nonexistent = tmp_path / "no_such_dir"
        with patch.object(lw, "_get_ecosystem_root", return_value=nonexistent):
            results = lw.scan_branch_log_files()
            assert results == []

    def test_scans_multiple_branches(self, mock_prax_infrastructure, tmp_path):
        """Scans logs/ across multiple branches."""
        lw = _import_watchdog(tmp_path)

        eco = tmp_path / "src" / "aipass"
        for branch in ("hooks", "backup", "trigger"):
            logs = eco / branch / "logs"
            logs.mkdir(parents=True)
            (logs / "test.log").write_text("line\n" * 10, encoding="utf-8")

        with patch.object(lw, "_get_ecosystem_root", return_value=eco):
            results = lw.scan_branch_log_files()
            branches = {r["branch"] for r in results}
            assert branches == {"hooks", "backup", "trigger"}


class TestBranchLogHealthSummary:
    """Tests for log_watchdog.py branch_log_health_summary()."""

    def test_healthy_summary(self, mock_prax_infrastructure, tmp_path):
        """Returns healthy when all files are ok."""
        lw = _import_watchdog(tmp_path)

        eco = tmp_path / "src" / "aipass"
        logs = eco / "prax" / "logs"
        logs.mkdir(parents=True)
        (logs / "test.log").write_text("line\n" * 5, encoding="utf-8")

        with patch.object(lw, "_get_ecosystem_root", return_value=eco):
            summary = lw.branch_log_health_summary()
            assert summary["healthy"] is True
            assert summary["total_files"] == 1
            assert summary["oversized_count"] == 0

    def test_empty_summary(self, mock_prax_infrastructure, tmp_path):
        """Returns healthy empty summary when no files found."""
        lw = _import_watchdog(tmp_path)

        nonexistent = tmp_path / "nope"
        with patch.object(lw, "_get_ecosystem_root", return_value=nonexistent):
            summary = lw.branch_log_health_summary()
            assert summary["healthy"] is True
            assert summary["total_files"] == 0


class TestEnforceBranchLogLimits:
    """Tests for log_watchdog.py enforce_branch_log_limits()."""

    def test_truncates_oversized_jsonl(self, mock_prax_infrastructure, tmp_path):
        """Truncates .jsonl files that exceed size threshold."""
        lw = _import_watchdog(tmp_path)

        eco = tmp_path / "src" / "aipass"
        logs = eco / "hooks" / "logs"
        logs.mkdir(parents=True)

        big_jsonl = logs / "engine.jsonl"
        big_jsonl.write_text(
            "\n".join(f'{{"line": {i}, "padding": "{" " * 200}}}' for i in range(10000)) + "\n",
            encoding="utf-8",
        )

        with patch.object(lw, "_get_ecosystem_root", return_value=eco):
            with patch.object(lw, "BRANCH_WARN_SIZE_MB", 0.5):
                actions = lw.enforce_branch_log_limits(max_lines=1000)
                assert len(actions) >= 1
                action = actions[0]
                assert action["truncated"] is True
                assert action["branch"] == "hooks"

                content = big_jsonl.read_text(encoding="utf-8")
                assert "LOG TRUNCATED by PRAX watchdog" in content


class TestSetupWindowsSafeRotatingHandlerDoRollover:
    """Tests for the rotating handler setup.py builds into every module logger."""

    @pytest.fixture
    def system_handler(self, monkeypatch, tmp_path):
        """The system-log handler of a freshly built logger, its file holding 'data'."""
        monkeypatch.setattr(logging_setup, "get_system_logs_dir", lambda: tmp_path)
        monkeypatch.setattr(logging_setup, "get_module_logs_dir", lambda branch: tmp_path / "local")
        monkeypatch.setattr(
            logging_setup,
            "load_log_config",
            lambda: {
                "log_format": "%(message)s",
                "date_format": "%H:%M:%S",
                "system_logs": {"max_lines": 1, "backup_count": 1},
                "local_logs": {"max_lines": 1, "backup_count": 1},
            },
        )
        monkeypatch.setattr(logging_setup, "lines_to_bytes", lambda lines: 10)
        monkeypatch.setattr(logging_setup, "_captured_loggers", {})
        log_file = tmp_path / "prax_rollover_test.log"
        log_file.write_text("data\n", encoding="utf-8")
        built = logging_setup.setup_individual_logger("rollover_test", caller_branch="prax")
        try:
            yield built.handlers[0], log_file
        finally:
            for handler in list(built.handlers):
                built.removeHandler(handler)
                handler.close()

    def test_do_rollover_success(self, mock_prax_infrastructure, system_handler, tmp_path):
        """Normal rollover succeeds."""
        handler, log_file = system_handler
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="A" * 50,
            args=(),
            exc_info=None,
        )
        handler.emit(record)
        handler.close()

        backup = tmp_path / "prax_rollover_test.log.1"
        assert backup.read_text(encoding="utf-8") == "data\n"
        assert log_file.read_text(encoding="utf-8") == "A" * 50 + "\n"

    def test_do_rollover_permission_error_suppressed(self, mock_prax_infrastructure, system_handler, tmp_path):
        """PermissionError during rollover is caught, not raised."""
        handler, log_file = system_handler

        with (
            patch(
                "logging.handlers.RotatingFileHandler.doRollover",
                side_effect=PermissionError("locked"),
            ),
            patch.object(logging_setup, "logger") as mock_logger,
        ):
            handler.doRollover()
        handler.close()

        # Not raising is half the contract: the skip is reported once and no backup is made.
        mock_logger.warning.assert_called_once_with("Log rotation skipped (file locked): %s", ANY)
        assert str(mock_logger.warning.call_args[0][1]) == "locked"
        assert not (tmp_path / "prax_rollover_test.log.1").exists()
        assert log_file.read_text(encoding="utf-8") == "data\n"


_COUNT_IMPORT_WRITES = """
import sys
writes = []
def hook(event, args):
    if event in ("os.rename", "os.replace"):
        writes.append(str(args[1]))
    elif event == "open" and any(c in str(args[1] or "r") for c in "wax+"):
        writes.append(str(args[0]))
sys.addaudithook(hook)
import aipass.prax.apps.modules.dashboard
print(len(writes))
"""


class TestAnImportWritesNothing:
    """A fresh import of the dashboard module writes nothing.

    Handlers call get_direct_logger() at module level, so any write there is paid by every
    importer. The fresh interpreter has AIPASS_TEST_LOG_DIR set: a red run writes under tmp_path.
    """

    def test_a_fresh_import_of_the_dashboard_module_writes_nothing(self, tmp_path):
        import os
        import subprocess

        env = dict(os.environ, AIPASS_TEST_LOG_DIR=str(tmp_path / "logs"))
        done = subprocess.run(
            [sys.executable, "-c", _COUNT_IMPORT_WRITES],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
            cwd=str(tmp_path),
            env=env,
        )
        assert done.returncode == 0, done.stderr[-600:]
        assert done.stdout.strip().splitlines()[-1] == "0"
