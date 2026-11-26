# =================== AIPass ====================
# Name: sync_registry.py
# Description: Registry repair — thin CLI layer for registry synchronization
# Version: 1.6.0
# Created: 2026-03-07
# Modified: 2026-11-26
# =============================================

"""Registry synchronization for branch lifecycle management.

Reference: docs/registry_and_repair.md
"""

from aipass.prax import logger

from aipass.cli import console, err_console, error, warning

from aipass.spawn.apps.handlers.convert_registry_ops import convert_registry
from aipass.spawn.apps.handlers.registry import find_registry
from aipass.spawn.apps.handlers.sync_registry_ops import (
    DAMAGED_STATE,
    sync_registry,
    check_owner_identity,
    fix_owner_identity,
    rebuild_registry,
)
from aipass.spawn.apps.handlers.json import json_handler
from aipass.spawn.apps.handlers.meta_ops import CorruptTemplateManifest
from aipass.spawn.apps.handlers.seat_gate import PREVIEW_NOTE, seat_refusal


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
    console.print("[dim]Run drone @spawn sync-registry --help for usage[/dim]")


def handle_command(command: str, args: list) -> bool:
    """Handle commands routed by the entry point."""
    if command != "sync-registry":
        return False

    if not args:
        print_introspection()
        return True

    if "--help" in args:
        print_help()
        return True

    return handle_sync_registry(args) == 0


def print_help():
    """Display sync-registry help."""
    console.print(
        "[bold cyan]Usage:[/bold cyan] drone @spawn sync-registry "
        "\\[project-path] [--fix|--check|--rebuild|--lowercase] [--json] [--dry-run] [--confirm]"
    )
    console.print()
    console.print("  [green](no args)[/green]      Report mismatches between registry and filesystem")
    console.print("  [green]--fix[/green]          Auto-repair: stale/unregistered + owner/identity reconcile")
    console.print("  [green]--fix --dry-run[/green] Show planned owner/identity fixes without applying")
    console.print("  [green]--check[/green]        Read-only owner/identity health check (exit 0=clean)")
    console.print("  [green]--check --json[/green]  Machine-readable check output")
    console.print("  [green]--rebuild[/green]      Preview rebuilding a CORRUPT registry from its passports")
    console.print(
        "  [green]--rebuild --confirm[/green] Move the corrupt file aside as <name>.corrupt-<stamp>, write the"
        " rebuilt one; admin and ci_cure are not restored (re-run grant-admin, grant-ci-cure)"
    )
    console.print(
        "  [green]--lowercase[/green]    Preview lowercasing row names, certificate owners and passport names,"
        " and relative paths"
        " (exit 0 nothing to convert, 1 rows to convert, 2 refused)"
    )
    console.print(
        "  [green]--lowercase --confirm[/green] Copy the registry to <name>.pre-convert-<stamp>, then convert it;"
        " project-path may name the registry file itself"
    )
    console.print()
    console.print("[bold cyan]Examples:[/bold cyan]")
    console.print("  drone @spawn sync-registry")
    console.print("  drone @spawn sync-registry --fix --dry-run")
    console.print("  drone @spawn sync-registry --check --json")
    console.print()


