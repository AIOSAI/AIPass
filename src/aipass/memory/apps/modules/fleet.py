# =================== AIPass ====================
# Name: fleet.py
# Description: Fleet definition module — the public cross-branch gateway
# Version: 2.0.0
# Created: 2026-08-30
# Modified: 2026-10-17
# =============================================

"""
Fleet Definition Module — Public API

Cross-branch door to ``apps/handlers/monitor/registry_scope.py``: names are re-exported
by IDENTITY, never wrapped, so there is one definition. Import the MODULE, not the symbols.
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

    from aipass.cli.apps.modules import error

    error(f"fleet: unknown subcommand '{args[0]}'")
    print_introspection()
    return True
