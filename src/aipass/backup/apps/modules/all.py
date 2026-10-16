# =================== AIPass ====================
# Name: all.py
# Description: All module — full cycle: snapshot + versioned + drive (shared scan)
# Version: 4.2.0
# Created: 2026-04-17
# Modified: 2026-10-16
# =============================================

"""All Module — runs snapshot then versioned backup with shared scan, then drive sync when the project has it on.

``all --registered`` runs the cycle for every project in the registry, in
registry order, and ends with one summary line per project. One project's
failure never stops the next; any failure makes the exit non-zero. This is the
line the nightly daemon job runs.

A stop (DPLAN-0412) ends the sub-lane in flight and starts no other: each
sub-lane writes its own running file with verb ``all``, and the entry point
exits 130. ``all --registered`` starts no further project after a stop.
"""

import os
import sys
import time
from pathlib import Path

if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8", errors="replace")

from aipass.prax import logger
from aipass.cli.apps.modules import console, error

from aipass.backup.apps.handlers.ignore.patterns import load_spec
from aipass.backup.apps.handlers.ignore.whitelist import load_whitelist
from aipass.backup.apps.handlers.audit import trail
from aipass.backup.apps.handlers.project.config import load_project_config
from aipass.backup.apps.handlers.project.registry import list_projects
from aipass.backup.apps.handlers.project.setup import create_backup_dir
from aipass.backup.apps.handlers.scan.ceiling import check_ceiling
from aipass.backup.apps.handlers.scan.filter import filter_paths
from aipass.backup.apps.handlers.scan.walk import walk_project
from aipass.backup.apps.handlers.state.progress import LaneProgress
from aipass.backup.apps.handlers.state.stop_flag import catch_sigterm, run_was_stopped, stop_requested
from aipass.backup.apps.modules.display import refuse_missing_root, refuse_oversized_run
from aipass.backup.apps.modules.snapshot import run_snapshot
from aipass.backup.apps.modules.stop import report_stopped
from aipass.backup.apps.modules.versioned import run_versioned

MODULE_NAME = "all"
PRIMARY_COMMAND = "all"
REGISTERED_FLAG = "--registered"


def print_introspection():
    """Display module info and connected handlers."""
    console.print(f"[bold cyan]{MODULE_NAME} Module[/bold cyan]")
    console.print(f"  Primary command: [yellow]{PRIMARY_COMMAND}[/yellow]")
    console.print("  Status: Phase 4 -- shared scan + drive sync")
    console.print("  Orchestration: scan -> snapshot -> versioned -> drive (when drive_sync is on)")
    console.print("  Usage: all <project_path|@name> [--quiet] | all --registered [--quiet]")


def print_help():
    """Display help for this module."""
    print_introspection()


def run_all(project_root: str, show_panels: bool = True) -> dict:
    """Run the full cycle for one project.

    Args:
        project_root: Absolute path to the project.
        show_panels: False under --quiet; the Drive step's panels follow it.

    Returns:
        Dict with ok, snapshot_files, versioned_files, drive (uploaded,
        skipped or failed), seconds, and stopped (True when a stop ended the
        cycle; the sub-lanes after it never started).
    """
    with catch_sigterm():
        return _all_run(project_root, show_panels)


def _stopped_summary(summary: dict, start: float) -> dict:
    """The cycle's summary after a stop: not ok, stopped, timed."""
    summary["stopped"] = True
    summary["seconds"] = time.monotonic() - start
    return summary


