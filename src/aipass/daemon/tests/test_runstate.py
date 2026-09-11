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
    _slot_anchor,
    is_catch_up_fire,
    missed_window,
    needs_slot_seed,
    note_missed_window,
    seed_interval_slot,
    window_closed_unrun,
    window_label,
    MISSED_MARKER,
    WINDOW_MINUTES,
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
        "id": "rounds",
        "enabled": True,
        "schedule": {"type": "rotation", "time": time_str},
        "prompt": "ROUNDS for {branch}.",
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
        runstate = {"jobs": {"@daemon/rounds": {"last_run": now.isoformat()}}}
        assert is_job_due(rotation_job(now.strftime("%H:%M")), runstate) is False

    def test_disabled_rotation_never_fires(self):
        job = rotation_job(datetime.now().strftime("%H:%M"))
        job["enabled"] = False
        assert is_job_due(job, {"jobs": {}}) is False

    def test_next_run_is_the_next_night(self):
        runstate = {"jobs": {}}
        update_job_runstate(runstate, "@daemon", "rounds", {"type": "rotation", "time": "05:00"})
        next_run = runstate["jobs"]["@daemon/rounds"]["next_run"]
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


# ── closed windows: catch_up + the MISSED record (FPLAN-0492 ruling 6) ──

DAY = "2026-09-07"


def windowed_job(time_str="03:00", catch_up=None, owner="@seedgo", job_id="nightly"):
    """A daily job, optionally opted in to catch-up."""
    schedule = {"type": "daily", "time": time_str}
    if catch_up is not None:
        schedule["catch_up"] = catch_up
    return {"owner": owner, "id": job_id, "enabled": True, "schedule": schedule, "prompt": "x"}


class TestWindowClosedUnrun:
    def test_inside_the_window_is_not_closed(self):
        # 03:10 is inside 03:00 +/-15, so the window is still open and the job
        # has not missed anything yet.
        assert window_closed_unrun({"time": "03:00"}, None, datetime(2026, 9, 7, 3, 10)) is False

    def test_on_the_closing_edge_is_not_closed(self):
        # 03:15 is the last minute INSIDE the window. Off-by-one here would
        # accuse a job in the same minute it is still allowed to fire.
        assert window_closed_unrun({"time": "03:00"}, None, datetime(2026, 9, 7, 3, 15)) is False

    def test_one_minute_past_the_edge_is_closed(self):
        assert window_closed_unrun({"time": "03:00"}, None, datetime(2026, 9, 7, 3, 16)) is True

    def test_before_the_window_is_not_closed(self):
        assert window_closed_unrun({"time": "03:00"}, None, datetime(2026, 9, 7, 1, 0)) is False

    def test_a_run_today_means_nothing_was_missed(self):
        ran = datetime(2026, 9, 7, 3, 2).isoformat()
        assert window_closed_unrun({"time": "03:00"}, ran, datetime(2026, 9, 7, 9, 0)) is False

    def test_yesterdays_run_does_not_cover_today(self):
        ran = datetime(2026, 9, 6, 3, 2).isoformat()
        assert window_closed_unrun({"time": "03:00"}, ran, datetime(2026, 9, 7, 9, 0)) is True

    def test_window_crossing_midnight_never_closes(self):
        # 23:50 +/-15 runs to 00:05 the NEXT day, so no instant inside 09-07
        # proves the miss. Refused rather than guessed.
        for hour in (0, 12, 23):
            assert window_closed_unrun({"time": "23:50"}, None, datetime(2026, 9, 7, hour, 30)) is False

    def test_unparseable_time_states_no_window(self):
        assert window_closed_unrun({"time": "not-a-time"}, None, datetime(2026, 9, 7, 9, 0)) is False


