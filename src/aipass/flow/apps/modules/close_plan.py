# =================== AIPass ====================
# Name: close_plan.py
# Description: PLAN closure module with registry cleanup
# Version: 3.6.0
# Created: 2025-11-25
# Modified: 2025-11-25
# =============================================

"""
Close PLAN Module

Thin orchestrator for plan closure workflow.
All business logic delegated to handlers.
Module handles all display output.

Usage:
    From flow.py: flow close <number>
    From flow.py: flow close --all
    Standalone: python3 close_plan.py <number>
"""

import sys
from pathlib import Path
from typing import List, Dict, Any

# INFRASTRUCTURE IMPORT PATTERN
_PKG_ROOT = Path(__file__).resolve().parents[3]  # file.py -> modules/ -> apps/ -> flow/ -> aipass/
FLOW_ROOT = _PKG_ROOT / "flow"

# External: Prax logger
from aipass.prax import logger

# JSON handler for operation tracking
from aipass.flow.apps.handlers.json import json_handler

# CLI services for display and error handling
from aipass.cli.apps.modules import console, error, warning

# Internal: Registry handlers
from aipass.flow.apps.handlers.registry.load_registry import load_registry
from aipass.flow.apps.handlers.registry.save_registry import save_registry

# Internal: Plan handlers
from aipass.flow.apps.handlers.plan.get_open_plans import get_open_plans
from aipass.flow.apps.handlers.plan.validator import normalize_plan_number, validate_plan_exists
from aipass.flow.apps.handlers.plan.confirmation import confirm_plan_deletion
from aipass.flow.apps.handlers.plan.display import (
    format_plan_deletion_header,
    format_plan_error,
    format_plan_deletion_success,
    format_deletion_cancelled,
    format_delete_usage_error
)

# Internal: Dashboard handlers
from aipass.flow.apps.handlers.dashboard.update_local import update_dashboard_local
from aipass.flow.apps.handlers.dashboard.push_central import push_to_plans_central
from aipass.flow.apps.handlers.dashboard.push_branch_dashboard import push_flow_to_branch_dashboard

# Internal: Memory bank template check (lightweight, no API calls)
from aipass.flow.apps.handlers.mbank.process import is_template_content

# Internal: Close operations handler (implementation)
from aipass.flow.apps.handlers.plan.close_ops import close_plan_impl, close_all_plans_impl

# =============================================
# CONFIGURATION
# =============================================

MODULE_NAME = "close_plan"


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
            error_text = msg.get("text", "general")
            plan_num = msg.get("plan_num", "")
            details = msg.get("details", None)
            console.print(format_plan_error(error_text, plan_num, details=details))

        elif msg_type == "warning":
            warning(msg['text'])

        elif msg_type == "dim":
            console.print(f"[dim]{msg['text']}[/dim]")

        elif msg_type == "step":
            console.print(f"[dim]{msg['text']}[/dim]")

        elif msg_type == "success":
            console.print(f"[green]{msg['text']}[/green]")

        elif msg_type == "error_text":
            error(msg['text'])

        elif msg_type == "header":
            console.print(format_plan_deletion_header(msg["plan_key"], msg["plan_info"], prefix=msg.get("prefix", "FPLAN")))

        elif msg_type == "cancelled":
            console.print(format_deletion_cancelled())

        elif msg_type == "close_success":
            console.print(format_plan_deletion_success(msg["plan_key"], prefix=msg.get("prefix", "FPLAN")))

        elif msg_type == "plan_list":
            warning(f"Found {msg['count']} open plan(s) to close:")
            for plan in msg.get("plans", []):
                console.print(f"  * {plan.get('prefix', 'FPLAN')}-{plan['plan_num']}: {plan['subject']}")

        elif msg_type == "confirm_warning":
            error(f"WARNING: This will close all {msg['count']} plans!")

        elif msg_type == "closing_all":
            console.print(f"\n[bold]Closing all {msg['count']} plan(s)...[/bold]")
            console.print("-" * 60)

        elif msg_type == "closing_single":
            console.print(f"\n[dim]Closing {msg.get('prefix', 'FPLAN')}-{msg['plan_num']}...[/dim]")

        elif msg_type == "close_all_summary":
            console.print("\n" + "=" * 60)
            console.print("[bold green]CLOSE ALL COMPLETE[/bold green]")
            console.print(f"  * Successfully closed: {msg['success_count']}")
            console.print(f"  * Failed to close: {msg['failure_count']}")
            console.print(f"  * Total processed: {msg['total']}")
            console.print("=" * 60 + "\n")


