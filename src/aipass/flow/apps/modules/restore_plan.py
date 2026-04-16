# =================== AIPass ====================
# Name: restore_plan.py
# Description: PLAN restore module (reopen closed plans)
# Version: 1.5.0
# Created: 2025-11-22
# Modified: 2025-11-22
# =============================================

"""
Restore PLAN Module

Thin orchestrator for plan restore workflow (reopening closed plans).
All business logic delegated to handlers.
Module handles all display output.

Usage:
    From flow.py: flow restore <number>
    Standalone: drone @flow restore <number>
"""

import sys
from pathlib import Path
from typing import List, Dict, Any

# INFRASTRUCTURE IMPORT PATTERN
_PKG_ROOT = Path(__file__).resolve().parents[3]  # file.py -> modules/ -> apps/ -> flow/ -> aipass/
FLOW_ROOT = _PKG_ROOT / "flow"

# External: Prax logger
from aipass.prax.apps.modules.logger import system_logger as logger

# JSON handler for operation tracking
from aipass.flow.apps.handlers.json import json_handler

# CLI services for display and error handling
from aipass.cli.apps.modules import console, warning

# Internal: Registry handlers
from aipass.flow.apps.handlers.registry.load_registry import load_registry
from aipass.flow.apps.handlers.registry.save_registry import save_registry

# Internal: Plan handlers
from aipass.flow.apps.handlers.plan.validator import normalize_plan_number, validate_plan_exists
from aipass.flow.apps.handlers.plan.display import (
    format_restore_header,
    format_restore_error,
    format_restore_success,
    format_restore_usage_error,
)

# Internal: Dashboard handlers
from aipass.flow.apps.handlers.dashboard.update_local import update_dashboard_local
from aipass.flow.apps.handlers.dashboard.push_central import push_to_plans_central

# Internal: Restore operations handler (implementation)
from aipass.flow.apps.handlers.plan.restore_ops import (
    recover_plan_from_backup as _recover_plan_from_backup_impl,
    restore_plan_impl,
)

# =============================================
# CONFIGURATION
# =============================================

MODULE_NAME = "restore_plan"

# =============================================
# DISPLAY HELPERS
# =============================================


def _display_messages(messages: List[Dict[str, Any]]):
    """Render handler result messages to console

    Args:
        messages: List of message dicts from handler with type/text keys
    """
    for msg in messages:
        msg_type = msg.get("type", "")

        if msg_type == "error":
            error_type = msg.get("error_type", "general")
            plan_key = msg.get("plan_key", "")
            details = msg.get("details", None)
            console.print(format_restore_error(error_type, plan_key, details=details))

        elif msg_type == "warning":
            warning(msg["text"])

        elif msg_type == "dim":
            console.print(f"[dim]{msg['text']}[/dim]")

        elif msg_type == "success":
            console.print(f"[green]{msg['text']}[/green]")

        elif msg_type == "restore_header":
            console.print(format_restore_header(msg["plan_key"], msg["plan_info"]))

        elif msg_type == "restore_success":
            console.print(format_restore_success(msg["plan_key"], msg.get("location")))


# =============================================
# INTROSPECTION
# =============================================


def print_introspection():
    """Display module info and connected handlers"""
    console.print()
    console.print("[bold cyan]restore_plan Module[/bold cyan]")
    console.print()

    console.print("[yellow]Connected Handlers:[/yellow]")
    console.print()

    console.print("  [cyan]handlers/plan/[/cyan]")
    console.print("    [dim]- restore_ops.py (implementation)[/dim]")
    console.print("    [dim]- command_parser.py[/dim]")
    console.print("    [dim]- validator.py[/dim]")
    console.print("    [dim]- display.py[/dim]")
    console.print()

    console.print("  [cyan]handlers/registry/[/cyan]")
    console.print("    [dim]- load_registry.py[/dim]")
    console.print("    [dim]- save_registry.py[/dim]")
    console.print()

    console.print("  [cyan]handlers/dashboard/[/cyan]")
    console.print("    [dim]- update_local.py[/dim]")
    console.print("    [dim]- push_central.py[/dim]")
    console.print()

    console.print("[dim]Run 'drone @flow restore --help' for usage[/dim]")
    console.print()


def print_help():
    """Print help information for restore_plan module"""
    console.print()
    console.print("[bold cyan]restore_plan[/bold cyan] — Reopen closed PLAN files")
    console.print()
    console.print("[yellow]USAGE:[/yellow]")
    console.print("  drone @flow restore <PLAN-ID>")
    console.print()
    console.print("[yellow]EXAMPLES:[/yellow]")
    console.print("  [dim]drone @flow restore FPLAN-0042[/dim]        # Reopen a closed plan")
    console.print("  [dim]drone @flow restore DPLAN-0005[/dim]        # Reopen a closed DPLAN")
    console.print()
    console.print("[yellow]NOTES:[/yellow]")
    console.print("  Plan must be closed. File must exist at registered location.")
    console.print()


