# =================== AIPass ====================
# Name: test_run_blocked_contract.py
# Description: Blocked is not ran — a wake that never started must not consume the period
# Version: 1.0.0
# Created: 2026-08-30
# Modified: 2026-08-30
# =============================================

"""
BLOCKED IS NOT RAN — the second face of "a failed fire consumes its period".

Dispatched by @devpulse with the live chain measured on this machine: the 19:47
daemon wake of @vera opened an interactive tmux room, she finished in minutes,
and the room then SAT AT THE PROMPT for 90+ minutes. wake_branch refuses to
spawn into an occupied branch, ``_fire_job`` recorded that refusal as a failure,
and ``record_job_failure`` stamped ``last_run`` — so tonight's leftover room
would have swallowed tomorrow's 10:00 fire. A scheduler whose every fire plants
the blocker for its next fire is the defect shape.

Two halves, one contract, both pinned here:

  1. SCHEDULED LANE. ``run.py`` passes ``scheduled=True``, so a manager target
     goes headless through dispatch_monitor instead of an unattended tmux room
     nobody closes. No room, so no self-blocking. rotation.py was already doing
     this; run.py was the odd path out, and two lanes in one caller disagreeing
     is its own defect.

  2. BLOCKED IS NOT RAN. When the wake never STARTED — occupancy, a live
     dispatch lock, autonomous_pause, a lock we could not take — the job stays
     DUE and retries on later ticks inside its window. ``last_run`` is only
     stamped by a wake that actually started.

The bound is stated, not omitted: a blocked fire buys a short retry hold
(``_BLOCKED_RETRY_MINUTES``). Removing a suppression has to be replaced by a
bound rather than by nothing — an INTERVAL job measures from its last ATTEMPT,
so a blocked-forever interval job with no hold would re-attempt on every
~2-minute tick for as long as the target stayed busy.
"""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from aipass.daemon.apps.handlers.schedule import runstate as rs
from aipass.daemon.apps.modules import run as run_mod
from aipass.daemon.apps.modules.run import (
    OUTCOME_BLOCKED,
    OUTCOME_FAILED,
    OUTCOME_FIRED,
    _fire_job,
    run_tick,
)

RUN = "aipass.daemon.apps.modules.run"

DAILY = {"type": "daily", "time": "10:00"}
INTERVAL = {"type": "interval", "interval_minutes": 60}


def _job(schedule=None, owner="@vera", job_id="release-watch"):
    return {
        "owner": owner,
        "id": job_id,
        "enabled": True,
        "schedule": schedule or DAILY,
        "wake": {"fresh": True},
        "prompt": "tend your branch",
    }


class FakeStatus:
    """Stand-in for ai_mail's DispatchStatus — same steps list, same reader.

    A seam, never the real dispatcher: these tests must never reach a live
    wake_branch, a tmux server or another branch's lock file.
    """

    def __init__(self, steps):
        self.steps = list(steps)

    def find_step(self, label):
        for step in reversed(self.steps):
            if step[1] == label:
                return step
        return None

    @property
    def summary(self):
        if self.steps:
            _, label, detail = self.steps[-1]
            return f"{label}: {detail}"
        return "no status"


# Every terminal shape wake_branch can return with ok=False, taken from the
# gates in ai_mail's wake_branch, paired with the outcome daemon owes it.
OCCUPIED = FakeStatus(
    [
        ("ok", "resolve", "@vera → /repo/vera"),
        ("warn", "occupancy", "Interactive Claude session in /repo/vera"),
        ("fail", "blocked", "Cannot spawn — interactive session running"),
    ]
)
LOCKED = FakeStatus([("ok", "resolve", "@vera → /repo/vera"), ("fail", "lock", "Active agent (PID 4242, since 19:47)")])
PAUSED = FakeStatus([("fail", "pause", "System paused (autonomous_pause active)")])
LOCK_LOST = FakeStatus([("ok", "occupancy", "No interactive session"), ("fail", "lock-acquire", "Lock failed: taken")])
NOT_FOUND = FakeStatus([("fail", "resolve", "Branch not found: @vera")])
BLOCKLISTED = FakeStatus([("fail", "blocklist", "@devpulse is on WAKE_BLOCKLIST — refused in the scheduled lane")])
SPAWNED = FakeStatus([("ok", "spawn", "session started")])


def _fire_with(status, ok, job=None):
    """Run _fire_job against a stubbed wake_branch. Returns (outcome, detail)."""
    fake_wake = MagicMock(return_value=(status, ok))
    with (
        patch("aipass.ai_mail.apps.handlers.dispatch.wake.wake_branch", fake_wake),
        patch(f"{RUN}._should_notify", return_value=False),
    ):
        return _fire_job(job or _job(), {"jobs": {}}), fake_wake


