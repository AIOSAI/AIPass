# =================== AIPass ====================
# Name: config.py
# Description: Registry configuration management
# Version: 1.1.1
# Created: 2026-03-09
# Modified: 2026-10-24
# =============================================

"""
Registry configuration management.

Thin orchestrator that delegates to registry_handler for path resolution.
"""

import shlex
from typing import List, Optional

from aipass.prax import logger
from aipass.cli.apps.modules import console
from aipass.drone.apps.handlers.json import json_handler
from aipass.drone.apps.handlers.registry_handler import (
    get_registry_path,
    missing_home_tip,
    passport_fault,
    resolve_aipass_home,
    set_registry_path,
    reset_registry_path,
)
from aipass.drone.apps.handlers.help_flags import wants_help

__all__ = [
    "get_registry_path",
    "missing_home_tip",
    "passport_fault",
    "resolve_aipass_home",
    "set_registry_path",
    "reset_registry_path",
]


def print_introspection():
    """Display module introspection info."""
    try:
        from aipass.cli.apps.modules.display import console
    except ImportError:
        logger.warning("CLI console not available, using fallback")
        from rich.console import Console

        console = Console()

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
    from aipass.cli.apps.modules import console

    console.print("config — Registry configuration management")
    console.print()
    console.print("Commands:")
    console.print("  path                Show current registry path")
    console.print("  set <path>          Print the AIPASS_REGISTRY export that selects a registry")
    console.print("  reset               Print the unset that restores the default registry")
