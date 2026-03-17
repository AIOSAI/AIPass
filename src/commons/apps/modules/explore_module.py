# =================== AIPass ====================
# Name: explore_module.py
# Description: Exploration Module
# Version: 1.0.0
# Created: 2026-03-07
# Modified: 2026-03-07
# =============================================

"""
Exploration Module

Router + display layer for secret room exploration commands. Delegates
all logic to handlers/rooms/explore_ops.py and renders results with Rich.

Handles: explore, secrets commands.
"""

from typing import List

from aipass.prax.apps.modules.logger import system_logger as logger

try:
    from aipass.cli.apps.modules import console
except ImportError:
    from rich.console import Console
    console = Console()

from rich.panel import Panel
from rich.table import Table

from commons.apps.handlers.rooms.explore_ops import explore_rooms, list_secrets
from commons.apps.handlers.json import json_handler


def print_introspection():
    """Display module introspection info."""
    console.print()
    console.print("explore_module Module")
    console.print("Router and display layer for secret room exploration commands.")
    console.print()
    console.print("Connected Handlers:")
    console.print("  handlers/rooms/")
    console.print("    - explore_ops.py (explore_rooms — discover hidden rooms based on visit history)")
    console.print("    - explore_ops.py (list_secrets — list discovered secret rooms)")
    console.print()


# =============================================================================
# COMMAND ROUTING
# =============================================================================

def handle_command(command: str, args: List[str]) -> bool:
    """Handle exploration commands."""
    if command not in ["explore", "secrets"]:
        return False

    if command == "explore":
        result = _handle_explore(args)
    elif command == "secrets":
        result = _handle_secrets(args)
    else:
        return False

    if result:
        json_handler.log_operation(f"{command}_executed", {"command": command, "success": True})
    return result


# =============================================================================
# DISPLAY HANDLERS
# =============================================================================

def _handle_explore(args: List[str]) -> bool:
    result = explore_rooms(args)
    if not result["success"]:
        console.print(f"[red]{result['error']}[/red]")
        return True

    hidden_rooms = result["hidden_rooms"]
    rooms_visited = result["rooms_visited"]

    if not hidden_rooms:
        console.print("\n[dim]No hidden rooms exist... yet.[/dim]\n")
        return True

    console.print()
    console.print(Panel(
        "[italic]You sense something beyond the ordinary rooms...[/italic]\n\n"
        "[dim]Hidden places exist in The Commons. "
        "Those who explore widely may discover their names.[/dim]",
        title="[bold]Exploration[/bold]",
        border_style="magenta",
    ))
    console.print()

    console.print("[bold]Whispered Hints:[/bold]")
    console.print()
    for room in hidden_rooms:
        hint = room.get("discovery_hint") or "..."
        console.print(f"  [magenta]?[/magenta] [italic]{hint}[/italic]")
    console.print()

    revealed = result.get("revealed")
    if revealed:
        console.print(f"[green]Your exploration has paid off! You've visited {rooms_visited} rooms.[/green]")
        console.print(f"[green]A secret room reveals itself:[/green] [bold magenta]r/{revealed['name']}[/bold magenta]")
        console.print(f"  [dim]{revealed['description']}[/dim]")
        console.print()
        console.print(f"[dim]Try: commons enter {revealed['name']}[/dim]")
    else:
        remaining = 3 - rooms_visited
        console.print(f"[dim]You've visited {rooms_visited} room(s). Visit {remaining} more to unlock a discovery...[/dim]")

    console.print()
    return True


def _handle_secrets(args: List[str]) -> bool:
    result = list_secrets(args)
    if not result["success"]:
        console.print(f"[red]{result['error']}[/red]")
        return True

    discovered = result["discovered"]
    total_hidden = result["total_hidden"]

    console.print()

    if not discovered:
        console.print("[dim]You haven't discovered any secret rooms yet.[/dim]")
        console.print(f"[dim]There are {total_hidden} secret room(s) waiting to be found.[/dim]")
        console.print("[dim]Try: commons explore[/dim]")
    else:
        table = Table(title="Your Discovered Secrets", border_style="magenta")
        table.add_column("Room", style="bold magenta")
        table.add_column("Name", style="bold")
        table.add_column("Description", style="dim")

        for room in discovered:
            table.add_row(f"r/{room['name']}", room["display_name"], room["description"])

        console.print(table)
        console.print(f"\n[dim]Discovered {len(discovered)} of {total_hidden} secret room(s)[/dim]")

    console.print()
    return True
