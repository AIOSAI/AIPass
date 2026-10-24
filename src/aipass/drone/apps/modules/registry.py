# =================== AIPass ====================
# Name: registry.py
# Description: Registry operations for branch management
# Version: 1.0.2
# Created: 2026-03-09
# Modified: 2026-10-23
# =============================================

"""
Registry operations for branch management.
"""

from typing import List, Optional

from aipass.prax import logger
from aipass.drone.apps.handlers.exceptions import RegistryError, RegistryMismatchError
from aipass.drone.apps.handlers.json import json_handler
from aipass.drone.apps.handlers.registry_handler import (
    get_registry_path,
    load_registry,
    get_all_branches,
    get_branch_by_name,
)
from aipass.drone.apps.handlers.help_flags import wants_help
from aipass.drone.apps.modules.resolver import normalize_branch_name

# Public contract: path and error types live here too, so callers never reach into the handler.
__all__ = [
    "load_registry",
    "get_all_branches",
    "get_branch_by_name",
    "get_registry_path",
    "RegistryError",
    "RegistryMismatchError",
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
    console.print("[bold cyan]registry Module[/bold cyan]")
    console.print("[dim]Registry operations for branch management — loading and querying AIPASS_REGISTRY.json.[/dim]")
    console.print()
    console.print("[yellow]Connected Handlers:[/yellow]")
    console.print("  [cyan]handlers/[/cyan]")
    console.print(
        "    - [cyan]registry_handler.py[/cyan] [dim](load_registry — load and parse the registry file)[/dim]"
    )
    console.print(
        "    - [cyan]registry_handler.py[/cyan] [dim](get_all_branches — list branches with type/status filters)[/dim]"
    )
    console.print(
        "    - [cyan]registry_handler.py[/cyan] [dim](get_branch_by_name — look up a single branch by name)[/dim]"
    )
    console.print()


def handle_command(command: Optional[str] = None, args: Optional[List[str]] = None) -> bool:
    """Route registry commands to handler functions."""
    if not args:
        if command is None:
            print_introspection()
            return True
        args = []
    if wants_help(command, args):
        print_help()
        return True
    json_handler.log_operation("handle_command", {"module": "registry", "command": command})
    if command == "load":
        registry = load_registry()
        branch_count = len(registry.get("branches", {}))
        logger.info("Registry loaded: %d branches", branch_count)
        return True
    if command == "branches":
        branch_type = args[0] if args else None
        branches = get_all_branches(branch_type=branch_type)
        for branch in branches:
            logger.info("  %s", branch.get("name", "unknown"))
        return True
    if command == "lookup":
        if not args:
            logger.warning("registry lookup requires a branch name")
            return False
        branch = get_branch_by_name(normalize_branch_name(args[0]))
        if branch:
            logger.info("Branch: %s", branch)
        else:
            logger.warning("Branch '%s' not found", args[0])
            return False
        return True
    logger.warning("registry: unknown command '%s'", command)
    return False


def print_help() -> None:
    """Print help for the registry module."""
    from aipass.cli.apps.modules import console

    console.print("registry — Registry operations for branch management")
    console.print()
    console.print("Commands:")
    console.print("  load                Load and show registry stats")
    console.print("  branches \\[type]     List branches, optionally by type")
    console.print("  lookup <name>       Look up a specific branch")
