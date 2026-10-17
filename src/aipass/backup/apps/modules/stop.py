# =================== AIPass ====================
# Name: stop.py
# Description: Stop module — ends a project's running lanes by request, and the stopped report every lane prints
# Version: 1.0.0
# Created: 2026-10-16
# Modified: 2026-10-16
# =============================================

"""Stop Module — ``stop <project_root|@name> [lane]`` ends the lanes running for a project.

Reads the project's running files (``.backup/running/<lane>.json``), sends
SIGTERM to the named lane's process, or to every running lane's when none is
named, waits up to STOP_WAIT_SECONDS for it to go and sends SIGKILL after. One
stdout line per stopped lane: ``stopped <lane> (pid N)``, exit 0. Nothing
running: one line, ``nothing running for <project>`` or ``<lane> is not running
for <project>``, exit non-zero. ``<project>`` is the name status --json reports.

A pid is signalled only when its process started no later than the lane and
its command line is backup running that verb for that root
(handlers/state/lane_process.py); anything else is refused on stderr.

The lane side is :func:`report_stopped`, which every lane calls when it
honours the stop flag: the trail row ``<lane>_stopped``, the stopped line as the
run's last stdout line, and the mark the entry point turns into exit 130.
The contract is devpulse's backup_door_contract.md, "stop".
"""

import os
import sys
from pathlib import Path

if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8", errors="replace")

from aipass.prax import logger
from aipass.cli.apps.modules import console, error, mark_command_failed

from aipass.backup.apps.handlers.audit import trail
from aipass.backup.apps.handlers.json.json_handler import InvalidDocument
from aipass.backup.apps.handlers.path.caller import resolve_caller_path
from aipass.backup.apps.handlers.project.config import load_project_config
from aipass.backup.apps.handlers.state import lane_process
from aipass.backup.apps.handlers.state.progress import read_running
from aipass.backup.apps.handlers.state.stop_flag import (
    STOPPED_EXIT,
    mark_stopped,
    reset_stop_state,
    run_was_stopped,
    stopped_line,
)

MODULE_NAME = "stop"
PRIMARY_COMMAND = "stop"
USAGE = "stop <project_root|@name> [lane]"

#: How long a lane is given to go after SIGTERM before SIGKILL.
STOP_WAIT_SECONDS = 30

#: The words a lane may be named by: the three that do work, and all, which
#: names whatever sub-lane an all run is in.
LANE_WORDS = ("snapshot", "versioned", "drive_sync", "all")

__all__ = ["STOPPED_EXIT", "reset_stop_state", "run_was_stopped", "report_stopped", "stop_lanes", "handle_command"]


def print_introspection():
    """Display module info and connected handlers."""
    console.print(f"[bold cyan]{MODULE_NAME} Module[/bold cyan]")
    console.print(f"  Primary command: [yellow]{PRIMARY_COMMAND}[/yellow]")
    console.print("  Status: live -- SIGTERM, wait, SIGKILL after; the lane exits 130")
    console.print("  Handlers: state/progress, state/lane_process, state/stop_flag")


def print_help():
    """Display help for this module."""
    print_introspection()
    console.print()
    console.print(f"Usage: {USAGE}", markup=False)
    console.print(f"  lane: one of {', '.join(LANE_WORDS)}; none stops every running lane of the project.")
    console.print(f"  SIGTERM, then up to {STOP_WAIT_SECONDS}s for the lane to go, then SIGKILL.")
    console.print("  The stopped lane saves what it must, prints its counts and exits 130.")


def report_stopped(
    lane: str,
    verb: str,
    project_root: str,
    done: int,
    total: int,
    failed: int,
    bytes_done: int,
) -> None:
    """A lane honoured the stop flag: record it, say it last, and mark the run stopped.

    Args:
        lane: The lane that stopped.
        verb: What was invoked (the lane, or all).
        project_root: The project.
        done: Files gone through before the stop.
        total: Files the run had planned.
        failed: Of done, the files that failed.
        bytes_done: Bytes copied or uploaded before the stop.
    """
    trail.log_operation(
        f"{lane}_stopped",
        {
            "project_root": project_root,
            "verb": verb,
            "done": done,
            "total": total,
            "failed": failed,
            "bytes_done": bytes_done,
        },
    )
    logger.info(f"[backup] {lane} stopped by request: {done} of {total} files ({project_root})")
    mark_stopped()
    console.print(stopped_line(done, total, bytes_done), markup=False, highlight=False)


