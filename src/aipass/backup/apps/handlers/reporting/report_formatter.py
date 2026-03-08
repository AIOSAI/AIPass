
# ===================AIPASS====================
# META DATA HEADER
# Name: report_formatter.py - Backup result reporting
# Date: 2025-11-23
# Version: 1.1.0
# Category: handlers
#
# CHANGELOG (Max 5 entries):
#   - v1.1.0 (2025-11-23): Added dry-run statistics display
#     * Added dry_run parameter to display_backup_results()
#     * Shows "Would copy", "Would skip", "Would delete" in dry-run mode
#     * Provides clear differentiation between dry-run and actual execution
#   - v1.0.0 (2025-11-18): Extracted from backup_core.py
#     * Extracted statistics display formatting
#     * Handles error/warning display
#     * Formats skipped items reports
#
# CODE STANDARDS:
#   - Follow seed 3-layer architecture
#   - Handlers must be independent and transportable
#   - No cross-handler imports except within same domain
# =============================================

"""
Report Formatter - Backup result formatting and display

Formats and displays backup operation results, statistics, errors, and warnings.
"""

# =============================================
# IMPORTS
# =============================================

import datetime
from pathlib import Path

from rich.console import Console

console = Console()

def _header(text):
    console.print(f"\n[bold cyan]{'='*70}[/bold cyan]")
    console.print(f"[bold cyan]  {text}[/bold cyan]")
    console.print(f"[bold cyan]{'='*70}[/bold cyan]")

from aipass.backup.apps.handlers.models.backup_models import BackupResult

# =============================================
# REPORT FORMATTING OPERATIONS
# =============================================

def display_backup_results(result: BackupResult, mode_config: dict, backup_path: Path,
                           skipped_items: dict, filter_tracked_items_func, dry_run: bool = False) -> None:
    """Display comprehensive backup results with statistics and errors.

    Args:
        result: BackupResult with operation statistics
        mode_config: Mode configuration dict
        backup_path: Backup destination path
        skipped_items: Dict of skipped directories and files
        filter_tracked_items_func: Function to filter tracked items
        dry_run: If True, show "would be" language in statistics
    """
    duration = datetime.datetime.now() - result.start_time

    # Determine overall result status
    if result.critical_errors:
        status_style = "[bold red]"
        status_icon = "!"
        status_text = "FAILED"
    elif result.errors > 0:
        status_style = "[bold red]"
        status_icon = "X"
        status_text = "COMPLETED WITH ERRORS"
    elif result.warnings:
        status_style = "[bold yellow]"
        status_icon = "!"
        status_text = "COMPLETED WITH WARNINGS"
    else:
        status_style = "[bold green]"
        status_icon = "OK"
        status_text = "COMPLETED SUCCESSFULLY"

    # Use _header for main status
    console.print()
    _header(f"{status_icon} {mode_config['name'].upper()} {status_text}")
    console.print()

    # Statistics Section
    console.print("[bold cyan]STATISTICS:[/bold cyan]")
    console.print(f"  Files checked: [dim]{result.files_checked}[/dim]")

    if dry_run:
        # Dry-run mode: show "would be" language
        console.print(f"  Would copy:    [bold]{result.files_copied}[/bold] files")
        console.print(f"  Would skip:    [dim]{result.files_skipped}[/dim] files (unchanged)")
        if result.files_deleted > 0:
            console.print(f"  Would delete:  [yellow]{result.files_deleted}[/yellow] files")
    else:
        # Normal mode: show actual actions
        console.print(f"  Files copied:  [bold]{result.files_copied}[/bold]")
        if result.mode == 'versioned' and result.files_added > 0:
            console.print(f"  Files added:   [green]{result.files_added}[/green] (new)")
        console.print(f"  Files skipped: [dim]{result.files_skipped}[/dim]")
        if result.mode == 'versioned' and result.files_deleted == 0:
            console.print(f"  Files deleted: [dim]{result.files_deleted}[/dim] [dim](cleanup disabled - keeps history)[/dim]")
        else:
            console.print(f"  Files deleted: [red]{result.files_deleted}[/red]")

    console.print(f"  Errors:        {status_style}{result.errors}[/]")
    console.print(f"  Warnings:      [yellow]{len(result.warnings)}[/yellow]")
    console.print(f"  Duration:      [blue]{duration.total_seconds():.2f}s[/blue]")
    console.print(f"  Location:      [dim]{backup_path}[/dim]")

    # Display detailed error information
    if result.critical_errors:
        console.print()
        console.print(f"[bold red]CRITICAL ERRORS ({len(result.critical_errors)}):[/bold red]")
        console.print("-" * 40)
        for i, error in enumerate(result.critical_errors, 1):
            console.print(f"  {i}. [red]{error}[/red]")
        console.print()
        console.print("[bold]RECOVERY SUGGESTIONS:[/bold]")
        console.print("  - Check disk space and permissions")
        console.print("  - Ensure backup destination is accessible")
        console.print("  - Try running as administrator if permission issues")
        console.print("  - Check if antivirus is blocking file operations")

    elif result.error_details:
        console.print()
        console.print(f"[bold red]ERRORS ({len(result.error_details)}):[/bold red]")
        console.print("-" * 40)
        for i, error in enumerate(result.error_details[:10], 1):
            console.print(f"  {i}. [red]{error}[/red]")
        if len(result.error_details) > 10:
            console.print(f"  [dim]... and {len(result.error_details) - 10} more errors[/dim]")
        console.print()
        console.print("[bold]SUGGESTIONS:[/bold]")
        console.print("  - Some files may be in use - try closing applications")
        console.print("  - Check file permissions on failed files")

    if result.warnings:
        console.print()
        console.print(f"[bold yellow]WARNINGS ({len(result.warnings)}):[/bold yellow]")
        console.print("-" * 40)
        for i, warning in enumerate(result.warnings[:5], 1):
            console.print(f"  {i}. [yellow]{warning}[/yellow]")
        if len(result.warnings) > 5:
            console.print(f"  [dim]... and {len(result.warnings) - 5} more warnings[/dim]")

    # Display project-specific skipped items
    tracked_items = filter_tracked_items_func(skipped_items)
    total_tracked = len(tracked_items["directories"]) + len(tracked_items["files"])
    total_all_skipped = len(skipped_items["directories"]) + len(skipped_items["files"])

    if total_tracked > 0:
        console.print()
        console.print(f"[bold cyan]NOTABLE SKIPPED ITEMS ({total_tracked}):[/bold cyan]")
        console.print(f"[dim]Total ignored: {total_all_skipped}[/dim]")
        console.print("-" * 50)

        if tracked_items["directories"]:
            console.print(f"[bold]Directories ({len(tracked_items['directories'])}):[/bold]")
            for i, dir_path in enumerate(sorted(tracked_items["directories"]), 1):
                console.print(f"  {i}. [dim]{dir_path}/[/dim]")

        if tracked_items["files"]:
            console.print(f"[bold]Files ({len(tracked_items['files'])}):[/bold]")
            for i, file_path in enumerate(sorted(tracked_items["files"]), 1):
                console.print(f"  {i}. [dim]{file_path}[/dim]")
    else:
        console.print()
        if total_all_skipped > 0:
            console.print(f"[dim]No project-specific items skipped ({total_all_skipped} common items filtered)[/dim]")
        else:
            console.print("[dim]No items were skipped.[/dim]")


# =============================================
# MODULE INITIALIZATION
# =============================================

# Pure handler - no initialization needed
