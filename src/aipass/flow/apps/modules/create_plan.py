# =================== AIPass ====================
# Name: create_plan.py
# Description: PLAN creation module with location awareness
# Version: 1.2.0
# Created: 2025-11-16
# Modified: 2025-11-16
# =============================================

"""
Create PLAN Module - Thin Orchestrator

Orchestrates plan creation workflow by delegating to handlers.
Module contains NO business logic - only workflow coordination.

Workflow:
    1. Parse arguments -> command_parser handler
    2. Load registry -> registry handlers
    3. Auto-cleanup -> plan handlers
    4. Validate location -> plan handlers
    5. Calculate paths -> plan handlers
    6. Get template -> template handlers
    7. Create file -> plan handlers
    8. Update registry -> plan handlers
    9. Update dashboards -> dashboard handlers
    10. Display results -> display handlers

Usage:
    From flow.py: flow plan create [location] [subject] [template]
    Standalone: python3 create_plan.py [location] [subject] [template]
"""

import sys
from pathlib import Path
from typing import Any, Dict, Tuple, List

# INFRASTRUCTURE IMPORT PATTERN
_PKG_ROOT = Path(__file__).resolve().parents[3]  # file.py -> modules/ -> apps/ -> flow/ -> aipass/
FLOW_ROOT = _PKG_ROOT / "flow"

# External: Prax logger
from aipass.prax.apps.modules.logger import system_logger as logger

# JSON handler for operation tracking
from aipass.flow.apps.handlers.json import json_handler

# CLI services for display
from aipass.cli.apps.modules import console, warning

# Registry handlers (cross-domain - OK for modules)
from aipass.flow.apps.handlers.registry.load_registry import load_registry
from aipass.flow.apps.handlers.registry.save_registry import save_registry

# Template handlers (cross-domain - OK for modules)
from aipass.flow.apps.handlers.template.get_template import get_template
from aipass.flow.apps.handlers.template.plan_type_loader import get_plan_type

# Plan handlers (same-domain)
from aipass.flow.apps.handlers.plan.command_parser import parse_create_plan_args
from aipass.flow.apps.handlers.plan.auto_cleanup import auto_close_orphaned_plans
from aipass.flow.apps.handlers.plan.resolve_location import resolve_plan_location
from aipass.flow.apps.handlers.plan.calculate_relative_path import calculate_relative_location
from aipass.flow.apps.handlers.plan.create_file import create_plan_file
from aipass.flow.apps.handlers.plan.build_registry_entry import build_plan_registry_entry
from aipass.flow.apps.handlers.plan.display import display_plan_created, display_plan_result

# Dashboard handlers (cross-domain - OK for modules)
from aipass.flow.apps.handlers.dashboard.update_local import update_dashboard_local
from aipass.flow.apps.handlers.dashboard.push_central import push_to_plans_central
from aipass.flow.apps.handlers.dashboard.push_branch_dashboard import push_flow_to_branch_dashboard

# Implementation handler
from aipass.flow.apps.handlers.plan.create_ops import create_plan_impl


# =============================================
# CONFIGURATION
# =============================================

MODULE_NAME = "create_plan"
ECOSYSTEM_ROOT = _PKG_ROOT

# =============================================
# INTROSPECTION
# =============================================

def print_introspection():
    """Display module info and connected handlers"""
    console.print()
    console.print("[bold cyan]create_plan Module[/bold cyan]")
    console.print()

    console.print("[yellow]Connected Handlers:[/yellow]")
    console.print()

    console.print("  [cyan]handlers/plan/[/cyan]")
    console.print("    [dim]- create_ops.py (implementation)[/dim]")
    console.print("    [dim]- command_parser.py[/dim]")
    console.print("    [dim]- auto_cleanup.py[/dim]")
    console.print("    [dim]- resolve_location.py[/dim]")
    console.print("    [dim]- calculate_relative_path.py[/dim]")
    console.print("    [dim]- create_file.py[/dim]")
    console.print("    [dim]- build_registry_entry.py[/dim]")
    console.print("    [dim]- display.py[/dim]")
    console.print()

    console.print("  [cyan]handlers/registry/[/cyan]")
    console.print("    [dim]- load_registry.py[/dim]")
    console.print("    [dim]- save_registry.py[/dim]")
    console.print()

    console.print("  [cyan]handlers/template/[/cyan]")
    console.print("    [dim]- get_template.py[/dim]")
    console.print()

    console.print("  [cyan]handlers/dashboard/[/cyan]")
    console.print("    [dim]- update_local.py[/dim]")
    console.print("    [dim]- push_central.py[/dim]")
    console.print()

    console.print("[dim]Run 'python3 create_plan.py --help' for usage[/dim]")
    console.print()

def print_help():
    """Print help information for create_plan module"""
    console.print()
    console.print("[bold cyan]create_plan.py[/bold cyan] - Create new PLAN file")
    console.print()
    console.print("[yellow]COMMANDS:[/yellow]")
    console.print("  create, create_plan")
    console.print()
    console.print("[yellow]USAGE:[/yellow]")
    console.print("  python3 create_plan.py create [location] [subject] [template]")
    console.print("  python3 create_plan.py --help")
    console.print()
    console.print("[yellow]EXAMPLES:[/yellow]")
    console.print("  [dim]# Create in current directory[/dim]")
    console.print("  python3 create_plan.py create")
    console.print()
    console.print("  [dim]# Create with location and subject[/dim]")
    console.print("  python3 create_plan.py create @flow \"New feature implementation\"")
    console.print()
    console.print("  [dim]# Create with custom template[/dim]")
    console.print("  python3 create_plan.py create @flow \"Research task\" master")
    console.print()


