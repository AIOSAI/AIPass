# =================== AIPass ====================
# Name: test_schedule_module.py
# Description: Tests for the schedule CLI module
# Version: 1.0.0
# Created: 2026-04-03
# Modified: 2026-04-03
# =============================================

"""Tests for the schedule CLI module (apps/modules/schedule.py)."""

from unittest.mock import patch, MagicMock

MODULE = "aipass.daemon.apps.modules.schedule"


# =============================================
# handle_command -- routing basics
# =============================================

@patch(f"{MODULE}.json_handler")
@patch(f"{MODULE}.console")
@patch(f"{MODULE}.cli_error")
@patch(f"{MODULE}.logger")
class TestHandleCommandRouting:
    """Tests for handle_command routing."""

    def test_wrong_command_returns_false(self, _log, _err, _con, _jh):
        from aipass.daemon.apps.modules.schedule import handle_command

        assert handle_command("not_schedule", []) is False

    def test_no_args_shows_introspection(self, _log, _err, mock_con, _jh):
        from aipass.daemon.apps.modules.schedule import handle_command

        result = handle_command("schedule", [])
        assert result is True
        calls = [str(c) for c in mock_con.print.call_args_list]
        assert any("schedule Module" in c for c in calls)

    def test_help_flag(self, _log, _err, mock_con, _jh):
        from aipass.daemon.apps.modules.schedule import handle_command

        result = handle_command("schedule", ["--help"])
        assert result is True
        calls = [str(c) for c in mock_con.print.call_args_list]
        assert any("USAGE" in c for c in calls)

    def test_unknown_subcommand(self, _log, mock_err, _con, _jh):
        from aipass.daemon.apps.modules.schedule import handle_command

        result = handle_command("schedule", ["foobar"])
        assert result is False
        mock_err.assert_called()


# =============================================
# handle_command -- list subcommand
# =============================================

@patch(f"{MODULE}.json_handler")
@patch(f"{MODULE}.console")
@patch(f"{MODULE}.cli_error")
@patch(f"{MODULE}.logger")
class TestListSubcommand:
    """Tests for 'schedule list' subcommand."""

    @patch(f"{MODULE}.load_tasks", return_value=[])
    def test_list_success(self, mock_load, _log, _err, mock_con, mock_jh):
        from aipass.daemon.apps.modules.schedule import handle_command

        result = handle_command("schedule", ["list"])
        assert result is True
        mock_load.assert_called_once()

    @patch(f"{MODULE}.load_tasks", side_effect=RuntimeError("disk error"))
    def test_list_exception(self, _load, _log, mock_err, _con, _jh):
        from aipass.daemon.apps.modules.schedule import handle_command

        result = handle_command("schedule", ["list"])
        assert result is False
        mock_err.assert_called()


# =============================================
# handle_command -- delete subcommand
# =============================================

@patch(f"{MODULE}.json_handler")
@patch(f"{MODULE}.console")
@patch(f"{MODULE}.cli_error")
@patch(f"{MODULE}.logger")
class TestDeleteSubcommand:
    """Tests for 'schedule delete' subcommand."""

    def test_delete_no_args_shows_error(self, _log, mock_err, _con, _jh):
        from aipass.daemon.apps.modules.schedule import handle_command

        result = handle_command("schedule", ["delete"])
        assert result is False
        mock_err.assert_called()

    @patch(f"{MODULE}.delete_task", return_value=True)
    def test_delete_success(self, mock_del, _log, _err, _con, _jh):
        from aipass.daemon.apps.modules.schedule import handle_command

        result = handle_command("schedule", ["delete", "abc123"])
        assert result is True
        mock_del.assert_called_once_with("abc123")

    @patch(f"{MODULE}.delete_task", return_value=False)
    def test_delete_not_found(self, mock_del, _log, mock_err, _con, _jh):
        from aipass.daemon.apps.modules.schedule import handle_command

        result = handle_command("schedule", ["delete", "abc123"])
        assert result is False
        mock_err.assert_called()


# =============================================
# handle_command -- run-due subcommand
# =============================================

@patch(f"{MODULE}.json_handler")
@patch(f"{MODULE}.console")
@patch(f"{MODULE}.cli_error")
@patch(f"{MODULE}.logger")
class TestRunDueSubcommand:
    """Tests for 'schedule run-due' subcommand."""

    @patch(f"{MODULE}.process_due_tasks_batch", return_value={
        "recovered": 0, "due": 0, "success": 0, "failed": 0, "processed_tasks": [],
    })
    @patch(f"{MODULE}.FILELOCK_AVAILABLE", False)
    def test_run_due_without_lock(self, mock_batch, _log, _err, mock_con, _jh):
        from aipass.daemon.apps.modules.schedule import handle_command

        result = handle_command("schedule", ["run-due"])
        assert result is True
        mock_batch.assert_called_once()

    @patch(f"{MODULE}.process_due_tasks_batch", return_value={
        "recovered": 1,
        "due": 2,
        "success": 1,
        "failed": 1,
        "processed_tasks": [
            {"id": "a1", "recipient": "@flow", "task": "Check plan", "status": "sent"},
            {"id": "a2", "recipient": "@seedgo", "task": "Audit", "status": "failed"},
        ],
    })
    @patch(f"{MODULE}.FILELOCK_AVAILABLE", False)
    def test_run_due_processes_tasks(self, mock_batch, _log, _err, mock_con, _jh):
        from aipass.daemon.apps.modules.schedule import handle_command

        result = handle_command("schedule", ["run-due"])
        assert result is True
        mock_batch.assert_called_once()
        calls = " ".join(str(c) for c in mock_con.print.call_args_list)
        assert "1 sent" in calls
        assert "1 failed" in calls


