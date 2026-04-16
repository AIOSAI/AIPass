# =================== AIPass ====================
# Name: reply.py
# Description: Email Reply Handler
# Version: 1.0.0
# Created: 2025-11-30
# Modified: 2025-11-30
# =============================================

"""
Email Reply Handler

Handles replying to emails and auto-closing the original.
"""

import json
import uuid
from pathlib import Path
from typing import Dict, Tuple, Optional
from datetime import datetime

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.ai_mail.apps.handlers.json import json_handler

# Services imported in __main__ only (handlers should not display)


def get_email_by_id(inbox_file: Path, message_id: str) -> Optional[Dict]:
    """
    Get an email from inbox by its ID.

    Args:
        inbox_file: Path to inbox.json
        message_id: ID of message to find

    Returns:
        Email dict or None if not found
    """
    if not inbox_file.exists():
        return None

    try:
        with open(inbox_file, "r", encoding="utf-8") as f:
            inbox_data = json.load(f)

        for msg in inbox_data.get("messages", []):
            if msg.get("id") == message_id:
                return msg
        return None

    except Exception as e:
        logger.warning("[reply] get_email_by_id(%s, %s) failed: %s", inbox_file, message_id, e)
        return None


def send_reply(from_branch_path: Path, original_email: Dict, reply_message: str) -> Tuple[bool, str, Optional[str]]:
    """
    Send a reply to an email's original sender.

    This imports delivery and create handlers to send the reply,
    then closes the original email.

    Args:
        from_branch_path: Path to the replying branch
        original_email: The original email being replied to
        reply_message: The reply message content

    Returns:
        Tuple of (success: bool, message: str, reply_id: str or None)
    """
    json_handler.log_operation(
        "send_reply", {"from_branch": str(from_branch_path), "reply_to": original_email.get("from", "unknown")}
    )
    # Import here to avoid circular imports
    from aipass.ai_mail.apps.handlers.email.delivery import deliver_email_to_branch
    from aipass.ai_mail.apps.handlers.registry.read import get_all_branches
    from aipass.ai_mail.apps.handlers.email.inbox_cleanup import mark_as_closed_and_archive
    from aipass.ai_mail.apps.handlers.users.branch_detection import get_branch_info_from_registry

    # Get sender info from current branch
    sender_info = get_branch_info_from_registry(from_branch_path)
    if not sender_info:
        return False, "Could not detect sender branch", None

    # REPLY CHAIN VALIDATION: Check if this was a dispatched email
    # If dispatched_to is set, only that branch should be replying
    dispatched_to = original_email.get("dispatched_to")
    current_sender = sender_info.get("email", "@unknown")

    # Normalize dispatched_to to email format if it's a path
    # DRONE's preprocess_args converts @branch to paths, so we may receive
    # a filesystem path instead of "@trigger"
    if dispatched_to and not dispatched_to.startswith("@"):
        # It's a path - look up email in registry
        dispatch_info = get_branch_info_from_registry(Path(dispatched_to))
        if dispatch_info:
            dispatched_to = dispatch_info.get("email", dispatched_to)

    if dispatched_to and dispatched_to != current_sender:
        error_msg = f"IDENTITY MISMATCH: Dispatched to {dispatched_to}, reply from {current_sender}"
        # Fail loud - raise exception to stop execution (caller logs this)
        raise RuntimeError(error_msg)

    # Get reply destination - use reply_to if set, otherwise use original sender
    # This allows emails to specify where replies should go (e.g., broadcasts from devpulse)
    reply_destination = original_email.get("reply_to") or original_email.get("from", "")
    if not reply_destination:
        return False, "Original email has no sender or reply_to address", None

    # Create reply subject
    original_subject = original_email.get("subject", "No subject")
    reply_subject = f"RE: {original_subject}" if not original_subject.startswith("RE:") else original_subject

    # Build reply email data
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    reply_email_data = {
        "from": sender_info.get("email", "@unknown"),
        "from_name": sender_info.get("name", "Unknown"),
        "to": reply_destination,
        "subject": reply_subject,
        "message": reply_message,
        "timestamp": timestamp,
        "in_reply_to": original_email.get("id"),  # Link to original message
    }

    # Find recipient branch
    branches = get_all_branches()
    target_branch = None
    for branch in branches:
        if branch.get("email") == reply_destination:
            target_branch = branch
            break

    if not target_branch:
        # Fallback: cross-project delivery via reply_path stored at receive time
        stored_reply_path = original_email.get("reply_path")
        if stored_reply_path:
            return _deliver_via_reply_path(stored_reply_path, reply_email_data, from_branch_path, original_email)
        return False, f"Could not find branch for {reply_destination}", None

    # Deliver the reply (pass email address, not path)
    success, error_msg = deliver_email_to_branch(reply_destination, reply_email_data)
    if not success:
        return False, f"Failed to deliver reply: {error_msg}", None

    # Save to sender's sent folder
    sent_folder = from_branch_path / ".ai_mail.local" / "sent"
    sent_folder.mkdir(parents=True, exist_ok=True)

    reply_id = str(uuid.uuid4())[:8]
    reply_email_data["id"] = reply_id
    sent_file = sent_folder / f"{reply_id}.json"
    with open(sent_file, "w", encoding="utf-8") as f:
        json.dump(reply_email_data, f, indent=2)

    # Auto-close the original email
    original_id = original_email.get("id")
    if original_id:
        close_success, close_msg = mark_as_closed_and_archive(from_branch_path, original_id)
        if not close_success:
            # Reply sent but close failed - not critical
            return True, f"Reply sent (warning: original not closed: {close_msg})", reply_id

    return True, f"Reply sent to {reply_destination}, original closed", reply_id


