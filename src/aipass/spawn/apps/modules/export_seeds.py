# =================== AIPass ====================
# Name: export_seeds.py
# Description: Passport seed export — thin CLI layer over seed_ops
# Version: 1.0.0
# Created: 2026-08-28
# Modified: 2026-08-28
# =============================================

"""Export every core citizen's passport seed (TDPLAN-0017).

Thin CLI module that parses arguments and delegates to the seed handler.
All implementation logic lives in apps/handlers/seed_ops.py.

DRY RUN IS THE DEFAULT, for the same reason ``migrate-passports`` has one: this
command writes a TRACKED file into eighteen branches at once. ``--confirm`` is
the only thing that writes, and re-running it is a measured no-op — every seed
that already matches its live passport reports "current" and is not touched.
"""

import argparse

from aipass.prax import logger

# CLI service: from cli.apps.modules import console (via aipass namespace)
from aipass.cli.apps.modules import console, err_console, error, header, warning

from aipass.spawn.apps.handlers.json import json_handler
from aipass.spawn.apps.handlers.seed_ops import SEED_RELATIVE_PATH, export_seeds


def print_introspection():
    """Display module introspection info."""
    console.print()
    console.print("[bold cyan]export_seeds Module[/bold cyan]")
    console.print("Passport seeds — regenerate each branch's tracked .aipass/passport.seed.json")
    console.print()
    console.print("[yellow]Connected Handlers:[/yellow]")
    console.print("  [cyan]handlers/[/cyan]")
    console.print("    [dim]- seed_ops.py (build_seed, export_seeds, load_seed, mint_from_seed)[/dim]")
    console.print()
    console.print("[dim]Run 'drone @spawn export-seeds --help' for usage information[/dim]")
    console.print()


# =============================================================================
# DRONE ROUTING
# =============================================================================


def handle_command(command: str, args: list) -> bool:
    """Handle commands routed by the entry point.

    Args:
        command: The command string (e.g. "export-seeds").
        args: List of arguments for the command.

    Returns:
        True if the command was handled, False otherwise.
    """
    if command != "export-seeds":
        return False

    if not args:
        # No args → introspection, matching migrate_passports.py: this is the
        # plugin/dispatch door, not the CLI one. spawn.py routes the CLI
        # straight to handle_export_seeds, where no args is the (safe,
        # read-only) dry run.
        print_introspection()
        return True

    if "--help" in args or "-h" in args:
        print_help()
        return True

    return handle_export_seeds(args) == 0


# =============================================================================
# PUBLIC API
# =============================================================================


def handle_export_seeds(args: list[str]) -> int:
    """Parse args and export the fleet's passport seeds.

    Args patterns:
        []                          -> dry run over the live fleet (writes nothing)
        ["--dry-run"]               -> the same dry run, stated explicitly
        ["--confirm"]               -> execute (writes/updates each seed)
        ["--root", "<path>"]        -> scan a different repo root
        ["--only", "@branch"]       -> restrict to one branch

    Returns exit code (0=clean, 1=one or more seeds could not be exported).
    """
    # --help is intercepted BEFORE parse_args: the parser runs with
    # add_help=False (house shape), so argparse would otherwise treat --help
    # as an unknown option and exit(2) with its own usage line.
    if "--help" in args or "-h" in args:
        print_help()
        return 0

    parser = argparse.ArgumentParser(prog="spawn export-seeds", add_help=False)
    parser.add_argument("--confirm", action="store_true")
    # --dry-run is the DEFAULT behaviour, so the flag changes nothing on its
    # own. It exists to be typed: it is how a caller asks for the measurement.
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--root", default=None)
    parser.add_argument("--only", default=None)

    try:
        parsed, unknown = parser.parse_known_args(args)
    except SystemExit as exc:
        logger.error(f"[export-seeds] Argument parsing failed: {exc}")
        error("could not parse arguments", suggestion="drone @spawn export-seeds --help")
        return 1

    if unknown:
        error(f"unknown argument(s): {' '.join(unknown)}", suggestion="drone @spawn export-seeds --help")
        return 1

    try:
        receipt = export_seeds(root=parsed.root, only=parsed.only, confirm=parsed.confirm)
    except Exception as exc:
        logger.error(f"[export-seeds] Unexpected error: {exc}")
        error(str(exc))
        return 1

    # Every invocation is recorded, dry runs included — a dry run is the
    # measurement that precedes the GO, and it leaves no other trace.
    json_handler.log_operation(
        "export_seeds",
        data={
            "mode": "confirm" if parsed.confirm else "dry-run",
            "scanned": receipt["scanned"],
            "changed": receipt["changed"],
            "errors": len(receipt["errors"]),
        },
    )

    _print_receipt(receipt)
    return 1 if receipt["errors"] else 0


