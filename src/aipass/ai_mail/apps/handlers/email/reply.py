# =================== AIPass ====================
# Name: reply.py
# Description: Email Reply Handler
# Version: 1.1.2
# Created: 2025-11-30
# Modified: 2026-10-17
# =============================================

"""
Email Reply Handler
"""

import json
import os
import sys
import uuid
from pathlib import Path
from typing import Dict, Tuple, Optional
from datetime import datetime

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.ai_mail.apps.handlers.json import json_handler
from aipass.ai_mail.apps.handlers.paths import registries_in
from aipass.ai_mail.apps.handlers.email.delivery import deliver_to_inbox_file
from aipass.ai_mail.apps.handlers.dispatch.report import stamp_dispatch_id

if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8", errors="replace")


def get_email_by_id(inbox_file: Path, message_id: str) -> Optional[Dict]:
    """Get an email from inbox by its ID.

    An unreadable inbox raises (OSError, ValueError): None would read as "message not found".
    """
    if not inbox_file.exists():
        return None

    with open(inbox_file, "r", encoding="utf-8") as f:
        inbox_data = json.load(f)

    from aipass.ai_mail.apps.handlers.email.inbox_ops import find_message

    return find_message(inbox_data.get("messages", []), message_id)


def send_reply(from_branch_path: Path, original_email: Dict, reply_message: str) -> Tuple[bool, str, Optional[str]]:
    """Send a reply to an email's original sender."""
    json_handler.log_operation(
        "send_reply", {"from_branch": str(from_branch_path), "reply_to": original_email.get("from", "unknown")}
    )
    from aipass.ai_mail.apps.handlers.email.delivery import deliver_email_to_branch
    from aipass.ai_mail.apps.handlers.registry.read import get_all_branches
    from aipass.ai_mail.apps.handlers.email.inbox_cleanup import mark_as_closed_and_archive
    from aipass.ai_mail.apps.handlers.users.branch_detection import get_branch_info_from_registry

    sender_info = get_branch_info_from_registry(from_branch_path)
    if not sender_info:
        return False, "Could not detect sender branch", None

    dispatched_to = original_email.get("dispatched_to")
    current_sender = sender_info.get("email", "@unknown")

    # drone's preprocess_args turns @branch into a path, so dispatched_to may be one.
    if dispatched_to and not dispatched_to.startswith("@"):
        dispatch_info = get_branch_info_from_registry(Path(dispatched_to))
        if dispatch_info:
            dispatched_to = dispatch_info.get("email", dispatched_to)

    if dispatched_to and dispatched_to != current_sender:
        error_msg = f"IDENTITY MISMATCH: Dispatched to {dispatched_to}, reply from {current_sender}"
        raise RuntimeError(error_msg)

    reply_destination = original_email.get("reply_to") or original_email.get("from", "")
    if not reply_destination:
        return False, "Original email has no sender or reply_to address", None

    original_subject = original_email.get("subject", "No subject")
    reply_subject = f"RE: {original_subject}" if not original_subject.startswith("RE:") else original_subject

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    reply_email_data = {
        "from": sender_info.get("email", "@unknown"),
        "from_name": sender_info.get("name", "Unknown"),
        "to": reply_destination,
        "subject": reply_subject,
        "message": reply_message,
        "timestamp": timestamp,
        "in_reply_to": original_email.get("id"),  # Link to original message
        # Return address for external recipients; from the replying branch, never the CWD guess.
        "reply_path": str(from_branch_path / ".ai_mail.local" / "inbox.json"),
    }

    # Stamped before either delivery lane runs, so both lanes' sent records carry it.
    stamp_dispatch_id(reply_email_data)

    branches = get_all_branches()
    target_branch = None
    for branch in branches:
        if branch.get("email") == reply_destination:
            target_branch = branch
            break

    if not target_branch:
        stored_reply_path = original_email.get("reply_path")
        if stored_reply_path:
            return _deliver_via_reply_path(stored_reply_path, reply_email_data, from_branch_path, original_email)
        return False, f"Could not find branch for {reply_destination}", None

    # Mint the id BEFORE delivering: the recipient's copy carries it as sent_id back to sent/.
    reply_id = str(uuid.uuid4())[:8]
    reply_email_data["id"] = reply_id

    success, error_msg = deliver_email_to_branch(reply_destination, reply_email_data)
    if not success:
        return False, f"Failed to deliver reply: {error_msg}", None

    sent_folder = from_branch_path / ".ai_mail.local" / "sent"
    sent_folder.mkdir(parents=True, exist_ok=True)

    sent_file = sent_folder / f"{reply_id}.json"
    with open(sent_file, "w", encoding="utf-8") as f:
        json.dump(reply_email_data, f, indent=2)

    # AFTER delivery, never before: closing for an undelivered reply erases an open promise.
    _close_dispatch_row_on_reply(reply_email_data)

    original_id = original_email.get("id")
    if original_id:
        close_success, close_msg = mark_as_closed_and_archive(from_branch_path, original_id)
        if not close_success:
            return True, f"Reply sent (warning: original not closed: {close_msg})", reply_id

    return True, f"Reply sent to {reply_destination}, original closed", reply_id


