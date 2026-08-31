# =================== AIPass ====================
# Name: test_runstate_failure_retry.py
# Description: A failed fire must not consume its own period
# Version: 1.0.0
# Created: 2026-08-30
# Modified: 2026-08-30
# =============================================

"""
A FAILED fire used to suppress its own retry for the rest of the period.

Reported by @ai_mail (mail 826e02cd) after @devpulse spotted it, and measured
against this branch's live runstate before I touched anything:
record_job_failure() stamped ``last_run`` exactly as the success path does, and
every due-ness checker read ``last_run`` without ever consulting
``last_status``. So the field meaning "when did this last SUCCEED" was being
written by the failure path, and due-ness could not tell the two apart.

Live proof at the time of the report - @vera/release-watch, whose only fire
that day raised "resolve: Branch not found", was not due again until the next
day.

Two rules come out of the fix and both are pinned here:

  1. WINDOWED schedules (daily, rotation, hourly) measure period-completion
     from the last SUCCESS. A failure no longer counts as the period's work.
  2. A failure still buys a short BACKOFF, so a permanently-broken job retries
     a couple of times inside its window instead of once per ~2-minute tick.
     Interval jobs keep measuring from the last ATTEMPT - their interval is
     already the bound, and measuring them from the last success would make a
     never-succeeding job due on every tick forever. That is the storm this
     fix must not create while removing the suppression.
"""

from datetime import datetime, timedelta

import pytest

from aipass.daemon.apps.handlers.schedule import runstate as rs


DAILY = {"type": "daily", "time": "19:00"}
HOURLY = {"type": "hourly", "time": "2"}
INTERVAL = {"type": "interval", "interval_minutes": 60}


def _job(schedule, owner="@vera", job_id="release-watch"):
    return {"owner": owner, "id": job_id, "enabled": True, "schedule": schedule}


def _state_after_failure(ts):
    st = {}
    rs.record_job_failure(st, "@vera", "release-watch", "resolve: Branch not found", timestamp=ts)
    return st


def _state_after_success(ts, schedule=DAILY):
    st = {}
    rs.update_job_runstate(st, "@vera", "release-watch", schedule, timestamp=ts)
    return st


class TestAFailedFireDoesNotConsumeItsPeriod:
    """Rule 1. The reported defect, held for every windowed schedule type."""

    @pytest.mark.parametrize(
        "schedule,failed_at,retry_at",
        [
            (DAILY, "2026-08-30T19:02:04", datetime(2026, 8, 30, 19, 14)),
            ({"type": "rotation", "time": "19:00"}, "2026-08-30T19:02:04", datetime(2026, 8, 30, 19, 14)),
            (HOURLY, "2026-08-30T19:02:04", datetime(2026, 8, 30, 19, 14)),
        ],
    )
    def test_a_windowed_job_is_due_again_after_a_failure(self, schedule, failed_at, retry_at):
        st = _state_after_failure(failed_at)

        assert rs.is_job_due(_job(schedule), st, now=retry_at) is True

    def test_the_exact_live_entry_from_the_report_is_due_again(self):
        # @vera/release-watch as it actually sat in daemon_runstate.json.
        st = {
            "jobs": {
                rs.job_key("@vera", "release-watch"): {
                    "last_run": "2026-08-30T19:02:04.616354",
                    "last_status": "failed",
                    "last_failure_at": "2026-08-30T19:02:04.616354",
                    "last_error": "resolve: Branch not found: @vera",
                }
            }
        }

        assert (
            rs._is_daily_due(
                DAILY, rs._due_from(st["jobs"][rs.job_key("@vera", "release-watch")]), datetime(2026, 8, 30, 19, 14)
            )
            is True
        )


class TestASuccessStillConsumesItsPeriod:
    """The behaviour that must NOT change - success is still once per period."""

    def test_a_succeeded_daily_job_is_not_due_again_the_same_day(self):
        st = _state_after_success("2026-08-30T19:02:04")

        assert rs.is_job_due(_job(DAILY), st, now=datetime(2026, 8, 30, 19, 14)) is False

    def test_a_succeeded_daily_job_is_due_again_the_next_day(self):
        st = _state_after_success("2026-08-29T19:02:04")

        assert (
            rs._is_daily_due(
                DAILY, rs._due_from(st["jobs"][rs.job_key("@vera", "release-watch")]), datetime(2026, 8, 30, 19, 5)
            )
            is True
        )

    def test_a_legacy_entry_with_no_last_success_at_still_counts_as_run(self):
        # Entries written before last_success_at existed carry only last_run
        # plus last_status. Treating those as "never succeeded" would re-fire
        # every already-done job on this machine the moment the fix landed.
        entry = {"last_run": "2026-08-30T19:02:04", "last_status": "success"}

        assert rs._due_from(entry) == "2026-08-30T19:02:04"

    def test_an_entry_with_no_status_at_all_is_read_as_a_run(self):
        # Oldest shape: last_run alone. Same reasoning - absence of a failure
        # marker is not evidence of a failure.
        assert rs._due_from({"last_run": "2026-08-30T19:02:04"}) == "2026-08-30T19:02:04"

    def test_a_failed_entry_reports_no_usable_success(self):
        assert rs._due_from({"last_run": "x", "last_status": "failed"}) is None


