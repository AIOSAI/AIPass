"""Tests for daemon runstate tracking and due-logic."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from aipass.daemon.apps.handlers.schedule import runstate as runstate_mod
from aipass.daemon.apps.handlers.schedule.runstate import (
    load_runstate,
    save_runstate,
    job_key,
    get_job_state,
    is_job_due,
    update_job_runstate,
    prune_orphans,
    _is_daily_due,
    _is_hourly_due,
    _is_interval_due,
    _is_once_due,
    _already_ran_today,
    _already_ran_this_hour,
)


# ── Fixtures ──────────────────────────────────────────


@pytest.fixture(autouse=True)
def _mute_log_operation(monkeypatch):
    """Keep every test here off the real daemon_json log file.

    update_job_runstate/record_job_failure call json_handler.log_operation,
    which read-modify-writes a shared repo file — xdist workers racing on it
    produce empty-read JSONDecodeError flakes. Patched on the runstate module
    object so the functions imported above resolve the mock via their globals.
    """
    monkeypatch.setattr(runstate_mod, "json_handler", MagicMock(log_operation=MagicMock(return_value=True)))


@pytest.fixture
def tmp_runstate(tmp_path):
    """Patch RUNSTATE_FILE to a temp path."""
    rf = tmp_path / "daemon_runstate.json"
    with patch("aipass.daemon.apps.handlers.schedule.runstate.RUNSTATE_FILE", rf):
        yield rf


@pytest.fixture
def interval_job():
    return {
        "owner": "@commons",
        "id": "wake-test",
        "enabled": True,
        "schedule": {"type": "interval", "interval_minutes": 60},
        "wake": {"fresh": True},
        "prompt": "test",
    }


@pytest.fixture
def daily_job():
    return {
        "owner": "@seedgo",
        "id": "daily-audit",
        "enabled": True,
        "schedule": {"type": "daily", "time": "04:00"},
        "wake": {"fresh": True},
        "prompt": "audit",
    }


# ── job_key / get_job_state ──────────────────────────


class TestJobKey:
    def test_composite_key(self):
        assert job_key("@commons", "wake-test") == "@commons/wake-test"

    def test_get_existing_state(self):
        runstate = {"jobs": {"@commons/wake-test": {"last_run": "2026-01-01T00:00:00"}}}
        state = get_job_state(runstate, "@commons", "wake-test")
        assert state["last_run"] == "2026-01-01T00:00:00"

    def test_get_missing_state(self):
        runstate = {"jobs": {}}
        state = get_job_state(runstate, "@commons", "wake-test")
        assert state == {}


# ── load/save runstate ───────────────────────────────


class TestRunstateIO:
    def test_load_missing_file(self, tmp_runstate):
        data = load_runstate()
        assert data == {"version": 1, "jobs": {}}

    def test_save_and_load(self, tmp_runstate):
        data = {"version": 1, "jobs": {"@x/y": {"last_run": "2026-01-01T00:00:00"}}}
        assert save_runstate(data) is True
        loaded = load_runstate()
        assert loaded["jobs"]["@x/y"]["last_run"] == "2026-01-01T00:00:00"

    def test_load_corrupted_json(self, tmp_runstate):
        tmp_runstate.write_text("{bad json")
        data = load_runstate()
        assert data == {"version": 1, "jobs": {}}

    def test_a_read_modify_write_cycle_does_not_overwrite_the_other_jobs(self, tmp_runstate):
        """Recording one job's run must leave every other job's history alone.

        The no_overwrite claim daemon actually owns. load_runstate() returns
        the empty default when the file is absent, and the whole runstate is
        rewritten on every save — so if the load handed back that default for
        a file that already_exists, the next save would silently erase every
        other job's last_run. Nothing else would notice: the file would still
        parse, the scheduler would just re-fire jobs it had already run.

        Written here after the sweep (DPLAN-0325). The item used to be scored
        off tests/test_json_handler.py, a DPLAN-0059 stamp file that had
        stopped RUNNING — it skipped module-wide on a JSON_DIR the shim does
        not have — so daemon was credited for a no-clobber claim nothing was
        executing. This one executes, and it is about daemon's own state.
        """
        first = {"version": 1, "jobs": {"@commons/wake": {"last_run": "2026-01-01T00:00:00"}}}
        assert save_runstate(first) is True

        # The cycle a caller performs: load what already_exists, add one job,
        # write the whole structure back.
        current = load_runstate()
        current["jobs"]["@memory/sweep"] = {"last_run": "2026-02-02T00:00:00"}
        assert save_runstate(current) is True

        after = load_runstate()
        assert after["jobs"]["@memory/sweep"]["last_run"] == "2026-02-02T00:00:00"
        assert after["jobs"]["@commons/wake"]["last_run"] == "2026-01-01T00:00:00", (
            "the earlier job's history was overwritten by a later save - "
            "every job would re-fire once its record was lost"
        )


# ── Due-logic: _already_ran_today / _already_ran_this_hour


class TestAlreadyRan:
    def test_no_last_run(self):
        now = datetime.now()
        assert _already_ran_today(None, now) is False
        assert _already_ran_this_hour(None, now) is False

    def test_ran_today(self):
        now = datetime.now()
        assert _already_ran_today(now.isoformat(), now) is True

    def test_ran_yesterday(self):
        now = datetime.now()
        yesterday = (now - timedelta(days=1)).isoformat()
        assert _already_ran_today(yesterday, now) is False

    def test_ran_this_hour(self):
        now = datetime.now()
        assert _already_ran_this_hour(now.isoformat(), now) is True

    def test_ran_last_hour(self):
        now = datetime.now()
        last_hour = (now - timedelta(hours=1)).isoformat()
        assert _already_ran_this_hour(last_hour, now) is False

    def test_invalid_timestamp(self):
        now = datetime.now()
        assert _already_ran_today("not-a-date", now) is False
        assert _already_ran_this_hour("not-a-date", now) is False


# ── Due-logic: individual schedule types ─────────────


class TestDailyDue:
    def test_within_window(self):
        now = datetime.now().replace(hour=4, minute=0, second=0)
        schedule = {"type": "daily", "time": "04:00"}
        assert _is_daily_due(schedule, None, now) is True

    def test_outside_window(self):
        now = datetime.now().replace(hour=12, minute=0, second=0)
        schedule = {"type": "daily", "time": "04:00"}
        assert _is_daily_due(schedule, None, now) is False

    def test_already_ran(self):
        now = datetime.now().replace(hour=4, minute=5, second=0)
        schedule = {"type": "daily", "time": "04:00"}
        assert _is_daily_due(schedule, now.isoformat(), now) is False

    def test_invalid_time(self):
        now = datetime.now()
        assert _is_daily_due({"time": "bad"}, None, now) is False


class TestHourlyDue:
    def test_within_window(self):
        now = datetime.now().replace(minute=30, second=0)
        schedule = {"type": "hourly", "time": "30"}
        assert _is_hourly_due(schedule, None, now) is True

    def test_outside_window(self):
        now = datetime.now().replace(minute=0, second=0)
        schedule = {"type": "hourly", "time": "30"}
        assert _is_hourly_due(schedule, None, now) is False


class TestIntervalDue:
    def test_never_run(self):
        schedule = {"type": "interval", "interval_minutes": 60}
        assert _is_interval_due(schedule, None, datetime.now()) is True

    def test_elapsed(self):
        now = datetime.now()
        old = (now - timedelta(minutes=120)).isoformat()
        schedule = {"type": "interval", "interval_minutes": 60}
        assert _is_interval_due(schedule, old, now) is True

    def test_not_elapsed(self):
        now = datetime.now()
        recent = (now - timedelta(minutes=5)).isoformat()
        schedule = {"type": "interval", "interval_minutes": 60}
        assert _is_interval_due(schedule, recent, now) is False


class TestOnceDue:
    def test_due_today(self):
        now = datetime.now()
        schedule = {"type": "once", "due_date": now.strftime("%Y-%m-%d")}
        assert _is_once_due(schedule, None, now) is True

    def test_future(self):
        now = datetime.now()
        future = (now + timedelta(days=7)).strftime("%Y-%m-%d")
        schedule = {"type": "once", "due_date": future}
        assert _is_once_due(schedule, None, now) is False

    def test_completed(self):
        now = datetime.now()
        schedule = {"type": "once", "due_date": now.strftime("%Y-%m-%d")}
        assert _is_once_due(schedule, now.isoformat(), now) is False

    def test_no_due_date(self):
        assert _is_once_due({}, None, datetime.now()) is False


# ── is_job_due (integration) ─────────────────────────


class TestIsJobDue:
    def test_interval_no_runstate(self, interval_job):
        runstate = {"jobs": {}}
        assert is_job_due(interval_job, runstate) is True

    def test_disabled_job(self, interval_job):
        interval_job["enabled"] = False
        runstate = {"jobs": {}}
        assert is_job_due(interval_job, runstate) is False

    def test_interval_recently_run(self, interval_job):
        runstate = {"jobs": {"@commons/wake-test": {"last_run": datetime.now().isoformat()}}}
        assert is_job_due(interval_job, runstate) is False

    def test_unknown_schedule_type(self):
        job = {"owner": "@x", "id": "y", "enabled": True, "schedule": {"type": "biweekly"}, "prompt": "z"}
        assert is_job_due(job, {"jobs": {}}) is False


# ── rotation schedule type (DPLAN-0287 piece 1) ──────


def rotation_job(time_str: str) -> dict:
    """A rotation job targeting a given HH:MM."""
    return {
        "owner": "@daemon",
        "id": "fleet-steward",
        "enabled": True,
        "schedule": {"type": "rotation", "time": time_str},
        "prompt": "STEWARD NIGHT for {branch}.",
    }


class TestRotationDue:
    def test_due_inside_the_window(self):
        now = datetime.now()
        assert is_job_due(rotation_job(now.strftime("%H:%M")), {"jobs": {}}) is True

    def test_not_due_outside_the_window(self):
        far = (datetime.now() + timedelta(hours=6)).strftime("%H:%M")
        assert is_job_due(rotation_job(far), {"jobs": {}}) is False

    def test_fires_once_per_night(self):
        now = datetime.now()
        runstate = {"jobs": {"@daemon/fleet-steward": {"last_run": now.isoformat()}}}
        assert is_job_due(rotation_job(now.strftime("%H:%M")), runstate) is False

    def test_disabled_rotation_never_fires(self):
        job = rotation_job(datetime.now().strftime("%H:%M"))
        job["enabled"] = False
        assert is_job_due(job, {"jobs": {}}) is False

    def test_next_run_is_the_next_night(self):
        runstate = {"jobs": {}}
        update_job_runstate(runstate, "@daemon", "fleet-steward", {"type": "rotation", "time": "05:00"})
        next_run = runstate["jobs"]["@daemon/fleet-steward"]["next_run"]
        assert next_run is not None
        assert datetime.fromisoformat(next_run).strftime("%H:%M") == "05:00"
        assert datetime.fromisoformat(next_run) > datetime.now()


# ── update_job_runstate ──────────────────────────────


class TestUpdateRunstate:
    def test_creates_entry(self):
        runstate = {"jobs": {}}
        schedule = {"type": "interval", "interval_minutes": 60}
        update_job_runstate(runstate, "@commons", "wake-test", schedule)
        entry = runstate["jobs"]["@commons/wake-test"]
        assert "last_run" in entry
        assert "next_run" in entry

    def test_once_marks_completed(self):
        runstate = {"jobs": {}}
        schedule = {"type": "once", "due_date": "2026-01-01"}
        update_job_runstate(runstate, "@x", "y", schedule)
        entry = runstate["jobs"]["@x/y"]
        assert "completed" in entry


# ── prune_orphans ────────────────────────────────────


class TestPruneOrphans:
    def test_removes_orphans(self):
        runstate = {"jobs": {"@a/1": {"last_run": "x"}, "@b/2": {"last_run": "y"}, "@c/3": {"last_run": "z"}}}
        pruned = prune_orphans(runstate, {"@a/1", "@c/3"})
        assert pruned == 1
        assert "@b/2" not in runstate["jobs"]
        assert len(runstate["jobs"]) == 2

    def test_no_orphans(self):
        runstate = {"jobs": {"@a/1": {}}}
        pruned = prune_orphans(runstate, {"@a/1"})
        assert pruned == 0
