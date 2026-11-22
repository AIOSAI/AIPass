# =================== AIPass ====================
# Name: status.py
# Description: PRAX Status Command
# Version: 2.1.0
# Created: 2025-11-15
# Modified: 2026-11-22
# =============================================

"""PRAX Status Module"""

import sys
from typing import List

from aipass.prax.apps.modules.logger import get_system_status
from aipass.cli import console
from aipass.prax.apps.handlers.json import json_handler
from aipass.prax.apps.handlers.cli.arg_gate import refuse
from aipass.prax.apps.handlers.cli.help_flags import wants_help


def print_help():
    """Display module help and connected handlers"""
    console.print()
    console.print("[bold cyan]prax Status Commands:[/bold cyan]")
    console.print("  [white]status[/white]              Show prax system status")
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

    # A help flag anywhere wins: before the unknown-argument refusal.
    if wants_help(args):
        print_help()
        return True

    # Refuse, never swallow: a typo'd subcommand must not print the normal block and exit 0.
    if args:
        refuse("status", args[0], "drone @prax status --help")

    json_handler.log_operation("status_checked", {"subcommand": "show"})
    status = get_system_status()

    console.print()
    console.print("[bold cyan]prax System Status[/bold cyan]")
    console.print("=" * 60)
    total = status["total_modules"]
    console.print(f"  Total Modules:   {'unreadable (see the prax log)' if total is None else total}")
    console.print(f"  Loggers opened by this command: {status['individual_loggers']}")
    console.print(f"  System Logs Dir: {status['system_logs_dir']}")
    console.print(f"  Module Logs Dir: {status['module_logs_dir']}")
    console.print(f"  Registry File:   {status['registry_file']}")
    console.print(f"  Last Scan:       {_format_last_scan(status['last_scan'])}")
    console.print("=" * 60)
    console.print()
    return True


def print_introspection():
    """Display module introspection info."""
    console.print()
    console.print("status Module")
    console.print("Implements the 'status' command to display prax system status dashboard")
    console.print()
    console.print("Connected Handlers:")
    console.print("  modules/")
    console.print("    - logger.py (get_system_status — returns module count, log dirs, registry, last scan)")
    console.print()


if __name__ == "__main__":
    if len(sys.argv) == 1:
        print_help()
        sys.exit(0)
