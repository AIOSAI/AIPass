# =================== AIPass ====================
# Name: run.py
# Description: Manual one-tick scheduler command (drone @daemon run)
# Version: 1.7.0
# Created: 2026-06-15
# Modified: 2026-10-22
# =============================================

"""
Manual one-tick scheduler — discover .daemon/ jobs, fire due ones via wake_branch.

Reference: docs/scheduler_tick.md
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
    failed_today_at,
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

# Three states: a wake REFUSED before it started is neither a run nor a failure.
# Re-exported from catch_up_lane so the drain and this module cannot drift.
OUTCOME_FIRED = catch_up_lane.OUTCOME_FIRED
OUTCOME_FAILED = catch_up_lane.OUTCOME_FAILED
OUTCOME_BLOCKED = catch_up_lane.OUTCOME_BLOCKED

# wake_branch gates that refuse BEFORE a process exists, matched by step label (summary prose may change).
# "resolve" and "blocklist" are deliberately absent: not transient, so they stay failures with backoff.
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


def _blocked_reason(status) -> str:
    """Name the gate that refused to START this wake, or "" if none did.

    Only a FAILED step counts: the same labels are written as `ok` on the happy path.
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
    """Run a command job's drone command as a subprocess. No wake, no seat, no tokens.

    Never BLOCKED: exit 0 is FIRED; anything else is FAILED with the output tail as detail.
    """
    owner, job_id, command = job["owner"], job["id"], job["command"]
    mail_to = command_job.notify_email(job)

    _log(f"FIRE: {owner}/{job_id} -> command: {command}")
    logger.info("[run] FIRE %s/%s command: %s", owner, job_id, command)
    if mail_to:
        _mail_notice(mail_to, *command_job.start_mail(job))

    result = command_job.run_command(command, job.get("branch_path"), command_job.timeout_for(job))
    done = command_job.done_text(result)
    _log(f"DONE: {owner}/{job_id} — {done}")
    (logger.info if result.ok else logger.warning)("[run] DONE %s/%s %s", owner, job_id, done)
    if mail_to:
        _mail_notice(mail_to, *command_job.finish_mail(job, result))

    return (OUTCOME_FIRED if result.ok else OUTCOME_FAILED), done


def _fire_job(job: dict, runstate: dict, header: str = "") -> tuple:
    """Fire a single job via direct wake_branch import.

    Returns (outcome, detail); only OUTCOME_FIRED consumes the job's period. Rotation never
    reports BLOCKED: a busy steward is already a recorded miss, so blocked would re-fire it.
    """
    if "command" in job:
        return _fire_command_job(job)

    if job.get("schedule", {}).get("type") == ROTATION_TYPE:
        ok, detail = fire_rotation(job, runstate, header=header)
        # Logged here, not in rotation: prax files a line under the calling module (logs/run.log).
        if ok:
            logger.info("[run] Fired %s/%s: %s", job["owner"], job["id"], detail)
        else:
            logger.warning("[run] Failed to fire %s/%s: %s", job["owner"], job["id"], detail)
        return (OUTCOME_FIRED if ok else OUTCOME_FAILED), detail

    from aipass.ai_mail.apps.modules.door_wake import wake_branch

    owner = job["owner"]
    job_id = job["id"]
    prompt = recovery.compose_prompt(header, job["prompt"]) if header else job["prompt"]
    recovery.record_wake_prompt(owner, job_id, prompt)
    wake = job.get("wake", {})
    fresh = wake.get("fresh", True)
    model = wake.get("model")

    _log(f"FIRE: {owner}/{job_id} -> wake_branch({owner}, fresh={fresh}, model={model})")

    try:
        status, ok = wake_branch(
            owner,
            custom_message=prompt,
            fresh=fresh,
            auto=True,
            sender="@daemon",
            model=model,
            # Describes this caller's lane, not the target: a manager target goes headless
            # instead of an interactive tmux room nothing closes (which blocks the next fire).
            scheduled=True,
            # No job prompt wants an answer; a wake-back would spend a @daemon session on nothing.
            wake_back=False,
        )
        if ok:
            _log(f"OK: {owner}/{job_id} — {status.summary}")
            logger.info("[run] Fired %s/%s successfully", owner, job_id)
            return OUTCOME_FIRED, ""

        blocked = _blocked_reason(status)
        if blocked:
            _log(f"BLOCKED: {owner}/{job_id} — {blocked}; stays due, retries this window")
            logger.info("[run] Blocked firing %s/%s: %s — not recorded as a run", owner, job_id, blocked)
            return OUTCOME_BLOCKED, blocked

        msg = status.summary
        _log(f"FAIL: {owner}/{job_id} — {msg}")
        logger.warning("[run] Failed to fire %s/%s: %s", owner, job_id, msg)
        return OUTCOME_FAILED, msg
    except Exception as e:
        logger.error("[run] Exception firing %s/%s: %s", owner, job_id, e)
        _log(f"ERROR: {owner}/{job_id} — {e}")
        return OUTCOME_FAILED, str(e)