def _all_run(project_root: str, show_panels: bool) -> dict:
    """The cycle proper, inside the stop handler."""
    start = time.monotonic()
    summary: dict = {
        "ok": False,
        "snapshot_files": 0,
        "versioned_files": 0,
        "drive": "skipped",
        "seconds": 0.0,
        "stopped": False,
    }

    # Refuse before the shared scan — snapshot/versioned each guard themselves,
    # but the scan below would otherwise run against a path that isn't there.
    if not Path(project_root).is_dir():
        refuse_missing_root("all", project_root, show_panels)
        summary["seconds"] = time.monotonic() - start
        return summary

    logger.info(f"[backup] Running full backup cycle for {project_root}")

    # Scaffold BEFORE the shared scan. create_backup_dir is what writes the
    # seed .backupignore, and it used to run first inside run_snapshot — after
    # this scan had already been taken. On a project's first run that meant
    # load_spec() read a file that did not exist yet, returned an empty spec,
    # and handed versioned every path the seed was about to exclude. Snapshot
    # rescanned and looked correct; versioned took the pre-seed list and
    # copied the artifacts anyway. Idempotent: nothing is overwritten.
    if create_backup_dir(project_root) is None:
        refuse_missing_root("all", project_root, show_panels)
        summary["seconds"] = time.monotonic() - start
        return summary

    # ONE scan shared between both modes (single-scan rule). The scan is the
    # snapshot lane's first work, so it is announced as that lane, verb all.
    with LaneProgress(project_root, "snapshot", PRIMARY_COMMAND):
        config = load_project_config(project_root)
        spec = load_spec(project_root)
        whitelist_entries = load_whitelist(project_root)
        max_size = config.get("max_file_size_mb", 100)
        all_files = list(walk_project(project_root))
        filtered = filter_paths(all_files, spec, whitelist_entries, max_size)

    # Refuse the whole cycle here, not just inside the sub-modules. A refusal
    # from run_snapshot alone does not stop this function: it would fall
    # straight through to run_versioned and write the store it just refused
    # to mirror.
    breach = check_ceiling(filtered, config)
    if breach is not None:
        refuse_oversized_run("all", project_root, breach, show_panels)
        summary["seconds"] = time.monotonic() - start
        return summary

    # A stop during the scan: snapshot has copied nothing, and nothing starts.
    if stop_requested():
        report_stopped("snapshot", PRIMARY_COMMAND, project_root, done=0, total=len(filtered), failed=0, bytes_done=0)
        return _stopped_summary(summary, start)

    snap_result = run_snapshot(project_root, verb=PRIMARY_COMMAND)
    summary["snapshot_files"] = snap_result.files_copied
    if run_was_stopped():
        return _stopped_summary(summary, start)
    console.print()

    ver_result = run_versioned(project_root, pre_scanned=filtered, verb=PRIMARY_COMMAND)
    summary["versioned_files"] = ver_result.files_copied
    if run_was_stopped():
        return _stopped_summary(summary, start)

    # Drive step, only when the project's drive_sync setting is on (DPLAN-0411).
    # A real True, not a truthy value: a hand-edited "false" string must not
    # send the store off the machine. Fail honestly if no creds.
    drive_result: dict = {}
    drive_on = config.get("drive_sync") is True
    if not drive_on:
        console.print("Drive sync off for this project")
    else:
        summary["drive"] = "uploaded"
        try:
            from aipass.backup.apps.modules.drive_sync import run_drive_sync

            console.print()
            drive_result = run_drive_sync(
                project_root,
                show_panels=show_panels,
                verb=PRIMARY_COMMAND,
            )
            if run_was_stopped():
                summary["drive"] = "stopped"
                return _stopped_summary(summary, start)
            # A headroom refusal has already printed its sentence as the Drive
            # step's last line (error_shown); repeating it would push it off
            # the end of the run, where the contract puts it.
            if drive_result.get("error") and not drive_result.get("error_shown"):
                console.print(f"[bold]Drive sync: {drive_result['error']}[/bold]")
            if drive_result.get("error") or drive_result.get("failed"):
                summary["drive"] = "failed"
        except ImportError:
            summary["drive"] = "failed"
            logger.warning("Drive sync unavailable: Google API libraries not installed")
            console.print("[bold]Drive sync unavailable: Google API libraries not installed[/bold]")
        except Exception as exc:
            summary["drive"] = "failed"
            logger.warning(f"Drive sync failed: {exc}")
            console.print(f"[bold]Drive sync failed: {exc}[/bold]")

    trail.log_operation(
        "all_complete",
        {
            "project_root": project_root,
            "snapshot_files": snap_result.files_copied,
            "versioned_files": ver_result.files_copied,
            "drive_uploaded": drive_result.get("uploaded", 0),
            "drive_skipped": not drive_on,
        },
    )
    logger.info(
        f"[backup] Full backup complete: snapshot={snap_result.files_copied}, "
        f"versioned={ver_result.files_copied}, "
        f"drive_uploaded={drive_result.get('uploaded', 0)}, drive={summary['drive']}"
    )
    summary["ok"] = snap_result.success and ver_result.success and summary["drive"] != "failed"
    summary["seconds"] = time.monotonic() - start
    return summary


