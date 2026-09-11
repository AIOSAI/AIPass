# =================== AIPass ====================
# Name: run.py
# Description: Manual one-tick scheduler command (drone @daemon run)
# Version: 1.6.0
# Created: 2026-06-15
# Modified: 2026-09-11
# =============================================

"""
Manual one-tick scheduler — discover .daemon/ jobs, fire due ones via wake_branch.

Handles 'drone @daemon run': one discover -> due-check -> fire pass.
Part of the DPLAN-0204 decentralized scheduler redesign.
"""

import sys
import time
from typing import List

from aipass.prax import logger
from aipass.cli.apps.modules import console
from aipass.daemon.apps.handlers.json import json_handler
from aipass.daemon.apps.handlers.cli.arg_gate import gate
from aipass.daemon.apps.modules.rotation import ROTATION_TYPE, fire_rotation
from aipass.daemon.apps.handlers.schedule.discovery import discover_jobs
from aipass.daemon.apps.handlers.schedule.runstate import (
    catch_up_on,
    get_job_state,
    load_runstate,
    save_runstate,
    is_catch_up_fire,
    is_job_due,
    missed_window,
    needs_slot_seed,
    note_missed_window,
    seed_interval_slot,
    update_job_runstate,
    record_job_failure,
    record_job_blocked,
    job_key,
    prune_orphans,
    window_label,
)
from aipass.daemon.apps.handlers.schedule import catch_up_lane
from aipass.daemon.apps.handlers.schedule import command_job
from aipass.daemon.apps.handlers.schedule.job_reference import job_reference_lines
from aipass.daemon.apps.handlers.schedule import recovery
from aipass.daemon.apps.handlers.schedule import tick_lock
from aipass.daemon.apps.handlers.module_root import module_file

_DAEMON_ROOT = module_file(__file__).parents[2]  # src/aipass/daemon/
LOCK_FILE = _DAEMON_ROOT / "daemon_json" / "schedule.lock"

HANDLED_COMMANDS = {"run"}

# What a single fire attempt ended as. Three states, not two: a wake that was
# REFUSED before anything started is neither a run nor a failure, and collapsing
# it into either one is the defect this vocabulary exists to prevent.
# Re-exported, not redefined: catch_up_lane's drain branches on the same three
# words this module returns, and one definition means they cannot drift. Callers
# and tests that import these from run keep working.
OUTCOME_FIRED = catch_up_lane.OUTCOME_FIRED
OUTCOME_FAILED = catch_up_lane.OUTCOME_FAILED
OUTCOME_BLOCKED = catch_up_lane.OUTCOME_BLOCKED

# wake_branch gates that refuse BEFORE a process exists. Read by step LABEL from
# the DispatchStatus rather than by matching the prose in `summary`, which is a
# human-facing string ai_mail is free to reword.
#
# Deliberately NOT here: "resolve" (the branch does not exist) and "blocklist"
# (the target is refused by policy). Both are decided, not transient - nothing
# about the next two minutes changes the answer, so retrying them on every tick
# inside the window is noise. Those stay failures and keep the failure backoff.
_BLOCKED_STEPS = ("pause", "lock", "blocked", "lock-acquire")


def print_introspection():
    """Display module introspection info."""
    console.print()
    console.print("[bold cyan]run Module[/bold cyan]")
    console.print()
    console.print("[dim]Decentralized scheduler — one discover/due/fire tick[/dim]")
    console.print()
    console.print("[yellow]Reads:[/yellow]")
    console.print("  [cyan]*[/cyan] src/aipass/*/.daemon/*.json [dim](per-branch schedule files)[/dim]")
    console.print("  [cyan]*[/cyan] daemon_json/daemon_runstate.json [dim](last_run/next_run state)[/dim]")
    console.print()
    console.print("[yellow]Fires via:[/yellow]")
    console.print("  [cyan]*[/cyan] wake_branch() [dim](ai_mail dispatch — direct import)[/dim]")
    console.print("  [cyan]*[/cyan] a drone subprocess [dim](command jobs — no wake, DPLAN-0338)[/dim]")
    console.print()


def print_help():
    """Display usage information."""
    console.print("\n[bold cyan]run — Decentralized Scheduler Tick[/bold cyan]")
    console.print("\n[yellow]USAGE:[/yellow]")
    console.print("  drone @daemon run           Run one discover/due/fire pass")
    console.print("  drone @daemon run --dry-run  Show what would fire without firing")
    console.print("  drone @daemon run --help     Show this help message")
    console.print("\n[yellow]DESCRIPTION:[/yellow]")
    console.print("  Sweeps src/aipass/*/.daemon/*.json for scheduled jobs,")
    console.print("  evaluates due-ness, and wakes each due branch via wake_branch().")
    for line in job_reference_lines():
        console.print(line)


