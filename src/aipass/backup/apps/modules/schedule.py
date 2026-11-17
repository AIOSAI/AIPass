# =================== AIPass ====================
# Name: schedule.py
# Description: Schedule module — read and set a registered project's scheduled backup
# Version: 1.1.0
# Created: 2026-11-15
# Modified: 2026-11-15
# =============================================

"""Schedule Module — a registered project's scheduled backup: read it, set its time, turn it on or off.

Reference: docs/schedule.md
"""

import calendar
import datetime
import json
import sys
from pathlib import Path

import aipass.drone as drone
from aipass.prax import logger
from aipass.cli import console, error

from aipass.backup.apps.handlers.audit import trail
from aipass.backup.apps.handlers.json.json_handler import InvalidDocument
from aipass.backup.apps.handlers.project.config import load_project_config
from aipass.backup.apps.handlers.project.registry import list_projects
from aipass.backup.apps.handlers.schedule.jobs import (
    WEEKDAYS,
    ScheduleError,
    find_job,
    job_id,
    parse_job,
    schedule_from,
    write_job,
)
from aipass.backup.apps.modules.register import resolve_project

MODULE_NAME = "schedule"
PRIMARY_COMMAND = "schedule"
USAGE = (
    "schedule <project_path|@name> [--json] | schedule <project_path|@name> "
    "on|off|daily HH:MM|weekly WEEKDAY HH:MM|monthly DAY HH:MM"
)
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
    console.print("  daily HH:MM               every day at that 24-hour time")
    console.print("  weekly WEEKDAY HH:MM      WEEKDAY is monday..sunday")
    console.print("  monthly DAY HH:MM         DAY is 1-31; past a month's end it runs on the last day")
    console.print("  A new schedule starts off; changing when it runs keeps on or off.")


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


def _runs_on(parsed: dict, date: datetime.date) -> bool:
    """Whether the schedule runs on ``date``; a monthly day past the month's end runs on its last day."""
    if parsed["frequency"] == "weekly":
        return WEEKDAYS[date.weekday()] == parsed["weekday"]
    if parsed["frequency"] == "monthly":
        return date.day == min(parsed["day"], calendar.monthrange(date.year, date.month)[1])
    return True


def next_run(parsed: dict, now: datetime.datetime | None = None) -> str:
    """The next local run after ``now``, in @daemon's form; @daemon has no next_run before a first run."""
    now = now or datetime.datetime.now()
    hour, minute = map(int, parsed["time"].split(":"))
    # Every schedule runs at least once in any 32 days: monthly days past a month's end clamp to it.
    for offset in range(33):
        due = (now + datetime.timedelta(days=offset)).replace(hour=hour, minute=minute, second=0, microsecond=0)
        if due > now and _runs_on(parsed, due.date()):
            return due.isoformat()
    raise ScheduleError(f"No run within 32 days for {parsed}")


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
        "next_run": next_run(parsed) if parsed["on"] else None,
    }


def _show(view: dict, as_json: bool) -> None:
    """Print the schedule: one JSON line, or a few plain lines."""
    if as_json:
        console.print(json.dumps(view), markup=False, highlight=False, soft_wrap=True)
        return
    when = describe(view) if view["scheduled"] else "no schedule"
    state = "on" if view["on"] else "off"
    console.print(f"{view['project']}: {when}, {state}", markup=False)
    console.print(f"  runs: {' -> '.join(view['steps'])}", markup=False)
    console.print(f"  last: {view['last_run'] or 'never'} {view['last_status'] or ''}".rstrip(), markup=False)
    console.print(f"  next: {view['next_run'] or 'none'}", markup=False)


def describe(parsed: dict) -> str:
    """'daily 05:00', 'weekly monday 05:00' or 'monthly day 31 05:00'."""
    weekday = f" {parsed['weekday']}" if parsed["weekday"] else ""
    day = f" day {parsed['day']}" if parsed["day"] else ""
    return f"{parsed['frequency']}{weekday}{day} {parsed['time']}"


def _set(name: str, words: list[str]) -> None:
    """Apply one set form: on, off, or a schedule. ScheduleError names what was refused."""
    if words in (["on"], ["off"]):
        job = write_job(name, on=words[0] == "on")
    else:
        job = write_job(name, schedule=schedule_from(words))
    logger.info(f"[backup] schedule {name}: {' '.join(words)}")
    parsed = parse_job(job)
    console.print(f"{name}: {describe(parsed)}, {'on' if parsed['on'] else 'off'}", markup=False)


def run_schedule(name: str, root: str, words: list[str]) -> None:
    """Read the schedule (no words, or --json) or set it; an unreadable source is an error on stderr."""
    try:
        if words and words != ["--json"]:
            _set(name, words)
            return
        view = build_schedule(name, root)
    except (ScheduleError, InvalidDocument, OSError) as exc:
        logger.error(f"[backup] schedule failed for {name}: {exc}")
        error(f"Schedule: {exc}", suggestion=USAGE)
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
