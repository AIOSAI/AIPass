# =================== AIPass ====================
# Name: test_scheduler_bot.py
# Description: Tests for TDPLAN-0008 Phase 1 — scheduler bot daemon layer
# Version: 1.1.0
# Created: 2026-06-25
# Modified: 2026-09-28
# =============================================

"""Tests for apps/modules/queue.py, apps/modules/run.py and handlers/schedule/ — TDPLAN-0008 Phase 1."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that apps/modules/queue.py, apps/modules/run.py and telegram_notifier.py parse
# seedgo: no-test-needed(generated) — _print_rich_table's column layout; only the --json contract is frozen

import importlib.util
import json
from datetime import datetime
from pathlib import Path
from unittest.mock import ANY, patch

import pytest

from aipass.daemon.apps.handlers.cli.arg_gate import UnknownArgument
from aipass.daemon.apps.handlers.schedule.runstate import (
    update_job_runstate,
    record_job_failure,
)
from aipass.daemon.apps.handlers.schedule.telegram_notifier import (
    notify_triggered,
    notify_complete,
    notify_error,
)
from aipass.daemon.apps.modules import queue as queue_mod
from aipass.daemon.apps.modules.actions import handle_command as act_cmd
from aipass.daemon.apps.modules.queue import handle_command
from aipass.daemon.apps.modules.run import OUTCOME_FIRED, run_tick
from aipass.daemon.apps.modules.schedule import handle_command as sched_cmd


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


def _queue_json(monkeypatch, capsys, jobs, runstate):
    """What `drone @daemon queue --json` prints for these jobs and this runstate, parsed."""
    monkeypatch.setattr(queue_mod, "discover_jobs", lambda: jobs)
    monkeypatch.setattr(queue_mod, "load_runstate", lambda: runstate)
    capsys.readouterr()
    assert handle_command("queue", ["--json"]) is True
    return json.loads(capsys.readouterr().out)


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

    def test_completed_once_excluded_from_queue(self, once_job, monkeypatch, capsys):
        """Completed once jobs are filtered out of the queue view. Mutant killed: the completed skip removed."""
        runstate = {
            "jobs": {
                "@api/data-check": {
                    "completed": "2026-06-25T10:00:00",
                    "last_run": "2026-06-25T10:00:00",
                }
            }
        }
        assert _queue_json(monkeypatch, capsys, [once_job], runstate)["jobs"] == []


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

    def test_schema_structure(self, interval_job, monkeypatch, capsys):
        """JSON output has generated_at, count, jobs array. Mutant killed: count pinned to 0."""
        output = _queue_json(monkeypatch, capsys, [interval_job], {"jobs": {}})
        assert "generated_at" in output
        assert "count" in output
        assert isinstance(output["jobs"], list)
        assert output["count"] == len(output["jobs"])

    def test_job_fields(self, interval_job, monkeypatch, capsys):
        """Each job in output has all frozen-schema fields."""
        job_out = _queue_json(monkeypatch, capsys, [interval_job], {"jobs": {}})["jobs"][0]
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
        # The floor. The loop's iterable is a literal one assignment above, but
        # nothing in the unit says how many names it must hold — eleven is the
        # frozen schema this test is named for, counted from the list.
        assert len(required_fields) == 11, f"the frozen schema is eleven fields, this list names {len(required_fields)}"
        for field in required_fields:
            assert field in job_out, f"Missing field: {field}"

    def test_a_command_job_previews_its_command_in_the_same_schema(self, interval_job, monkeypatch, capsys):
        """DPLAN-0338: a command job has no prompt, so the preview names what it runs. Keys unchanged."""
        command = {key: value for key, value in interval_job.items() if key != "prompt"}
        command.update(id="sweep", command="drone rm --stale 10d ../..", branch_path="unused", wake={})
        wake_entry, command_entry = _queue_json(monkeypatch, capsys, [interval_job, command], {"jobs": {}})["jobs"]
        assert command_entry["prompt_preview"] == "command: drone rm --stale 10d ../.."
        assert set(command_entry) == set(wake_entry), "a command job may not change the frozen schema's keys"

    def test_type_values(self, once_job, interval_job, monkeypatch, capsys):
        """Type field matches schedule type. Mutant killed: type pinned to "interval"."""
        once_entry, interval_entry = _queue_json(monkeypatch, capsys, [once_job, interval_job], {"jobs": {}})["jobs"]
        assert once_entry["type"] == "once"
        assert interval_entry["type"] == "interval"

    def test_schedule_human_formats(self, interval_job, monkeypatch, capsys):
        """schedule_human renders each type correctly. Mutant killed: hourly drops its colon."""
        schedules = {
            "once": {"type": "once", "due_date": "2026-07-02"},
            "daily": {"type": "daily", "time": "04:00"},
            "hourly": {"type": "hourly", "time": "30"},
            "two-hours": {"type": "interval", "interval_minutes": 120},
            "half-hour": {"type": "interval", "interval_minutes": 30},
        }
        jobs = [dict(interval_job, id=job_id, schedule=schedule) for job_id, schedule in schedules.items()]
        rendered = {
            row["id"]: row["schedule_human"] for row in _queue_json(monkeypatch, capsys, jobs, {"jobs": {}})["jobs"]
        }
        assert rendered == {
            "once": "2026-07-02",
            "daily": "daily @ 04:00",
            "hourly": "hourly @ :30",
            "two-hours": "every 2h",
            "half-hour": "every 30m",
        }

    @pytest.mark.parametrize("bad_interval", ["sixty", None, True], ids=["text", "null", "bool"])
    def test_an_unreadable_interval_renders_its_row(self, interval_job, monkeypatch, capsys, bad_interval):
        """A text or null interval_minutes raised on `mins >= 60` and took the whole queue view down.

        The row renders and names the raw value as unreadable (DPLAN-0354 leg 3, item 3).
        Mutant killed: _schedule_human's number check removed.
        """
        job = dict(interval_job, schedule={"type": "interval", "interval_minutes": bad_interval})
        (row,) = _queue_json(monkeypatch, capsys, [job], {"jobs": {}})["jobs"]
        assert row["schedule_human"] == f"every ? (interval_minutes {bad_interval!r} unreadable)"

    def test_an_absent_interval_reads_as_the_hour_the_scheduler_uses(self, interval_job, monkeypatch, capsys):
        """An interval job with no interval_minutes fires every 60 minutes; the queue said "every 0m".

        The queue now reads the same default the scheduler reads (DPLAN-0354 leg 4).
        Mutant killed: the queue's default put back to 0.
        """
        job = dict(interval_job, schedule={"type": "interval"})
        (row,) = _queue_json(monkeypatch, capsys, [job], {"jobs": {}})["jobs"]
        assert row["schedule_human"] == "every 1h"


# ── Test 5: empty tick emits ZERO telegram calls ──


class TestEmptyTickNoNotify:
    """Verify no telegram calls on empty ticks (no due jobs)."""

    @patch("aipass.daemon.apps.modules.run.discover_jobs", return_value=[])
    @patch("aipass.daemon.apps.handlers.schedule.telegram_notifier._send")
    def test_no_jobs_no_send(self, mock_send, mock_discover):
        """Empty tick with no discovered jobs makes zero telegram calls."""
        run_tick(dry_run=True)
        mock_send.assert_not_called()

    @patch("aipass.daemon.apps.modules.run.discover_jobs")
    @patch("aipass.daemon.apps.modules.run.load_runstate")
    @patch("aipass.daemon.apps.handlers.schedule.telegram_notifier._send")
    def test_no_due_jobs_no_send(self, mock_send, mock_rs, mock_discover):
        """Tick with jobs but none due makes zero telegram calls."""
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
        """Exception in send_telegram_notification is caught, returns False. Mutant killed: _send re-raises."""
        assert notify_triggered("@x", "y") is False
        mock_notifier.assert_called_once()

    @patch("aipass.daemon.apps.modules.run.save_runstate")
    @patch("aipass.daemon.apps.modules.run.record_job_failure")
    @patch("aipass.daemon.apps.modules.run.update_job_runstate")
    @patch("aipass.daemon.apps.modules.run.discover_jobs")
    @patch("aipass.daemon.apps.modules.run.load_runstate", return_value={"jobs": {}})
    def test_fire_continues_when_notify_fails(self, mock_rs, mock_discover, mock_update, mock_fail, mock_save):
        """Job fires and records status even when telegram is down. Mutant killed: owner and id swapped."""
        schedule = {"type": "interval", "interval_minutes": 1}
        mock_discover.return_value = [
            {
                "owner": "@commons",
                "id": "test",
                "enabled": True,
                "schedule": schedule,
                "wake": {"fresh": True},
                "prompt": "test",
                "notify": True,
            }
        ]

        with patch("aipass.daemon.apps.modules.run._fire_job", return_value=(OUTCOME_FIRED, "")):
            results = run_tick()
            assert results["fired"] == 1
        mock_update.assert_called_once_with(ANY, "@commons", "test", schedule, caught_up=ANY)
        mock_fail.assert_not_called()
        mock_save.assert_called()


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
        assert importlib.util.find_spec("aipass.daemon.apps.handlers.schedule.task_registry") is None

    def test_actions_registry_not_importable(self):
        """actions_registry handler is gone from the live import path."""
        assert importlib.util.find_spec("aipass.daemon.apps.handlers.actions.actions_registry") is None

    def test_schedule_module_retired(self):
        """Bare `schedule` shows the migration notice; a retired subcommand refuses.

        The notice is still the right GUIDANCE and still prints — but `schedule
        create test` did not create anything, and exiting 0 told the caller's
        `&&` that it had (FPLAN-0492 wave 2b).
        """
        assert sched_cmd("schedule", []) is True
        with pytest.raises(UnknownArgument) as exc:
            sched_cmd("schedule", ["create", "test"])
        assert exc.value.token == "create"

    def test_actions_module_retired(self):
        """Bare `actions` shows the migration notice; a retired subcommand refuses."""
        assert act_cmd("actions", []) is True
        with pytest.raises(UnknownArgument) as exc:
            act_cmd("actions", ["list"])
        assert exc.value.token == "list"

    def test_queue_command_wired(self):
        """drone @daemon queue is routable."""
        assert handle_command("queue", []) is True
        assert handle_command("notqueue", []) is False
