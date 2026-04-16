# =================== AIPass ====================
# Name: test_map.py
# Description: Custom Function Test Coverage Map Module
# Version: 1.0.0
# Created: 2026-03-24
# Modified: 2026-03-24
# =============================================

"""
Custom Function Test Coverage Map Module

AST-scans a branch's apps/modules/ and apps/handlers/ for public functions,
cross-references against tests/, and outputs a coverage map showing which
custom functions have tests and which don't.

Run: drone @seedgo test_map @branch
"""

from typing import List

# =============================================================================
# INFRASTRUCTURE SETUP
# =============================================================================

# IMPORTS
# =============================================================================

# Prax logger (system-wide, always first)
from aipass.prax import logger

# CLI services (display/output formatting)
from aipass.cli import console, header
from aipass.cli.apps.modules import error

# JSON handler for tracking
from aipass.seedgo.apps.handlers.json import json_handler

# Handler (implementation)
from aipass.seedgo.apps.handlers.test_map.function_scanner import scan_branch

# Drone services for @ resolution
from aipass.drone.apps.modules import normalize_branch_arg

# Branch discovery
from aipass.seedgo.apps.handlers.audit.discovery import discover_branches


# =============================================================================
# COMMAND HANDLER
# =============================================================================


def print_introspection() -> None:
    """Display module info and connected handlers."""
    console.print()
    console.print("[bold cyan]test_map Module[/bold cyan]")
    console.print("Custom function test coverage mapping")
    console.print()

    console.print("[yellow]Connected Handlers:[/yellow]")
    console.print("  [dim]- test_map/function_scanner.py (AST-based public function scanner)[/dim]")
    console.print()

    console.print("[yellow]What It Does:[/yellow]")
    console.print("  [dim]Scans apps/modules/ and apps/handlers/ for public functions,[/dim]")
    console.print("  [dim]cross-references against tests/, shows what has tests and what doesn't.[/dim]")
    console.print("  [dim]Excludes standard infrastructure (json_handler, CLI routing).[/dim]")
    console.print()

    console.print("[yellow]Next:[/yellow]")
    console.print("  [green]drone @seedgo test_map @flow[/green]        [dim]# Scan a branch[/dim]")
    console.print("  [green]drone @seedgo test_map --help[/green]       [dim]# Full usage guide[/dim]")
    console.print()


def handle_command(command: str, args: List[str]) -> bool:
    """Route test_map command."""
    if command not in ("test_map",):
        return False

    if not args:
        print_introspection()
        return True

    if args[0] in ("--help", "-h", "help"):
        print_help()
        return True

    # Expect @branch argument
    branch_arg = args[0]
    if not branch_arg.startswith("@"):
        error(
            f"Branch name must use @ prefix: '@{branch_arg}'",
            suggestion=f"Usage: drone @seedgo test_map @{branch_arg}",
        )
        return True

    branch_name = normalize_branch_arg(branch_arg)

    # Resolve branch path
    branches = discover_branches(include_private=True)
    branch_entry = None
    for b in branches:
        if b["name"].lower() == branch_name:
            branch_entry = b
            break

    if not branch_entry:
        error(
            f"Branch not found: @{branch_name}",
            suggestion="Run: drone systems",
        )
        return True

    branch_path = branch_entry["path"]

    # Run the scan
    result = scan_branch(branch_path)

    # Display results
    _display_coverage_map(result)

    json_handler.log_operation(
        "test_map_scan",
        {
            "branch": branch_name,
            "total": result["total_functions"],
            "tested": result["tested_functions"],
            "pct": result["coverage_pct"],
        },
    )

    return True


# =============================================================================
# DISPLAY
# =============================================================================


def _display_coverage_map(result: dict) -> None:
    """Render the coverage map with Rich formatting."""
    branch = result["branch"]
    total = result["total_functions"]
    tested = result["tested_functions"]
    pct = result["coverage_pct"]

    console.print()
    header(f"@{branch} CUSTOM FUNCTION COVERAGE")
    console.print()

    if total == 0:
        console.print("[dim]No custom public functions found in apps/modules/ or apps/handlers/[/dim]")
        console.print()
        return

    for file_entry in result["files"]:
        rel_path = file_entry["relative_path"]
        funcs = file_entry["functions"]
        console.print(f"[cyan]{rel_path}:[/cyan]")

        for func in funcs:
            if func["tested"]:
                test_note = f" — tested in {func['test_file']}" if func["test_file"] else " — tested"
                console.print(f"  [green]✓[/green] {func['name']}(){test_note}")
            else:
                console.print(f"  [red]✗[/red] {func['name']}() — [dim]NOT TESTED[/dim]")

        console.print()

    # Summary
    style = "green" if pct >= 50 else "yellow" if pct >= 25 else "red"
    console.print(f"[bold]Summary:[/bold] [{style}]{tested}/{total}[/{style}] custom functions tested ({pct}%)")
    console.print()


def print_help() -> None:
    """Full usage guide."""
    console.print()
    header("TEST MAP — USAGE")
    console.print()

    console.print("[yellow]Description:[/yellow]")
    console.print("  AST-scans a branch for custom public functions and maps them")
    console.print("  against existing tests. Shows test coverage opportunities.")
    console.print()

    console.print("[yellow]Commands:[/yellow]")
    console.print("  [green]drone @seedgo test_map[/green]            [dim]Module info[/dim]")
    console.print("  [green]drone @seedgo test_map @branch[/green]    [dim]Scan a branch[/dim]")
    console.print("  [green]drone @seedgo test_map --help[/green]     [dim]This help[/dim]")
    console.print()

    console.print("[yellow]What It Scans:[/yellow]")
    console.print("  [dim]• apps/modules/*.py — module-level public functions[/dim]")
    console.print("  [dim]• apps/handlers/**/*.py — handler-level public functions[/dim]")
    console.print()

    console.print("[yellow]What It Excludes:[/yellow]")
    console.print("  [dim]• Private functions (_name)[/dim]")
    console.print("  [dim]• CLI routing (handle_command, print_introspection, print_help, main)[/dim]")
    console.print("  [dim]• json_handler standard functions (covered by test_quality checker)[/dim]")
    console.print()

    console.print("[yellow]Examples:[/yellow]")
    console.print("  [green]drone @seedgo test_map @flow[/green]")
    console.print("  [green]drone @seedgo test_map @api[/green]")
    console.print()


# =============================================================================
# STANDALONE EXECUTION
# =============================================================================

if __name__ == "__main__":
    logger.info("[TEST_MAP] Module loaded directly")
    json_handler.log_operation("module_loaded", {"module": "test_map"})
    print_introspection()
