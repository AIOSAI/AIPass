# =================== AIPass ====================
# Name: commons_identity.py
# Description: Branch identity detection module
# Version: 1.1.0
# Created: 2026-03-08
# Modified: 2026-03-08
# =============================================

"""
Branch Identity Detection for The Commons

Thin wrapper that re-exports identity functions from
handlers/identity/identity_ops.py for backward compatibility.

Handles: whoami command.

Usage:
    from commons.apps.modules.commons_identity import get_caller_branch
"""

from typing import List

from aipass.prax.apps.modules.logger import system_logger as logger

try:
    from aipass.cli.apps.modules import console, error, warning
except ImportError:
    from rich.console import Console
    console = Console()
    error = lambda msg, **kw: console.print(f"[red]{msg}[/red]")
    warning = lambda msg, **kw: console.print(f"[yellow]{msg}[/yellow]")

# Re-export all public functions for backward compatibility
from commons.apps.handlers.identity.identity_ops import (
    find_branch_root,
    get_branch_info_from_registry,
    get_caller_branch,
    extract_mentions,
    resolve_display_name,
)
from commons.apps.handlers.json import json_handler

__all__ = [
    "find_branch_root",
    "get_branch_info_from_registry",
    "get_caller_branch",
    "extract_mentions",
    "resolve_display_name",
    "handle_command",
]


def print_introspection():
    """Display module introspection info."""
    console.print()
    console.print("commons_identity Module")
    console.print("Branch identity detection — detects caller branch and resolves display names")
    console.print()
    console.print("Connected Handlers:")
    console.print("  handlers/identity/")
    console.print("    - identity_ops.py (find_branch_root — locate branch root directory)")
    console.print("    - identity_ops.py (get_branch_info_from_registry — look up branch in registry)")
    console.print("    - identity_ops.py (get_caller_branch — detect which branch is calling)")
    console.print("    - identity_ops.py (extract_mentions — parse @mentions from text)")
    console.print("    - identity_ops.py (resolve_display_name — map branch name to display name)")
    console.print()


# =============================================================================
# COMMAND ROUTING
# =============================================================================

def handle_command(command: str, args: List[str]) -> bool:
    """
    Handle identity-related commands routed by the entry point.

    Args:
        command: Command name (whoami)
        args: Command arguments

    Returns:
        True if command handled, False otherwise
    """
    if command == "whoami":
        result = _handle_whoami(args)
        if result:
            json_handler.log_operation("whoami_executed", {"command": "whoami", "success": True})
        return result
    return False


# =============================================================================
# DISPLAY HANDLERS
# =============================================================================

def _handle_whoami(args: List[str]) -> bool:
    """Detect and display the caller's branch identity."""
    try:
        branch_info = get_caller_branch()

        if not branch_info:
            warning("Could not detect your branch identity. Run from a branch directory.")
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
        console.print(f"[red]Error detecting identity:[/red] {e}")
        return True
