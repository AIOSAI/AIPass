# =================== AIPass ====================
# Name: repair.py
# Description: Project structure repair — thin CLI layer for move, cleanup, scan
# Version: 1.0.0
# Created: 2026-05-15
# Modified: 2026-05-15
# =============================================

"""Repair orchestrator for project structure fixes.

Thin CLI module that parses arguments and delegates to the repair handler.
All implementation logic lives in apps/handlers/repair_ops.py.
"""

from pathlib import Path

from aipass.prax import logger

from aipass.cli.apps.modules import console, header, error, warning

from aipass.spawn.apps.handlers.repair_ops import (
    move_branch,
    cleanup_pollution,
    repair_project,
)
from aipass.spawn.apps.handlers.json import json_handler


def print_introspection():
    """Display module introspection info."""
    console.print()
    console.print("[bold cyan]repair Module[/bold cyan]")
    console.print("Project structure repair — move branches, clean pollution, fix registries")
    console.print()
    console.print("[yellow]Connected Handlers:[/yellow]")
    console.print("  [cyan]handlers/[/cyan]")
    console.print("    [dim]- repair_ops.py (move_branch, cleanup_pollution, repair_project)[/dim]")
    console.print()


# =============================================================================
# DRONE ROUTING
# =============================================================================


def handle_command(command: str, args: list) -> bool:
    """Handle commands routed by the entry point."""
    if command != "repair":
        return False

    if not args:
        print_introspection()
        return True

    if "--help" in args:
        _print_help()
        return True

    return handle_repair(args) == 0


# =============================================================================
# PUBLIC API
# =============================================================================


def handle_repair(args: list[str]) -> int:
    """Parse args and execute repair.

    Args patterns:
        ["<project_path>"]                          -> scan and report
        ["<project_path>", "--dry-run"]              -> scan only
        ["--relocate", "@branch", "new/path"]        -> move branch
        ["<project_path>", "--clean-pollution"]       -> archive duplicates

    Returns exit code (0=success, 1=failure).
    """
    if "--help" in args or "-h" in args:
        _print_help()
        return 0

    if not args:
        _print_help()
        return 1

    apply = "--apply" in args
    dry_run = not apply

    if "--relocate" in args:
        return _handle_relocate(args, dry_run)

    if "--clean-pollution" in args:
        return _handle_clean_pollution(args, dry_run)

    return _handle_scan(args, dry_run)


# =============================================================================
# SUBCOMMAND HANDLERS
# =============================================================================


def _handle_relocate(args, dry_run):
    """Handle --relocate @branch new/path [--relocate-artifacts]."""
    flags = {"--dry-run", "--apply", "--relocate", "--relocate-artifacts"}
    positional = [a for a in args if a not in flags]
    relocate_artifacts = "--relocate-artifacts" in args

    if len(positional) < 2:
        error("--relocate requires @branch and new_path")
        warning("Usage: drone @spawn repair --relocate @branch src/pkg/branch [--relocate-artifacts] [--dry-run]")
        return 1

    branch_name = positional[0].lstrip("@").lower()
    new_path = positional[1]
    registry_path = positional[2] if len(positional) > 2 else None

    try:
        result = move_branch(
            branch_name,
            new_path,
            registry_path=registry_path,
            dry_run=dry_run,
            relocate_artifacts=relocate_artifacts,
        )
    except Exception as exc:
        logger.error("[repair] Unexpected error relocating %s: %s", branch_name, exc)
        error(f"Error relocating {branch_name}: {exc}")
        return 1

    _print_move_result(result, dry_run)

    if result.get("success") and not dry_run:
        json_handler.log_operation("repair_relocate", data={"branch": branch_name, "new_path": new_path})

    return 0 if result.get("success") else 1


def _handle_clean_pollution(args, dry_run):
    """Handle --clean-pollution <project_path>."""
    flags = {"--dry-run", "--apply", "--clean-pollution"}
    positional = [a for a in args if a not in flags]

    if not positional:
        error("project path required")
        return 1

    project_path = Path(positional[0]).resolve()

    try:
        result = cleanup_pollution(project_path, dry_run=dry_run)
    except Exception as exc:
        logger.error("[repair] Unexpected error cleaning pollution: %s", exc)
        error(f"Error cleaning pollution: {exc}")
        return 1

    _print_pollution_result(result, dry_run)
    return 0 if result.get("success") else 1


