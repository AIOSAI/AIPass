# =================== AIPass ====================
# Name: scan.py
# Description: Module orchestrator for branch command scanning
# Version: 1.0.2
# Created: 2026-03-17
# Modified: 2026-11-15
# =============================================

"""Module orchestrator for branch command scanning.

Thin orchestrator that resolves ``@target`` to a branch path and delegates
scanning to the handler layer.  Displays results via Rich formatters.
"""

from __future__ import annotations

from aipass.prax import logger
from aipass.drone.apps.handlers.json import json_handler
from aipass.drone.apps.handlers.scanning.scanner import scan_branch
from aipass.drone.apps.handlers.scanning.formatters import (
    format_help_scan_failure,
    format_no_commands,
    format_scan_results,
)
from aipass.drone.apps.modules.resolver import resolve_branch
from aipass.drone.apps.handlers.help_flags import wants_help

__all__ = [
    "handle_command",
    "print_help",
    "print_introspection",
    "scan",
]


def handle_command(command: str | None = None, args: list[str] | None = None) -> bool:
    """Route scan subcommands to handler functions.

    Scans are positional: *command* is unused and ``args[0]`` is the ``@target``.
    """
    if not args:
        if command is None:
            print_introspection()
            return True
        args = []
    if wants_help(command, args):
        print_help()
        return True

    json_handler.log_operation("handle_command", {"module": "scan", "command": command})

    if not args:
        logger.warning("scan requires a target argument (e.g. scan @sentry)")
        return False

    results = scan(args[0])
    return results is not None


def print_introspection() -> None:
    """Display module introspection info."""
    from aipass.cli import console

    console.print()
    console.print("[bold cyan]scan Module[/bold cyan]")
    console.print("[dim]Branch command scanning -- discover available commands in a branch.[/dim]")
    console.print()
    console.print("[yellow]Connected Handlers:[/yellow]")
    console.print("  [cyan]handlers/scanning/[/cyan]")
    console.print("    - [cyan]scanner.py[/cyan] [dim](scan_branch, scan_help_output, scan_module_files)[/dim]")
    console.print(
        "    - [cyan]formatters.py[/cyan]"
        " [dim](format_scan_results, format_no_commands, format_help_scan_failure)[/dim]"
    )
    console.print()
    console.print("[yellow]Connected Modules:[/yellow]")
    console.print("  [cyan]modules/[/cyan]")
    console.print("    - [cyan]resolver.py[/cyan] [dim](resolve_branch -- branch name resolution)[/dim]")
    console.print()
    console.print("Run [green]'drone scan --help'[/green] for usage information")
    console.print()


def print_help() -> None:
    """Print help for the scan module."""
    from aipass.cli import console

    console.print("[bold cyan]scan[/bold cyan] — Branch command scanning")
    console.print()
    console.print("[bold cyan]Usage:[/bold cyan]")
    console.print("  [cyan]drone scan @target[/cyan]     Scan a branch for available commands")
    console.print()
    console.print("[bold cyan]Examples:[/bold cyan]")
    console.print("  [green]drone scan @sentry[/green]     Scan sentry for commands")
    console.print("  [green]drone scan @flow[/green]       Scan flow for commands")


def scan(target: str) -> list[dict] | None:
    """Resolve ``@target``, scan for commands, display and return results.

    None means the target did not resolve; an empty list means no commands were found.
    """
    branch_name = target.lstrip("@").lower()

    try:
        branch_path = resolve_branch(target)
    except Exception as exc:
        logger.warning("scan: could not resolve '%s': %s", target, exc)
        from aipass.cli import err_console

        err_console.print(f"scan: could not resolve '{target}': {exc}")
        return None

    help_errors: list[str] = []
    commands = scan_branch(branch_path, branch_name, help_errors)

    if commands:
        format_scan_results(branch_name, commands)
    else:
        format_no_commands(branch_name)
    format_help_scan_failure(branch_name, help_errors)

    return commands
