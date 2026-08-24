# =================== AIPass ====================
# Name: display.py
# Description: Rich CLI rendering for backup results (full 9-stage output)
# Version: 3.0.0
# Created: 2026-06-12
# Modified: 2026-06-12
# =============================================

"""Rich CLI rendering for backup — full output pipeline faithfully ported from gold source."""

import os
import sys

if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8", errors="replace")

from rich.progress import BarColumn, Progress, TextColumn, TimeRemainingColumn

from aipass.prax import logger
from aipass.cli.apps.modules import console, error, header, success, warning

from aipass.backup.apps.handlers.json import json_handler
from aipass.backup.apps.handlers.report.formatter import _human_bytes
from aipass.backup.apps.handlers.report.result import BackupResult
from aipass.backup.apps.handlers.scan.ceiling import CeilingBreach
from aipass.backup.apps.handlers.state.backup_timestamps import (
    format_age,
    get_timestamps,
    update_timestamp,
)

MODULE_NAME = "display"


def print_introspection():
    """Display module info."""
    console.print(f"[bold cyan]{MODULE_NAME} Module[/bold cyan]")
    console.print("  Rich CLI rendering for backup results (full 9-stage output)")
    console.print("  Not a command module — used by snapshot/versioned/all")


def refuse_missing_root(mode: str, project_root: str, show_panels: bool = True) -> BackupResult:
    """Build the refusal result for a project root that is not a directory.

    Shared by snapshot/versioned/all: create_backup_dir refuses a non-directory
    by returning None, and every caller must stop there rather than let the
    rest of the pipeline mkdir the tree it was told not to touch.
    """
    message = f"Project path is not a directory: {project_root}"
    logger.error(f"[backup] {mode} refused — {message}")
    if show_panels:
        error(message)
    json_handler.log_operation(
        f"{mode}_refused",
        {"project_root": project_root, "reason": "not a directory"},
    )
    result = BackupResult(mode=mode, project_root=project_root)
    result.add_error(message, is_critical=True)
    return result


def refuse_oversized_run(
    mode: str,
    project_root: str,
    breach: CeilingBreach,
    show_panels: bool = True,
) -> BackupResult:
    """Build the refusal result for a run that breached a per-run ceiling.

    Shared by snapshot/versioned/all. Fails LOUD and early: the alternative
    the baud incident demonstrated is a run that grinds for 7.5h writing
    50GB of build artifacts while reporting nothing wrong.
    """
    message = f"Backup refused — {breach.summary()}"
    logger.error(f"[backup] {mode} refused — {breach.summary()}")
    if show_panels:
        error(message)
        for line in breach.detail_lines():
            console.print(f"[dim]{line}[/dim]")
    json_handler.log_operation(
        f"{mode}_refused",
        {
            "project_root": project_root,
            "reason": f"ceiling_{breach.reason}",
            "measured": breach.measured,
            "limit": breach.limit,
        },
    )
    result = BackupResult(mode=mode, project_root=project_root)
    result.add_error(message, is_critical=True)
    return result


def print_help():
    """Display help for this module."""
    print_introspection()


def show_last_backups() -> None:
    """Stage 1: Show 'Last backups:' panel with dim ages."""
    ts = get_timestamps()
    console.print()
    console.print("[dim]Last backups:[/dim]")
    console.print(f"  [dim]Snapshot:   {format_age(ts.get('snapshot'))}[/dim]")
    console.print(f"  [dim]Versioned:  {format_age(ts.get('versioned'))}[/dim]")
    console.print(f"  [dim]Drive sync: {format_age(ts.get('drive_sync'))}[/dim]")


def show_run_header(result: BackupResult) -> None:
    """Stage 3: Show run header with boxed panel."""
    header(
        f"Backup — {result.mode.title()}",
        {
            "Project": result.project_root,
            "Mode": result.mode,
        },
    )


def build_progress_bar():
    """Stage 5: Create and return a Rich Progress context for the copy loop."""
    return Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeRemainingColumn(),
        console=console,
        transient=True,
    )


def show_result_summary(result: BackupResult) -> None:
    """Stage 6+7: Show rich result summary (stats + completion status)."""
    console.print()

    if result.errors:
        if len(result.errors) > 5:
            error(
                f"{result.mode.title()} backup FAILED",
                suggestion="Check file permissions and disk space",
            )
        else:
            warning(
                f"{result.mode.title()} completed with {len(result.errors)} errors",
                details="; ".join(result.errors[:3]),
            )
        for err in result.errors[:5]:
            console.print(f"  [dim]- {err}[/dim]")
        if len(result.errors) > 5:
            console.print(f"  [dim]... and {len(result.errors) - 5} more[/dim]")
    else:
        success(
            f"{result.mode.title()} backup complete",
            files_copied=result.files_copied,
            files_checked=result.files_checked,
            files_skipped=result.files_skipped,
            size=_human_bytes(result.bytes_copied),
        )

    location = result.backup_path if result.backup_path else result.project_root
    console.print(f"  [dim]Duration: {result.duration_seconds:.1f}s | Location: {location}[/dim]")

    json_handler.log_operation("render_result", {"mode": result.mode})
    logger.info(f"[backup] Rendered {result.mode} result: {result.files_copied} files")


def show_backups_now(mode: str) -> None:
    """Stage 8: Update timestamp and show 'Backups now:' panel with updated dim ages."""
    update_timestamp(mode)
    ts = get_timestamps()
    console.print()
    console.print("[dim]Backups now:[/dim]")
    console.print(f"  [dim]Snapshot:   {format_age(ts.get('snapshot'))}[/dim]")
    console.print(f"  [dim]Versioned:  {format_age(ts.get('versioned'))}[/dim]")
    console.print(f"  [dim]Drive sync: {format_age(ts.get('drive_sync'))}[/dim]")


def show_drive_result(result: dict) -> None:
    """Show Drive sync result panel matching Snapshot/Versioned style."""
    console.print()

    total = result.get("total", 0)
    uploaded = result.get("uploaded", 0)
    failed = result.get("failed", 0)
    skipped = result.get("skipped", 0)
    bytes_uploaded = result.get("bytes_uploaded", 0)
    duration = result.get("duration", 0.0)
    location = result.get("location", "")

    header(
        "Backup — Drive sync",
        {
            "Location": location,
            "Mode": "drive_sync",
        },
    )

    console.print(f"Processing completed: {total}/{total} files checked")

    if failed:
        warning(
            f"Drive sync completed with {failed} failures",
            details=f"{uploaded} uploaded, {skipped} skipped",
        )
    else:
        success(
            "Drive sync complete",
            files_copied=uploaded,
            files_checked=total,
            files_skipped=skipped,
            size=_human_bytes(bytes_uploaded),
        )

    console.print(f"  [dim]Duration: {duration:.1f}s | Location: {location}[/dim]")

    if not failed:
        show_backups_now("drive_sync")

    json_handler.log_operation("render_drive_result", {"uploaded": uploaded})
    logger.info(f"[backup] Rendered drive_sync result: {uploaded} uploaded")


def handle_command(command: str, args: list) -> bool:
    """Handle only the module's own name. Returns True if handled.

    Display is a rendering helper, not a backup verb, so it answers to
    'display' alone. The missing ownership guard was the bug: discovery order
    put this module first, so a no-args gate that ignored the command name
    swallowed EVERY unknown command and printed this introspection instead of
    the unknown-command error.
    """
    if command != MODULE_NAME:
        return False

    if not args:
        print_introspection()
        return True

    if args[0] in ("--help", "-h", "help"):
        print_introspection()
        return True

    return False


# =============================================
