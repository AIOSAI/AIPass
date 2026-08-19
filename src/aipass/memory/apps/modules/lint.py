# =================== AIPass ====================
# Name: lint.py
# Description: Lint module — CLI routing for entry limit auditing
# Version: 1.0.0
# Created: 2026-06-13
# Modified: 2026-06-13
# =============================================

"""
Lint Module — Entry Limit Violation Scanner

Thin CLI routing layer that discovers branches via the registry,
delegates scanning to the lint handler, and formats results for
the console.

Strictly **read-only** — never writes, modifies, truncates, or
deletes any file.

Usage:
    drone @memory lint              # Scan all branches
    drone @memory lint @devpulse    # Scan one branch
"""

import os
import sys
from typing import Any

if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8", errors="replace")

from aipass.prax import logger
from aipass.cli.apps.modules import console, error, success, warning
from aipass.memory.apps.handlers.json import json_handler
from aipass.memory.apps.handlers.cli.help_flags import wants_help

# Handler import (same package family — json handlers)
from aipass.memory.apps.handlers.json.lint_handler import run_lint

# Cross-handler access for branch discovery (module layer bridges handlers)
from aipass.memory.apps.handlers.monitor.detector import _read_registry


# =============================================================================
# COMMAND HANDLER
# =============================================================================


def handle_command(command: str, args: list[str]) -> bool:
    """Handle lint commands with seedgo-compliant introspection.

    Routing:
        lint (no args)            -> print_introspection()
        lint --help / -h / help   -> print_help()
        lint @branch              -> scan one branch
        lint run                  -> scan all branches
        lint run @branch          -> scan one branch

    Args:
        command: Command name.
        args: Additional arguments.

    Returns:
        True if command handled, False otherwise.
    """
    if command != "lint":
        return False

    # No args -> introspection (seedgo standard)
    if not args:
        print_introspection()
        return True

    # Help — a flag ANYWHERE wins; lint takes no free-text arguments,
    # so a bare `help` counts in any slot too
    if wants_help(args, allow_bare_word=True):
        print_help()
        return True

    # Parse optional @branch filter
    branch_filter = _extract_branch(args)

    # "run" subcommand is accepted but optional — lint always runs
    filtered_args = [a for a in args if a != "run" and not a.startswith("@")]

    if filtered_args:
        error(
            f"Unknown lint argument: {filtered_args[0]}",
            suggestion="Run 'drone @memory lint help' for usage",
        )
        return True

    _execute_lint(branch_filter)
    return True


# =============================================================================
# ARGUMENT HELPERS
# =============================================================================


def _extract_branch(args: list[str]) -> str | None:
    """Extract @branch from args, return branch name or None."""
    for arg in args:
        if arg.startswith("@"):
            return arg[1:]
    return None


# =============================================================================
# LINT EXECUTION
# =============================================================================


def _execute_lint(branch_filter: str | None = None) -> None:
    """Run the lint scan and display results.

    Args:
        branch_filter: If provided, only lint this branch.
    """
    # Branch discovery happens in the module layer (bridges handlers)
    try:
        branches = _read_registry()
    except Exception as exc:
        logger.warning(f"[lint] Failed to read registry: {exc}")
        error(f"Failed to read registry: {exc}")
        return

    if not branches:
        warning("No branches found in registry")
        return

    # An unknown branch must not read as a clean bill of health. run_lint
    # matches case-insensitively, so the guard has to as well.
    if branch_filter:
        known = {str(b.get("name", "")).lower() for b in branches}
        if branch_filter.lower() not in known:
            logger.warning(f"[lint] Unknown branch requested: {branch_filter}")
            error(
                f"Unknown branch: @{branch_filter}",
                suggestion="Run 'drone systems' to list branches, or 'drone @memory lint run' to scan all",
            )
            return

    result = run_lint(branches, branch_filter=branch_filter)

    if not result.get("success"):
        error(result.get("error", "Unknown lint error"))
        return

    _display_results(result, branch_filter)


# =============================================================================
# DISPLAY
# =============================================================================


def _display_results(result: dict[str, Any], branch_filter: str | None) -> None:
    """Format and display lint results via Rich console.

    Args:
        result: Result dict from ``run_lint``.
        branch_filter: The branch filter used (for display context).
    """
    violations = result.get("violations", [])
    scanned = result.get("branches_scanned", 0)
    skipped = result.get("branches_skipped", 0)
    total = result.get("total_violations", 0)

    console.print()

    if not violations:
        scope = f"@{branch_filter}" if branch_filter else "all branches"
        success(f"No violations found across {scope} ({scanned} scanned)")
        console.print()
        return

    # Per-violation detail (sorted worst-first by handler)
    warning(f"{total} violation(s) found")
    console.print()

    current_branch: str | None = None
    branch_count = 0

    for v in violations:
        branch = v["branch"]
        if branch != current_branch:
            if current_branch is not None:
                console.print()
            console.print(f"  [bold cyan]{branch}[/bold cyan]")
            current_branch = branch
            branch_count = 0

        branch_count += 1
        console.print(
            f"    [red]![/red] {v['file']}:{v['container']}/{v['key']} "
            f"[dim]({v['entry_type']})[/dim] "
            f"{v['length']}/{v['cap']} chars "
            f"[red]+{v['over_by']} over[/red]"
        )

    console.print()
    console.print(f"[dim]Scanned {scanned} branch(es), skipped {skipped}[/dim]")
    console.print()

    json_handler.log_operation(
        "lint_display",
        {"total_violations": total, "branches_scanned": scanned},
        module_name="lint",
    )


# =============================================================================
# INTROSPECTION
# =============================================================================


def print_introspection() -> None:
    """Display module introspection (seedgo standard).

    Called when ``lint`` is invoked with no arguments.
    """
    console.print()
    console.print("[bold cyan]lint Module[/bold cyan]")
    console.print("Audits .trinity entries for over-limit character violations (read-only)")
    console.print()

    console.print("[yellow]Connected Handlers:[/yellow]")
    console.print("  [cyan]handlers/json/[/cyan]  [dim]lint_handler.py, entry_limits.py[/dim]")
    console.print()

    console.print("[yellow]Next:[/yellow]")
    console.print("  [green]drone @memory lint run[/green]          [dim]# Scan all branches[/dim]")
    console.print("  [green]drone @memory lint @devpulse[/green]    [dim]# Scan one branch[/dim]")
    console.print("  [green]drone @memory lint help[/green]         [dim]# Full usage guide[/dim]")
    console.print()


def print_help() -> None:
    """Display lint module help."""
    console.print()
    console.print("[bold cyan]Lint Module - Entry Limit Violation Scanner[/bold cyan]")
    console.print()
    console.print("[bold]USAGE:[/bold]")
    console.print("  drone @memory lint              Scan all branches")
    console.print("  drone @memory lint @<branch>    Scan a specific branch")
    console.print("  drone @memory lint run          Scan all branches (explicit)")
    console.print()
    console.print("[bold]WHAT IT DOES:[/bold]")
    console.print("  Reads .trinity/local.json and .trinity/observations.json for every")
    console.print("  registered branch. Checks each entry against configured character")
    console.print("  caps from memory.config.json. Reports violations sorted worst-first.")
    console.print()
    console.print("[bold]NOTE:[/bold]")
    console.print("  This command is strictly [green]read-only[/green]. It never modifies any file.")
    console.print()
