# =================== AIPass ====================
# Name: schedule.py
# Description: Schedule module — read and set a registered project's scheduled backup
# Version: 1.0.0
# Created: 2026-11-15
# Modified: 2026-11-15
# =============================================

"""Schedule Module — a registered project's scheduled backup: read it, set its time, turn it on or off.

Reference: docs/schedule.md
"""

import datetime
import json
import sys
from pathlib import Path

import aipass.drone as drone
from aipass.prax import logger
from aipass.cli.apps.modules import console, error

from aipass.backup.apps.handlers.audit import trail
from aipass.backup.apps.handlers.json.json_handler import InvalidDocument
from aipass.backup.apps.handlers.project.config import load_project_config
from aipass.backup.apps.handlers.project.registry import list_projects
from aipass.backup.apps.handlers.schedule.jobs import ScheduleError, find_job, job_id, parse_job, write_job
from aipass.backup.apps.modules.register import resolve_project

MODULE_NAME = "schedule"
PRIMARY_COMMAND = "schedule"
USAGE = "schedule <project_path|@name> [--json] | schedule <project_path|@name> on|off|daily HH:MM"
#: Frequencies the owner designed that @daemon's schedule cannot express yet: refused, never approximated.
HELD = ("weekly", "monthly")
DAEMON_TIMEOUT_SECONDS = 60


def print_introspection():
    """Display module info and connected handlers."""
    console.print(f"[bold cyan]{MODULE_NAME} Module[/bold cyan]")
    console.print(f"  Primary command: [yellow]{PRIMARY_COMMAND}[/yellow]")
    console.print("  Handlers: schedule/jobs, project/config, project/registry")


def print_help():
    """Display help for this module."""
    print_introspection()
    console.print()
    console.print(f"Usage: {USAGE}", markup=False)
    console.print("  A scheduled run is the all lane: snapshot, then drive_sync when the project has it on.")
    console.print("  --json      one JSON object on stdout, nothing else")
    console.print("  on | off    run the schedule, or keep it and never run it")
    console.print("  daily HH:MM run every day at that 24-hour time; a new schedule starts off")
    console.print("  weekly and monthly are refused: @daemon has no type for them yet.")


def _registered(target: str) -> tuple[str, str] | None:
    """(name, root) of a registered project; None after an error naming why."""
    root = resolve_project(target)
    if root is None:
        error(f"Cannot resolve project: {target}")
        return None
    for name, entry in list_projects().items():
        if Path(entry.get("path", "")).resolve() == Path(root).resolve():
            return name, root
    error(f"{root} is not registered: a scheduled run is 'all @name'", suggestion="register <path> --name <name>")
    return None


def _daemon_row(jid: str) -> dict:
    """@daemon's queue row for the job: last_run, last_status, last_error, next_run. ScheduleError when unread."""
    try:
        result = drone.route_command("@daemon", "queue", ["--json"], timeout=DAEMON_TIMEOUT_SECONDS)
    except drone.RoutingError as exc:
        raise ScheduleError(f"@daemon queue unreachable: {exc}") from exc
    if result.exit_code != 0:
        raise ScheduleError(f"@daemon queue --json exited {result.exit_code}")
    try:
        queue = json.loads(result.stdout)
    except ValueError as exc:
        raise ScheduleError(f"@daemon queue --json is not JSON: {exc}") from exc
    refused = [str(r) for r in queue.get("refused", []) if jid in str(r)]
    if refused:
        raise ScheduleError(f"@daemon refuses job {jid}: {refused[0]}")
    return next((r for r in queue.get("jobs", []) if r.get("owner") == "@backup" and r.get("id") == jid), {})


def next_daily(time: str, now: datetime.datetime | None = None) -> str:
    """The next local HH:MM after ``now``, in @daemon's form; @daemon has no next_run before a first run."""
    now = now or datetime.datetime.now()
    hour, minute = map(int, time.split(":"))
    due = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if due <= now:
        due += datetime.timedelta(days=1)
    return due.isoformat()


def build_schedule(name: str, root: str) -> dict:
    """The schedule object --json prints; ScheduleError or InvalidDocument when a source is unreadable."""
    job = find_job(name)
    parsed = parse_job(job) if job else {"on": False, "frequency": None, "time": None, "weekday": None, "day": None}
    row = _daemon_row(job_id(name)) if job else {}
    drive_on = load_project_config(root).get("drive_sync") is True
    return {
        "project": name,
        "root": root,
        "job_id": job_id(name),
        "scheduled": job is not None,
        **parsed,
        "steps": ["snapshot", "drive_sync"] if drive_on else ["snapshot"],
        "last_run": row.get("last_run"),
        "last_status": row.get("last_status"),
        "last_error": row.get("last_error"),
        "next_run": next_daily(parsed["time"]) if parsed["on"] else None,
    }


def _show(view: dict, as_json: bool) -> None:
    """Print the schedule: one JSON line, or a few plain lines."""
    if as_json:
        console.print(json.dumps(view), markup=False, highlight=False, soft_wrap=True)
        return
    when = f"{view['frequency']} {view['time']}" if view["scheduled"] else "no schedule"
    state = "on" if view["on"] else "off"
    console.print(f"{view['project']}: {when}, {state}", markup=False)
    console.print(f"  runs: {' -> '.join(view['steps'])}", markup=False)
    console.print(f"  last: {view['last_run'] or 'never'} {view['last_status'] or ''}".rstrip(), markup=False)
    console.print(f"  next: {view['next_run'] or 'none'}", markup=False)


def _set(name: str, words: list[str]) -> None:
    """Apply one set form: on, off, or daily HH:MM. Errors name the word refused."""
    if words in (["on"], ["off"]):
        job = write_job(name, on=words[0] == "on")
    elif len(words) == 2 and words[0] == "daily":
        job = write_job(name, time=words[1])
    elif words[0] in HELD:
        error(f"{words[0]} is not schedulable yet: @daemon has no {words[0]} type; daily is", suggestion=USAGE)
        return
    else:
        error(f"schedule does not take: {' '.join(words)}", suggestion=USAGE)
        return
    logger.info(f"[backup] schedule {name}: {' '.join(words)}")
    state = "on" if job["enabled"] else "off"
    console.print(f"{name}: daily {job['schedule']['time']}, {state}", markup=False)


def run_schedule(name: str, root: str, words: list[str]) -> None:
    """Read the schedule (no words, or --json) or set it; an unreadable source is an error on stderr."""
    try:
        if words and words != ["--json"]:
            _set(name, words)
            return
        view = build_schedule(name, root)
    except (ScheduleError, InvalidDocument, OSError) as exc:
        logger.error(f"[backup] schedule failed for {name}: {exc}")
        error(f"Schedule: {exc}")
        return
    _show(view, as_json=words == ["--json"])
    trail.log_operation("schedule_read", {"project": name})


def handle_command(command: str, args: list) -> bool:
    """Handle the schedule command. Returns True if handled."""
    if command != PRIMARY_COMMAND:
        return False

    if not args:
        print_introspection()
        return True

    if args[0] == "help" or any(arg in ("--help", "-h") for arg in args):
        print_help()
        return True

    if args[0].startswith("-"):
        error(f"schedule does not take: {args[0]}", suggestion=USAGE)
        return True

    project = _registered(args[0])
    if project is None:
        return True
    run_schedule(*project, args[1:])
    return True


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print_introspection()
        sys.exit(0)
    handle_command(PRIMARY_COMMAND, sys.argv[1:])
