# =================== AIPass ====================
# Name: limits.py
# Description: Entry-limits gateway — the public door to the shape, the caps and the budgets
# Version: 1.0.0
# Created: 2026-09-15
# Modified: 2026-09-15
# =============================================

"""
Entry Limits Module — Public API

The caps, the closed entry shape and the whole-file budgets the fleet writes
against, answered from one door. The rules themselves live in
``apps/handlers/json/entry_limits.py`` and stay there; this module is the DOOR
to them.

WHY IT EXISTS. ``apps/handlers/`` is private implementation, and @seedgo's
``check_handler_independence`` sends cross-branch callers to a branch's
``modules`` package instead. Today @hooks and @seedgo both reach past that rule
into ``handlers/json/entry_limits.py`` — @hooks by ``importlib.import_module``
on the dotted handler path, @seedgo by a guarded import of ``draft_target`` —
because no door existed to reach for. This is that door. Their files are theirs
to change on their own pass; nothing here breaks the old path.

``apps/modules/fleet.py`` is the same pattern, built for the same reason.

WHAT THIS IS NOT. Not a wrapper, not a copy, not a compatibility layer. Every
name below is re-exported by IDENTITY, so a caller here and the write gate
inside this branch run the same function object. A gateway that computed
anything would be the second source of truth it exists to prevent — which is
the precise defect FPLAN-0593 Phase 5 closed when ``draft_percent`` stopped
being a module constant here and a mirrored ``_DRAFT_PERCENT`` over in @seedgo.

WHAT IS DELIBERATELY BEHIND THE DOOR. The reason-shape internals
(``_field_violation``, ``_check_list_field``, the private type names) and
``config_loader`` itself. A consumer that pinned those would make a routine
change to how a violation is assembled into a breaking one; the published
reason KEYS are here instead, because @hooks matches on those strings and a
typo in a refusal reason is a refusal nobody renders.

THE COMMAND SURFACE IS INTROSPECTION ONLY. ``drone @memory limits`` describes
the contract and reads the live numbers. Nothing here writes: changing a cap is
``drone @memory config set``, which is @memory's own verb and refuses out of
bounds.

USAGE (cross-branch)::

    from aipass.memory.apps.modules import limits

    shape = limits.fields_for("sessions", limits.load_entry_limits())
    target = limits.draft_target(shape["summary"]["max_chars"])

Import the MODULE, not the symbols: it keeps refusals and logging attributable
to @memory, and a signature change then surfaces as an ``AttributeError`` at the
call site instead of a wrong answer downstream.
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
