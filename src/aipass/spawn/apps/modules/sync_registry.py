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
from aipass.cli.apps.modules import console, err_console, error, warning

from aipass.spawn.apps.handlers.sync_registry_ops import (
    sync_registry,
    check_owner_identity,
    fix_owner_identity,
)
from aipass.spawn.apps.handlers.json import json_handler


def print_introspection():
    """Display module introspection info."""
    console.print()
    console.print("[bold cyan]sync_registry Module[/bold cyan]")
    console.print("Registry repair — detect and fix mismatches between AIPASS_REGISTRY and filesystem")
    console.print()
    console.print("[yellow]Connected Handlers:[/yellow]")
    console.print("  [cyan]handlers/[/cyan]")
    console.print(
        "    [dim]- sync_registry_ops.py"
        " (sync_registry — scan filesystem, detect stale/unregistered, auto-repair)[/dim]"
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
        []                          -> report only (show mismatches)
        ["--fix"]                   -> auto-repair mismatches + owner/identity reconcile
        ["--check"]                 -> read-only owner/identity health check
        ["--check", "--json"]       -> machine-readable check output
        ["--fix", "--dry-run"]      -> show planned owner/identity fixes without applying

    An optional positional path can precede any flag to target
    a specific project registry (default: CWD-based discovery).

    Returns exit code (0=success/clean, 1=failure/issues).
    """
    if args and args[0] in ["--help", "-h"]:
        console.print(
            "[bold cyan]Usage:[/bold cyan] drone @spawn sync-registry "
            "\\[project-path] [--fix|--check] [--json] [--dry-run]"
        )
        console.print()
        console.print("  [green](no args)[/green]      Report mismatches between registry and filesystem")
        console.print("  [green]--fix[/green]          Auto-repair: stale/unregistered + owner/identity reconcile")
        console.print("  [green]--fix --dry-run[/green] Show planned owner/identity fixes without applying")
        console.print("  [green]--check[/green]        Read-only owner/identity health check (exit 0=clean)")
        console.print("  [green]--check --json[/green]  Machine-readable check output")
        return 0

    project_path = None
    flags = set()
    for arg in args:
        if arg.startswith("--"):
            flags.add(arg)
        elif project_path is None:
            project_path = arg

    registry_path = None
    if project_path:
        from pathlib import Path

        from aipass.spawn.apps.handlers.registry import find_registry

        registry_path = find_registry(start_path=Path(project_path))

    if "--check" in flags:
        return _handle_check(registry_path, json_output="--json" in flags)

    fix = "--fix" in flags
    dry_run = "--dry-run" in flags

    try:
        result = sync_registry(fix=fix and not dry_run)
    except Exception as exc:
        logger.error(f"[sync-registry] Unexpected error: {exc}")
        error(str(exc))
        return 1

    json_handler.log_operation("registry_synced")
    _print_summary(result)

    if fix:
        return _handle_fix(registry_path, dry_run=dry_run)

    return 0


def _handle_check(registry_path, json_output=False) -> int:
    """Run owner/identity health check and report."""
    import json as _json

    try:
        result = check_owner_identity(registry_path=registry_path)
    except Exception as exc:
        logger.error(f"[sync-registry] Check error: {exc}")
        error(str(exc))
        return 1

    if json_output:
        console.print(_json.dumps(result, indent=2, ensure_ascii=False))
        return 0 if result["clean"] else 1

    issues = result["issues"]
    console.print()
    if not issues:
        console.print("[green]Owner/identity check: clean[/green]")
        return 0

    error(f"Owner/identity check: {len(issues)} issue(s)")
    console.print()
    for issue in issues:
        console.print(f"  [{issue['flag']}] {issue['detail']}")
    console.print()
    console.print("[dim]Run with --fix to reconcile.[/dim]")
    return 1


def _handle_fix(registry_path, dry_run=False) -> int:
    """Run owner/identity reconcile."""
    try:
        result = fix_owner_identity(registry_path=registry_path, dry_run=dry_run)
    except Exception as exc:
        logger.error(f"[sync-registry] Fix error: {exc}")
        error(str(exc))
        return 1

    actions = result["actions"]
    console.print()
    if not actions:
        console.print("[green]Owner/identity: nothing to reconcile[/green]")
        return 0

    label = "Planned" if dry_run else "Applied"
    console.print(f"[bold]{label} owner/identity actions ({len(actions)}):[/bold]")
    for action in actions:
        console.print(f"  {action}")

    if dry_run:
        console.print()
        console.print("[dim]Dry-run — no changes written. Remove --dry-run to apply.[/dim]")
    console.print()
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

    # Stale — names follow their header onto stderr, or stdout files them under Healthy
    if stale:
        error(f"Stale ({len(stale)}): registered but missing/invalid")
        for name in sorted(stale):
            err_console.print(f"    {name}")
    else:
        console.print("  [green]No stale entries[/green]")

    # Unregistered — same rule as stale
    if unregistered:
        warning(f"Unregistered ({len(unregistered)}): on disk but not in registry")
        for name in sorted(unregistered):
            err_console.print(f"    {name}")
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
