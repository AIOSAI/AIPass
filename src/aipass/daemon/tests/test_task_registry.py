# ===================AIPASS====================
# META DATA HEADER
# Name: test_task_registry.py - Task Registry Tests
# Date: 2026-03-24
# Version: 1.0.0
# Category: daemon/tests
#
# CHANGELOG (Max 5 entries):
#   - v1.0.0 (2026-03-24): Initial creation - task_registry handler tests
#
# CODE STANDARDS:
#   - Pytest conventions
#   - Temp dir isolation (no writes to real registry)
# =============================================

"""Tests for the scheduled task registry handler."""

import json
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from aipass.daemon.apps.handlers.schedule import task_registry as _mod

parse_due_date = _mod.parse_due_date
create_task = _mod.create_task
load_tasks = _mod.load_tasks
save_tasks = _mod.save_tasks
get_due_tasks = _mod.get_due_tasks
mark_dispatching = _mod.mark_dispatching
mark_completed = _mod.mark_completed
mark_pending = _mod.mark_pending
recover_stale_dispatches = _mod.recover_stale_dispatches
delete_task = _mod.delete_task
get_task_by_id = _mod.get_task_by_id
get_pending_tasks = _mod.get_pending_tasks
ensure_lock_dir = _mod.ensure_lock_dir


@pytest.fixture(autouse=True)
def isolate_registry(tmp_path):
    """Redirect SCHEDULE_JSON_PATH to a temp dir for every test."""
    test_file = tmp_path / "schedule.json"
    original = _mod.SCHEDULE_JSON_PATH
    _mod.SCHEDULE_JSON_PATH = test_file
    yield test_file
    _mod.SCHEDULE_JSON_PATH = original


# =============================================
# DATE PARSING TESTS
# =============================================

class TestParseDueDate:
    def test_days_format(self):
        """'7d' should resolve to 7 days from today."""
        result = parse_due_date("7d")
        expected = (datetime.now().date() + timedelta(days=7)).isoformat()
        assert result == expected

    def test_days_format_single_digit(self):
        """'1d' should resolve to tomorrow."""
        result = parse_due_date("1d")
        expected = (datetime.now().date() + timedelta(days=1)).isoformat()
        assert result == expected

    def test_weeks_format(self):
        """'1w' should resolve to 1 week from today."""
        result = parse_due_date("1w")
        expected = (datetime.now().date() + timedelta(weeks=1)).isoformat()
        assert result == expected

    def test_weeks_format_multiple(self):
        """'2w' should resolve to 2 weeks from today."""
        result = parse_due_date("2w")
        expected = (datetime.now().date() + timedelta(weeks=2)).isoformat()
        assert result == expected

    def test_iso_date_format(self):
        """'2026-06-15' should pass through as-is."""
        result = parse_due_date("2026-06-15")
        assert result == "2026-06-15"

    def test_whitespace_stripped(self):
        """Leading/trailing whitespace should be stripped."""
        result = parse_due_date("  7d  ")
        expected = (datetime.now().date() + timedelta(days=7)).isoformat()
        assert result == expected

    def test_case_insensitive_days(self):
        """'7D' should work the same as '7d'."""
        result = parse_due_date("7D")
        expected = (datetime.now().date() + timedelta(days=7)).isoformat()
        assert result == expected

    def test_case_insensitive_weeks(self):
        """'2W' should work the same as '2w'."""
        result = parse_due_date("2W")
        expected = (datetime.now().date() + timedelta(weeks=2)).isoformat()
        assert result == expected

    def test_invalid_format_raises(self):
        """Unsupported format should raise ValueError."""
        with pytest.raises(ValueError, match="Invalid date format"):
            parse_due_date("next tuesday")

    def test_invalid_iso_date_raises(self):
        """Invalid calendar date in ISO format should raise ValueError."""
        with pytest.raises(ValueError, match="Invalid date"):
            parse_due_date("2026-02-30")

    def test_empty_string_raises(self):
        """Empty string should raise ValueError."""
        with pytest.raises(ValueError, match="Invalid date format"):
            parse_due_date("")

    def test_zero_days(self):
        """'0d' should resolve to today."""
        result = parse_due_date("0d")
        expected = datetime.now().date().isoformat()
        assert result == expected


# =============================================
# LOAD / SAVE TESTS
# =============================================