def _log(message: str) -> None:
    """Print timestamped log line."""
    from datetime import datetime

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    console.print(f"[{timestamp}] {message}")


def _should_notify(job: dict) -> bool:
    """Check if this job should emit telegram notifications."""
    return job.get("notify", True)


def _blocked_reason(status) -> str:
    """Name the gate that refused to START this wake, or "" if none did.

    Reads the gate's own verdict via find_step() — a step counts only when it
    actually FAILED, because the same labels are written on the happy path too
    ("lock: No active lock — agent is sleeping" is an `ok`, not a refusal).
    """
    for label in _BLOCKED_STEPS:
        step = status.find_step(label)
        if step is not None and step[0] == "fail":
            return f"{label}: {step[2]}"
    return ""


def _mail_notice(to: str, subject: str, body: str) -> None:
    """Send a command job's notify.email mail. A mail that fails is logged; it never changes the fire."""
    failure = command_job.send_mail(to, subject, body, _DAEMON_ROOT)  # signed @daemon: cwd is identity
    if failure:
        _log(f"WARNING: notify mail to {to} not sent — {failure}")
        logger.warning("[run] notify mail to %s not sent: %s", to, failure)


def _fire_command_job(job: dict) -> tuple:
    """Run a command job's drone command as a subprocess (DPLAN-0338). No wake, no seat, no tokens.

    Never BLOCKED: nothing uses a seat, so no gate can refuse it and no active-agent
    lock is taken. Exit 0 is FIRED; a non-zero exit, a timeout or a command that
    never started is FAILED with the output tail as its detail. FIRE and DONE go
    to the console (the tick log) AND the logger (logs/run.log), pass or fail.
    """
    from aipass.daemon.apps.handlers.schedule.telegram_notifier import notify_complete, notify_error, notify_triggered

    owner, job_id, command = job["owner"], job["id"], job["command"]
    notify, mail_to = _should_notify(job), command_job.notify_email(job)

    _log(f"FIRE: {owner}/{job_id} -> command: {command}")
    logger.info("[run] FIRE %s/%s command: %s", owner, job_id, command)
    if notify:
        notify_triggered(owner, job_id)
    if mail_to:
        _mail_notice(mail_to, *command_job.start_mail(job))

    result = command_job.run_command(command, job.get("branch_path"), command_job.timeout_for(job))
    done = command_job.done_text(result)
    _log(f"DONE: {owner}/{job_id} — {done}")
    (logger.info if result.ok else logger.warning)("[run] DONE %s/%s %s", owner, job_id, done)
    if mail_to:
        _mail_notice(mail_to, *command_job.finish_mail(job, result))

    if result.ok:
        if notify:
            notify_complete(owner, job_id, done)
        return OUTCOME_FIRED, done
    if notify:
        notify_error(owner, job_id, done)
    return OUTCOME_FAILED, done


