# =================== AIPass ====================
# Name: test_next_run_agrees_with_due.py
# Description: next_run must name an instant is_job_due actually agrees with
# Version: 1.0.0
# Created: 2026-08-31
# Modified: 2026-08-31
# =============================================

"""One question, one answer: next_run and is_job_due must not disagree.

FOUND LIVE, 2026-08-31. @vera's release-watch is `daily @ 10:00`. It fired at
09:45:11 - correct, that is the leading edge of the +/-15min window - and the
runstate then advertised next_run = 2026-08-31T10:00:00. Nine minutes away, and
a fire that could never happen: _already_ran_today consumes the whole CALENDAR
DAY, so is_job_due answered False at 09:55, 10:00, 10:05 and 10:14, and True
only on 2026-09-01.

THE MECHANISM: _calc_next_run is HANDED last_run_ts and, for daily/rotation and
hourly, ignores it and reads the wall clock instead. It then asks a different
question - "when does the target time next come round" - than the one the
scheduler asks - "which period has already been consumed". Two implementations
of one contract, which is the species that has bitten this branch before (S51:
a guard that re-derived what it policed instead of consulting it).

INTERVAL WAS ALREADY RIGHT, and that is the tell: it is the one branch that uses
the timestamp it was given. The bug is not "daily is hard", it is "two branches
reached for now() when the answer was in the argument list".

WHY IT MATTERS even though nothing schedules off next_run: `drone @daemon queue`
is the human status surface. An operator reading NEXT RUN 10:00 at 09:52 expects
a wake in eight minutes. When it does not come, the field that lied is the first
place they will look for the reason - so it points the investigation the wrong
way at exactly the moment someone is already debugging a missed wake.

THE PIN IS THE AGREEMENT, not a restatement of the arithmetic. Asserting
"daily -> tomorrow" would be a third implementation. These tests drive
is_job_due at the instant next_run names and require it to say True - and
require False at every instant strictly before it, on the same window grid.
"""

from datetime import datetime, timedelta

import pytest

from aipass.daemon.apps.handlers.schedule import runstate


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

# The +/-15min window is_job_due enforces for windowed schedules. Named once,
# asserted against real behaviour in test_the_window_slack_is_real_and_bounded.
WINDOW_SLACK = timedelta(minutes=15)


class TestNextRunNamesAnInstantThatIsActuallyDue:
    @pytest.mark.parametrize(
        "schedule,fired_at",
        [
            # The live case: fired at the leading edge of its window.
            (DAILY, "2026-08-31T09:45:11"),
            # ...and the ordinary case, fired dead on target.
            (DAILY, "2026-08-31T10:00:00"),
            # ...and the trailing edge.
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
        """The other half: next_run must not be LATER than the true next fire.

        Without this, returning the year 3000 would satisfy the test above.

        WINDOW_SLACK is the one allowance, and it is a decision rather than a
        tolerance bolted on to make a red go green. A windowed job becomes due
        at target-15min, so the earliest possible fire is always earlier than
        the target time next_run reports. Reporting target-15min instead was
        considered and rejected in _calc_next_run's docstring: "daily @ 10:00"
        is what the owner configured and what the queue should echo, and window
        arithmetic in a human-facing field helps nobody.

        So: due strictly inside the window before next_run is EXPECTED. Due
        anywhere earlier than that means a whole period was skipped, which is
        the defect this file exists for, and stays red.
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
        """Control for the allowance above: it must not be free to grow.

        A tolerance nobody measures becomes a place to hide the next defect.
        This asserts the job IS due somewhere inside the slack window - so the
        allowance is describing real behaviour - and that WINDOW_SLACK matches
        the window is_job_due actually enforces.
        """
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
    """The structural half - the defect was reaching for now() at all.

    Driven by firing the SAME job at the same instant twice, with the process
    clock moved in between. A function that derives its answer from the
    timestamp it was handed cannot notice; the pre-fix daily and hourly
    branches gave two different answers.
    """

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