class TestLoadSave:
    def test_load_creates_file_if_missing(self, isolate_registry):
        """load_tasks should create schedule.json if it does not exist."""
        assert not isolate_registry.exists()
        tasks = load_tasks()
        assert tasks == []
        assert isolate_registry.exists()

    def test_load_returns_empty_on_fresh_file(self):
        """Fresh schedule.json should have no tasks."""
        tasks = load_tasks()
        assert tasks == []

    def test_save_and_load_roundtrip(self, isolate_registry):
        """save_tasks then load_tasks should return the same data."""
        sample = [{"id": "abc123", "task": "test", "status": "pending"}]
        assert save_tasks(sample) is True
        loaded = load_tasks()
        assert len(loaded) == 1
        assert loaded[0]["id"] == "abc123"

    def test_save_overwrites_existing(self, isolate_registry):
        """Saving new tasks should fully replace existing data."""
        save_tasks([{"id": "first", "status": "pending"}])
        save_tasks([{"id": "second", "status": "pending"}])
        loaded = load_tasks()
        assert len(loaded) == 1
        assert loaded[0]["id"] == "second"

    def test_load_handles_corrupt_json(self, isolate_registry):
        """Corrupt JSON should return empty list, not crash."""
        isolate_registry.parent.mkdir(parents=True, exist_ok=True)
        isolate_registry.write_text("{invalid json", encoding="utf-8")
        tasks = load_tasks()
        assert tasks == []


# =============================================
# CREATE TASK TESTS
# =============================================

class TestCreateTask:
    @patch.object(_mod.json_handler, "log_operation")
    def test_create_basic(self, mock_log):
        """Create a task and verify all fields."""
        task = create_task(
            task="Check backup health",
            due_date="7d",
            recipient="@devpulse",
            message="Verify backup systems",
        )
        assert task["task"] == "Check backup health"
        assert task["recipient"] == "@devpulse"
        assert task["message"] == "Verify backup systems"
        assert task["status"] == "pending"
        assert len(task["id"]) == 16
        assert task["id"].isalnum()
        assert task["created"] == datetime.now().date().isoformat()
        mock_log.assert_called_once_with("task_created")

    @patch.object(_mod.json_handler, "log_operation")
    def test_create_persists_to_json(self, mock_log, isolate_registry):
        """Created task should be saved to the JSON file."""
        create_task(
            task="persisted task",
            due_date="1d",
            recipient="@seedgo",
            message="msg",
        )
        raw = json.loads(isolate_registry.read_text(encoding="utf-8"))
        assert len(raw["tasks"]) == 1
        assert raw["tasks"][0]["task"] == "persisted task"

    @patch.object(_mod.json_handler, "log_operation")
    def test_create_multiple_tasks(self, mock_log):
        """Multiple tasks should accumulate in the registry."""
        create_task(task="t1", due_date="1d", recipient="@a", message="m1")
        create_task(task="t2", due_date="2d", recipient="@b", message="m2")
        tasks = load_tasks()
        assert len(tasks) == 2
        assert tasks[0]["task"] == "t1"
        assert tasks[1]["task"] == "t2"

    def test_create_invalid_date_raises(self):
        """create_task should propagate ValueError from bad due_date."""
        with pytest.raises(ValueError):
            create_task(task="bad", due_date="xyz", recipient="@a", message="m")


# =============================================
# DUE TASKS TESTS
# =============================================

class TestDueTasks:
    def test_overdue_task_returned(self, isolate_registry):
        """A pending task with a past due_date should be returned."""
        yesterday = (datetime.now().date() - timedelta(days=1)).isoformat()
        save_tasks([{
            "id": "past01",
            "due_date": yesterday,
            "status": "pending",
            "task": "overdue",
        }])
        due = get_due_tasks()
        assert len(due) == 1
        assert due[0]["id"] == "past01"

    def test_today_task_returned(self, isolate_registry):
        """A pending task due today should be returned."""
        today = datetime.now().date().isoformat()
        save_tasks([{
            "id": "today01",
            "due_date": today,
            "status": "pending",
            "task": "due today",
        }])
        due = get_due_tasks()
        assert len(due) == 1
        assert due[0]["id"] == "today01"

    def test_future_task_not_returned(self, isolate_registry):
        """A pending task with a future due_date should not be returned."""
        future = (datetime.now().date() + timedelta(days=30)).isoformat()
        save_tasks([{
            "id": "future01",
            "due_date": future,
            "status": "pending",
            "task": "future task",
        }])
        due = get_due_tasks()
        assert len(due) == 0

    def test_dispatching_task_excluded(self, isolate_registry):
        """Tasks with status 'dispatching' should not be returned."""
        yesterday = (datetime.now().date() - timedelta(days=1)).isoformat()
        save_tasks([{
            "id": "disp01",
            "due_date": yesterday,
            "status": "dispatching",
            "task": "already dispatching",
        }])
        due = get_due_tasks()
        assert len(due) == 0

    def test_completed_task_excluded(self, isolate_registry):
        """Tasks with status 'completed' should not be returned."""
        yesterday = (datetime.now().date() - timedelta(days=1)).isoformat()
        save_tasks([{
            "id": "done01",
            "due_date": yesterday,
            "status": "completed",
            "task": "done",
        }])
        due = get_due_tasks()
        assert len(due) == 0

    def test_empty_registry_returns_empty(self):
        """Empty registry should return empty list."""
        due = get_due_tasks()
        assert due == []


