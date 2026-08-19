# =================== AIPass ====================
# Name: module_registry.py
# Description: Internal module registry for drone
# Version: 1.0.0
# Created: 2026-03-09
# Modified: 2026-03-09
# =============================================

"""
Internal module registry for drone.

Thin orchestrator that delegates all module registry operations
to the handler layer.
"""

from __future__ import annotations

from aipass.prax import logger
from aipass.cli.apps.modules import console
from aipass.drone.apps.handlers.json import json_handler
from aipass.drone.apps.handlers.module_registry_handler import (
    ModuleInfo,
    list_modules,
    is_module,
    get_module_info,
    route_module_command,
    get_module_help,
    get_module_introspective,
)
from aipass.drone.apps.handlers.help_flags import wants_help

__all__ = [
    "ModuleInfo",
    "list_modules",
    "is_module",
    "get_module_info",
    "route_module_command",
    "get_module_help",
    "get_module_introspective",
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
    console.print("[bold cyan]module_registry Module[/bold cyan]")
    console.print("[dim]Internal module registry for drone — dynamic module loading and command delegation.[/dim]")
    console.print()
    console.print("[yellow]Connected Handlers:[/yellow]")
    console.print("  [cyan]handlers/[/cyan]")
    console.print("    - [cyan]module_registry_handler.py[/cyan] [dim](ModuleInfo — module metadata dataclass)[/dim]")
    console.print(
        "    - [cyan]module_registry_handler.py[/cyan] [dim](list_modules — list registered module names)[/dim]"
    )
    console.print(
        "    - [cyan]module_registry_handler.py[/cyan] [dim](is_module — check if a module is registered)[/dim]"
    )
    console.print(
        "    - [cyan]module_registry_handler.py[/cyan] [dim](get_module_info — retrieve module metadata)[/dim]"
    )
    console.print(
        "    - [cyan]module_registry_handler.py[/cyan] [dim](route_module_command — delegate command to module)[/dim]"
    )
    console.print(
        "    - [cyan]module_registry_handler.py[/cyan] [dim](get_module_help — get help text for a module)[/dim]"
    )
    console.print(
        "    - [cyan]module_registry_handler.py[/cyan]"
        " [dim](get_module_introspective — introspect module adapter)[/dim]"
    )
    console.print()


def handle_command(command: str | None = None, args: list[str] | None = None) -> bool:
    """Route module registry commands to handler functions.

    Args:
        command: The command string (e.g. "list", "info", "register")
        args: List of arguments for the command

    Returns:
        True if command succeeded, False otherwise
    """
    if not args:
        if command is None:
            print_introspection()
            return True
        args = []
    if wants_help(command, args):
        print_help()
        return True
    json_handler.log_operation("handle_command", {"module": "module_registry", "command": command})
    if command == "list":
        modules = list_modules()
        for name in modules:
            info = get_module_info(name)
            if info:
                console.print(f"  @{name:<18} {info.description}")
            else:
                console.print(f"  @{name:<18} (not available)")
        return True
    if command == "info":
        if not args:
            logger.warning("module_registry info requires a module name")
            return False
        info = get_module_info(args[0])
        if info:
            console.print(f"Module: {info.name} v{info.version} — {info.description}")
        else:
            logger.warning("Module '%s' not found", args[0])
            return False
        return True
    if command == "check":
        if not args:
            logger.warning("module_registry check requires a module name")
            return False
        console.print(f"Module '{args[0]}' registered: {is_module(args[0])}")
        return True
    logger.warning("module_registry: unknown command '%s'", command)
    return False


def print_help() -> None:
    """Print help for the module_registry module."""
    from aipass.cli.apps.modules import console

    console.print("module_registry — Internal module registry for drone")
    console.print()
    console.print("Commands:")
    console.print("  list                List registered modules")
    console.print("  info <name>         Show module metadata")
    console.print("  check <name>        Check if module is registered")