def _close_dispatch_row_on_reply(reply_email_data: Dict) -> None:
    """Close the dispatch register row this reply answers. Never raises.

    Matched by thread (replier, recipient, subject), not the dispatch stamp, which names the
    dispatch the agent runs under. Never raises: the reply is already delivered.
    """
    try:
        from aipass.ai_mail.apps.handlers.dispatch import register

        closed = register.close_on_reply(
            replier=str(reply_email_data.get("from", "")),
            recipient=str(reply_email_data.get("to", "")),
            subject=str(reply_email_data.get("subject", "")),
        )
        if closed:
            logger.info("[reply] dispatch %s closed — its target reported back on the thread", closed[:8])
    except Exception as e:
        logger.warning("[reply] could not close a dispatch row for this reply: %s", e)


def _validate_reply_path(reply_path: str) -> Tuple[bool, str]:
    """Validate that reply_path points to a legitimate inbox.json.

    The ancestor check globs *_REGISTRY.json: external projects name theirs PROJECTNAME_REGISTRY.json.
    """
    try:
        path = Path(reply_path).resolve()
    except (OSError, ValueError) as e:
        logger.warning("[reply] _validate_reply_path resolution failed: %s", e)
        return False, f"Path resolution failed: {e}"

    if path.name != "inbox.json" or path.parent.name != ".ai_mail.local":
        return False, f"Path does not end with .ai_mail.local/inbox.json: {path}"

    for parent in path.parents:
        if registries_in(parent):
            return True, ""
        if parent == parent.parent:
            break

    return False, f"No *_REGISTRY.json found in ancestors of {path}"


def _deliver_via_reply_path(
    reply_path: str,
    reply_email_data: Dict,
    from_branch_path: Path,
    original_email: Dict,
) -> Tuple[bool, str, Optional[str]]:
    """Deliver reply directly to an external project's inbox via stored reply_path."""
    valid, reason = _validate_reply_path(reply_path)
    if not valid:
        logger.warning("[reply] reply_path rejected: %s", reason)
        return False, f"Invalid reply_path: {reason}", None

    inbox_file = Path(reply_path).resolve()
    success, error_msg, reply_id = deliver_to_inbox_file(inbox_file, reply_email_data)
    if not success:
        logger.warning("[reply] _deliver_via_reply_path failed for %s: %s", reply_path, error_msg)
        return False, f"Failed to deliver to reply_path: {error_msg}", None

    reply_email_data["id"] = reply_id
    logger.info("[reply] Cross-project reply delivered to %s", reply_path)

    sent_folder = from_branch_path / ".ai_mail.local" / "sent"
    sent_folder.mkdir(parents=True, exist_ok=True)
    sent_file = sent_folder / f"{reply_id}.json"
    try:
        with open(sent_file, "w", encoding="utf-8") as f:
            json.dump(reply_email_data, f, indent=2)
    except Exception as e:
        logger.warning("[reply] failed to save sent copy: %s", e)

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