def _seed_interval_slots(enabled: List[dict], runstate: dict, dry_run: bool) -> int:
    """Give every never-run interval job a rhythm before it can fire. Returns count seeded.

    Must run BEFORE the due check: an unseeded interval job is due on the tick that discovers it.
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
                "its first fire is IMMEDIATE, on this tick (never, if its interval_minutes is not "
                "a positive number), and every later run measures from that arbitrary minute. "
                "Add a slot to choose the hour.",
                owner,
                job_id,
            )
            _log(
                f"WARNING: {owner}/{job_id} — no slot, first fire is immediate at this tick's minute "
                "(never, if its interval is not a positive number)"
            )
            continue

        if dry_run:
            _log(f"DRY RUN — would seed {owner}/{job_id} from slot {slot}")
            continue

        seeded = seed_interval_slot(runstate, job)
        if seeded is None:
            _log(
                f"WARNING: {owner}/{job_id} — slot {slot!r} not seeded: an unreadable slot fires "
                "immediately, an interval that is not a positive number never fires"
            )
            continue

        seeded_count += 1
        next_run = runstate["jobs"][job_key(owner, job_id)].get("next_run")
        _log(f"SEED: {owner}/{job_id} — slot {slot}, last_run seeded {seeded}, first fire {next_run}")

    if seeded_count and not dry_run:
        save_runstate(runstate)
    return seeded_count


def _report_missed_windows(enabled: List[dict], runstate: dict, dry_run: bool) -> int:
    """Write one MISSED line per daily job whose window closed unrun, catch_up or not. Returns count."""
    missed_count = 0
    for job in enabled:
        if not missed_window(job, runstate):
            continue

        owner, job_id = job["owner"], job["id"]
        window = window_label(job["schedule"])
        # Same predicate is_job_due() uses; reading the raw field lets the line contradict the fire.
        catch_up = catch_up_on(job.get("schedule", {}))

        if dry_run:
            _log(f"DRY RUN — would record MISSED {owner}/{job_id} (window {window})")
            continue

        if not note_missed_window(runstate, owner, job_id):
            continue

        missed_count += 1
        tail = "catch_up is on — firing late this tick" if catch_up else "catch_up is off — not firing"
        # A windowed job retries a failure inside its window, so a missed window may hold real runs.
        failed_at = failed_today_at(runstate, owner, job_id)
        unrun = f"no successful run (last attempt failed at {failed_at})" if failed_at else "no run"
        logger.warning("[run] MISSED %s/%s: window %s closed with %s; %s", owner, job_id, window, unrun, tail)
        _log(f"MISSED: {owner}/{job_id} — window {window} closed with {unrun}; {tail}")

    if missed_count and not dry_run:
        save_runstate(runstate)
    return missed_count


def run_tick(dry_run: bool = False) -> dict:
    """Execute one discover -> due-check -> fire pass, and stamp the tick.

    The stamp is in a finally: gap detection reads last_tick, so early returns must stamp too.
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

    _log("Discovering .daemon/ schedule files...")
    jobs = discover_jobs()
    results["discovered"] = len(jobs)

    if not jobs:
        _log("No jobs discovered.")
        return results

    enabled = [j for j in jobs if j.get("enabled", True)]
    results["enabled"] = len(enabled)
    _log(f"Found {len(jobs)} job(s), {len(enabled)} enabled")

    if not enabled:
        _log("No enabled jobs.")
        return results

    # Save prunes now: quiet ticks never reach the save in the fire loop.
    active_keys = {job_key(j["owner"], j["id"]) for j in jobs}
    pruned = prune_orphans(runstate, active_keys)
    if pruned and not dry_run:
        save_runstate(runstate)
        _log(f"Pruned {pruned} orphan runstate entr{'y' if pruned == 1 else 'ies'}")

    results["seeded"] = _seed_interval_slots(enabled, runstate, dry_run)

    # Before the due check: an open window can only supersede its queued entry if the entry exists.
    gap, results["queued"] = catch_up_lane.detect_and_queue(enabled, runstate, dry_run, _log)

    results["missed"] = _report_missed_windows(enabled, runstate, dry_run)

    due_jobs = [j for j in enabled if is_job_due(j, runstate)]
    results["due"] = len(due_jobs)
    results["skipped"] = len(enabled) - len(due_jobs)

    if not due_jobs:
        _log("No jobs due at this time.")
        for j in enabled:
            _log(f"  {j['owner']}/{j['id']} — not due")
        results["drained"] = catch_up_lane.drain_one(runstate, enabled, dry_run, _log, _fire_job)
        return results

    _log(f"{len(due_jobs)} job(s) due:")
    for j in due_jobs:
        _log(f"  {j['owner']}/{j['id']} ({j['schedule']['type']})")

    if dry_run:
        _log("DRY RUN — no jobs fired.")
        return results

    for job in due_jobs:
        # Asked BEFORE the fire: firing makes it untrue.
        caught_up = is_catch_up_fire(job, runstate)

        # A superseded queue entry's missed list rides on this wake, or the agent never learns it was away.
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
            # Never stamps last_run: the job stays due for the next tick.
            results["blocked"] += 1
            record_job_blocked(runstate, job["owner"], job["id"], detail)
        else:
            results["failed"] += 1
            record_job_failure(runstate, job["owner"], job["id"], detail)
        save_runstate(runstate)

        if job != due_jobs[-1]:
            time.sleep(1.0)

    # At most one catch-up per tick, and only after the on-time fires.
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

    LOCK_FILE is read here, not in tick_lock, so tests patching run.LOCK_FILE hit the real open.
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
