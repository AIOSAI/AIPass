# =================== AIPass ====================
# Name: format.py
# Description: Email Formatting Handler
# Version: 1.4.0
# Created: 2025-11-15
# Modified: 2026-10-17
# =============================================

"""
Email Formatting Handler

Every email-sourced string is sender-shaped Rich markup: escape it here, once, for every surface.
"""

import json
import os
import sys
from typing import Dict, Optional

from rich.markup import escape

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.ai_mail.apps.handlers.json import json_handler
from aipass.ai_mail.apps.handlers.paths import find_repo_root

if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8", errors="replace")


REGISTRY_PATH = find_repo_root() / "AIPASS_REGISTRY.json"


def lookup_branch_alias(branch_name: str) -> Optional[str]:
    """Look up a branch's alias from AIPASS_REGISTRY.json.

    Returns None when there is no alias to show, including an unreadable registry.
    """
    try:
        registry = json.loads(REGISTRY_PATH.read_text())
        for branch in registry.get("branches", []):
            if branch.get("name") == branch_name:
                alias = branch.get("alias", "")
                return alias if alias else None
        return None
    except Exception as e:
        logger.warning("[format] lookup_branch_alias(%s) failed: %s", branch_name, e)
        return None


def format_sender_display(from_name: str, from_addr: str) -> str:
    """Format sender display with alias if available."""
    alias = lookup_branch_alias(from_name)
    if alias:
        return f"{escape(alias)} ({escape(from_addr)})"
    return f"{escape(from_name)} ({escape(from_addr)})"


def format_email_preview(message: str, max_length: int = 100) -> str:
    """Format email message as preview text."""
    if len(message) <= max_length:
        return message

    return message[:max_length] + "..."


def format_update_count(email_data: Dict) -> int:
    """Read a message's repeat counter for display.

    Returns 0 for ordinary mail and a first send, so callers render nothing in the common case.
    """
    try:
        count = int(email_data.get("updates", 0))
    except (TypeError, ValueError):
        logger.warning("[format] unreadable updates counter on message %s", email_data.get("id", "?"))
        return 0
    return count if count > 1 else 0


def format_email_header(email_data: Dict) -> str:
    """Format email header for display."""
    json_handler.log_operation("format_email_header", {"subject": email_data.get("subject", "")})
    sender = format_sender_display(email_data.get("from_name", "Unknown"), email_data.get("from", "unknown"))
    lines = [
        "=" * 70,
        f"From: {sender}",
        f"Date: {escape(str(email_data.get('timestamp', 'Unknown')))}",
        f"Subject: {escape(str(email_data.get('subject', 'No Subject')))}",
    ]

    # One upserted message stands for N sends; without the count the reader sees one where there were thirty.
    updates = format_update_count(email_data)
    if updates:
        last = email_data.get("last_updated") or email_data.get("timestamp", "Unknown")
        lines.append(f"Updates: {updates} (last: {escape(str(last))})")

    lines.append("=" * 70)
    return "\n".join(lines)


def format_email_list_item(index: int, email_data: Dict, show_unread: bool = True) -> str:
    """Format email as list item for inbox/sent display."""
    lines = []

    msg_id = escape(str(email_data.get("id", "????????")))
    timestamp = escape(str(email_data.get("timestamp", "Unknown")))
    if show_unread:
        # v2 `status` wins; legacy messages carry only `read`.
        status = email_data.get("status")
        is_new = status == "new" if status else not email_data.get("read", False)
        unread_marker = "📨" if is_new else "📬"
        sender = format_sender_display(email_data.get("from_name", "Unknown"), email_data.get("from", "unknown"))
        updates = format_update_count(email_data)
        repeat = f" [yellow]x{updates}[/yellow]" if updates else ""
        lines.append(f"\n{index}. {unread_marker} \\[{msg_id}] From: {sender} @ {timestamp}{repeat}")
    else:
        recipient = escape(str(email_data.get("to", "Unknown")))
        # A refused sent record must not render like a delivered one: senders read the row as proof.
        refused = " [red]REFUSED[/red]" if email_data.get("status") == "refused" else ""
        lines.append(f"\n{index}. \\[{msg_id}] To: {recipient} @ {timestamp}{refused}")

    lines.append(f"   Subject: {escape(str(email_data.get('subject', 'No Subject')))}")

    if email_data.get("status") == "refused":
        reason = escape(str(email_data.get("refused_reason", "no reason recorded")))
        lines.append(f"   [red]Not delivered:[/red] {reason}")

    message = email_data.get("message", "")
    preview = format_email_preview(message, 100)
    lines.append(f"   {escape(preview)}")

    return "\n".join(lines)


if __name__ == "__main__":
    from aipass.cli.apps.modules import console

    console.print("\n" + "=" * 70)
    console.print("EMAIL FORMATTING HANDLER")
    console.print("=" * 70)
    console.print("\nPURPOSE:")
    console.print("  Email display formatting and text utilities")
    console.print()
    console.print("FUNCTIONS PROVIDED:")
    console.print("  - format_email_preview(message, max_length) -> str")
    console.print("  - format_update_count(email_data) -> int")
    console.print("  - format_email_header(email_data) -> str")
    console.print("  - format_email_list_item(index, email_data, show_unread) -> str")
    console.print()
    console.print("HANDLER CHARACTERISTICS:")
    console.print("  [green]+[/green] Independent - no module dependencies")
    console.print("  [green]+[/green] Can import Prax (service provider)")
    console.print("  [green]+[/green] Pure business logic")
    console.print("  [dim]-[/dim] CANNOT import parent modules")
    console.print()
    console.print("USAGE FROM MODULES:")
    console.print("  from ai_mail.apps.handlers.email.format import format_email_preview")
    console.print("  from ai_mail.apps.handlers.email.format import format_email_header")
    console.print()
    console.print("=" * 70 + "\n")