def handle_sync_registry(args: list[str]) -> int:
    """Parse args and execute sync.

    Returns exit code (0=success/clean, 1=failure/issues).
    """
    if args and args[0] in ["--help", "-h"]:
        print_help()
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

        named = Path(project_path)
        registry_path = named if named.is_file() else find_registry(start_path=named)
        # A named project with no registry is an error; falling back to the cwd's would write the wrong project.
        if registry_path is None:
            error(f"No *_REGISTRY.json found at or above {project_path}")
            return 1

    if "--check" in flags:
        return _handle_check(registry_path, json_output="--json" in flags)
    if "--rebuild" in flags:
        return _handle_rebuild(registry_path, confirm="--confirm" in flags)
    if "--lowercase" in flags:
        return _handle_lowercase(registry_path, confirm="--confirm" in flags)

    fix = "--fix" in flags
    dry_run = "--dry-run" in flags
    refusal = fix and not dry_run and seat_refusal("sync-registry --fix", str(registry_path))
    if refusal:
        error(refusal)
        return 1
    if fix and dry_run:
        console.print(f"[dim]{PREVIEW_NOTE}[/dim]")

    try:
        result = sync_registry(fix=fix and not dry_run, registry_path=registry_path)
    except CorruptTemplateManifest:
        raise
    except Exception as exc:
        logger.error(f"[sync-registry] Unexpected error: {exc}")
        error(str(exc))
        return 1

    # The owner/identity fix would load the same missing or unreadable registry as empty and save that.
    if result.get("error"):
        error(f"Registry sync: {result['error']}")
        return 1

    json_handler.log_operation("registry_synced")
    _print_summary(result)

    code = _handle_fix(registry_path, dry_run=dry_run) if fix else 0
    # A damaged citizen is a fault the sync could not repair: never a clean exit.
    return 1 if result.get("damaged") else code


def _handle_check(registry_path, json_output=False) -> int:
    """Run owner/identity health check and report. Exit 0 clean, 1 issues, 2 the check itself crashed."""
    import json as _json

    try:
        result = check_owner_identity(registry_path=registry_path)
    except Exception as exc:
        logger.error(f"[sync-registry] Check error: {exc}")
        error(str(exc))
        return 2

    if json_output:
        text = _json.dumps(result, indent=2, ensure_ascii=False)
        console.print(text, markup=False, highlight=False, soft_wrap=True)
        return 0 if result["clean"] else 1

    issues = result["issues"]
    notes = result.get("notes", [])
    console.print()
    if not issues:
        console.print("[green]Owner/identity check: clean[/green]")
        _print_notes(notes)
        return 0

    error(f"Owner/identity check: {len(issues)} issue(s)")
    console.print()
    for issue in issues:
        console.print(f"  \\[{issue['flag']}] {issue['detail']}")
    _print_notes(notes)
    console.print()
    console.print("[dim]Run with --fix to reconcile.[/dim]")
    return 1


def _handle_rebuild(registry_path, confirm=False) -> int:
    """Rebuild a corrupt registry from its passports; a preview unless --confirm."""
    registry_path = registry_path or find_registry()
    if registry_path is None:
        error("No *_REGISTRY.json found above the current directory")
        return 1
    refusal = confirm and seat_refusal("sync-registry --rebuild --confirm", str(registry_path))
    if refusal:
        error(refusal)
        return 1

    try:
        receipt = rebuild_registry(registry_path, confirm=confirm)
    except Exception as exc:
        logger.error(f"[sync-registry] Rebuild error: {exc}")
        error(str(exc))
        return 1
    if receipt["refused"]:
        error(f"Registry rebuild refused: {receipt['refused']}")
        return 1

    label = "Rebuilt" if receipt["written"] else "Would rebuild"
    console.print()
    console.print(f"[bold]{label} {registry_path} - credential {receipt['credential']}[/bold]")
    for row in receipt["rows"]:
        console.print(f"  {row['name']}  {row['path']}  {row['registry_id']}", markup=False)
    console.print(f"  Owner: {receipt['owner'] or '(none)'}", markup=False)
    if receipt["aside"]:
        console.print(f"  Corrupt bytes kept at {receipt['aside']}", markup=False)
    if receipt["ceremonies"]:
        warning("Not restored by a rebuild - re-run each ceremony:")
        for command in receipt["ceremonies"]:
            err_console.print(f"    {command}", markup=False)
    if not receipt["written"]:
        console.print("[dim]Preview - nothing written. Add --confirm to rebuild.[/dim]")
    console.print()
    return 0


