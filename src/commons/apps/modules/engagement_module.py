# =================== AIPass ====================
# Name: engagement_module.py
# Description: Engagement Orchestration Module
# Version: 1.0.0
# Created: 2026-03-07
# Modified: 2026-03-07
# =============================================

"""
Engagement Orchestration Module

Thin router for community engagement workflows. Delegates all
implementation to handlers/engagement/engagement_ops.py and
renders results with Rich.

Handles: prompt, event commands.
"""

from typing import List

from aipass.prax.apps.modules.logger import system_logger as logger

try:
    from aipass.cli.apps.modules import console
except ImportError:
    from rich.console import Console
    console = Console()

from commons.apps.handlers.engagement.engagement_ops import generate_prompt, create_event
from commons.apps.handlers.json import json_handler


def print_introspection():
    """Display module introspection info."""
    console.print()
    console.print("engagement_module Module")
    console.print("Thin router for community engagement workflows. Generates daily prompts and creates events.")
    console.print()
    console.print("Connected Handlers:")
    console.print("  handlers/engagement/")
    console.print("    - engagement_ops.py (generate_prompt — create and post a daily community prompt)")
    console.print("    - engagement_ops.py (create_event — create a community event/announcement)")
    console.print()


# =============================================================================
# COMMAND ROUTING
# =============================================================================

HANDLED_COMMANDS = ["prompt", "event"]


def handle_command(command: str, args: List[str]) -> bool:
    """
    Handle engagement-related commands.

    Args:
        command: Command name (prompt, event)
        args: Command arguments

    Returns:
        True if command handled, False otherwise
    """
    if command not in HANDLED_COMMANDS:
        return False

    if command == "prompt":
        result = _handle_prompt(args)
    elif command == "event":
        result = _handle_event(args)
    else:
        return False

    if result:
        json_handler.log_operation(f"{command}_executed", {"command": command, "success": True})
    return result


# =============================================================================
# DISPLAY HANDLERS
# =============================================================================

def _handle_prompt(args: List[str]) -> bool:
    """Generate a daily prompt and display result."""
    result = generate_prompt(args)

    if not result["success"]:
        console.print(f"[red]{result['error']}[/red]")
        return True

    console.print()
    console.print("[green]Daily prompt posted![/green]")
    console.print(f"  [dim]ID:[/dim] {result['post_id']}")
    console.print(f"  [dim]Room:[/dim] r/{result['room']}")
    console.print(f"  [dim]Theme:[/dim] {result['theme']}")
    console.print(f"  [dim]Author:[/dim] {result['author']}")
    console.print()

    return True


def _handle_event(args: List[str]) -> bool:
    """Create an event and display result."""
    result = create_event(args)

    if not result["success"]:
        console.print(f"[red]{result['error']}[/red]")
        return True

    console.print()
    console.print("[green]Event created![/green]")
    console.print(f"  [dim]ID:[/dim] {result['post_id']}")
    console.print(f"  [dim]Room:[/dim] r/{result['room']}")
    console.print(f"  [dim]Title:[/dim] {result['title']}")
    console.print(f"  [dim]Type:[/dim] announcement")
    console.print(f"  [dim]Author:[/dim] {result['author']}")
    console.print()

    return True