# =============================================================================
# OUTPUT HELPERS
# =============================================================================


def print_help():
    """Display export-seeds command help."""
    console.print()
    console.print(
        "[bold cyan]Usage:[/bold cyan] drone @spawn export-seeds "
        "\\[--dry-run|--confirm] \\[--root <path>] \\[--only <branch>]"
    )
    console.print()
    console.print(f"  Regenerate every core citizen's TRACKED seed at [cyan]{SEED_RELATIVE_PATH}[/cyan] from its")
    console.print("  live (gitignored) passport, so identities ship with the repo. The seed is the")
    console.print("  passport minus the machine-local facts: registered, registry_id, citizen_id,")
    console.print("  and the seed stamp itself.")
    console.print()
    console.print(
        "  [green](no args)[/green]        Dry run — report every seed that would change, write nothing "
        "[dim](default)[/dim]"
    )
    console.print("  [green]--dry-run[/green]        The same dry run, asked for by name")
    console.print("  [green]--confirm[/green]        Execute: write each new or changed seed")
    console.print("  [green]--root[/green] <path>    Repo root to scan [dim](default: the live AIPass root)[/dim]")
    console.print("  [green]--only[/green] <branch>  Restrict to one branch (@ optional)")
    console.print()
    console.print("[dim]Seeds are GENERATED, never hand-edited — edit the passport, then re-export.[/dim]")
    console.print("[dim]Re-running is a measured no-op: an up-to-date seed reports 'current'.[/dim]")
    console.print()


def _print_receipt(receipt: dict) -> None:
    """Print the measured export receipt."""
    mode = "APPLIED" if receipt["confirm"] else "DRY RUN"

    console.print()
    header(f"Passport Seed Export — {mode}")
    console.print()
    console.print(f"  [bold]Root:[/bold] {receipt['root']}")
    if receipt["only"]:
        console.print(f"  [bold]Only:[/bold] {receipt['only']}")
    console.print()
    console.print(f"  Scanned:  {receipt['scanned']}  [dim](core citizens)[/dim]")
    console.print(f"  Created:  {receipt['created']}")
    console.print(f"  Updated:  {receipt['updated']}")
    console.print(f"  Current:  {receipt['current']}")
    console.print(f"  Written:  {receipt['written']}")

    if receipt["skipped_resident"]:
        console.print(
            f"  [dim]Residents not exported: {receipt['skipped_resident']} "
            f"— a resident's identity belongs to its own project's repo.[/dim]"
        )

    baseline = receipt["baseline"]
    if not baseline["filtered"] and not baseline["matches"]:
        warning(
            f"Discovered {baseline['discovered_core']} core passport(s) — the measured fleet is "
            f"{baseline['expected_core']}. Reporting the discovered set as found; "
            "verify the difference before applying."
        )

    _print_per_branch(receipt)
    _print_errors(receipt)

    console.print()
    if not receipt["confirm"] and receipt["changed"]:
        console.print("  [dim]No files were written. Add --confirm to execute.[/dim]")
    elif not receipt["changed"]:
        console.print("  [green]Every seed is already current — nothing to export.[/green]")
    console.print()


def _print_per_branch(receipt: dict) -> None:
    """Print one line per scanned branch."""
    console.print()
    console.print("[bold]Per branch:[/bold]")
    for rec in receipt["seeds"]:
        if rec["error"]:
            continue
        console.print(f"  {rec['branch']:<14} {rec['action']}")


def _print_errors(receipt: dict) -> None:
    """Print every branch whose seed was refused, and why."""
    errors = receipt["errors"]
    if not errors:
        return
    console.print()
    error(f"{len(errors)} seed(s) could not be exported:")
    for item in errors:
        err_console.print(f"    {item['branch']}: {item['error']}")
