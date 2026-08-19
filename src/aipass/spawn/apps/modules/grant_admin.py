# =================== AIPass ====================
# Name: grant_admin.py
# Description: Admin ceremony — thin CLI layer for the registry admin flag
# Version: 1.0.0
# Created: 2026-08-12
# Modified: 2026-08-12
# =============================================

"""Admin grant ceremony for the devpulse seat (DPLAN-0288).

Thin CLI module that parses arguments and delegates to
``registry.ensure_admin``. Patrick runs this once, at the terminal.

The flag this writes GRANTS NOTHING on its own — the admin dispatch lane
verifies five legs (verified caller, cert path, cert content, HMAC
signature, and this registry flag). Spawn owns exactly one of them.

There is deliberately NO branch argument: the seat is a constant.
"""

from aipass.prax import logger

# CLI service: from cli.apps.modules import console (via aipass namespace)
from aipass.cli.apps.modules import console, error

from aipass.spawn.apps.handlers.registry import ADMIN_BRANCH, ensure_admin
from aipass.spawn.apps.handlers.json import json_handler


def print_introspection():
    """Display module introspection info."""
    console.print()
    console.print("[bold cyan]grant_admin Module[/bold cyan]")
    console.print(f"Admin ceremony — writes admin:true onto the {ADMIN_BRANCH} registry entry")
    console.print()
    console.print("[yellow]Connected Handlers:[/yellow]")
    console.print("  [cyan]handlers/[/cyan]")
    console.print(f"    [dim]- registry.py (ensure_admin — sanctioned writer, {ADMIN_BRANCH}-only fence)[/dim]")
    console.print()


# =============================================================================
# DRONE ROUTING
# =============================================================================


def handle_command(command: str, args: list) -> bool:
    """Handle commands routed by the entry point.

    Args:
        command: The command string (e.g. "grant-admin")
        args: List of arguments for the command

    Returns:
        True if command was handled, False otherwise.
    """
    if command != "grant-admin":
        return False

    # No args → introspection
    if not args:
        print_introspection()
        return True

    if "--help" in args:
        print_introspection()
        return True

    return handle_grant_admin(args) == 0


# =============================================================================
# PUBLIC API
# =============================================================================


def _print_usage() -> None:
    """Print the ceremony usage block."""
    console.print("[bold cyan]Usage:[/bold cyan] drone @spawn grant-admin [--registry <path>]")
    console.print()
    console.print(f"  [dim]Writes admin:true onto the {ADMIN_BRANCH} entry of the root registry.[/dim]")
    console.print("  [green]--registry[/green]  Path to AIPASS_REGISTRY.json [dim](default: discover from CWD)[/dim]")
    console.print()
    console.print(f"  [dim]Takes no branch argument — admin is a {ADMIN_BRANCH}-only privilege (DPLAN-0288).[/dim]")
    console.print("  [dim]The flag alone grants nothing: the lane verifies five legs.[/dim]")


def handle_grant_admin(args: list[str]) -> int:
    """Run the admin grant ceremony.

    Args patterns:
        []                          -> grant on the discovered root registry
        ["--registry", "<path>"]    -> grant on an explicit registry path

    A branch argument is REFUSED: the seat is a constant, not a choice.

    Returns exit code (0=granted or already granted, 1=refused/failure).
    """
    if "--help" in args or "-h" in args:
        _print_usage()
        return 0

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
            f"grant-admin takes no branch argument (got '{positional[0]}') — "
            f"admin is a {ADMIN_BRANCH}-only privilege and the seat is a constant",
            suggestion="drone @spawn grant-admin [--registry <path>]",
        )
        return 1

    try:
        status, reason = ensure_admin(registry_path)
    except Exception as exc:
        logger.error(f"[grant-admin] Unexpected error: {exc}")
        error(str(exc))
        return 1

    # The ceremony itself is logged — refusals included, so a rejected
    # attempt on the admin seat leaves a trace, not just a console line.
    json_handler.log_operation("admin_ceremony", data={"branch": ADMIN_BRANCH, "status": status})

    console.print()
    if status == "refused":
        error(reason)
        console.print()
        return 1

    label = "Admin granted" if status == "granted" else "Admin already in place"
    console.print(f"[green]{label}[/green]")
    console.print(f"  {reason}")
    console.print()
    console.print("  [dim]This flag is one of five legs — the dispatch lane still verifies[/dim]")
    console.print("  [dim]caller identity, cert path, cert content and signature.[/dim]")
    console.print()
    return 0
