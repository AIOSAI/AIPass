# =================== AIPass ====================
# Name: sync_registry.py
# Description: Registry repair — thin CLI layer for registry synchronization
# Version: 1.1.0
# Created: 2026-03-07
# Modified: 2026-03-14
# =============================================

"""Registry synchronization for branch lifecycle management.

Thin CLI module that parses arguments and delegates to the sync handler.
All implementation logic lives in apps/handlers/sync_registry_ops.py.
"""

from aipass.prax import logger

# CLI service: from cli.apps.modules import console (via aipass namespace)
from aipass.cli.apps.modules import console, error, warning

from aipass.spawn.apps.handlers.sync_registry_ops import sync_registry
from aipass.spawn.apps.handlers.json import json_handler


def print_introspection():
    """Display module introspection info."""
    console.print()
    console.print("sync_registry Module")
    console.print("Registry repair — detect and fix mismatches between AIPASS_REGISTRY and filesystem")
    console.print()
    console.print("Connected Handlers:")
    console.print("  handlers/")
    console.print(
        "    - sync_registry_ops.py (sync_registry — scan filesystem, detect stale/unregistered, auto-repair)"
    )
    console.print()


# =============================================================================
# DRONE ROUTING
# =============================================================================


def handle_command(command: str, args: list) -> bool:
    """Handle commands routed by the entry point.

    Args:
        command: The command string (e.g. "sync-registry")
        args: List of arguments for the command

    Returns:
        True if command was handled, False otherwise.
    """
    if command != "sync-registry":
        return False

    # No args → introspection
    if not args:
        print_introspection()
        return True

    if "--help" in args:
        print_introspection()
        return True

    return handle_sync_registry(args) == 0


# =============================================================================
# PUBLIC API
# =============================================================================


def handle_sync_registry(args: list[str]) -> int:
    """Parse args and execute sync.

    Args patterns:
        []           -> report only (show mismatches)
        ["--fix"]    -> auto-repair mismatches

    Returns exit code (0=success, 1=failure).
    """
    if args and args[0] in ["--help", "-h"]:
        warning("Usage: drone @spawn sync-registry [--fix]")
        console.print()
        console.print("  [green](no args)[/green]  Report mismatches between registry and filesystem")
        console.print("  [green]--fix[/green]      Auto-repair: remove stale, add unregistered")
        return 0

    fix = "--fix" in args

    try:
        result = sync_registry(fix=fix)
    except Exception as exc:
        logger.error(f"[sync-registry] Unexpected error: {exc}")
        error(str(exc))
        return 1

    json_handler.log_operation("registry_synced")

    _print_summary(result)
    return 0


# =============================================================================
# OUTPUT HELPERS
# =============================================================================


def _print_summary(result: dict) -> None:
    """Print a rich summary of the sync operation."""
    stale = result.get("stale", [])
    unregistered = result.get("unregistered", [])
    healthy = result.get("healthy", [])
    fixed = result.get("fixed", False)

    console.print()
    console.print("[bold]Registry Sync Report[/bold]")
    console.print()

    # Healthy
    if healthy:
        console.print(f"  [green]Healthy ({len(healthy)}):[/green]")
        for name in sorted(healthy):
            console.print(f"    {name}")

    # Stale
    if stale:
        error(f"Stale ({len(stale)}): registered but missing/invalid")
        for name in sorted(stale):
            console.print(f"    {name}")
    else:
        console.print("  [green]No stale entries[/green]")

    # Unregistered
    if unregistered:
        warning(f"Unregistered ({len(unregistered)}): on disk but not in registry")
        for name in sorted(unregistered):
            console.print(f"    {name}")
    else:
        console.print("  [green]No unregistered branches[/green]")

    # Fix status
    ids_fixed = result.get("ids_fixed", [])
    if fixed or ids_fixed:
        console.print()
        console.print("  [green]Registry has been repaired.[/green]")
        if ids_fixed:
            console.print(
                f"  [green]Fixed registry_id in {len(ids_fixed)} passport(s): {', '.join(sorted(ids_fixed))}[/green]"
            )
    elif stale or unregistered:
        console.print()
        console.print("  [dim]Run with --fix to auto-repair.[/dim]")

    console.print()