# =============================================
# STATUS TRANSITION TESTS
# =============================================

class TestStatusTransitions:
    def _seed_task(self, task_id: str = "abc12345abcd1234", status: str = "pending"):
        """Helper to seed a single task."""
        save_tasks([{
            "id": task_id,
            "task": "test",
            "status": status,
            "due_date": "2026-01-01",
        }])
        return task_id

    def test_mark_dispatching_success(self):
        """mark_dispatching should set status and dispatch_started."""
        tid = self._seed_task()
        assert mark_dispatching(tid) is True
        task = get_task_by_id(tid)
        assert task is not None
        assert task["status"] == "dispatching"
        assert "dispatch_started" in task

    def test_mark_dispatching_missing(self):
        """mark_dispatching returns False for nonexistent ID."""
        assert mark_dispatching("nonexistent_id__") is False

    def test_mark_completed_success(self):
        """mark_completed should set status and completed_date."""
        tid = self._seed_task()
        assert mark_completed(tid) is True
        task = get_task_by_id(tid)
        assert task is not None
        assert task["status"] == "completed"
        assert task["completed_date"] == datetime.now().date().isoformat()

    def test_mark_completed_missing(self):
        """mark_completed returns False for nonexistent ID."""
        assert mark_completed("nonexistent_id__") is False

    def test_mark_pending_success(self):
        """mark_pending should reset status and remove dispatch_started."""
        tid = self._seed_task(status="dispatching")
        # Add dispatch_started to simulate real scenario
        tasks = load_tasks()
        tasks[0]["dispatch_started"] = datetime.now().isoformat()
        save_tasks(tasks)

        assert mark_pending(tid) is True
        task = get_task_by_id(tid)
        assert task is not None
        assert task["status"] == "pending"
        assert "dispatch_started" not in task

    def test_mark_pending_missing(self):
        """mark_pending returns False for nonexistent ID."""
        assert mark_pending("nonexistent_id__") is False

    def test_full_lifecycle(self):
        """pending -> dispatching -> completed lifecycle."""
        tid = self._seed_task()
        task = get_task_by_id(tid)
        assert task is not None
        assert task["status"] == "pending"

        mark_dispatching(tid)
        task = get_task_by_id(tid)
        assert task is not None
        assert task["status"] == "dispatching"

        mark_completed(tid)
        task = get_task_by_id(tid)
        assert task is not None
        assert task["status"] == "completed"


# =============================================
# RECOVER STALE DISPATCHES TESTS
# =============================================

