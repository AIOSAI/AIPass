# =================== AIPass ====================
# Name: runstate.py
# Description: Daemon runstate tracking and due-logic for decentralized scheduler
# Version: 1.4.0
# Created: 2026-06-15
# Modified: 2026-08-31
# =============================================

"""
Daemon runstate — tracks last_run/next_run per job and evaluates due-ness.

Due-logic lifted verbatim from actions_registry.py (DPLAN-043), re-keyed
to composite 'owner/id' strings for the decentralized .daemon/ model.

Part of the DPLAN-0204 decentralized scheduler redesign.
"""

import json
from datetime import datetime, timedelta
from typing import Optional

from aipass.prax import logger
from aipass.daemon.apps.handlers.json import json_handler
from aipass.daemon.apps.handlers.module_root import module_file

_DAEMON_ROOT = module_file(__file__).parents[3]  # src/aipass/daemon/
RUNSTATE_FILE = _DAEMON_ROOT / "daemon_json" / "daemon_runstate.json"


def _empty_runstate() -> dict:
    """Return a fresh empty runstate structure."""
    return {"version": 1, "jobs": {}}


def load_runstate() -> dict:
    """Load daemon_runstate.json. Returns empty runstate if missing."""
    if not RUNSTATE_FILE.exists():
        return _empty_runstate()
    try:
        with open(RUNSTATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if "jobs" not in data:
            data["jobs"] = {}
        return data
    except (json.JSONDecodeError, OSError) as e:
        logger.error("[runstate] Failed to load: %s", e)
        return _empty_runstate()


def save_runstate(data: dict) -> bool:
    """Save daemon_runstate.json. Returns True on success."""
    try:
        RUNSTATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(RUNSTATE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        return True
    except OSError as e:
        logger.error("[runstate] Failed to save: %s", e)
        return False


def job_key(owner: str, job_id: str) -> str:
    """Build composite key for runstate lookup."""
    return f"{owner}/{job_id}"


def get_job_state(runstate: dict, owner: str, job_id: str) -> dict:
    """Get runstate entry for a job. Returns empty dict if not tracked."""
    return runstate.get("jobs", {}).get(job_key(owner, job_id), {})


# =============================================
# DUE CHECKING (lifted from actions_registry.py)
# =============================================


def _already_ran_today(last_run: Optional[str], now: datetime) -> bool:
    """Check if a daily job already ran today."""
    if not last_run:
        return False
    try:
        last_dt = datetime.fromisoformat(last_run)
        return last_dt.date() == now.date()
    except (ValueError, TypeError) as e:
        logger.info("[runstate] Daily last_run parse failed: %s", e)
        return False


def _already_ran_this_hour(last_run: Optional[str], now: datetime) -> bool:
    """Check if an hourly job already ran this hour."""
    if not last_run:
        return False
    try:
        last_dt = datetime.fromisoformat(last_run)
        return last_dt.hour == now.hour and last_dt.date() == now.date()
    except (ValueError, TypeError) as e:
        logger.info("[runstate] Hourly last_run parse failed: %s", e)
        return False


def _is_daily_due(schedule: dict, last_run: Optional[str], now: datetime) -> bool:
    """Check if a daily job is due (within +/-15 min window)."""
    target_time = schedule.get("time", "00:00")
    try:
        target_h, target_m = map(int, target_time.split(":"))
    except (ValueError, AttributeError) as e:
        logger.info("[runstate] Daily time parse failed for %r: %s", target_time, e)
        return False
    current_minutes = now.hour * 60 + now.minute
    target_minutes = target_h * 60 + target_m
    minutes_diff = abs(current_minutes - target_minutes)
    minutes_diff = min(minutes_diff, 1440 - minutes_diff)
    if minutes_diff > 15:
        return False
    return not _already_ran_today(last_run, now)


def _is_hourly_due(schedule: dict, last_run: Optional[str], now: datetime) -> bool:
    """Check if an hourly job is due (within +/-15 min window)."""
    target_m_str = schedule.get("time", "0")
    try:
        target_m = int(target_m_str)
    except (ValueError, TypeError) as e:
        logger.info("[runstate] Hourly time parse failed for %r: %s", target_m_str, e)
        return False
    minutes_diff = abs(now.minute - target_m)
    minutes_diff = min(minutes_diff, 60 - minutes_diff)
    if minutes_diff > 15:
        return False
    return not _already_ran_this_hour(last_run, now)


def _is_interval_due(schedule: dict, last_run: Optional[str], now: datetime) -> bool:
    """Check if an interval job is due (elapsed >= interval_minutes since last_run)."""
    interval = schedule.get("interval_minutes", 60)
    if not last_run:
        return True
    try:
        last_dt = datetime.fromisoformat(last_run)
        elapsed = (now - last_dt).total_seconds() / 60
        return elapsed >= interval
    except (ValueError, TypeError) as e:
        logger.info("[runstate] Interval last_run parse failed: %s", e)
        return True


def _is_once_due(schedule: dict, completed: Optional[str], now: datetime) -> bool:
    """Check if a one-shot job is due (due_date <= today, not completed)."""
    if completed:
        return False
    due_date = schedule.get("due_date")
    if not due_date:
        return False
    try:
        due_dt = (
            datetime.fromisoformat(due_date).date()
            if "T" in due_date
            else datetime.strptime(due_date, "%Y-%m-%d").date()
        )
        return now.date() >= due_dt
    except (ValueError, TypeError) as e:
        logger.info("[runstate] Once due_date parse failed for %r: %s", due_date, e)
        return False


# A failed fire buys a short pause, not the rest of the period. The scheduler
# ticks about every two minutes and the windowed schedules allow +/-15, so
# without a bound a permanently-broken daily job would spawn ~8 agents a day.
# Ten minutes leaves room for a couple of honest retries inside one window.
_FAILURE_BACKOFF_MINUTES = 10

# A BLOCKED fire never started anything, so it buys an even shorter pause than a
# failure: the target is busy, which is a transient fact about the world and the
# retry is the point. The bound still has to exist. An interval job measures from
# its last ATTEMPT and a block writes no attempt, so with no hold at all a
# blocked-forever interval job would re-attempt on every ~2-minute tick for as
# long as the target stayed occupied. Five minutes still leaves ~5 attempts
# inside a windowed schedule's +/-15.
_BLOCKED_RETRY_MINUTES = 5

# Statuses record_job_failure() writes. Anything else - "success", "blocked", or
# a legacy entry with no status at all - is read as a completed run.
#
# "blocked" is deliberately NOT here. A block leaves last_run untouched, so
# _due_from() falls through to whatever the last real run wrote; listing it here
# would make the read say "never ran" for a job that ran fine yesterday.
_FAILURE_STATUSES = frozenset({"failed", "error", "timeout"})


def _due_from(state: dict) -> Optional[str]:
    """The timestamp a WINDOWED schedule should measure its period from.

    ``last_run`` means "when did this last ATTEMPT" - the failure path stamps
    it too, and the queue display depends on that. Due-ness asks a different
    question: has this period's work been DONE? So it measures from the last
    SUCCESS, and a failed fire no longer consumes the day it failed in.

    Legacy entries predating ``last_success_at`` carry only ``last_run`` and a
    status. Those are read as runs: absence of a failure marker is not evidence
    of a failure, and treating them as never-succeeded would re-fire every
    already-done job on the machine the moment this landed.
    """
    success = state.get("last_success_at")
    if success:
        return success
    if state.get("last_status") in _FAILURE_STATUSES:
        return None
    return state.get("last_run")


def _in_failure_backoff(state: dict, now: datetime) -> bool:
    """True while a recent failure should hold off the next attempt."""
    failed_at = state.get("last_failure_at")
    if not failed_at:
        return False
    # A later success clears the hold - the old last_failure_at stays in the
    # record as history and must not keep braking a job that recovered.
    success = state.get("last_success_at")
    if success and success >= failed_at:
        return False
    try:
        failed_dt = datetime.fromisoformat(failed_at)
    except (ValueError, TypeError) as e:
        logger.info("[runstate] Failure backoff parse failed for %r: %s", failed_at, e)
        return False
    return (now - failed_dt) < timedelta(minutes=_FAILURE_BACKOFF_MINUTES)


def _in_blocked_hold(state: dict, now: datetime) -> bool:
    """True while a recent BLOCK should space out the next attempt.

    Separate from the failure backoff because it answers a different question.
    A failure means the wake ran and went wrong; a block means it never started
    at all - the target was busy, paused, or already held the lock. The job's
    period is untouched either way, but the block is both cheaper to retry (no
    agent spawns) and likelier to clear on its own, so it holds for less time.
    """
    blocked_at = state.get("last_blocked_at")
    if not blocked_at:
        return False
    # Anything that happened AFTER the block ends the hold: a success means the
    # target freed up, and a failure hands the job to the longer failure
    # backoff. The old last_blocked_at stays in the record as history.
    for later in (state.get("last_success_at"), state.get("last_failure_at")):
        if later and later >= blocked_at:
            return False
    try:
        blocked_dt = datetime.fromisoformat(blocked_at)
    except (ValueError, TypeError) as e:
        logger.info("[runstate] Blocked hold parse failed for %r: %s", blocked_at, e)
        return False
    return (now - blocked_dt) < timedelta(minutes=_BLOCKED_RETRY_MINUTES)


def is_job_due(job: dict, runstate: dict, now: Optional[datetime] = None) -> bool:
    """
    Check if a discovered job should fire now.

    Merges job schedule info with runstate tracking data.

    ``now`` is injectable so due-ness can be asserted against a stated instant.
    Every helper below already took its clock as an argument; this function was
    the one that reached for datetime.now() itself, which made the behaviour
    around a window boundary untestable except by luck of the wall clock.
    """
    if not job.get("enabled", True):
        return False

    state = get_job_state(runstate, job["owner"], job["id"])
    last_run = state.get("last_run")
    completed = state.get("completed")
    if now is None:
        now = datetime.now()

    if _in_failure_backoff(state, now):
        return False

    if _in_blocked_hold(state, now):
        return False

    # Windowed schedules measure from the last SUCCESS; interval measures from
    # the last ATTEMPT. That split is deliberate, not an oversight: an interval
    # job measured from its last success would be due on EVERY tick forever
    # once it started failing, because the elapsed time only grows. Its
    # interval is already the bound it needs.
    since_success = _due_from(state)

    schedule = job.get("schedule", {})
    sched_type = schedule.get("type", "")

    checkers = {
        "daily": lambda: _is_daily_due(schedule, since_success, now),
        # A rotation job is a daily job that picks a different target each night.
        "rotation": lambda: _is_daily_due(schedule, since_success, now),
        "hourly": lambda: _is_hourly_due(schedule, since_success, now),
        "interval": lambda: _is_interval_due(schedule, last_run, now),
        "once": lambda: _is_once_due(schedule, completed, now),
    }

    checker = checkers.get(sched_type)
    if checker is None:
        return False
    return checker()


# =============================================
# RUNSTATE UPDATES
# =============================================


def _calc_next_run(schedule: dict, last_run_ts: str) -> Optional[str]:
    """Calculate the next run time given schedule and a last_run timestamp.

    Every branch answers from LAST_RUN_TS, never from the wall clock. That is
    the fix for a live defect, not a refactor: @vera's `daily @ 10:00` fired at
    09:45:11 - the legitimate leading edge of the +/-15min window - and the old
    daily branch, reading now(), advertised next_run = 10:00 THE SAME DAY. But
    _already_ran_today consumes the whole calendar day, so is_job_due answered
    False right through 10:14 and True only the next morning. The field named a
    wake that could not happen.

    The rule the windowed branches follow is the one is_job_due enforces: firing
    consumes the PERIOD, not the instant. A daily fire consumes its calendar day
    whenever in the window it landed, so the next one is the following day at
    target; an hourly fire consumes its clock hour. Interval already did this
    correctly - it was the only branch using the argument it was handed, which
    is the whole tell.

    KNOWN AND DELIBERATE SLACK: this returns the TARGET time, while the
    scheduler will actually fire up to 15 minutes earlier, at the leading edge
    of the window. Returning target-15min was considered and rejected - "daily @
    10:00" is what the owner configured and what the queue should echo, and the
    alternative puts window arithmetic into a field whose readers are humans.
    The pin in test_next_run_agrees_with_due.py allows exactly that much
    earliness and no more, so under-reporting by a whole PERIOD stays red.

    Args:
        schedule: The job's schedule block.
        last_run_ts: ISO timestamp of the firing this next_run follows.

    Returns:
        ISO timestamp of the next run, or None if the schedule cannot be parsed.
    """
    sched_type = schedule.get("type", "")

    if sched_type in ("daily", "rotation"):
        target_time = schedule.get("time", "00:00")
        try:
            target_h, target_m = map(int, target_time.split(":"))
        except (ValueError, AttributeError) as e:
            logger.info("[runstate] calc_next_run daily time parse failed: %s", e)
            return None
        try:
            last_dt = datetime.fromisoformat(last_run_ts)
        except (ValueError, TypeError) as e:
            logger.info("[runstate] calc_next_run daily last_run parse failed: %s", e)
            return None
        # The day of last_run is spent, whenever in its window the fire landed.
        next_dt = (last_dt + timedelta(days=1)).replace(hour=target_h, minute=target_m, second=0, microsecond=0)
        return next_dt.isoformat()

    if sched_type == "hourly":
        target_m_str = schedule.get("time", "0")
        try:
            target_m = int(target_m_str)
        except (ValueError, TypeError) as e:
            logger.info("[runstate] calc_next_run hourly time parse failed: %s", e)
            return None
        try:
            last_dt = datetime.fromisoformat(last_run_ts)
        except (ValueError, TypeError) as e:
            logger.info("[runstate] calc_next_run hourly last_run parse failed: %s", e)
            return None
        # The clock hour of last_run is spent, same rule one unit down.
        next_dt = (last_dt + timedelta(hours=1)).replace(minute=target_m, second=0, microsecond=0)
        return next_dt.isoformat()

    if sched_type == "interval":
        interval = schedule.get("interval_minutes", 60)
        try:
            last_dt = datetime.fromisoformat(last_run_ts)
            return (last_dt + timedelta(minutes=interval)).isoformat()
        except (ValueError, TypeError) as e:
            # None, like every other parse failure here. The old form returned
            # now(), which advertises "due immediately" for a job whose schedule
            # could not be read - the loudest possible wrong answer.
            logger.info("[runstate] calc_next_run interval parse failed: %s", e)
            return None

    if sched_type == "once":
        return schedule.get("due_date")

    return None


def update_job_runstate(
    runstate: dict,
    owner: str,
    job_id: str,
    schedule: dict,
    timestamp: Optional[str] = None,
) -> None:
    """Update runstate for a job after successful firing."""
    if timestamp is None:
        timestamp = datetime.now().isoformat()

    key = job_key(owner, job_id)
    entry = runstate.setdefault("jobs", {}).setdefault(key, {})
    entry["last_run"] = timestamp
    entry["next_run"] = _calc_next_run(schedule, timestamp)
    entry["last_status"] = "success"
    entry["last_success_at"] = timestamp
    entry["last_error"] = None

    if schedule.get("type") == "once":
        entry["completed"] = timestamp

    json_handler.log_operation("update_job_runstate", {"key": key})


def record_job_failure(
    runstate: dict,
    owner: str,
    job_id: str,
    error_msg: str,
    status: str = "failed",
    timestamp: Optional[str] = None,
) -> None:
    """Record a failed job firing in runstate."""
    if timestamp is None:
        timestamp = datetime.now().isoformat()

    key = job_key(owner, job_id)
    entry = runstate.setdefault("jobs", {}).setdefault(key, {})
    entry["last_run"] = timestamp
    entry["last_status"] = status
    entry["last_failure_at"] = timestamp
    entry["last_error"] = error_msg[:500]

    json_handler.log_operation("record_job_failure", {"key": key, "status": status})


def record_job_blocked(
    runstate: dict,
    owner: str,
    job_id: str,
    reason: str,
    timestamp: Optional[str] = None,
) -> None:
    """Record a fire that never STARTED - the target was busy, not broken.

    BLOCKED IS NOT RAN. Unlike both other writers this one leaves ``last_run``
    alone, because ``last_run`` means "when did this last attempt actually
    happen" and a refused wake is not an attempt that happened. Stamping it was
    the reported defect: a leftover interactive session in a branch made the
    scheduler record a run it never made, and the next day's fire was suppressed
    by a room nobody was sitting in.

    ``last_failure_at`` is left alone too - a block is not a failure and must
    not arm the failure backoff. ``last_blocked_at`` carries its own, shorter
    hold (see ``_in_blocked_hold``).
    """
    if timestamp is None:
        timestamp = datetime.now().isoformat()

    key = job_key(owner, job_id)
    entry = runstate.setdefault("jobs", {}).setdefault(key, {})
    entry["last_status"] = "blocked"
    entry["last_blocked_at"] = timestamp
    entry["last_error"] = reason[:500]

    json_handler.log_operation("record_job_blocked", {"key": key})


def prune_orphans(runstate: dict, active_keys: set) -> int:
    """Remove runstate entries for jobs that no longer exist. Returns count pruned."""
    jobs = runstate.get("jobs", {})
    orphans = set(jobs.keys()) - active_keys
    for key in orphans:
        del jobs[key]
    if orphans:
        logger.info("[runstate] Pruned %d orphan runstate entries", len(orphans))
    return len(orphans)
