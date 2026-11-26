# =================== AIPass ====================
# Name: limits.py
# Description: Entry-limits module — introspection of the shape, the caps and the budgets
# Version: 1.1.1
# Created: 2026-09-15
# Modified: 2026-11-26
# =============================================

"""
Entry Limits Module

Describes ``handlers/json/entry_limits.py``. Other branches take its names from the
package door, ``from aipass.memory import load_entry_limits``, never from here.
"""

from aipass.prax import logger

from aipass.memory.apps.handlers.json import json_handler
from aipass.memory.apps.handlers.json.entry_limits import draft_percent

__all__ = ["print_introspection", "handle_command"]


def print_introspection() -> None:
    """Display module introspection (sentry standard)."""
    from aipass.cli import console

    console.print()
    console.print("[bold cyan]limits Module[/bold cyan]")
    console.print("The entry shape, the char caps and the file budgets — owned by @memory, read from one door")
    console.print()
    console.print("[yellow]Public API:[/yellow]")
    console.print("  load_entry_limits(branch=None)            -> the entry_limits config, per_branch merged")
    console.print("  fields_for(entry_type, limits)            -> the closed shape: every field an entry may carry")
    console.print("  changed_entries(before, after, ...)       -> what a write AUTHORS, split from what it carries")
    console.print("  check_file_budget(file_name, text)        -> the file-over-budget violation, or none")
    console.print(f"  draft_target(max_chars)                   -> {draft_percent()}% of one cap, floored")
    console.print()
    console.print("[dim]Library names — import from: aipass.memory[/dim]")
    console.print("[dim]Run drone @memory limits --help for more[/dim]")


def print_help() -> None:
    """Display limits help (sentry standard)."""
    from aipass.cli import console

    console.print()
    console.print("[bold cyan]limits[/bold cyan] - introspection of the entry-limits library")
    console.print()
    console.print("[bold]USAGE:[/bold]")
    console.print("  drone @memory limits            Show the public API")
    console.print("  drone @memory limits --help     Show this help")
    console.print("  Library module, imported from aipass.memory; this verb only describes it")
    console.print()
    console.print("[bold]EXAMPLES:[/bold]")
    console.print("  [dim]drone @memory limits[/dim]")
    console.print()


def handle_command(command: str, args: list) -> bool:
    """Entry point for drone module discovery — limits has no CLI work, only introspection."""
    if command != "limits":
        return False

    json_handler.log_operation("limits_command", {"args": args})
    logger.debug(f"[limits] introspection requested with args={args}")

    if not args:
        print_introspection()
        return True

    if args[0] in ("--help", "-h", "help"):
        print_introspection()
        return True

    from aipass.cli import error

    error(f"limits: unknown subcommand '{args[0]}'")
    print_introspection()
    return True