# ── Half 1: the scheduled lane ───────────────────────


class TestScheduledLane:
    """run.py fires on a clock, so every wake it makes is a scheduled wake."""

    def test_run_passes_scheduled_true(self):
        (_outcome, _detail), fake_wake = _fire_with(SPAWNED, True)
        assert fake_wake.call_args.kwargs["scheduled"] is True

    def test_scheduled_is_not_conditional_on_the_target(self):
        """The flag describes the CALLER's lane, not the target's class.

        Deciding it per-target would mean reading the passport here, which is a
        second copy of the manager gate wake_branch already owns.
        """
        for owner in ("@vera", "@commons", "@backup"):
            (_outcome, _detail), fake_wake = _fire_with(SPAWNED, True, job=_job(owner=owner))
            assert fake_wake.call_args.kwargs["scheduled"] is True, owner

    def test_sender_is_still_daemon(self):
        (_outcome, _detail), fake_wake = _fire_with(SPAWNED, True)
        assert fake_wake.call_args.kwargs["sender"] == "@daemon"


# ── Half 2: blocked is not ran ───────────────────────


class TestBlockedClassification:
    """Which refusals are 'never started' and which are a decided failure."""

    @pytest.mark.parametrize(
        "status", [OCCUPIED, LOCKED, PAUSED, LOCK_LOST], ids=["occupancy", "lock", "pause", "lock-acquire"]
    )
    def test_gates_that_never_started_a_wake_are_blocked(self, status):
        (outcome, detail), _ = _fire_with(status, False)
        assert outcome == OUTCOME_BLOCKED
        assert detail

    @pytest.mark.parametrize("status", [NOT_FOUND, BLOCKLISTED], ids=["resolve", "blocklist"])
    def test_decided_refusals_are_still_failures(self, status):
        """A missing branch and a blocklisted target are not transient.

        Retrying either on every tick inside the window is noise: nothing about
        the next two minutes changes the answer.
        """
        (outcome, _detail), _ = _fire_with(status, False)
        assert outcome == OUTCOME_FAILED

    def test_a_started_wake_is_fired(self):
        (outcome, _detail), _ = _fire_with(SPAWNED, True)
        assert outcome == OUTCOME_FIRED

    def test_an_exception_is_a_failure_not_a_block(self):
        with (
            patch("aipass.ai_mail.apps.handlers.dispatch.wake.wake_branch", side_effect=RuntimeError("boom")),
            patch(f"{RUN}._should_notify", return_value=False),
        ):
            outcome, detail = _fire_job(_job(), {"jobs": {}})
        assert outcome == OUTCOME_FAILED
        assert "boom" in detail

    def test_an_ok_lock_step_is_not_read_as_blocked(self):
        """The success path records a 'lock' step too — status, not label, decides.

        The real shape: the wake got PAST the lock and occupancy gates, then
        died at the spawn. Both cleared gates are still in the steps list, so a
        reader that matched on label alone would call a genuine spawn failure a
        block and retry it every window forever without ever recording it.
        """
        status = FakeStatus(
            [
                ("ok", "lock", "No active lock — agent is sleeping"),
                ("ok", "occupancy", "No interactive session"),
                ("fail", "spawn", "claude binary not found"),
            ]
        )
        (outcome, detail), _ = _fire_with(status, False)
        assert outcome == OUTCOME_FAILED
        assert "claude binary not found" in detail

    def test_a_cleared_gate_on_a_succeeding_wake_is_still_fired(self):
        status = FakeStatus([("ok", "lock", "No active lock — agent is sleeping"), ("ok", "spawn", "started")])
        (outcome, _detail), _ = _fire_with(status, True)
        assert outcome == OUTCOME_FIRED


