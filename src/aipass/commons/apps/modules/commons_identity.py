# =================== AIPass ====================
# Name: commons_identity.py
# Description: Branch identity detection module
# Version: 1.3.1
# Created: 2026-03-08
# Modified: 2026-11-26
# =============================================

"""
Branch Identity Detection for commons

Handles whoami; the identity names live in handlers/identity/identity_ops.
"""

from typing import List

from aipass.prax import logger
from aipass.cli import console, error

from aipass.commons.apps.handlers.identity.identity_ops import get_caller_branch, resolve_display_name
from aipass.commons.apps.handlers.json import json_handler

__all__ = ["handle_command"]


def print_introspection():
    """Display module introspection info."""
    console.print()
    console.print("[bold cyan]commons_identity - Branch Identity[/bold cyan]")
    console.print("[dim]Branch identity detection — detects caller branch and resolves display names[/dim]")
    console.print()
    console.print("[bold cyan]Connected Handlers:[/bold cyan]")
    console.print("  [cyan]handlers/identity/[/cyan]")
    console.print("    [cyan]-[/cyan] identity_ops.py [dim](find_branch_root — locate branch root directory)[/dim]")
    console.print(
        "    [cyan]-[/cyan] identity_ops.py [dim](get_branch_info_from_registry — look up branch in registry)[/dim]"
    )
    console.print("    [cyan]-[/cyan] identity_ops.py [dim](get_caller_branch — detect which branch is calling)[/dim]")
    console.print("    [cyan]-[/cyan] identity_ops.py [dim](extract_mentions — parse @mentions from text)[/dim]")
    console.print(
        "    [cyan]-[/cyan] identity_ops.py [dim](resolve_display_name — map branch name to display name)[/dim]"
    )
    console.print()
    console.print("[dim]Run 'drone @commons whoami --help' for usage[/dim]")


def print_help():
    """Display usage help for the whoami command."""
    console.print()
    console.print("[bold cyan]commons_identity - Branch Identity[/bold cyan]")
    console.print("[dim]Show which branch you are, with its description and path[/dim]")
    console.print()
    console.print("[bold cyan]Usage:[/bold cyan]")
    console.print("  [cyan]drone @commons whoami[/cyan]")
    console.print()
    console.print("[bold cyan]Examples:[/bold cyan]")
    console.print("  [cyan]drone @commons whoami[/cyan]")
    console.print()


def handle_command(command: str, args: List[str]) -> bool:
    """Handle identity-related commands routed by the entry point."""
    if command == "whoami":
        if "--help" in args or "-h" in args:
            print_help()
            return True
        result = _handle_whoami()
        if result:
            json_handler.log_operation("whoami_executed", {"command": "whoami", "success": True})
        return result
    return False


def _handle_whoami() -> bool:
    """Detect and display the caller's branch identity."""
    try:
        branch_info = get_caller_branch()

        if not branch_info:
            # error(), not warning(): only error() marks the command failed, which resolve_exit() reads.
            error("Could not detect your branch identity. Run from a branch directory.")
            return True

        name = branch_info.get("name", "unknown")
        display = resolve_display_name(name)
        description = branch_info.get("description", "")
        path = branch_info.get("path", "")

        console.print()
        console.print(f"[bold cyan]You are:[/bold cyan] {display}")
        if description:
            console.print(f"[dim]  {description}[/dim]")
        if path:
            console.print(f"[dim]  Path: {path}[/dim]")
        console.print()

        return True

    except Exception as e:
        logger.error(f"[commons.identity] whoami failed: {e}")
        error(f"Error detecting identity: {e}")
        return True
