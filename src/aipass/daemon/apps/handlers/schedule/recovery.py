# =================== AIPass ====================
# Name: recovery.py
# Description: Gap detection, missed-window enumeration, catch-up queue and drain policy
# Version: 1.0.0
# Created: 2026-09-08
# Modified: 2026-09-08
# =============================================

"""
Schedule recovery — what the scheduler owes the fleet after it was away.

DPLAN-0332, Patrick 2026-09-08. The scheduler's timer was uninstalled for 23
hours on 09-07; @vera's 10:00 window and @daemon's 09:00 inbox-sweep closed
unrun and nothing noticed, because a MISSED line needs a tick to write it.

THE RULE THIS FILE ENCODES, in Patrick's words: "a missed schedule gets
identified, added to a queued run, then reissued one by one, not all at once -
imagine 10 missed events all firing at once." And: "down 10 days, Vera misses
10 events - she does ONE, is told we have been away 10 days with the list, and
figures out the rest herself."

So: **the system informs, the agent reasons.** Ten missed windows become ONE
wake carrying ten dates. Nothing is replayed.

WHY THIS IS NOT IN runstate.py. runstate owns due-ness: given a job and a
clock, should it fire. This file owns a different subject — given a gap, what
did the fleet miss and in what order should it be repaid. Keeping them apart is
what lets the drain be tested with no schedule in sight, and due-ness with no
gap. runstate keeps ``last_tick`` itself, because a tick is a fact about a run.
"""

from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Tuple

from aipass.prax import logger
from aipass.daemon.apps.handlers.json import json_handler
from aipass.daemon.apps.handlers.schedule import runstate as rs

# =============================================
# GAP DETECTION
# =============================================

#: A gap wider than this means windows may have closed unseen. One window
#: (2 * WINDOW_MINUTES) is the smallest interval in which a daily job's whole
#: firing opportunity can pass, so anything wider is worth inspecting. Ticks are
#: ~2 min apart, so this is ~15 missed ticks — never a normal hiccup.
GAP_THRESHOLD_MINUTES = 30

#: Runstate key holding the instant of the last completed tick.
LAST_TICK_FIELD = "last_tick"

#: Cause vocabulary. THREE values, and @devpulse ruled on the shape 2026-09-08:
#: "Boot inside the gap reports both facts, naming the boot instant and that the
#: gap opened before it. That sentence is the one that points at yesterday's real
#: defect; keep it."
#:
#: The DPLAN as agreed was two-valued — boot-after meant machine_off, boot-before
#: meant scheduler_stopped. Measuring 09-07 showed the real incident was BOTH:
#: the timer was removed at 11:46 while the machine was up, and the machine then
#: rebooted at 16:14 inside the same gap. Two values would have reported only the
#: reboot and hidden the defect that actually mattered.
#:
#: ``machine_off`` is deliberately NOT a value here. Boot-inside-the-gap cannot
#: be told apart from "shut down for the night" without positive evidence the
#: host was up during the gap, and no cross-platform source provides it — so the
#: cause names what is KNOWN (the gap opened, then the host booted inside it) and
#: the sentence states both instants rather than picking a story.
CAUSE_SCHEDULER_STOPPED = "scheduler_stopped"
CAUSE_STOPPED_THEN_REBOOTED = "scheduler_stopped_then_rebooted"
CAUSE_UNKNOWN = "unknown"


class BootTimeUnavailable(Exception):
    """The host could not be asked when it booted.

    Raised rather than returning a default, because a guessed boot time turns
    into a confident sentence in an agent's wake header about why the system was
    away. Refused by name is the honest answer; the gap is still reported, with
    its cause named ``unknown``.
    """


