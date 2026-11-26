# =================== AIPass ====================
# Name: room.py
# Description: Room management orchestration module
# Version: 1.0.3
# Created: 2026-03-07
# Modified: 2026-11-26
# =============================================

"""Room Management Module"""

from typing import List

from aipass.prax import logger  # noqa: F401 - the imports standard requires the prax logger in every module
from aipass.cli import console, error, success

from rich.table import Table

from aipass.commons.apps.handlers.rooms.room_ops import create_room, list_rooms, join_room, leave_room
from aipass.commons.apps.handlers.json import json_handler


def print_introspection():
    """Display module introspection info."""
    console.print()
    console.print("[bold cyan]room - Room Management[/bold cyan]")
    console.print("[dim]Thin router for room management. Handles creating, listing, and joining community rooms.[/dim]")
    console.print()
    console.print("[bold cyan]Connected Handlers:[/bold cyan]")
    console.print("  [cyan]handlers/rooms/[/cyan]")
    console.print("    [cyan]-[/cyan] room_ops.py [dim](create_room — create a new community room)[/dim]")
    console.print(
        "    [cyan]-[/cyan] room_ops.py [dim](list_rooms — list all available rooms with member/post counts)[/dim]"
    )
    console.print("    [cyan]-[/cyan] room_ops.py [dim](join_room — join an existing room as a member)[/dim]")
    console.print()
    console.print("[dim]Run 'drone @commons room --help' for usage[/dim]")


def print_help():
    """Display usage help for the room command."""
    console.print()
    console.print("[bold cyan]room - Room Management[/bold cyan]")
    console.print("[dim]Create, list, join and leave community rooms.[/dim]")
    console.print()
    console.print("[bold cyan]Usage:[/bold cyan]")
    console.print("  [cyan]drone @commons room create[/cyan] <name> \\[description...]")
    console.print("  [cyan]drone @commons room list[/cyan]")
    console.print("  [cyan]drone @commons room join[/cyan] <name>")
    console.print("  [cyan]drone @commons room leave[/cyan] <name>")
    console.print()
    console.print("[bold cyan]Examples:[/bold cyan]")
    console.print('  [cyan]drone @commons room create builds "Build talk"[/cyan]')
    console.print("  [cyan]drone @commons room list[/cyan]")
    console.print("  [cyan]drone @commons room join builds[/cyan]")
    console.print("  [cyan]drone @commons room leave builds[/cyan]")
    console.print()


def handle_command(command: str, args: List[str]) -> bool:
    """Handle `room <create|list|join|leave>`; False if the command is not ours."""
    if command != "room":
        return False

    if "--help" in args or "-h" in args:
        print_help()
        return True

    if not args:
        print_introspection()
        return True

    subcommand = args[0].lower()
    sub_args = args[1:]

    if subcommand == "create":
        result = _handle_create_room(sub_args)
    elif subcommand == "list":
        result = _handle_list_rooms()
    elif subcommand == "join":
        result = _handle_join_room(sub_args)
    elif subcommand == "leave":
        result = _handle_leave_room(sub_args)
    else:
        error(f"Unknown room subcommand: {subcommand}")
        console.print("[dim]Available: create, list, join, leave[/dim]")
        return True

    if result:
        json_handler.log_operation(f"room_{subcommand}_executed", {"command": "room", "success": True})
    return result


def _handle_create_room(args: List[str]) -> bool:
    """Create a room and display the result."""
    result = create_room(args)

    if not result["success"]:
        error(result["error"])
        return True

    console.print()
    success(f"Room '{result['name']}' created!")
    if result.get("description"):
        console.print(f"  [dim]Description:[/dim] {result['description']}")
    console.print(f"  [dim]Created by:[/dim] {result['created_by']}")
    console.print()

    return True


def _handle_list_rooms() -> bool:
    """List rooms and display as a Rich table."""
    result = list_rooms()

    if not result["success"]:
        error(result["error"])
        return True

    rooms = result["rooms"]

    console.print()
    console.print(f"[bold cyan]Rooms in The Commons[/bold cyan] [dim]({len(rooms)} rooms)[/dim]")
    console.print()

    if not rooms:
        console.print("[dim]  No rooms yet. Create one with: room create <name> \\[description][/dim]")
        console.print()
        return True

    table = Table(show_header=True, header_style="bold", expand=False, padding=(0, 1))
    table.add_column("Room", style="cyan", min_width=15)
    table.add_column("Description", min_width=30)
    table.add_column("Members", width=8, justify="center")
    table.add_column("Posts", width=8, justify="center")

    for room in rooms:
        table.add_row(
            room["name"],
            room.get("description", "") or "[dim]--[/dim]",
            str(room.get("member_count", 0)),
            str(room.get("post_count", 0)),
        )

    console.print(table)
    console.print()

    return True


def _handle_join_room(args: List[str]) -> bool:
    """Join a room and display the result."""
    result = join_room(args)

    if not result["success"]:
        error(result["error"])
        return True

    console.print()
    success(f"{result['agent']} joined room '{result['room']}'!")
    console.print()

    return True


def _handle_leave_room(args: List[str]) -> bool:
    """Leave a room and display the result."""
    result = leave_room(args)

    if not result["success"]:
        error(result["error"])
        return True

    console.print()
    success(f"{result['agent']} left room '{result['room']}'.")
    console.print()

    return True
