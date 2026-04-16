# =================== AIPass ====================
# Name: scan.py
# Description: Module orchestrator for branch command scanning
# Version: 1.0.0
# Created: 2026-03-17
# Modified: 2026-03-17
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
    format_no_commands,
    format_scan_results,
)
from aipass.drone.apps.modules.resolver import resolve_branch

__all__ = [
    "handle_command",
    "print_help",
    "print_introspection",
    "scan",
]


# ---------------------------------------------------------------------------
# Standard module interface
# ---------------------------------------------------------------------------


def handle_command(command: str | None = None, args: list[str] | None = None) -> bool:
    """Route scan subcommands to handler functions.

    Args:
        command: The subcommand string (currently unused -- scans are positional).
        args: List of arguments; first element is the ``@target``.

    Returns:
        True if the command succeeded, False otherwise.
    """
    if not args:
        if command is None:
            print_introspection()
            return True
        args = []
    if command in ("--help", "-h") or (args and args[0] in ("--help", "-h")):
        print_help()
        return True

    json_handler.log_operation("handle_command", {"module": "scan", "command": command})

    if not args:
        logger.warning("scan requires a target argument (e.g. scan @seedgo)")
        return False

    results = scan(args[0])
    return results is not None


def print_introspection() -> None:
    """Display module introspection info."""
    try:
        from aipass.cli.apps.modules.display import console
    except ImportError:
        logger.warning("CLI console not available, using fallback")
        from rich.console import Console

        console = Console()

    console.print()
    console.print("scan Module")
    console.print("Branch command scanning -- discover available commands in a branch.")
    console.print()
    console.print("Connected Handlers:")
    console.print("  handlers/scanning/")
    console.print("    - scanner.py (scan_branch, scan_help_output, scan_module_files)")
    console.print("    - formatters.py (format_scan_results, format_no_commands)")
    console.print()
    console.print("Connected Modules:")
    console.print("  modules/")
    console.print("    - resolver.py (resolve_branch -- branch name resolution)")
    console.print()


def print_help() -> None:
    """Print help for the scan module."""
    try:
        from aipass.cli.apps.modules.display import console
    except ImportError:
        logger.warning("CLI console not available, using fallback")
        from rich.console import Console

        console = Console()

    console.print("scan -- Branch command scanning")
    console.print()
    console.print("Usage:")
    console.print("  drone scan @target     Scan a branch for available commands")
    console.print()
    console.print("Examples:")
    console.print("  drone scan @seedgo     Scan seedgo for commands")
    console.print("  drone scan @flow       Scan flow for commands")


# ---------------------------------------------------------------------------
# Core operation
# ---------------------------------------------------------------------------


def scan(target: str) -> list[dict] | None:
    """Resolve ``@target``, scan for commands, display and return results.

    Args:
        target: Symbolic branch name (e.g. ``@seedgo``).

    Returns:
        List of discovered command dicts, or None on resolution failure.
    """
    branch_name = target.lstrip("@").lower()

    try:
        branch_path = resolve_branch(target)
    except Exception as exc:
        logger.warning("scan: could not resolve '%s': %s", target, exc)
        try:
            from aipass.cli.apps.modules import err_console

            err_console.print(f"scan: could not resolve '{target}': {exc}")
        except ImportError as exc:
            logger.warning("CLI err_console not available, skipping user-facing error: %s", exc)
        return None

    commands = scan_branch(branch_path, branch_name)

    if commands:
        format_scan_results(branch_name, commands)
    else:
        format_no_commands(branch_name)

    return commands
