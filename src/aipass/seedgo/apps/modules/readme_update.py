# =================== AIPass ====================
# Name: readme_update.py
# Description: README Auto-Update Module
# Version: 1.0.0
# Created: 2026-03-05
# Modified: 2026-03-05
# =============================================

"""
README Auto-Update Module

On-demand updating of auto-generated README sections for any AIPass branch.
Uses readme_generator handler to produce content for sections marked with
<!-- AUTO:SECTION --> comment markers in README.md files.

Run: seedgo readme update @branch
"""

import sys
from pathlib import Path
from typing import List

# =============================================================================
# INFRASTRUCTURE SETUP
# =============================================================================

# IMPORTS
# =============================================================================

# Prax logger (system-wide, always first)
from aipass.prax import logger
# JSON handler for tracking
from aipass.seedgo.apps.handlers.json import json_handler

# CLI services (display/output formatting)
from aipass.cli import console, header
from aipass.cli.apps.modules import error as display_error, warning

# Handler (implementation) — readme operations
from aipass.seedgo.apps.handlers.readme.readme_ops import (
    load_generator,
    resolve_targets,
    SECTION_NAMES,
)


# =============================================================================
# COMMAND HANDLER
# =============================================================================

def print_introspection() -> None:
    """Display module info and connected handlers."""
    console.print()
    console.print("[bold cyan]readme_update Module[/bold cyan]")
    console.print("On-demand updating of auto-generated README sections for any AIPass branch")
    console.print()

    console.print("[yellow]Connected Handlers:[/yellow]")
    console.print("  [cyan]handlers/standards/[/cyan]")
    console.print("    [dim]- readme_ops.py (load_generator, resolve_targets, SECTION_NAMES)[/dim]")
    console.print()
    console.print("  [cyan]handlers/json/[/cyan]")
    console.print("    [dim]- json_handler.py (log_operation — readme update tracking)[/dim]")
    console.print()

    console.print("[yellow]External Dependencies:[/yellow]")
    console.print("  [dim]- aipass.prax (logger)[/dim]")
    console.print("  [dim]- aipass.cli (console, header)[/dim]")
    console.print()

    console.print("[yellow]Next:[/yellow]")
    console.print("  [green]drone @seedgo readme update @flow[/green]     [dim]# Update a branch README[/dim]")
    console.print("  [green]drone @seedgo readme check @flow[/green]      [dim]# Dry run[/dim]")
    console.print("  [green]drone @seedgo readme --help[/green]            [dim]# Full usage guide[/dim]")
    console.print()


def handle_command(command: str, args: List[str]) -> bool:
    """
    Handle 'readme' command.

    Args:
        command: Command name
        args: Additional arguments

    Returns:
        True if handled, False if not this module's command
    """
    if command not in ("readme", "readme_update"):
        return False

    if not args:
        print_introspection()
        return True

    if "--help" in args or "-h" in args:
        print_help()
        return True

    # Subcommands: update, check
    subcommand = args[0]
    remaining_args = args[1:] if len(args) > 1 else []

    if subcommand == "update":
        _handle_update(remaining_args)
    elif subcommand == "check":
        _handle_check(remaining_args)
    else:
        # Unknown subcommand — fail to error, not fallback
        console.print(f"\n[red]Unknown subcommand:[/red] '{subcommand}'")
        console.print("[yellow]Valid subcommands:[/yellow] update, check")
        console.print()
        console.print("  [green]drone @seedgo readme update @branch[/green]   [dim]# Update README[/dim]")
        console.print("  [green]drone @seedgo readme check @branch[/green]    [dim]# Dry run[/dim]")
        console.print()
        console.print(f"[dim]Module: {Path(__file__)}[/dim]")
        console.print()

    return True


# =============================================================================
# SUBCOMMAND ORCHESTRATION
# =============================================================================

def _handle_update(args: List[str]) -> None:
    """Orchestrate the 'update' subcommand"""
    if load_generator is None:
        console.print("[red]readme_ops handler not available[/red]")
        console.print("[dim]Handler is in .sorting_unprocessed/ — needs migration to handlers/[/dim]")
        return
    generator = load_generator()
    if not generator:
        console.print("[red]Failed to load README generator[/red]")
        return

    branches, error = resolve_targets(args)
    if error:
        _print_target_error(error)
        return

    json_handler.log_operation(
        "readme_update_started",
        {"targets": [b['name'] for b in branches]}
    )

    total_updated = 0

    for branch in branches:
        branch_name = branch['name']
        branch_path = branch['path']

        console.print()
        console.print(f"[bold cyan]README Update: {branch_name}[/bold cyan]")

        readme_path = Path(branch_path) / 'README.md'
        if not readme_path.exists():
            warning(f"No README.md found at {branch_path}")
            continue

        try:
            result = generator.update_readme_auto_sections(branch_path, dry_run=False)
            _print_result(result)
            if result.get('updated'):
                total_updated += 1
        except Exception as e:
            display_error(f"Error: {e}")
            logger.error(f"README update failed for {branch_name}: {e}")

    if len(branches) > 1:
        console.print()
        console.print(f"[dim]Updated {total_updated}/{len(branches)} READMEs[/dim]")

    json_handler.log_operation(
        "readme_update_completed",
        {"branches_processed": len(branches), "branches_updated": total_updated}
    )


