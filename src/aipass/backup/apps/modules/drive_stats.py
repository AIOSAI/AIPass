# =================== AIPass ====================
# Name: drive_stats.py
# Description: Drive stats module — shows file tracker statistics
# Version: 1.0.0
# Created: 2026-04-17
# Modified: 2026-06-12
# =============================================

"""Drive Stats Module — displays tracker statistics for a project."""

import os
import sys

if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8", errors="replace")

from aipass.prax import logger
from aipass.cli.apps.modules import console, error as cli_error

from aipass.backup.apps.handlers.audit import trail


MODULE_NAME = "drive_stats"
PRIMARY_COMMAND = "drive_stats"


def print_introspection():
    """Display module info and connected handlers."""
    console.print(f"[bold cyan]{MODULE_NAME} Module[/bold cyan]")
    console.print(f"  Primary command: [yellow]{PRIMARY_COMMAND}[/yellow]")
    console.print("  Status: Phase 4 -- tracker statistics")
    console.print("  Handlers: drive/tracker")


def print_help():
    """Display help for this module."""
    print_introspection()
    console.print()
    console.print("Usage: drive_stats <project_root>")


def run_drive_stats(project_root: str) -> bool:
    """Show tracker statistics for a project.

    Args:
        project_root: Absolute path to the project.

    Returns:
        True if stats were displayed, False on error.
    """
    from aipass.backup.apps.handlers.drive.tracker import (
        get_stats,
        load_tracker,
    )

    try:
        tracker = load_tracker(project_root)
        stats = get_stats(tracker)

        console.print(f"[bold cyan]Drive Tracker Stats[/bold cyan] -- {project_root}")
        console.print(f"  Total tracked files: {stats['total']}")

        if stats.get("sample"):
            console.print("  Sample entries:")
            for key, entry in stats["sample"].items():
                drive_id = entry.get("drive_id", "?")
                console.print(f"    {key}: {drive_id}")

        trail.log_operation(
            "drive_stats_displayed",
            {"project_root": project_root, "total": stats["total"]},
        )
        logger.info(f"[backup] Drive stats: {stats['total']} tracked files")
        return True
    except Exception as exc:
        logger.warning(f"Failed to load tracker for {project_root}: {exc}")
        cli_error(f"Error loading tracker: {exc}")
        return False


def handle_command(command: str, args: list) -> bool:
    """Handle the drive-stats command. Returns True if handled."""
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
        print_help()
        return True

    project_root = args[0]
    run_drive_stats(project_root)
    return True


# =============================================

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print_introspection()
        sys.exit(0)
    handle_command(PRIMARY_COMMAND, sys.argv[1:])
