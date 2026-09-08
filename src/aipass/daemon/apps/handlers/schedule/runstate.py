# =================== AIPass ====================
# Name: runstate.py
# Description: Daemon runstate tracking and due-logic for decentralized scheduler
# Version: 1.5.0
# Created: 2026-06-15
# Modified: 2026-09-07
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


# Half-width of a windowed schedule's firing window, in minutes. Daily, rotation
# and hourly all fire inside +/-this, and _window_closed_today() measures the far
# edge from the same name — so widening the window cannot move the fire while
# leaving the catch-up reading the old edge.
WINDOW_MINUTES = 15

MINUTES_PER_DAY = 1440


def _target_minutes(schedule: dict) -> Optional[int]:
    """Minutes past midnight of a daily/rotation job's target time.

    Returns None when the field cannot be read, which every caller treats as
    "this schedule states no window" rather than as a window at 00:00.
    """
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
    """Check if an hourly job is due (within +/-15 min window)."""
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


# =============================================
# CLOSED WINDOWS — catch-up and the MISSED record
# =============================================

# Per-job opt-in, read from the job's ``schedule`` block alongside ``type`` and
# ``time``. Absent means off, which is every job that exists today.
CATCH_UP_FIELD = "catch_up"

# Schedule types that fire inside a daily window and can therefore MISS one.
_DAILY_TYPES = frozenset({"daily", "rotation"})

# Runstate key: the calendar date whose miss has already been reported, so the
# MISSED line is written once per job per day rather than on every tick for the
# rest of the day.
MISSED_MARKER = "missed_logged_for"