def _deliver_via_reply_path(
    reply_path: str,
    reply_email_data: Dict,
    from_branch_path: Path,
    original_email: Dict,
) -> Tuple[bool, str, Optional[str]]:
    """Deliver reply directly to an external project's inbox via stored reply_path.

    Used when the recipient is not in the AIPass registry (cross-project reply).
    Writes directly to the inbox.json at the stored path, then saves to sent/
    and closes the original.

    Args:
        reply_path: Absolute path to the target inbox.json (stored at receive time).
        reply_email_data: The reply email dict to deliver.
        from_branch_path: Path to the replying branch (for sent folder and close).
        original_email: The original email being replied to (for close).

    Returns:
        Tuple of (success, message, reply_id or None)
    """
    inbox_file = Path(reply_path)
    if not inbox_file.exists():
        return False, f"reply_path inbox not found: {reply_path}", None

    try:
        with open(inbox_file, "r", encoding="utf-8") as f:
            inbox_data = json.load(f)
    except Exception as e:
        logger.warning("[reply] _deliver_via_reply_path read failed %s: %s", reply_path, e)
        return False, f"Failed to read target inbox: {e}", None

    reply_id = str(uuid.uuid4())[:8]
    reply_email_data["id"] = reply_id

    inbox_data.setdefault("messages", []).insert(0, reply_email_data)
    inbox_data["total_messages"] = len(inbox_data["messages"])
    new_count = sum(1 for m in inbox_data["messages"] if m.get("status") == "new" or not m.get("read", False))
    inbox_data["unread_count"] = new_count

    try:
        with open(inbox_file, "w", encoding="utf-8") as f:
            json.dump(inbox_data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.warning("[reply] _deliver_via_reply_path write failed %s: %s", reply_path, e)
        return False, f"Failed to write to target inbox: {e}", None

    logger.info("[reply] Cross-project reply delivered to %s", reply_path)

    # Save to sender's sent folder
    sent_folder = from_branch_path / ".ai_mail.local" / "sent"
    sent_folder.mkdir(parents=True, exist_ok=True)
    sent_file = sent_folder / f"{reply_id}.json"
    try:
        with open(sent_file, "w", encoding="utf-8") as f:
            json.dump(reply_email_data, f, indent=2)
    except Exception as e:
        logger.warning("[reply] failed to save sent copy: %s", e)

    # Auto-close the original email
    from aipass.ai_mail.apps.handlers.email.inbox_cleanup import mark_as_closed_and_archive

    original_id = original_email.get("id")
    if original_id:
        close_success, close_msg = mark_as_closed_and_archive(from_branch_path, original_id)
        if not close_success:
            return True, f"Reply sent (warning: original not closed: {close_msg})", reply_id

    destination = reply_email_data.get("to", reply_path)
    return True, f"Reply sent to {destination} via reply_path, original closed", reply_id


if __name__ == "__main__":
    from aipass.cli.apps.modules import console

    console.print("\n" + "=" * 70)
    console.print("EMAIL REPLY HANDLER")
    console.print("=" * 70)
    console.print("\nPURPOSE:")
    console.print("  Sends reply to email's original sender and auto-closes original")
    console.print()
    console.print("FUNCTIONS PROVIDED:")
    console.print("  - get_email_by_id(inbox_file, message_id) -> dict or None")
    console.print("  - send_reply(from_path, original_email, message) -> (bool, str, id)")
    console.print()
    console.print("WORKFLOW:")
    console.print("  1. Find original email by ID")
    console.print("  2. Create reply with RE: subject")
    console.print("  3. Deliver to original sender's inbox")
    console.print("  4. Save to sender's sent folder")
    console.print("  5. Auto-close original email")
    console.print()
    console.print("=" * 70 + "\n")
