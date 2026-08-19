# =================== AIPass ====================
# Name: update.py
# Description: DAEMON Status Digest Module
# Version: 1.0.0
# Created: 2026-01-29
# Modified: 2026-01-29
# =============================================

"""
Returns digest of DAEMON activity for check-ins.
"""

# =============================================
# IMPORTS
# =============================================

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
from aipass.daemon.apps.handlers.update.data_loader import (
    load_inbox,
    load_local,
    categorize_messages,
    get_session_summary,
    get_escalations,
)


def _header(text):
    console.print(f"\n[bold cyan]{'=' * 70}[/bold cyan]")
    console.print(f"[bold cyan]  {text}[/bold cyan]")
    console.print(f"[bold cyan]{'=' * 70}[/bold cyan]")


# =============================================
# CONSTANTS
# =============================================

MODULE_NAME = "update"


# =============================================
# INTROSPECTION
# =============================================


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
        "  [cyan]*[/cyan] data_loader.py"
        " [dim](load_inbox, load_local,"
        " categorize_messages, get_session_summary,"
        " get_escalations — inbox and session data)[/dim]"
    )
    console.print()


# =============================================
# OUTPUT FORMATTING
# =============================================


def _print_digest(inbox_data: Dict[str, Any], local_data: Dict[str, Any]) -> None:
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

    session_summary = get_session_summary(local_data)
    console.print("[bold cyan]SESSION INFO[/bold cyan]")
    console.print(f"  Total sessions:      {session_summary['total_sessions']}")
    console.print(f"  Today's focus:       {session_summary['today_focus']}")

    recently_completed = session_summary.get("recently_completed", [])
    if recently_completed:
        console.print(f"  Recently completed:  {len(recently_completed)} tasks")
    else:
        console.print("  Recently completed:  [dim]None[/dim]")
    console.print()

    # Warn only when there is something to escalate. This header used to fire
    # unconditionally, so every quiet digest wrote "ESCALATIONS NEEDED" to stderr
    # above a stdout body reading "None - all clear" — a standing false alarm for
    # anything capturing stderr.
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
    console.print("    - Session info (focus, completed tasks)")
    console.print("    - Escalations needed (blocked, urgent)")
    console.print()


# =============================================
# ORCHESTRATION
# =============================================


def handle_command(command: str, args: list) -> bool:
    """
    Handle 'update' command.

    Args:
        command: Command name (should be 'update')
        args: Command arguments

    Returns:
        True if handled, False otherwise
    """
    if command != "update":
        return False

    try:
        if args and args[0] in ["--help", "-h", "help"]:
            print_help()
            return True

        # No args = run the digest (this is the primary use case)
        json_handler.log_operation("update_digest")
        inbox_data = load_inbox()
        local_data = load_local()
        _print_digest(inbox_data, local_data)

        logger.info("[DAEMON] Update digest generated successfully")
        return True

    except Exception as e:
        logger.error(f"[DAEMON] Error generating update digest: {e}", exc_info=True)
        error(f"Error: {e}")
        return True


# =============================================
# MAIN ENTRY
# =============================================


def main() -> None:
    """Main entry point for direct execution."""
    args = sys.argv[1:]

    if len(args) == 0 or args[0] in ["--help", "-h", "help"]:
        print_help()
        return

    handle_command("update", args)


if __name__ == "__main__":
    main()
