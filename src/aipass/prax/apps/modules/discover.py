# =================== AIPass ====================
# Name: discover.py
# Description: PRAX Discover Command
# Version: 1.0.0
# Created: 2026-09-12
# Modified: 2026-09-12
# =============================================

"""
PRAX Discover Module

Implements the 'discover' command: one full walk of the ecosystem that makes
the module registry a truthful snapshot.

The verb existed before and was archived 2026-03-18 (fe5f1d2c) when discovery
became a per-process inotify watch. DPLAN-0339 step 4 brings it back and retires
the watch: the walk now happens once a day on a daemon command job instead of on
the first log line of every process in the fleet.
"""

import os
import sys
from typing import List

if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8", errors="replace")

from aipass.prax.apps.handlers.discovery.scan import run_scan
from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.cli.apps.modules import console, success, error
from aipass.prax.apps.handlers.json import json_handler
from aipass.prax.apps.handlers.cli.arg_gate import refuse
from aipass.prax.apps.handlers.cli.help_flags import wants_help

MAX_NAMES_SHOWN = 10


def print_help():
    """Display module help and connected handlers"""
    console.print()
    console.print("[bold cyan]PRAX Discover Commands:[/bold cyan]")
    console.print("  [white]discover run[/white]        Scan the ecosystem and rewrite the module registry")
    console.print("  [white]discover[/white]            Show what this module is and what it connects to")
    console.print("  [white]discover help[/white]       Show this help")
    console.print()
    console.print("[dim]The scan is a snapshot: modules whose file is gone are removed, not kept.[/dim]")
    console.print("[dim]Runs daily as the module-scan-daily job in .daemon/schedule.json.[/dim]")
    console.print()


def _print_names(label: str, names: List[str]) -> None:
    """Print a capped, sorted name list — a scan that adds 900 modules is a
    count, not a wall of text."""
    if not names:
        return
    shown = ", ".join(names[:MAX_NAMES_SHOWN])
    more = "" if len(names) <= MAX_NAMES_SHOWN else f", +{len(names) - MAX_NAMES_SHOWN} more"
    console.print(f"  [dim]{label}: {shown}{more}[/dim]")


def handle_command(command: str, args: List[str]) -> bool:
    """Handle the 'discover' command routed by the entry point.

    Args:
        command: Command name — anything but "discover" is another module's.
        args: Command arguments.

    Returns:
        True if the command was handled, False to let routing continue.
    """
    if command != "discover":
        return False

    if wants_help(args):
        print_help()
        return True

    # No args shows what this module is, it does not scan. A verb that rewrites
    # the registry is not something a bare word should trigger.
    if not args:
        print_introspection()
        return True

    if args[0] != "run":
        refuse("discover", args[0], "drone @prax discover --help")

    json_handler.log_operation("discover_invoked", {})
    console.print()
    console.print("[bold cyan]Scanning ecosystem for Python modules...[/bold cyan]")

    result = run_scan()

    console.print()
    console.print(f"  Added:      {len(result['added'])}")
    _print_names("added", result["added"])
    console.print(f"  Removed:    {len(result['removed'])}")
    _print_names("removed", result["removed"])
    console.print(f"  Unchanged:  {result['unchanged']}")
    console.print(f"  Total:      {result['total']}")
    console.print()

    if not result["saved"]:
        error("The registry could not be written — the counts above describe the walk, not the file.")
        logger.error("discover: the scan completed but the registry write failed")
        return True

    success(f"Registry updated — {result['total']} modules")
    console.print()
    return True


def print_introspection():
    """Display module introspection info."""
    console.print()
    console.print("[bold cyan]discover Module[/bold cyan]")
    console.print("[dim]One full scan of the ecosystem into the module registry[/dim]")
    console.print()
    console.print("[yellow]Commands:[/yellow]")
    console.print("  [white]discover run[/white]        Scan and rewrite the registry")
    console.print()
    console.print("[yellow]Connected Handlers:[/yellow]")
    console.print("  [cyan]handlers/discovery/[/cyan]")
    console.print("    [dim]→ scan.py (run_scan — walks the ecosystem, writes the registry as a snapshot)[/dim]")
    console.print("    [dim]→ scanner.py (discover_python_modules — the walk itself)[/dim]")
    console.print("  [cyan]handlers/registry/[/cyan]")
    console.print("    [dim]→ save.py (save_module_registry — atomic write, carries the scan stats)[/dim]")
    console.print("    [dim]→ load.py (load_module_registry — what was on record before the walk)[/dim]")
    console.print()


if __name__ == "__main__":
    handle_command("discover", sys.argv[1:])
