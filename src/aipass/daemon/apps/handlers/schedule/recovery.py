# =================== AIPass ====================
# Name: recovery.py
# Description: Gap detection, missed-window enumeration, catch-up queue and drain policy
# Version: 1.0.0
# Created: 2026-09-08
# Modified: 2026-10-23
# =============================================

"""
Schedule recovery — what the scheduler owes the fleet after it was away.

Reference: docs/recovery_and_catch_up.md
"""

from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Tuple

from aipass.prax import logger
from aipass.daemon.apps.handlers.json import json_handler
from aipass.daemon.apps.handlers.schedule import runstate as rs

#: One window (2 * WINDOW_MINUTES), the smallest span a daily job's whole firing chance can pass in.
GAP_THRESHOLD_MINUTES = 30

LAST_TICK_FIELD = "last_tick"

#: No ``machine_off``: a boot inside the gap cannot be told from a night's shutdown
#: without proof the host was up, so the cause names only what is known.
CAUSE_SCHEDULER_STOPPED = "scheduler_stopped"
CAUSE_STOPPED_THEN_REBOOTED = "scheduler_stopped_then_rebooted"
CAUSE_UNKNOWN = "unknown"


class BootTimeUnavailable(Exception):
    """The host could not be asked when it booted. Never defaulted: a guess becomes a false header."""


