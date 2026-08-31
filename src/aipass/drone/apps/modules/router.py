# =================== AIPass ====================
# Name: router.py
# Description: Command routing logic for the drone module
# Version: 1.0.2
# Created: 2026-03-09
# Modified: 2026-08-31
# =============================================

"""
Command routing logic for the AIPass drone module.

Thin orchestrator that resolves targets and delegates execution
to the handler layer.
"""

import sys
from typing import Dict, List, Optional

from aipass.prax.apps.modules.logger import system_logger
from aipass.cli.apps.modules import console
from aipass.drone.apps.handlers.executor import CommandResult, resolve_timeout
from aipass.drone.apps.handlers.json import json_handler
from aipass.drone.apps.handlers.router_handler import (
    execute_branch_command,
    caller_cwd,
    # Re-exported, not used here: apps/drone.py reaches handlers through this
    # module rather than importing them directly (the same route caller_cwd
    # already takes), so the entry point keeps one seam into the handler layer.
    registries_in,  # noqa: F401
    resolve_caller_identity,
)
from .resolver import list_branches, resolve_branch
from aipass.drone.apps.handlers.help_flags import wants_help

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
    from aipass.cli.apps.modules import console

    console.print("router — Command routing logic")
    console.print()
    console.print("Commands:")
    console.print("  route <target> <cmd> \\[args]   Route command to a branch")
    console.print("  route_all <cmd> \\[args]        Route command to all branches")


def route_command(
    target: str,
    command: Optional[str] = None,
    args: Optional[List[str]] = None,
    timeout: int | None = None,
    interactive: bool = False,
) -> CommandResult:
    """Route a command to a branch's entry point.

    Resolves @target to a path, then delegates to the handler for execution.
    When command is None, runs the branch with no args (introspection).

    Timeout resolution: explicit value > per-command policy > DEFAULT_TIMEOUT.

    Output-extends-life applies only when NOBODY named a number. ``timeout`` is
    None exactly when the operator left it alone, which makes this the one place
    that can tell "the system's generous default" from "the operator's cap" — the
    handler below sees only an integer. An explicit ``--drone-timeout N`` means
    exactly N: extension would turn a deliberate tight cap into an unpredictable
    one, and an operator who asks for 5 seconds is usually probing, not waiting.
    """
    branch_path = resolve_branch(target)
    branch_name = target.lstrip("@").lower()
    resolved_timeout = resolve_timeout(branch_name, command, timeout)
    extend_on_output = timeout is None

    # Same resolver execute_branch_command uses — logging its own precedence
    # here would let the CALLER: tag name someone other than the branch actually
    # stamped on the work.
    caller = resolve_caller_identity(caller_cwd())
    # UNKNOWN, not an empty tag: an omitted caller reads as "not applicable" and
    # hides the gap. detect_caller_signal already logged the cwd.
    caller_tag = f" [CALLER:{caller.upper()}]" if caller else " [CALLER:UNKNOWN]"
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
    try:
        from aipass.cli.apps.modules.display import console
    except ImportError:
        logger.warning("CLI console not available, using fallback")
        from rich.console import Console

        console = Console()

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