def _project_name(project_root: str) -> str:
    """The project's name as status --json reports it: the config's project_name, else the directory name."""
    try:
        config = load_project_config(project_root)
    except InvalidDocument as exc:
        logger.info(f"[backup] stop: config unreadable, naming the project by its directory: {exc}")
        config = {}
    return config.get("project_name") or Path(project_root).name


def _end_entry(entry: dict, project_root: str, wait_seconds: float) -> bool:
    """Signal one running lane through both guards. True when it was stopped."""
    pid = entry.get("pid")
    proc = lane_process.live_lane(entry)
    if proc is None:
        # Went between the read and now, on its own: say so, never claim the stop.
        console.print(f"{entry.get('lane')} (pid {pid}) had already ended", markup=False, highlight=False)
        return True
    refusal = lane_process.lane_for_root(proc, entry, project_root)
    if refusal is not None:
        error(f"pid {pid} not signalled: {refusal}")
        trail.log_operation("stop_refused", {"project_root": project_root, "pid": pid, "reason": refusal})
        return False
    outcome = lane_process.end_process(proc, wait_seconds)
    trail.log_operation(
        "stop_lane",
        {"project_root": project_root, "lane": entry.get("lane"), "pid": pid, "outcome": outcome},
    )
    logger.info(f"[backup] stop: {entry.get('lane')} (pid {pid}) {outcome}")
    console.print(f"stopped {entry.get('lane')} (pid {pid})", markup=False, highlight=False)
    return True


def stop_lanes(project_root: str, lane: str | None = None, wait_seconds: float = STOP_WAIT_SECONDS) -> bool:
    """Stop a project's running lanes, or the one named.

    Args:
        project_root: Absolute project root.
        lane: One of LANE_WORDS, or None for every running lane.
        wait_seconds: How long SIGTERM is given before SIGKILL.

    Returns:
        True when every chosen lane was stopped. Nothing running, or a pid
        refused by the guard, is False and marks the command failed.
    """
    project = _project_name(project_root)
    running = read_running(project_root)
    if lane is None:
        chosen = running
    elif lane == "all":
        chosen = [entry for entry in running if entry.get("verb") == "all"]
    else:
        chosen = [entry for entry in running if entry.get("lane") == lane]

    if not chosen:
        line = f"nothing running for {project}" if lane is None else f"{lane} is not running for {project}"
        console.print(line, markup=False, highlight=False)
        trail.log_operation("stop_nothing_running", {"project_root": project_root, "lane": lane})
        mark_command_failed()
        return False

    all_stopped = True
    ended: set = set()
    for entry in chosen:
        if entry.get("pid") in ended:
            continue
        ended.add(entry.get("pid"))
        all_stopped = _end_entry(entry, project_root, wait_seconds) and all_stopped
    return all_stopped


def handle_command(command: str, args: list) -> bool:
    """Handle the stop command. Returns True if handled."""
    if command != PRIMARY_COMMAND:
        return False

    if not args:
        print_introspection()
        return True

    # Screen the WHOLE sequence: "stop <root> --help" must explain, never signal.
    if args[0] == "help" or any(arg in ("--help", "-h") for arg in args):
        print_help()
        return True

    if len(args) > 2 or any(arg.startswith("--") for arg in args):
        error(f"stop takes a project and at most one lane: got {' '.join(args)}", suggestion=USAGE)
        return True
    lane = args[1] if len(args) == 2 else None
    if lane is not None and lane not in LANE_WORDS:
        error(f"Unknown lane: {lane} (one of {', '.join(LANE_WORDS)})", suggestion=USAGE)
        return True

    project_root = str(resolve_caller_path(args[0]))
    if not Path(project_root).is_dir():
        error(f"Project path is not a directory: {project_root}")
        return True

    stop_lanes(project_root, lane)
    return True


# =============================================

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print_introspection()
        sys.exit(0)
    handle_command(PRIMARY_COMMAND, sys.argv[1:])