def _fire_job(job: dict, runstate: dict, header: str = "") -> tuple:
    """Fire a single job via direct wake_branch import (DPLAN-0204 path A).

    Rotation jobs don't wake their owner — they wake tonight's steward — so they
    are handed to the rotation module, which owns target selection and pointer
    state (DPLAN-0287).

    Returns (outcome: str, detail: str) where outcome is one of OUTCOME_FIRED,
    OUTCOME_FAILED or OUTCOME_BLOCKED. The third state is the point: only a wake
    that actually STARTED consumes the job's period.

    Rotation keeps the two-state answer and is mapped, not reclassified. A busy
    steward is already a recorded MISS there — the pointer advanced and a
    different citizen gets the night — so that night is genuinely spent, and
    calling it blocked would re-fire a rotation whose turn was already taken.

    A command job (DPLAN-0338) is asked about FIRST, ahead of rotation: a job that
    carries a command never wakes anyone, whatever else its schedule says.
    """
    if "command" in job:
        return _fire_command_job(job)

    if job.get("schedule", {}).get("type") == ROTATION_TYPE:
        ok, detail = fire_rotation(job, runstate, header=header)
        return (OUTCOME_FIRED if ok else OUTCOME_FAILED), detail

    # Cross-branch handler import authorized by DPLAN-0204 §2.8
    from aipass.ai_mail.apps.handlers.dispatch.wake import wake_branch  # noqa: E402
    from aipass.daemon.apps.handlers.schedule.telegram_notifier import (
        notify_triggered,
        notify_complete,
        notify_error,
    )

    owner = job["owner"]
    job_id = job["id"]
    prompt = recovery.compose_prompt(header, job["prompt"]) if header else job["prompt"]
    recovery.record_wake_prompt(owner, job_id, prompt)
    wake = job.get("wake", {})
    fresh = wake.get("fresh", True)
    model = wake.get("model")
    notify = _should_notify(job)

    _log(f"FIRE: {owner}/{job_id} -> wake_branch({owner}, fresh={fresh}, model={model})")

    if notify:
        notify_triggered(owner, job_id)

    try:
        status, ok = wake_branch(
            owner,
            custom_message=prompt,
            fresh=fresh,
            auto=True,
            sender="@daemon",
            model=model,
            # Every wake this module makes was fired by a clock, so it is a
            # scheduled wake by definition — the flag describes THIS caller's
            # lane, never the target. A manager target then goes headless
            # through dispatch_monitor (self-terminating, context pin, bounce
            # mail, lock cleanup) instead of an interactive tmux room that
            # nothing ever closes, and which blocked the next night's fire.
            # Deciding it per-target would mean reading the target's passport
            # here — a second copy of the manager gate wake_branch owns.
            scheduled=True,
            # A clock fired this, so the daemon never wants the answer: no job
            # prompt asks for one, and a wake-back would spend a whole @daemon
            # session reading a reply that does not exist (DPLAN-0337 R2).
            wake_back=False,
        )
        if ok:
            _log(f"OK: {owner}/{job_id} — {status.summary}")
            logger.info("[run] Fired %s/%s successfully", owner, job_id)
            if notify:
                notify_complete(owner, job_id, status.summary)
            return OUTCOME_FIRED, ""

        blocked = _blocked_reason(status)
        if blocked:
            # No telegram: a deferral is not an error, and a target that stays
            # busy would otherwise ping once per retry for as long as it sat
            # there. The console line and the prax record still name it.
            _log(f"BLOCKED: {owner}/{job_id} — {blocked}; stays due, retries this window")
            logger.info("[run] Blocked firing %s/%s: %s — not recorded as a run", owner, job_id, blocked)
            return OUTCOME_BLOCKED, blocked

        msg = status.summary
        _log(f"FAIL: {owner}/{job_id} — {msg}")
        logger.warning("[run] Failed to fire %s/%s: %s", owner, job_id, msg)
        if notify:
            notify_error(owner, job_id, msg)
        return OUTCOME_FAILED, msg
    except Exception as e:
        logger.error("[run] Exception firing %s/%s: %s", owner, job_id, e)
        _log(f"ERROR: {owner}/{job_id} — {e}")
        if notify:
            notify_error(owner, job_id, str(e))
        return OUTCOME_FAILED, str(e)


def _seed_interval_slots(enabled: List[dict], runstate: dict, dry_run: bool) -> int:
    """Give every never-run interval job a rhythm before it can fire. Returns count seeded.

    Runs BEFORE the due check, because an unseeded interval job is due on the
    very tick that discovers it — seeding afterwards would already have fired it
    at whatever minute the daemon happened to tick, which is the whole defect.

    A job declaring no slot keeps today's behaviour and fires immediately. That
    is not silent: it warns, names itself, and says what is about to happen, so
    an owner who wanted a slot finds out on the first tick rather than a week
    later from the wrong hour in their log.
    """
    seeded_count = 0
    for job in enabled:
        if not needs_slot_seed(job, runstate):
            continue

        owner, job_id = job["owner"], job["id"]
        slot = job.get("schedule", {}).get("slot")

        if not slot:
            logger.warning(
                "[run] %s/%s is an interval job that has never run and declares no 'slot' — "
                "its first fire is IMMEDIATE, on this tick, and every later run measures from "
                "that arbitrary minute. Add a slot to choose the hour.",
                owner,
                job_id,
            )
            _log(f"WARNING: {owner}/{job_id} — no slot, first fire is immediate at this tick's minute")
            continue

        if dry_run:
            _log(f"DRY RUN — would seed {owner}/{job_id} from slot {slot}")
            continue

        seeded = seed_interval_slot(runstate, job)
        if seeded is None:
            _log(f"WARNING: {owner}/{job_id} — slot {slot!r} unreadable, first fire is immediate")
            continue

        seeded_count += 1
        next_run = runstate["jobs"][job_key(owner, job_id)].get("next_run")
        _log(f"SEED: {owner}/{job_id} — slot {slot}, last_run seeded {seeded}, first fire {next_run}")

    if seeded_count and not dry_run:
        save_runstate(runstate)
    return seeded_count


