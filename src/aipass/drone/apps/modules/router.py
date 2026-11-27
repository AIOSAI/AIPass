# =================== AIPass ====================
# Name: router.py
# Description: Command routing logic for the drone module
# Version: 1.0.5
# Created: 2026-03-09
# Modified: 2026-11-26
# =============================================

"""
Command routing logic for the AIPass drone module.
"""

import sys
from typing import Dict, List, Optional

from aipass.prax import logger as system_logger
from aipass.cli import console
from aipass.drone.apps.handlers.executor import CommandResult, resolve_timeout
from aipass.drone.apps.handlers.json import json_handler
from aipass.drone.apps.handlers.router_handler import (
    execute_branch_command,
    caller_seat,
    # Re-exported for apps/drone.py: the entry point keeps one seam into handlers.
    caller_cwd,  # noqa: F401
    registry_named_entries,  # noqa: F401
    resolve_caller_identity,
)
from .resolver import list_branches, resolve_branch
from aipass.drone.apps.handlers.help_flags import wants_help

logger = system_logger


def handle_command(command: Optional[str] = None, args: Optional[List[str]] = None) -> bool:
    """Route router commands to handler functions."""
    if not args:
        if command is None:
            print_introspection()
            return True
        args = []
    if wants_help(command, args):
        print_help()
        return True
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
            sys.stdout.write(result.stdout)
        return result.exit_code == 0
    if command == "route_all":
        if not args:
            logger.warning("router route_all requires a command argument")
            return False
        cmd = args[0]
        cmd_args = args[1:] if len(args) > 1 else None
        results = route_all(cmd, args=cmd_args)
        for name, result in results.items():
            console.print(f"{name}: exit_code={result.exit_code}")
        return all(r.exit_code == 0 for r in results.values())
    logger.warning("router: unknown command '%s'", command)
    return False


def print_help() -> None:
    """Print help for the router module."""
    from aipass.cli import console

    console.print("[bold cyan]router[/bold cyan] — Command routing logic")
    console.print()
    console.print("[bold cyan]Usage:[/bold cyan]")
    console.print("  [dim]drone @drone router <command> <target> <cmd> \\[args][/dim]")
    console.print()
    console.print("[bold cyan]Commands:[/bold cyan]")
    console.print("  [cyan]route[/cyan] <target> <cmd> \\[args]   Route command to a branch")
    console.print("  [cyan]route_all[/cyan] <cmd> \\[args]        Route command to all branches")
    console.print()
    console.print("[bold cyan]Examples:[/bold cyan]")
    console.print("  [green]drone @drone router route flow --help[/green]")


def route_command(
    target: str,
    command: Optional[str] = None,
    args: Optional[List[str]] = None,
    timeout: int | None = None,
    interactive: bool = False,
) -> CommandResult:
    """Route a command to a branch's entry point.

    Output-extends-life applies only when ``timeout`` is None: this is the one place
    that can tell the default from an operator's cap, which means exactly N.
    """
    branch_path = resolve_branch(target)
    branch_name = target.lstrip("@").lower()
    resolved_timeout = resolve_timeout(branch_name, command, timeout)
    extend_on_output = timeout is None

    # Same resolver execute_branch_command uses, so the tag names who is stamped on the work.
    caller = resolve_caller_identity(caller_seat())
    # UNKNOWN, not an empty tag: an omitted caller hides the gap.
    caller_tag = f" [CALLER:{caller}]" if caller else " [CALLER:UNKNOWN]"
    logger.info(
        "Routing @%s%s → %s %s (timeout=%ds, extend_on_output=%s)",
        branch_name,
        caller_tag,
        command or "(introspection)",
        args or [],
        resolved_timeout,
        extend_on_output,
    )
    return execute_branch_command(
        branch_path=branch_path,
        branch_name=branch_name,
        command=command,
        args=args,
        timeout=resolved_timeout,
        interactive=interactive,
        extend_on_output=extend_on_output,
    )


def print_introspection():
    """Display module introspection info."""
    from aipass.cli import console

    console.print()
    console.print("[bold cyan]router Module[/bold cyan]")
    console.print("[dim]Command routing logic for the AIPass drone module.[/dim]")
    console.print()
    console.print("[yellow]Connected Handlers:[/yellow]")
    console.print("  [cyan]handlers/[/cyan]")
    console.print(
        "    - [cyan]router_handler.py[/cyan] "
        "[dim](execute_branch_command — resolves and executes branch commands)[/dim]"
    )
    console.print("    - [cyan]executor.py[/cyan] [dim](CommandResult — subprocess execution result dataclass)[/dim]")
    console.print()
    console.print("[yellow]Connected Modules:[/yellow]")
    console.print("  [cyan]modules/[/cyan]")
    console.print("    - [cyan]resolver.py[/cyan] [dim](resolve_branch, list_branches — branch name resolution)[/dim]")
    console.print()
    console.print("Run [green]'drone @drone router --help'[/green] for usage information")
    console.print()


def route_all(
    command: str,
    args: Optional[List[str]] = None,
    timeout: int | None = None,
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
                branch_name,
                command,
                exc,
            )
            results[branch_name] = CommandResult(
                stdout="",
                stderr=str(exc),
                exit_code=-1,
                branch=branch_name,
                command=command,
            )

    return results
