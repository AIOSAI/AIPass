# =================== AIPass ====================
# Name: runstate.py
# Description: Daemon runstate tracking and due-logic for decentralized scheduler
# Version: 1.7.0
# Created: 2026-06-15
# Modified: 2026-10-23
# =============================================

"""
Daemon runstate — tracks last_run/next_run per job and evaluates due-ness.
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


def _already_ran_today(last_run: Optional[str], now: datetime) -> bool:
    """Check if a daily job already ran today; an unreadable last_run answers no (one early fire)."""
    if not last_run:
        return False
    try:
        last_dt = datetime.fromisoformat(last_run)
        return last_dt.date() == now.date()
    except (ValueError, TypeError) as e:
        logger.info("[runstate] Daily last_run parse failed: %s", e)
        return False


def _already_ran_this_hour(last_run: Optional[str], now: datetime) -> bool:
    """Check if an hourly job already ran this hour; an unreadable last_run answers no (one early fire)."""
    if not last_run:
        return False
    try:
        last_dt = datetime.fromisoformat(last_run)
        return last_dt.hour == now.hour and last_dt.date() == now.date()
    except (ValueError, TypeError) as e:
        logger.info("[runstate] Hourly last_run parse failed: %s", e)
        return False


# Firing-window half-width; window_closed_unrun reads the same name, so fire and catch-up edge move together.
WINDOW_MINUTES = 15

MINUTES_PER_DAY = 1440


def _target_minutes(schedule: dict) -> Optional[int]:
    """Minutes past midnight of a daily/rotation job's target time; None (unreadable) means no window."""
    target_time = schedule.get("time", "00:00")
    try:
        target_h, target_m = map(int, target_time.split(":"))
    except (ValueError, AttributeError) as e:
        logger.info("[runstate] Daily time parse failed for %r: %s", target_time, e)
        return None
    return target_h * 60 + target_m


def _is_daily_due(schedule: dict, last_run: Optional[str], now: datetime) -> bool:
    """Check if a daily job is due (within +/-15 min window)."""
    target_minutes = _target_minutes(schedule)
    if target_minutes is None:
        return False
    current_minutes = now.hour * 60 + now.minute
    minutes_diff = abs(current_minutes - target_minutes)
    minutes_diff = min(minutes_diff, MINUTES_PER_DAY - minutes_diff)
    if minutes_diff > WINDOW_MINUTES:
        return False
    return not _already_ran_today(last_run, now)


def _is_hourly_due(schedule: dict, last_run: Optional[str], now: datetime) -> bool:
    """Check if an hourly job is due (within +/-15 min window). An unreadable time is never due."""
    target_m_str = schedule.get("time", "0")
    try:
        target_m = int(target_m_str)
    except (ValueError, TypeError) as e:
        logger.info("[runstate] Hourly time parse failed for %r: %s", target_m_str, e)
        return False
    minutes_diff = abs(now.minute - target_m)
    minutes_diff = min(minutes_diff, 60 - minutes_diff)
    if minutes_diff > WINDOW_MINUTES:
        return False
    return not _already_ran_this_hour(last_run, now)


def _is_interval_due(schedule: dict, last_run: Optional[str], now: datetime) -> bool:
    """Check if an interval job is due (elapsed >= interval_minutes since last_run).

    A non-positive interval is never due (it would fire every tick); an unreadable last_run is due (one fire).
    """
    interval = schedule.get("interval_minutes", 60)
    if isinstance(interval, bool) or not isinstance(interval, (int, float)) or interval <= 0:
        logger.warning("[runstate] Interval job not due: interval_minutes %r is not a positive number", interval)
        return False
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
    """Check if a one-shot job is due (due_date <= today, not completed).

    An unreadable due_date is never due: a one-shot fired early cannot be taken back.
    """
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


# Per-job schedule field; a job whose late run is worthless sets it false.
CATCH_UP_FIELD = "catch_up"

# The systemd tick runs this working tree, so nothing under this flag may be True unless someone watches a tick.
# False: catch_up is opt-in, no gap detection, no queue, no drain. Reference: docs/recovery_and_catch_up.md
RECOVERY_LANE_LIVE = False

_DAILY_TYPES = frozenset({"daily", "rotation"})

_WINDOWED_TYPES = frozenset({"daily", "rotation", "hourly"})

# Runstate key: the date whose miss was already reported, so MISSED logs once per job per day.
MISSED_MARKER = "missed_logged_for"


