# =================== AIPass ====================
# Name: sync_templates.py
# Description: Template sync — thin CLI layer for template synchronization
# Version: 1.1.0
# Created: 2026-03-07
# Modified: 2026-03-14
# =============================================

"""Template synchronization for branch lifecycle management.

Thin CLI module that parses arguments and delegates to the sync handler.
All implementation logic lives in apps/handlers/sync_templates_ops.py.
"""

from aipass.prax import logger
# CLI service: from cli.apps.modules import console (via aipass namespace)
from aipass.cli.apps.modules import console, error, warning

from aipass.spawn.apps.handlers.sync_templates_ops import sync_templates
from aipass.spawn.apps.handlers.json import json_handler


def print_introspection():
    """Display module introspection info."""
    console.print()
    console.print("sync_templates Module")
    console.print("Template synchronization — pull managed files from source branches into templates")
    console.print()
    console.print("Connected Handlers:")
    console.print("  handlers/")
    console.print("    - sync_templates_ops.py (sync_templates — compare hashes and pull updates from source branches)")
    console.print()


# =============================================================================
# DRONE ROUTING
# =============================================================================

def handle_command(command: str, args: list) -> bool:
    """Handle commands routed by the entry point.

    Args:
        command: The command string (e.g. "sync-templates")
        args: List of arguments for the command

    Returns:
        True if command was handled, False otherwise.
    """
    if command != "sync-templates":
        return False

    # No args → introspection
    if not args:
        print_introspection()
        return True

    return handle_sync_templates(args) == 0


# =============================================================================
# PUBLIC API
# =============================================================================

def handle_sync_templates(args: list[str]) -> int:
    """Parse args and execute template sync.

    Args patterns:
        []           -> report status (which files are stale)
        ["--status"] -> same as no args
        ["--sync"]   -> actually pull and update
        ["--dry-run"] -> preview changes

    Returns exit code (0=success, 1=failure).
    """
    if args and args[0] in ["--help", "-h"]:
        warning("Usage: drone @spawn sync-templates [--status|--sync|--dry-run]")
        console.print()
        console.print("  [green](no args)[/green]   Report which managed template files are stale")
        console.print("  [green]--status[/green]    Same as no args")
        console.print("  [green]--sync[/green]      Pull updated files from source branches into template")
        console.print("  [green]--dry-run[/green]   Preview what would be synced")
        return 0

    sync = "--sync" in args
    dry_run = "--dry-run" in args

    try:
        result = sync_templates(sync=sync, dry_run=dry_run)
    except Exception as exc:
        logger.error(f"[sync-templates] Unexpected error: {exc}")
        error(str(exc))
        return 1

    json_handler.log_operation("templates_synced")

    _print_summary(result, dry_run)
    return 0


# =============================================================================
# OUTPUT HELPERS
# =============================================================================

def _print_summary(result: dict, dry_run: bool) -> None:
    """Print a rich summary of the template sync operation."""
    managed = result.get("managed_files", 0)
    current = result.get("current", [])
    stale = result.get("stale", [])
    synced = result.get("synced", [])
    errors = result.get("errors", [])
    mode = "[dim](dry-run)[/dim] " if dry_run else ""

    console.print()
    console.print(f"[bold]Template Sync Report {mode}[/bold]")
    console.print()

    if managed == 0:
        console.print("  [dim]No managed files configured in template_owners.json[/dim]")
        console.print("  [dim]Add entries to spawn/apps/handlers/templates/template_owners.json[/dim]")
        console.print()
        return

    console.print(f"  Managed files: {managed}")

    if current:
        console.print(f"  [green]Current ({len(current)}):[/green]")
        for name in current:
            console.print(f"    {name}")

    if stale:
        warning(f"Stale ({len(stale)}):")
        for name in stale:
            console.print(f"    {name}")

    if synced:
        console.print(f"  [green]Synced ({len(synced)}):[/green]")
        for name in synced:
            console.print(f"    {name}")

    if errors:
        error(f"Errors ({len(errors)}):")
        for err in errors:
            console.print(f"    {err}")

    if stale and not synced and not dry_run:
        console.print()
        console.print("  [dim]Run with --sync to pull updates from source branches.[/dim]")

    console.print()
