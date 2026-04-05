# ===================AIPASS====================
# META DATA HEADER
# Name: test_scheduler_cron.py - Scheduler Cron Tests
# Date: 2026-04-02
# Version: 1.0.0
# Category: daemon/tests
#
# CHANGELOG (Max 5 entries):
#   - v1.0.0 (2026-04-02): Initial creation - scheduler_cron dispatch path tests
#
# CODE STANDARDS:
#   - Pytest conventions
#   - Full mock isolation (no real subprocesses or locks)
# =============================================

"""Tests for scheduler_cron dispatch paths."""

import subprocess
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

MODULE = "aipass.daemon.apps.scheduler_cron"


# =============================================
# FIXTURES
# =============================================

def _make_task(
    task_id: str = "abc12345-6789",
    recipient: str = "@devpulse",
    task: str = "Run morning briefing",
    message: str = "Details here",
) -> dict:
    """Build a minimal task dict for testing."""
    return {
        "id": task_id,
        "recipient": recipient,
        "task": task,
        "message": message,
    }


@pytest.fixture(autouse=True)
def _silence_logging():
    """Suppress logger and console output for all tests."""
    with (
        patch(f"{MODULE}.logger"),
        patch(f"{MODULE}.console"),
        patch(f"{MODULE}.log"),
    ):
        yield


# =============================================
# _send_email_via_drone
# =============================================

