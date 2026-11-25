# =================== AIPass ====================
# Name: config.py
# Description: Registry configuration management
# Version: 1.2.0
# Created: 2026-03-09
# Modified: 2026-11-17
# =============================================

"""
Registry configuration management.

Thin orchestrator that delegates to registry_handler for path resolution.
"""

import shlex
from typing import List, Optional

from aipass.prax import logger
from aipass.cli import console
from aipass.drone.apps.handlers.json import json_handler
from aipass.drone.apps.handlers import registry_handler
from aipass.drone.apps.handlers.registry_handler import get_registry_path
from aipass.drone.apps.handlers.help_flags import wants_help

__all__ = ["missing_home_tip", "passport_fault", "resolve_aipass_home"]


def resolve_aipass_home() -> "registry_handler.AipassHome":
    """The AIPass home and how it was found (``.path`` is None when none resolved)."""
    return registry_handler.resolve_aipass_home()


def missing_home_tip() -> str:
    """The tip printed under "Branch not found", or "" when an AIPass home resolved."""
    return registry_handler.missing_home_tip()


def passport_fault() -> Optional[str]:
    """The line naming a passport the credential checks could not read, or None."""
    return registry_handler.passport_fault()


def print_introspection():
    """Display module introspection info."""
    from aipass.cli import console

    console.print()
    console.print("[bold cyan]config Module[/bold cyan]")
    console.print("[dim]Registry configuration management — path resolution and overrides.[/dim]")
    console.print()
    console.print("[yellow]Connected Handlers:[/yellow]")
    console.print("  [cyan]handlers/[/cyan]")
    console.print(
        "    - [cyan]registry_handler.py[/cyan] [dim](get_registry_path — return current registry file path)[/dim]"
    )
    console.print(
        "    - [cyan]registry_handler.py[/cyan] [dim](set_registry_path — override registry file location)[/dim]"
    )
    console.print(
        "    - [cyan]registry_handler.py[/cyan] [dim](reset_registry_path — restore default registry path)[/dim]"
    )
    console.print()
    console.print("Run [green]'drone @drone config --help'[/green] for usage information")
    console.print()


def handle_command(command: Optional[str] = None, args: Optional[List[str]] = None) -> bool:
    """Route config commands (path, set, reset); True if the command succeeded."""
    if not args:
        if command is None:
            print_introspection()
            return True
        args = []
    if wants_help(command, args):
        print_help()
        return True
    json_handler.log_operation("handle_command", {"module": "config", "command": command})
    if command == "path":
        console.print(f"Registry path: {get_registry_path()}")
        return True
    # set/reset would change only this process, which exits at once: name the env var that persists.
    if command == "set":
        if not args:
            logger.warning("config set requires a path argument")
            return False
        console.print("config set does not persist across drone runs. To use this registry, run:")
        console.print(f"  export AIPASS_REGISTRY={shlex.quote(args[0])}", markup=False)
        return False
    if command == "reset":
        console.print("config reset does not persist across drone runs. To restore the default, run:")
        console.print("  unset AIPASS_REGISTRY")
        return False
    logger.warning("config: unknown command '%s'", command)
    return False


def print_help() -> None:
    """Print help for the config module."""
    from aipass.cli import console

    console.print("[bold cyan]config[/bold cyan] — Registry configuration management")
    console.print()
    console.print("[bold cyan]Usage:[/bold cyan]")
    console.print("  [dim]drone @drone config <command> \\[args][/dim]")
    console.print()
    console.print("[bold cyan]Commands:[/bold cyan]")
    console.print("  [cyan]path[/cyan]                Show current registry path")
    console.print("  [cyan]set[/cyan] <path>          Print the AIPASS_REGISTRY export that selects a registry")
    console.print("  [cyan]reset[/cyan]               Print the unset that restores the default registry")
    console.print()
    console.print("[bold cyan]Examples:[/bold cyan]")
    console.print("  [green]drone @drone config path[/green]")
