# =================== AIPass ====================
# Name: drive_stats.py
# Description: Drive stats module — shows file tracker statistics and the Drive account quota
# Version: 1.1.1
# Created: 2026-04-17
# Modified: 2026-10-17
# =============================================

"""Drive Stats Module — displays tracker statistics for a project and the Drive account quota."""

import os
import sys

if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8", errors="replace")

from aipass.prax import logger
from aipass.cli.apps.modules import console, error as cli_error, warning

from aipass.backup.apps.handlers.audit import trail
from aipass.backup.apps.handlers.report.formatter import _human_bytes


MODULE_NAME = "drive_stats"
PRIMARY_COMMAND = "drive_stats"


def print_introspection():
    """Display module info and connected handlers."""
    console.print(f"[bold cyan]{MODULE_NAME} Module[/bold cyan]")
    console.print(f"  Primary command: [yellow]{PRIMARY_COMMAND}[/yellow]")
    console.print("  Status: Phase 4 -- tracker statistics, account quota")
    console.print("  Handlers: drive/tracker, drive/client")


def print_help():
    """Display help for this module."""
    print_introspection()
    console.print()
    console.print("Usage: drive_stats <project_root>")
    console.print("  Prints the project's tracker, then the Drive account's storage used and limit")
    console.print("  (about.get storageQuota) -- one live, read-only Drive call.")


def show_drive_quota() -> bool:
    """Print the Drive account's storage used and limit, as two lines.

    Drive leaves ``limit`` out for unlimited storage; an absent field is said, never filled in.
    """
    from aipass.backup.apps.handlers.drive.client import DriveClient
    from aipass.backup.apps.handlers.drive.quota import read_quota

    client = DriveClient()
    if not client.authenticate():
        warning(f"Drive quota unavailable: {client.last_error or 'Drive authentication failed'}")
        return False

    quota = read_quota(client)
    if quota["error"]:
        warning(f"Drive quota unavailable: {quota['error']}")
        logger.warning(f"[backup] Drive quota unavailable: {quota['error']}")
        return False

    usage = quota["usage"]
    console.print(f"  Drive used:  {_human_bytes(usage)} ({usage:,} bytes)")
    limit = quota["limit"]
    if limit is None:
        console.print("  Drive limit: none reported -- Drive sends no limit for unlimited storage")
        logger.info(f"[backup] Drive quota: {usage} used, no limit reported")
        return False
    console.print(f"  Drive limit: {_human_bytes(limit)} ({limit:,} bytes)")
    logger.info(f"[backup] Drive quota: {usage} used of {limit}")
    return True


def run_drive_stats(project_root: str) -> bool:
    """Show tracker statistics for a project."""
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
    except Exception as exc:
        logger.warning(f"Failed to load tracker for {project_root}: {exc}")
        cli_error(f"Error loading tracker: {exc}")
        return False

    show_drive_quota()
    return True


def handle_command(command: str, args: list) -> bool:
    """Handle the drive-stats command. Returns True if handled."""
    if command != PRIMARY_COMMAND:
        return False

    if not args:
        print_introspection()
        return True

    # Screen every arg: the standalone __main__ skips the router's help normalisation.
    # Bare "help" is first-position only; later args are user values.
    if args[0] == "help" or any(arg in ("--help", "-h") for arg in args):
        print_help()
        return True

    project_root = args[0]
    run_drive_stats(project_root)
    return True


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print_introspection()
        sys.exit(0)
    handle_command(PRIMARY_COMMAND, sys.argv[1:])
