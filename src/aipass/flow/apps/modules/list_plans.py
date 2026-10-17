# =================== AIPass ====================
# Name: list_plans.py
# Description: PLAN listing module with filtering
# Version: 1.1.1
# Created: 2025-11-21
# Modified: 2026-10-17
# =============================================

"""
List PLAN Module - Thin Orchestrator

Orchestrates plan listing workflow by delegating to handlers.
Module contains NO business logic - only workflow coordination and display.

Workflow:
    1. Parse arguments
    2. Call list_ops handler for data
    3. Display results via console

Usage:
    From flow.py: flow plan list [filter]
    Standalone: drone @flow list [filter]

Filters:
    list          - List open plans only (default)
    list open     - List open plans only
    list closed   - List closed plans only
    list all      - List all plans
"""

import sys
import os

if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8", errors="replace")

from typing import List

from aipass.flow.apps.handlers.repo_root import module_file

_PKG_ROOT = module_file(__file__).parents[3]  # file.py -> modules/ -> apps/ -> flow/ -> aipass/
FLOW_ROOT = _PKG_ROOT / "flow"

from aipass.prax.apps.modules.logger import system_logger as logger

from aipass.flow.apps.handlers.cli.arg_gate import UnknownArgument, refuse_extra, refuse_unknown
from aipass.flow.apps.handlers.cli.help_flags import wants_help
from aipass.flow.apps.handlers.json import json_handler

from aipass.cli.apps.modules import console, error, warning

from aipass.flow.apps.handlers.registry.load_registry import load_registry
from aipass.flow.apps.handlers.registry.statistics import get_registry_statistics

from aipass.flow.apps.handlers.plan.display import format_plans_list, format_statistics_summary

from aipass.flow.apps.handlers.plan.list_ops import list_plans_impl

MODULE_NAME = "list_plans"

# Named once so the refusal message and the check cannot drift apart.
VALID_FILTERS = ("open", "closed", "all")


def print_introspection():
    """Display module info and connected handlers"""
    console.print()
    console.print("[bold cyan]list_plans Module[/bold cyan]")
    console.print()

    console.print("[yellow]Connected Handlers:[/yellow]")
    console.print()
    console.print("  [cyan]handlers/registry/[/cyan]")
    console.print("    [dim]- load_registry.py[/dim]")
    console.print("    [dim]- statistics.py[/dim]")
    console.print()
    console.print("  [cyan]handlers/plan/[/cyan]")
    console.print("    [dim]- list_ops.py (implementation)[/dim]")
    console.print("    [dim]- display.py[/dim]")
    console.print()

    console.print("[dim]Run 'drone @flow list --help' for usage[/dim]")
    console.print()


def print_help():
    """Print help information for list_plans module"""
    console.print()
    console.print("[bold cyan]list_plans[/bold cyan] — List PLAN files from registry")
    console.print()
    console.print("[yellow]USAGE:[/yellow]")
    console.print("  drone @flow list \\[filter]")
    console.print()
    console.print("[yellow]FILTERS:[/yellow]")
    console.print("  open      List open plans only [dim](default)[/dim]")
    console.print("  closed    List closed plans only")
    console.print("  all       List all plans (open + closed)")
    console.print()
    console.print("[yellow]EXAMPLES:[/yellow]")
    console.print("  [dim]drone @flow list open[/dim]       # Open plans")
    console.print("  [dim]drone @flow list closed[/dim]     # Closed plans")
    console.print("  [dim]drone @flow list all[/dim]        # Everything")
    console.print()
    console.print()


def list_plans(filter_type: str = "open") -> bool:
    """
    Orchestrate plan listing workflow (thin orchestrator)
    """
    result = list_plans_impl(
        filter_type=filter_type,
        load_registry=load_registry,
        get_registry_statistics=get_registry_statistics,
        format_plans_list=format_plans_list,
        format_statistics_summary=format_statistics_summary,
    )

    if result.get("empty") and result.get("success"):
        warning("No plans found in registry")
        return True

    if not result.get("success"):
        error_msg = result.get("error", "Unknown error")
        try:
            error(f"ERROR: {error_msg}")
        except BrokenPipeError:
            logger.info(f"[{MODULE_NAME}] Broken pipe while displaying error (stdout closed early)")
        return False

    try:
        console.print(result["formatted_list"])
        console.print(result["formatted_stats"])
    except BrokenPipeError:
        logger.info(f"[{MODULE_NAME}] Broken pipe (stdout closed early)")

    return True


def handle_command(command: str, args: List[str]) -> bool:
    """
    Handle command routing for list_plans module (thin orchestrator)

    Raises SystemExit(1) on an unknown filter or extra argument.
    """
    if command != "list":
        return False

    if not args:
        print_introspection()
        return True

    if wants_help(args):
        print_help()
        return True

    json_handler.log_operation("plans_listed", {"command": command, "args": args})

    # An unknown filter is refused, never defaulted to "open".
    try:
        filter_arg = args[0].lower()
        if filter_arg not in VALID_FILTERS:
            refuse_unknown(args[0], door="list", valid=VALID_FILTERS, noun="filter")
        if len(args) > 1:
            refuse_extra(args[1:], door=f"list {filter_arg}")
    except UnknownArgument as exc:
        error(exc.message, suggestion=exc.usage)
        raise SystemExit(1) from exc

    filter_type = filter_arg

    list_plans(filter_type)

    # False would make flow.py print a spurious "Unknown command"; the error is already shown.
    return True


if __name__ == "__main__":
    try:
        if len(sys.argv) == 1:
            print_introspection()
            sys.exit(0)

        if len(sys.argv) > 1 and sys.argv[1] in ["--help", "-h", "help"]:
            print_help()
            sys.exit(0)

        logger.info("Prax logger connected to list_plans")

        json_handler.log_operation("plans_listed", {"command": "standalone"})

        args = sys.argv[1:] if len(sys.argv) > 1 else []

        # A bare filter (no verb) is still accepted.
        if args and args[0] not in ["list", "list_plans"]:
            result = handle_command("list", args)
        else:
            cmd = args[0] if args else "list"
            result = handle_command(cmd, args[1:] if len(args) > 1 else [])

        sys.exit(0 if result else 1)

    except BrokenPipeError:
        import os

        logger.info(f"[{MODULE_NAME}] Broken pipe in standalone mode (stdout closed early)")
        try:
            sys.stdout.close()
        except Exception as e:
            logger.warning(f"[{MODULE_NAME}] Error closing stdout after broken pipe: {e}")
        os._exit(0)
