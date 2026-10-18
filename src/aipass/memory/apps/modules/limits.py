# =================== AIPass ====================
# Name: limits.py
# Description: Entry-limits gateway — the public door to the shape, the caps and the budgets
# Version: 1.0.0
# Created: 2026-09-15
# Modified: 2026-10-17
# =============================================

"""
Entry Limits Module — Public API

The cross-branch door to ``handlers/json/entry_limits.py``. Every name is
re-exported by identity: computing anything here would be a second source of truth.
Import the module, not the symbols, so a signature change fails at the call site.
"""

from aipass.prax import logger

from aipass.memory.apps.handlers.json import json_handler
from aipass.memory.apps.handlers.json.entry_limits import (
    REASON_FIELD_OVER_CAP,
    REASON_FILE_OVER_BUDGET,
    REASON_UNKNOWN_FIELD,
    changed_entries,
    check_file_budget,
    draft_percent,
    draft_target,
    fields_for,
    load_entry_limits,
    load_file_budgets,
)

__all__ = [
    "load_entry_limits",
    "load_file_budgets",
    "fields_for",
    "changed_entries",
    "check_file_budget",
    "draft_percent",
    "draft_target",
    "REASON_UNKNOWN_FIELD",
    "REASON_FIELD_OVER_CAP",
    "REASON_FILE_OVER_BUDGET",
]


def print_introspection() -> None:
    """Display module introspection (seedgo standard)."""
    from aipass.cli.apps.modules import console

    console.print()
    console.print("[bold cyan]limits Module[/bold cyan]")
    console.print("The entry shape, the char caps and the file budgets — owned by @memory, read from one door")
    console.print()
    console.print("[yellow]Public API:[/yellow]")
    console.print("  load_entry_limits(branch=None)            -> the entry_limits config, per_branch merged")
    console.print("  load_file_budgets()                       -> the whole-file ceilings, per .trinity file")
    console.print("  fields_for(entry_type, limits)            -> the closed shape: every field an entry may carry")
    console.print("  changed_entries(before, after, ...)       -> what a write AUTHORS, split from what it carries")
    console.print("  check_file_budget(file_name, text)        -> the file-over-budget violation, or none")
    console.print(f"  draft_percent()                           -> {draft_percent()}, the percent to draft to")
    console.print("  draft_target(max_chars)                   -> that percent of one cap, floored")
    console.print("  REASON_UNKNOWN_FIELD / _FIELD_OVER_CAP / _FILE_OVER_BUDGET")
    console.print()
    console.print("[dim]Library module — import from: aipass.memory.apps.modules.limits[/dim]")


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

    from aipass.cli.apps.modules import error

    error(f"limits: unknown subcommand '{args[0]}'")
    print_introspection()
    return True
