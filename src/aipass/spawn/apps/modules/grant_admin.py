# =================== AIPass ====================
# Name: grant_admin.py
# Description: Seat-flag ceremonies — thin CLI layer for the registry admin and ci_cure flags
# Version: 1.1.0
# Created: 2026-08-12
# Modified: 2026-10-23
# =============================================

"""Seat-flag ceremonies: admin on the devpulse entry, ci_cure on the trigger entry.

Each flag is one leg of a lane drone verifies; spawn owns only the write.
"""

from aipass.prax import logger

from aipass.cli.apps.modules import console, error

from aipass.spawn.apps.handlers.registry import ADMIN_BRANCH, CI_CURE_BRANCH, ensure_admin, ensure_ci_cure
from aipass.spawn.apps.handlers.json import json_handler


def print_introspection():
    """Display module introspection info."""
    console.print()
    console.print("[bold cyan]grant_admin Module[/bold cyan]")
    console.print(f"Admin ceremony — writes admin:true onto the {ADMIN_BRANCH} registry entry")
    console.print(f"ci-cure ceremony — writes ci_cure:true onto the {CI_CURE_BRANCH} registry entry")
    console.print()
    console.print("[yellow]Connected Handlers:[/yellow]")
    console.print("  [cyan]handlers/[/cyan]")
    console.print(f"    [dim]- registry.py (ensure_admin — sanctioned writer, {ADMIN_BRANCH}-only fence)[/dim]")
    console.print(f"    [dim]- registry.py (ensure_ci_cure — {CI_CURE_BRANCH}-only, one holder)[/dim]")
    console.print()


def handle_command(command: str, args: list) -> bool:
    """Handle commands routed by the entry point."""
    if command == "grant-admin":
        handler = handle_grant_admin
    elif command == "grant-ci-cure":
        handler = handle_grant_ci_cure
    else:
        return False

    if not args:
        print_introspection()
        return True

    if "--help" in args:
        print_introspection()
        return True

    return handler(args) == 0


def _print_usage() -> None:
    """Print the ceremony usage block."""
    console.print("[bold cyan]Usage:[/bold cyan] drone @spawn grant-admin [--registry <path>]")
    console.print()
    console.print(f"  [dim]Writes admin:true onto the {ADMIN_BRANCH} entry of the root registry.[/dim]")
    console.print("  [green]--registry[/green]  Path to AIPASS_REGISTRY.json [dim](default: discover from CWD)[/dim]")
    console.print()
    console.print(f"  [dim]Takes no branch argument — admin is a {ADMIN_BRANCH}-only privilege (DPLAN-0288).[/dim]")
    console.print("  [dim]The flag alone grants nothing: the lane verifies five legs.[/dim]")


def _print_ci_cure_usage() -> None:
    """Print the ci-cure ceremony usage block."""
    console.print("[bold cyan]Usage:[/bold cyan] drone @spawn grant-ci-cure [--registry <path>]")
    console.print()
    console.print(f"  [dim]Writes ci_cure:true onto the {CI_CURE_BRANCH} entry of the root registry.[/dim]")
    console.print("  [green]--registry[/green]  Path to AIPASS_REGISTRY.json [dim](default: discover from CWD)[/dim]")
    console.print()
    console.print(f"  [dim]Takes no branch argument — ci_cure is a {CI_CURE_BRANCH}-only privilege.[/dim]")
    console.print("  [dim]Refused when another entry already carries it: drone's tier needs exactly one holder.[/dim]")


def _run_ceremony(args: list[str], verb: str, flag: str, seat: str, ensure) -> int:
    """Parse --registry, refuse a branch argument, run the writer.

    Returns exit code (0=granted or already granted, 1=refused/failure).
    """
    registry_path = None
    positional = []
    i = 0
    while i < len(args):
        if args[i] == "--registry" and i + 1 < len(args):
            registry_path = args[i + 1]
            i += 2
        elif args[i].startswith("--"):
            i += 1
        else:
            positional.append(args[i])
            i += 1

    if positional:
        error(
            f"{verb} takes no branch argument (got '{positional[0]}') — "
            f"{flag} is a {seat}-only privilege and the seat is a constant",
            suggestion=f"drone @spawn {verb} [--registry <path>]",
        )
        return 1

    try:
        status, reason = ensure(registry_path)
    except Exception as exc:
        logger.error(f"[{verb}] Unexpected error: {exc}")
        error(str(exc))
        return 1

    # Refusals are logged too, so a rejected attempt on the seat leaves a trace.
    json_handler.log_operation(f"{flag}_ceremony", data={"branch": seat, "status": status})

    console.print()
    if status == "refused":
        error(reason)
        console.print()
        return 1

    title = "Admin" if flag == "admin" else flag.replace("_", "-")
    label = f"{title} granted" if status == "granted" else f"{title} already in place"
    console.print(f"[green]{label}[/green]")
    console.print(f"  {reason}")
    console.print()
    return 0


def handle_grant_admin(args: list[str]) -> int:
    """Run the admin grant ceremony.

    A branch argument is refused: the seat is a constant, not a choice.
    Returns exit code (0=granted or already granted, 1=refused/failure).
    """
    if "--help" in args or "-h" in args:
        _print_usage()
        return 0

    if _run_ceremony(args, "grant-admin", "admin", ADMIN_BRANCH, ensure_admin):
        return 1
    console.print("  [dim]This flag is one of five legs — the dispatch lane still verifies[/dim]")
    console.print("  [dim]caller identity, cert path, cert content and signature.[/dim]")
    console.print()
    return 0


def handle_grant_ci_cure(args: list[str]) -> int:
    """Run the ci-cure grant ceremony: ci_cure:true onto the trigger entry, one holder only.

    Returns exit code (0=granted or already granted, 1=refused/failure).
    """
    if "--help" in args or "-h" in args:
        _print_ci_cure_usage()
        return 0

    if _run_ceremony(args, "grant-ci-cure", "ci_cure", CI_CURE_BRANCH, ensure_ci_cure):
        return 1
    console.print("  [dim]drone's ci-cure tier still checks tenancy and the passport's path-binding.[/dim]")
    console.print()
    return 0