# =============================================
# ORCHESTRATION WORKFLOWS (thin wrappers)
# =============================================

def create_plan(
    location: str | None = None,
    subject: str = "",
    plan_type_key: str = "flow_plans",
    plan_type_config: Dict[str, Any] | None = None,
) -> Tuple[bool, int, str, str, str]:
    """
    Orchestrate plan creation workflow (thin orchestrator)

    Delegates all business logic to create_ops handler.
    Module handles all display output from handler messages.

    Args:
        location: Target directory for plan (@folder syntax supported)
        subject: Plan subject/title
        plan_type_key: Plan type key for the plugin system
            (e.g. "flow_plans", "dev_plans", "master")
        plan_type_config: Pre-resolved plan type config dict.
            If not provided, resolved from *plan_type_key*.

    Returns:
        (success, plan_number, location_description, template_type, error_message)
    """
    # Resolve plan type config from key when not provided
    if plan_type_config is None:
        try:
            plan_type_config = get_plan_type(plan_type_key)
        except ValueError as exc:
            return False, 0, "", "", str(exc)

    assert plan_type_config is not None  # guaranteed by get_plan_type or caller

    # Determine template_type for backward-compat display/registry
    template_type = plan_type_config.get("default_template", "default")

    result = create_plan_impl(
        location=location,
        subject=subject,
        template_type=template_type,
        plan_type_config=plan_type_config,
        # Inject dependencies
        ecosystem_root=ECOSYSTEM_ROOT,
        load_registry=load_registry,
        save_registry=save_registry,
        auto_close_orphaned_plans=auto_close_orphaned_plans,
        resolve_plan_location=resolve_plan_location,
        calculate_relative_location=calculate_relative_location,
        get_template=get_template,
        create_plan_file=create_plan_file,
        build_plan_registry_entry=build_plan_registry_entry,
        display_plan_created=display_plan_created,
        update_dashboard_local=update_dashboard_local,
        push_to_plans_central=push_to_plans_central,
        push_flow_to_branch_dashboard=push_flow_to_branch_dashboard,
    )

    # Handler returns 6-tuple: (success, num, loc, tmpl, error, messages)
    if len(result) == 6:
        ok, num, loc, tmpl, error, messages = result
        # Module handles display
        for msg in messages:
            msg_type = msg.get("type", "")
            if msg_type == "dim":
                console.print(f"[dim]{msg['text']}[/dim]")
            elif msg_type == "warning":
                warning(msg['text'])
            elif msg_type == "display":
                console.print(msg["text"])
        return ok, num, loc, tmpl, error

    # Fallback for 5-tuple (backward compatibility)
    return result


def handle_command(command: str, args: List[str]) -> bool:
    """
    Handle command routing for create_plan module

    THIN ORCHESTRATOR - delegates to handlers for all operations.

    Workflow:
        1. Parse arguments -> command_parser handler
        2. Execute create_plan workflow
        3. Display results -> display handler

    Args:
        command: Command name
        args: Additional arguments

    Returns:
        bool indicating success or failure of command handling
    """
    # Check if this is our command
    if command != "create":
        return False

    # Log the operation
    json_handler.log_operation(
        "plan_created",
        {"command": command, "args": args}
    )

    # STEP 1: Parse arguments (delegate to handler)
    location, subject, plan_type_key = parse_create_plan_args(args)

    # STEP 1b: Resolve plan type config (for prefix/digits in display)
    try:
        plan_type_config = get_plan_type(plan_type_key)
    except ValueError:
        plan_type_config = None

    # STEP 2: Execute workflow
    success, num, loc, tmpl, error = create_plan(
        location, subject,
        plan_type_key=plan_type_key,
        plan_type_config=plan_type_config,
    )

    # STEP 3: Display results (delegate to display handler)
    prefix = plan_type_config["prefix"] if plan_type_config else "FPLAN"
    digits = plan_type_config["digits"] if plan_type_config else 4
    result_msg = display_plan_result(
        success, num, loc, tmpl, error,
        prefix=prefix, digits=digits,
    )
    console.print(result_msg)

    # Return boolean result
    if success:
        return True
    else:
        return False


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
        print_help()
        sys.exit(0)

    # Confirm logger connection
    logger.info("Prax logger connected to create_plan")

    # Log standalone execution
    json_handler.log_operation(
        "plan_created",
        {"command": "standalone"}
    )

    # Call handle_command with default
    args = sys.argv[1:] if len(sys.argv) > 1 else []
    if args and args[0] not in ['create', 'create_plan']:
        # If first arg is not command, assume it's location (backward compatibility)
        args.insert(0, 'create')

    result = handle_command(args[0] if args else 'create', args[1:] if args else [])
    if result:
        sys.exit(0)
    else:
        sys.exit(1)
