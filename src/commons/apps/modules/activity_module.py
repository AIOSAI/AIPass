# =================== AIPass ====================
# Name: activity_module.py
# Description: Activity Feed Orchestration Module
# Version: 1.0.0
# Created: 2026-03-07
# Modified: 2026-03-07
# =============================================

"""
Activity Feed Orchestration Module

Thin router for the activity command. Delegates query logic
to handlers/activity/activity_ops.py and renders results with Rich.

Handles: activity command.
"""

from typing import List

from aipass.prax.apps.modules.logger import system_logger as logger

try:
    from aipass.cli.apps.modules import console
except ImportError:
    from rich.console import Console
    console = Console()

from rich.table import Table

from commons.apps.handlers.activity.activity_ops import run_activity
from commons.apps.handlers.identity.identity_ops import resolve_display_name
from commons.apps.handlers.json import json_handler


def print_introspection():
    """Display module introspection info."""
    console.print()
    console.print("activity_module Module")
    console.print("Thin router for the activity command. Queries recent activity and renders it as a Rich table.")
    console.print()
    console.print("Connected Handlers:")
    console.print("  handlers/activity/")
    console.print("    - activity_ops.py (run_activity — query recent community activity feed)")
    console.print("  handlers/identity/")
    console.print("    - identity_ops.py (resolve_display_name — resolve branch agent to display name)")
    console.print()


# =============================================================================
# COMMAND ROUTING
# =============================================================================

def handle_command(command: str, args: List[str]) -> bool:
    """
    Handle activity-related commands.

    Args:
        command: Command name (activity)
        args: Command arguments

    Returns:
        True if command handled, False otherwise
    """
    if command != "activity":
        return False

    return _handle_activity(args)


# =============================================================================
# DISPLAY HANDLER
# =============================================================================

def _handle_activity(args: List[str]) -> bool:
    """Query activity and display as Rich table."""
    result = run_activity(args)

    if not result["success"]:
        if result.get("error"):
            console.print(f"[red]{result['error']}[/red]")
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
