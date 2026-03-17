# =================== AIPass ====================
# Name: notification_module.py
# Description: Notification Preferences Module
# Version: 1.0.0
# Created: 2026-03-07
# Modified: 2026-03-07
# =============================================

"""
Notification Preferences Module

Thin router for notification preference commands. Delegates all
implementation to handlers/notifications/notification_ops.py
and renders results with Rich.

Handles: watch, mute, track, preferences commands.
"""

from typing import List

from aipass.prax.apps.modules.logger import system_logger as logger

try:
    from aipass.cli.apps.modules import console
except ImportError:
    from rich.console import Console
    console = Console()

from commons.apps.handlers.notifications.notification_ops import (
    set_watch,
    set_mute,
    set_track,
    show_preferences,
)
from commons.apps.handlers.json import json_handler


def print_introspection():
    """Display module introspection info."""
    console.print()
    console.print("notification_module Module")
    console.print("Thin router for notification preference commands — watch, mute, track, and preferences display.")
    console.print()
    console.print("Connected Handlers:")
    console.print("  handlers/notifications/")
    console.print("    - notification_ops.py (set_watch — set watch level for all activity notifications)")
    console.print("    - notification_ops.py (set_mute — mute notifications for a target)")
    console.print("    - notification_ops.py (set_track — set track level for mentions and replies only)")
    console.print("    - notification_ops.py (show_preferences — display all notification preferences)")
    console.print()


# =============================================================================
# COMMAND ROUTING
# =============================================================================

def handle_command(command: str, args: List[str]) -> bool:
    """
    Handle notification preference commands.

    Args:
        command: Command name (watch, mute, track, preferences)
        args: Command arguments

    Returns:
        True if command handled, False otherwise
    """
    if command not in ("watch", "mute", "track", "preferences"):
        return False

    # Action command that works without args — route before introspection gate
    if command == "preferences":
        result = _handle_preferences(args)
        if result:
            json_handler.log_operation("preferences_executed", {"command": "preferences", "success": True})
        return result

    if not args:
        print_introspection()
        return True

    if command == "watch":
        result = _handle_level(set_watch(args), "watch")
    elif command == "mute":
        result = _handle_level(set_mute(args), "mute")
    elif command == "track":
        result = _handle_level(set_track(args), "track")
    else:
        return False

    if result:
        json_handler.log_operation(f"{command}_executed", {"command": command, "success": True})
    return result


# =============================================================================
# DISPLAY HANDLERS
# =============================================================================

LEVEL_LABELS = {
    "watch": ("watching", "cyan", "All activity notifications"),
    "track": ("tracking", "green", "Mentions and replies only"),
    "mute": ("muted", "red", "No notifications"),
}


def _handle_level(result: dict, level: str) -> bool:
    """Display the result of setting a notification level."""
    if not result["success"]:
        console.print(f"[red]{result['error']}[/red]")
        return True

    label, color, description = LEVEL_LABELS[level]
    console.print()
    console.print(
        f"[{color}]Now {label} {result['target_type']} "
        f"'{result['target_id']}'[/{color}]"
    )
    console.print(f"  [dim]{description}[/dim]")
    console.print()

    return True


def _handle_preferences(args: List[str]) -> bool:
    """Display all notification preferences for the caller."""
    result = show_preferences(args)

    if not result["success"]:
        console.print(f"[red]{result['error']}[/red]")
        return True

    prefs = result["preferences"]
    agent_name = result["agent"]

    console.print()
    console.print(f"[bold cyan]Notification Preferences for {agent_name}[/bold cyan]")
    console.print()

    if not prefs:
        console.print("  [dim]No custom preferences set. All targets use default (track).[/dim]")
        console.print("  [dim]Track = notified of @mentions and direct replies only.[/dim]")
    else:
        level_colors = {
            "watch": "cyan",
            "track": "green",
            "mute": "red",
        }
        for pref in prefs:
            pref_level = pref["level"]
            color = level_colors.get(pref_level, "white")
            console.print(
                f"  [{color}]{pref_level.upper()}[/{color}] "
                f"{pref['target_type']} '{pref['target_id']}' "
                f"[dim](since {pref['created_at']})[/dim]"
            )

    console.print()
    console.print("[dim]Levels: watch (all activity) | track (mentions/replies) | mute (nothing)[/dim]")
    console.print("[dim]Default for all targets: track[/dim]")
    console.print()

    return True
