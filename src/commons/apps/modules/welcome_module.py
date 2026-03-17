# =================== AIPass ====================
# Name: welcome_module.py
# Description: Welcome Orchestration Module
# Version: 1.0.0
# Created: 2026-03-07
# Modified: 2026-03-07
# =============================================

"""
Welcome & Onboarding Orchestration Module

Thin router for the welcome command. Delegates logic
to handlers/welcome/welcome_ops.py and renders results with Rich.

Handles: welcome command.
"""

from typing import List

from aipass.prax.apps.modules.logger import system_logger as logger

try:
    from aipass.cli.apps.modules import console
except ImportError:
    from rich.console import Console
    console = Console()

from commons.apps.handlers.welcome.welcome_ops import run_welcome
from commons.apps.handlers.json import json_handler


def print_introspection():
    """Display module introspection info."""
    console.print()
    console.print("welcome_module Module")
    console.print("Thin router for the welcome command. Scans for new branches and creates welcome posts.")
    console.print()
    console.print("Connected Handlers:")
    console.print("  handlers/welcome/")
    console.print("    - welcome_ops.py (run_welcome — scan for new branches and post welcome messages)")
    console.print()


# =============================================================================
# COMMAND ROUTING
# =============================================================================

def handle_command(command: str, args: List[str]) -> bool:
    """
    Handle welcome-related commands.

    Args:
        command: Command name (welcome)
        args: Command arguments

    Returns:
        True if command handled, False otherwise
    """
    if command != "welcome":
        return False

    return _handle_welcome(args)


# =============================================================================
# DISPLAY HANDLER
# =============================================================================

def _handle_welcome(args: List[str]) -> bool:
    """Run welcome and display results."""
    result = run_welcome(args)

    if not result["success"]:
        console.print(f"[red]{result['error']}[/red]")
        return True

    console.print()

    if result["action"] == "scan":
        welcomed = result["welcomed"]
        console.print("[bold cyan]Checking for new branches to welcome...[/bold cyan]")
        console.print()

        if welcomed:
            for name in welcomed:
                console.print(f"  Welcome post created for: [green]@{name}[/green]")
            console.print()
            console.print(f"[bold]{len(welcomed)} new branch(es) welcomed![/bold]")
        else:
            console.print("  [dim]All branches have been welcomed already.[/dim]")

    elif result["action"] == "specific":
        branch = result["branch"]
        if result.get("already_welcomed"):
            console.print(f"  [dim]@{branch} has already been welcomed.[/dim]")
        else:
            console.print(f"  Welcome post created for: [green]@{branch}[/green]")

    console.print()

    json_handler.log_operation("welcome_executed", {"command": "welcome", "success": True})
    return True
