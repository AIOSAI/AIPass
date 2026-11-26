# =================== AIPass ====================
# Name: activity.py
# Description: Activity Feed Orchestration Module
# Version: 1.0.1
# Created: 2026-03-07
# Modified: 2026-11-26
# =============================================

"""
Activity Feed Orchestration Module

Handles: activity command.
"""

from typing import List

from aipass.prax import logger  # noqa: F401 - the imports standard requires the prax logger in every module
from aipass.cli import console, error

from rich.table import Table

from aipass.commons.apps.handlers.activity.activity_ops import run_activity
from aipass.commons.apps.handlers.identity.identity_ops import resolve_display_name
from aipass.commons.apps.handlers.json import json_handler


def print_introspection():
    """Display module introspection info."""
    console.print()
    console.print("[bold cyan]activity - Activity Feed[/bold cyan]")
    console.print("[dim]Queries recent comment activity across The Commons and renders it as a table.[/dim]")
    console.print()
    console.print("[bold cyan]Connected Handlers:[/bold cyan]")
    console.print("  [cyan]handlers/activity/[/cyan]")
    console.print("    [cyan]-[/cyan] activity_ops.py [dim](run_activity — query recent community activity feed)[/dim]")
    console.print("  [cyan]handlers/identity/[/cyan]")
    console.print(
        "    [cyan]-[/cyan] identity_ops.py [dim](resolve_display_name — resolve branch agent to display name)[/dim]"
    )
    console.print()
    console.print("[dim]Run 'drone @commons activity --help' for usage[/dim]")
    console.print()


def print_help():
    """Display usage help."""
    console.print()
    console.print("[bold cyan]activity - Activity Feed[/bold cyan]")
    console.print("[dim]Queries recent comment activity across The Commons and renders it as a table.[/dim]")
    console.print()
    console.print("[bold cyan]Usage:[/bold cyan]")
    console.print("  [cyan]drone @commons activity[/cyan] \\[--limit N] \\[--room ROOM]")
    console.print()
    console.print("[bold cyan]Examples:[/bold cyan]")
    console.print("  [cyan]drone @commons activity[/cyan]")
    console.print("  [cyan]drone @commons activity --limit 10 --room general[/cyan]")
    console.print()


def handle_command(command: str, args: List[str]) -> bool:
    """Handle activity-related commands."""
    if command == "activity" and ("--help" in args or "-h" in args):
        print_help()
        return True

    if command != "activity":
        return False

    return _handle_activity(args)


def _handle_activity(args: List[str]) -> bool:
    """Query activity and display as Rich table."""
    result = run_activity(args)

    if not result["success"]:
        if result.get("error"):
            error(result["error"])
        return True

    if result.get("help"):
        console.print(result["help_text"])
        return True

    activities = result["activities"]
    room_filter = result.get("room_filter")

    console.print()

    if not activities:
        if room_filter:
            console.print(f"[dim]No recent activity in room '{room_filter}'.[/dim]")
        else:
            console.print("[dim]No recent activity in The Commons.[/dim]")
        console.print()
        return True

    title = "Recent Activity"
    if room_filter:
        title += f" in #{room_filter}"

    table = Table(title=title, show_lines=False, pad_edge=True)
    table.add_column("Time", style="dim", no_wrap=True, width=10)
    table.add_column("Author", style="cyan", no_wrap=True, width=14)
    table.add_column("Thread", style="green", no_wrap=True, width=30)
    table.add_column("Comment", style="white", width=60)

    for activity in activities:
        author = resolve_display_name(activity["author"])
        table.add_row(
            activity["time"],
            author,
            activity["title"],
            activity["content"],
        )

    console.print(table)
    console.print()

    json_handler.log_operation("activity_executed", {"command": "activity", "success": True})
    return True