class TestSendEmailViaDrone:
    """Tests for _send_email_via_drone subprocess wrapper."""

    def test_success(self):
        from aipass.daemon.apps.scheduler_cron import _send_email_via_drone

        mock_result = MagicMock(returncode=0)
        with patch(f"{MODULE}.subprocess.run", return_value=mock_result) as mock_run:
            result = _send_email_via_drone("@devpulse", "Subject", "Body")
        assert result is True
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd[:3] == ["drone", "@ai_mail", "send"]
        assert "--dispatch" in cmd

    def test_no_auto_execute(self):
        from aipass.daemon.apps.scheduler_cron import _send_email_via_drone

        mock_result = MagicMock(returncode=0)
        with patch(f"{MODULE}.subprocess.run", return_value=mock_result) as mock_run:
            _send_email_via_drone("@devpulse", "Subj", "Msg", auto_execute=False)
        cmd = mock_run.call_args[0][0]
        assert "--dispatch" not in cmd

    def test_nonzero_returncode(self):
        from aipass.daemon.apps.scheduler_cron import _send_email_via_drone

        mock_result = MagicMock(returncode=1)
        with patch(f"{MODULE}.subprocess.run", return_value=mock_result):
            result = _send_email_via_drone("@devpulse", "Subj", "Msg")
        assert result is False

    def test_subprocess_error(self):
        from aipass.daemon.apps.scheduler_cron import _send_email_via_drone

        with patch(f"{MODULE}.subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="drone", timeout=15)):
            result = _send_email_via_drone("@devpulse", "Subj", "Msg")
        assert result is False

    def test_os_error(self):
        from aipass.daemon.apps.scheduler_cron import _send_email_via_drone

        with patch(f"{MODULE}.subprocess.run", side_effect=OSError("drone not found")):
            result = _send_email_via_drone("@devpulse", "Subj", "Msg")
        assert result is False


# =============================================
# _next_cron_run
# =============================================

class TestNextCronRun:
    """Tests for next cron run time calculation."""

    def test_before_half_hour(self):
        from aipass.daemon.apps.scheduler_cron import _next_cron_run

        fake_now = datetime(2026, 4, 2, 10, 15, 0)
        with patch(f"{MODULE}.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = _next_cron_run()
        assert result == "10:30"

    def test_after_half_hour(self):
        from aipass.daemon.apps.scheduler_cron import _next_cron_run

        fake_now = datetime(2026, 4, 2, 10, 45, 0)
        with patch(f"{MODULE}.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = _next_cron_run()
        assert result == "11:00"

    def test_before_midnight_rollover(self):
        from aipass.daemon.apps.scheduler_cron import _next_cron_run

        fake_now = datetime(2026, 4, 2, 23, 45, 0)
        with patch(f"{MODULE}.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = _next_cron_run()
        assert result == "00:00"


# =============================================
# _process_single_task
# =============================================

class TestProcessSingleTask:
    """Tests for the single-task dispatch function."""

    def test_success_path(self):
        from aipass.daemon.apps.scheduler_cron import _process_single_task

        results = {"success": 0, "failed": 0, "errors": []}
        task = _make_task()

        with (
            patch(f"{MODULE}.mark_dispatching") as mock_dispatch,
            patch(f"{MODULE}.send_email_direct", return_value=True) as mock_send,
            patch(f"{MODULE}.mark_completed") as mock_complete,
            patch(f"{MODULE}.AI_MAIL_AVAILABLE", True),
        ):
            _process_single_task(task, results)

        mock_dispatch.assert_called_once_with(task["id"])
        mock_send.assert_called_once()
        mock_complete.assert_called_once_with(task["id"])
        assert results["success"] == 1
        assert results["failed"] == 0

    def test_mark_dispatching_failure(self):
        from aipass.daemon.apps.scheduler_cron import _process_single_task

        results = {"success": 0, "failed": 0, "errors": []}
        task = _make_task()

        with (
            patch(f"{MODULE}.mark_dispatching", side_effect=RuntimeError("lock error")),
            patch(f"{MODULE}.send_email_direct") as mock_send,
        ):
            _process_single_task(task, results)

        mock_send.assert_not_called()
        assert results["failed"] == 1
        assert len(results["errors"]) == 1

    def test_email_unavailable(self):
        from aipass.daemon.apps.scheduler_cron import _process_single_task

        results = {"success": 0, "failed": 0, "errors": []}
        task = _make_task()

        with (
            patch(f"{MODULE}.mark_dispatching"),
            patch(f"{MODULE}.AI_MAIL_AVAILABLE", False),
            patch(f"{MODULE}.mark_pending") as mock_pending,
        ):
            _process_single_task(task, results)

        mock_pending.assert_called_once_with(task["id"])
        assert results["failed"] == 1

    def test_email_send_returns_false(self):
        from aipass.daemon.apps.scheduler_cron import _process_single_task

        results = {"success": 0, "failed": 0, "errors": []}
        task = _make_task()

        with (
            patch(f"{MODULE}.mark_dispatching"),
            patch(f"{MODULE}.send_email_direct", return_value=False),
            patch(f"{MODULE}.mark_pending") as mock_pending,
            patch(f"{MODULE}.AI_MAIL_AVAILABLE", True),
        ):
            _process_single_task(task, results)

        mock_pending.assert_called_once_with(task["id"])
        assert results["failed"] == 1
        assert results["success"] == 0

    def test_email_exception_resets_to_pending(self):
        from aipass.daemon.apps.scheduler_cron import _process_single_task

        results = {"success": 0, "failed": 0, "errors": []}
        task = _make_task()

        with (
            patch(f"{MODULE}.mark_dispatching"),
            patch(f"{MODULE}.send_email_direct", side_effect=ConnectionError("timeout")),
            patch(f"{MODULE}.mark_pending") as mock_pending,
            patch(f"{MODULE}.AI_MAIL_AVAILABLE", True),
        ):
            _process_single_task(task, results)

        mock_pending.assert_called_once_with(task["id"])
        assert results["failed"] == 1


# =============================================
# process_due_tasks
# =============================================

class TestProcessDueTasks:
    """Tests for the top-level due-task processor."""

    def test_no_tasks_due(self):
        from aipass.daemon.apps.scheduler_cron import process_due_tasks

        with (
            patch(f"{MODULE}.TASK_REGISTRY_AVAILABLE", True),
            patch(f"{MODULE}.recover_stale_dispatches", return_value=0),
            patch(f"{MODULE}.get_due_tasks", return_value=[]),
        ):
            results = process_due_tasks()

        assert results["due"] == 0
        assert results["success"] == 0

    def test_task_registry_unavailable(self):
        from aipass.daemon.apps.scheduler_cron import process_due_tasks

        with patch(f"{MODULE}.TASK_REGISTRY_AVAILABLE", False):
            results = process_due_tasks()

        assert results["due"] == 0
        assert results["success"] == 0

    def test_stale_dispatch_recovery(self):
        from aipass.daemon.apps.scheduler_cron import process_due_tasks

        with (
            patch(f"{MODULE}.TASK_REGISTRY_AVAILABLE", True),
            patch(f"{MODULE}.recover_stale_dispatches", return_value=3) as mock_recover,
            patch(f"{MODULE}.get_due_tasks", return_value=[]),
        ):
            results = process_due_tasks()

        mock_recover.assert_called_once_with(max_age_minutes=5)
        assert results["recovered"] == 3

    def test_stale_recovery_exception(self):
        from aipass.daemon.apps.scheduler_cron import process_due_tasks

        with (
            patch(f"{MODULE}.TASK_REGISTRY_AVAILABLE", True),
            patch(f"{MODULE}.recover_stale_dispatches", side_effect=RuntimeError("fs error")),
            patch(f"{MODULE}.get_due_tasks", return_value=[]),
        ):
            results = process_due_tasks()

        assert len(results["errors"]) == 1
        assert "Stale recovery" in results["errors"][0]

    def test_get_due_tasks_exception(self):
        from aipass.daemon.apps.scheduler_cron import process_due_tasks

        with (
            patch(f"{MODULE}.TASK_REGISTRY_AVAILABLE", True),
            patch(f"{MODULE}.recover_stale_dispatches", return_value=0),
            patch(f"{MODULE}.get_due_tasks", side_effect=RuntimeError("corrupt JSON")),
        ):
            results = process_due_tasks()

        assert "Load tasks" in results["errors"][0]

    @patch(f"{MODULE}.time.sleep")
    def test_successful_send(self, _mock_sleep):
        from aipass.daemon.apps.scheduler_cron import process_due_tasks

        task = _make_task()
        with (
            patch(f"{MODULE}.TASK_REGISTRY_AVAILABLE", True),
            patch(f"{MODULE}.recover_stale_dispatches", return_value=0),
            patch(f"{MODULE}.get_due_tasks", return_value=[task]),
            patch(f"{MODULE}.mark_dispatching"),
            patch(f"{MODULE}.send_email_direct", return_value=True),
            patch(f"{MODULE}.mark_completed"),
            patch(f"{MODULE}.AI_MAIL_AVAILABLE", True),
        ):
            results = process_due_tasks()

        assert results["due"] == 1
        assert results["success"] == 1
        assert results["failed"] == 0

    @patch(f"{MODULE}.time.sleep")
    def test_send_failure_marks_pending(self, _mock_sleep):
        from aipass.daemon.apps.scheduler_cron import process_due_tasks

        task = _make_task()
        with (
            patch(f"{MODULE}.TASK_REGISTRY_AVAILABLE", True),
            patch(f"{MODULE}.recover_stale_dispatches", return_value=0),
            patch(f"{MODULE}.get_due_tasks", return_value=[task]),
            patch(f"{MODULE}.mark_dispatching"),
            patch(f"{MODULE}.send_email_direct", return_value=False),
            patch(f"{MODULE}.mark_pending") as mock_pending,
            patch(f"{MODULE}.AI_MAIL_AVAILABLE", True),
        ):
            results = process_due_tasks()

        mock_pending.assert_called_once()
        assert results["failed"] == 1


# =============================================
# _run_locked
# =============================================

class TestRunLocked:
    """Tests for the locked orchestration function."""

    def test_success_no_errors(self):
        from aipass.daemon.apps.scheduler_cron import _run_locked

        task_results = {"due": 0, "success": 0, "failed": 0, "recovered": 0, "errors": []}
        action_results = {
            "total": 0, "enabled": 0, "executed": 0, "failed": 0,
            "errors": [], "executed_actions": [], "skipped_actions": [],
        }

        with (
            patch(f"{MODULE}.process_due_tasks", return_value=task_results),
            patch(f"{MODULE}.process_actions", return_value=action_results),
            patch(f"{MODULE}._next_cron_run", return_value="10:30"),
        ):
            code = _run_locked()

        assert code == 0

    def test_returns_1_on_task_failures(self):
        from aipass.daemon.apps.scheduler_cron import _run_locked

        task_results = {"due": 1, "success": 0, "failed": 1, "recovered": 0, "errors": ["fail"]}
        action_results = {
            "total": 0, "enabled": 0, "executed": 0, "failed": 0,
            "errors": [], "executed_actions": [], "skipped_actions": [],
        }

        with (
            patch(f"{MODULE}.process_due_tasks", return_value=task_results),
            patch(f"{MODULE}.process_actions", return_value=action_results),
            patch(f"{MODULE}._next_cron_run", return_value="10:30"),
        ):
            code = _run_locked()

        assert code == 1

    def test_process_due_tasks_unhandled_exception(self):
        from aipass.daemon.apps.scheduler_cron import _run_locked

        with patch(f"{MODULE}.process_due_tasks", side_effect=RuntimeError("boom")):
            code = _run_locked()

        assert code == 1

    def test_process_actions_exception_handled(self):
        from aipass.daemon.apps.scheduler_cron import _run_locked

        task_results = {"due": 0, "success": 0, "failed": 0, "recovered": 0, "errors": []}

        with (
            patch(f"{MODULE}.process_due_tasks", return_value=task_results),
            patch(f"{MODULE}.process_actions", side_effect=RuntimeError("action boom")),
            patch(f"{MODULE}._next_cron_run", return_value="10:30"),
        ):
            code = _run_locked()

        # The action error is caught but appended to errors, triggering exit 1
        assert code == 1


# =============================================
# main
# =============================================

class TestMain:
    """Tests for the main entry point."""

    def test_no_args_introspection(self):
        from aipass.daemon.apps.scheduler_cron import main

        with (
            patch(f"{MODULE}.sys.argv", ["scheduler_cron.py"]),
            patch(f"{MODULE}.print_introspection") as mock_intro,
        ):
            code = main()

        mock_intro.assert_called_once()
        assert code == 0

    def test_help_flag(self):
        from aipass.daemon.apps.scheduler_cron import main

        with (
            patch(f"{MODULE}.sys.argv", ["scheduler_cron.py", "--help"]),
            patch(f"{MODULE}.print_help") as mock_help,
        ):
            with pytest.raises(SystemExit) as exc_info:
                main()
        mock_help.assert_called_once()
        assert exc_info.value.code == 0

    def test_lock_acquisition_failure(self, tmp_path):
        from aipass.daemon.apps.scheduler_cron import main

        lock_file = tmp_path / "schedule.lock"
        mock_fd = MagicMock()
        with (
            patch(f"{MODULE}.sys.argv", ["scheduler_cron.py", "run"]),
            patch(f"{MODULE}.json_handler"),
            patch(f"{MODULE}.LOCK_FILE", lock_file),
            patch("builtins.open", return_value=mock_fd),
            patch(f"{MODULE}.fcntl.flock", side_effect=OSError("locked")),
        ):
            code = main()

        assert code == 0  # graceful skip when another instance is running
        mock_fd.close.assert_called()

    def test_lock_acquired_runs_locked(self, tmp_path):
        from aipass.daemon.apps.scheduler_cron import main

        lock_file = tmp_path / "schedule.lock"
        mock_fd = MagicMock()
        with (
            patch(f"{MODULE}.sys.argv", ["scheduler_cron.py", "run"]),
            patch(f"{MODULE}.json_handler"),
            patch(f"{MODULE}.LOCK_FILE", lock_file),
            patch("builtins.open", return_value=mock_fd),
            patch(f"{MODULE}.fcntl.flock"),
            patch(f"{MODULE}._run_locked", return_value=0) as mock_run,
        ):
            code = main()

        mock_run.assert_called_once()
        assert code == 0
