# =================== AIPass ====================
# Name: versioned.py
# Description: Versioned module — per-file baseline + diff backup
# Version: 3.1.2
# Created: 2026-04-17
# Modified: 2026-10-24
# =============================================

"""Versioned Module — per-file baseline + diff backup of a project directory."""

import os
import sys
import time

if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8", errors="replace")

from aipass.prax import logger
from aipass.cli.apps.modules import console

from aipass.backup.apps.handlers.copy.versioned import copy_versioned
from aipass.backup.apps.handlers.ignore.patterns import load_spec
from aipass.backup.apps.handlers.ignore.whitelist import load_whitelist
from aipass.backup.apps.handlers.audit import trail
from aipass.backup.apps.handlers.path.caller import resolve_caller_path
from aipass.backup.apps.handlers.path.builder import build_versioned_store
from aipass.backup.apps.handlers.project.config import load_project_config
from aipass.backup.apps.handlers.project.setup import create_backup_dir
from aipass.backup.apps.handlers.report.result import BackupResult
from aipass.backup.apps.handlers.scan.ceiling import check_ceiling
from aipass.backup.apps.handlers.scan.filter import filter_paths
from aipass.backup.apps.handlers.scan.walk import walk_project
from aipass.backup.apps.handlers.state.changelog import append_changelog
from aipass.backup.apps.handlers.state.metadata import build_metadata
from aipass.backup.apps.handlers.state.progress import LaneProgress
from aipass.backup.apps.handlers.state.stop_flag import catch_sigterm
from aipass.backup.apps.modules.display import (
    build_progress_bar,
    refuse_missing_root,
    refuse_oversized_run,
    show_backups_now,
    show_last_backups,
    show_result_summary,
    show_run_header,
)
from aipass.backup.apps.modules.stop import report_stopped

MODULE_NAME = "versioned"
PRIMARY_COMMAND = "versioned"


def print_introspection():
    """Display module info and connected handlers."""
    console.print(f"[bold cyan]{MODULE_NAME} Module[/bold cyan]")
    console.print(f"  Primary command: [yellow]{PRIMARY_COMMAND}[/yellow]")
    console.print("  Status: Phase 3 — baseline + diff engine")
    console.print("  Handlers: scan, copy/versioned, diff/generator, path, report")


def print_help():
    """Display help for this module."""
    print_introspection()


def run_versioned(
    project_root: str,
    show_panels: bool = True,
    pre_scanned: list[tuple[str, str]] | None = None,
    verb: str = PRIMARY_COMMAND,
) -> BackupResult:
    """Run a versioned backup into the persistent per-file store."""
    start = time.time()

    # create_backup_dir returns None for a non-directory — stop there rather
    # than let the store builder mkdir a tree the project doesn't have.
    if create_backup_dir(project_root) is None:
        return refuse_missing_root("versioned", project_root, show_panels)

    with catch_sigterm(), LaneProgress(project_root, PRIMARY_COMMAND, verb) as running:
        return _versioned_run(project_root, show_panels, pre_scanned, verb, start, running)


def _versioned_run(
    project_root: str,
    show_panels: bool,
    pre_scanned: list[tuple[str, str]] | None,
    verb: str,
    start: float,
    running: LaneProgress,
) -> BackupResult:
    """The versioned run proper, inside the stop handler and the running file."""
    if show_panels:
        show_last_backups(project_root)

    # Loaded on BOTH paths: the ceiling is a guard, and a guard that only
    # runs when this module did its own scan is not guarding the 'all' path.
    config = load_project_config(project_root)

    if pre_scanned is not None:
        filtered = pre_scanned
    else:
        spec = load_spec(project_root)
        whitelist_entries = load_whitelist(project_root)
        max_size = config.get("max_file_size_mb", 100)
        all_files = list(walk_project(project_root, spec, whitelist_entries))
        filtered = filter_paths(all_files, spec, whitelist_entries, max_size)

    breach = check_ceiling(filtered, config)
    if breach is not None:
        return refuse_oversized_run("versioned", project_root, breach, show_panels)

    store = str(build_versioned_store(project_root))

    result = BackupResult(
        mode="versioned",
        project_root=project_root,
        files_checked=len(filtered),
        backup_path=store,
    )

    if show_panels:
        show_run_header(result)

    running.plan(len(filtered))
    progress = build_progress_bar()
    with progress:
        task = progress.add_task("Processing files...", total=len(filtered))
        copy_result = copy_versioned(
            filtered,
            project_root,
            on_progress=lambda: progress.advance(task),
            on_file=running.file_done,
        )

    duration = time.time() - start

    result.files_copied = copy_result.get("files_copied", 0)
    result.files_skipped = result.files_checked - result.files_copied
    result.bytes_copied = copy_result.get("bytes_copied", 0)
    result.duration_seconds = duration
    result.errors = copy_result.get("errors", [])

    # Stopped: no changelog entry (lanes.versioned.last means a completed run).
    if copy_result.get("stopped"):
        result.add_warning("stopped by request")
        report_stopped(
            PRIMARY_COMMAND,
            verb,
            project_root,
            done=copy_result.get("files_done", 0),
            total=len(filtered),
            failed=len(result.errors),
            bytes_done=result.bytes_copied,
        )
        return result

    console.print(f"Processing completed: {len(filtered)}/{len(filtered)} files checked")

    metadata = build_metadata(result)
    append_changelog(project_root, metadata)

    trail.log_operation(
        "versioned_complete",
        {
            "project_root": project_root,
            "files_copied": result.files_copied,
            "files_unchanged": copy_result.get("files_unchanged", 0),
        },
    )
    logger.info(
        f"[backup] Versioned complete: {result.files_copied} changed, {copy_result.get('files_unchanged', 0)} unchanged"
    )

    if show_panels:
        show_result_summary(result)
        if not result.errors:
            show_backups_now(project_root)

    return result


def handle_command(command: str, args: list) -> bool:
    """Handle the versioned command. Returns True if handled."""
    if command != PRIMARY_COMMAND:
        return False

    if not args:
        print_introspection()
        return True

    # Screen every arg: the standalone __main__ skips the router's help normalisation.
    # Bare "help" is first-position only; later args are user values.
    if args[0] == "help" or any(arg in ("--help", "-h") for arg in args):
        print_introspection()
        return True

    project_root = str(resolve_caller_path(args[0]))
    run_versioned(project_root)
    return True


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print_introspection()
        sys.exit(0)
    handle_command(PRIMARY_COMMAND, sys.argv[1:])
