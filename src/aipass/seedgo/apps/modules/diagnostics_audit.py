# =================== AIPass ====================
# Name: diagnostics_audit.py
# Description: System-wide Type Error Diagnostics
# Version: 1.0.0
# Created: 2026-03-05
# Modified: 2026-03-05
# =============================================

"""
System-wide Type Error Diagnostics

Runs pyright on all AIPass branches to detect type errors,
undefined variables, and other static analysis issues.

Usage:
    seedgo diagnostics           # All branches
    seedgo diagnostics @flow     # Specific branch
"""

import sys
from pathlib import Path
from typing import Dict, List

from aipass.prax import logger

# CLI service
from aipass.cli import console
from aipass.cli.apps.modules import error, warning

# JSON handler for logging
from aipass.seedgo.apps.handlers.json import json_handler

# Drone services for @ resolution

# Diagnostics handlers


def print_branch_diagnostics(result: Dict):
    """Print diagnostics for a single branch.

    Note: Used by tests/test_diagnostics_audit.py — not called in production audit pipeline.
    """
    branch = result["branch"]
    errors = result.get("total_errors", 0)
    warnings = result.get("total_warnings", 0)
    files_analyzed = result.get("total_files", 0)
    files_with_errors = result.get("files_with_errors", 0)

    # Status icon
    if errors == 0:
        status = "[green]✓[/green]"
        color = "green"
    elif errors < 10:
        status = "[yellow]⚠[/yellow]"
        color = "yellow"
    else:
        status = "[red]✗[/red]"
        color = "red"

    console.print()
    console.print(f"{status} [bold]{branch}[/bold]")
    console.print(f"  Files: {files_analyzed} analyzed, {files_with_errors} with errors")
    console.print(f"  [{color}]Errors: {errors}[/{color}]  Warnings: {warnings}")

    # Show top files with errors (clickable paths)
    if files_with_errors > 0:
        console.print("  [dim]Top files with errors:[/dim]")
        for file_result in result.get("results", [])[:5]:
            if file_result["errors"] > 0:
                file_path = file_result["file"]
                file_errors = file_result["errors"]
                console.print(f"    [red]✗[/red] {file_path} [dim]({file_errors} errors)[/dim]")

                # Show first 3 errors per file
                for diag in file_result["diagnostics"][:3]:
                    line = diag["line"]
                    msg = diag["message"][:60] + "..." if len(diag["message"]) > 60 else diag["message"]
                    console.print(f"      [dim]L{line}:[/dim] {msg}")


def print_system_summary(all_results: List[Dict]):
    """Print system-wide diagnostics summary"""
    total_branches = len(all_results)
    total_errors = sum(r.get("total_errors", 0) for r in all_results)
    total_warnings = sum(r.get("total_warnings", 0) for r in all_results)
    total_files = sum(r.get("total_files", 0) for r in all_results)
    files_with_errors = sum(r.get("files_with_errors", 0) for r in all_results)

    clean_branches = sum(1 for r in all_results if r.get("total_errors", 0) == 0)
    branches_with_errors = total_branches - clean_branches

    console.print()
    console.print("─" * 70)
    console.print("[bold]SYSTEM DIAGNOSTICS SUMMARY:[/bold]")
    console.print(f"  Total branches:        {total_branches}")
    console.print(f"  Clean branches:        {clean_branches} [green]✓[/green]")
    console.print(f"  Branches with errors:  {branches_with_errors} [red]✗[/red]")
    console.print()
    console.print(f"  Files analyzed:        {total_files}")
    console.print(f"  Files with errors:     {files_with_errors}")
    console.print(f"  Total errors:          [red]{total_errors}[/red]")
    console.print(f"  Total warnings:        [yellow]{total_warnings}[/yellow]")
    console.print()

    # Top branches by error count
    if branches_with_errors > 0:
        console.print("[bold]BRANCHES BY ERROR COUNT:[/bold]")
        sorted_results = sorted(all_results, key=lambda x: x.get("total_errors", 0), reverse=True)
        for result in sorted_results[:10]:
            if result.get("total_errors", 0) > 0:
                branch = result["branch"]
                errors = result["total_errors"]
                console.print(f"  {branch:15} [red]{errors:4} errors[/red]")

    console.print("─" * 70)
    console.print()


