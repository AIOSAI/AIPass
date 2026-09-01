# =================== AIPass ====================
# Name: rotation.py
# Description: Steward rotation firing + status surface (drone @daemon rotation)
# Version: 1.1.0
# Created: 2026-08-12
# Modified: 2026-08-31
# =============================================

"""
Steward rotation — wakes one citizen a night for its maintenance turn.

A single `rotation` job (daemon's own .daemon/schedule.json) fires daily, picks
the next citizen off the roster, wakes it with the steward prompt, and advances
the pointer. Busy target? The miss is logged with the branch named and the
pointer advances anyway — that citizen gets its next turn in the cycle.

This module owns wake POLICY (blocklist, manager lane, model); the rotation
handler owns roster and pointer state.
"""

import inspect
import json
from typing import List, Optional

from aipass.prax import logger
from aipass.cli.apps.modules import console, warning
from aipass.daemon.apps.handlers.json import json_handler
from aipass.daemon.apps.handlers.schedule.discovery import MANAGER_CLASS, discover_jobs
from aipass.daemon.apps.handlers.schedule.runstate import load_runstate, job_key
from aipass.daemon.apps.handlers.schedule.rotation import (
    DEFAULT_INCLUDE_MANAGERS,
    OUTCOME_FAILED,
    OUTCOME_MISSED,
    OUTCOME_SKIPPED,
    OUTCOME_WOKEN,
    build_roster,
    get_rotation_state,
    next_target,
    record_rotation,
    render_prompt,
)

HANDLED_COMMANDS = {"rotation"}

ROTATION_TYPE = "rotation"

# Steward work needs judgment (APLAN writing, audit reading) — heavier than the
# inbox sweep's read-and-act wake.
DEFAULT_WAKE_MODEL = "sonnet"

SKIP_BLOCKLIST = "wake-blocklist"
SKIP_MANAGER_LANE = "manager-lane-unavailable"


def print_introspection():
    """Display module introspection info."""
    console.print()
    console.print("[bold cyan]rotation Module[/bold cyan]")
    console.print()
    console.print("[dim]Steward rotation — one citizen per night, in registry order[/dim]")
    console.print()
    console.print("[yellow]Reads:[/yellow]")
    console.print("  [cyan]*[/cyan] AIPASS_REGISTRY.json + projects/*/[dim]*_REGISTRY.json (roster)[/dim]")
    console.print("  [cyan]*[/cyan] daemon_json/daemon_runstate.json [dim](pointer + turn history)[/dim]")
    console.print()
    console.print("[yellow]Wakes via:[/yellow]")
    console.print("  [cyan]*[/cyan] wake_branch() [dim](ai_mail dispatch — direct import)[/dim]")
    console.print()


def print_help():
    """Display usage information."""
    console.print("\n[bold cyan]rotation — Nightly Steward Rotation[/bold cyan]")
    console.print("\n[yellow]USAGE:[/yellow]")
    console.print("  drone @daemon rotation           Show roster, whose turn is next, recent turns")
    console.print("  drone @daemon rotation --json    Machine-readable rotation state")
    console.print("  drone @daemon rotation --help    Show this help message")
    console.print("\n[yellow]DESCRIPTION:[/yellow]")
    console.print("  The rotation fires from a `rotation` job in a .daemon/schedule.json.")
    console.print("  Each night it wakes the next citizen on the roster with the steward")
    console.print("  prompt, then advances the pointer — busy targets are logged as a miss")
    console.print("  and get their next turn in the cycle.")
    console.print("\n[yellow]ROSTER RULES:[/yellow]")
    console.print("  [cyan]*[/cyan] Registry order — framework citizens, then project citizens")
    console.print("  [cyan]*[/cyan] @devpulse is never stewarded")
    console.print("  [cyan]*[/cyan] Managers are excluded unless config.include_managers is true")
    console.print("  [cyan]*[/cyan] Manager wakes also need ai_mail's scheduled lane — skipped if absent")
    console.print("\n[yellow]JOB STANZA:[/yellow]")
    console.print('  {"id": "fleet-steward", "schedule": {"type": "rotation", "time": "05:00"},')
    console.print('   "wake": {"fresh": true, "model": "sonnet"},')
    console.print('   "config": {"include_managers": false}, "prompt": "STEWARD NIGHT for {branch}..."}')
    console.print()


def _log(message: str) -> None:
    """Print timestamped log line."""
    from datetime import datetime

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    console.print(f"[{timestamp}] {message}")


