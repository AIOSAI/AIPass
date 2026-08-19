# =================== AIPass ====================
# Name: pool.py
# Description: Pool Module — drone CLI for pool commands
# Version: 1.0.0
# Created: 2026-06-06
# Modified: 2026-06-06
# =============================================

"""
Pool Module — drone CLI routing for memory pool commands.

Thin delegation layer. All implementation lives in handlers/intake/auto_process.py.
"""

import os
import sys
from typing import List, Any

if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8", errors="replace")

from rich.panel import Panel
from rich import box

from aipass.prax import logger  # noqa: F401
from aipass.cli.apps.modules import console, error
from aipass.memory.apps.handlers.json import json_handler
from aipass.memory.apps.handlers.cli.help_flags import wants_help


# =============================================================================
# COMMAND HANDLERS
# =============================================================================

_SUBCOMMANDS = {
    "process": "Process memory pool files (vectorize + archive)",
    "status": "Show memory pool status",
}


def handle_command(command: str, args: List[Any]) -> bool:
    """
    Handle pool commands.

    Routing:
        pool (no args)        -> print_introspection()
        pool --help/-h/help   -> print_help()
        pool process          -> run auto_process()
        pool status           -> show pool status

    Args:
        command: Command name
        args: Additional arguments

    Returns:
        True if command handled, False otherwise
    """
    if command == "pool":
        if not args:
            print_introspection()
            return True

        # A help flag ANYWHERE wins — asking about `process` must never process.
        # No pool subcommand takes free text, so a bare `help` counts too.
        if wants_help(args, allow_bare_word=True):
            print_help()
            return True

        sub = args[0]

        if sub == "process":
            _run_process_command()
            return True

        if sub == "status":
            _run_status_command()
            return True

        error(
            f"Unknown subcommand: '{sub}'",
            suggestion="Available: " + ", ".join(_SUBCOMMANDS.keys()),
        )
        return True

    return False


# =============================================================================
# CLI DISPLAY
# =============================================================================


def _run_process_command() -> None:
    """Execute pool processing + rollover check and display results."""
    from aipass.memory.apps.handlers.intake.auto_process import auto_process

    console.print()
    console.print("[bold cyan]Processing memory pool...[/bold cyan]")
    console.print()

    result = auto_process()

    json_handler.log_operation(
        "pool_process_command",
        {"success": result.get("success", False)},
    )

    # Pool results
    pool = result.get("pool", {})
    if pool.get("skipped"):
        console.print(f"[dim]Pool: skipped — {pool.get('reason', 'unknown')}[/dim]")
    elif pool.get("success") is False:
        error(f"Pool: failed — {pool.get('error', 'unknown')}")
    else:
        files = pool.get("files_processed", 0)
        chunks = pool.get("total_chunks", 0)
        if files > 0:
            console.print(f"[green]>[/green] Pool: {files} files processed, {chunks} chunks vectorized")
        else:
            console.print("[dim]Pool: no files to process[/dim]")

    # Rollover results
    rollover = result.get("rollover", {})
    if rollover.get("skipped"):
        console.print("[dim]Rollover: no triggers[/dim]")
    elif rollover.get("success") is False:
        error(f"Rollover: failed — {rollover.get('error', 'unknown')}")
    else:
        processed = rollover.get("processed", 0)
        total = rollover.get("triggers", 0)
        console.print(f"[green]>[/green] Rollover: {processed}/{total} triggers processed")

    console.print()


def _run_status_command() -> None:
    """Display memory pool status."""
    from aipass.memory.apps.handlers.intake.pool_processor import get_pool_status

    console.print()

    status = get_pool_status()

    json_handler.log_operation(
        "pool_status_command",
        {"files_in_pool": status.get("files_in_pool", 0)},
    )

    enabled = "[green]enabled[/green]" if status.get("enabled") else "[red]disabled[/red]"
    console.print(f"[bold cyan]Memory Pool Status[/bold cyan]  ({enabled})")
    console.print()
    console.print(f"  Files in pool:  {status.get('files_in_pool', 0)}")
    console.print(f"  Keep recent:    {status.get('keep_recent', 0)}")
    console.print(f"  Vectors stored: {status.get('vectors_stored', 0)}")
    console.print(f"  Collection:     {status.get('collection_name', 'unknown')}")

    newest = status.get("newest_file")
    oldest = status.get("oldest_file")
    if newest:
        console.print(f"  Newest file:    {newest}")
    if oldest and oldest != newest:
        console.print(f"  Oldest file:    {oldest}")

    console.print()


def print_introspection() -> None:
    """Display pool module introspection."""
    console.print()
    console.print("[bold cyan]Pool Module - Memory Pool Processing[/bold cyan]")
    console.print()
    console.print("[dim]Processes memory_pool/ files and checks rollover triggers[/dim]")
    console.print()
    for sub, desc in _SUBCOMMANDS.items():
        console.print(f"  [cyan]*[/cyan] {sub} — {desc}")
    console.print()


def print_help() -> None:
    """Display pool module help."""
    console.print()
    console.print(
        Panel.fit(
            "[bold cyan]Pool Module - Memory Pool & Auto-Processing[/bold cyan]\n"
            "[dim]Vectorize pool files, check rollover, manual or hook-driven[/dim]",
            border_style="cyan",
            box=box.ROUNDED,
        )
    )
    console.print()
    console.print("[bold cyan]COMMANDS:[/bold cyan]")
    console.print()
    console.print("  [green]pool process[/green]   Process pool files + check/run rollover")
    console.print("  [green]pool status[/green]    Show pool file count, config, vector stats")
    console.print()
    console.print("[bold cyan]USAGE:[/bold cyan]")
    console.print()
    console.print("  [dim]drone @memory pool process[/dim]")
    console.print("  [dim]drone @memory pool status[/dim]")
    console.print()