def _report_missed_windows(enabled: List[dict], runstate: dict, dry_run: bool) -> int:
    """Write one MISSED line per daily job whose window closed unrun. Returns count.

    Independent of ``catch_up``: a job nobody opted in still missed its window,
    and that is exactly the fact an operator needs in order to decide whether to
    opt it in. Stamped once per job per day so a tick every two minutes does not
    repeat the same miss until midnight.
    """
    missed_count = 0
    for job in enabled:
        if not missed_window(job, runstate):
            continue

        owner, job_id = job["owner"], job["id"]
        window = window_label(job["schedule"])
        # ONE predicate for the line and the fire. Reading the raw field here
        # while is_job_due() read catch_up_on() is what let 11:37:52 log
        # "catch_up is off - not firing" three seconds before firing.
        catch_up = catch_up_on(job.get("schedule", {}))

        if dry_run:
            _log(f"DRY RUN — would record MISSED {owner}/{job_id} (window {window})")
            continue

        if not note_missed_window(runstate, owner, job_id):
            continue

        missed_count += 1
        tail = "catch_up is on — firing late this tick" if catch_up else "catch_up is off — not firing"
        logger.warning("[run] MISSED %s/%s: window %s closed with no run; %s", owner, job_id, window, tail)
        _log(f"MISSED: {owner}/{job_id} — window {window} closed with no run; {tail}")

    if missed_count and not dry_run:
        save_runstate(runstate)
    return missed_count


def run_tick(dry_run: bool = False) -> dict:
    """Execute one discover -> due-check -> fire pass, and stamp the tick.

    THE STAMP IS IN A finally, and that is the whole reason this wrapper exists.
    ``last_tick`` is what gap detection reads, so a tick that returned early —
    no jobs discovered, nothing enabled — must still record that the scheduler
    was alive. Miss those and the next tick reports a gap the fleet never had,
    and queues catch-ups for windows nobody missed.

    A dry run stamps nothing: it is a question about the world, not an event in
    it, and answering it must not erase the gap a real tick is about to report.
    """
    runstate = load_runstate()
    try:
        return _tick_body(runstate, dry_run)
    finally:
        if not dry_run:
            recovery.record_tick(runstate)
            save_runstate(runstate)