class TestBlockedNeverStampsLastRun:
    """The reported defect: a refusal that stamps last_run eats tomorrow."""

    def test_record_job_blocked_leaves_last_run_untouched(self):
        st = {
            "jobs": {
                "@vera/release-watch": {"last_run": "2026-08-29T10:00:11", "last_success_at": "2026-08-29T10:00:11"}
            }
        }
        rs.record_job_blocked(st, "@vera", "release-watch", "blocked: interactive session running")
        entry = st["jobs"]["@vera/release-watch"]
        assert entry["last_run"] == "2026-08-29T10:00:11"
        assert entry["last_success_at"] == "2026-08-29T10:00:11"

    def test_record_job_blocked_never_invents_a_last_run(self):
        st = {}
        rs.record_job_blocked(st, "@vera", "release-watch", "lock: active agent")
        assert "last_run" not in st["jobs"]["@vera/release-watch"]

    def test_blocked_is_named_in_the_record(self):
        st = {}
        rs.record_job_blocked(
            st, "@vera", "release-watch", "blocked: interactive session running", timestamp="2026-08-30T10:01:00"
        )
        entry = st["jobs"]["@vera/release-watch"]
        assert entry["last_status"] == "blocked"
        assert entry["last_blocked_at"] == "2026-08-30T10:01:00"
        assert "interactive session" in entry["last_error"]

    def test_blocked_does_not_arm_the_failure_backoff(self):
        """last_failure_at is the failure path's field. Blocked is a different fact."""
        st = {}
        rs.record_job_blocked(st, "@vera", "release-watch", "lock: active agent")
        assert "last_failure_at" not in st["jobs"]["@vera/release-watch"]

    def test_the_error_text_is_capped_like_the_failure_path(self):
        st = {}
        rs.record_job_blocked(st, "@vera", "release-watch", "x" * 1000)
        assert len(st["jobs"]["@vera/release-watch"]["last_error"]) == 500


class TestBlockedStaysDueAndRetries:
    """Half 2's whole point: the next tick inside the window fires."""

    def _blocked_at(self, ts, schedule=DAILY, prior=None):
        st = {"jobs": {"@vera/release-watch": dict(prior or {})}}
        rs.record_job_blocked(st, "@vera", "release-watch", "blocked: interactive session", timestamp=ts)
        return st

    def test_retry_fires_within_the_same_window(self):
        st = self._blocked_at("2026-08-30T09:52:00")
        assert rs.is_job_due(_job(), st, now=datetime(2026, 8, 30, 10, 4)) is True

    def test_yesterdays_success_does_not_suppress_todays_retry(self):
        st = self._blocked_at(
            "2026-08-30T09:52:00", prior={"last_run": "2026-08-29T10:00:11", "last_success_at": "2026-08-29T10:00:11"}
        )
        assert rs.is_job_due(_job(), st, now=datetime(2026, 8, 30, 10, 4)) is True

    def test_the_retry_hold_is_a_bound_not_a_suppression(self):
        """A blocked fire holds briefly, then retries — inside the same window."""
        st = self._blocked_at("2026-08-30T09:52:00")
        held = datetime(2026, 8, 30, 9, 54)  # 2 min later — next tick
        assert held - datetime(2026, 8, 30, 9, 52) < timedelta(minutes=rs._BLOCKED_RETRY_MINUTES)
        assert rs.is_job_due(_job(), st, now=held) is False
        assert rs.is_job_due(_job(), st, now=datetime(2026, 8, 30, 9, 58)) is True

    def test_an_interval_job_blocked_forever_is_rate_limited(self):
        """The storm this bound exists to prevent — interval measures from ATTEMPT."""
        st = self._blocked_at("2026-08-30T09:52:00", prior={"last_run": "2026-08-30T08:00:00"})
        job = _job(schedule=INTERVAL)
        assert rs.is_job_due(job, st, now=datetime(2026, 8, 30, 9, 54)) is False
        assert rs.is_job_due(job, st, now=datetime(2026, 8, 30, 9, 58)) is True

    def test_a_later_success_clears_the_hold(self):
        """Measured on an INTERVAL job, so the hold is the only thing that could

        say no. A daily job would read False after a success for its own reason
        (already ran today), which cannot tell a cleared hold from a live one.
        """
        job = _job(schedule={"type": "interval", "interval_minutes": 1})
        st = self._blocked_at("2026-08-30T09:52:00")
        rs.update_job_runstate(st, "@vera", "release-watch", job["schedule"], timestamp="2026-08-30T09:53:00")
        # 09:55 is still inside the 5-minute hold started at 09:52.
        assert rs.is_job_due(job, st, now=datetime(2026, 8, 30, 9, 55)) is True

    def test_a_failure_after_a_block_still_gets_the_longer_backoff(self):
        st = self._blocked_at("2026-08-30T09:52:00")
        rs.record_job_failure(st, "@vera", "release-watch", "spawn failed", timestamp="2026-08-30T09:58:00")
        assert rs.is_job_due(_job(), st, now=datetime(2026, 8, 30, 10, 4)) is False
        assert rs.is_job_due(_job(), st, now=datetime(2026, 8, 30, 10, 9)) is True