def run_registered(show_panels: bool = True) -> bool:
    """Run the full cycle for every registered project, in registry order.

    A project that refuses or raises is recorded and the next one runs. The
    summary prints after the last project, one line each.

    Args:
        show_panels: False under --quiet.

    Returns:
        True when every project succeeded. On any failure error() is called,
        which is what turns the exit code non-zero.
    """
    projects = list_projects()
    if not projects:
        error("No projects registered — nothing for all --registered to back up")
        return False

    with catch_sigterm():
        return _registered_run(projects, show_panels)


def _registered_run(projects: dict, show_panels: bool) -> bool:
    """Every registered project in turn, inside the stop handler; a stop starts no further project."""
    rows: list[tuple[str, dict]] = []
    for name, entry in projects.items():
        root = entry.get("path", "") if isinstance(entry, dict) else ""
        console.print(f"all --registered: {name} ({root})", markup=False)
        start = time.monotonic()
        try:
            summary = run_all(root, show_panels=show_panels)
        except Exception as exc:
            logger.error(f"[backup] all --registered: {name} failed: {exc}")
            error(f"all --registered: {name} failed -- {exc}")
            summary = {"ok": False, "snapshot_files": 0, "versioned_files": 0, "drive": "skipped"}
            summary["seconds"] = time.monotonic() - start
        rows.append((name, summary))
        if summary.get("stopped"):
            # The stopped line the sub-lane printed stays the run's last line: no summary after it.
            trail.log_operation("all_registered_stopped", {"projects": len(rows), "stopped_at": name})
            logger.info(f"[backup] all --registered: stopped by request in {name}")
            return False

    console.print()
    console.print("all --registered summary:")
    for name, summary in rows:
        state = "ok" if summary["ok"] else "FAILED"
        console.print(
            f"{name} {state} snapshot={summary['snapshot_files']} versioned={summary['versioned_files']} "
            f"drive={summary['drive']} {summary['seconds']:.1f}s",
            markup=False,
        )

    failed = [name for name, summary in rows if not summary["ok"]]
    trail.log_operation(
        "all_registered_complete",
        {"projects": len(rows), "failed": failed},
    )
    logger.info(f"[backup] all --registered: {len(rows) - len(failed)} of {len(rows)} projects ok")
    if failed:
        error(f"all --registered: {len(failed)} of {len(rows)} projects failed: {', '.join(failed)}")
        return False
    return True


def handle_command(command: str, args: list) -> bool:
    """Handle the all command. Returns True if handled."""
    if command != PRIMARY_COMMAND:
        return False

    if not args:
        print_introspection()
        return True

    # Screen the WHOLE sequence, not just args[0]. This module has a
    # standalone __main__ entry that never reaches the router's help
    # normalisation, so a trailing flag used to fall through and run the
    # verb for real. Bare "help" stays first-position-only: later
    # positions are user values (filenames), not flags.
    if args[0] == "help" or any(arg in ("--help", "-h") for arg in args):
        print_introspection()
        return True

    show_panels = "--quiet" not in args

    if REGISTERED_FLAG in args:
        named = [arg for arg in args if not arg.startswith("--")]
        if named:
            error(f"all --registered runs every registered project; drop the project argument: {named[0]}")
            return True
        run_registered(show_panels=show_panels)
        return True

    run_all(args[0], show_panels=show_panels)
    return True


# =============================================

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print_introspection()
        sys.exit(0)
    handle_command(PRIMARY_COMMAND, sys.argv[1:])
