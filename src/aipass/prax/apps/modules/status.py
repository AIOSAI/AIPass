# =================== AIPass ====================
# Name: status.py
# Description: PRAX Status Command
# Version: 1.4.0
# Created: 2025-11-15
# Modified: 2026-10-17
# =============================================

"""PRAX Status Module"""

import os
import sys
from typing import List

if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8", errors="replace")

from aipass.prax.apps.modules.logger import get_system_status, system_logger as logger
from aipass.prax.apps.handlers.status.sync import sync_status
from aipass.cli.apps.modules import console, error, warning
from aipass.prax.apps.handlers.json import json_handler
from aipass.prax.apps.handlers.cli.arg_gate import refuse
from aipass.prax.apps.handlers.cli.help_flags import wants_help


def print_help():
    """Display module help and connected handlers"""
    console.print()
    console.print("[bold cyan]PRAX Status Commands:[/bold cyan]")
    console.print("  [white]status[/white]              Show PRAX system status")
    console.print(
        "  [white]status sync[/white]         Scan branch STATUS.local.md files (writes nothing — decommissioned)"
    )
    console.print("  [white]status help[/white]         Show this help")
    console.print()


def _format_last_scan(last_scan: dict | None) -> str:
    """One line describing the last discovery scan.

    No watcher line: is_file_watcher_active() answers for the calling process, never this one.
    None (unreadable registry) must not print as "never"."""
    if last_scan is None:
        return "unreadable — the registry could not be read; see the prax log"
    if not last_scan:
        return "never — run: drone @prax discover run"

    when = str(last_scan.get("timestamp", "unknown"))
    added = last_scan.get("added", "?")
    removed = last_scan.get("removed", "?")
    return f"{when} (+{added} / -{removed})"


def handle_command(command: str, args: List[str]) -> bool:
    """Handle status command"""
    if command != "status":
        return False

    # A help flag anywhere wins: before the sync verb and before the unknown-argument refusal.
    if wants_help(args):
        print_help()
        return True

    if args and args[0] == "sync":
        json_handler.log_operation("status_checked", {"subcommand": "sync"})
        return _handle_sync()

    # Refuse, never swallow: a typo'd subcommand must not print the normal block and exit 0.
    if args:
        refuse("status", args[0], "drone @prax status --help")

    json_handler.log_operation("status_checked", {"subcommand": "show"})
    status = get_system_status()

    console.print()
    console.print("[bold cyan]PRAX System Status[/bold cyan]")
    console.print("=" * 60)
    total = status["total_modules"]
    console.print(f"  Total Modules:   {'unreadable (see the prax log)' if total is None else total}")
    console.print(f"  Active Loggers:  {status['individual_loggers']}")
    console.print(f"  System Logs Dir: {status['system_logs_dir']}")
    console.print(f"  Module Logs Dir: {status['module_logs_dir']}")
    console.print(f"  Registry File:   {status['registry_file']}")
    console.print(f"  Last Scan:       {_format_last_scan(status['last_scan'])}")
    console.print(f"  Logger Override: {'Active' if status['logger_override_active'] else 'Inactive'}")
    console.print("=" * 60)
    console.print()
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

    # The scan is real, the write is not: never report "written".
    warning(
        f"Nothing written — {len(synced)} branches scanned",
        details=result.get("reason", ""),
    )

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
    console.print("status Module")
    console.print("Implements the 'status' command to display PRAX system status dashboard")
    console.print()
    console.print("Connected Handlers:")
    console.print("  modules/")
    console.print("    - logger.py (get_system_status — returns module count, watcher, override status)")
    console.print("    - logger.py (system_logger — auto-routing logger for module log files)")
    console.print()


if __name__ == "__main__":
    if len(sys.argv) == 1:
        print_help()
        sys.exit(0)
