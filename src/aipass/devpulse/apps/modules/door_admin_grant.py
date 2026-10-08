# =================== AIPass ====================
# Name: door_admin_grant.py
# Description: Door: devpulse's admin-grant verification, published for ai_mail's verified-caller rail (DPLAN-0404)
# Version: 1.0.0
# Created: 2026-10-07
# Modified: 2026-10-07
# =============================================

"""Door for apps/handlers/owner/admin_grant.py: the one home of the 5-leg admin contract."""

from aipass.cli.apps.modules import console
from aipass.devpulse.apps.handlers.json import json_handler
from aipass.devpulse.apps.handlers.owner.admin_grant import verify_admin_grant

__all__ = ["verify_admin_grant"]


def print_introspection() -> None:
    """Display module introspection info."""
    console.print()
    console.print("[bold cyan]door_admin_grant Door[/bold cyan]")
    console.print("[dim]Publishes verify_admin_grant for ai_mail's verified-caller rail;[/dim]")
    console.print("[dim]the implementation stays in handlers/owner/admin_grant.py.[/dim]")
    console.print()


def handle_command(command: str, args: list[str]) -> bool:
    """A door has no verbs: with or without arguments it prints what it publishes.

    Auto-discovered by devpulse.py module loader.
    """
    if command != "door_admin_grant":
        return False

    if not args:
        print_introspection()
        return True

    json_handler.log_operation("door_admin_grant", {"args": args})
    print_introspection()
    return True
