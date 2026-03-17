# =================== AIPass ====================
# Name: discovery.py
# Description: Module and command discovery for branch introspection
# Version: 1.0.0
# Created: 2026-03-09
# Modified: 2026-03-09
# =============================================

"""
Module and command discovery for AIPass branch introspection.

Thin orchestrator that delegates all discovery logic to the handler layer.
"""

from typing import Dict, List, Optional

from aipass.prax import logger
from aipass.drone.apps.handlers.discovery_handler import HelpResult
from aipass.drone.apps.handlers.json import json_handler
from .resolver import list_branches, resolve_branch


def handle_command(command: Optional[str] = None, args: Optional[List[str]] = None) -> bool:
    """Route discovery commands to handler functions.

    Args:
        command: The command string (e.g. "modules", "help", "system")
        args: List of arguments for the command

    Returns:
        True if command succeeded, False otherwise
    """
    if not args:
        if command is None:
            print_introspection()
            return True
        args = []
    json_handler.log_operation("handle_command", {"module": "discovery", "command": command})
    if command == "modules":
        if not args:
            logger.warning("discovery modules requires a target argument")
            return False
        modules = discover_modules(args[0])
        for mod in modules:
            logger.info("  %s", mod)
        return True
    if command == "help":
        if not args:
            logger.warning("discovery help requires a target argument")
            return False
        target = args[0]
        cmd = args[1] if len(args) > 1 else None
        result = get_help(target, cmd)
        logger.info("%s", result.text)
        return True
    if command == "system":
        results = get_system_help()
        for name, result in results.items():
            logger.info("%s: %s", name, result.text[:80])
        return True
    logger.warning("discovery: unknown command '%s'", command)
    return False


def print_help() -> None:
    """Print help for the discovery module."""
    from aipass.cli.apps.modules import console

    console.print("discovery — Module and command discovery")
    console.print()
    console.print("Functions:")
    console.print("  discover_modules(target)           List available commands for a branch")
    console.print("  get_help(target, command=None)      Get structured help for a branch/command")
    console.print("  get_system_help()                   Aggregate help across all active branches")
    console.print()
    console.print("Usage via drone:")
    console.print("  drone @branch --help               Show help for a branch")
    console.print("  drone systems                      List all registered branches")


def print_introspection():
    """Display module introspection info."""
    try:
        from aipass.cli.apps.modules.display import console
    except ImportError:
        from rich.console import Console
        console = Console()

    console.print()
    console.print("discovery Module")
    console.print("Module and command discovery for AIPass branch introspection.")
    console.print()
    console.print("Connected Handlers:")
    console.print("  handlers/")
    console.print("    - discovery_handler.py (HelpResult — structured help query result)")
    console.print("    - discovery_handler.py (discover_modules — list available commands for a branch)")
    console.print("    - discovery_handler.py (get_help — get structured help for a branch/command)")
    console.print("    - discovery_handler.py (get_system_help — aggregate help across all branches)")
    console.print()
    console.print("Connected Modules:")
    console.print("  modules/")
    console.print("    - resolver.py (resolve_branch, list_branches — branch name resolution)")
    console.print()


def discover_modules(target: str) -> List[str]:
    """Discover available commands for a branch.

    Resolves target to path and delegates to handler.
    """
    from aipass.drone.apps.handlers.discovery_handler import (
        discover_modules as _discover,
    )

    branch_path = resolve_branch(target)
    branch_name = target.lstrip("@").lower()
    return _discover(branch_path, branch_name)


def get_help(target: str, command: Optional[str] = None) -> HelpResult:
    """Get structured help for a branch or a specific command.

    Resolves target to path and delegates to handler.
    """
    from aipass.drone.apps.handlers.discovery_handler import (
        get_help as _get_help,
    )

    branch_path = resolve_branch(target)
    branch_name = target.lstrip("@").lower()
    return _get_help(branch_path, branch_name, command)


def get_system_help() -> Dict[str, HelpResult]:
    """Aggregate help across all active branches in the registry."""
    from aipass.drone.apps.handlers.discovery_handler import (
        get_system_help as _get_system_help,
    )

    active_branches = list_branches(status="active")
    return _get_system_help(active_branches)
