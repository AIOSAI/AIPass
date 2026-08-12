# =================== AIPass ====================
# Name: queue.py
# Description: Unified job queue view (drone @daemon queue)
# Version: 1.0.0
# Created: 2026-06-25
# Modified: 2026-06-25
# =============================================

"""
Unified queue view — aggregates .daemon/schedule.json jobs joined to runstate.

Human-readable Rich table (default) or --json matching the frozen contract
consumed by @skills' scheduler bot.
"""

import json
from datetime import datetime, timezone
from typing import List, Optional

from aipass.prax import logger
from aipass.cli.apps.modules import console
from aipass.daemon.apps.handlers.json import json_handler
from aipass.daemon.apps.handlers.schedule.discovery import discover_jobs
from aipass.daemon.apps.handlers.schedule.runstate import (
    load_runstate,
    get_job_state,
)

HANDLED_COMMANDS = {"queue"}


def print_introspection():
    """Display module introspection info."""
    console.print()
    console.print("[bold cyan]queue Module[/bold cyan]")
    console.print()
    console.print("[dim]Unified job queue view — .daemon/ jobs joined to runstate[/dim]")
    console.print()
    console.print("[yellow]Reads:[/yellow]")
    console.print("  [cyan]*[/cyan] src/aipass/*/.daemon/*.json [dim](per-branch schedule files)[/dim]")
    console.print("  [cyan]*[/cyan] daemon_json/daemon_runstate.json [dim](last_run/status state)[/dim]")
    console.print()


def print_help():
    """Display usage information."""
    console.print("\n[bold cyan]queue — Unified Job Queue View[/bold cyan]")
    console.print("\n[yellow]USAGE:[/yellow]")
    console.print("  drone @daemon queue           Show job queue (Rich table)")
    console.print("  drone @daemon queue --json     Machine-readable JSON (frozen schema)")
    console.print("  drone @daemon queue --help     Show this help message")
    console.print()


def _schedule_human(job: dict) -> str:
    """Build human-readable schedule string."""
    sched = job.get("schedule", {})
    sched_type = sched.get("type", "")
    if sched_type == "once":
        return sched.get("due_date", "?")
    if sched_type == "daily":
        return f"daily @ {sched.get('time', '??:??')}"
    if sched_type == "rotation":
        return f"rotation @ {sched.get('time', '??:??')}"
    if sched_type == "hourly":
        m = sched.get("time", "0")
        return f"hourly @ :{int(m):02d}"
    if sched_type == "interval":
        mins = sched.get("interval_minutes", 0)
        if mins >= 60:
            return f"every {mins // 60}h"
        return f"every {mins}m"
    return sched_type


def _compute_next_run(job: dict, state: dict) -> Optional[str]:
    """Determine next_run from runstate or schedule."""
    if state.get("completed"):
        return None
    next_run = state.get("next_run")
    if next_run:
        return next_run
    sched = job.get("schedule", {})
    if sched.get("type") == "once":
        due = sched.get("due_date")
        if due and "T" not in due:
            return f"{due}T09:00:00"
        return due
    return None


def _build_queue(jobs: list, runstate: dict) -> list:
    """Build unified queue entries from discovered jobs + runstate."""
    entries = []
    for job in jobs:
        state = get_job_state(runstate, job["owner"], job["id"])
        if state.get("completed"):
            continue

        owner = job["owner"]
        if owner.startswith("@"):
            pass
        elif "@" in owner:
            owner = f"@{owner.split('@')[0]}"

        prompt = job.get("prompt", "")
        flat = " ".join(prompt.split())  # collapse newlines/whitespace → single-line preview
        preview = flat[:80] + "..." if len(flat) > 80 else flat

        entries.append(
            {
                "owner": owner,
                "id": job["id"],
                "enabled": job.get("enabled", True),
                "type": job["schedule"].get("type", ""),
                "schedule_human": _schedule_human(job),
                "next_run": _compute_next_run(job, state),
                "last_run": state.get("last_run"),
                "last_status": state.get("last_status"),
                "last_error": state.get("last_error"),
                "prompt_preview": preview,
                "wake": job.get("wake", {}),
            }
        )
    return entries


def _print_rich_table(entries: list) -> None:
    """Print queue as a Rich table."""
    console.print()
    console.print("[bold cyan]Job Queue[/bold cyan]")
    console.print()

    if not entries:
        console.print("[dim]No jobs in queue.[/dim]")
        console.print()
        return

    console.print(
        f"  {'OWNER':<14} {'ID':<20} {'ON':<4} {'TYPE':<9} {'SCHEDULE':<18} {'LAST STATUS':<12} {'NEXT RUN':<20}"
    )
    console.print("  " + "-" * 97)

    for e in entries:
        enabled = "[green]ON[/green] " if e["enabled"] else "[red]OFF[/red]"
        last_status = e.get("last_status") or "-"
        next_run = (e.get("next_run") or "-")[:19]
        console.print(
            f"  {e['owner']:<14} {e['id']:<20} {enabled:<4} {e['type']:<9} "
            f"{e['schedule_human']:<18} {last_status:<12} {next_run:<20}"
        )

    console.print()
    enabled_count = sum(1 for e in entries if e["enabled"])
    console.print(f"  [dim]Total: {len(entries)} job(s) ({enabled_count} enabled)[/dim]")
    console.print()


def _build_json_output(entries: list) -> dict:
    """Build frozen-schema JSON output for @skills consumption."""
    return {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "count": len(entries),
        "jobs": entries,
    }


def handle_command(command: str, args: List[str]) -> bool:
    """Handle 'queue' command from daemon CLI router."""
    if command not in HANDLED_COMMANDS:
        return False

    if not args:
        json_handler.log_operation("queue_command", {"json": False})
        jobs = discover_jobs()
        runstate = load_runstate()
        entries = _build_queue(jobs, runstate)
        _print_rich_table(entries)
        logger.info("[queue] Queue displayed (%d jobs)", len(entries))
        return True

    if args[0] in ("--help", "-h"):
        print_help()
        return True

    json_handler.log_operation("queue_command", {"json": "--json" in args})

    jobs = discover_jobs()
    runstate = load_runstate()
    entries = _build_queue(jobs, runstate)

    if "--json" in args:
        output = _build_json_output(entries)
        # soft_wrap=True + markup=False — default console.print forces width-80
        # wrapping on non-TTY and parses [] markup, injecting newlines mid-string
        # that corrupt machine output. These flags emit clean, parseable JSON.
        console.print(json.dumps(output, indent=2), soft_wrap=True, markup=False)
    else:
        _print_rich_table(entries)

    logger.info("[queue] Queue displayed (%d jobs)", len(entries))
    return True