def _handle_scan(args, dry_run):
    """Handle default scan mode — report structural issues."""
    flags = {"--dry-run", "--apply"}
    positional = [a for a in args if a not in flags]

    if not positional:
        error("project path required")
        return 1

    project_path = Path(positional[0]).resolve()

    try:
        result = repair_project(project_path, dry_run=dry_run)
    except Exception as exc:
        logger.error("[repair] Unexpected error scanning project: %s", exc)
        error(f"Error scanning project: {exc}")
        return 1

    _print_scan_result(result)
    return 0 if result.get("success") else 1


# =============================================================================
# OUTPUT HELPERS
# =============================================================================


def _print_help():
    """Display repair command help."""
    console.print("[bold cyan]Usage:[/bold cyan] drone @spawn repair <project_path> \\[options]")
    console.print()
    console.print("  [green]<project_path>[/green]           Path to project root")
    console.print("  [green]--apply[/green]                  Execute changes (default is preview-only)")
    console.print("  [green]--dry-run[/green]                Preview changes without modifying [dim](default)[/dim]")
    console.print("  [green]--relocate[/green] @branch path  Move a branch to a new location")
    console.print(
        "  [green]--relocate-artifacts[/green]    Move .chroma/ into branch (with --relocate, single-branch only)"
    )
    console.print("  [green]--clean-pollution[/green]        Archive and remove duplicate dirs")
    console.print()


def _print_move_result(result, dry_run):
    """Print relocate operation results."""
    mode = "[dim](dry-run)[/dim] " if dry_run else ""
    console.print()

    if result.get("success"):
        console.print(f"[green]Relocate {mode}{result.get('branch', '?')}[/green]")
        console.print(f"  From: {result.get('old_path', '?')}")
        console.print(f"  To:   {result.get('new_path', '?')}")
        if result.get("archive_path"):
            console.print(f"  Archive: {result['archive_path']}")
        if dry_run and result.get("actions"):
            console.print()
            console.print("  [bold cyan]Would:[/bold cyan]")
            for action in result["actions"]:
                console.print(f"    - {action}")
    else:
        error(f"Relocate FAILED: {result.get('error', 'unknown')}")

    console.print()


def _print_pollution_result(result, dry_run):
    """Print pollution cleanup results."""
    mode = "[dim](dry-run)[/dim] " if dry_run else ""
    console.print()

    issues_found = result.get("issues_found", 0)
    if issues_found == 0:
        console.print("[green]No pollution detected[/green]")
    else:
        warning(f"Pollution cleanup {mode}— {issues_found} issue(s)")
        if dry_run:
            for issue in result.get("issues", []):
                console.print(f"  - {issue['description']}")
                console.print(f"    Path: {issue['path']}")
        else:
            for item in result.get("cleaned", []):
                console.print(f"  Cleaned: {item['path']}")
            for item in result.get("errors", []):
                error(f"Failed: {item['path']} — {item['error']}")

    console.print()


def _print_scan_result(result):
    """Print project scan results."""
    console.print()
    header(f"Structure Report — {result.get('project', '?')}")
    console.print()

    total = result.get("total_issues", 0)
    if total == 0:
        console.print("[green]No structural issues found[/green]")
    else:
        warning(f"{total} issue(s) found")

    pollution = result.get("pollution", [])
    if pollution:
        console.print()
        console.print(f"[bold]Pollution ({len(pollution)}):[/bold]")
        for p in pollution:
            console.print(f"  - {p['description']}")
            console.print(f"    Fix: drone @spawn repair {result.get('project', '?')} --clean-pollution")

    mismatches = result.get("registry_mismatches", [])
    if mismatches:
        console.print()
        console.print(f"[bold]Registry mismatches ({len(mismatches)}):[/bold]")
        for m in mismatches:
            console.print(f"  - {m['branch']}: {m['issue']}")
            console.print(f"    Registered: {m['registered_path']}")

    console.print()