class TestTheFailureBackoffBoundsTheRetry:
    """Rule 2. Removing the suppression must not create a per-tick storm."""

    def test_a_job_that_just_failed_is_not_retried_on_the_next_tick(self):
        # The tick cadence is ~2 minutes; without this the +/-15 min daily
        # window would fire a permanently-broken job about 8 times a day.
        st = _state_after_failure("2026-08-30T19:02:04")
        two_minutes_later = datetime(2026, 8, 30, 19, 4)

        assert rs._in_failure_backoff(st["jobs"][rs.job_key("@vera", "release-watch")], two_minutes_later) is True

    def test_the_backoff_expires_and_the_retry_happens(self):
        st = _state_after_failure("2026-08-30T19:02:04")
        entry = st["jobs"][rs.job_key("@vera", "release-watch")]

        assert rs._in_failure_backoff(entry, datetime(2026, 8, 30, 19, 14)) is False
        assert rs.is_job_due(_job(DAILY), st, now=datetime(2026, 8, 30, 19, 14)) is True

    def test_a_broken_daily_job_fires_a_bounded_number_of_times_in_its_window(self):
        # The whole point, measured rather than asserted: walk the real tick
        # cadence across the real window and count.
        st = _state_after_failure("2026-08-30T18:45:00")
        fires = 0
        now = datetime(2026, 8, 30, 18, 45)
        end = datetime(2026, 8, 30, 19, 15)
        while now <= end:
            if rs.is_job_due(_job(DAILY), st, now=now):
                fires += 1
                rs.record_job_failure(st, "@vera", "release-watch", "still broken", timestamp=now.isoformat())
            now += timedelta(minutes=2)

        assert 1 <= fires <= 4, f"a broken daily job fired {fires} times in one window"

    def test_a_successful_job_is_never_held_by_a_stale_backoff(self):
        # An entry that failed once and later succeeded must not be blocked by
        # the old last_failure_at still sitting in the record.
        st = _state_after_failure("2026-08-30T19:02:04")
        rs.update_job_runstate(st, "@vera", "release-watch", DAILY, timestamp="2026-08-30T19:03:00")
        entry = st["jobs"][rs.job_key("@vera", "release-watch")]

        assert rs._in_failure_backoff(entry, datetime(2026, 8, 30, 19, 4)) is False


class TestIntervalJobsKeepMeasuringFromTheAttempt:
    """The regression this fix must not introduce."""

    def test_a_never_succeeding_interval_job_is_not_due_every_tick(self):
        st = _state_after_failure("2026-08-30T19:02:04")

        assert rs.is_job_due(_job(INTERVAL), st, now=datetime(2026, 8, 30, 19, 30)) is False

    def test_an_interval_job_retries_once_its_interval_has_passed(self):
        st = {
            "jobs": {
                rs.job_key("@vera", "release-watch"): {
                    "last_run": "2026-08-30T18:00:00",
                    "last_status": "failed",
                    "last_failure_at": "2026-08-30T18:00:00",
                }
            }
        }

        assert rs._is_interval_due(INTERVAL, "2026-08-30T18:00:00", datetime(2026, 8, 30, 19, 5)) is True
        assert rs.is_job_due(_job(INTERVAL), st, now=datetime(2026, 8, 30, 19, 5)) is True


class TestLastRunStillMeansTheLastAttempt:
    """Nothing here quietly changes what the queue display reports."""

    def test_a_failure_still_stamps_last_run_for_the_queue(self):
        st = _state_after_failure("2026-08-30T19:02:04")
        entry = st["jobs"][rs.job_key("@vera", "release-watch")]

        assert entry["last_run"] == "2026-08-30T19:02:04"
        assert entry["last_status"] == "failed"
        assert entry["last_error"].startswith("resolve:")
