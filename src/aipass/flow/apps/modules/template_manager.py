# =================== AIPass ====================
# Name: template_manager.py
# Description: Template registry management module
# Version: 1.0.0
# Created: 2026-03-18
# Modified: 2026-03-18
# =============================================

"""
Template Manager Module - Thin Orchestrator

Orchestrates template registration commands by delegating to handlers.
Module contains NO business logic - only workflow coordination and display.

Workflow:
    1. Parse arguments
    2. Route to appropriate handler
    3. Display results via console

Usage:
    From flow.py: drone @flow templates | register | unregister | scan
    Standalone: drone @flow templates | register | unregister | scan
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
from aipass.cli.apps.modules import console, error, warning, success

# Template registry handlers
from aipass.flow.apps.handlers.template.registry_ops import (
    load_registry,
    add_type,
    remove_type,
    scan_unregistered,
)

# =============================================
# CONFIGURATION
# =============================================

MODULE_NAME = "template_manager"

# =============================================
# INTROSPECTION
# =============================================


def print_introspection():
    """Display module info, registered types, and connected handlers"""
    registry = load_registry()
    _display_registered_types(registry)

    console.print("[yellow]Connected Handlers:[/yellow]")
    console.print()
    console.print("  [cyan]handlers/template/[/cyan]")
    console.print("    [dim]- registry_ops.py (CRUD operations)[/dim]")
    console.print("    [dim]- plan_type_loader.py (discovery integration)[/dim]")
    console.print()

    console.print("[dim]Run 'drone @flow templates --help' for usage[/dim]")
    console.print()


def print_help():
    """Print help information for template_manager module"""
    console.print()
    console.print("[bold cyan]template_manager[/bold cyan] — Manage plan type templates")
    console.print()
    console.print("[yellow]USAGE:[/yellow]")
    console.print("  drone @flow templates                    Show registered types")
    console.print("  drone @flow register <dir> <PREFIX>      Register new plan type")
    console.print("  drone @flow unregister <dir>             Remove plan type registration")
    console.print("  drone @flow scan                         Find unregistered template directories")
    console.print()
    console.print("[yellow]EXAMPLES:[/yellow]")
    console.print("  [dim]# Register testing/ as TPLAN[/dim]")
    console.print("  drone @flow register testing TPLAN")
    console.print()
    console.print("  [dim]# Unregister testing[/dim]")
    console.print("  drone @flow unregister testing")
    console.print()
    console.print("  [dim]# Show all types + templates[/dim]")
    console.print("  drone @flow templates")
    console.print()
    console.print("  [dim]# Find new directories[/dim]")
    console.print("  drone @flow scan")
    console.print()


# =============================================
# DISPLAY HELPERS
# =============================================


def _suggest_prefix(dir_name: str) -> str:
    """Generate a suggested prefix from a directory name.

    Takes the first word of the dir name (split on underscores),
    uppercases the first letter, and appends 'PLAN'.
    E.g. 'testing' -> 'TPLAN', 'skills_plans' -> 'SPLAN'.
    """
    first_word = dir_name.split("_")[0]
    return first_word[0].upper() + "PLAN" if first_word else "XPLAN"


def _display_registered_types(registry: dict) -> None:
    """Display all registered plan types with their details."""
    types = registry.get("types", {})

    if not types:
        warning("No plan types registered")
        console.print()
        console.print("[dim]Register one with: drone @flow register <dir> <PREFIX>[/dim]")
        console.print()
        return

    console.print()
    console.print("[bold cyan]Registered Plan Types[/bold cyan]")
    console.print()

    for dir_name, type_info in sorted(types.items()):
        prefix = type_info.get("prefix", "???")
        shorthand = type_info.get("shorthand", prefix.lower())
        registered = type_info.get("created", "unknown")

        console.print(f"  [bold green]{dir_name}/[/bold green]")
        console.print(f"    Prefix:     [cyan]{prefix}[/cyan]")
        console.print(f"    Shorthand:  [cyan]{shorthand}[/cyan]")
        console.print(f"    Registered: [dim]{registered}[/dim]")

        # Scan the actual directory for .md templates
        templates_dir = FLOW_ROOT / "templates" / dir_name
        if templates_dir.is_dir():
            md_files = sorted(p.stem for p in templates_dir.iterdir() if p.suffix == ".md")
            if md_files:
                console.print(f"    Templates:  [yellow]{', '.join(md_files)}[/yellow]")
            else:
                console.print("    Templates:  [dim]none found[/dim]")
        else:
            console.print("    Templates:  [dim]directory missing[/dim]")

        console.print()


# =============================================
# COMMAND HANDLER
# =============================================


def handle_command(command: str, args: List[str]) -> bool:
    """
    Handle command routing for template_manager module

    Routes:
        templates  - Show registered types
        register   - Register new plan type
        unregister - Remove plan type registration
        scan       - Find unregistered template directories

    Args:
        command: Command name
        args: Additional arguments

    Returns:
        True if command was recognized, False if not
    """
    # ---- templates ----
    if command == "templates":
        if not args:
            print_introspection()
            return True

        # Intercept help before arg parsing
        if args[0] in ["--help", "-h", "help"]:
            print_help()
            return True

        # Log the operation
        json_handler.log_operation(
            "templates_listed",
            {"command": command, "args": args},
        )

        registry = load_registry()
        _display_registered_types(registry)
        return True

    # ---- register ----
    if command == "register":
        if not args or len(args) < 2:
            error("Usage: drone @flow register <dir> <PREFIX>")
            console.print()
            console.print("[dim]Example: drone @flow register testing TPLAN[/dim]")
            console.print()
            return True

        dir_name = args[0]
        prefix = args[1]

        # Validate PREFIX convention: uppercase and ends with PLAN
        if not prefix.isupper() or not prefix.endswith("PLAN"):
            error(f"PREFIX must be uppercase and end with 'PLAN' (got '{prefix}')")
            console.print()
            console.print("[dim]Convention: first letter of dir + 'PLAN' (e.g., testing -> TPLAN)[/dim]")
            console.print()
            return True

        # Log the operation
        json_handler.log_operation(
            "type_registered",
            {"dir_name": dir_name, "prefix": prefix},
        )

        registered = add_type(dir_name, prefix)

        if registered:
            success(f"Registered '{dir_name}' with prefix {prefix}")
            console.print()
            console.print(f'[dim]Create plans with: drone @flow create . "subject" {prefix.lower()}[/dim]')
            console.print()
        else:
            error(f"Failed to register '{dir_name}' — check logs for details")
            console.print()

        return True

    # ---- unregister ----
    if command == "unregister":
        if not args:
            error("Usage: drone @flow unregister <dir>")
            console.print()
            console.print("[dim]Example: drone @flow unregister testing[/dim]")
            console.print()
            return True

        dir_name = args[0]

        # Log the operation
        json_handler.log_operation(
            "type_unregistered",
            {"dir_name": dir_name},
        )

        removed = remove_type(dir_name)

        if removed:
            success(f"Unregistered '{dir_name}'")
            console.print()
        else:
            error(f"Failed to unregister '{dir_name}' — check logs for details")
            console.print()

        return True

    # ---- scan ----
    if command == "scan":
        # Log the operation
        json_handler.log_operation(
            "templates_scanned",
            {"command": command},
        )

        console.print()
        console.print("[bold]Scanning for unregistered template directories...[/bold]")
        console.print()

        unregistered = scan_unregistered()

        if not unregistered:
            console.print("[green]All template directories are registered.[/green]")
            console.print()
            return True

        warning(f"Found {len(unregistered)} unregistered directory(ies):")
        console.print()

        for entry in unregistered:
            dir_name = str(entry.get("dir_name", "unknown"))
            template_count = entry.get("template_count", 0)
            suggested = _suggest_prefix(dir_name)

            console.print(f"  [bold]{dir_name}/[/bold]  ({template_count} template(s))")
            console.print(f"    [dim]drone @flow register {dir_name} {suggested}[/dim]")
            console.print()

        return True

    # Not our command
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
    if len(sys.argv) > 1 and sys.argv[1] in ["--help", "-h", "help"]:
        print_help()
        sys.exit(0)

    # Confirm logger connection
    logger.info("Prax logger connected to template_manager")

    # Log standalone execution
    json_handler.log_operation(
        "template_manager",
        {"command": "standalone"},
    )

    # Route through handle_command
    args = sys.argv[1:] if len(sys.argv) > 1 else []
    cmd = args[0] if args else "templates"
    cmd_args = args[1:] if len(args) > 1 else []

    result = handle_command(cmd, cmd_args)

    if result:
        sys.exit(0)
    else:
        # Unknown command -- show help
        print_help()
        sys.exit(1)
