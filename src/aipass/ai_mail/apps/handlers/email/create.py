# =================== AIPass ====================
# Name: create.py
# Description: Email File Creation Handler
# Version: 1.2.0
# Created: 2025-11-15
# Modified: 2025-11-15
# =============================================

"""
Email File Creation Handler

Handles creation and storage of email files in sent folders.
Independent handler - no module dependencies.
"""

import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.ai_mail.apps.handlers.json import json_handler

# Lazy imports
_append_footer = None


def _get_append_footer():
    """Lazy import append_footer."""
    global _append_footer
    if _append_footer is None:
        from aipass.ai_mail.apps.handlers.email.footer import append_footer

        _append_footer = append_footer
    return _append_footer


def create_email_file(
    to_branch: str,
    subject: str,
    message: str,
    user_info: Dict,
    reply_to: str | None = None,
    dispatched_to: str | None = None,
) -> Path:
    """
    Create email file and save to sent folder.

    Args:
        to_branch: Recipient email address (e.g., "@admin" or "all")
        subject: Email subject line
        message: Email body text
        user_info: User information dict with keys:
            - email_address: Sender email address
            - display_name: Sender display name
            - timestamp_format: Datetime format string (default: "%Y-%m-%d %H:%M:%S")
            - mailbox_path: Path to user's mailbox directory
        reply_to: Optional branch address where replies should go instead of sender
        dispatched_to: Branch address where dispatch was sent (for reply chain validation)

    Returns:
        Path to created email file in sent folder
    """
    json_handler.log_operation("create_email_file", {"to": to_branch, "subject": subject})
    timestamp = datetime.now()
    timestamp_str = timestamp.strftime(user_info.get("timestamp_format", "%Y-%m-%d %H:%M:%S"))

    # Append standard footer to message
    message_with_footer = _get_append_footer()(message)

    # Create email data structure
    email_data = {
        "from": user_info["email_address"],
        "from_name": user_info["display_name"],
        "to": to_branch,
        "subject": subject,
        "message": message_with_footer,
        "timestamp": timestamp_str,
        "status": "sent",
    }

    # Add reply_to if specified (for redirecting replies to different branch)
    if reply_to:
        email_data["reply_to"] = reply_to

    # Add dispatched_to for reply chain validation (tracks original dispatch recipient)
    if dispatched_to:
        email_data["dispatched_to"] = dispatched_to

    # Create filename (safe, no special chars)
    safe_subject = "".join(c if c.isalnum() or c in (" ", "-", "_") else "_" for c in subject)
    safe_subject = safe_subject[:50].strip()  # Limit length
    filename = f"{timestamp.strftime('%Y%m%d_%H%M%S')}_{safe_subject}.json"

    # Save to sent folder
    mailbox_path = Path(user_info["mailbox_path"])
    sent_folder = mailbox_path / "sent"
    sent_folder.mkdir(parents=True, exist_ok=True)

    email_file = sent_folder / filename
    with open(email_file, "w", encoding="utf-8") as f:
        json.dump(email_data, f, indent=2)

    # Trigger auto-purge if sent folder exceeds threshold
    _trigger_sent_purge(mailbox_path)

    return email_file


def _trigger_sent_purge(mailbox_path: Path) -> None:
    """
    Trigger auto-purge of sent folder if threshold exceeded.

    Non-blocking - failures silently ignored.
    """
    try:
        from aipass.ai_mail.apps.handlers.email.purge import purge_sent_folder

        purge_sent_folder(mailbox_path)
    except Exception as e:
        logger.warning("[create] _trigger_sent_purge() failed: %s", e)


def load_email_file(email_file: Path) -> Optional[Dict]:
    """
    Load email data from file.

    Args:
        email_file: Path to email JSON file

    Returns:
        Email data dict or None if file cannot be read
    """
    if not email_file.exists():
        return None

    try:
        with open(email_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning("[create] load_email_file(%s) failed: %s", email_file, e)
        return None


if __name__ == "__main__":
    from rich.console import Console

    c = Console()
    c.print("\n" + "=" * 70)
    c.print("EMAIL FILE CREATION HANDLER")
    c.print("=" * 70)
    c.print("\nPURPOSE:")
    c.print("  Creates and stores email files in sent folders")
    c.print()
    c.print("FUNCTIONS PROVIDED:")
    c.print("  - create_email_file(to_branch, subject, message, user_info) -> Path")
    c.print("  - load_email_file(email_file) -> Optional[Dict]")
    c.print()
    c.print("HANDLER CHARACTERISTICS:")
    c.print("  ✓ Independent - no module dependencies")
    c.print("  ✓ Pure business logic")
    c.print("  ✗ CANNOT import parent modules")
    c.print()
    c.print("USAGE FROM MODULES:")
    c.print("  from ai_mail.apps.handlers.email.create import create_email_file")
    c.print("  from ai_mail.apps.handlers.email.create import load_email_file")
    c.print()
    c.print("=" * 70 + "\n")
