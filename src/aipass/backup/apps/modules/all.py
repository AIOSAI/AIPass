# =================== AIPass ====================
# Name: all.py
# Description: All module — full cycle: snapshot + versioned + drive (shared scan)
# Version: 4.0.0
# Created: 2026-04-17
# Modified: 2026-06-12
# =============================================

"""All Module — runs snapshot then versioned backup with shared scan, then drive sync."""

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
from aipass.cli.apps.modules import console

from aipass.backup.apps.handlers.ignore.patterns import load_spec
from aipass.backup.apps.handlers.ignore.whitelist import load_whitelist
from aipass.backup.apps.handlers.json import json_handler
from aipass.backup.apps.handlers.project.config import load_project_config
from aipass.backup.apps.handlers.project.setup import create_backup_dir
from aipass.backup.apps.handlers.scan.ceiling import check_ceiling
from aipass.backup.apps.handlers.scan.filter import filter_paths
from aipass.backup.apps.handlers.scan.walk import walk_project
from aipass.backup.apps.modules.display import refuse_missing_root, refuse_oversized_run
from aipass.backup.apps.modules.snapshot import run_snapshot
from aipass.backup.apps.modules.versioned import run_versioned

MODULE_NAME = "all"
PRIMARY_COMMAND = "all"


def print_introspection():
    """Display module info and connected handlers."""
    console.print(f"[bold cyan]{MODULE_NAME} Module[/bold cyan]")
    console.print(f"  Primary command: [yellow]{PRIMARY_COMMAND}[/yellow]")
    console.print("  Status: Phase 4 -- shared scan + drive sync")
    console.print("  Orchestration: scan -> snapshot -> versioned -> drive")


def print_help():
    """Display help for this module."""
    print_introspection()


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

    project_root = args[0]
    show_panels = "--quiet" not in args

    # Refuse before the shared scan — snapshot/versioned each guard themselves,
    # but the scan below would otherwise run against a path that isn't there.
    if not Path(project_root).is_dir():
        refuse_missing_root("all", project_root, show_panels)
        return True

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
        return True

    # ONE scan shared between both modes (single-scan rule)
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
        return True

    snap_result = run_snapshot(project_root)
    console.print()

    ver_result = run_versioned(project_root, pre_scanned=filtered)

    # Drive step (fail honestly if no creds)
    drive_result: dict = {}
    try:
        from aipass.backup.apps.modules.drive_sync import run_drive_sync

        console.print()
        drive_result = run_drive_sync(
            project_root,
            show_panels=show_panels,
        )
        if drive_result.get("error"):
            console.print(f"[bold]Drive sync: {drive_result['error']}[/bold]")
    except ImportError:
        logger.warning("Drive sync unavailable: Google API libraries not installed")
        console.print("[bold]Drive sync unavailable: Google API libraries not installed[/bold]")
    except Exception as exc:
        logger.warning(f"Drive sync failed: {exc}")
        console.print(f"[bold]Drive sync failed: {exc}[/bold]")

    json_handler.log_operation(
        "all_complete",
        {
            "project_root": project_root,
            "snapshot_files": snap_result.files_copied,
            "versioned_files": ver_result.files_copied,
            "drive_uploaded": drive_result.get("uploaded", 0),
        },
    )
    logger.info(
        f"[backup] Full backup complete: snapshot={snap_result.files_copied}, "
        f"versioned={ver_result.files_copied}, "
        f"drive_uploaded={drive_result.get('uploaded', 0)}"
    )
    return True


# =============================================

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print_introspection()
        sys.exit(0)
    handle_command(PRIMARY_COMMAND, sys.argv[1:])