# =============================================
# INTROSPECTION
# =============================================

def print_introspection():
    """Display module info and connected handlers"""
    console.print()
    console.print("[bold cyan]close_plan Module[/bold cyan]")
    console.print()

    console.print("[yellow]Connected Handlers:[/yellow]")
    console.print()

    console.print("  [cyan]handlers/plan/[/cyan]")
    console.print("    [dim]- close_ops.py (implementation)[/dim]")
    console.print("    [dim]- get_open_plans.py[/dim]")
    console.print("    [dim]- command_parser.py[/dim]")
    console.print("    [dim]- confirmation.py[/dim]")
    console.print("    [dim]- validator.py[/dim]")
    console.print("    [dim]- display.py[/dim]")
    console.print("    [dim]- file_ops.py[/dim]")
    console.print("    [dim]- update_registry.py[/dim]")
    console.print()

    console.print("  [cyan]handlers/registry/[/cyan]")
    console.print("    [dim]- load_registry.py[/dim]")
    console.print("    [dim]- save_registry.py[/dim]")
    console.print()

    console.print("  [cyan]handlers/dashboard/[/cyan]")
    console.print("    [dim]- update_local.py[/dim]")
    console.print("    [dim]- push_central.py[/dim]")
    console.print()

    console.print("[dim]Run 'drone @flow close --help' for usage[/dim]")
    console.print()

def print_help():
    """Print help information for close_plan module"""
    console.print()
    console.print("[bold cyan]close_plan[/bold cyan] — Close PLAN files")
    console.print()
    console.print("[yellow]USAGE:[/yellow]")
    console.print("  drone @flow close <PLAN-ID> [options]")
    console.print()
    console.print("[yellow]OPTIONS:[/yellow]")
    console.print("  --all       Close all open plans")
    console.print("  --confirm   Interactive confirmation prompt")
    console.print("  --dry-run   Preview what would be closed (no action taken)")
    console.print()
    console.print("[yellow]EXAMPLES:[/yellow]")
    console.print("  [dim]drone @flow close FPLAN-0042[/dim]          # Close specific plan")
    console.print("  [dim]drone @flow close DPLAN-0005[/dim]          # Close a DPLAN")
    console.print("  [dim]drone @flow close --all[/dim]               # Close all open plans")
    console.print("  [dim]drone @flow close --all --dry-run[/dim]     # Preview close-all")
    console.print()


# =============================================
# CLOSE PLAN WORKFLOW (thin orchestrator)
# =============================================

def close_plan(plan_num: str | None = None, confirm: bool = False, all_plans: bool = False, spawn_background: bool = True, dry_run: bool = False) -> bool:
    """
    Orchestrate plan closure workflow (thin orchestrator)

    Auto-confirms by default - running 'close' IS the intent.
    Use confirm=True (--confirm/--interactive) to explicitly request a prompt.

    Delegates all business logic to handlers:
    - Validation: validator handler
    - Registry ops: registry handlers
    - File ops: file_ops handler
    - Confirmation: confirmation handler
    - Display: display handler
    - Close implementation: close_ops handler

    Args:
        plan_num: Plan number (e.g., "0001" or "1" or "42") - required if all_plans=False
        confirm: Whether to ask for confirmation (default False, auto-confirms)
        all_plans: If True, close all open plans (default False)
        spawn_background: Whether to spawn background post-processing (default True).
                          Set False when called from close_all_plans() to avoid race condition.
        dry_run: If True, preview what would be closed without taking action (default False)

    Returns:
        True if successful, False otherwise
    """
    result = close_plan_impl(
        plan_num=plan_num,
        confirm=confirm,
        all_plans=all_plans,
        spawn_background=spawn_background,
        dry_run=dry_run,
        # Inject dependencies
        normalize_plan_number=normalize_plan_number,
        load_registry=load_registry,
        save_registry=save_registry,
        validate_plan_exists=validate_plan_exists,
        confirm_plan_deletion=confirm_plan_deletion,
        is_template_content=is_template_content,
        update_dashboard_local=update_dashboard_local,
        push_to_plans_central=push_to_plans_central,
        push_flow_to_branch_dashboard=push_flow_to_branch_dashboard,
        close_all_plans_fn=close_all_plans,
    )

    # Handle dict result from handler
    if isinstance(result, dict):
        _display_messages(result.get("messages", []))
        return result.get("success", False)

    # Fallback for bool result
    return bool(result)