def _handle_lowercase(registry_path, confirm=False) -> int:
    """Lowercase a registry's rows and its citizens' certificate owner and passport name; preview unless --confirm.

    Exit 0: nothing to convert, or converted. 1: a preview with rows to convert. 2: refused or crashed."""
    registry_path = registry_path or find_registry()
    if registry_path is None:
        error("No *_REGISTRY.json found above the current directory")
        return 2
    refusal = confirm and seat_refusal("sync-registry --lowercase --confirm", str(registry_path))
    if refusal:
        error(refusal)
        return 2

    try:
        receipt = convert_registry(registry_path, confirm=confirm)
    except Exception as exc:
        logger.error(f"[sync-registry] Lowercase conversion error: {exc}")
        error(str(exc))
        return 2
    if receipt["refused"]:
        error(f"Registry conversion refused: {receipt['refused']}")
        return 2

    console.print()
    for skipped in receipt["skipped"]:
        console.print(f"  skipped {skipped['file']}: {skipped['skipped']}", markup=False)
    if not (receipt["changes"] or receipt["files"]):
        console.print(f"{registry_path} is already converted - nothing to do.", markup=False)
        console.print()
        return 0
    label = "Converted" if receipt["written"] else "Would convert"
    console.print(
        f"{label} {len(receipt['changes'])} row(s) and {len(receipt['files'])} file(s) for {registry_path}",
        markup=False,
    )
    for change in receipt["changes"]:
        console.print(
            f"  {change['old_name']} -> {change['new_name']}    {change['old_path']} -> {change['new_path']}",
            markup=False,
        )
    for change in receipt["files"]:
        console.print(f"  {change['file']}: {change['field']} {change['old']} -> {change['new']}", markup=False)
    if receipt["copy"]:
        console.print(f"  Original kept at {receipt['copy']}", markup=False)
    if not receipt["written"]:
        console.print("[dim]Preview - nothing written. Add --confirm to convert.[/dim]")
    console.print()
    return 0 if receipt["written"] else 1


def _print_notes(notes) -> None:
    """Print informational check lines; they never change the exit code."""
    for note in notes:
        console.print(f"  [dim]note \\[{note['flag']}] {note['detail']}[/dim]")


def _handle_fix(registry_path, dry_run=False) -> int:
    """Run owner/identity reconcile."""
    try:
        result = fix_owner_identity(registry_path=registry_path, dry_run=dry_run)
    except Exception as exc:
        logger.error(f"[sync-registry] Fix error: {exc}")
        error(str(exc))
        return 1

    if result.get("error"):
        error(f"Owner/identity fix: {result['error']}")
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


def _print_summary(result: dict) -> None:
    """Print a rich summary of the sync operation."""
    stale = result.get("stale", [])
    unregistered = result.get("unregistered", [])
    healthy = result.get("healthy", [])
    fixed = result.get("fixed", False)

    console.print()
    console.print("[bold]Registry Sync Report[/bold]")
    console.print()

    if healthy:
        console.print(f"  [green]Healthy ({len(healthy)}):[/green]")
        for name in sorted(healthy):
            console.print(f"    {name}")

    # Stale and unregistered names follow their header onto stderr, or stdout files them under Healthy.
    if stale:
        error(f"Stale ({len(stale)}): registered but missing/invalid")
        for name in sorted(stale):
            err_console.print(f"    {name}")
    else:
        console.print("  [green]No stale entries[/green]")

    damaged = result.get("damaged", [])
    if damaged:
        error(f"Damaged ({len(damaged)}): {DAMAGED_STATE}")
        for name in sorted(damaged):
            err_console.print(f"    {name} - {result['damaged_cures'][name]}")

    if unregistered:
        warning(f"Unregistered ({len(unregistered)}): on disk but not in registry")
        for name in sorted(unregistered):
            err_console.print(f"    {name}")
    else:
        console.print("  [green]No unregistered branches[/green]")

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
    ids_failed = result.get("ids_failed", [])
    if ids_failed:
        warning(f"registry_id NOT fixed in {len(ids_failed)} passport(s): {', '.join(sorted(ids_failed))}")

    console.print()