def _tick_body(runstate: dict, dry_run: bool = False) -> dict:
    """The tick itself. Returns summary dict with counts."""
    results = {
        "discovered": 0,
        "enabled": 0,
        "due": 0,
        "fired": 0,
        "failed": 0,
        "blocked": 0,
        "skipped": 0,
        "seeded": 0,
        "missed": 0,
        "caught_up": 0,
        "queued": 0,
        "drained": 0,
    }

    json_handler.log_operation("scheduler_tick", {"dry_run": dry_run})

    # Step 1: Discover
    _log("Discovering .daemon/ schedule files...")
    jobs = discover_jobs()
    results["discovered"] = len(jobs)

    if not jobs:
        _log("No jobs discovered.")
        return results

    # Step 2: Filter enabled
    enabled = [j for j in jobs if j.get("enabled", True)]
    results["enabled"] = len(enabled)
    _log(f"Found {len(jobs)} job(s), {len(enabled)} enabled")

    if not enabled:
        _log("No enabled jobs.")
        return results

    # Step 3: Check due. The runstate arrived from run_tick, which holds it so
    # the tick stamp survives every early return above.
    # Prune orphan runstate entries. Persist immediately when anything changed:
    # pruning happens on every tick but the save used to live inside the fire
    # loop, so quiet ticks dropped their prunes and stale entries survived for
    # months (DPLAN-0287 piece 3).
    active_keys = {job_key(j["owner"], j["id"]) for j in jobs}
    pruned = prune_orphans(runstate, active_keys)
    if pruned and not dry_run:
        save_runstate(runstate)
        _log(f"Pruned {pruned} orphan runstate entr{'y' if pruned == 1 else 'ies'}")

    results["seeded"] = _seed_interval_slots(enabled, runstate, dry_run)

    # DPLAN-0332. Before the due check on purpose: a job whose regular window is
    # open right now must be able to supersede its own queued entry on this very
    # tick, and it can only do that if the entry already exists.
    gap, results["queued"] = catch_up_lane.detect_and_queue(enabled, runstate, dry_run, _log)

    results["missed"] = _report_missed_windows(enabled, runstate, dry_run)

    due_jobs = [j for j in enabled if is_job_due(j, runstate)]
    results["due"] = len(due_jobs)
    results["skipped"] = len(enabled) - len(due_jobs)

    if not due_jobs:
        _log("No jobs due at this time.")
        for j in enabled:
            _log(f"  {j['owner']}/{j['id']} — not due")
        # A quiet tick is exactly when the queue should move: nothing is
        # competing for the fleet and the branches are most likely free.
        results["drained"] = catch_up_lane.drain_one(runstate, enabled, dry_run, _log, _fire_job)
        return results

    _log(f"{len(due_jobs)} job(s) due:")
    for j in due_jobs:
        _log(f"  {j['owner']}/{j['id']} ({j['schedule']['type']})")

    if dry_run:
        _log("DRY RUN — no jobs fired.")
        return results

    # Step 4: Fire due jobs
    for job in due_jobs:
        # Asked BEFORE the fire: firing is what makes it untrue, so a caught-up
        # run read after the fact would always report as an ordinary one.
        caught_up = is_catch_up_fire(job, runstate)

        # SUPERSESSION (DPLAN-0332). This job's regular window arrived before
        # its queued catch-up got a turn, so the queue entry is dropped — but
        # its missed list rides along on THIS wake. The truth about time travels
        # with whichever wake goes first, or an agent whose catch-up was
        # superseded would never learn it was away at all.
        superseded = recovery.drop_from_queue(runstate, job["owner"], job["id"])
        missed_list = superseded.get("missed", []) if superseded else []
        if superseded:
            _log(
                f"SUPERSEDED: {job['owner']}/{job['id']} — regular window arrived first, "
                f"carrying {len(missed_list)} missed window(s) on this wake"
            )

        state = get_job_state(runstate, job["owner"], job["id"])
        header = recovery.scheduled_header(job, state, missed=missed_list)
        outcome, detail = _fire_job(job, runstate, header=header)
        if outcome == OUTCOME_FIRED:
            results["fired"] += 1
            if caught_up:
                results["caught_up"] += 1
                window = window_label(job["schedule"])
                _log(f"CAUGHT UP: {job['owner']}/{job['id']} — ran after its {window} window closed")
            update_job_runstate(runstate, job["owner"], job["id"], job["schedule"], caught_up=caught_up)
        elif outcome == OUTCOME_BLOCKED:
            # Never stamps last_run — the job stays due and the next tick tries
            # again inside the same window.
            results["blocked"] += 1
            record_job_blocked(runstate, job["owner"], job["id"], detail)
        else:
            results["failed"] += 1
            record_job_failure(runstate, job["owner"], job["id"], detail)
        save_runstate(runstate)

        if job != due_jobs[-1]:
            time.sleep(1.0)

    # One catch-up per tick at most, and never in front of a live window: the
    # on-time fires above have already had their turn.
    results["drained"] = catch_up_lane.drain_one(runstate, enabled, dry_run, _log, _fire_job)

    _log(
        f"Tick complete: {results['fired']} fired, {results['failed']} failed, "
        f"{results['blocked']} blocked, {results['skipped']} skipped, "
        f"{results['seeded']} seeded, {results['missed']} missed, {results['caught_up']} caught up, "
        f"{results['queued']} queued, {results['drained']} drained"
    )
    return results


def _run_with_lock(dry_run: bool = False) -> int:
    """Run one tick under the single-instance lock. Returns the process exit code.

    LOCK_FILE stays owned HERE and is passed in, so a test that seams the path on
    this module still seams the file that actually gets opened.
    """
    tick_lock.prepare(LOCK_FILE)

    if not tick_lock.available():
        _log("fcntl not available (non-Unix), running without lock.")
        results = run_tick(dry_run)
        return 1 if results["failed"] > 0 else 0

    handle = tick_lock.acquire(LOCK_FILE)
    if handle is None:
        _log("Another scheduler instance is running, skipping.")
        return 0

    try:
        results = run_tick(dry_run)
        return 1 if results["failed"] > 0 else 0
    finally:
        tick_lock.release(handle)


def handle_command(command: str, args: List[str]) -> bool:
    """Handle 'run' command from daemon CLI router."""
    if command not in HANDLED_COMMANDS:
        return False

    if not args:
        pass
    elif args[0] in ("--help", "-h"):
        print_help()
        return True

    gate("run", args, flags=("--dry-run",), usage="drone @daemon run [--dry-run]")

    dry_run = "--dry-run" in args

    _log("=" * 60)
    _log("Decentralized scheduler tick")

    exit_code = _run_with_lock(dry_run)

    _log("=" * 60)

    if exit_code != 0:
        sys.exit(exit_code)

    return True