def close_all_plans(confirm: bool = False, dry_run: bool = False) -> bool:
    """
    Close all open plans in one operation (thin orchestrator)

    Args:
        confirm: Whether to ask for bulk confirmation (default False, auto-confirms)
        dry_run: If True, preview what would be closed without taking action (default False)

    Returns:
        True if at least one plan closed successfully, False otherwise
    """
    result = close_all_plans_impl(
        confirm=confirm,
        dry_run=dry_run,
        get_open_plans=get_open_plans,
        close_plan_fn=close_plan,
    )

    # Handle dict result from handler
    if isinstance(result, dict):
        _display_messages(result.get("messages", []))
        return result.get("success", False)

    # Fallback for bool result
    return bool(result)


def handle_command(command: str, args: List[str]) -> bool:
    """
    Handle command routing for close_plan module (thin orchestrator)

    Delegates to handlers:
    - Argument parsing: command_parser handler
    - Workflow execution: close_plan orchestrator
    - Error display: display handler

    Args:
        command: Command name
        args: Additional arguments

    Returns:
        bool indicating success or failure
    """
    # Check if this is our command
    if command != "close":
        return False

    if not args:
        print_introspection()
        return True

    # Handle help flag
    if args[0] in ["--help", "-h", "help"]:
        print_help()
        return True

    # Import parser here (after command check)
    from aipass.flow.apps.handlers.plan.command_parser import parse_close_command_args

    # Log the operation
    json_handler.log_operation(
        "plan_closed",
        {"command": command, "args": args}
    )

    # 1. PARSE ARGS: Use command_parser handler
    plan_num, confirm, all_plans, dry_run, error = parse_close_command_args(args)

    # 2. VALIDATE: Check for parsing errors
    if error:
        console.print(format_delete_usage_error())
        return True  # Command was handled (error already displayed)

    # 3. EXECUTE: Run workflow orchestrator
    close_plan(plan_num=plan_num, confirm=confirm, all_plans=all_plans, dry_run=dry_run)

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
    if len(sys.argv) > 1 and sys.argv[1] in ['--help', '-h', 'help']:
        import argparse
        PARSER = argparse.ArgumentParser(
            description='Close PLAN file',
            formatter_class=argparse.RawDescriptionHelpFormatter,
            epilog="""
COMMANDS:
  close, close_plan      Close a single plan
  close --all            Close all open plans

USAGE:
  python3 close_plan.py close <plan_number>
  python3 close_plan.py close <plan_number> --confirm
  python3 close_plan.py close --all
  python3 close_plan.py --help

OPTIONS:
  --confirm, --interactive   Request confirmation prompt (off by default)
  --yes, -y                  Backwards compat (redundant, already auto-confirms)
  --all                      Close all open plans

EXAMPLES:
  # Close plan (auto-confirms)
  python3 close_plan.py close 42

  # Close with interactive confirmation prompt
  python3 close_plan.py close 42 --confirm

  # Close all open plans (auto-confirms)
  python3 close_plan.py close --all
            """
        )
        PARSER.print_help()
        sys.exit(0)

    # Confirm logger connection
    logger.info("Prax logger connected to close_plan")

    # Log standalone execution
    json_handler.log_operation(
        "plan_closed",
        {"command": "standalone"}
    )

    # Call handle_command with default
    args = sys.argv[1:] if len(sys.argv) > 1 else []
    if not args:
        console.print(format_delete_usage_error())
        console.print("Run with --help for usage information")
        console.print()
        sys.exit(1)

    # If first arg is not command, assume it's plan number (backward compatibility)
    if args[0] not in ['close', 'close_plan']:
        args.insert(0, 'close')

    result = handle_command(args[0], args[1:])
    # Result is True on success, False on failure
    if result:
        sys.exit(0)
    else:
        sys.exit(1)
