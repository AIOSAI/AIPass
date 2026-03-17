# =================== AIPass ====================
# Name: update.py
# Description: Update orchestrator — thin CLI layer for branch updates
# Version: 1.1.0
# Created: 2026-03-07
# Modified: 2026-03-14
# =============================================

"""Update orchestrator for branch lifecycle management.

Thin CLI module that parses arguments and delegates to the update handler.
All implementation logic lives in apps/handlers/update_ops.py.
"""

from aipass.prax import logger
# CLI service: from cli.apps.modules import console (via aipass namespace)
from aipass.cli.apps.modules import console, error, warning

from aipass.spawn.apps.handlers.update_ops import (
    update_branch,
    update_all,
)
from aipass.spawn.apps.handlers.json import json_handler


def print_introspection():
    """Display module introspection info."""
    console.print()
    console.print("update Module")
    console.print("Branch updates — sync single or all branches against their class templates")
    console.print()
    console.print("Connected Handlers:")
    console.print("  handlers/")
    console.print("    - update_ops.py (update_branch, update_all — renames, additions, JSON merges, pruned file archival)")
    console.print()


# =============================================================================
# DRONE ROUTING
# =============================================================================

def handle_command(command: str, args: list) -> bool:
    """Handle commands routed by the entry point.

    Args:
        command: The command string (e.g. "update")
        args: List of arguments for the command

    Returns:
        True if command was handled, False otherwise.
    """
    if command != "update":
        return False

    # No args → introspection
    if not args:
        print_introspection()
        return True

    return handle_update(args) == 0


# =============================================================================
# PUBLIC API
# =============================================================================

def handle_update(args: list[str]) -> int:
    """Parse args and dispatch to update_branch or update_all.

    Args patterns:
        ["@branch"]                -> update single branch (uses passport's class)
        ["builder", "--all"]       -> update all builder-class branches
        ["birthright", "--all"]    -> update all birthright-class branches
        ["--all"]                  -> BLOCKED (must specify class)
        ["--dry-run", "@branch"]   -> preview mode
        ["--dry-run", "--all"]     -> BLOCKED
        ["--trace", "@branch"]     -> verbose logging

    Returns exit code (0=success, 1=failure).
    """
    if not args:
        warning("Usage: drone @spawn update <@branch|class --all> [--dry-run] [--trace]")
        console.print()
        console.print("  [green]@branch[/green]           Update a single branch (uses its own class)")
        console.print("  [green]builder --all[/green]     Update all builder-class branches")
        console.print("  [green]birthright --all[/green]  Update all birthright-class branches")
        console.print("  [green]--dry-run[/green]         Preview changes without modifying files")
        console.print("  [green]--trace[/green]           Enable verbose logging")
        return 1

    from aipass.spawn.apps.modules.core import validate_class, get_available_classes

    dry_run = "--dry-run" in args
    trace = "--trace" in args

    # Filter out flags to find positional args
    positional = [a for a in args if not a.startswith("--")]

    # Detect citizen class argument
    citizen_class = None
    targets = positional
    if positional and validate_class(positional[0]):
        citizen_class = positional[0]
        targets = positional[1:]

    # Handle --all
    if "--all" in args:
        if citizen_class is None:
            classes = ", ".join(get_available_classes())
            error("--all requires a citizen class", suggestion=f"drone @spawn update <class> --all (available: {classes})")
            return 1

        results = update_all(dry_run=dry_run, trace=trace, citizen_class=citizen_class)
        _print_all_summary(results, dry_run)
        return 0 if all(r.get("success") for r in results) else 1

    if not targets:
        error("specify a branch name (e.g. @prax) or use <class> --all")
        return 1

    # Take the first target, strip leading @
    branch_name = targets[0].lstrip("@")

    try:
        result = update_branch(branch_name, dry_run=dry_run, trace=trace)
    except Exception as exc:
        logger.error(f"[update] Unexpected error updating {branch_name}: {exc}")
        error(f"Error updating {branch_name}: {exc}")
        return 1

    if result.get("success"):
        json_handler.log_operation("branch_updated", data={"branch": branch_name})

    _print_branch_summary(result, dry_run)
    return 0 if result.get("success") else 1


