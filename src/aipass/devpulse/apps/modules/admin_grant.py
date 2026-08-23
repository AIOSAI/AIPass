# =================== AIPass ====================
# Name: admin_grant.py
# Description: Admin grant module — birth-cert privilege ceremony CLI (FPLAN-0401)
# Version: 1.1.0
# Created: 2026-08-12
# Modified: 2026-08-22
# =============================================

"""
Admin grant ceremony — keygen, mint, verify the birth-cert admin privilege.

Auto-discovered by devpulse.py via handle_command() convention. The ceremony
verbs (keygen, mint) are owner-gated; status and verify are open reads.
DPLAN-0288 / FPLAN-0401: devpulse-only dispatch-anyone privilege, anchored in
a signed privilege block on the existing birth certificate.
"""

from aipass.prax import logger
from aipass.cli.apps.modules import err_console, error
from aipass.devpulse.apps.handlers.json import json_handler

from aipass.devpulse.apps.handlers.owner.admin_grant import (
    generate_key,
    grant_status,
    mint_grant,
    verify_admin_grant,
)

console = err_console

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

    ``error`` and NOT ``warning``: ``warning`` does not call
    ``mark_command_failed``, so this refusal used to EXIT 0 — a privilege
    ceremony reporting success to the shell while granting nothing. @canary
    found the identical defect in watchdog from a non-owner seat on 2026-08-22
    and asked whether the shared guard had other callers; it had two, and this
    was the worse one.
    """
    from aipass.devpulse.apps.handlers.owner.guard import guard_owner_caller, owner_address

    if guard_owner_caller("admin_grant"):
        return True
    owner = owner_address()
    whose = f"they belong to {owner}" if owner else "no owner is sealed for this project"
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
        console.print(f"[yellow]REFUSED[/yellow] — {reason}")


def _cmd_keygen(args: list[str]) -> None:
    if not _guard_caller():
        return
    ok, message = generate_key(force="--force" in args)
    if ok:
        console.print(f"[green]OK[/green] — {message}")
        console.print("[dim]Next: admin_grant mint, then the @spawn grant-admin registry flag.[/dim]")
    else:
        console.print(f"[yellow]REFUSED[/yellow] — {message}")


def _cmd_mint() -> None:
    if not _guard_caller():
        return
    ok, message = mint_grant()
    if ok:
        console.print(f"[green]OK[/green] — {message}")
        console.print("[dim]Next: @spawn grant-admin registry flag, then admin_grant verify.[/dim]")
    else:
        console.print(f"[yellow]REFUSED[/yellow] — {message}")


def _wants_help(args: list[str]) -> bool:
    """Help flag anywhere in args = explain, never execute (DPLAN-0291 rule E).

    Bare word 'help' counts only at position 0 — later positions may be values.
    """
    return bool(args) and (args[0] in ("--help", "-h", "help") or any(a in ("--help", "-h") for a in args))


def handle_command(command: str, args: list[str]) -> bool:
    """Route admin_grant commands to handler functions.

    Auto-discovered by devpulse.py module loader.

    Args:
        command: The primary command string.
        args: Additional arguments after the command.

    Returns:
        bool: True if the command was handled, False otherwise.
    """
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
        # error, not warning: an unrecognised verb ran nothing, and a caller
        # chaining on this needs the exit code to say so. watchdog's unknown
        # subcommand already exits 2; this one exited 0 for the same reason
        # the owner refusal above did.
        error(f"unknown admin_grant verb: {verb}", suggestion="Use 'admin_grant --help' for usage")
        console.print(HELP_TEXT)
    return True