def boot_time() -> datetime:
    """When did this host last boot? Raises BootTimeUnavailable if it cannot be known."""
    try:
        import psutil

        return datetime.fromtimestamp(psutil.boot_time())
    except ImportError:
        logger.info("[recovery] psutil unavailable, trying /proc/stat")
    except (OSError, ValueError, OverflowError) as e:
        logger.warning("[recovery] psutil.boot_time() unreadable: %s", e)

    try:
        with open("/proc/stat", "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("btime "):
                    return datetime.fromtimestamp(int(line.split()[1]))
    except (OSError, ValueError, IndexError) as e:
        logger.warning("[recovery] /proc/stat btime unreadable: %s", e)

    raise BootTimeUnavailable("no readable boot time (psutil absent, /proc/stat unusable)")


def _classify_cause(gap_start: datetime, boot: Optional[datetime]) -> Tuple[str, str]:
    """Name why the scheduler was away. Returns (cause, human sentence)."""
    if boot is None:
        return CAUSE_UNKNOWN, "the cause could not be read from this host"

    if boot <= gap_start:
        # Say the earlier boot did not cause it: a boot named beside a gap reads as cause.
        return (
            CAUSE_SCHEDULER_STOPPED,
            f"the scheduler stopped ticking at {gap_start:%Y-%m-%d %H:%M} while the machine was up "
            f"(the host booted {boot:%Y-%m-%d %H:%M}, BEFORE the gap opened, so the boot did not cause it)",
        )

    return (
        CAUSE_STOPPED_THEN_REBOOTED,
        f"the scheduler stopped ticking at {gap_start:%Y-%m-%d %H:%M}, and the machine "
        f"booted at {boot:%Y-%m-%d %H:%M} — inside the gap, after it had already opened",
    )


def format_duration(delta: timedelta) -> str:
    """Human duration for a header an agent will read: "10d 4h", "23h 0m", "45m"."""
    total_minutes = int(delta.total_seconds() // 60)
    days, rem = divmod(total_minutes, 1440)
    hours, minutes = divmod(rem, 60)
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def detect_gap(runstate: dict, now: Optional[datetime] = None) -> Optional[dict]:
    """Was the scheduler away since its last tick? Returns a gap record or None.

    None when last_tick is missing or unreadable: never fall back to an older stamp, that invents a gap.
    """
    if now is None:
        now = datetime.now()

    raw = runstate.get(LAST_TICK_FIELD)
    if not raw:
        logger.info("[recovery] no %s yet — no gap can be known on this tick", LAST_TICK_FIELD)
        return None

    try:
        gap_start = datetime.fromisoformat(raw)
    except (ValueError, TypeError) as e:
        logger.warning("[recovery] last_tick %r unparseable: %s", raw, e)
        return None

    delta = now - gap_start
    if delta < timedelta(minutes=GAP_THRESHOLD_MINUTES):
        return None

    try:
        boot: Optional[datetime] = boot_time()
    except BootTimeUnavailable as e:
        logger.warning("[recovery] %s", e)
        boot = None

    cause, sentence = _classify_cause(gap_start, boot)

    return {
        "gap_start": gap_start.isoformat(),
        "gap_end": now.isoformat(),
        "duration": format_duration(delta),
        "cause": cause,
        "sentence": sentence,
        "boot_time": boot.isoformat() if boot else None,
    }


def record_tick(runstate: dict, now: Optional[datetime] = None) -> str:
    """Stamp this tick. Returns the instant written.

    Call at the END of a tick: stamping before detection erases the gap.
    """
    if now is None:
        now = datetime.now()
    stamp = now.isoformat()
    runstate[LAST_TICK_FIELD] = stamp
    return stamp


WINDOWED_TYPES = frozenset({"daily", "rotation", "hourly"})

#: Header list cap: a months-long gap on an hourly job is thousands of windows.
MAX_LISTED_INSTANTS = 50


def enumerate_missed(job: dict, gap_start: datetime, gap_end: datetime) -> List[str]:
    """Every window of *job* that closed inside the gap. Returns ISO instants, oldest first.

    Walks the calendar, not 24h steps: across DST those are different sequences.
    """
    schedule = job.get("schedule", {})
    sched_type = schedule.get("type")
    if sched_type not in WINDOWED_TYPES:
        return []

    if sched_type == "hourly":
        return _enumerate_hourly(schedule, gap_start, gap_end)
    return _enumerate_daily(schedule, gap_start, gap_end)


def _enumerate_daily(schedule: dict, gap_start: datetime, gap_end: datetime) -> List[str]:
    """Daily/rotation windows that both opened and closed inside the gap."""
    target = rs._target_minutes(schedule)
    if target is None:
        return []

    missed: List[str] = []
    day = gap_start.date()
    last_day = gap_end.date()
    while day <= last_day:
        fire_at = datetime.combine(day, datetime.min.time()) + timedelta(minutes=target)
        close_at = fire_at + timedelta(minutes=rs.WINDOW_MINUTES)
        # A window still open at gap_end is not missed: it fires this tick the ordinary way.
        if fire_at >= gap_start and close_at <= gap_end:
            missed.append(fire_at.isoformat())
        day += timedelta(days=1)
    return missed


def _enumerate_hourly(schedule: dict, gap_start: datetime, gap_end: datetime) -> List[str]:
    """Hourly windows that both opened and closed inside the gap.

    An unreadable ``time`` answers [], as runstate's hourly due check refuses the same value.
    """
    # Hourly ``time`` is an int minute past the hour ("30"), not "HH:MM"; read it as _is_hourly_due does.
    raw = schedule.get("time", "0")
    try:
        minute = int(raw)
    except (TypeError, ValueError):
        logger.warning("[recovery] hourly time %r unreadable — no windows enumerated", raw)
        return []

    missed: List[str] = []
    cursor = gap_start.replace(minute=0, second=0, microsecond=0)
    while cursor <= gap_end:
        fire_at = cursor + timedelta(minutes=minute)
        close_at = fire_at + timedelta(minutes=rs.WINDOW_MINUTES)
        if fire_at >= gap_start and close_at <= gap_end:
            missed.append(fire_at.isoformat())
        cursor += timedelta(hours=1)
    return missed


QUEUE_FIELD = "catch_up_queue"

IN_FLIGHT_FIELD = "catch_up_in_flight"

#: Backstop only: the previous catch-up completing is the trigger, this covers one that never reports.
DRAIN_CEILING_MINUTES = 60

MAX_ATTEMPTS = 3

CATCH_UP_MAX_AGE_FIELD = "catch_up_max_age_hours"


def catch_up_enabled(schedule: dict) -> bool:
    """Is catch-up on for this job? Windowed types only, by the due check's own rule (rs.catch_up_on)."""
    return schedule.get("type") in WINDOWED_TYPES and rs.catch_up_on(schedule)


def _within_max_age(schedule: dict, instant: str, now: datetime) -> bool:
    """Is this missed window young enough to be worth firing?

    Unset or unreadable bound/instant answers True: a late wake costs less than a dropped window.
    """
    limit = schedule.get(CATCH_UP_MAX_AGE_FIELD)
    if limit is None:
        return True
    try:
        hours = float(limit)
    except (TypeError, ValueError):
        logger.warning("[recovery] %s %r unreadable, treating as unlimited", CATCH_UP_MAX_AGE_FIELD, limit)
        return True
    try:
        when = datetime.fromisoformat(instant)
    except (ValueError, TypeError):
        return True
    return (now - when) <= timedelta(hours=hours)


def queue_catch_up(
    runstate: dict,
    job: dict,
    instants: List[str],
    gap: dict,
    now: Optional[datetime] = None,
) -> Optional[dict]:
    """Record that *job* owes one catch-up covering *instants*. Returns the entry, or None.

    Idempotent by key: an existing entry absorbs new instants, so re-detection is still one wake.
    """
    if now is None:
        now = datetime.now()

    schedule = job.get("schedule", {})
    if not catch_up_enabled(schedule):
        return None

    fresh = [i for i in instants if _within_max_age(schedule, i, now)]
    if not fresh:
        return None

    key = rs.job_key(job["owner"], job["id"])
    queue = runstate.setdefault(QUEUE_FIELD, {})
    entry = queue.get(key)

    if entry is None:
        entry = {
            "owner": job["owner"],
            "job_id": job["id"],
            "missed": [],
            "queued_at": now.isoformat(),
            "attempts": 0,
            "gap": gap,
        }
        queue[key] = entry

    merged = sorted(set(entry["missed"]) | set(fresh))
    entry["missed"] = merged
    entry["oldest"] = merged[0]
    entry["count"] = len(merged)
    json_handler.log_operation("queue_catch_up", {"key": key, "windows": len(merged)})
    return entry


def drop_from_queue(runstate: dict, owner: str, job_id: str) -> Optional[dict]:
    """Remove a job's catch-up entry and return it, so its missed list rides whichever wake goes first."""
    return runstate.get(QUEUE_FIELD, {}).pop(rs.job_key(owner, job_id), None)


def queue_order(runstate: dict) -> List[dict]:
    """The queue, FIFO by oldest missed window. Entries at the tail sort last."""
    entries = list(runstate.get(QUEUE_FIELD, {}).values())
    return sorted(entries, key=lambda e: (e.get("parked_at") or "", e.get("oldest") or ""))


def in_flight(runstate: dict) -> Optional[dict]:
    """The catch-up currently in flight fleet-wide, or None."""
    return runstate.get(IN_FLIGHT_FIELD)


def _branch_is_awake(owner: str) -> bool:
    """Is this branch already busy? Asks ai_mail's dispatch register, never guesses.

    Unreadable answers awake: holding costs a tick, firing onto a live agent is the collision.
    """
    try:
        from aipass.ai_mail import outstanding_dispatches

        return any(str(entry.get("target", "")) == owner for entry in outstanding_dispatches())
    except ImportError as e:
        logger.warning("[recovery] dispatch register unavailable (%s) — holding the drain", e)
        return True
    except OSError as e:
        logger.warning("[recovery] dispatch register unreadable (%s) — holding the drain", e)
        return True


def drain_ready(runstate: dict, now: Optional[datetime] = None) -> Optional[dict]:
    """The one catch-up entry that may fire on this tick, or None.

    One in flight fleet-wide; the next fires when it completes, DRAIN_CEILING_MINUTES at most.
    """
    if now is None:
        now = datetime.now()

    flying = in_flight(runstate)
    if flying:
        fired_at = flying.get("fired_at")
        try:
            fired = datetime.fromisoformat(fired_at) if fired_at else None
        except (ValueError, TypeError):
            logger.warning(
                "[recovery] in-flight fired_at %r unreadable — releasing the drain rather "
                "than holding it on a stamp nobody can read",
                fired_at,
            )
            fired = None

        # Completed is the trigger: the branch released its lock.
        if fired is not None and _branch_is_awake(flying.get("owner", "")):
            if now - fired < timedelta(minutes=DRAIN_CEILING_MINUTES):
                return None
            logger.warning(
                "[recovery] catch-up %s/%s never reported after %d min — releasing the drain",
                flying.get("owner"),
                flying.get("job_id"),
                DRAIN_CEILING_MINUTES,
            )
        runstate.pop(IN_FLIGHT_FIELD, None)

    for entry in queue_order(runstate):
        if _branch_is_awake(entry["owner"]):
            continue
        return entry
    return None


def mark_in_flight(runstate: dict, entry: dict, now: Optional[datetime] = None) -> None:
    """Record that this entry's catch-up has just been fired."""
    if now is None:
        now = datetime.now()
    runstate[IN_FLIGHT_FIELD] = {
        "owner": entry["owner"],
        "job_id": entry["job_id"],
        "fired_at": now.isoformat(),
        "windows": entry.get("count", len(entry.get("missed", []))),
    }


def record_attempt(entry: dict, now: Optional[datetime] = None) -> bool:
    """Count a refused catch-up fire. True when the entry has just been parked at the tail.

    Parked, never dropped: "could not reach this branch" is not "this branch owed nothing".
    """
    if now is None:
        now = datetime.now()
    entry["attempts"] = entry.get("attempts", 0) + 1
    entry["last_attempt_at"] = now.isoformat()
    if entry["attempts"] >= MAX_ATTEMPTS and not entry.get("parked_at"):
        entry["parked_at"] = now.isoformat()
        return True
    return False


def _humanise_ago(then: Optional[str], now: datetime) -> str:
    """ " (2 days ago)" for a header, or "" when the instant is unknown/unreadable."""
    if not then:
        return ""
    try:
        when = datetime.fromisoformat(then)
    except (ValueError, TypeError):
        return ""
    return f" ({format_duration(now - when)} ago)"


def _format_instants(instants: List[str]) -> str:
    """Missed windows as a reader-sized list, truncated with an honest count."""
    shown = [i.replace("T", " ")[:16] for i in instants[:MAX_LISTED_INSTANTS]]
    text = ", ".join(shown)
    if len(instants) > MAX_LISTED_INSTANTS:
        text += f", ... (+{len(instants) - MAX_LISTED_INSTANTS} more)"
    return text


def scheduled_header(
    job: dict,
    state: dict,
    now: Optional[datetime] = None,
    missed: Optional[List[str]] = None,
) -> str:
    """The SCHEDULED header: an on-time wake, and what it still owes the agent.

    Carries the missed list: a superseded catch-up would otherwise never tell the job it was away.
    """
    if now is None:
        now = datetime.now()

    window = job.get("schedule", {}).get("time", "")
    window_text = f", window {window}" if window else ""
    line = (
        f"Scheduled wake: {job['id']}{window_text}, fired {now:%Y-%m-%d %H:%M}. "
        f"Last run {(state.get('last_run') or 'never').replace('T', ' ')[:16]}"
        f"{_humanise_ago(state.get('last_run'), now)}."
    )
    if missed:
        line += (
            f"\nYou also missed {len(missed)} window(s) since {missed[0].replace('T', ' ')[:16]}: "
            f"{_format_instants(missed)}."
        )
    return line


def catch_up_header(entry: dict, job: dict, state: dict, now: Optional[datetime] = None) -> str:
    """The CATCH-UP header: one run covering every window the gap swallowed.

    Keep "do not replay each one": without it an agent handed ten dates does ten runs of work.
    """
    if now is None:
        now = datetime.now()

    missed = entry.get("missed", [])
    gap = entry.get("gap", {})
    gap_start = (gap.get("gap_start") or "").replace("T", " ")[:16]
    gap_end = (gap.get("gap_end") or "").replace("T", " ")[:16]
    sentence = gap.get("sentence", "the cause could not be read from this host")
    next_run = (state.get("next_run") or "unknown").replace("T", " ")[:16]

    return (
        f"Catch-up wake, NOT the schedule: {job['id']}. "
        f"The scheduler was away {gap.get('duration', '?')} ({gap_start} to {gap_end}): {sentence}. "
        f"You missed {len(missed)} window(s): {_format_instants(missed)}. "
        f"This is ONE run covering all of them — read the gap, decide what matters now, "
        f"do not replay each one. Next regular window: {next_run}."
    )


def compose_prompt(header: str, prompt: str) -> str:
    """Header first, then the job's own prompt, separated so neither reads as the other."""
    return f"{header}\n\n---\n\n{prompt}"


def _branch_daemon_dir(owner: str):
    """The target branch's ``.daemon/`` directory, or None if it cannot be resolved.

    Keyed on email through discovery's roster, never a path convention of its own.
    """
    try:
        from aipass.daemon.apps.handlers.schedule.discovery import active_citizens

        for citizen in active_citizens():
            if citizen.get("email") == owner:
                return Path(citizen["path"]) / ".daemon"
    except (ImportError, OSError, TypeError, KeyError) as e:
        logger.warning("[recovery] could not resolve .daemon/ for %s: %s", owner, e)
    return None


def record_wake_prompt(owner: str, job_id: str, prompt: str) -> None:
    """File the exact text a wake was sent, header and all. Two places, both ours.

    Fail-soft per destination: a wake is never lost to an unwritable transcript.
    """
    branch_dir = _branch_daemon_dir(owner)
    if branch_dir is not None:
        try:
            rs.write_atomic(branch_dir / "last_wake_prompt.txt", lambda f: f.write(prompt))
        except OSError as e:
            logger.warning("[recovery] could not file wake prompt in %s: %s", branch_dir, e)

    try:
        rs.write_atomic(rs.RUNSTATE_FILE.parent / "last_wake_prompt.txt", lambda f: f.write(prompt))
    except OSError as e:
        logger.warning("[recovery] could not record wake prompt for %s/%s: %s", owner, job_id, e)
