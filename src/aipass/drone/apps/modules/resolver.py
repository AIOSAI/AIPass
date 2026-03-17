# =================== AIPass ====================
# Name: resolver.py
# Description: Branch resolution logic for symbolic @branch names
# Version: 1.0.0
# Created: 2026-03-09
# Modified: 2026-03-09
# =============================================

"""
Branch resolution logic.

Thin orchestrator for resolving symbolic @branch names to paths and metadata.
Delegates registry access to the handler layer.
"""

from typing import Any, Dict, List, Optional

from aipass.prax import logger
from aipass.prax.apps.modules.logger import system_logger
from aipass.drone.apps.handlers.exceptions import BranchNotFoundError
from aipass.drone.apps.handlers.json import json_handler
from aipass.drone.apps.handlers.registry_handler import (
    load_registry,
    get_all_branches,
    get_branch_by_name,
)


def handle_command(command: Optional[str] = None, args: Optional[List[str]] = None) -> bool:
    """Route resolver commands to handler functions.

    Args:
        command: The command string (e.g. "resolve", "exists", "info", "list")
        args: List of arguments for the command

    Returns:
        True if command succeeded, False otherwise
    """
    if not args:
        if command is None:
            print_introspection()
            return True
        args = []
    json_handler.log_operation("handle_command", {"module": "resolver", "command": command})
    if command == "resolve":
        if not args:
            logger.warning("resolver resolve requires a branch name")
            return False
        path = resolve_branch(args[0])
        logger.info("%s -> %s", args[0], path)
        return True
    if command == "exists":
        if not args:
            logger.warning("resolver exists requires a branch name")
            return False
        logger.info("%s exists: %s", args[0], branch_exists(args[0]))
        return True
    if command == "info":
        if not args:
            logger.warning("resolver info requires a branch name")
            return False
        info = get_branch_info(args[0])
        logger.info("Branch info: %s", info)
        return True
    if command == "list":
        branches = list_branches()
        for name in branches:
            logger.info("  %s", name)
        return True
    logger.warning("resolver: unknown command '%s'", command)
    return False


def print_help() -> None:
    """Print help for the resolver module."""
    from aipass.cli.apps.modules import console

    console.print("resolver — Branch resolution logic")
    console.print()
    console.print("Commands:")
    console.print("  resolve <branch>    Resolve branch name to path")
    console.print("  exists <branch>     Check if branch exists")
    console.print("  info <branch>       Get branch metadata")
    console.print("  list                List all branches")


def print_introspection():
    """Display module introspection info."""
    try:
        from aipass.cli.apps.modules.display import console
    except ImportError:
        from rich.console import Console
        console = Console()

    console.print()
    console.print("resolver Module")
    console.print("Branch resolution logic — resolves symbolic @branch names to paths and metadata.")
    console.print()
    console.print("Connected Handlers:")
    console.print("  handlers/")
    console.print("    - registry_handler.py (load_registry — load and parse AIPASS_REGISTRY.json)")
    console.print("    - registry_handler.py (get_all_branches — list branches with optional filters)")
    console.print("    - registry_handler.py (get_branch_by_name — look up a single branch)")
    console.print("    - exceptions.py (BranchNotFoundError — raised when branch not in registry)")
    console.print()


def normalize_branch_name(symbolic_name: str) -> str:
    """Normalize a symbolic branch name. Strips @ prefix if present."""
    if symbolic_name.startswith("@"):
        return symbolic_name[1:]
    return symbolic_name


def normalize_branch_arg(target: str) -> str:
    """Normalize @branch argument: strip @ prefix, lowercase."""
    return target.lstrip("@").lower()


def resolve_branch(symbolic_name: str) -> str:
    """Resolve a symbolic branch name to its absolute path.

    Args:
        symbolic_name: Branch name with or without @ prefix

    Returns:
        Absolute path to branch directory as string

    Raises:
        BranchNotFoundError: If branch not in registry
        RegistryNotFoundError: If registry file missing
    """
    registry = load_registry()

    name = normalize_branch_name(symbolic_name).lower()
    branch = registry.get("branches", {}).get(name)

    if branch is None:
        raise BranchNotFoundError(
            f"Branch '{symbolic_name}' not found in registry"
        )

    system_logger.info("Resolved @%s → %s", name, branch["path"])
    return branch["path"]


def branch_exists(symbolic_name: str) -> bool:
    """Check if a branch exists in the registry."""
    name = normalize_branch_name(symbolic_name).lower()
    branch = get_branch_by_name(name)
    return branch is not None


def get_branch_info(symbolic_name: str) -> Dict[str, Any]:
    """Get full metadata for a branch.

    Raises:
        BranchNotFoundError: If branch not in registry
    """
    registry = load_registry()

    name = normalize_branch_name(symbolic_name).lower()
    branch = registry.get("branches", {}).get(name)

    if branch is None:
        raise BranchNotFoundError(
            f"Branch '{symbolic_name}' not found in registry"
        )

    return branch


def list_branches(
    branch_type: Optional[str] = None,
    status: str = "active",
) -> List[str]:
    """List all registered branches, optionally filtered by type and status.

    Returns:
        List of branch names with @ prefix
    """
    branches = get_all_branches(branch_type=branch_type, status=status)
    return [f"@{branch['name']}" for branch in branches]
