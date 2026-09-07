# =================== AIPass ====================
# Name: run.py
# Description: Manual one-tick scheduler command (drone @daemon run)
# Version: 1.4.0
# Created: 2026-06-15
# Modified: 2026-09-07
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
    console.print("              [dim]Fires when elapsed >= N since last_run.[/dim]")
    console.print("              [dim]Never run and no slot -> fires IMMEDIATELY (warned in run.log).[/dim]")
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
    console.print("  [bold]Optional schedule fields:[/bold]")
    console.print('    [cyan]slot[/cyan]      "2026-09-06T03:00:00"   [dim](interval jobs)[/dim]')
    console.print("              [dim]An ISO instant naming ONE occurrence of the rhythm you want.[/dim]")
    console.print("              [dim]A job that has never run is seeded from it, so the first fire[/dim]")
    console.print("              [dim]lands on the next slot instead of the next tick. Without it,[/dim]")
    console.print("              [dim]enabling a weekly job at 01:34 locks it to 01:34 forever.[/dim]")
    console.print("              [dim]A past slot keeps its phase — it is rolled forward, not used raw.[/dim]")
    console.print("    [cyan]catch_up[/cyan]  true                    [dim](daily and rotation jobs)[/dim]")
    console.print("              [dim]Off unless stated. When the window closed with no run (host[/dim]")
    console.print("              [dim]down, daemon not ticking), the first tick after it fires the[/dim]")
    console.print("              [dim]job once and stamps caught_up on the runstate row.[/dim]")
    console.print()
    console.print("  [bold]Staggering:[/bold] Prefer `slot` on interval jobs. Seeding last_run values")
    console.print("  in daemon_json/daemon_runstate.json by hand still works for the other types.")
    console.print()
    console.print("  [bold]run.log:[/bold] a MISSED line names every daily job whose window closed")
    console.print("  unrun — once per job per day, whether or not catch_up is on.")
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
        catch_up = job.get("schedule", {}).get("catch_up")

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
        "seeded": 0,
        "missed": 0,
        "caught_up": 0,
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

    results["seeded"] = _seed_interval_slots(enabled, runstate, dry_run)
    results["missed"] = _report_missed_windows(enabled, runstate, dry_run)

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
        # Asked BEFORE the fire: firing is what makes it untrue, so a caught-up
        # run read after the fact would always report as an ordinary one.
        caught_up = is_catch_up_fire(job, runstate)
        outcome, detail = _fire_job(job, runstate)
        if outcome == OUTCOME_FIRED:
            results["fired"] += 1
            if caught_up:
                results["caught_up"] += 1
                _log(
                    f"CAUGHT UP: {job['owner']}/{job['id']} — ran after its {window_label(job['schedule'])} window closed"
                )
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

    _log(
        f"Tick complete: {results['fired']} fired, {results['failed']} failed, "
        f"{results['blocked']} blocked, {results['skipped']} skipped, "
        f"{results['seeded']} seeded, {results['missed']} missed, {results['caught_up']} caught up"
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

    gate("run", args, flags=("--dry-run",), usage="drone @daemon run [--dry-run]")

    dry_run = "--dry-run" in args

    _log("=" * 60)
    _log("Decentralized scheduler tick")

    exit_code = _run_with_lock(dry_run)

    _log("=" * 60)

    if exit_code != 0:
        sys.exit(exit_code)

    return True
