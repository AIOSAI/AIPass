# =================== AIPass ====================
# Name: update.py
# Description: DAEMON Status Digest Module
# Version: 1.0.1
# Created: 2026-01-29
# Modified: 2026-10-23
# =============================================

"""
Returns digest of DAEMON activity for check-ins.
"""

import os
import sys
from typing import Dict, Any, List

if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8", errors="replace")

from aipass.prax import logger

from aipass.cli.apps.modules import console, error, warning
from aipass.daemon.apps.handlers.json import json_handler
from aipass.daemon.apps.handlers.cli.arg_gate import gate
from aipass.daemon.apps.handlers.update.data_loader import (
    load_inbox,
    categorize_messages,
    get_escalations,
)


def _header(text):
    console.print(f"\n[bold cyan]{'=' * 70}[/bold cyan]")
    console.print(f"[bold cyan]  {text}[/bold cyan]")
    console.print(f"[bold cyan]{'=' * 70}[/bold cyan]")


MODULE_NAME = "update"


def print_introspection():
    """Display module introspection info."""
    console.print()
    console.print("[bold cyan]update Module[/bold cyan]")
    console.print()
    console.print("[dim]Returns digest of DAEMON activity for check-ins[/dim]")
    console.print()
    console.print("[yellow]Connected Handlers:[/yellow]")
    console.print("  handlers/update/")
    console.print(
        "  [cyan]*[/cyan] data_loader.py [dim](load_inbox, categorize_messages, get_escalations — inbox data)[/dim]"
    )
    console.print()


def _print_digest(inbox_data: Dict[str, Any]) -> None:
    """Print formatted digest to console."""
    console.print()
    _header("DAEMON Status Digest")
    console.print()

    messages: List[Dict[str, Any]] = inbox_data.get("messages", [])
    categories = categorize_messages(messages)

    console.print("[bold cyan]INBOX STATUS[/bold cyan]")
    console.print(f"  Total messages: {inbox_data.get('total_messages', 0)}")
    console.print(f"  Unread (new):   {len(categories['new'])}")
    console.print(f"  Opened:         {len(categories['opened'])}")
    console.print()

    console.print("[bold yellow]ACTIONABLE ITEMS[/bold yellow]")
    if categories["actionable"]:
        for msg in categories["actionable"][:5]:
            from_addr = msg.get("from", "unknown")
            subject = str(msg.get("subject", "No subject"))[:50]
            status = msg.get("status", "new")
            console.print(f"  [{status}] {from_addr}: {subject}")
    else:
        console.print("  [dim]None pending[/dim]")
    console.print()

    # Warn only when there is something to escalate: an unconditional warning is a false alarm on stderr.
    escalations = get_escalations(messages)
    if escalations:
        warning("ESCALATIONS NEEDED")
        for msg in escalations:
            console.print(f"  ! {msg.get('from', 'unknown')}: {str(msg.get('subject', ''))[:50]}")
    else:
        console.print("[bold cyan]ESCALATIONS[/bold cyan]")
        console.print("  [dim]None - all clear[/dim]")
    console.print()


def print_help() -> None:
    """Display help using Rich formatted output."""
    console.print()
    _header("Update Module - DAEMON Status Digest")
    console.print()

    console.print("[yellow]USAGE:[/yellow]")
    console.print("  drone @daemon update")
    console.print("  daemon update")
    console.print()

    console.print("[yellow]DESCRIPTION:[/yellow]")
    console.print("  Returns a digest of DAEMON activity for check-ins.")
    console.print()
    console.print("  Gathers and displays:")
    console.print("    - Inbox status (total, unread, opened)")
    console.print("    - Actionable items (tasks, builds, requests)")
    console.print("    - Escalations needed (blocked, urgent)")
    console.print()


def handle_command(command: str, args: list) -> bool:
    """
    Handle 'update' command.
    """
    if command != "update":
        return False

    if args and args[0] in ["--help", "-h", "help"]:
        print_help()
        return True

    # OUTSIDE the try: the digest's catch-all would swallow this refusal and report it as a digest failure.
    gate("update", args, usage="drone @daemon update")

    try:
        json_handler.log_operation("update_digest")
        _print_digest(load_inbox())

        logger.info("[DAEMON] Update digest generated successfully")
        return True

    except Exception as e:
        logger.error(f"[DAEMON] Error generating update digest: {e}", exc_info=True)
        error(f"Error: {e}")
        # SystemExit, not a return: True is the success answer, and the router's
        # `except Exception` would turn a False or a re-raise into "Unknown command".
        raise SystemExit(1) from e


def main() -> None:
    """Main entry point for direct execution.

    Help is screened ANYWHERE in the args: handle_command checks only args[0], and the gate would refuse the rest.
    """
    args = sys.argv[1:]

    if not args or any(a in ("--help", "-h", "help") for a in args):
        print_help()
        return

    handle_command("update", args)


if __name__ == "__main__":
    main()
