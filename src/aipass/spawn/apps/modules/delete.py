# =================== AIPass ====================
# Name: delete.py
# Description: Branch deletion — thin CLI layer for archive and deregister
# Version: 1.1.0
# Created: 2026-03-07
# Modified: 2026-03-14
# =============================================

"""Delete orchestrator for branch lifecycle management.

Thin CLI module that parses arguments and delegates to the delete handler.
All implementation logic lives in apps/handlers/delete_ops.py.
"""

from aipass.prax import logger

# CLI service: from cli.apps.modules import console (via aipass namespace)
from aipass.cli.apps.modules import console, error, warning

from aipass.spawn.apps.handlers.delete_ops import delete_branch
from aipass.spawn.apps.handlers.json import json_handler


def print_introspection():
    """Display module introspection info."""
    console.print()
    console.print("delete Module")
    console.print("Branch deletion — archive directory and deregister from AIPASS_REGISTRY")
    console.print()
    console.print("Connected Handlers:")
    console.print("  handlers/")
    console.print("    - delete_ops.py (delete_branch — resolve path, archive, remove from registry)")
    console.print()


# =============================================================================
# DRONE ROUTING
# =============================================================================


def handle_command(command: str, args: list) -> bool:
    """Handle commands routed by the entry point.

    Args:
        command: The command string (e.g. "delete")
        args: List of arguments for the command

    Returns:
        True if command was handled, False otherwise.
    """
    if command != "delete":
        return False

    # No args → introspection
    if not args:
        print_introspection()
        return True

    if "--help" in args:
        print_introspection()
        return True

    return handle_delete(args) == 0


# =============================================================================
# PUBLIC API
# =============================================================================


def handle_delete(args: list[str]) -> int:
    """Parse args and execute delete.

    Args patterns:
        ["@branch"]             -> delete with confirmation prompt
        ["--yes", "@branch"]    -> skip confirmation
        ["--dry-run", "@branch"] -> preview only

    Returns exit code (0=success, 1=failure).
    """
    # Intercept --help before processing (argparse has add_help=False)
    if "--help" in args or "-h" in args:
        warning("Usage: drone @spawn delete <@branch> [--yes] [--dry-run]")
        console.print()
        console.print("  [green]@branch[/green]    Branch to archive and deregister")
        console.print("  [green]--yes[/green]      Skip confirmation prompt")
        console.print("  [green]--dry-run[/green]  Preview what would happen without changes")
        return 0

    if not args:
        warning("Usage: drone @spawn delete <@branch> [--yes] [--dry-run]")
        console.print()
        console.print("  [green]@branch[/green]    Branch to archive and deregister")
        console.print("  [green]--yes[/green]      Skip confirmation prompt")
        console.print("  [green]--dry-run[/green]  Preview what would happen without changes")
        return 1

    dry_run = "--dry-run" in args
    skip_confirm = "--yes" in args

    # Filter out flags to find the target
    targets = [a for a in args if not a.startswith("--")]

    if not targets:
        error("specify a branch name (e.g. @api)")
        return 1

    branch_name = targets[0].lstrip("@").lower()

    try:
        result = delete_branch(
            branch_name,
            confirm=not skip_confirm,
            dry_run=dry_run,
        )
    except Exception as exc:
        logger.error(f"[delete] Unexpected error deleting {branch_name}: {exc}")
        error(f"Error deleting {branch_name}: {exc}")
        return 1

    if result.get("success"):
        json_handler.log_operation("branch_deleted", data={"branch": branch_name})

    _print_summary(result, dry_run)
    return 0 if result.get("success") else 1


# =============================================================================
# OUTPUT HELPERS
# =============================================================================


def _print_summary(result: dict, dry_run: bool) -> None:
    """Print a rich summary of the delete operation."""
    branch = result.get("branch", "unknown")
    success = result.get("success", False)
    mode = "[dim](dry-run)[/dim] " if dry_run else ""

    console.print()
    if success:
        console.print(f"[green]Delete {mode}{branch}[/green]")
    else:
        error(f"Delete FAILED {mode}{branch}")

    archive_path = result.get("archive_path", "")
    if archive_path:
        console.print(f"  Archive: {archive_path}")

    console.print(f"  Registry updated: {result.get('registry_updated', False)}")

    err_msg = result.get("error", "")
    if err_msg:
        error(err_msg)

    console.print()