def window_closed_unrun(schedule: dict, last_run: Optional[str], now: datetime) -> bool:
    """True when TODAY's daily window has closed with nothing run inside it.

    MISSED and catch-up both read this one predicate, so they never disagree; callers pass _due_from().
    A window whose tail crosses midnight answers False: no instant makes the miss certain.
    """
    target_minutes = _target_minutes(schedule)
    if target_minutes is None:
        return False

    close_minutes = target_minutes + WINDOW_MINUTES
    if close_minutes >= MINUTES_PER_DAY:
        return False

    if now.hour * 60 + now.minute <= close_minutes:
        return False

    return not _already_ran_today(last_run, now)


def catch_up_on(schedule: dict) -> bool:
    """Is catch-up enabled for this schedule? Opt-in while RECOVERY_LANE_LIVE is False, else ON unless false."""
    if not RECOVERY_LANE_LIVE:
        return schedule.get(CATCH_UP_FIELD) is True
    return schedule.get(CATCH_UP_FIELD) is not False


def _hourly_window_closed_unrun(schedule: dict, last_run: Optional[str], now: datetime) -> bool:
    """True when THIS HOUR's window has closed with nothing run inside it.

    False for an unreadable time or a tail crossing the hour, as window_closed_unrun refuses midnight.
    """
    raw = schedule.get("time", "0")
    try:
        target_m = int(raw)
    except (ValueError, TypeError) as e:
        logger.info("[runstate] Hourly time parse failed for %r: %s", raw, e)
        return False

    close_minute = target_m + WINDOW_MINUTES
    if close_minute >= 60:
        return False
    if now.minute <= close_minute:
        return False
    return not _already_ran_this_hour(last_run, now)


def _is_catch_up_due(schedule: dict, last_run: Optional[str], now: datetime) -> bool:
    """True when a windowed job should fire late, after its window closed unrun."""
    if not catch_up_on(schedule):
        return False
    if schedule.get("type") == "hourly":
        return _hourly_window_closed_unrun(schedule, last_run, now)
    return window_closed_unrun(schedule, last_run, now)


def is_catch_up_fire(job: dict, runstate: dict, now: Optional[datetime] = None) -> bool:
    """Would firing *job* at *now* be a catch-up rather than a window run?"""
    schedule = job.get("schedule", {})
    if schedule.get("type") not in _WINDOWED_TYPES:
        return False
    if now is None:
        now = datetime.now()
    state = get_job_state(runstate, job["owner"], job["id"])
    return _is_catch_up_due(schedule, _due_from(state), now)


def missed_window(job: dict, runstate: dict, now: Optional[datetime] = None) -> bool:
    """Did *job* miss today's window, catch_up or not?"""
    schedule = job.get("schedule", {})
    sched_type = schedule.get("type")
    if sched_type not in _WINDOWED_TYPES:
        return False
    if now is None:
        now = datetime.now()
    state = get_job_state(runstate, job["owner"], job["id"])
    if sched_type == "hourly":
        return _hourly_window_closed_unrun(schedule, _due_from(state), now)
    return window_closed_unrun(schedule, _due_from(state), now)


def failed_today_at(runstate: dict, owner: str, job_id: str, now: Optional[datetime] = None) -> str:
    """'HH:MM' of the job's last failure when it is stamped today, else ''. Read as text: stamps are isoformat."""
    if now is None:
        now = datetime.now()
    stamp = get_job_state(runstate, owner, job_id).get("last_failure_at")
    if not isinstance(stamp, str) or not stamp.startswith(now.date().isoformat() + "T"):
        return ""
    return stamp[11:16]


def note_missed_window(runstate: dict, owner: str, job_id: str, now: Optional[datetime] = None) -> bool:
    """Stamp today's miss as reported. True when this call is the FIRST for today."""
    if now is None:
        now = datetime.now()
    key = job_key(owner, job_id)
    entry = runstate.setdefault("jobs", {}).setdefault(key, {})
    today = now.date().isoformat()
    if entry.get(MISSED_MARKER) == today:
        return False
    entry[MISSED_MARKER] = today
    return True


def window_label(schedule: dict) -> str:
    """Human name for the window a MISSED line is reporting, e.g. "03:00 +/-15m"."""
    return f"{schedule.get('time', '??:??')} +/-{WINDOW_MINUTES}m"


# Per-job ISO instant naming one occurrence of an interval job's rhythm. Reference: docs/schedule_contract.md
SLOT_FIELD = "slot"