# =============================================================================
# OUTPUT HELPERS
# =============================================================================

def _print_branch_summary(result: dict, dry_run: bool) -> None:
    """Print a rich summary for a single branch update."""
    branch = result.get("branch", "unknown")
    success = result.get("success", False)
    mode = "[dim](dry-run)[/dim] " if dry_run else ""

    console.print()
    if success:
        console.print(f"[green]Update {mode}{branch}[/green]")
    else:
        error(f"Update FAILED {mode}{branch}")

    console.print(f"  Additions:  {result.get('additions', 0)}")
    console.print(f"  Renames:    {result.get('renames', 0)}")
    console.print(f"  Updates:    {result.get('updates', 0)}")
    console.print(f"  Pruned:     {result.get('pruned', 0)}")
    console.print(f"  Skipped py: {result.get('skipped_py', 0)}")

    errs = result.get("errors", [])
    if errs:
        error(f"Errors: {len(errs)}")
        for e in errs:
            console.print(f"    - {e}")

    # In dry-run mode, show details of what would change
    if dry_run:
        additions_detail = result.get("_additions_detail", [])
        if isinstance(additions_detail, list) and additions_detail:
            console.print()
            console.print("  [cyan]Would add:[/cyan]")
            for a in additions_detail:
                if isinstance(a, dict):
                    console.print(f"    + {a.get('template_path', '')}")

        updates_detail = result.get("_updates_detail", [])
        if isinstance(updates_detail, list) and updates_detail:
            console.print("  [cyan]Would update/skip:[/cyan]")
            for u in updates_detail:
                if isinstance(u, dict):
                    tp = u.get("template_path", "")
                    bp = u.get("branch_path", tp)
                    if tp.endswith(".py"):
                        console.print(f"    ! {bp} [dim](skipped - .py manual review)[/dim]")
                    elif tp.endswith(".json"):
                        console.print(f"    ~ {bp} [dim](JSON deep merge)[/dim]")
                    else:
                        console.print(f"    - {bp} [dim](skipped - non-JSON)[/dim]")

        renames_detail = result.get("_renames_detail", [])
        if isinstance(renames_detail, list) and renames_detail:
            console.print("  [cyan]Would rename:[/cyan]")
            for r in renames_detail:
                if isinstance(r, dict):
                    console.print(f"    > {r.get('old_name', '')} -> {r.get('new_name', '')}")

        pruned_detail = result.get("_pruned_detail", [])
        if isinstance(pruned_detail, list) and pruned_detail:
            console.print("  [cyan]Would archive (pruned):[/cyan]")
            for p in pruned_detail:
                if isinstance(p, dict):
                    console.print(f"    - {p.get('branch_path', '')}")

    console.print()


def _print_all_summary(results: list[dict], dry_run: bool) -> None:
    """Print summary for update_all."""
    mode = "(dry-run) " if dry_run else ""

    console.print()
    console.print(f"[bold]Update All {mode}— {len(results)} branches[/bold]")
    console.print()

    total_add = sum(r.get("additions", 0) for r in results)
    total_ren = sum(r.get("renames", 0) for r in results)
    total_upd = sum(r.get("updates", 0) for r in results)
    total_prn = sum(r.get("pruned", 0) for r in results)
    total_skip = sum(r.get("skipped_py", 0) for r in results)
    total_err = sum(len(r.get("errors", [])) for r in results)

    for r in results:
        branch = r.get("branch", "?")
        status = "[green]OK[/green]" if r.get("success") else "[red]FAIL[/red]"
        changes = r.get("additions", 0) + r.get("renames", 0) + r.get("updates", 0) + r.get("pruned", 0)
        console.print(f"  {status} {branch}: {changes} changes")

    console.print()
    console.print(f"  Totals: +{total_add} added, ~{total_upd} updated, "
                  f">{total_ren} renamed, -{total_prn} pruned, "
                  f"!{total_skip} py-skipped")

    if total_err:
        error(f"{total_err} errors across all branches")
    console.print()
