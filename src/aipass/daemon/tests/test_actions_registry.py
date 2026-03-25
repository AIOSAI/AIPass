# ===================AIPASS====================
# META DATA HEADER
# Name: test_actions_registry.py - Action Registry Tests
# Date: 2026-03-02
# Version: 1.1.0
# Category: daemon/tests
#
# CHANGELOG (Max 5 entries):
#   - v1.1.0 (2026-03-07): Adapted for AIPass public repo
#     * Removed sys.path manipulation, uses package imports
#   - v1.0.0 (2026-03-02): Initial creation - DPLAN-043 tests
#
# CODE STANDARDS:
#   - Pytest conventions
#   - Temp dir isolation (no writes to real registry)
# =============================================

"""Tests for the action registry handler."""

import json
from datetime import datetime, timedelta

import pytest

from aipass.daemon.apps.handlers.actions import actions_registry as _reg_mod

create_action = _reg_mod.create_action
get_action = _reg_mod.get_action
list_actions = _reg_mod.list_actions
toggle_action = _reg_mod.toggle_action
delete_action = _reg_mod.delete_action
update_last_run = _reg_mod.update_last_run
mark_reminder_completed = _reg_mod.mark_reminder_completed
is_action_due = _reg_mod.is_action_due
calc_next_run = _reg_mod.calc_next_run
next_due_str = _reg_mod.next_due_str


@pytest.fixture(autouse=True)
def clean_registry(tmp_path):
    """Isolate REGISTRY_FILE to a temp dir for every test."""
    test_registry = tmp_path / "actions_registry.json"
    original = _reg_mod.REGISTRY_FILE
    _reg_mod.REGISTRY_FILE = test_registry
    yield test_registry
    _reg_mod.REGISTRY_FILE = original


# =============================================
# CRUD TESTS
# =============================================

class TestCreate:
    def test_create_action_basic(self, clean_registry):
        """Create a simple schedule action and verify fields."""
        action = create_action(
            name="test_audit",
            action_type="schedule",
            schedule_type="daily",
            target_branch="@seed",
            prompt="Run audit",
            time="04:00",
            fresh=True,
            max_turns=20,
        )
        assert action["id"] == "0001"
        assert action["name"] == "test_audit"
        assert action["type"] == "schedule"
        assert action["schedule_type"] == "daily"
        assert action["time"] == "04:00"
        assert action["target_branch"] == "@seed"
        assert action["enabled"] is True
        assert action["last_run"] is None
        assert action["completed"] is None

    def test_create_sequential_ids(self, clean_registry):
        """IDs should be sequential: 0001, 0002, 0003..."""
        a1 = create_action(name="first", action_type="schedule", schedule_type="daily")
        a2 = create_action(name="second", action_type="schedule", schedule_type="daily")
        a3 = create_action(name="third", action_type="reminder", schedule_type="once")
        assert a1["id"] == "0001"
        assert a2["id"] == "0002"
        assert a3["id"] == "0003"

    def test_create_reminder(self, clean_registry):
        """Create a one-shot reminder action."""
        action = create_action(
            name="Check VERA progress",
            action_type="reminder",
            schedule_type="once",
            target_branch="@dev_central",
            prompt="Check VERA progress",
            due_date="2026-03-11",
        )
        assert action["type"] == "reminder"
        assert action["schedule_type"] == "once"
        assert action["due_date"] == "2026-03-11"

    def test_create_persists_to_json(self, clean_registry):
        """Action should be persisted to the JSON file."""
        create_action(name="persisted", action_type="schedule", schedule_type="daily")
        data = json.loads(clean_registry.read_text())
        assert len(data["actions"]) == 1
        assert data["actions"][0]["name"] == "persisted"
        assert data["next_id"] == 2


class TestGet:
    def test_get_existing(self, clean_registry):
        """Get an action by ID."""
        create_action(name="findme", action_type="schedule", schedule_type="daily")
        action = get_action("0001")
        assert action is not None
        assert action["name"] == "findme"

    def test_get_missing(self, clean_registry):
        """Get returns None for nonexistent ID."""
        assert get_action("9999") is None


class TestList:
    def test_list_all(self, clean_registry):
        """List returns all non-completed actions."""
        create_action(name="a", action_type="schedule", schedule_type="daily")
        create_action(name="b", action_type="schedule", schedule_type="hourly")
        actions = list_actions()
        assert len(actions) == 2

    def test_list_excludes_completed(self, clean_registry):
        """Completed reminders should be excluded by default."""
        create_action(name="done", action_type="reminder", schedule_type="once",
                       due_date="2026-01-01")
        mark_reminder_completed("0001")
        assert len(list_actions()) == 0
        assert len(list_actions(include_completed=True)) == 1


class TestToggle:
    def test_toggle_off(self, clean_registry):
        """Toggle an action off."""
        create_action(name="toggleme", action_type="schedule", schedule_type="daily")
        assert toggle_action("0001", False) is True
        action = get_action("0001")
        assert action is not None
        assert action["enabled"] is False

    def test_toggle_on(self, clean_registry):
        """Toggle an action back on."""
        create_action(name="toggleme", action_type="schedule", schedule_type="daily",
                       enabled=False)
        assert toggle_action("0001", True) is True
        action = get_action("0001")
        assert action is not None
        assert action["enabled"] is True

    def test_toggle_missing(self, clean_registry):
        """Toggle returns False for nonexistent ID."""
        assert toggle_action("9999", True) is False


class TestDelete:
    def test_delete_existing(self, clean_registry):
        """Delete an action by ID."""
        create_action(name="deleteme", action_type="schedule", schedule_type="daily")
        assert delete_action("0001") is True
        assert get_action("0001") is None

    def test_delete_missing(self, clean_registry):
        """Delete returns False for nonexistent ID."""
        assert delete_action("9999") is False


