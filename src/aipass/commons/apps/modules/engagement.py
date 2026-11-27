# =================== AIPass ====================
# Name: engagement.py
# Description: Engagement Orchestration Module
# Version: 1.0.1
# Created: 2026-03-07
# Modified: 2026-11-26
# =============================================

"""Engagement Orchestration Module"""

from typing import List

from aipass.prax import logger  # noqa: F401 - the imports standard requires the prax logger in every module
from aipass.cli import console, error, success

from aipass.commons.apps.handlers.engagement.engagement_ops import generate_prompt, create_event
from aipass.commons.apps.handlers.json import json_handler


def print_introspection():
    """Display module introspection info."""
    console.print()
    console.print("[bold cyan]engagement - Community Engagement[/bold cyan]")
    console.print(
        "[dim]Thin router for community engagement workflows. Generates daily prompts and creates events.[/dim]"
    )
    console.print()
    console.print("[bold cyan]Connected Handlers:[/bold cyan]")
    console.print("  [cyan]handlers/engagement/[/cyan]")
    console.print(
        "    [cyan]-[/cyan] engagement_ops.py [dim](generate_prompt — create and post a daily community prompt)[/dim]"
    )
    console.print(
        "    [cyan]-[/cyan] engagement_ops.py [dim](create_event — create a community event/announcement)[/dim]"
    )
    console.print()
    console.print("[dim]Run 'drone @commons prompt --help' or 'drone @commons event --help' for usage[/dim]")


def print_help():
    """Display usage help for the prompt and event commands."""
    console.print()
    console.print("[bold cyan]engagement - Community Engagement[/bold cyan]")
    console.print("[dim]Post a daily community prompt or announce a community event[/dim]")
    console.print()
    console.print("[bold cyan]Usage:[/bold cyan]")
    console.print('  [cyan]drone @commons prompt[/cyan] \\[--theme "question"] \\[--dry-run]')
    console.print("  [cyan]drone @commons event[/cyan] <title> <description> \\[--dry-run]")
    console.print()
    console.print("[bold cyan]Examples:[/bold cyan]")
    console.print("  [cyan]drone @commons prompt --dry-run[/cyan]")
    console.print('  [cyan]drone @commons prompt --theme "What did you build today?"[/cyan]')
    console.print('  [cyan]drone @commons event "Release day" "v2 ships Friday"[/cyan]')
    console.print()


HANDLED_COMMANDS = ["prompt", "event"]


def handle_command(command: str, args: List[str]) -> bool:
    """Handle engagement-related commands; False if the command is not ours."""
    if command not in HANDLED_COMMANDS:
        return False

    if "--help" in args or "-h" in args:
        print_help()
        return True

    if command == "prompt":
        result = _handle_prompt(args)
    elif command == "event":
        result = _handle_event(args)
    else:
        return False

    if result:
        json_handler.log_operation(f"{command}_executed", {"command": command, "success": True})
    return result


def _handle_prompt(args: List[str]) -> bool:
    """Generate a daily prompt and display result."""
    result = generate_prompt(args)

    if not result["success"]:
        error(result["error"])
        return True

    if result.get("dry_run"):
        console.print()
        console.print("[bold cyan][DRY RUN] Prompt preview:[/bold cyan]")
        console.print(f"  [dim]Room:[/dim] r/{result['room']}")
        console.print(f"  [dim]Theme:[/dim] {result['theme']}")
        console.print()
        return True

    console.print()
    success("Daily prompt posted!")
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
        error(result["error"])
        return True

    if result.get("dry_run"):
        console.print()
        console.print("[bold cyan][DRY RUN] Event preview:[/bold cyan]")
        console.print(f"  [dim]Room:[/dim] r/{result['room']}")
        console.print(f"  [dim]Title:[/dim] {result['title']}")
        console.print()
        return True

    console.print()
    success("Event created!")
    console.print(f"  [dim]ID:[/dim] {result['post_id']}")
    console.print(f"  [dim]Room:[/dim] r/{result['room']}")
    console.print(f"  [dim]Title:[/dim] {result['title']}")
    console.print("  [dim]Type:[/dim] announcement")
    console.print(f"  [dim]Author:[/dim] {result['author']}")
    console.print()

    return True
