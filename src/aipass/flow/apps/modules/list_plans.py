# =================== AIPass ====================
# Name: list_plans.py
# Description: PLAN listing module with filtering
# Version: 1.1.0
# Created: 2025-11-21
# Modified: 2025-11-21
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
from pathlib import Path
from typing import List

# INFRASTRUCTURE IMPORT PATTERN
_PKG_ROOT = Path(__file__).resolve().parents[3]  # file.py -> modules/ -> apps/ -> flow/ -> aipass/
FLOW_ROOT = _PKG_ROOT / "flow"

# External: Prax logger
from aipass.prax.apps.modules.logger import system_logger as logger

# JSON handler for operation tracking
from aipass.flow.apps.handlers.json import json_handler

# CLI services for display
from aipass.cli.apps.modules import console, error, warning

# Registry handlers
from aipass.flow.apps.handlers.registry.load_registry import load_registry
from aipass.flow.apps.handlers.registry.statistics import get_registry_statistics

# Plan display handler
from aipass.flow.apps.handlers.plan.display import format_plans_list, format_statistics_summary

# Implementation handler
from aipass.flow.apps.handlers.plan.list_ops import list_plans_impl

# =============================================
# CONFIGURATION
# =============================================

MODULE_NAME = "list_plans"

# =============================================
# INTROSPECTION FUNCTION
# =============================================


def print_introspection():
    """Display module info and connected handlers"""
    console.print()
    console.print("[bold cyan]list_plans Module[/bold cyan]")
    console.print()

    # List handlers this module actually imports/uses
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
    console.print("  drone @flow list [filter]")
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


# =============================================
# ORCHESTRATION WORKFLOWS
# =============================================


def list_plans(filter_type: str = "open") -> bool:
    """
    Orchestrate plan listing workflow (thin orchestrator)

    Delegates all business logic to list_ops handler.
    Module handles all display output.

    Args:
        filter_type: Filter plans by status ("open", "closed", "all")

    Returns:
        True if successful, False otherwise
    """
    result = list_plans_impl(
        filter_type=filter_type,
        load_registry=load_registry,
        get_registry_statistics=get_registry_statistics,
        format_plans_list=format_plans_list,
        format_statistics_summary=format_statistics_summary,
    )

    # Module handles display
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

    # Display formatted results
    try:
        console.print(result["formatted_list"])
        console.print(result["formatted_stats"])
    except BrokenPipeError:
        # Pipe closed by reader - not a real error
        logger.info(f"[{MODULE_NAME}] Broken pipe (stdout closed early)")

    return True


def handle_command(command: str, args: List[str]) -> bool:
    """
    Handle command routing for list_plans module (thin orchestrator)

    Delegates to handlers:
    - Argument parsing: handled locally (simple case)
    - Workflow execution: list_plans orchestrator

    Args:
        command: Command name ("list" or "list_plans")
        args: Additional arguments (filter type)

    Returns:
        bool indicating success or failure
    """
    # Check if this is our command
    if command != "list":
        return False

    if not args:
        print_introspection()
        return True

    # Handle help flag
    if args[0] in ["--help", "-h", "help"]:
        print_help()
        return True

    # Log the operation
    json_handler.log_operation("plans_listed", {"command": command, "args": args})

    # STEP 1: Parse filter argument
    filter_type = "open"  # Default to open plans

    filter_arg = args[0].lower()
    if filter_arg in ["open", "closed", "all"]:
        filter_type = filter_arg
    else:
        warning(f"Unknown filter '{filter_arg}', defaulting to 'open'")
        console.print("[dim]Valid filters: open, closed, all[/dim]")

    # STEP 2: Execute workflow
    list_plans(filter_type)

    # STEP 3: Command was handled (even if the operation failed, the error
    # has already been displayed -- returning False would cause flow.py to
    # print a spurious "Unknown command" message)
    return True


# =============================================
# STANDALONE EXECUTION (for testing)
# =============================================

if __name__ == "__main__":
    try:
        # Show introspection when run without arguments
        if len(sys.argv) == 1:
            print_introspection()
            sys.exit(0)

        # Handle help flag
        if len(sys.argv) > 1 and sys.argv[1] in ["--help", "-h", "help"]:
            print_help()
            sys.exit(0)

        # Confirm logger connection
        logger.info("Prax logger connected to list_plans")

        # Log standalone execution
        json_handler.log_operation("plans_listed", {"command": "standalone"})

        # Call handle_command
        args = sys.argv[1:] if len(sys.argv) > 1 else []

        # If first arg is not our command, assume it's a filter (backward compatibility)
        if args and args[0] not in ["list", "list_plans"]:
            # First arg is filter
            result = handle_command("list", args)
        else:
            # Standard command format
            cmd = args[0] if args else "list"
            result = handle_command(cmd, args[1:] if len(args) > 1 else [])

        # Exit with appropriate code
        sys.exit(0 if result else 1)

    except BrokenPipeError:
        # Pipe closed by reader - exit cleanly
        import os

        logger.info(f"[{MODULE_NAME}] Broken pipe in standalone mode (stdout closed early)")
        try:
            sys.stdout.close()
        except Exception as e:
            logger.warning(f"[{MODULE_NAME}] Error closing stdout after broken pipe: {e}")
        os._exit(0)