def _apply_wake_blocklist(roster: List[dict]) -> List[dict]:
    """Drop roster entries ai_mail refuses to wake.

    The handler excludes @devpulse structurally; this re-checks the live
    blocklist so a branch added there tomorrow is honoured without a code change.
    """
    try:
        from aipass.ai_mail.apps.handlers.dispatch.wake import is_wake_blocked
    # OSError, not only ImportError: MEASURED 2026-08-31 - importing ai_mail's wake
    # module under a dead working directory raises FileNotFoundError today, and an
    # uncaught one here takes the whole rotation down from inside an OPTIONAL
    # consult. The fallback is unchanged and still fail-open by design (an
    # unfiltered roster, logged); what changes is that the world reaching it no
    # longer arrives as a traceback.
    except (ImportError, OSError) as e:
        logger.warning("[rotation] Wake blocklist unavailable, roster unfiltered: %s", e)
        return roster

    kept = []
    for entry in roster:
        if is_wake_blocked(entry["email"]):
            logger.info("[rotation] %s dropped from roster (%s)", entry["email"], SKIP_BLOCKLIST)
            continue
        kept.append(entry)
    return kept


def _scheduled_lane_available() -> bool:
    """Report whether ai_mail's wake_branch accepts the scheduled headless lane.

    @ai_mail is building `scheduled=True` (headless + 350k pin) in parallel with
    this build. Until the parameter exists, manager targets are skipped by name
    rather than dropped into an interactive 5am tmux session.
    """
    try:
        from aipass.ai_mail.apps.handlers.dispatch.wake import wake_branch

        return "scheduled" in inspect.signature(wake_branch).parameters
    except (ImportError, TypeError, ValueError) as e:
        logger.warning("[rotation] Could not inspect wake_branch signature: %s", e)
        return False


def _wake_steward(target: dict, prompt: str, model: str, fresh: bool) -> tuple:
    """Wake one steward. Returns (ok: bool, detail: str, errored: bool).

    `errored` separates a crash in the wake path from an ordinary busy target —
    the first is a rotation failure worth reading, the second is just a miss.
    """
    # Cross-branch handler import authorized by DPLAN-0204 §2.8 (same path as run.py)
    from aipass.ai_mail.apps.handlers.dispatch.wake import wake_branch

    email = target["email"]
    kwargs = {
        "custom_message": prompt,
        "fresh": fresh,
        "auto": True,
        "sender": "@daemon",
        "model": model,
    }

    # Managers only travel the scheduled lane — never the interactive tmux path.
    if target.get("citizen_class") == MANAGER_CLASS:
        kwargs["scheduled"] = True

    try:
        status, ok = wake_branch(email, **kwargs)
    except Exception as e:
        logger.error("[rotation] Exception waking steward %s: %s", email, e)
        return False, str(e), True

    return ok, status.summary, False


def fire_rotation(job: dict, runstate: dict) -> tuple:
    """
    Fire one rotation turn: pick the next citizen, wake it, advance the pointer.

    Returns (ok: bool, detail: str) for the scheduler tick. `ok` reports whether
    the rotation completed a turn — a target that was busy is a recorded miss,
    not a job failure.
    """
    key = job_key(job["owner"], job["id"])
    config = job.get("config", {})
    include_managers = config.get("include_managers", DEFAULT_INCLUDE_MANAGERS)

    roster = _apply_wake_blocklist(build_roster(include_managers=include_managers))
    if not roster:
        _log("ROTATION: roster is empty — nobody to steward")
        return False, "rotation roster is empty"

    state = get_rotation_state(runstate, key)
    target = next_target(roster, state.get("last_target"))
    if target is None:
        return False, "rotation roster is empty"

    email = target["email"]
    is_manager = target.get("citizen_class") == MANAGER_CLASS

    if is_manager and not _scheduled_lane_available():
        detail = "ai_mail scheduled lane not available yet"
        _log(f"SKIP: {email} — manager, {detail}; pointer advances")
        logger.warning("[rotation] Skipped manager steward %s — %s", email, detail)
        record_rotation(runstate, key, email, OUTCOME_SKIPPED, f"{SKIP_MANAGER_LANE}: {detail}")
        return True, f"skipped {email} ({SKIP_MANAGER_LANE})"

    wake = job.get("wake", {})
    model = wake.get("model") or DEFAULT_WAKE_MODEL
    fresh = wake.get("fresh", True)
    prompt = render_prompt(job.get("prompt", ""), email)

    _log(f"STEWARD: {email} — wake_branch(fresh={fresh}, model={model}, manager={is_manager})")

    ok, detail, errored = _wake_steward(target, prompt, model, fresh)

    if ok:
        _log(f"OK: {email} — {detail}")
        logger.info("[rotation] Steward night started for %s", email)
        record_rotation(runstate, key, email, OUTCOME_WOKEN, detail)
        return True, detail

    if errored:
        _log(f"ERROR: {email} — {detail}; pointer advances")
        record_rotation(runstate, key, email, OUTCOME_FAILED, detail)
        return False, f"wake error for {email}: {detail}"

    # Busy target (dispatch lock / interactive occupancy) — named, then passed over.
    _log(f"MISS: {email} — {detail}; pointer advances, next turn comes round")
    logger.warning("[rotation] Steward miss for %s: %s", email, detail)
    record_rotation(runstate, key, email, OUTCOME_MISSED, detail)
    return True, f"missed {email}: {detail}"


