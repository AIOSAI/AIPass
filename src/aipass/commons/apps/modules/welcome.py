# =================== AIPass ====================
# Name: welcome.py
# Description: Welcome Orchestration Module
# Version: 1.0.1
# Created: 2026-03-07
# Modified: 2026-11-26
# =============================================

"""Welcome & Onboarding Orchestration Module"""

from typing import List

from aipass.prax import logger  # noqa: F401 - the imports standard requires the prax logger in every module
from aipass.cli import console, error

from aipass.commons.apps.handlers.welcome.welcome_ops import run_welcome
from aipass.commons.apps.handlers.json import json_handler


def print_introspection():
    """Display module introspection info."""
    console.print()
    console.print("[bold cyan]welcome - Welcome & Onboarding[/bold cyan]")
    console.print("[dim]Thin router for the welcome command. Scans for new branches and creates welcome posts.[/dim]")
    console.print()
    console.print("[bold cyan]Connected Handlers:[/bold cyan]")
    console.print("  [cyan]handlers/welcome/[/cyan]")
    console.print(
        "    [cyan]-[/cyan] welcome_ops.py [dim](run_welcome — scan for new branches and post welcome messages)[/dim]"
    )
    console.print()
    console.print("[dim]Run 'drone @commons welcome --help' for usage[/dim]")


def print_help():
    """Display usage help for the welcome module."""
    console.print()
    console.print("[bold cyan]welcome - Welcome & Onboarding[/bold cyan]")
    console.print("[dim]Welcome new branches with a post, or preview who would be welcomed.[/dim]")
    console.print()
    console.print("[bold cyan]Usage:[/bold cyan]")
    console.print("  [cyan]drone @commons welcome[/cyan] \\[branch] \\[--dry-run]")
    console.print()
    console.print("[bold cyan]Examples:[/bold cyan]")
    console.print("  [cyan]drone @commons welcome[/cyan]")
    console.print("  [cyan]drone @commons welcome seedgo --dry-run[/cyan]")
    console.print()


def handle_command(command: str, args: List[str]) -> bool:
    """Handle welcome-related commands; False if the command is not ours."""
    if command != "welcome":
        return False

    if "--help" in args or "-h" in args:
        print_help()
        return True

    return _handle_welcome(args)


def _handle_welcome(args: List[str]) -> bool:
    """Run welcome and display results."""
    result = run_welcome(args)

    if not result["success"]:
        error(result["error"])
        return True

    if result.get("dry_run"):
        console.print()
        console.print("[bold cyan][DRY RUN] Welcome preview:[/bold cyan]")
        would = result.get("would_welcome", [])
        if isinstance(would, list):
            if would:
                for name in would:
                    console.print(f"  Would welcome: [green]@{name}[/green]")
            else:
                console.print("  [dim]All branches have been welcomed already.[/dim]")
        elif isinstance(would, bool):
            branch = result.get("branch", "unknown")
            if would:
                console.print(f"  Would welcome: [green]@{branch}[/green]")
            else:
                console.print(f"  [dim]@{branch} has already been welcomed.[/dim]")
        console.print()
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