def _slot_anchor(slot: str, interval: int, now: datetime) -> Optional[datetime]:
    """The slot occurrence to seed ``last_run`` with, or None if unreadable.

    A past slot rolls forward by whole intervals to keep its phase; a future one is seeded one interval behind.
    None also for a non-positive interval, which _is_interval_due never fires.
    """
    try:
        anchor = datetime.fromisoformat(slot)
    except (ValueError, TypeError) as e:
        logger.warning("[runstate] Unreadable slot %r: %s", slot, e)
        return None

    if isinstance(interval, bool) or not isinstance(interval, (int, float)) or interval <= 0:
        logger.warning("[runstate] Slot %r with non-positive interval %r, not seeding", slot, interval)
        return None

    if anchor > now:
        return anchor - timedelta(minutes=interval)

    steps = int((now - anchor).total_seconds() / 60 // interval)
    return anchor + timedelta(minutes=steps * interval)


def needs_slot_seed(job: dict, runstate: dict) -> bool:
    """True for an enabled interval job that has never actually RUN.

    Keyed on last_run, not row presence: a blocked fire writes a row with no last_run.
    """
    if not job.get("enabled", True):
        return False
    if job.get("schedule", {}).get("type") != "interval":
        return False
    return not get_job_state(runstate, job["owner"], job["id"]).get("last_run")


def seed_interval_slot(runstate: dict, job: dict, now: Optional[datetime] = None) -> Optional[str]:
    """Seed a never-run interval job's ``last_run`` from its declared slot.

    None for no readable slot (fires next tick) or no positive interval (never fires); callers warn on None.
    """
    schedule = job.get("schedule", {})
    slot = schedule.get(SLOT_FIELD)
    if not slot:
        return None

    if now is None:
        now = datetime.now()

    anchor = _slot_anchor(slot, schedule.get("interval_minutes", 60), now)
    if anchor is None:
        return None

    seeded = anchor.isoformat()
    key = job_key(job["owner"], job["id"])
    entry = runstate.setdefault("jobs", {}).setdefault(key, {})
    entry["last_run"] = seeded
    entry["next_run"] = _calc_next_run(schedule, seeded)
    entry["seeded_from_slot"] = slot

    logger.info("[runstate] Seeded %s from slot %s -> last_run %s", key, slot, seeded)
    json_handler.log_operation("seed_interval_slot", {"key": key, "slot": slot})
    return seeded


# Without a bound a broken windowed job would spawn an agent on every ~2-minute tick of its window.
_FAILURE_BACKOFF_MINUTES = 10

# A block writes no attempt, so without this hold a blocked interval job would retry every tick.
_BLOCKED_RETRY_MINUTES = 5

# Not "blocked": a block leaves last_run untouched, so listing it would read "never ran".
_FAILURE_STATUSES = frozenset({"failed", "error", "timeout"})


def _due_from(state: dict) -> Optional[str]:
    """The timestamp a WINDOWED schedule should measure its period from.

    The last SUCCESS, since last_run also stamps failures; a legacy row with no failure status reads as a run.
    """
    success = state.get("last_success_at")
    if success:
        return success
    if state.get("last_status") in _FAILURE_STATUSES:
        return None
    return state.get("last_run")


def _in_failure_backoff(state: dict, now: datetime) -> bool:
    """True while a recent failure should hold off the next attempt.

    An unreadable last_failure_at answers no hold (it could never expire); an unreadable success lifts nothing.
    """
    failed_at = state.get("last_failure_at")
    if not failed_at:
        return False
    try:
        failed_dt = datetime.fromisoformat(failed_at)
    except (ValueError, TypeError) as e:
        logger.info("[runstate] Failure backoff parse failed for %r: %s", failed_at, e)
        return False
    success = state.get("last_success_at")
    if success:
        try:
            if datetime.fromisoformat(success) >= failed_dt:
                return False
        except (ValueError, TypeError) as e:
            logger.warning("[runstate] Unreadable last_success_at %r does not lift the failure backoff: %s", success, e)
    return (now - failed_dt) < timedelta(minutes=_FAILURE_BACKOFF_MINUTES)


def _in_blocked_hold(state: dict, now: datetime) -> bool:
    """True while a recent BLOCK should space out the next attempt.

    An unreadable last_blocked_at answers no hold (it could never expire); an unreadable later stamp lifts nothing.
    """
    blocked_at = state.get("last_blocked_at")
    if not blocked_at:
        return False
    try:
        blocked_dt = datetime.fromisoformat(blocked_at)
    except (ValueError, TypeError) as e:
        logger.info("[runstate] Blocked hold parse failed for %r: %s", blocked_at, e)
        return False
    # A later failure ends the hold too: the longer failure backoff takes over.
    for key in ("last_success_at", "last_failure_at"):
        later = state.get(key)
        if not later:
            continue
        try:
            if datetime.fromisoformat(later) >= blocked_dt:
                return False
        except (ValueError, TypeError) as e:
            logger.warning("[runstate] Unreadable %s %r does not lift the blocked hold: %s", key, later, e)
    return (now - blocked_dt) < timedelta(minutes=_BLOCKED_RETRY_MINUTES)


def is_job_due(job: dict, runstate: dict, now: Optional[datetime] = None) -> bool:
    """Check if a discovered job should fire now."""
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

    # Interval measures from the last attempt, not success: measured from success, a failing one is due every tick.
    since_success = _due_from(state)

    schedule = job.get("schedule", {})
    sched_type = schedule.get("type", "")

    # _already_ran_today bounds both arms, so a caught-up run never double-fires its day.
    checkers = {
        "daily": lambda: _is_daily_due(schedule, since_success, now) or _is_catch_up_due(schedule, since_success, now),
        "rotation": lambda: (
            _is_daily_due(schedule, since_success, now) or _is_catch_up_due(schedule, since_success, now)
        ),
        "hourly": lambda: (
            _is_hourly_due(schedule, since_success, now) or _is_catch_up_due(schedule, since_success, now)
        ),
        "interval": lambda: _is_interval_due(schedule, last_run, now),
        "once": lambda: _is_once_due(schedule, completed, now),
    }

    checker = checkers.get(sched_type)
    if checker is None:
        return False
    return checker()


def _calc_next_run(schedule: dict, last_run_ts: str) -> Optional[str]:
    """Calculate the next run time given schedule and a last_run timestamp.

    From last_run_ts, never the wall clock: a fire consumes its whole period, as is_job_due enforces.
    Returns the target time, not the window's early edge; None for any unreadable field (display only).
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
        next_dt = (last_dt + timedelta(hours=1)).replace(minute=target_m, second=0, microsecond=0)
        return next_dt.isoformat()

    if sched_type == "interval":
        interval = schedule.get("interval_minutes", 60)
        if isinstance(interval, bool) or not isinstance(interval, (int, float)) or interval <= 0:
            logger.info("[runstate] calc_next_run: interval_minutes %r is not a positive number", interval)
            return None
        try:
            last_dt = datetime.fromisoformat(last_run_ts)
            return (last_dt + timedelta(minutes=interval)).isoformat()
        except (ValueError, TypeError) as e:
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
    caught_up: bool = False,
) -> None:
    """Update runstate for a job after successful firing.

    caught_up is cleared to None on an ordinary run, or a stale marker would report a healthy job as late.
    """
    if timestamp is None:
        timestamp = datetime.now().isoformat()

    key = job_key(owner, job_id)
    entry = runstate.setdefault("jobs", {}).setdefault(key, {})
    entry["last_run"] = timestamp
    entry["next_run"] = _calc_next_run(schedule, timestamp)
    entry["last_status"] = "success"
    entry["last_success_at"] = timestamp
    entry["last_error"] = None
    entry["caught_up"] = timestamp if caught_up else None

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
    schedule: Optional[dict] = None,
) -> None:
    """Record a failed job firing in runstate.

    An interval job's next fire measures from this attempt, so its next_run moves too; a windowed job retries in-window.
    """
    if timestamp is None:
        timestamp = datetime.now().isoformat()

    key = job_key(owner, job_id)
    entry = runstate.setdefault("jobs", {}).setdefault(key, {})
    entry["last_run"] = timestamp
    entry["last_status"] = status
    entry["last_failure_at"] = timestamp
    entry["last_error"] = error_msg[:500]
    if schedule and schedule.get("type") == "interval":
        entry["next_run"] = _calc_next_run(schedule, timestamp)

    json_handler.log_operation("record_job_failure", {"key": key, "status": status})


def record_job_blocked(
    runstate: dict,
    owner: str,
    job_id: str,
    reason: str,
    timestamp: Optional[str] = None,
) -> None:
    """Record a fire that never STARTED - the target was busy, not broken.

    Leaves last_run and last_failure_at alone: a refused wake is no attempt and must not arm the failure backoff.
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
