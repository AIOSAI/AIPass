# =================== AIPass ====================
# Name: admin_grant.py
# Description: Admin grant module — birth-cert privilege ceremony CLI (FPLAN-0401)
# Version: 1.2.1
# Created: 2026-08-12
# Modified: 2026-10-18
# =============================================

"""
Admin grant ceremony — keygen, mint, verify the birth-cert admin privilege.
"""

from aipass.prax import logger
from aipass.cli.apps.modules import console, error
from aipass.devpulse.apps.handlers.json import json_handler

from aipass.devpulse.apps.handlers.owner.admin_grant import (
    generate_key,
    grant_status,
    mint_grant,
    verify_admin_grant,
)

HELP_TEXT = """\
[bold cyan]admin_grant[/bold cyan] — birth-cert admin privilege ceremony (DPLAN-0288)

[bold]Usage:[/bold]
  admin_grant status              Ceremony/lane state (key, cert, signature, verify)
  admin_grant verify              Run the full 5-leg contract check
  admin_grant keygen              Generate signing key at ~/.aipass/admin_grant.key (owner)
  admin_grant keygen --force      Regenerate key (invalidates existing signature) (owner)
  admin_grant mint                Add + sign the admin privilege block on the cert (owner)
  admin_grant --help              Show this help

[dim]Ceremony order: keygen -> mint -> grant-admin registry flag (via @spawn) -> verify.[/dim]
"""


def _guard_caller() -> bool:
    """Owner-only gate for ceremony verbs (see handlers.owner.guard).

    ``error``, not ``warning``: warning skips mark_command_failed, and the shell would read a refusal as success.
    """
    from aipass.devpulse.apps.handlers.owner.guard import guard_owner_caller, owner_address

    if guard_owner_caller("admin_grant"):
        return True
    owner = owner_address()
    whose = f"they belong to {owner}" if owner else "no owner is sealed or readable for this project"
    error(
        "admin_grant ceremony verbs are owner-only and this seat is not the owner",
        suggestion=(
            f"{whose} — ownership is the entry marked owner: true in the project's sealed registry. "
            "Run 'aipass doctor' if you believe the seat is wrong. 'admin_grant --help' works from anywhere."
        ),
    )
    return False


def print_introspection() -> None:
    """Display module introspection info."""
    console.print()
    console.print("[bold cyan]admin_grant Module[/bold cyan]")
    console.print("[dim]Birth-certificate admin privilege: keygen, mint (sign),[/dim]")
    console.print("[dim]verify — the DPLAN-0288 ceremony tooling.[/dim]")
    console.print()
    console.print("[yellow]Subcommands:[/yellow] [cyan]status, verify, keygen, mint[/cyan]")
    console.print()


def _cmd_status() -> None:
    state = grant_status()
    console.print("[bold cyan]admin grant status[/bold cyan]")
    console.print(f"  key present : {state['key_present']}")
    console.print(f"  cert present: {state['cert_present']}")
    console.print(f"  privileges  : {state['privileges'] or 'none'}")
    console.print(f"  signed      : {state['signed']}")
    verdict = "[green]VERIFIED[/green]" if state["verified"] else "[yellow]not verified[/yellow]"
    console.print(f"  verify      : {verdict} — {state['verify_reason']}")


def _cmd_verify() -> None:
    ok, reason = verify_admin_grant()
    if ok:
        console.print(f"[green]VERIFIED[/green] — {reason}")
    else:
        # error, not a print: a refusal that exits 0 lets a chained next step run on an unverified grant.
        error(f"REFUSED — {reason}")


def _cmd_keygen(args: list[str]) -> None:
    if not _guard_caller():
        return
    ok, message = generate_key(force="--force" in args)
    if ok:
        console.print(f"[green]OK[/green] — {message}")
        console.print("[dim]Next: admin_grant mint, then the @spawn grant-admin registry flag.[/dim]")
    else:
        error(f"REFUSED — {message}")  # same reason as verify: a refusal exits non-zero


def _cmd_mint() -> None:
    if not _guard_caller():
        return
    ok, message = mint_grant()
    if ok:
        console.print(f"[green]OK[/green] — {message}")
        console.print("[dim]Next: @spawn grant-admin registry flag, then admin_grant verify.[/dim]")
    else:
        error(f"REFUSED — {message}")  # same reason as verify: a refusal exits non-zero


def _wants_help(args: list[str]) -> bool:
    """Help flag anywhere in args = explain, never execute; bare 'help' only first, later positions are values."""
    return bool(args) and (args[0] in ("--help", "-h", "help") or any(a in ("--help", "-h") for a in args))


def handle_command(command: str, args: list[str]) -> bool:
    """Route admin_grant commands to handler functions."""
    if command != "admin_grant":
        return False

    if not args:
        print_introspection()
        return True

    if _wants_help(args):
        console.print(HELP_TEXT)
        return True

    verb, rest = args[0], args[1:]
    logger.info("[admin_grant] verb=%s", verb)
    json_handler.log_operation("admin_grant", {"verb": verb})

    if verb == "status":
        _cmd_status()
    elif verb == "verify":
        _cmd_verify()
    elif verb == "keygen":
        _cmd_keygen(rest)
    elif verb == "mint":
        _cmd_mint()
    else:
        # error, not warning: an unrecognised verb ran nothing, and a chained caller needs the exit code to say so.
        error(f"unknown admin_grant verb: {verb}", suggestion="Use 'admin_grant --help' for usage")
        console.print(HELP_TEXT)
    return True
