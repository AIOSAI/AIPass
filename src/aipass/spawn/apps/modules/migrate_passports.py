# =================== AIPass ====================
# Name: migrate_passports.py
# Description: Passport 2.0 fleet migration — thin CLI layer over passport_migration
# Version: 1.0.1
# Created: 2026-08-28
# Modified: 2026-10-24
# =============================================

"""One-shot fleet passport migration to schema 2.0 (DPLAN-0319).

Dry run is the default; ``--confirm`` is the only thing that writes.
"""

import argparse

from aipass.prax import logger

from aipass.cli.apps.modules import console, err_console, error, header, warning

from aipass.spawn.apps.handlers.passport_migration import migrate_fleet
from aipass.spawn.apps.handlers.json import json_handler


def print_introspection():
    """Display module introspection info."""
    console.print()
    console.print("[bold cyan]migrate_passports Module[/bold cyan]")
    console.print("Passport 2.0 migration — one-shot fleet upgrade of every .trinity/passport.json")
    console.print()
    console.print("[yellow]Connected Handlers:[/yellow]")
    console.print("  [cyan]handlers/[/cyan]")
    console.print(
        "    [dim]- passport_migration.py (discover_passports, migrate_document, migrate_fleet, backup_passport)[/dim]"
    )
    console.print()
    console.print("[dim]Run 'drone @spawn migrate-passports --help' for usage information[/dim]")
    console.print()


def handle_command(command: str, args: list) -> bool:
    """Handle commands routed by the entry point."""
    if command != "migrate-passports":
        return False

    if not args:
        # Dispatch door only; the CLI goes straight to handle_migrate_passports (no args = dry run).
        print_introspection()
        return True

    if "--help" in args or "-h" in args:
        print_help()
        return True

    return handle_migrate_passports(args) == 0


def handle_migrate_passports(args: list[str]) -> int:
    """Parse args and execute the passport 2.0 migration.

    Returns exit code (0=clean, 1=one or more passports could not be migrated).
    """
    # Before parse_args: with add_help=False argparse would reject --help and exit(2).
    if "--help" in args or "-h" in args:
        print_help()
        return 0

    parser = argparse.ArgumentParser(prog="spawn migrate-passports", add_help=False)
    parser.add_argument("--confirm", action="store_true")
    # A no-op flag on purpose: the way to ask for the dry run by name.
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--root", default=None)
    parser.add_argument("--only", default=None)

    try:
        parsed, unknown = parser.parse_known_args(args)
    except SystemExit as exc:
        logger.error(f"[migrate-passports] Argument parsing failed: {exc}")
        error("could not parse arguments", suggestion="drone @spawn migrate-passports --help")
        return 1

    if unknown:
        error(f"unknown argument(s): {' '.join(unknown)}", suggestion="drone @spawn migrate-passports --help")
        return 1

    try:
        receipt = migrate_fleet(root=parsed.root, only=parsed.only, confirm=parsed.confirm)
    except Exception as exc:
        logger.error(f"[migrate-passports] Unexpected error: {exc}")
        error(str(exc))
        return 1

    # Dry runs are logged too: they leave no other trace.
    json_handler.log_operation(
        "migrate_passports",
        data={
            "mode": "confirm" if parsed.confirm else "dry-run",
            "scanned": receipt["scanned"],
            "changed": receipt["changed"],
            "errors": len(receipt["errors"]),
        },
    )

    _print_receipt(receipt)
    # Zero scanned is a refusal and exits 1, so a wrong --root never reads as "already 2.0".
    return 1 if receipt["errors"] or not receipt["scanned"] else 0


def print_help():
    """Display migrate-passports command help."""
    console.print()
    console.print(
        "[bold cyan]Usage:[/bold cyan] drone @spawn migrate-passports "
        "\\[--dry-run|--confirm] \\[--root <path>] \\[--only <branch>]"
    )
    console.print()
    console.print("  Migrate every live passport to schema 2.0 (DPLAN-0319): block order,")
    console.print("  principles into identity, residency, class renames, casing and path fixes.")
    console.print()
    console.print(
        "  [green](no args)[/green]        Dry run — report every planned change, write nothing [dim](default)[/dim]"
    )
    console.print("  [green]--dry-run[/green]        The same dry run, asked for by name")
    console.print("  [green]--confirm[/green]        Execute: back up to passport.json.pre_v2_backup, then write")
    console.print("  [green]--root[/green] <path>    Repo root to scan [dim](default: the live AIPass root)[/dim]")
    console.print("  [green]--only[/green] <branch>  Restrict to one branch (@ optional)")
    console.print()
    console.print("[dim]Re-running is a measured no-op: an already-2.0 passport reports 0 changes.[/dim]")
    console.print()


