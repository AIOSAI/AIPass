# =================== AIPass ====================
# Name: snapshot.py
# Description: Snapshot module — full-copy backup of a project
# Version: 2.2.0
# Created: 2026-04-17
# Modified: 2026-10-17
# =============================================

"""Snapshot Module — full mirror backup of a project directory."""

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
from aipass.cli.apps.modules import console, error

from aipass.backup.apps.handlers.copy.snapshot import copy_snapshot
from aipass.backup.apps.handlers.json.json_handler import WriteFailed
from aipass.backup.apps.handlers.ignore.patterns import load_spec
from aipass.backup.apps.handlers.ignore.whitelist import load_whitelist
from aipass.backup.apps.handlers.audit import trail
from aipass.backup.apps.handlers.path.builder import build_snapshot_path
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
from aipass.backup.apps.handlers.state.timestamps import load_timestamps, save_timestamps
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

MODULE_NAME = "snapshot"
PRIMARY_COMMAND = "snapshot"


def print_introspection():
    """Display module info and connected handlers."""
    console.print(f"[bold cyan]{MODULE_NAME} Module[/bold cyan]")
    console.print(f"  Primary command: [yellow]{PRIMARY_COMMAND}[/yellow]")
    console.print("  Status: Phase 3 — implemented")
    console.print("  Handlers: scan, copy/snapshot, state, ignore, path, report")


def print_help():
    """Display help for this module."""
    print_introspection()


def _build_current_timestamps(
    filtered: list[tuple[str, str]],
) -> dict | None:
    """Build a {rel_path: mtime} dict from filtered files.

    Returns None if any file's mtime cannot be read (invalidates quick-check).
    """
    timestamps: dict[str, float] = {}
    for abs_p, rel_p in filtered:
        try:
            timestamps[rel_p] = os.path.getmtime(abs_p)
        except OSError as e:
            logger.info(f"[backup] Quick-check mtime read failed for {rel_p}: {e}")
            return None
    return timestamps


def _build_saved_timestamps(
    filtered: list[tuple[str, str]],
) -> dict:
    """Build the {rel_path: mtime} dict to persist after a snapshot run.

    A file gone since the scan gets no entry, never an abort; the next quick-check then sees the mismatch.
    """
    timestamps: dict[str, float] = {}
    for abs_p, rel_p in filtered:
        try:
            timestamps[rel_p] = os.path.getmtime(abs_p)
        except OSError as e:
            logger.info(f"[backup] Vanished before timestamp save, skipping {rel_p}: {e}")
    return timestamps


def _persist_timestamps(
    project_root: str,
    filtered: list[tuple[str, str]],
    result: BackupResult,
) -> None:
    """Save the timestamp map for the next quick-check, reporting a lost map.

    Runs after the changelog and audit record: losing the map must not cost this run's record. A failure
    is reported (result, error(), trail), never raised: a stale map only costs a full re-copy next run.
    """
    try:
        save_timestamps(project_root, _build_saved_timestamps(filtered))
    except WriteFailed as e:
        message = f"Snapshot copied, but the timestamp map was not saved: {e}"
        logger.error(f"[backup] {message}")
        error(message)
        trail.log_operation(
            "snapshot_timestamps_failed",
            {"project_root": project_root, "error": str(e)},
        )
        result.add_error(message, is_critical=True)


def _quick_check_early_return(
    project_root: str,
    filtered: list[tuple[str, str]],
    start: float,
    show_panels: bool,
) -> BackupResult:
    """Return an early BackupResult when no files have changed."""
    duration = time.time() - start
    result = BackupResult(
        mode="snapshot",
        project_root=project_root,
        files_checked=len(filtered),
        files_skipped=len(filtered),
        duration_seconds=duration,
    )
    trail.log_operation(
        "snapshot_skipped",
        {
            "project_root": project_root,
            "reason": "no_changes",
            "files_checked": len(filtered),
        },
    )
    logger.info(f"[backup] Snapshot quick-check: no changes ({len(filtered)} files)")
    if show_panels:
        show_run_header(result)
        console.print()
        console.print("[green]No changes detected — snapshot is current[/green]")
        console.print(f"  [dim]Files checked: {len(filtered)} | Duration: {duration:.1f}s[/dim]")
    return result


def run_snapshot(project_root: str, show_panels: bool = True, verb: str = PRIMARY_COMMAND) -> BackupResult:
    """Run a full snapshot backup for a project."""
    start = time.time()

    # Respect create_backup_dir's None refusal: the pipeline would otherwise mkdir the tree
    # and back up the .backupignore it had just written.
    if create_backup_dir(project_root) is None:
        return refuse_missing_root("snapshot", project_root, show_panels)

    with catch_sigterm(), LaneProgress(project_root, PRIMARY_COMMAND, verb) as running:
        return _snapshot_run(project_root, show_panels, verb, start, running)


def _snapshot_run(
    project_root: str,
    show_panels: bool,
    verb: str,
    start: float,
    running: LaneProgress,
) -> BackupResult:
    """The snapshot run proper, inside the stop handler and the running file."""
    if show_panels:
        show_last_backups()

    config = load_project_config(project_root)

    spec = load_spec(project_root)
    whitelist_entries = load_whitelist(project_root)
    max_size = config.get("max_file_size_mb", 100)

    all_files = list(walk_project(project_root))
    filtered = filter_paths(all_files, spec, whitelist_entries, max_size)

    # Ceiling before any copying: a run this large is an ignore-pattern miss, not a big project.
    breach = check_ceiling(filtered, config)
    if breach is not None:
        return refuse_oversized_run("snapshot", project_root, breach, show_panels)

    prev_timestamps = load_timestamps(project_root)
    if prev_timestamps:
        current_timestamps = _build_current_timestamps(filtered)
        if current_timestamps is not None and current_timestamps == prev_timestamps:
            return _quick_check_early_return(
                project_root,
                filtered,
                start,
                show_panels,
            )

    dest = str(build_snapshot_path(project_root))

    result = BackupResult(
        mode="snapshot",
        project_root=project_root,
        files_checked=len(filtered),
        backup_path=dest,
    )

    if show_panels:
        show_run_header(result)

    running.plan(len(filtered))
    progress = build_progress_bar()
    with progress:
        task = progress.add_task("Processing files...", total=len(filtered))
        copy_result = copy_snapshot(
            filtered,
            dest,
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

    # Stopped: no changelog entry (lanes.snapshot.last means a completed run) and no timestamp map
    # (a partial copy must not read as current to the next quick-check).
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
        "snapshot_complete",
        {"project_root": project_root, "files": result.files_copied},
    )
    logger.info(f"[backup] Snapshot complete: {result.files_copied} files")

    # Last: the copy is on disk and recorded before the map only the next run reads can fail anything.
    _persist_timestamps(project_root, filtered, result)

    if show_panels:
        show_result_summary(result)
        if not result.errors:
            show_backups_now("snapshot")

    return result


def handle_command(command: str, args: list) -> bool:
    """Handle the snapshot command. Returns True if handled."""
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

    project_root = args[0]
    run_snapshot(project_root)
    return True


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print_introspection()
        sys.exit(0)
    handle_command(PRIMARY_COMMAND, sys.argv[1:])
