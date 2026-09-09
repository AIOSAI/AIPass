# =================== AIPass ====================
# Name: catch_up_lane.py
# Description: Tick-side glue for the DPLAN-0332 catch-up lane
# Version: 1.0.0
# Created: 2026-09-08
# Modified: 2026-09-08
# =============================================

"""The catch-up lane as a tick sees it: detect and queue, then drain one.

``recovery.py`` answers questions about a gap — how wide, what closed inside it,
who is next, what the header says. THIS module is the part that happens *during a
tick*: it walks the enabled jobs, writes the queue, picks the one entry that may
fire, and reports each decision in the operator's log. That is why it is separate
from recovery and separate from run.py — recovery has no tick, and run.py had
grown past the size a reader can hold.

**It fires nothing itself.** ``fire`` and ``log`` arrive as callables from the
caller. That is not ceremony: a handler may not import a module (seedgo's
encapsulation rule, and the circular import it exists to prevent), and the
firing lane lives in ``apps/modules/run.py``. Injecting them keeps this file
testable without a tick and keeps the dependency arrow pointing one way.

Everything here is inert while ``runstate.RECOVERY_LANE_LIVE`` is False.
"""

from datetime import datetime
from typing import Callable, List, Optional, Tuple

from aipass.prax import logger
from aipass.daemon.apps.handlers.json import json_handler
from aipass.daemon.apps.handlers.schedule import recovery
from aipass.daemon.apps.handlers.schedule.runstate import (
    RECOVERY_LANE_LIVE,
    get_job_state,
    job_key,
    save_runstate,
    update_job_runstate,
)

#: The vocabulary a fire attempt answers in. BLOCKED is the third state and the
#: reason there are three: a wake refused before it started (occupancy, lock,
#: pause) is not a run and must not consume the job's period — the S54
#: BLOCKED-IS-NOT-RAN contract. Defined here because both run.py and this
#: module's drain branch on it, and a shared vocabulary belongs to neither
#: caller alone.
OUTCOME_FIRED = "fired"
OUTCOME_FAILED = "failed"
OUTCOME_BLOCKED = "blocked"


def detect_and_queue(
    enabled: List[dict],
    runstate: dict,
    dry_run: bool,
    log: Callable[[str], None],
) -> Tuple[Optional[dict], int]:
    """Find the gap, enumerate what closed inside it, queue one entry per job.

    Returns ``(gap or None, jobs_queued)``. Runs BEFORE the due check, because a
    job whose regular window is open right now must be able to supersede its own
    queued entry on this same tick — the missed list then rides the on-time wake
    instead of a second one.
    """
    if not RECOVERY_LANE_LIVE:
        return None, 0

    gap = recovery.detect_gap(runstate)
    if not gap:
        return None, 0

    log(f"GAP {gap['duration']} ({gap['sentence']})")
    logger.warning("[run] GAP %s — %s", gap["duration"], gap["sentence"])

    try:
        gap_start = datetime.fromisoformat(gap["gap_start"])
        gap_end = datetime.fromisoformat(gap["gap_end"])
    except (ValueError, TypeError) as e:
        logger.error("[run] gap instants unreadable (%s) — nothing queued", e)
        return gap, 0

    queued = 0
    for job in enabled:
        instants = recovery.enumerate_missed(job, gap_start, gap_end)
        if not instants:
            continue
        if dry_run:
            log(f"DRY RUN — would queue {job['owner']}/{job['id']} ({len(instants)} window(s))")
            continue
        entry = recovery.queue_catch_up(runstate, job, instants, gap)
        if entry is None:
            log(f"SKIP QUEUE: {job['owner']}/{job['id']} — catch_up off or every window too old")
            continue
        queued += 1
        log(f"QUEUED: {job['owner']}/{job['id']} ({entry['count']} window(s), oldest {entry['oldest']})")

    if queued and not dry_run:
        save_runstate(runstate)
    json_handler.log_operation("catch_up_detect_and_queue", {"queued": queued, "cause": gap["cause"]})
    return gap, queued


def drain_one(
    runstate: dict,
    enabled: List[dict],
    dry_run: bool,
    log: Callable[[str], None],
    fire: Callable[..., Tuple[str, str]],
) -> int:
    """Fire at most ONE queued catch-up. Returns 1 if one fired, else 0.

    Patrick's rule, and the reason this function can only ever return 0 or 1:
    "imagine 10 missed events all firing at once."
    """
    if not RECOVERY_LANE_LIVE:
        return 0

    entry = recovery.drain_ready(runstate)
    if entry is None:
        return 0

    by_key = {job_key(j["owner"], j["id"]): j for j in enabled}
    job = by_key.get(job_key(entry["owner"], entry["job_id"]))
    if job is None:
        # The job left the fleet while it was queued. Drop it rather than
        # retrying forever against a schedule nobody publishes any more.
        recovery.drop_from_queue(runstate, entry["owner"], entry["job_id"])
        log(f"CATCH-UP DROPPED: {entry['owner']}/{entry['job_id']} — job no longer discovered")
        if not dry_run:
            save_runstate(runstate)
        return 0

    if dry_run:
        log(f"DRY RUN — would fire CATCH-UP {entry['owner']}/{entry['job_id']} ({entry['count']} window(s))")
        return 0

    state = get_job_state(runstate, entry["owner"], entry["job_id"])
    header = recovery.catch_up_header(entry, job, state)
    outcome, detail = fire(job, runstate, header=header)

    if outcome == OUTCOME_FIRED:
        recovery.drop_from_queue(runstate, entry["owner"], entry["job_id"])
        recovery.mark_in_flight(runstate, entry)
        update_job_runstate(runstate, job["owner"], job["id"], job["schedule"], caught_up=True)
        log(f"CATCH-UP FIRED: {entry['owner']}/{entry['job_id']} ({entry['count']} window(s))")
        logger.info("[run] CATCH-UP FIRED %s/%s (%s windows)", entry["owner"], entry["job_id"], entry["count"])
        save_runstate(runstate)
        return 1

    parked = recovery.record_attempt(entry)
    if parked:
        log(f"CATCH-UP FAILED: {entry['owner']}/{entry['job_id']} — {recovery.MAX_ATTEMPTS} attempts, moved to tail")
        logger.warning(
            "[run] CATCH-UP FAILED %s/%s after %s attempts — moved to the tail",
            entry["owner"],
            entry["job_id"],
            recovery.MAX_ATTEMPTS,
        )
    else:
        log(f"CATCH-UP DEFERRED: {entry['owner']}/{entry['job_id']} — {detail}")
    save_runstate(runstate)
    return 0
