# =================== AIPass ====================
# Name: status_module.py
# Description: PRAX Status Command
# Version: 1.1.0
# Created: 2025-11-15
# Modified: 2026-03-10
# =============================================

"""
PRAX Status Module

Implements the 'status' command using handle_command interface.
"""

import sys
from pathlib import Path
from typing import List

from aipass.prax.apps.modules.logger import get_system_status, system_logger as logger
from aipass.prax.apps.handlers.status.sync import sync_status
from aipass.cli.apps.modules import console, header, success, error, warning


def print_help():
    """Display module help and connected handlers"""
    console.print()
    console.print("[bold cyan]PRAX Status Commands:[/bold cyan]")
    console.print("  [white]status[/white]              Show PRAX system status")
    console.print("  [white]status sync[/white]         Scan all branches, build STATUS.md at repo root")
    console.print("  [white]status help[/white]         Show this help")
    console.print()


def handle_command(command: str, args: List[str]) -> bool:
    """
    Handle status command

    Args:
        command: Command name
        args: Command arguments

    Returns:
        True if command was handled
    """
    if command != 'status':
        return False

    # --- sub-command routing ------------------------------------------------
    if args and args[0] in ("--help", "help"):
        print_help()
        return True

    if args and args[0] == "sync":
        return _handle_sync()

    # --- default: show PRAX system status -----------------------------------
    status = get_system_status()

    console.print("\n📊 PRAX System Status")
    console.print("=" * 60)
    console.print(f"Total Modules: {status['total_modules']}")
    console.print(f"Active Loggers: {status['individual_loggers']}")
    console.print(f"System Logs Dir: {status['system_logs_dir']}")
    console.print(f"Module Logs Dir: {status['module_logs_dir']}")
    console.print(f"Registry File: {status['registry_file']}")
    console.print(f"File Watcher: {'🟢 Active' if status['file_watcher_active'] else '🔴 Inactive'}")
    console.print(f"Logger Override: {'🟢 Active' if status['logger_override_active'] else '🔴 Inactive'}")
    console.print("=" * 60 + "\n")
    return True


def _handle_sync() -> bool:
    """Run the status sync handler and display results."""
    console.print()
    console.print("[bold cyan]Syncing branch status...[/bold cyan]")

    try:
        result = sync_status()
    except Exception as exc:
        error(f"Status sync failed: {exc}")
        logger.error("Status sync failed: %s", exc)
        return True

    if result["status"] == "error":
        error("Status sync encountered an error — check logs for details.")
        return True

    synced = result["branches_synced"]
    missing = result["branches_missing"]

    success(f"STATUS.md written — {len(synced)} branches synced")

    if missing:
        warning(
            f"{len(missing)} branches missing STATUS.local.md",
            details=", ".join(missing),
        )

    console.print(f"  [dim]Timestamp: {result['timestamp']}[/dim]")
    console.print()
    return True


def print_introspection():
    """Display module introspection info."""
    console.print()
    console.print("status_module Module")
    console.print("Implements the 'status' command to display PRAX system status dashboard")
    console.print()
    console.print("Connected Handlers:")
    console.print("  modules/")
    console.print("    - logger.py (get_system_status — returns module count, watcher, override status)")
    console.print("    - logger.py (system_logger — auto-routing logger for module log files)")
    console.print()


if __name__ == "__main__":
    # Show introspection when run without arguments
    if len(sys.argv) == 1:
        print_help()
        sys.exit(0)