def _print_receipt(receipt: dict) -> None:
    """Print the measured migration receipt."""
    mode = "APPLIED" if receipt["confirm"] else "DRY RUN"

    console.print()
    header(f"Passport 2.0 Migration — {mode}")
    console.print()
    console.print(f"  [bold]Root:[/bold]     {receipt['root']}")
    console.print(f"  [bold]Run date:[/bold] {receipt['run_date']}")
    if receipt["only"]:
        console.print(f"  [bold]Only:[/bold]     {receipt['only']}")
    console.print()

    baseline = receipt["baseline"]
    scanned_core = sum(1 for rec in receipt["files"] if rec["residency"] == "core")
    scanned_resident = receipt["scanned"] - scanned_core
    console.print(f"  Scanned:   {receipt['scanned']}  [dim](core {scanned_core} / resident {scanned_resident})[/dim]")
    console.print(f"  Changed:   {receipt['changed']}")
    console.print(f"  Unchanged: {receipt['unchanged']}")
    console.print(f"  Backups:   {receipt['backups_written']}")

    if not baseline["filtered"] and not baseline["matches"]:
        warning(
            f"Discovered {baseline['discovered_total']} passport(s) "
            f"(core {baseline['discovered_core']} / resident {baseline['discovered_resident']}) — "
            f"the measured fleet is {baseline['expected']['total']} "
            f"(core {baseline['expected']['core']} / resident {baseline['expected']['resident']}). "
            "Reporting the discovered set as found; verify the difference before applying."
        )

    _print_field_counts(receipt)
    _print_per_branch(receipt)
    _print_unknown(receipt)
    _print_errors(receipt)

    console.print()
    if not receipt["confirm"] and receipt["changed"]:
        console.print("  [dim]No files were written. Add --confirm to execute.[/dim]")
    elif not receipt["scanned"]:
        # Not an all-clear: discovery only matches an AIPass checkout's layout.
        error(
            f"No passports found under {receipt['root']} — nothing was scanned.",
            suggestion="Point --root at an AIPass checkout, or drop --root to scan this repository.",
        )
        console.print(
            "  [dim]Discovery matches this repository's layout "
            "(src/aipass/<branch>/ and projects/<project>/src/<pkg>/<branch>/).[/dim]"
        )
    elif not receipt["changed"] and not receipt["errors"]:
        console.print("  [green]Nothing to migrate — every scanned passport is already 2.0.[/green]")
    console.print()


def _print_field_counts(receipt: dict) -> None:
    """Print the per-field change tally."""
    counts = receipt["field_counts"]
    if not counts:
        return
    console.print()
    console.print("[bold]Field changes:[/bold]")
    width = max(len(name) for name in counts)
    for name, count in counts.items():
        console.print(f"  {name:<{width}}  {count}")


def _print_per_branch(receipt: dict) -> None:
    """Print one line per scanned passport."""
    console.print()
    console.print("[bold]Per branch:[/bold]")
    for rec in receipt["files"]:
        if rec["error"]:
            continue
        state = f"{len(rec['changes'])} change(s)" if rec["changed"] else "already 2.0"
        backup = "  [dim]+backup[/dim]" if rec["backup_written"] else ""
        console.print(f"  {rec['branch']:<14} {rec['residency']:<9} {state}{backup}")


def _print_unknown(receipt: dict) -> None:
    """Print fields the migration did not recognise but PRESERVED."""
    unknown = receipt["unknown_fields"]
    if not unknown:
        return
    console.print()
    warning(f"Preserved {len(unknown)} unrecognised field(s) — not in the 2.0 schema, not dropped:")
    for name, branches in sorted(unknown.items()):
        err_console.print(f"    {name}  [{', '.join(sorted(set(branches)))}]")


def _print_errors(receipt: dict) -> None:
    """Print every passport that was skipped, and why."""
    errors = receipt["errors"]
    if not errors:
        return
    console.print()
    error(f"{len(errors)} passport(s) could not be migrated:")
    for item in errors:
        err_console.print(f"    {item['branch']}: {item['error']}")