def _handle_check(args: List[str]) -> None:
    """Orchestrate the 'check' subcommand (dry run)"""
    if load_generator is None:
        console.print("[red]readme_ops handler not available[/red]")
        console.print("[dim]Handler is in .sorting_unprocessed/ — needs migration to handlers/[/dim]")
        return
    generator = load_generator()
    if not generator:
        console.print("[red]Failed to load README generator[/red]")
        return

    branches, error = resolve_targets(args)
    if error:
        _print_target_error(error)
        return

    for branch in branches:
        branch_name = branch['name']
        branch_path = branch['path']

        console.print()
        console.print(f"[bold cyan]README Check: {branch_name}[/bold cyan]")

        readme_path = Path(branch_path) / 'README.md'
        if not readme_path.exists():
            warning(f"No README.md found at {branch_path}")
            continue

        try:
            result = generator.update_readme_auto_sections(branch_path, dry_run=True)
            _print_result(result, is_check=True)
        except Exception as e:
            display_error(f"Error: {e}")
            logger.error(f"README check failed for {branch_name}: {e}")


# =============================================================================
# DISPLAY HELPERS
# =============================================================================

def _print_target_error(err_code: str) -> None:
    """Display target resolution errors"""
    if err_code == "no_args":
        warning("Usage: drone @seedgo readme update @branch")
        console.print("[dim]Use @all to update all branches[/dim]")
    elif err_code == "no_branches":
        display_error("No branches found in registry")
    elif err_code.startswith("not_found:"):
        target = err_code.split(":", 1)[1]
        display_error(f"Branch '{target}' not found in registry")


def _print_result(result: dict, is_check: bool = False) -> None:
    """Display formatted results of an update or check operation"""
    updated = result.get('updated', [])
    missing = result.get('missing_markers', [])
    errors = result.get('errors', [])

    if errors:
        for err in errors:
            console.print(f"  [red]Error: {err}[/red]")
        return

    for section_key, display_name in SECTION_NAMES.items():
        if section_key in updated:
            if is_check:
                console.print(f"  [yellow]Would update[/yellow] {display_name} - content differs")
            else:
                console.print(f"  [green]Updated[/green] {display_name}")
        elif section_key in missing:
            console.print(f"  [dim]Skipped[/dim]  {display_name} - no marker found")
        else:
            if is_check:
                console.print(f"  [green]Up to date[/green] {display_name}")


def print_help():
    """Print help information"""
    console.print()
    header("README Auto-Update")
    console.print()
    console.print("[yellow]COMMANDS:[/yellow]")
    console.print("  [green]drone @seedgo readme update @branch[/green]    [dim]Update auto-generated sections[/dim]")
    console.print("  [green]drone @seedgo readme update @all[/green]       [dim]Update all branch READMEs[/dim]")
    console.print("  [green]drone @seedgo readme check @branch[/green]     [dim]Dry run - show what would change[/dim]")
    console.print()
    console.print("[yellow]AUTO-GENERATED SECTIONS:[/yellow]")
    console.print("  TREE          Directory structure")
    console.print("  MODULES       Module list from apps/modules/")
    console.print("  COMMANDS      Commands from --help output")
    console.print("  HEADER        Branch info from .trinity/passport.json")
    console.print("  LAST_UPDATED  Timestamp")
    console.print()
    console.print("[dim]Sections are marked with <!-- AUTO:NAME --> comments in README.md[/dim]")
    console.print("[dim]Commands: readme, --help[/dim]")


if __name__ == "__main__":
    # Handle help flag
    if len(sys.argv) > 1 and sys.argv[1] in ['--help', '-h', 'help']:
        print_help()
        sys.exit(0)

    # Confirm Prax logger connection
    logger.info("Prax logger connected to readme_update")

    # Log standalone execution
    json_handler.log_operation(
        "readme_update_run",
        {"command": "standalone", "args": sys.argv[1:]}
    )

    # Run command
    handle_command("readme", sys.argv[1:])