class TestCatchUpDueness:
    def test_on_by_default_a_closed_window_fires_late(self):
        """DPLAN-0332 flipped this, and the flip is the whole point of the plan.

        Was test_off_by_default_a_closed_window_does_not_fire, pinning ruling 6
        of 2026-09-07 (catch-up opt-in). Patrick superseded it on 09-08 after
        the 23h gap: every enabled job in the fleet had left catch_up unset, so
        opt-in meant nothing recovered. A job that states nothing now catches up.

        The pin READS THE FLAG rather than hard-coding one world. The lane is
        gated by RECOVERY_LANE_LIVE while @devpulse and Patrick run the
        controlled live proof, and a pin that asserted the flipped world would
        go red on a tree that is behaving exactly as ruled. What must always
        hold is that the flag and the default agree.
        """
        job = windowed_job()
        assert job["schedule"].get("catch_up") is None, "this job must state nothing about catch_up"
        due = is_job_due(job, {"jobs": {}}, now=datetime(2026, 9, 7, 9, 0))
        assert due is runstate_mod.RECOVERY_LANE_LIVE

    def test_explicit_false_opts_out(self):
        """The escape hatch: a job whose late run is worthless says so."""
        job = windowed_job(catch_up=False)
        assert is_job_due(job, {"jobs": {}}, now=datetime(2026, 9, 7, 9, 0)) is False

    def test_opted_in_a_closed_window_fires_late(self):
        job = windowed_job(catch_up=True)
        assert is_job_due(job, {"jobs": {}}, now=datetime(2026, 9, 7, 9, 0)) is True

    def test_catch_up_cannot_double_fire_the_same_day(self):
        # The bound is _already_ran_today: once today's catch-up has run, the
        # rest of the day's ticks must not fire it again.
        job = windowed_job(catch_up=True)
        runstate = {
            "jobs": {
                "@seedgo/nightly": {
                    "last_run": datetime(2026, 9, 7, 9, 1).isoformat(),
                    "last_success_at": datetime(2026, 9, 7, 9, 1).isoformat(),
                }
            }
        }
        assert is_job_due(job, runstate, now=datetime(2026, 9, 7, 9, 30)) is False

    def test_catch_up_does_not_widen_the_window_backwards(self):
        job = windowed_job(catch_up=True)
        assert is_job_due(job, {"jobs": {}}, now=datetime(2026, 9, 7, 1, 0)) is False

    def test_rotation_opts_in_the_same_way(self):
        job = windowed_job(catch_up=True)
        job["schedule"]["type"] = "rotation"
        assert is_job_due(job, {"jobs": {}}, now=datetime(2026, 9, 7, 9, 0)) is True

    def test_in_window_still_fires_with_catch_up_on(self):
        job = windowed_job(catch_up=True)
        assert is_job_due(job, {"jobs": {}}, now=datetime(2026, 9, 7, 3, 5)) is True


class TestIsCatchUpFire:
    def test_names_a_late_run(self):
        assert is_catch_up_fire(windowed_job(catch_up=True), {"jobs": {}}, now=datetime(2026, 9, 7, 9, 0)) is True

    def test_an_in_window_run_is_not_a_catch_up(self):
        assert is_catch_up_fire(windowed_job(catch_up=True), {"jobs": {}}, now=datetime(2026, 9, 7, 3, 5)) is False

    def test_interval_jobs_are_never_catch_ups(self):
        job = {"owner": "@a", "id": "b", "schedule": {"type": "interval", "interval_minutes": 30}}
        assert is_catch_up_fire(job, {"jobs": {}}, now=datetime(2026, 9, 7, 9, 0)) is False


class TestCaughtUpStamp:
    def test_a_caught_up_run_is_recorded_as_one(self):
        runstate = {"jobs": {}}
        update_job_runstate(
            runstate,
            "@seedgo",
            "nightly",
            {"type": "daily", "time": "03:00"},
            timestamp="2026-09-07T09:00:00",
            caught_up=True,
        )
        assert runstate["jobs"]["@seedgo/nightly"]["caught_up"] == "2026-09-07T09:00:00"

    def test_an_ordinary_run_clears_a_stale_marker(self):
        # A marker left from last week's catch-up would report a healthy job as
        # chronically late for as long as nobody looked at the timestamp.
        runstate = {"jobs": {"@seedgo/nightly": {"caught_up": "2026-08-30T09:00:00"}}}
        update_job_runstate(
            runstate, "@seedgo", "nightly", {"type": "daily", "time": "03:00"}, timestamp="2026-09-07T03:02:00"
        )
        assert runstate["jobs"]["@seedgo/nightly"]["caught_up"] is None


class TestMissedWindowRecord:
    def test_missed_window_is_independent_of_catch_up(self):
        # A job nobody opted in still MISSED, and the operator still needs told.
        assert missed_window(windowed_job(), {"jobs": {}}, now=datetime(2026, 9, 7, 9, 0)) is True

    def test_first_note_is_new_and_the_rest_are_not(self):
        runstate = {"jobs": {}}
        now = datetime(2026, 9, 7, 9, 0)
        assert note_missed_window(runstate, "@seedgo", "nightly", now) is True
        assert note_missed_window(runstate, "@seedgo", "nightly", now) is False
        assert runstate["jobs"]["@seedgo/nightly"][MISSED_MARKER] == DAY

    def test_a_new_day_is_reported_again(self):
        runstate = {"jobs": {"@seedgo/nightly": {MISSED_MARKER: "2026-09-06"}}}
        assert note_missed_window(runstate, "@seedgo", "nightly", datetime(2026, 9, 7, 9, 0)) is True

    def test_the_marker_does_not_make_a_job_look_run(self):
        # note_missed_window creates a runstate row. If that row read as a run,
        # a catch_up job would be silenced by the very line reporting its miss.
        runstate = {"jobs": {}}
        now = datetime(2026, 9, 7, 9, 0)
        note_missed_window(runstate, "@seedgo", "nightly", now)
        assert is_job_due(windowed_job(catch_up=True), runstate, now=now) is True

    def test_window_label_names_the_window(self):
        assert window_label({"time": "03:00"}) == f"03:00 +/-{WINDOW_MINUTES}m"