class TestBlockedIsNotAFailureStatus:
    """The read the block must not disturb: what period is this measured from?"""

    def test_a_blocked_entry_still_measures_from_its_last_real_run(self):
        """Listing "blocked" in _FAILURE_STATUSES would make _due_from() answer

        None — "never ran" — for a job that ran perfectly well before it was
        refused once. A block says nothing about whether the period's work was
        done; it says the wake could not start.
        """
        st = {"last_run": "2026-08-29T10:00:11", "last_status": "blocked", "last_blocked_at": "2026-08-30T09:52:00"}
        assert rs._due_from(st) == "2026-08-29T10:00:11"

    def test_a_failed_entry_still_measures_from_nothing(self):
        st = {"last_run": "2026-08-29T10:00:11", "last_status": "failed", "last_failure_at": "2026-08-29T10:00:11"}
        assert rs._due_from(st) is None


class TestTickAccounting:
    """A blocked job is reported as blocked — never as fired, never as failed."""

    def _tick(self, outcome, detail=""):
        runstate = {"jobs": {}}
        with (
            patch(f"{RUN}.discover_jobs", return_value=[_job(schedule=INTERVAL)]),
            patch(f"{RUN}.load_runstate", return_value=runstate),
            patch(f"{RUN}.save_runstate", return_value=True),
            patch(f"{RUN}._fire_job", return_value=(outcome, detail)),
        ):
            return run_tick(), runstate

    def test_blocked_counted_separately(self):
        results, _ = self._tick(OUTCOME_BLOCKED, "blocked: interactive session")
        assert results["blocked"] == 1
        assert results["fired"] == 0
        assert results["failed"] == 0

    def test_blocked_writes_the_blocked_record(self):
        _results, runstate = self._tick(OUTCOME_BLOCKED, "blocked: interactive session")
        entry = runstate["jobs"]["@vera/release-watch"]
        assert entry["last_status"] == "blocked"
        assert "last_run" not in entry

    def test_fired_still_stamps_a_run(self):
        _results, runstate = self._tick(OUTCOME_FIRED)
        assert runstate["jobs"]["@vera/release-watch"]["last_status"] == "success"

    def test_failed_still_stamps_a_run(self):
        _results, runstate = self._tick(OUTCOME_FAILED, "spawn failed")
        entry = runstate["jobs"]["@vera/release-watch"]
        assert entry["last_status"] == "failed"
        assert entry["last_run"]

    @pytest.mark.parametrize(
        "outcome,expected_rc",
        [(OUTCOME_BLOCKED, 0), (OUTCOME_FIRED, 0), (OUTCOME_FAILED, 1)],
        ids=["blocked", "fired", "failed"],
    )
    def test_only_a_real_failure_makes_the_tick_exit_red(self, outcome, expected_rc, tmp_path):
        """A deferral is not a tick failure — the systemd unit must not read red.

        LOCK_FILE is seamed to tmp_path: the live daemon_json/schedule.lock is
        the one the systemd timer takes every two minutes, and a test grabbing
        it would either skip its own tick or make the real one skip.
        """
        with (
            patch(f"{RUN}.LOCK_FILE", tmp_path / "schedule.lock"),
            patch(f"{RUN}.discover_jobs", return_value=[_job(schedule=INTERVAL)]),
            patch(f"{RUN}.load_runstate", return_value={"jobs": {}}),
            patch(f"{RUN}.save_runstate", return_value=True),
            patch(f"{RUN}._fire_job", return_value=(outcome, "detail")),
        ):
            assert run_mod._run_with_lock(dry_run=False) == expected_rc


class TestRotationIsUnchanged:
    """A rotation miss already advances the pointer — it must keep consuming the night."""

    def test_rotation_miss_is_not_reclassified_as_blocked(self):
        job = _job(schedule={"type": "rotation", "time": "05:00"}, owner="@daemon", job_id="fleet-steward")
        with patch(f"{RUN}.fire_rotation", return_value=(True, "missed @backup: lock")) as mock_rotation:
            outcome, detail = _fire_job(job, {"jobs": {}})
        assert outcome == OUTCOME_FIRED
        assert detail == "missed @backup: lock"
        mock_rotation.assert_called_once()

    def test_rotation_failure_is_a_failure(self):
        job = _job(schedule={"type": "rotation", "time": "05:00"}, owner="@daemon", job_id="fleet-steward")
        with patch(f"{RUN}.fire_rotation", return_value=(False, "rotation roster is empty")):
            outcome, _detail = _fire_job(job, {"jobs": {}})
        assert outcome == OUTCOME_FAILED
