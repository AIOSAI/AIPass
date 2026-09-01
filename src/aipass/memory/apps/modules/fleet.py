# =================== AIPass ====================
# Name: fleet.py
# Description: Fleet definition module — the public cross-branch gateway
# Version: 2.0.0
# Created: 2026-08-30
# Modified: 2026-08-30
# =============================================

"""
Fleet Definition Module — Public API

Who is in the fleet, answered once. The definition itself lives in
``apps/handlers/monitor/registry_scope.py`` and stays there; this module is the
DOOR to it.

WHY IT EXISTS. ``apps/handlers/`` is private implementation. @seedgo's
``handlers_check.py`` states the rule directly — another branch's ``modules``
package is its PUBLIC GATEWAY, and ``check_handler_independence`` sends
cross-branch callers there — so the handler import I sanctioned for @daemon
failed both encapsulation and handlers on their first checklist run. They
reported it rather than shimming around it (dispatch 2a70bbcd), which was the
right call: a gateway living in @daemon would be a second public surface for MY
module in a branch I do not control, and the next consumer would import theirs
or write a third. That is the "implementations agreeing by coincidence" failure
in a new costume, which is the exact thing ``registry_scope`` 2.0.0 was built to
end.

``apps/modules/health.py`` is the same pattern, built for the same consumer.

WHAT THIS IS NOT. Not a wrapper, not a copy, not a compatibility layer. Every
name below is re-exported by IDENTITY, so a caller here and a caller inside this
branch run the same function object. A gateway that computed anything would be
the second definition it exists to prevent.

WHAT IS DELIBERATELY BEHIND THE DOOR. ``resident_registry_paths`` and
``read_registry_branches`` are the mechanics of HOW residents are found, not the
question of who is in the fleet. They stop being the whole story the moment the
external tier lands, so pinning a consumer to them would make a routine change
a breaking one.

THE COMMAND SURFACE IS INTROSPECTION ONLY. I first built this with no
``handle_command`` at all, reasoning that a library gateway should stay
invisible to ``apps/memory.py``'s module discovery. The branch's own convention
said otherwise — ``health.py``, the gateway built for the same consumer, is
discoverable and answers introspection, and three @seedgo standards agree with
it. So this one does the same: ``drone @memory fleet`` describes the contract
and nothing here executes fleet work from the CLI.

USAGE (cross-branch)::

    from aipass.memory.apps.modules import fleet

    for citizen in fleet.fleet_branches():
        ...  # citizen["name"], citizen["email"], citizen["path"]

Import the MODULE, not the symbols: it keeps refusals and logging attributable
to @memory, and a signature change then surfaces as an ``AttributeError`` at the
call site instead of a wrong answer downstream.
"""

from aipass.prax import logger

from aipass.memory.apps.handlers.json import json_handler
from aipass.memory.apps.handlers.monitor.registry_scope import (
    DECLARED_ROOTS,
    RESIDENCY_CORE,
    RESIDENCY_EXTERNAL,
    RESIDENCY_RESIDENT,
    accepted_resident_paths,
    declared_residency,
    declared_roots,
    external_branches,
    find_repo_root,
    fleet_branches,
)

__all__ = [
    "fleet_branches",
    "find_repo_root",
    "declared_residency",
    "accepted_resident_paths",
    "declared_roots",
    "external_branches",
    "RESIDENCY_CORE",
    "RESIDENCY_RESIDENT",
    "RESIDENCY_EXTERNAL",
    "DECLARED_ROOTS",
]


def print_introspection() -> None:
    """Display module introspection (seedgo standard)."""
    from aipass.cli.apps.modules import console

    console.print()
    console.print("[bold cyan]fleet Module[/bold cyan]")
    console.print("The fleet definition — who is a citizen, answered once and owned by @memory")
    console.print()
    console.print("[yellow]Public API:[/yellow]")
    console.print("  fleet_branches(repo_root=None, name_from='path')  -> every citizen in scope")
    console.print("  find_repo_root(start=None)                        -> the repo anchor")
    console.print("  declared_residency(branch_path)                   -> what a passport declares")
    console.print("  accepted_resident_paths(repo_root=None)           -> resolved resident paths")
    console.print("  declared_roots(repo_root=None)                    -> participating repo roots")
    console.print("  external_branches(repo_root=None)                 -> citizens outside this repo")
    console.print("  RESIDENCY_CORE / RESIDENT / EXTERNAL              -> the three tier labels")
    console.print(f"  DECLARED_ROOTS                                    -> '{DECLARED_ROOTS}', the machine anchor")
    console.print()
    console.print("[dim]Library module — import from: aipass.memory.apps.modules.fleet[/dim]")


def handle_command(command: str, args: list) -> bool:
    """Entry point for drone module discovery — fleet has no CLI work, only introspection."""
    if command != "fleet":
        return False

    json_handler.log_operation("fleet_command", {"args": args})
    logger.debug(f"[fleet] introspection requested with args={args}")

    if not args:
        print_introspection()
        return True

    if args[0] in ("--help", "-h", "help"):
        print_introspection()
        return True

    from aipass.cli.apps.modules import warning

    warning(f"fleet: unknown subcommand '{args[0]}'")
    print_introspection()
    return True