class TestRecoverStale:
    def test_recovers_stale_task(self, isolate_registry):
        """Task stuck in dispatching beyond max_age should be reset."""
        stale_time = (datetime.now() - timedelta(minutes=10)).isoformat()
        save_tasks([{
            "id": "stale01",
            "task": "stale dispatch",
            "status": "dispatching",
            "dispatch_started": stale_time,
            "due_date": "2026-01-01",
        }])
        recovered = recover_stale_dispatches(max_age_minutes=5)
        assert recovered == 1
        task = get_task_by_id("stale01")
        assert task is not None
        assert task["status"] == "pending"
        assert "dispatch_started" not in task

    def test_does_not_recover_recent_dispatch(self, isolate_registry):
        """Task dispatching within max_age should not be recovered."""
        recent_time = (datetime.now() - timedelta(minutes=1)).isoformat()
        save_tasks([{
            "id": "recent01",
            "task": "recent dispatch",
            "status": "dispatching",
            "dispatch_started": recent_time,
            "due_date": "2026-01-01",
        }])
        recovered = recover_stale_dispatches(max_age_minutes=5)
        assert recovered == 0
        task = get_task_by_id("recent01")
        assert task is not None
        assert task["status"] == "dispatching"

    def test_recovers_invalid_timestamp(self, isolate_registry):
        """Task with unparseable dispatch_started should be recovered."""
        save_tasks([{
            "id": "bad_ts01",
            "task": "bad timestamp",
            "status": "dispatching",
            "dispatch_started": "not-a-date",
            "due_date": "2026-01-01",
        }])
        recovered = recover_stale_dispatches(max_age_minutes=5)
        assert recovered == 1
        task = get_task_by_id("bad_ts01")
        assert task is not None
        assert task["status"] == "pending"

    def test_pending_tasks_untouched(self, isolate_registry):
        """Pending tasks should not be affected by recovery."""
        save_tasks([{
            "id": "ok01",
            "task": "normal pending",
            "status": "pending",
            "due_date": "2026-01-01",
        }])
        recovered = recover_stale_dispatches(max_age_minutes=5)
        assert recovered == 0
        task = get_task_by_id("ok01")
        assert task is not None
        assert task["status"] == "pending"

    def test_empty_registry_returns_zero(self):
        """Recovery on empty registry should return 0."""
        assert recover_stale_dispatches() == 0


# =============================================
# DELETE TASK TESTS
# =============================================

class TestDeleteTask:
    def test_delete_existing(self, isolate_registry):
        """Deleting an existing task returns True and removes it."""
        save_tasks([{"id": "del01", "task": "to delete", "status": "pending"}])
        assert delete_task("del01") is True
        assert get_task_by_id("del01") is None
        assert load_tasks() == []

    def test_delete_missing(self):
        """Deleting a nonexistent task returns False."""
        assert delete_task("nonexistent_id__") is False

    def test_delete_preserves_other_tasks(self, isolate_registry):
        """Deleting one task should leave others intact."""
        save_tasks([
            {"id": "keep01", "task": "keep this", "status": "pending"},
            {"id": "del02", "task": "delete this", "status": "pending"},
        ])
        delete_task("del02")
        remaining = load_tasks()
        assert len(remaining) == 1
        assert remaining[0]["id"] == "keep01"

    def test_delete_from_empty_registry(self):
        """Delete on empty registry should return False without error."""
        assert delete_task("anything") is False


# =============================================
# GET PENDING TASKS TESTS
# =============================================

class TestGetPendingTasks:
    """Tests for get_pending_tasks()."""

    def test_returns_only_pending(self, isolate_registry):
        """Only tasks with status 'pending' are returned."""
        save_tasks([
            {"id": "pend01", "task": "pending one", "status": "pending"},
            {"id": "pend02", "task": "pending two", "status": "pending"},
            {"id": "done01", "task": "done", "status": "completed"},
        ])
        result = get_pending_tasks()
        assert len(result) == 2
        assert all(t["status"] == "pending" for t in result)

    def test_excludes_dispatching_and_completed(self, isolate_registry):
        """Tasks with dispatching or completed status are excluded."""
        save_tasks([
            {"id": "disp01", "task": "dispatching", "status": "dispatching"},
            {"id": "done01", "task": "completed", "status": "completed"},
            {"id": "pend01", "task": "pending", "status": "pending"},
        ])
        result = get_pending_tasks()
        assert len(result) == 1
        assert result[0]["id"] == "pend01"

    def test_empty_registry_returns_empty(self):
        """Empty registry returns empty list."""
        result = get_pending_tasks()
        assert result == []


# =============================================
# ENSURE LOCK DIR TESTS
# =============================================

class TestEnsureLockDir:
    """Tests for ensure_lock_dir()."""

    def test_creates_directory_if_missing(self, isolate_registry):
        """Creates the lock directory when it does not exist."""
        lock_dir = isolate_registry.parent
        if lock_dir.exists():
            import shutil
            shutil.rmtree(lock_dir)
        assert not lock_dir.exists()

        result = ensure_lock_dir()
        assert lock_dir.exists()
        assert lock_dir.is_dir()
        assert result["path"] == str(lock_dir)

    def test_returns_dict_with_path_key(self, isolate_registry):
        """Return value is a dict containing the 'path' key."""
        result = ensure_lock_dir()
        assert isinstance(result, dict)
        assert "path" in result
        assert isinstance(result["path"], str)
