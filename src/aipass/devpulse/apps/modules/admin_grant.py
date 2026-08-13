# =================== AIPass ====================
# Name: admin_grant.py
# Description: Admin grant module — birth-cert privilege ceremony CLI (FPLAN-0401)
# Version: 1.0.0
# Created: 2026-08-12
# Modified: 2026-08-12
# =============================================

"""
Admin grant ceremony — keygen, mint, verify the birth-cert admin privilege.

Auto-discovered by devpulse.py via handle_command() convention. The ceremony
verbs (keygen, mint) are owner-gated; status and verify are open reads.
DPLAN-0288 / FPLAN-0401: devpulse-only dispatch-anyone privilege, anchored in
a signed privilege block on the existing birth certificate.
"""

from aipass.prax import logger
from aipass.cli.apps.modules import err_console, warning
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
    """Owner-only gate for ceremony verbs (see handlers.owner.guard)."""
    from aipass.devpulse.apps.handlers.owner.guard import guard_owner_caller

    if guard_owner_caller("admin_grant"):
        return True
    warning("admin_grant ceremony verbs are owner-only — refusing non-owner call")
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

    if args[0] in ("--help", "-h", "help"):
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
        warning(f"unknown admin_grant verb: {verb}")
        console.print(HELP_TEXT)
    return True