def boot_time() -> datetime:
    """When did this host last boot? Raises BootTimeUnavailable if it cannot be known.

    psutil first because it is the cross-platform answer and this fleet runs a
    Windows job; /proc/stat second because it is always right on Linux and costs
    nothing when psutil is absent. No third guess: uptime parsing differs per
    distro and a wrong boot time is worse than no boot time.
    """
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
    """Name why the scheduler was away. Returns (cause, human sentence).

    ``boot`` is None when the host refused to say, and the caller must not
    invent one — the gap is still real and still reported.
    """
    if boot is None:
        return CAUSE_UNKNOWN, "the cause could not be read from this host"

    if boot <= gap_start:
        # A BOOT THAT PRECEDES THE LAST TICK DID NOT CAUSE THE GAP, and the
        # sentence has to say so rather than merely mention the instant — naming
        # a boot next to a gap reads as cause to anyone skimming it. @devpulse,
        # 2026-09-08, on a header that named a boot a day older than the gap.
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

    The trigger is the GAP, never "a reboot": 09-07 was no reboot at the point
    it broke — the machine was up and the timer was simply gone. Asking "did I
    tick recently" catches both shapes with one question.

    Returns None when there is no last_tick at all. That is the first tick after
    this lands, and it has no history to reason from; queueing off an unknown
    past would invent windows the fleet never actually missed.
    """
    if now is None:
        now = datetime.now()

    raw = runstate.get(LAST_TICK_FIELD)
    if not raw:
        # NO last_tick IS NOT A GAP. The first tick after this lands has no
        # history to reason from, and reaching for some older timestamp instead
        # would invent an absence the fleet never had — then queue catch-ups for
        # windows nobody missed. @devpulse's rule, 2026-09-08.
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

    Called at the END of a tick, after detection has read the previous value —
    stamping first would erase the very gap the tick exists to notice.
    """
    if now is None:
        now = datetime.now()
    stamp = now.isoformat()
    runstate[LAST_TICK_FIELD] = stamp
    return stamp


# =============================================
# MISSED WINDOW ENUMERATION
# =============================================

#: Schedule types that fire inside a window and can therefore miss one.
#: ``hourly`` is here and was NOT in runstate's catch-up path before DPLAN-0332
#: — is_job_due mapped it to _is_hourly_due alone, so an hourly job had no
#: catch-up at all. This is a build, not a flag flip.
WINDOWED_TYPES = frozenset({"daily", "rotation", "hourly"})

#: Ceiling on how many instants one entry carries into a header. A three-month
#: gap on an hourly job is ~2000 windows, and a wake header naming all of them
#: is not information, it is a denial of service on the agent's attention.
MAX_LISTED_INSTANTS = 50


