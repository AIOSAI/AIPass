# =================== AIPass ====================
# Name: export_vault.py
# Description: Passport vault export — thin CLI layer over seed_ops
# Version: 2.0.1
# Created: 2026-08-28
# Modified: 2026-11-26
# =============================================

"""Export the passport vaults of the tree or project the registry names.

Dry run is the default: this writes a tracked file into every citizen's branch at once.
"""

import argparse

from aipass.prax import logger

from aipass.cli import console, err_console, error, header

from aipass.spawn.apps.handlers.json import json_handler
from aipass.spawn.apps.handlers.seed_ops import LEGACY_FILE_NAME, VAULT_RELATIVE_PATH, export_seeds


def print_introspection():
    """Display module introspection info."""
    console.print()
    console.print("[bold cyan]export_vault Module[/bold cyan]")
    console.print(f"Passport vaults — regenerate each branch's tracked {VAULT_RELATIVE_PATH}")
    console.print()
    console.print("[yellow]Connected Handlers:[/yellow]")
    console.print("  [cyan]handlers/[/cyan]")
    console.print("    [dim]- seed_ops.py (build_seed, export_seeds, load_seed, mint_from_seed)[/dim]")
    console.print()
    console.print("[dim]Run 'drone @spawn export-vault --help' for usage information[/dim]")
    console.print()


def handle_command(command: str, args: list) -> bool:
    """Handle commands routed by the entry point."""
    if command != "export-vault":
        return False

    if not args:
        # The dispatch door; spawn.py routes the CLI to handle_export_vault, where no args is the dry run.
        print_introspection()
        return True

    if "--help" in args or "-h" in args:
        print_help()
        return True

    return handle_export_vault(args) == 0


def handle_export_vault(args: list[str]) -> int:
    """Parse args and export the passport vaults. Returns 1 if any vault could not be exported."""
    # Before parse_args: with add_help=False argparse would reject --help as unknown.
    if "--help" in args or "-h" in args:
        print_help()
        return 0

    parser = argparse.ArgumentParser(prog="spawn export-vault", add_help=False)
    parser.add_argument("--confirm", action="store_true")
    # A no-op flag (dry run is the default); it exists so a caller can ask for it by name.
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--root", default=None)
    parser.add_argument("--only", default=None)

    try:
        parsed, unknown = parser.parse_known_args(args)
    except SystemExit as exc:
        logger.error(f"[export-vault] Argument parsing failed: {exc}")
        error("could not parse arguments", suggestion="drone @spawn export-vault --help")
        return 1

    if unknown:
        error(f"unknown argument(s): {' '.join(unknown)}", suggestion="drone @spawn export-vault --help")
        return 1

    try:
        receipt = export_seeds(root=parsed.root, only=parsed.only, confirm=parsed.confirm)
    except Exception as exc:
        logger.error(f"[export-vault] Unexpected error: {exc}")
        error(str(exc))
        return 1

    # Dry runs are logged too; they leave no other trace.
    json_handler.log_operation(
        "export_vault",
        data={
            "mode": "confirm" if parsed.confirm else "dry-run",
            "scanned": receipt["scanned"],
            "changed": receipt["changed"],
            "errors": len(receipt["errors"]),
        },
    )

    _print_receipt(receipt)
    return 1 if receipt["errors"] or not receipt["scanned"] else 0


def print_help():
    """Display export-vault command help."""
    console.print()
    console.print(
        "[bold cyan]Usage:[/bold cyan] drone @spawn export-vault "
        "\\[--dry-run|--confirm] \\[--root <path>] \\[--only <branch>]"
    )
    console.print()
    console.print(f"  Regenerate the TRACKED passport vault at [cyan]{VAULT_RELATIVE_PATH}[/cyan] from each")
    console.print("  citizen's live (gitignored) passport, so identities ship with the repo. In the AIPass tree")
    console.print("  that is every core citizen; in a project root, every citizen in that project's registry.")
    console.print("  The vault is the passport minus the machine-local facts: registered, registry_id,")
    console.print("  citizen_id, and the vault stamp itself. It is as fresh as its last write.")
    console.print(f"  A seat still holding the older {LEGACY_FILE_NAME} is rewritten under the vault name;")
    console.print("  the old file moves into the seat's .spawn/.recovery/.")
    console.print()
    console.print(
        "  [green](no args)[/green]        Dry run — report every vault that would change, write nothing "
        "[dim](default)[/dim]"
    )
    console.print("  [green]--dry-run[/green]        The same dry run, asked for by name")
    console.print("  [green]--confirm[/green]        Execute: write each new or changed vault")
    console.print("  [green]--root[/green] <path>    Where to find the registry [dim](default: the current dir)[/dim]")
    console.print("  [green]--only[/green] <branch>  Restrict to one branch (@ optional)")
    console.print()
    console.print("[dim]Vaults are GENERATED, never hand-edited — edit the passport, then re-export.[/dim]")
    console.print("[dim]Re-running is a measured no-op: an up-to-date vault reports 'current'.[/dim]")
    console.print()
    console.print("[yellow]Examples:[/yellow]")
    console.print("  [green]drone @spawn export-vault[/green]")
    console.print("  [green]drone @spawn export-vault --only @drone[/green]")
    console.print("  [green]drone @spawn export-vault --confirm[/green]")
    console.print()


def _print_receipt(receipt: dict) -> None:
    """Print the measured export receipt."""
    mode = "APPLIED" if receipt["confirm"] else "DRY RUN"

    console.print()
    header(f"Passport Vault Export — {mode}")
    console.print()
    console.print(f"  [bold]Root:[/bold] {receipt['root']}")
    if receipt["only"]:
        console.print(f"  [bold]Only:[/bold] {receipt['only']}")
    console.print()
    console.print(f"  Scanned:  {receipt['scanned']}  [dim]({receipt['scope']} citizens)[/dim]")
    console.print(f"  Created:  {receipt['created']}")
    console.print(f"  Updated:  {receipt['updated']}")
    console.print(f"  Current:  {receipt['current']}")
    console.print(f"  Written:  {receipt['written']}")

    if receipt["skipped_resident"]:
        console.print(
            f"  [dim]Residents and externals not exported: {receipt['skipped_resident']} "
            f"— each identity belongs to its own project's repo.[/dim]"
        )

    _print_per_branch(receipt)
    _print_errors(receipt)

    console.print()
    if not receipt["confirm"] and receipt["changed"]:
        console.print("  [dim]No files were written. Add --confirm to execute.[/dim]")
    elif not receipt["scanned"]:
        error(f"No {receipt['scope']} passports found under {receipt['root']} — nothing was scanned.")
    elif not receipt["changed"] and not receipt["errors"]:
        console.print("  [green]Every passport vault is already current — nothing to export.[/green]")
    console.print()


def _print_per_branch(receipt: dict) -> None:
    """Print one line per scanned branch."""
    console.print()
    console.print("[bold]Per branch:[/bold]")
    console.print("  [dim]each scanned branch's vault action, one line per branch[/dim]")
    for rec in receipt["seeds"]:
        if rec["error"]:
            continue
        retired = f"  [dim](old {LEGACY_FILE_NAME} moved to .spawn/.recovery/)[/dim]" if rec.get("retired") else ""
        console.print(f"  {rec['branch']:<14} {rec['action']}{retired}")


def _print_errors(receipt: dict) -> None:
    """Print every branch whose vault was refused, and why."""
    errors = receipt["errors"]
    if not errors:
        return
    console.print()
    error(f"{len(errors)} passport vault(s) could not be exported:")
    for item in errors:
        err_console.print(f"    {item['branch']}: {item['error']}")
