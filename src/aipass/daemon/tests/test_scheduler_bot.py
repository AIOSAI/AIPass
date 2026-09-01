# =================== AIPass ====================
# Name: test_scheduler_bot.py
# Description: Tests for TDPLAN-0008 Phase 1 — scheduler bot daemon layer
# Version: 1.0.0
# Created: 2026-06-25
# Modified: 2026-06-25
# =============================================

"""Tests for TDPLAN-0008 Phase 1: status capture, queue view, lifecycle notifications, archive."""

from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from aipass.daemon.apps.handlers.schedule.runstate import (
    update_job_runstate,
    record_job_failure,
)
from aipass.daemon.apps.handlers.schedule.telegram_notifier import (
    notify_triggered,
    notify_complete,
    notify_error,
)
from aipass.daemon.apps.modules.queue import (
    _build_queue,
    _build_json_output,
    _schedule_human,
    handle_command,
)


# ── Fixtures ──────────────────────────────────────────


@pytest.fixture
def once_job():
    """A once-type job that fires on due_date."""
    return {
        "owner": "@api",
        "id": "data-check",
        "enabled": True,
        "schedule": {"type": "once", "due_date": datetime.now().strftime("%Y-%m-%d")},
        "wake": {"fresh": True, "model": "haiku"},
        "prompt": "Check the live data and report back.",
    }


@pytest.fixture
def interval_job():
    """An interval-type job."""
    return {
        "owner": "@commons",
        "id": "rotation",
        "enabled": True,
        "schedule": {"type": "interval", "interval_minutes": 120},
        "wake": {"fresh": True},
        "prompt": "Rotate community content.",
    }


# ── Test 1: once job fires on due_date, then marks completed ───


class TestOnceJobLifecycle:
    """Verify once jobs fire on/after due_date and mark completed."""

    def test_fires_on_due_date(self, once_job):
        """Once job with today's due_date gets last_status=success + completed."""
        runstate = {"jobs": {}}
        update_job_runstate(runstate, "@api", "data-check", once_job["schedule"])
        entry = runstate["jobs"]["@api/data-check"]
        assert entry["last_status"] == "success"
        assert "completed" in entry
        assert entry["last_success_at"] is not None
        assert entry["last_error"] is None

    def test_completed_once_excluded_from_queue(self, once_job):
        """Completed once jobs are filtered out of the queue view."""
        runstate = {
            "jobs": {
                "@api/data-check": {
                    "completed": "2026-06-25T10:00:00",
                    "last_run": "2026-06-25T10:00:00",
                }
            }
        }
        entries = _build_queue([once_job], runstate)
        assert len(entries) == 0


# ── Test 2: fire emits notify_triggered then notify_complete; failed emits notify_error ──


class TestLifecycleNotifications:
    """Verify telegram notifications fire on real job events."""

    @patch("aipass.daemon.apps.handlers.schedule.telegram_notifier._send")
    def test_triggered_sends_running(self, mock_send):
        """notify_triggered sends running ping."""
        mock_send.return_value = True
        result = notify_triggered("@api", "data-check")
        assert result is True
        call_msg = mock_send.call_args[0][0]
        assert "@api/data-check" in call_msg
        assert "running" in call_msg

    @patch("aipass.daemon.apps.handlers.schedule.telegram_notifier._send")
    def test_complete_sends_dispatched(self, mock_send):
        """notify_complete sends dispatched ping with summary."""
        mock_send.return_value = True
        result = notify_complete("@api", "data-check", "Agent spawned OK")
        assert result is True
        call_msg = mock_send.call_args[0][0]
        assert "dispatched" in call_msg
        assert "Agent spawned OK" in call_msg

    @patch("aipass.daemon.apps.handlers.schedule.telegram_notifier._send")
    def test_error_sends_failed(self, mock_send):
        """notify_error sends failed ping with error detail."""
        mock_send.return_value = True
        result = notify_error("@api", "data-check", "timeout")
        assert result is True
        call_msg = mock_send.call_args[0][0]
        assert "FAILED" in call_msg
        assert "timeout" in call_msg


# ── Test 3: runstate records last_status + last_error on both paths ──


