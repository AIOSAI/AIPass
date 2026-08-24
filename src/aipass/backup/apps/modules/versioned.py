# =================== AIPass ====================
# Name: versioned.py
# Description: Versioned module — per-file baseline + diff backup
# Version: 3.0.0
# Created: 2026-04-17
# Modified: 2026-06-12
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
from aipass.backup.apps.handlers.json import json_handler
from aipass.backup.apps.handlers.path.builder import build_versioned_store
from aipass.backup.apps.handlers.project.config import load_project_config
from aipass.backup.apps.handlers.project.setup import create_backup_dir
from aipass.backup.apps.handlers.report.result import BackupResult
from aipass.backup.apps.handlers.scan.ceiling import check_ceiling
from aipass.backup.apps.handlers.scan.filter import filter_paths
from aipass.backup.apps.handlers.scan.walk import walk_project
from aipass.backup.apps.handlers.state.changelog import append_changelog
from aipass.backup.apps.handlers.state.metadata import build_metadata
from aipass.backup.apps.modules.display import (
    build_progress_bar,
    refuse_missing_root,
    refuse_oversized_run,
    show_backups_now,
    show_last_backups,
    show_result_summary,
    show_run_header,
)

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
) -> BackupResult:
    """Run a versioned backup into the persistent per-file store.

    Args:
        project_root: Absolute path to the project.
        show_panels: Whether to show rich CLI output.
        pre_scanned: Pre-scanned file list from 'all' (shared scan).
    """
    start = time.time()

    # create_backup_dir returns None for a non-directory — stop there rather
    # than let the store builder mkdir a tree the project doesn't have.
    if create_backup_dir(project_root) is None:
        return refuse_missing_root("versioned", project_root, show_panels)

    if show_panels:
        show_last_backups()

    # Loaded on BOTH paths: the ceiling is a guard, and a guard that only
    # runs when this module did its own scan is not guarding the 'all' path.
    config = load_project_config(project_root)

    if pre_scanned is not None:
        filtered = pre_scanned
    else:
        spec = load_spec(project_root)
        whitelist_entries = load_whitelist(project_root)
        max_size = config.get("max_file_size_mb", 100)
        all_files = list(walk_project(project_root))
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

    progress = build_progress_bar()
    with progress:
        task = progress.add_task("Processing files...", total=len(filtered))
        copy_result = copy_versioned(
            filtered,
            project_root,
            on_progress=lambda: progress.advance(task),
        )

    console.print(f"Processing completed: {len(filtered)}/{len(filtered)} files checked")

    duration = time.time() - start

    result.files_copied = copy_result.get("files_copied", 0)
    result.files_skipped = result.files_checked - result.files_copied
    result.bytes_copied = copy_result.get("bytes_copied", 0)
    result.duration_seconds = duration
    result.errors = copy_result.get("errors", [])

    metadata = build_metadata(result)
    append_changelog(project_root, metadata)

    json_handler.log_operation(
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
            show_backups_now("versioned")

    return result


def handle_command(command: str, args: list) -> bool:
    """Handle the versioned command. Returns True if handled."""
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
    run_versioned(project_root)
    return True


# =============================================

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print_introspection()
        sys.exit(0)
    handle_command(PRIMARY_COMMAND, sys.argv[1:])
