# =================== AIPass ====================
# Name: test_next_run_agrees_with_due.py
# Description: next_run must name an instant is_job_due actually agrees with
# Version: 1.0.1
# Created: 2026-08-31
# Modified: 2026-10-17
# =============================================

"""Tests for handlers/schedule/runstate.py — next_run and is_job_due must not disagree."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that runstate.py parses and imports
# seedgo: no-test-needed(stdlib) — datetime's own arithmetic; the pins drive is_job_due at the instants next_run names

from datetime import datetime, timedelta

import pytest

from aipass.daemon.apps.handlers.schedule import runstate

# The queue shows next_run to humans, so it must name an instant is_job_due agrees with.
# The pin is the agreement, not the arithmetic: restating "daily -> tomorrow" would be a third implementation.


def _state_after_firing(schedule: dict, fired_at: str) -> dict:
    """A runstate holding exactly one job, fired at *fired_at*."""
    rs = {"version": 1, "jobs": {}}
    runstate.update_job_runstate(rs, "@probe", "job", schedule, timestamp=fired_at)
    return rs


def _job(schedule: dict) -> dict:
    return {"owner": "@probe", "id": "job", "schedule": schedule, "prompt": "x", "enabled": True}


DAILY = {"type": "daily", "time": "10:00"}
ROTATION = {"type": "rotation", "time": "05:00"}
HOURLY = {"type": "hourly", "time": "0"}
INTERVAL = {"type": "interval", "interval_minutes": 60}

# is_job_due's +/-15min window, pinned by test_the_window_slack_is_real_and_bounded.
WINDOW_SLACK = timedelta(minutes=15)


class TestNextRunNamesAnInstantThatIsActuallyDue:
    @pytest.mark.parametrize(
        "schedule,fired_at",
        [
            (DAILY, "2026-08-31T09:45:11"),
            (DAILY, "2026-08-31T10:00:00"),
            (DAILY, "2026-08-31T10:14:00"),
            (ROTATION, "2026-08-31T04:46:00"),
            (HOURLY, "2026-08-31T09:47:00"),
            (INTERVAL, "2026-08-31T09:45:11"),
        ],
    )
    def test_is_job_due_agrees_at_the_advertised_instant(self, schedule, fired_at):
        rs = _state_after_firing(schedule, fired_at)
        next_run = rs["jobs"]["@probe/job"]["next_run"]

        assert next_run is not None, f"{schedule['type']} advertised no next run at all"
        assert runstate.is_job_due(_job(schedule), rs, datetime.fromisoformat(next_run)), (
            f"{schedule['type']} fired at {fired_at} advertises next_run={next_run}, "
            "but is_job_due says the job is NOT due at that instant - the queue "
            "shows the operator a wake that will never come"
        )

    @pytest.mark.parametrize(
        "schedule,fired_at",
        [
            (DAILY, "2026-08-31T09:45:11"),
            (ROTATION, "2026-08-31T04:46:00"),
            (HOURLY, "2026-08-31T09:47:00"),
        ],
    )
    def test_the_queue_never_under_reports_by_a_whole_period(self, schedule, fired_at):
        """next_run must not be LATER than the true next fire (else the year 3000 passes the test above).

        Due inside WINDOW_SLACK before next_run is expected: next_run echoes the configured target time.
        """
        rs = _state_after_firing(schedule, fired_at)
        next_run = datetime.fromisoformat(rs["jobs"]["@probe/job"]["next_run"])
        fired = datetime.fromisoformat(fired_at)
        earliest_honest = next_run - WINDOW_SLACK

        probe = fired + timedelta(minutes=5)
        early = []
        while probe < earliest_honest:
            if runstate.is_job_due(_job(schedule), rs, probe):
                early.append(probe.isoformat())
            probe += timedelta(minutes=5)

        assert early == [], (
            f"{schedule['type']} is due at {early[:3]} - more than the {WINDOW_SLACK} "
            f"window before the advertised next_run={next_run.isoformat()}, so the "
            "queue under-reports by a whole period"
        )

    @pytest.mark.parametrize("schedule,fired_at", [(DAILY, "2026-08-31T09:45:11"), (ROTATION, "2026-08-31T04:46:00")])
    def test_the_window_slack_is_real_and_bounded(self, schedule, fired_at):
        """Control: WINDOW_SLACK matches the window is_job_due actually enforces, and cannot grow."""
        rs = _state_after_firing(schedule, fired_at)
        next_run = datetime.fromisoformat(rs["jobs"]["@probe/job"]["next_run"])

        assert runstate.is_job_due(_job(schedule), rs, next_run - WINDOW_SLACK), (
            f"{schedule['type']} is NOT due at next_run-{WINDOW_SLACK}; the slack "
            "this file allows does not describe real behaviour"
        )
        assert not runstate.is_job_due(_job(schedule), rs, next_run - WINDOW_SLACK - timedelta(minutes=1)), (
            f"{schedule['type']} is due EARLIER than {WINDOW_SLACK} before target - "
            "the window widened and this file's allowance is now too small to catch it"
        )


class TestCalcNextRunReadsItsArgumentNotTheWallClock:
    """Same firing instant, process clock moved in between: next_run must not change."""

    @pytest.mark.parametrize("schedule,fired_at", [(DAILY, "2026-08-31T09:45:11"), (HOURLY, "2026-08-31T09:47:00")])
    def test_the_answer_does_not_move_when_the_wall_clock_does(self, schedule, fired_at, monkeypatch):
        first = _state_after_firing(schedule, fired_at)["jobs"]["@probe/job"]["next_run"]

        real_datetime = runstate.datetime

        class Shifted(real_datetime):
            @classmethod
            def now(cls, tz=None):
                return real_datetime(2027, 3, 4, 23, 59, 0)

        monkeypatch.setattr(runstate, "datetime", Shifted)

        # Control: the injection really did move the process clock.
        assert runstate.datetime.now().year == 2027

        second = _state_after_firing(schedule, fired_at)["jobs"]["@probe/job"]["next_run"]

        assert first == second, (
            f"{schedule['type']} next_run changed from {first} to {second} for the "
            "SAME firing instant - it is reading the wall clock instead of the "
            "last_run timestamp it was given"
        )