class TestRunstateStatusCapture:
    """Verify runstate tracks status on success AND failure."""

    def test_success_records_status(self):
        """Successful fire sets last_status=success, last_success_at, clears error."""
        runstate = {"jobs": {}}
        schedule = {"type": "interval", "interval_minutes": 60}
        update_job_runstate(runstate, "@commons", "test", schedule)
        entry = runstate["jobs"]["@commons/test"]
        assert entry["last_status"] == "success"
        assert entry["last_success_at"] is not None
        assert entry["last_error"] is None

    def test_failure_records_status(self):
        """Failed fire sets last_status=failed, last_failure_at, last_error."""
        runstate = {"jobs": {}}
        record_job_failure(runstate, "@commons", "test", "branch locked")
        entry = runstate["jobs"]["@commons/test"]
        assert entry["last_status"] == "failed"
        assert entry["last_failure_at"] is not None
        assert entry["last_error"] == "branch locked"

    def test_failure_preserves_last_run(self):
        """Failure path still records last_run timestamp."""
        runstate = {"jobs": {}}
        record_job_failure(runstate, "@x", "y", "err")
        entry = runstate["jobs"]["@x/y"]
        assert "last_run" in entry

    def test_error_truncated(self):
        """Long error messages are truncated to 500 chars."""
        runstate = {"jobs": {}}
        record_job_failure(runstate, "@x", "y", "x" * 1000)
        entry = runstate["jobs"]["@x/y"]
        assert len(entry["last_error"]) == 500


# ── Test 4: queue --json returns frozen schema ──


class TestQueueJsonSchema:
    """Verify queue --json output matches the frozen contract."""

    def test_schema_structure(self, interval_job):
        """JSON output has generated_at, count, jobs array."""
        runstate = {"jobs": {}}
        entries = _build_queue([interval_job], runstate)
        output = _build_json_output(entries)
        assert "generated_at" in output
        assert "count" in output
        assert isinstance(output["jobs"], list)
        assert output["count"] == len(output["jobs"])

    def test_job_fields(self, interval_job):
        """Each job in output has all frozen-schema fields."""
        runstate = {"jobs": {}}
        entries = _build_queue([interval_job], runstate)
        job_out = entries[0]
        required_fields = [
            "owner",
            "id",
            "enabled",
            "type",
            "schedule_human",
            "next_run",
            "last_run",
            "last_status",
            "last_error",
            "prompt_preview",
            "wake",
        ]
        for field in required_fields:
            assert field in job_out, f"Missing field: {field}"

    def test_type_values(self, once_job, interval_job):
        """Type field matches schedule type."""
        runstate = {"jobs": {}}
        once_entries = _build_queue([once_job], runstate)
        assert once_entries[0]["type"] == "once"
        interval_entries = _build_queue([interval_job], runstate)
        assert interval_entries[0]["type"] == "interval"

    def test_schedule_human_formats(self):
        """schedule_human renders each type correctly."""
        assert _schedule_human({"schedule": {"type": "once", "due_date": "2026-07-02"}}) == "2026-07-02"
        assert _schedule_human({"schedule": {"type": "daily", "time": "04:00"}}) == "daily @ 04:00"
        assert _schedule_human({"schedule": {"type": "hourly", "time": "30"}}) == "hourly @ :30"
        assert _schedule_human({"schedule": {"type": "interval", "interval_minutes": 120}}) == "every 2h"
        assert _schedule_human({"schedule": {"type": "interval", "interval_minutes": 30}}) == "every 30m"


# ── Test 5: empty tick emits ZERO telegram calls ──


class TestEmptyTickNoNotify:
    """Verify no telegram calls on empty ticks (no due jobs)."""

    @patch("aipass.daemon.apps.modules.run.discover_jobs", return_value=[])
    @patch("aipass.daemon.apps.handlers.schedule.telegram_notifier._send")
    def test_no_jobs_no_send(self, mock_send, mock_discover):
        """Empty tick with no discovered jobs makes zero telegram calls."""
        from aipass.daemon.apps.modules.run import run_tick

        run_tick(dry_run=True)
        mock_send.assert_not_called()

    @patch("aipass.daemon.apps.modules.run.discover_jobs")
    @patch("aipass.daemon.apps.modules.run.load_runstate")
    @patch("aipass.daemon.apps.handlers.schedule.telegram_notifier._send")
    def test_no_due_jobs_no_send(self, mock_send, mock_rs, mock_discover):
        """Tick with jobs but none due makes zero telegram calls."""
        from aipass.daemon.apps.modules.run import run_tick

        mock_discover.return_value = [
            {
                "owner": "@commons",
                "id": "test",
                "enabled": True,
                "schedule": {"type": "interval", "interval_minutes": 9999},
                "wake": {},
                "prompt": "test",
            }
        ]
        mock_rs.return_value = {"jobs": {"@commons/test": {"last_run": datetime.now().isoformat()}}}
        run_tick()
        mock_send.assert_not_called()