# =============================================
# RECOVERY FUNCTIONS
# =============================================


def recover_plan_from_backup(plan_key: str) -> tuple[bool, str]:
    """
    Attempt to recover a plan from processed_plans backup (thin orchestrator)

    Delegates to restore_ops handler for implementation.

    Args:
        plan_key: Normalized plan number (e.g., "0165")

    Returns:
        (success, message)
    """
    return _recover_plan_from_backup_impl(
        plan_key,
        load_registry=load_registry,
        save_registry=save_registry,
    )


# =============================================
# RESTORE PLAN WORKFLOW
# =============================================


def restore_plan(plan_num: str | None) -> bool:
    """
    Orchestrate plan restore workflow (thin orchestrator)

    Delegates all business logic to restore_ops handler.
    Module handles all display output.

    Args:
        plan_num: Plan number (e.g., "0001" or "1" or "42")

    Returns:
        True if successful, False otherwise
    """
    # Import scan_plan_files here (lazy import to avoid circular dependency)
    from aipass.flow.apps.modules.registry_monitor import scan_plan_files

    result = restore_plan_impl(
        plan_num=plan_num,
        # Inject dependencies
        normalize_plan_number=normalize_plan_number,
        load_registry=load_registry,
        save_registry=save_registry,
        validate_plan_exists=validate_plan_exists,
        recover_plan_from_backup_fn=recover_plan_from_backup,
        scan_plan_files=scan_plan_files,
        update_dashboard_local=update_dashboard_local,
        push_to_plans_central=push_to_plans_central,
    )

    # Module handles display
    _display_messages(result.get("messages", []))
    return result.get("success", False)


def handle_command(command: str, args: List[str]) -> bool:
    """
    Handle command routing for restore_plan module (thin orchestrator)

    Delegates to handlers:
    - Argument parsing: command_parser handler
    - Workflow execution: restore_plan orchestrator
    - Error display: display handler

    Args:
        command: Command name
        args: Additional arguments

    Returns:
        bool indicating success or failure
    """
    # Check if this is our command
    if command != "restore":
        return False

    if not args:
        print_introspection()
        return True

    # Handle help flag
    if args[0] in ["--help", "-h", "help"]:
        print_help()
        return True

    # Import parser here (after command check)
    from aipass.flow.apps.handlers.plan.command_parser import parse_restore_command_args

    # Log the operation
    json_handler.log_operation("plan_restored", {"command": command, "args": args})

    # 1. PARSE ARGS: Use command_parser handler
    plan_num, error = parse_restore_command_args(args)

    # 2. VALIDATE: Check for parsing errors
    if error:
        console.print(format_restore_usage_error())
        return True  # Command was handled (error already displayed)

    # 3. EXECUTE: Run workflow orchestrator
    restore_plan(plan_num=plan_num)

    # 4. RETURN: True = command was handled (even if the operation failed,
    #    the error has already been displayed -- returning False would cause
    #    flow.py to print a spurious "Unknown command" message)
    return True


# =============================================
# STANDALONE EXECUTION (for testing)
# =============================================

if __name__ == "__main__":
    # Show introspection when run without arguments
    if len(sys.argv) == 1:
        print_introspection()
        sys.exit(0)

    # Handle help flag
    if len(sys.argv) > 1 and sys.argv[1] in ["--help", "-h", "help"]:
        import argparse

        PARSER = argparse.ArgumentParser(
            description="Restore PLAN file to open status",
            formatter_class=argparse.RawDescriptionHelpFormatter,
            epilog="""
COMMANDS:
  restore, restore_plan      Restore a closed plan to open status

USAGE:
  drone @flow restore <PLAN-ID>
  drone @flow restore --help

EXAMPLES:
  # Restore a closed plan
  drone @flow restore FPLAN-0042

  # Using plan number directly
  drone @flow restore FPLAN-0042

NOTES:
  - Plan must be closed to restore
  - Plan file must exist at registered location
  - Only updates registry metadata (does not move files)
            """,
        )
        PARSER.print_help()
        sys.exit(0)

    # Confirm logger connection
    logger.info("Prax logger connected to restore_plan")

    # Log standalone execution
    json_handler.log_operation("plan_restored", {"command": "standalone"})

    # Call handle_command with default
    args = sys.argv[1:] if len(sys.argv) > 1 else []
    if not args:
        console.print(format_restore_usage_error())
        console.print("Run with --help for usage information")
        console.print()
        sys.exit(1)

    # If first arg is not command, assume it's plan number (backward compatibility)
    if args[0] not in ["restore", "restore_plan"]:
        args.insert(0, "restore")

    result = handle_command(args[0], args[1:])
    # Result is True on success, False on failure
    if result:
        sys.exit(0)
    else:
        sys.exit(1)