# =============================================
# DUE CHECKING TESTS
# =============================================

class TestIsDue:
    def test_daily_due_at_correct_time(self, clean_registry):
        """Daily action is due when current time matches."""
        now = datetime.now()
        action = {
            "enabled": True,
            "completed": None,
            "schedule_type": "daily",
            "time": f"{now.hour:02d}:{now.minute:02d}",
            "last_run": None,
        }
        assert is_action_due(action) is True

    def test_daily_not_due_wrong_time(self, clean_registry):
        """Daily action is not due at wrong time (12 hours away from now)."""
        from datetime import datetime
        now = datetime.now()
        # Pick a time 12 hours away — always outside the 15-min fuzzy window
        far_hour = (now.hour + 12) % 24
        action = {
            "enabled": True,
            "completed": None,
            "schedule_type": "daily",
            "time": f"{far_hour:02d}:00",
            "last_run": None,
        }
        assert is_action_due(action) is False

    def test_daily_not_due_already_ran_today(self, clean_registry):
        """Daily action not due if already ran today."""
        now = datetime.now()
        action = {
            "enabled": True,
            "completed": None,
            "schedule_type": "daily",
            "time": f"{now.hour:02d}:{now.minute:02d}",
            "last_run": now.isoformat(),
        }
        assert is_action_due(action) is False

    def test_interval_due_never_run(self, clean_registry):
        """Interval action is due if never run before."""
        action = {
            "enabled": True,
            "completed": None,
            "schedule_type": "interval",
            "interval_minutes": 60,
            "last_run": None,
        }
        assert is_action_due(action) is True

    def test_interval_due_enough_time_elapsed(self, clean_registry):
        """Interval action is due when enough time has passed."""
        past = (datetime.now() - timedelta(minutes=120)).isoformat()
        action = {
            "enabled": True,
            "completed": None,
            "schedule_type": "interval",
            "interval_minutes": 60,
            "last_run": past,
        }
        assert is_action_due(action) is True

    def test_interval_not_due_too_soon(self, clean_registry):
        """Interval action is not due when too little time has passed."""
        recent = (datetime.now() - timedelta(minutes=5)).isoformat()
        action = {
            "enabled": True,
            "completed": None,
            "schedule_type": "interval",
            "interval_minutes": 60,
            "last_run": recent,
        }
        assert is_action_due(action) is False

    def test_once_due_past_date(self, clean_registry):
        """Reminder is due when due_date is in the past."""
        action = {
            "enabled": True,
            "completed": None,
            "schedule_type": "once",
            "due_date": "2026-01-01",
        }
        assert is_action_due(action) is True

    def test_once_not_due_future_date(self, clean_registry):
        """Reminder is not due when due_date is in the future."""
        action = {
            "enabled": True,
            "completed": None,
            "schedule_type": "once",
            "due_date": "2099-12-31",
        }
        assert is_action_due(action) is False

    def test_disabled_never_due(self, clean_registry):
        """Disabled action is never due."""
        action = {
            "enabled": False,
            "completed": None,
            "schedule_type": "interval",
            "interval_minutes": 1,
            "last_run": None,
        }
        assert is_action_due(action) is False

    def test_completed_never_due(self, clean_registry):
        """Completed action is never due."""
        action = {
            "enabled": True,
            "completed": "2026-03-01T12:00:00",
            "schedule_type": "once",
            "due_date": "2026-01-01",
        }
        assert is_action_due(action) is False


# =============================================
# NEXT RUN TESTS
# =============================================

class TestCalcNextRun:
    def test_daily_next_run(self, clean_registry):
        """Daily action calculates next run correctly."""
        action = {"schedule_type": "daily", "time": "04:00", "last_run": None}
        result = calc_next_run(action)
        assert result is not None
        assert "04:00:00" in result

    def test_interval_next_run(self, clean_registry):
        """Interval action calculates next run from last_run + interval."""
        last = datetime.now().isoformat()
        action = {"schedule_type": "interval", "interval_minutes": 60, "last_run": last}
        result = calc_next_run(action)
        assert result is not None

    def test_once_next_run(self, clean_registry):
        """Reminder returns due_date as next run."""
        action = {"schedule_type": "once", "due_date": "2026-03-11", "completed": None}
        assert calc_next_run(action) == "2026-03-11"


class TestNextDueStr:
    def test_daily_str(self, clean_registry):
        action = {"schedule_type": "daily", "time": "04:00"}
        assert next_due_str(action) == "daily @ 04:00"

    def test_hourly_str(self, clean_registry):
        action = {"schedule_type": "hourly", "time": "30"}
        assert next_due_str(action) == "hourly @ :30"

    def test_once_str(self, clean_registry):
        action = {"schedule_type": "once", "due_date": "2026-03-11"}
        assert next_due_str(action) == "2026-03-11"


# =============================================
# UPDATE TESTS
# =============================================

class TestUpdateLastRun:
    def test_update_last_run(self, clean_registry):
        """Update last_run sets timestamp and recalculates next_run."""
        create_action(name="test", action_type="schedule", schedule_type="interval",
                       interval_minutes=60)
        ts = "2026-03-02T12:00:00"
        assert update_last_run("0001", ts) is True
        action = get_action("0001")
        assert action is not None
        assert action["last_run"] == ts
        assert action["next_run"] is not None


class TestMarkCompleted:
    def test_mark_reminder_completed(self, clean_registry):
        """Marking a reminder completed sets completed timestamp and disables it."""
        create_action(name="reminder", action_type="reminder", schedule_type="once",
                       due_date="2026-03-01")
        assert mark_reminder_completed("0001") is True
        action = get_action("0001")
        assert action is not None
        assert action["completed"] is not None
        assert action["enabled"] is False