def handle_command(command: str, args: List[str]) -> bool:
    """
    Handle 'diagnostics' command

    Args:
        command: Command name
        args: Additional arguments

    Returns:
        True if handled, False if not this module's command
    """
    if command not in ("diagnostics", "diagnostics_audit"):
        return False

    # --help → full help
    if args and args[0] in ["--help", "-h", "help"]:
        print_help()
        return True

    # No args → introspection
    if not args:
        print_introspection()
        return True

    # Unknown argument — fail to error, not fallback
    error(f"Unknown argument: '{args[0]}'")
    warning("This module has no subcommands.")
    console.print("Diagnostics runs through the audit pipeline:")
    console.print("  [green]drone @seedgo audit aipass[/green]")
    console.print()
    handlers_dir = Path(__file__).parent.parent / "handlers" / "diagnostics"
    console.print(f"[dim]Handler: {handlers_dir}[/dim]")
    console.print(f"[dim]Module:  {Path(__file__)}[/dim]")
    console.print()
    return True


def print_introspection():
    """Display module info when run without arguments (Seedgo pattern)"""
    console.print()
    console.print("[bold cyan]Diagnostics Audit Module[/bold cyan]")
    console.print("[dim]System-wide type error detection using pyright[/dim]")
    console.print()

    console.print("[yellow]Connected Handlers:[/yellow]")
    console.print("  [cyan]handlers/diagnostics/[/cyan]")
    console.print("    [dim]- discovery.py (discover_branches — finds all AIPass branches)[/dim]")
    console.print()

    console.print("[yellow]How It Works:[/yellow]")
    console.print("  Diagnostics checking runs through the audit pipeline:")
    console.print("  [green]drone @seedgo audit aipass[/green]         [dim]# All branches[/dim]")
    console.print("  [green]drone @seedgo audit aipass @flow[/green]   [dim]# Single branch[/dim]")
    console.print()

    console.print("[yellow]Next:[/yellow]")
    console.print("  [green]drone @seedgo diagnostics_audit --help[/green]   [dim]# Full usage guide[/dim]")
    console.print()


def print_help():
    """Print help information"""
    console.print()
    console.print("[bold cyan]Diagnostics Audit Module[/bold cyan]")
    console.print("System-wide type error detection using pyright")
    console.print()

    console.print("[yellow]COMMANDS:[/yellow]")
    console.print(
        "  [green]drone @seedgo diagnostics_audit[/green]            [dim]Scan all branches for type errors[/dim]"
    )
    console.print("  [green]drone @seedgo diagnostics_audit @<branch>[/green]  [dim]Scan specific branch[/dim]")
    console.print()

    console.print("[yellow]EXAMPLES:[/yellow]")
    console.print("  [green]drone @seedgo diagnostics_audit[/green]")
    console.print("  [green]drone @seedgo diagnostics_audit @flow[/green]")
    console.print("  [green]drone @seedgo diagnostics_audit @spawn[/green]")
    console.print()

    console.print("[yellow]WHAT IT CHECKS:[/yellow]")
    console.print("  - Type errors (Pylance/pyright)")
    console.print("  - Undefined variables")
    console.print("  - Import errors")
    console.print("  - Argument type mismatches")
    console.print()


if __name__ == "__main__":
    # Handle help flag or no arguments
    if len(sys.argv) == 1 or (len(sys.argv) > 1 and sys.argv[1] in ["--help", "-h", "help"]):
        print_help()
        sys.exit(0)

    # Confirm Prax logger connection
    logger.info("Prax logger connected to diagnostics_audit")

    # Log standalone execution
    json_handler.log_operation("diagnostics_run", {"command": "standalone", "args": sys.argv[1:]})

    # Run diagnostics
    handle_command("diagnostics", sys.argv[1:])
