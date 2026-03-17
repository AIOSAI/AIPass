# =================== AIPass ====================
# Name: router.py
# Description: Command routing logic for the drone module
# Version: 1.0.0
# Created: 2026-03-09
# Modified: 2026-03-09
# =============================================

"""
Command routing logic for the AIPass drone module.

Thin orchestrator that resolves targets and delegates execution
to the handler layer.
"""

from typing import Dict, List, Optional

from aipass.prax import logger
from aipass.prax.apps.modules.logger import system_logger
from aipass.drone.apps.handlers.executor import CommandResult
from aipass.drone.apps.handlers.json import json_handler
from aipass.drone.apps.handlers.router_handler import execute_branch_command
from .resolver import list_branches, resolve_branch

logger = system_logger


def handle_command(command: Optional[str] = None, args: Optional[List[str]] = None) -> bool:
    """Route router commands to handler functions.

    Args:
        command: The command string (e.g. "route", "route_all")
        args: List of arguments for the command

    Returns:
        True if command succeeded, False otherwise
    """
    if not args:
        if command is None:
            print_introspection()
            return True
        args = []
    json_handler.log_operation("handle_command", {"module": "router", "command": command})
    if command == "route":
        if len(args) < 2:
            logger.warning("router route requires <target> <command> [args...]")
            return False
        target = args[0]
        cmd = args[1]
        cmd_args = args[2:] if len(args) > 2 else None
        result = route_command(target, cmd, args=cmd_args)
        if result.stdout:
            logger.info("%s", result.stdout)
        return result.exit_code == 0
    if command == "route_all":
        if not args:
            logger.warning("router route_all requires a command argument")
            return False
        cmd = args[0]
        cmd_args = args[1:] if len(args) > 1 else None
        results = route_all(cmd, args=cmd_args)
        for name, result in results.items():
            logger.info("%s: exit_code=%d", name, result.exit_code)
        return all(r.exit_code == 0 for r in results.values())
    logger.warning("router: unknown command '%s'", command)
    return False


def print_help() -> None:
    """Print help for the router module."""
    from aipass.cli.apps.modules import console

    console.print("router — Command routing logic")
    console.print()
    console.print("Commands:")
    console.print("  route <target> <cmd> [args]   Route command to a branch")
    console.print("  route_all <cmd> [args]        Route command to all branches")


def route_command(
    target: str,
    command: Optional[str] = None,
    args: Optional[List[str]] = None,
    timeout: int = 30,
    interactive: bool = False,
) -> CommandResult:
    """Route a command to a branch's entry point.

    Resolves @target to a path, then delegates to the handler for execution.
    When command is None, runs the branch with no args (introspection).
    """
    branch_path = resolve_branch(target)
    branch_name = target.lstrip("@").lower()

    logger.info("Routing @%s → %s %s", branch_name, command or "(introspection)", args or [])
    return execute_branch_command(
        branch_path=branch_path,
        branch_name=branch_name,
        command=command,
        args=args,
        timeout=timeout,
        interactive=interactive,
    )


def print_introspection():
    """Display module introspection info."""
    try:
        from aipass.cli.apps.modules.display import console
    except ImportError:
        from rich.console import Console
        console = Console()

    console.print()
    console.print("router Module")
    console.print("Command routing logic for the AIPass drone module.")
    console.print()
    console.print("Connected Handlers:")
    console.print("  handlers/")
    console.print("    - router_handler.py (execute_branch_command — resolves and executes branch commands)")
    console.print("    - executor.py (CommandResult — subprocess execution result dataclass)")
    console.print()
    console.print("Connected Modules:")
    console.print("  modules/")
    console.print("    - resolver.py (resolve_branch, list_branches — branch name resolution)")
    console.print()


def route_all(
    command: str,
    args: Optional[List[str]] = None,
    timeout: int = 30,
) -> Dict[str, CommandResult]:
    """Route the same command to ALL active branches in the registry."""
    if args is None:
        args = []

    results: Dict[str, CommandResult] = {}
    active_branches = list_branches(status="active")

    for symbolic_name in active_branches:
        branch_name = symbolic_name.lstrip("@")
        try:
            result = route_command(symbolic_name, command, args=list(args), timeout=timeout)
            results[branch_name] = result
        except Exception as exc:
            logger.warning(
                "route_all: branch '%s' failed for command '%s': %s",
                branch_name, command, exc,
            )
            results[branch_name] = CommandResult(
                stdout="",
                stderr=str(exc),
                exit_code=-1,
                branch=branch_name,
                command=command,
            )

    return results
