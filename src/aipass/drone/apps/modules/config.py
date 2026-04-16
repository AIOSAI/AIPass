# =================== AIPass ====================
# Name: config.py
# Description: Registry configuration management
# Version: 1.0.0
# Created: 2026-03-09
# Modified: 2026-03-09
# =============================================

"""
Registry configuration management.

Thin orchestrator that delegates to registry_handler for path resolution.
"""

from typing import List, Optional

from aipass.prax import logger
from aipass.cli.apps.modules import console
from aipass.drone.apps.handlers.json import json_handler
from aipass.drone.apps.handlers.registry_handler import (
    get_registry_path,
    set_registry_path,
    reset_registry_path,
)

__all__ = ["get_registry_path", "set_registry_path", "reset_registry_path"]


def print_introspection():
    """Display module introspection info."""
    try:
        from aipass.cli.apps.modules.display import console
    except ImportError:
        logger.warning("CLI console not available, using fallback")
        from rich.console import Console

        console = Console()

    console.print()
    console.print("config Module")
    console.print("Registry configuration management — path resolution and overrides.")
    console.print()
    console.print("Connected Handlers:")
    console.print("  handlers/")
    console.print("    - registry_handler.py (get_registry_path — return current registry file path)")
    console.print("    - registry_handler.py (set_registry_path — override registry file location)")
    console.print("    - registry_handler.py (reset_registry_path — restore default registry path)")
    console.print()


def handle_command(command: Optional[str] = None, args: Optional[List[str]] = None) -> bool:
    """Route config commands to handler functions.

    Args:
        command: The command string (e.g. "path", "set", "reset")
        args: List of arguments for the command

    Returns:
        True if command succeeded, False otherwise
    """
    if not args:
        if command is None:
            print_introspection()
            return True
        args = []
    if command in ("--help", "-h") or (args and args[0] in ("--help", "-h")):
        print_help()
        return True
    json_handler.log_operation("handle_command", {"module": "config", "command": command})
    if command == "path":
        console.print(f"Registry path: {get_registry_path()}")
        return True
    if command == "set":
        if not args:
            logger.warning("config set requires a path argument")
            return False
        set_registry_path(args[0])
        console.print(f"Registry path set to: {args[0]}")
        return True
    if command == "reset":
        reset_registry_path()
        console.print("Registry path reset to default")
        return True
    logger.warning("config: unknown command '%s'", command)
    return False


def print_help() -> None:
    """Print help for the config module."""
    from aipass.cli.apps.modules import console

    console.print("config — Registry configuration management")
    console.print()
    console.print("Commands:")
    console.print("  path                Show current registry path")
    console.print("  set <path>          Set custom registry path")
    console.print("  reset               Reset registry path to default")