def find_rotation_jobs() -> List[dict]:
    """Return every discovered job using the rotation schedule type."""
    return [j for j in discover_jobs() if j.get("schedule", {}).get("type") == ROTATION_TYPE]


def _build_status(job: Optional[dict], runstate: dict) -> dict:
    """Build the rotation status payload for display or --json."""
    include_managers = DEFAULT_INCLUDE_MANAGERS
    key = None
    enabled = False

    if job is not None:
        key = job_key(job["owner"], job["id"])
        include_managers = job.get("config", {}).get("include_managers", DEFAULT_INCLUDE_MANAGERS)
        enabled = job.get("enabled", True)

    roster = _apply_wake_blocklist(build_roster(include_managers=include_managers))
    state = get_rotation_state(runstate, key) if key else {}
    upcoming = next_target(roster, state.get("last_target"))

    return {
        "job_id": job["id"] if job else None,
        "job_owner": job["owner"] if job else None,
        "enabled": enabled,
        "time": job["schedule"].get("time") if job else None,
        "include_managers": include_managers,
        "manager_lane_available": _scheduled_lane_available(),
        "roster_size": len(roster),
        "roster": [{"email": c["email"], "class": c.get("citizen_class", ""), "source": c["source"]} for c in roster],
        "last_target": state.get("last_target"),
        "next_target": upcoming["email"] if upcoming else None,
        "history": state.get("history", []),
    }


def _print_status(status: dict) -> None:
    """Print the rotation status as a Rich view."""
    console.print()
    console.print("[bold cyan]Steward Rotation[/bold cyan]")
    console.print()

    if status["job_id"] is None:
        warning("No rotation job configured")
        console.print("  [dim]Add one with schedule type 'rotation' — drone @daemon rotation --help[/dim]")
        console.print()
    else:
        state = "[green]ON[/green]" if status["enabled"] else "[red]OFF[/red]"
        console.print(f"  Job:      {status['job_owner']}/{status['job_id']}  {state}  daily @ {status['time']}")

    managers = "included" if status["include_managers"] else "excluded"
    lane = "available" if status["manager_lane_available"] else "not built yet"
    console.print(f"  Managers: {managers} [dim](ai_mail scheduled lane: {lane})[/dim]")
    console.print(f"  Next up:  [bold]{status['next_target'] or '-'}[/bold]")
    console.print(f"  Last:     {status['last_target'] or '-'}")
    console.print()

    console.print(f"  [yellow]Roster ({status['roster_size']}):[/yellow]")
    for entry in status["roster"]:
        marker = "[bold cyan]>[/bold cyan]" if entry["email"] == status["next_target"] else " "
        klass = f" [dim]({entry['class']})[/dim]" if entry["class"] else ""
        console.print(f"  {marker} {entry['email']:<16} [dim]{entry['source']}[/dim]{klass}")
    console.print()

    history = status["history"]
    console.print(f"  [yellow]Recent turns ({len(history)}):[/yellow]")
    if not history:
        console.print("  [dim]No steward night has run yet.[/dim]")
    for turn in history:
        console.print(f"    {turn['at'][:19]}  {turn['target']:<16} {turn['outcome']}")
    console.print()


def handle_command(command: str, args: List[str]) -> bool:
    """Handle 'rotation' command from daemon CLI router."""
    if command not in HANDLED_COMMANDS:
        return False

    if args and args[0] in ("--help", "-h"):
        print_help()
        return True

    json_handler.log_operation("rotation_command", {"json": "--json" in args})

    jobs = find_rotation_jobs()
    if len(jobs) > 1:
        logger.warning("[rotation] %d rotation jobs discovered — showing the first", len(jobs))

    status = _build_status(jobs[0] if jobs else None, load_runstate())

    if "--json" in args:
        # soft_wrap + markup off — same machine-output contract as queue --json.
        console.print(json.dumps(status, indent=2), soft_wrap=True, markup=False)
    else:
        _print_status(status)

    return True