def window_closed_unrun(schedule: dict, last_run: Optional[str], now: datetime) -> bool:
    """True when TODAY's daily window has closed with nothing run inside it.

    This is the single fact both new behaviours read. The MISSED line reports
    it for every daily job; ``catch_up`` additionally makes it a reason to fire.
    Keeping them on one predicate is what guarantees a caught-up run and its log
    line can never disagree about whether the window was actually missed.

    MEASURED FROM THE SAME TIMESTAMP AS DUE-NESS. Callers pass ``_due_from()``,
    so a fire that FAILED inside the window leaves the window genuinely unrun -
    which is the honest reading, and the one that lets catch_up retry it.

    A WINDOW WHOSE TAIL CROSSES MIDNIGHT NEVER CLOSES inside its own calendar
    day (``time`` later than 23:44), so there is no instant at which today's
    miss is certain. Those are refused rather than guessed: a false MISSED line
    accuses a job that may still fire in the next few minutes, and a false
    catch-up double-fires it.
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


def _is_catch_up_due(schedule: dict, last_run: Optional[str], now: datetime) -> bool:
    """True when an opted-in daily job should fire late, after its closed window."""
    if not schedule.get(CATCH_UP_FIELD):
        return False
    return window_closed_unrun(schedule, last_run, now)


def is_catch_up_fire(job: dict, runstate: dict, now: Optional[datetime] = None) -> bool:
    """Would firing *job* at *now* be a catch-up rather than a window run?

    Asked by the scheduler immediately before it fires, so the runstate row can
    record WHICH kind of run it was. A reader that only sees ``last_run`` cannot
    tell a job that ran at its slot from one that ran nine hours late, and those
    two say very different things about the health of the host.
    """
    schedule = job.get("schedule", {})
    if schedule.get("type") not in _DAILY_TYPES:
        return False
    if now is None:
        now = datetime.now()
    state = get_job_state(runstate, job["owner"], job["id"])
    return _is_catch_up_due(schedule, _due_from(state), now)


def missed_window(job: dict, runstate: dict, now: Optional[datetime] = None) -> bool:
    """Did *job* miss today's window, catch_up or not?

    Independent of the opt-in on purpose: a job nobody chose to catch up still
    missed its window, and the operator needs to be told. Reports state only -
    :func:`note_missed_window` owns the once-per-day bookkeeping.
    """
    schedule = job.get("schedule", {})
    if schedule.get("type") not in _DAILY_TYPES:
        return False
    if now is None:
        now = datetime.now()
    state = get_job_state(runstate, job["owner"], job["id"])
    return window_closed_unrun(schedule, _due_from(state), now)


def note_missed_window(runstate: dict, owner: str, job_id: str, now: Optional[datetime] = None) -> bool:
    """Stamp today's miss as reported. True when this call is the FIRST for today.

    The scheduler ticks about every two minutes, so an unguarded MISSED line
    would repeat ~500 times between a closed window and midnight and drown the
    log it exists to inform.
    """
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


# =============================================
# INTERVAL SLOTS — a rhythm before the first run
# =============================================

# Per-job, in the ``schedule`` block. An ISO instant naming ONE occurrence of the
# rhythm the owner wants ("2026-09-06T03:00:00"); the interval supplies the rest.
# Chosen over a weekday+time shape because it needs no vocabulary of its own, it
# is exactly what a hand-seeded runstate row already holds, and it stays correct
# for intervals that are not a whole number of days.
SLOT_FIELD = "slot"


def _slot_anchor(slot: str, interval: int, now: datetime) -> Optional[datetime]:
    """The slot occurrence to seed ``last_run`` with, or None if unreadable.

    Rolled forward by whole intervals rather than used verbatim, so a slot left
    in the past keeps its PHASE without making the job instantly overdue: the
    anchor names the rhythm, not a one-off date. A slot still in the future is
    seeded one interval BEHIND itself, so the first fire lands exactly on it.
    """
    try:
        anchor = datetime.fromisoformat(slot)
    except (ValueError, TypeError) as e:
        logger.warning("[runstate] Unreadable slot %r: %s", slot, e)
        return None

    if interval <= 0:
        logger.warning("[runstate] Slot %r with non-positive interval %r, not seeding", slot, interval)
        return None

    if anchor > now:
        return anchor - timedelta(minutes=interval)

    steps = int((now - anchor).total_seconds() / 60 // interval)
    return anchor + timedelta(minutes=steps * interval)


def needs_slot_seed(job: dict, runstate: dict) -> bool:
    """True for an enabled interval job that has never actually RUN.

    KEYED ON ``last_run``, NOT ON THE PRESENCE OF A ROW, and the difference is
    the whole defect. A blocked fire creates a runstate row carrying
    ``last_blocked_at`` and no ``last_run`` (see :func:`record_job_blocked`), so
    a "no row" test would refuse to seed exactly the job that most needs it -
    @seedgo's weekly cycle was enabled unseeded, blocked twice at 01:34 and
    01:40, and only its own branch lock kept the week from locking to 01:34
    Monday. A job that has never run has no rhythm to preserve.
    """
    if not job.get("enabled", True):
        return False
    if job.get("schedule", {}).get("type") != "interval":
        return False
    return not get_job_state(runstate, job["owner"], job["id"]).get("last_run")


def seed_interval_slot(runstate: dict, job: dict, now: Optional[datetime] = None) -> Optional[str]:
    """Seed a never-run interval job's ``last_run`` from its declared slot.

    Returns the seeded ISO timestamp, or None when the job declares no readable
    slot - in which case today's behaviour stands and the job fires on the next
    tick. Callers warn on None; the decision to fire immediately is not silent.
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

    # Both daily forms gain the OPT-IN catch-up: due inside the window as
    # always, and additionally due once the window has closed unrun for a job
    # whose owner asked for that. _already_ran_today bounds both arms, so a
    # caught-up run can never double-fire the day it lands in.
    checkers = {
        "daily": lambda: _is_daily_due(schedule, since_success, now) or _is_catch_up_due(schedule, since_success, now),
        # A rotation job is a daily job that picks a different target each night.
        # It opts in the same way: a missed night woken late still hands the
        # night to a steward, which is the point of the rotation.
        "rotation": lambda: (
            _is_daily_due(schedule, since_success, now) or _is_catch_up_due(schedule, since_success, now)
        ),
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
    caught_up: bool = False,
) -> None:
    """Update runstate for a job after successful firing.

    ``caught_up`` records that this run happened AFTER its window closed rather
    than inside it. Written on every success, cleared to None on the ordinary
    path, because a stale marker left over from last week's catch-up would
    report a healthy job as chronically late.
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