def enumerate_missed(job: dict, gap_start: datetime, gap_end: datetime) -> List[str]:
    """Every window of *job* that closed inside the gap. Returns ISO instants, oldest first.

    Walks the calendar rather than dividing the gap, because a daily window is a
    wall-clock time and DST makes "every 24h" and "every day at 08:00" different
    sequences. The walk is bounded by the gap itself.
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
        # Both edges inside the gap: a window still open at gap_end has not been
        # missed, it is about to fire on this very tick through the ordinary path.
        if fire_at >= gap_start and close_at <= gap_end:
            missed.append(fire_at.isoformat())
        day += timedelta(days=1)
    return missed


def _enumerate_hourly(schedule: dict, gap_start: datetime, gap_end: datetime) -> List[str]:
    """Hourly windows that both opened and closed inside the gap."""
    # An hourly job spells its target as ``time``, an INT MINUTE past the hour
    # ("30"), not "HH:MM" — the same field name as daily carrying a different
    # shape. Read it the way _is_hourly_due reads it or the enumeration and the
    # due check would disagree about when the window even was.
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


# =============================================
# THE CATCH-UP QUEUE — one entry per job, never a replay
# =============================================

#: Runstate key holding the FIFO of catch-up entries, oldest missed window first.
QUEUE_FIELD = "catch_up_queue"

#: Runstate key holding the one catch-up currently in flight fleet-wide.
IN_FLIGHT_FIELD = "catch_up_in_flight"

#: Patrick's ceiling: "I think 60min cool down then it retires the next." The
#: COMPLETION of the previous catch-up is the trigger; this is the backstop for
#: when nothing ever reports (dead monitor, reboot mid-drain).
DRAIN_CEILING_MINUTES = 60

#: Attempts before a refused entry stops blocking the head of the queue.
MAX_ATTEMPTS = 3

#: Per-job opt-out and age bound, read from the job's ``schedule`` block.
CATCH_UP_MAX_AGE_FIELD = "catch_up_max_age_hours"


def catch_up_enabled(schedule: dict) -> bool:
    """Is catch-up on for this job? Default ON since DPLAN-0332.

    Supersedes ruling 6 of 2026-09-07, which made it opt-in — and every enabled
    job in the fleet left it unset, which is exactly why nothing recovered on
    09-08. A job whose late run is worthless sets ``"catch_up": false``.
    """
    if schedule.get("type") not in WINDOWED_TYPES:
        return False
    return schedule.get(rs.CATCH_UP_FIELD, True) is not False


def _within_max_age(schedule: dict, instant: str, now: datetime) -> bool:
    """Is this missed window young enough to be worth firing?

    Unlimited by default: Patrick's ten-day case wants exactly one wake however
    long it has been. A job that sets the bound is saying its own late run stops
    being useful after N hours.
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

    IDEMPOTENT BY KEY, which is what makes a second reboot mid-drain lose
    nothing: an entry already queued for this job absorbs any newly discovered
    instants rather than becoming a second entry. Ten days off is one Vera wake
    with ten dates, and detecting it twice is still one wake.
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
    """Remove a job's catch-up entry and return it.

    Called on supersession — the regular window arrived before the catch-up
    fired — and after a successful catch-up fire. The missed list travels on
    with the caller, because the truth about time rides whichever wake goes
    first.
    """
    return runstate.get(QUEUE_FIELD, {}).pop(rs.job_key(owner, job_id), None)


def queue_order(runstate: dict) -> List[dict]:
    """The queue, FIFO by oldest missed window. Entries at the tail sort last.

    A tail-parked entry (3 failed attempts) carries ``parked_at``, and sorting
    on that first is what stops it blocking the head forever while still keeping
    it in the queue rather than silently dropping work.
    """
    entries = list(runstate.get(QUEUE_FIELD, {}).values())
    return sorted(entries, key=lambda e: (e.get("parked_at") or "", e.get("oldest") or ""))


def in_flight(runstate: dict) -> Optional[dict]:
    """The catch-up currently in flight fleet-wide, or None."""
    return runstate.get(IN_FLIGHT_FIELD)


