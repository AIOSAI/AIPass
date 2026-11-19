# =================== AIPass ====================
# Name: fleet.py
# Description: Fleet definition module — introspection of the fleet names the package door hands out
# Version: 2.1.0
# Created: 2026-08-30
# Modified: 2026-11-17
# =============================================

"""
Fleet Definition Module

Describes the fleet contract of ``apps/handlers/monitor/registry_scope.py``. Other branches
take those names from the package door, ``from aipass.memory import <name>``, never from here.
"""

from aipass.prax import logger

from aipass.memory.apps.handlers.json import json_handler

__all__ = ["print_introspection", "handle_command"]


def print_introspection() -> None:
    """Display module introspection (sentry standard)."""
    from aipass.cli import console

    console.print()
    console.print("[bold cyan]fleet Module[/bold cyan]")
    console.print("The fleet definition — who is a citizen, answered once and owned by @memory")
    console.print()
    console.print("[yellow]Public API:[/yellow]")
    console.print("  fleet_branches(repo_root=None, name_from='path')  -> every citizen in scope")
    console.print("  find_repo_root(start=None)                        -> the repo anchor")
    console.print("  declared_residency(branch_path)                   -> what a passport declares")
    console.print("  declared_roots(repo_root=None)                    -> participating repo roots")
    console.print("  external_branches(repo_root=None)                 -> citizens outside this repo")
    console.print("  RESIDENCY_CORE / RESIDENT / EXTERNAL              -> the three tier labels")
    console.print()
    console.print("[dim]Library names — import from: aipass.memory[/dim]")


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

    from aipass.cli import error

    error(f"fleet: unknown subcommand '{args[0]}'")
    print_introspection()
    return True
