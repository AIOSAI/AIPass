# =================== AIPass ====================
# Name: governance.py
# Description: Surfacing governance module — introspection of the names the package door hands out
# Version: 1.3.0
# Created: 2026-07-16
# Modified: 2026-11-26
# =============================================

"""
Surfacing Governance Module

Cross-branch consumers import from the package door: ``from aipass.memory import should_surface``.
"""

from aipass.prax import logger  # noqa: F401
from aipass.memory.apps.handlers.json import json_handler

__all__ = ["print_introspection", "handle_command"]


def print_introspection() -> None:
    """Display module introspection (sentry standard)."""
    from aipass.cli import console

    console.print()
    console.print("[bold cyan]governance Module[/bold cyan]")
    console.print("Pure surfacing governance — state-in/state-out decision functions")
    console.print()
    console.print("[yellow]Public API:[/yellow]")
    console.print("  should_surface(item_id, relevance_score, state, config)")
    console.print("  record_message(state)")
    console.print("  new_state()")
    console.print()
    console.print("[dim]Library names — import from: aipass.memory[/dim]")
    console.print("[dim]Run drone @memory governance --help for more[/dim]")


def print_help() -> None:
    """Display governance help (sentry standard)."""
    from aipass.cli import console

    console.print()
    console.print("[bold cyan]governance[/bold cyan] - introspection of the surfacing-governance library")
    console.print()
    console.print("[bold]USAGE:[/bold]")
    console.print("  drone @memory governance        Show the public API")
    console.print("  drone @memory governance --help Show this help")
    console.print("  Library module, imported from aipass.memory; this verb only describes it")
    console.print()
    console.print("[bold]EXAMPLES:[/bold]")
    console.print("  [dim]drone @memory governance[/dim]")
    console.print()


def handle_command(command: str, args: list) -> bool:
    """Entry point for drone module discovery — governance has no CLI surface."""
    if command != "governance":
        return False

    json_handler.log_operation("governance_command", {"args": args})

    if not args:
        print_introspection()
        return True

    if args[0] in ("--help", "-h", "help"):
        print_help()
        return True

    from aipass.cli import error

    error(f"governance: unknown subcommand '{args[0]}'")
    print_introspection()
    return True