# ── Test 6: send is fail-soft ──


class TestFailSoft:
    """Verify telegram send failures don't block job firing."""

    @patch("aipass.daemon.apps.handlers.schedule.telegram_notifier._send")
    def test_send_returns_false_on_failure(self, mock_send):
        """When _send fails, notify functions return False gracefully."""
        mock_send.return_value = False
        assert notify_triggered("@x", "y") is False
        assert notify_complete("@x", "y", "s") is False
        assert notify_error("@x", "y", "e") is False

    @patch(
        "aipass.skills.lib.telegram.apps.handlers.notifier.send_telegram_notification",
        side_effect=Exception("connection refused"),
    )
    def test_exception_caught(self, mock_notifier):
        """Exception in send_telegram_notification is caught, returns False."""
        from aipass.daemon.apps.handlers.schedule.telegram_notifier import _send

        result = _send("test message")
        assert result is False

    @patch("aipass.daemon.apps.modules.run.save_runstate")
    @patch("aipass.daemon.apps.modules.run.record_job_failure")
    @patch("aipass.daemon.apps.modules.run.update_job_runstate")
    @patch("aipass.daemon.apps.modules.run.discover_jobs")
    @patch("aipass.daemon.apps.modules.run.load_runstate", return_value={"jobs": {}})
    def test_fire_continues_when_notify_fails(self, mock_rs, mock_discover, mock_update, mock_fail, mock_save):
        """Job fires and records status even when telegram is down."""
        from aipass.daemon.apps.modules.run import run_tick

        mock_discover.return_value = [
            {
                "owner": "@commons",
                "id": "test",
                "enabled": True,
                "schedule": {"type": "interval", "interval_minutes": 1},
                "wake": {"fresh": True},
                "prompt": "test",
                "notify": True,
            }
        ]

        from aipass.daemon.apps.modules.run import OUTCOME_FIRED

        with patch("aipass.daemon.apps.modules.run._fire_job", return_value=(OUTCOME_FIRED, "")):
            results = run_tick()
            assert results["fired"] == 1


# ── Test 7: dormant registries archived ──


class TestDormantArchived:
    """Verify dormant registries are archived and no live code references them."""

    def test_original_data_files_gone(self):
        """Original data files no longer at daemon_json/ root."""
        daemon_root = Path(__file__).resolve().parents[1]
        assert not (daemon_root / "daemon_json" / "schedule.json").exists()
        assert not (daemon_root / "daemon_json" / "actions_registry.json").exists()

    def test_task_registry_not_importable(self):
        """task_registry handler is gone from the live import path."""
        with pytest.raises(ImportError):
            from aipass.daemon.apps.handlers.schedule.task_registry import load_tasks  # type: ignore[import-not-found] # noqa: F401

    def test_actions_registry_not_importable(self):
        """actions_registry handler is gone from the live import path."""
        with pytest.raises(ImportError):
            from aipass.daemon.apps.handlers.actions.actions_registry import load_registry  # type: ignore[import-not-found] # noqa: F401

    def test_schedule_module_retired(self):
        """Schedule module handle_command shows retirement notice, not old CRUD."""
        from aipass.daemon.apps.modules.schedule import handle_command as sched_cmd

        assert sched_cmd("schedule", []) is True
        assert sched_cmd("schedule", ["create", "test"]) is True

    def test_actions_module_retired(self):
        """Actions module handle_command shows retirement notice, not old CRUD."""
        from aipass.daemon.apps.modules.actions import handle_command as act_cmd

        assert act_cmd("actions", []) is True
        assert act_cmd("actions", ["list"]) is True

    def test_queue_command_wired(self):
        """drone @daemon queue is routable."""
        assert handle_command("queue", []) is True
        assert handle_command("notqueue", []) is False