# ── interval slots (FPLAN-0492 ruling 6, the seedgo weekly lesson) ──

WEEK_MINUTES = 7 * 24 * 60


def slotted_job(slot=None, minutes=WEEK_MINUTES, owner="@seedgo", job_id="shadow-cycle-weekly"):
    schedule = {"type": "interval", "interval_minutes": minutes}
    if slot is not None:
        schedule["slot"] = slot
    return {"owner": owner, "id": job_id, "enabled": True, "schedule": schedule, "prompt": "x"}


class TestSlotAnchor:
    def test_a_past_slot_rolls_forward_by_whole_intervals(self):
        # The anchor names a RHYTHM, so a slot left in the past keeps its phase
        # instead of making the job instantly overdue.
        anchor = _slot_anchor("2026-08-02T03:00:00", WEEK_MINUTES, datetime(2026, 9, 7, 9, 0))
        assert anchor == datetime(2026, 9, 6, 3, 0)

    def test_a_future_slot_seeds_one_interval_behind_itself(self):
        anchor = _slot_anchor("2026-09-13T03:00:00", WEEK_MINUTES, datetime(2026, 9, 7, 9, 0))
        assert anchor == datetime(2026, 9, 6, 3, 0)

    def test_unreadable_slot_is_refused(self):
        assert _slot_anchor("next tuesday", WEEK_MINUTES, datetime(2026, 9, 7, 9, 0)) is None

    def test_non_positive_interval_is_refused(self):
        assert _slot_anchor("2026-09-06T03:00:00", 0, datetime(2026, 9, 7, 9, 0)) is None


class TestNeedsSlotSeed:
    def test_a_never_run_interval_job_needs_seeding(self):
        assert needs_slot_seed(slotted_job(), {"jobs": {}}) is True

    def test_a_job_that_has_run_does_not(self):
        runstate = {"jobs": {"@seedgo/shadow-cycle-weekly": {"last_run": "2026-09-06T03:00:00"}}}
        assert needs_slot_seed(slotted_job(), runstate) is False

    def test_a_blocked_job_still_needs_seeding(self):
        # THE DEFECT, pinned. record_job_blocked creates a row carrying
        # last_blocked_at and no last_run, so a "no row" test would refuse to
        # seed exactly the job that most needs it - @seedgo's weekly cycle,
        # enabled unseeded and blocked twice at 01:34 and 01:40 on 2026-09-07.
        runstate = {
            "jobs": {
                "@seedgo/shadow-cycle-weekly": {"last_status": "blocked", "last_blocked_at": "2026-09-07T01:34:52"}
            }
        }
        assert needs_slot_seed(slotted_job(), runstate) is True

    def test_disabled_jobs_are_left_alone(self):
        job = slotted_job()
        job["enabled"] = False
        assert needs_slot_seed(job, {"jobs": {}}) is False

    def test_daily_jobs_are_not_interval_jobs(self):
        assert needs_slot_seed(windowed_job(), {"jobs": {}}) is False


class TestSeedIntervalSlot:
    def test_seeding_moves_the_first_fire_to_the_next_slot(self):
        # The lesson in one test: enabled 01:34 Monday, seeded from a Sunday
        # 03:00 slot, first fire is the NEXT Sunday 03:00 - not 01:34.
        runstate = {"jobs": {}}
        job = slotted_job(slot="2026-09-06T03:00:00")
        seeded = seed_interval_slot(runstate, job, now=datetime(2026, 9, 7, 1, 34))
        assert seeded == "2026-09-06T03:00:00"
        entry = runstate["jobs"]["@seedgo/shadow-cycle-weekly"]
        assert entry["next_run"] == "2026-09-13T03:00:00"
        assert entry["seeded_from_slot"] == "2026-09-06T03:00:00"

    def test_a_seeded_job_is_not_due_on_the_next_tick(self):
        runstate = {"jobs": {}}
        job = slotted_job(slot="2026-09-06T03:00:00")
        seed_interval_slot(runstate, job, now=datetime(2026, 9, 7, 1, 34))
        assert is_job_due(job, runstate, now=datetime(2026, 9, 7, 1, 36)) is False

    def test_a_seeded_job_is_due_at_its_slot(self):
        runstate = {"jobs": {}}
        job = slotted_job(slot="2026-09-06T03:00:00")
        seed_interval_slot(runstate, job, now=datetime(2026, 9, 7, 1, 34))
        assert is_job_due(job, runstate, now=datetime(2026, 9, 13, 3, 0)) is True

    def test_no_slot_seeds_nothing(self):
        runstate = {"jobs": {}}
        assert seed_interval_slot(runstate, slotted_job(), now=datetime(2026, 9, 7, 1, 34)) is None
        assert runstate["jobs"] == {}

    def test_unreadable_slot_seeds_nothing(self):
        runstate = {"jobs": {}}
        job = slotted_job(slot="whenever")
        assert seed_interval_slot(runstate, job, now=datetime(2026, 9, 7, 1, 34)) is None
        assert runstate["jobs"] == {}
