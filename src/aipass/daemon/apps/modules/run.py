# =================== AIPass ====================
# Name: run.py
# Description: Manual one-tick scheduler command (drone @daemon run)
# Version: 1.3.0
# Created: 2026-06-15
# Modified: 2026-08-31
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
from aipass.daemon.apps.modules.rotation import ROTATION_TYPE, fire_rotation
from aipass.daemon.apps.handlers.schedule.discovery import discover_jobs
from aipass.daemon.apps.handlers.schedule.runstate import (
    load_runstate,
    save_runstate,
    is_job_due,
    update_job_runstate,
    record_job_failure,
    record_job_blocked,
    job_key,
    prune_orphans,
)
from aipass.daemon.apps.handlers.module_root import module_file

try:
    import fcntl
except ImportError:
    fcntl = None  # type: ignore[assignment]
    logger.info("[run] fcntl unavailable (Windows)")

_DAEMON_ROOT = module_file(__file__).parents[2]  # src/aipass/daemon/
LOCK_FILE = _DAEMON_ROOT / "daemon_json" / "schedule.lock"

HANDLED_COMMANDS = {"run"}

# What a single fire attempt ended as. Three states, not two: a wake that was
# REFUSED before anything started is neither a run nor a failure, and collapsing
# it into either one is the defect this vocabulary exists to prevent.
OUTCOME_FIRED = "fired"
OUTCOME_FAILED = "failed"
OUTCOME_BLOCKED = "blocked"

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
    console.print("\n[bold cyan]SCHEDULING — How to author a job:[/bold cyan]")
    console.print("  [bold]File:[/bold] src/aipass/<branch>/.daemon/schedule.json")
    console.print()
    console.print("  [bold]Schema:[/bold]")
    console.print("    {")
    console.print('      "version": 1,')
    console.print('      "branch": "@<branch>",')
    console.print('      "jobs": [')
    console.print("        {")
    console.print('          "id": "my-job",')
    console.print('          "enabled": true,')
    console.print('          "schedule": { "type": "interval", "interval_minutes": 30 },')
    console.print('          "wake": { "fresh": true, "model": "haiku" },')
    console.print('          "prompt": "Do something, then STOP."')
    console.print("        }")
    console.print("      ]")
    console.print("    }")
    console.print()
    console.print("  [bold]Schedule types:[/bold]")
    console.print("    [cyan]interval[/cyan]  interval_minutes: N")
    console.print("              [dim]Fires when elapsed >= N since last_run. Fires immediately if never run.[/dim]")
    console.print("    [cyan]daily[/cyan]     time: HH:MM")
    console.print("              [dim]+/-15 min window, once per day.[/dim]")
    console.print("    [cyan]hourly[/cyan]    time: M  [dim](minute of hour)[/dim]")
    console.print("              [dim]+/-15 min window, once per hour.[/dim]")
    console.print("    [cyan]once[/cyan]      due_date: YYYY-MM-DD")
    console.print("              [dim]Fires when date <= today, then marks completed.[/dim]")
    console.print("    [cyan]rotation[/cyan]  time: HH:MM")
    console.print("              [dim]Daily window, but wakes the NEXT citizen on the fleet[/dim]")
    console.print("              [dim]roster instead of the owner. See drone @daemon rotation.[/dim]")
    console.print()
    console.print("  [bold]wake options:[/bold]  fresh (bool), model (haiku/sonnet — use light models)")
    console.print()
    console.print("  [bold]Staggering:[/bold] No native offset field. Seed different last_run values")
    console.print("  in daemon_json/daemon_runstate.json to offset first-fire timing.")
    console.print()


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


def _fire_job(job: dict, runstate: dict) -> tuple:
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
    """
    if job.get("schedule", {}).get("type") == ROTATION_TYPE:
        ok, detail = fire_rotation(job, runstate)
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
    prompt = job["prompt"]
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


def run_tick(dry_run: bool = False) -> dict:
    """
    Execute one discover -> due-check -> fire pass.

    Returns summary dict with counts.
    """
    results = {
        "discovered": 0,
        "enabled": 0,
        "due": 0,
        "fired": 0,
        "failed": 0,
        "blocked": 0,
        "skipped": 0,
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

    # Step 3: Load runstate and check due
    runstate = load_runstate()

    # Prune orphan runstate entries. Persist immediately when anything changed:
    # pruning happens on every tick but the save used to live inside the fire
    # loop, so quiet ticks dropped their prunes and stale entries survived for
    # months (DPLAN-0287 piece 3).
    active_keys = {job_key(j["owner"], j["id"]) for j in jobs}
    pruned = prune_orphans(runstate, active_keys)
    if pruned and not dry_run:
        save_runstate(runstate)
        _log(f"Pruned {pruned} orphan runstate entr{'y' if pruned == 1 else 'ies'}")

    due_jobs = [j for j in enabled if is_job_due(j, runstate)]
    results["due"] = len(due_jobs)
    results["skipped"] = len(enabled) - len(due_jobs)

    if not due_jobs:
        _log("No jobs due at this time.")
        for j in enabled:
            _log(f"  {j['owner']}/{j['id']} — not due")
        return results

    _log(f"{len(due_jobs)} job(s) due:")
    for j in due_jobs:
        _log(f"  {j['owner']}/{j['id']} ({j['schedule']['type']})")

    if dry_run:
        _log("DRY RUN — no jobs fired.")
        return results

    # Step 4: Fire due jobs
    for job in due_jobs:
        outcome, detail = _fire_job(job, runstate)
        if outcome == OUTCOME_FIRED:
            results["fired"] += 1
            update_job_runstate(runstate, job["owner"], job["id"], job["schedule"])
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

    _log(
        f"Tick complete: {results['fired']} fired, {results['failed']} failed, "
        f"{results['blocked']} blocked, {results['skipped']} skipped"
    )
    return results


def _run_with_lock(dry_run: bool = False) -> int:
    """Run tick with fcntl lock to prevent concurrent execution."""
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)

    if fcntl is None:
        _log("fcntl not available (non-Unix), running without lock.")
        results = run_tick(dry_run)
        return 1 if results["failed"] > 0 else 0

    lock_fd = open(LOCK_FILE, "w", encoding="utf-8")  # noqa: SIM115
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as e:
        logger.info("[run] Lock acquisition failed (another instance running): %s", e)
        _log("Another scheduler instance is running, skipping.")
        lock_fd.close()
        return 0

    try:
        results = run_tick(dry_run)
        return 1 if results["failed"] > 0 else 0
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


def handle_command(command: str, args: List[str]) -> bool:
    """Handle 'run' command from daemon CLI router."""
    if command not in HANDLED_COMMANDS:
        return False

    if not args:
        pass
    elif args[0] in ("--help", "-h"):
        print_help()
        return True

    dry_run = "--dry-run" in args

    _log("=" * 60)
    _log("Decentralized scheduler tick")

    exit_code = _run_with_lock(dry_run)

    _log("=" * 60)

    if exit_code != 0:
        sys.exit(exit_code)

    return True
