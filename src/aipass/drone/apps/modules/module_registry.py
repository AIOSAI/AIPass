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
from aipass.drone.apps.handlers.json import json_handler
from aipass.drone.apps.handlers.module_registry_handler import (
    ModuleInfo,
    list_modules,
    is_module,
    get_module_info,
    route_module_command,
    get_module_help,
    get_module_introspective,
    register_module,
)

__all__ = [
    "ModuleInfo",
    "list_modules",
    "is_module",
    "get_module_info",
    "route_module_command",
    "get_module_help",
    "get_module_introspective",
    "register_module",
]


def print_introspection():
    """Display module introspection info."""
    try:
        from aipass.cli.apps.modules.display import console
    except ImportError:
        from rich.console import Console
        console = Console()

    console.print()
    console.print("module_registry Module")
    console.print("Internal module registry for drone — dynamic module loading and command delegation.")
    console.print()
    console.print("Connected Handlers:")
    console.print("  handlers/")
    console.print("    - module_registry_handler.py (ModuleInfo — module metadata dataclass)")
    console.print("    - module_registry_handler.py (list_modules — list registered module names)")
    console.print("    - module_registry_handler.py (is_module — check if a module is registered)")
    console.print("    - module_registry_handler.py (get_module_info — retrieve module metadata)")
    console.print("    - module_registry_handler.py (route_module_command — delegate command to module)")
    console.print("    - module_registry_handler.py (get_module_help — get help text for a module)")
    console.print("    - module_registry_handler.py (get_module_introspective — introspect module adapter)")
    console.print("    - module_registry_handler.py (register_module — register a new module adapter)")
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
    json_handler.log_operation("handle_command", {"module": "module_registry", "command": command})
    if command == "list":
        modules = list_modules()
        for name in modules:
            info = get_module_info(name)
            if info:
                logger.info("  @%-18s %s", name, info.description)
            else:
                logger.info("  @%-18s (not available)", name)
        return True
    if command == "info":
        if not args:
            logger.warning("module_registry info requires a module name")
            return False
        info = get_module_info(args[0])
        if info:
            logger.info("Module: %s v%s — %s", info.name, info.version, info.description)
        else:
            logger.warning("Module '%s' not found", args[0])
            return False
        return True
    if command == "check":
        if not args:
            logger.warning("module_registry check requires a module name")
            return False
        logger.info("Module '%s' registered: %s", args[0], is_module(args[0]))
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