# =============================================
# _handle_create
# =============================================

@patch(f"{MODULE}.console")
@patch(f"{MODULE}.cli_error")
@patch(f"{MODULE}.logger")
class TestHandleCreate:
    """Tests for _handle_create."""

    @patch(f"{MODULE}.create_task", return_value={"id": "task-001"})
    @patch(f"{MODULE}.parse_due_date", return_value="2026-04-10")
    def test_create_valid(self, _due, mock_create, _log, _err, _con):
        from aipass.daemon.apps.modules.schedule import _handle_create

        result = _handle_create(["Follow up", "--due", "7d", "--to", "@flow"])
        assert result is True
        mock_create.assert_called_once()

    def test_create_missing_task(self, _log, mock_err, _con):
        from aipass.daemon.apps.modules.schedule import _handle_create

        result = _handle_create(["--due", "7d", "--to", "@flow"])
        assert result is False
        mock_err.assert_called()

    @patch(f"{MODULE}.parse_due_date", return_value=None)
    def test_create_invalid_due(self, _due, _log, mock_err, _con):
        from aipass.daemon.apps.modules.schedule import _handle_create

        result = _handle_create(["Task text", "--due", "xyz", "--to", "@flow"])
        assert result is False
        mock_err.assert_called()


# =============================================
# _process_due_tasks
# =============================================

@patch(f"{MODULE}.console")
@patch(f"{MODULE}.cli_error")
@patch(f"{MODULE}.logger")
class TestProcessDueTasks:
    """Tests for _process_due_tasks."""

    @patch(f"{MODULE}.process_due_tasks_batch", return_value={
        "recovered": 0, "due": 0, "success": 0, "failed": 0, "processed_tasks": [],
    })
    def test_no_tasks_due(self, mock_batch, _log, _err, mock_con):
        from aipass.daemon.apps.modules.schedule import _process_due_tasks

        result = _process_due_tasks()
        assert result is True
        calls = " ".join(str(c) for c in mock_con.print.call_args_list)
        assert "No tasks due" in calls

    @patch(f"{MODULE}.process_due_tasks_batch", return_value={
        "recovered": 0,
        "due": 2,
        "success": 1,
        "failed": 1,
        "processed_tasks": [
            {"id": "t1", "recipient": "@flow", "task": "Check", "status": "sent"},
            {"id": "t2", "recipient": "@seedgo", "task": "Audit", "status": "failed"},
        ],
    })
    def test_mix_sent_failed(self, mock_batch, _log, _err, mock_con):
        from aipass.daemon.apps.modules.schedule import _process_due_tasks

        result = _process_due_tasks()
        assert result is True
        calls = " ".join(str(c) for c in mock_con.print.call_args_list)
        assert "1 sent" in calls
        assert "1 failed" in calls


# =============================================
# _display_task_result
# =============================================

@patch(f"{MODULE}.console")
@patch(f"{MODULE}.cli_error")
@patch(f"{MODULE}.logger")
class TestDisplayTaskResult:
    """Tests for _display_task_result per-status output."""

    def test_status_sent(self, mock_log, _err, mock_con):
        from aipass.daemon.apps.modules.schedule import _display_task_result

        _display_task_result({
            "id": "t1", "recipient": "@flow", "task": "Check plan", "status": "sent",
        })
        calls = " ".join(str(c) for c in mock_con.print.call_args_list)
        assert "OK" in calls or "Sent" in calls or "@flow" in calls

    def test_status_skipped(self, _log, mock_err, _con):
        from aipass.daemon.apps.modules.schedule import _display_task_result

        _display_task_result({
            "id": "t2", "recipient": "@seedgo", "task": "Audit", "status": "skipped",
        })
        mock_err.assert_called()

    def test_status_failed(self, _log, mock_err, _con):
        from aipass.daemon.apps.modules.schedule import _display_task_result

        _display_task_result({
            "id": "t3", "recipient": "@vera", "task": "Heartbeat", "status": "failed",
        })
        mock_err.assert_called()

    def test_status_error(self, _log, mock_err, _con):
        from aipass.daemon.apps.modules.schedule import _display_task_result

        _display_task_result({
            "id": "t4", "recipient": "@drone", "task": "Ping", "status": "error",
            "error": "timeout",
        })
        mock_err.assert_called()


# =============================================
# _send_email_via_drone
# =============================================

@patch(f"{MODULE}.logger")
class TestSendEmailViaDrone:
    """Tests for _send_email_via_drone subprocess wrapper."""

    @patch("subprocess.run")
    def test_success(self, mock_run, _log):
        from aipass.daemon.apps.modules.schedule import _send_email_via_drone

        mock_run.return_value = MagicMock(returncode=0)
        assert _send_email_via_drone("@flow", "subj", "body") is True
        mock_run.assert_called_once()

    @patch("subprocess.run", side_effect=OSError("no drone"))
    def test_failure(self, _run, _log):
        from aipass.daemon.apps.modules.schedule import _send_email_via_drone

        assert _send_email_via_drone("@flow", "subj", "body") is False