def _branch_is_awake(owner: str) -> bool:
    """Is this branch already busy? Asks ai_mail's dispatch register, never guesses.

    ``outstanding()`` is the register's public read and is what the DPLAN names
    as the completion signal: an entry disappears from it when the dispatch
    closes, which is precisely "the previous catch-up completed".

    UNREADABLE ANSWERS "AWAKE", and that direction is deliberate. The register's
    own contract says a missing file yields [] but an unreadable one RAISES,
    because "nothing is outstanding" and "I cannot tell what is outstanding" are
    opposite answers. For a drain the asymmetry is stark: refusing to fire costs
    one tick of delay, and firing onto a live agent is the collision the whole
    one-at-a-time rule exists to prevent. So a read we cannot trust holds the
    queue rather than releasing it.
    """
    # The OWNER'S package door, not their handler. @ai_mail confirmed it on
    # 2026-09-08: aipass.ai_mail.__init__ exports outstanding_dispatches beside
    # feed_path and register_path, built for @devpulse under FPLAN-0452 for this
    # exact reason, and it is a thin delegation to the same function — one
    # implementation, imported at call time, so the values cannot drift.
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

    THE TWO GATES, both of them Patrick's. One catch-up in flight fleet-wide,
    because "imagine 10 missed events all firing at once". And the next fires
    when the previous COMPLETED, with 60 minutes as the ceiling rather than the
    rhythm — his event-driven rule of 09-07.
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

    Takes the ENTRY, not the runstate: the entry is a live reference into the
    queue, so mutating it is the persist. A runstate parameter here was unused
    and would have read as though this function decided something fleet-wide.

    Three attempts, then it stops blocking the head — but it stays in the queue.
    Dropping it would turn "we could not reach this branch" into "this branch
    owed nothing", and those are not the same sentence.
    """
    if now is None:
        now = datetime.now()
    entry["attempts"] = entry.get("attempts", 0) + 1
    entry["last_attempt_at"] = now.isoformat()
    if entry["attempts"] >= MAX_ATTEMPTS and not entry.get("parked_at"):
        entry["parked_at"] = now.isoformat()
        return True
    return False


# =============================================
# THE WAKE HEADER — why you are awake
# =============================================
#
# Patrick, 2026-09-08: "temporal awareness is a thing ... in the information
# provided to the agent say: you have missed 10 days, the machine was off. A
# reboot is different." And the principle this adds to the culture: THE SYSTEM
# INFORMS, THE AGENT REASONS. The header states facts about time and stops. It
# never tells the agent what to conclude, and it never replays history at it.


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

    After a gap even an on-time wake carries the missed list, because a job whose
    catch-up was superseded by its own next window would otherwise never learn
    it was away — the truth about time rides whichever wake goes first.
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

    The last sentence is the load-bearing one. Without "do not replay each day"
    an agent handed ten dates may reasonably try to do ten days of work, which
    is the exact failure Patrick named: "it's not gonna just run each one".
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

    Resolved through discovery's own citizen roster, keyed on EMAIL — the same
    key discovery uses to address jobs and wakes. Inventing a second path
    convention here is how a wake gets filed under a branch that does not exist,
    or worse, under a different citizen who happens to share a directory name.
    """
    try:
        from aipass.daemon.apps.handlers.schedule.discovery import active_citizens

        for citizen in active_citizens():
            if citizen.get("email") == owner:
                return Path(citizen["path"]) / ".daemon"
    except (ImportError, OSError, TypeError, KeyError) as e:
        logger.warning("[recovery] could not resolve .daemon/ for %s: %s", owner, e)
    return None


def _write_atomic(target, text: str) -> None:
    """Write via a sibling tmp file then replace. Never a partial read.

    @devpulse's ruling 2026-09-08: "Write it atomically (tmp then replace), never
    partial." A branch waking up mid-write would otherwise read half a header and
    reason about a gap that the other half described.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(target)


def record_wake_prompt(owner: str, job_id: str, prompt: str) -> None:
    """File the exact text a wake was sent, header and all. Two places, both ours.

    @devpulse ruled on 2026-09-08, after I asked whether this was a cross-branch
    write: "the daemon composes the prompt, so the daemon writes what it sent to
    the target branch's .daemon/last_wake_prompt.txt before firing — the .daemon/
    directory is the scheduler's surface in every branch (the owner writes
    schedule.json into it, the scheduler writes its outputs beside it), so this
    is not a cross-branch edit of somebody's code, it is the daemon's own
    artifact in the daemon's own directory. Also keep the daemon_json record
    since it costs nothing."

    ai_mail's write at wake.py:802 stays for the tmux manager lane. That file now
    has a SECOND writer, for the headless scheduled lane it never covered, so
    ai_mail can retire theirs later.

    Lives in a handler rather than run.py because a handler may touch the
    filesystem and a module may not.

    Fail-soft, and per-destination: a wake must never be lost because its
    transcript could not be filed, and an unwritable target branch must not cost
    us the local record too.
    """
    branch_dir = _branch_daemon_dir(owner)
    if branch_dir is not None:
        try:
            _write_atomic(branch_dir / "last_wake_prompt.txt", prompt)
        except OSError as e:
            logger.warning("[recovery] could not file wake prompt in %s: %s", branch_dir, e)

    try:
        _write_atomic(rs.RUNSTATE_FILE.parent / "last_wake_prompt.txt", prompt)
    except OSError as e:
        logger.warning("[recovery] could not record wake prompt for %s/%s: %s", owner, job_id, e)
