# =================== AIPass ====================
# Name: delivery.py
# Description: Email Delivery Handler
# Version: 3.0.0
# Created: 2025-12-02
# Modified: 2025-12-02
# =============================================

"""
Email Delivery Handler

Handles delivery of emails to branch inboxes.
Independent handler - no module dependencies.
"""

import json
import os
import uuid
from pathlib import Path
from typing import Dict, Tuple, List, Optional, Callable

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.ai_mail.apps.handlers.json import json_handler
from aipass.ai_mail.apps.handlers.paths import find_repo_root
from aipass.ai_mail.apps.handlers.registry.read import get_all_branches


_REPO_ROOT = find_repo_root()

# Lazy imports to avoid circular dependencies
_INBOX_LOCK = None


def _load_caller_project_branches(caller_cwd: str) -> Dict[str, str]:
    """Load branches from the caller's project registry.

    Delegates to registry.read.get_caller_project_branches — shared
    implementation used by both delivery and wake for cross-project resolution.
    """
    from aipass.ai_mail.apps.handlers.registry.read import get_caller_project_branches

    return get_caller_project_branches(caller_cwd)


def _auto_register_contact(email: str, branch_path: Path, inbox_file: Path) -> None:
    """Auto-register a recipient in the contacts address book after successful delivery.

    Non-critical: failures are logged and silently ignored.

    Args:
        email: Recipient email address (e.g., '@devpulse').
        branch_path: Resolved path to the branch root directory.
        inbox_file: Path to the branch's inbox.json file.
    """
    try:
        from aipass.ai_mail.apps.handlers.email.contacts import register_contact

        name_key = email.lstrip("@").lower()
        register_contact(name_key, "AIPass", str(inbox_file))
    except Exception as e:
        logger.warning("[delivery] _auto_register_contact(%s) failed: %s", email, e)


def _auto_register_sender(branch_name: str, caller_cwd: str) -> None:
    """Auto-register a sender in contacts when called from an external project.

    Walks up from caller_cwd to find .ai_mail.local/inbox.json.
    Non-critical: failures are logged and silently ignored.

    Args:
        branch_name: Sender branch name or email (e.g., 'vera' or '@vera').
        caller_cwd: Working directory of the calling project.
    """
    try:
        candidate = Path(caller_cwd)
        for path in [candidate] + list(candidate.parents)[:5]:
            inbox_file = path / ".ai_mail.local" / "inbox.json"
            if inbox_file.exists():
                from aipass.ai_mail.apps.handlers.email.contacts import register_contact

                name_key = branch_name.lstrip("@").lower()
                register_contact(name_key, "", str(inbox_file))
                return
    except Exception as e:
        logger.warning("[delivery] _auto_register_sender(%s) failed: %s", branch_name, e)


def _get_inbox_lock():
    """Lazy import inbox_lock context manager."""
    global _INBOX_LOCK
    if _INBOX_LOCK is None:
        from aipass.ai_mail.apps.handlers.email.inbox_lock import inbox_lock

        _INBOX_LOCK = inbox_lock
    return _INBOX_LOCK


def _migrate_inbox_format(inbox_data: Dict, inbox_file: Path) -> Dict:
    """
    Auto-migrate old inbox format to v2 schema.

    Old format: {"inbox": [...]}
    New format: {"mailbox": "inbox", "total_messages": N, "unread_count": N, "messages": [...]}

    Migrates in-place and persists to disk if changes were made.

    Args:
        inbox_data: Loaded inbox dict (may be old or new format)
        inbox_file: Path to inbox.json (for persisting migration)

    Returns:
        Migrated inbox data dict with v2 schema
    """
    migrated = False

    # Case 0: inbox_data is a list instead of a dict (corrupted/malformed inbox.json)
    if isinstance(inbox_data, list):
        inbox_data = {"messages": inbox_data}
        migrated = True

    # Case 1: Old format with "inbox" key instead of "messages"
    if "inbox" in inbox_data and "messages" not in inbox_data:
        old_messages = inbox_data.pop("inbox", [])
        inbox_data["messages"] = old_messages if isinstance(old_messages, list) else []
        migrated = True

    # Case 2: Missing "messages" key entirely
    if "messages" not in inbox_data:
        inbox_data["messages"] = []
        migrated = True

    # Ensure v2 metadata fields exist
    if "mailbox" not in inbox_data:
        inbox_data["mailbox"] = "inbox"
        migrated = True

    if "total_messages" not in inbox_data:
        inbox_data["total_messages"] = len(inbox_data["messages"])
        migrated = True

    if "unread_count" not in inbox_data:
        inbox_data["unread_count"] = sum(
            1
            for msg in inbox_data["messages"]
            if msg.get("status") == "new" or (msg.get("status") is None and not msg.get("read", False))
        )
        migrated = True

    # Persist migration to disk
    if migrated:
        try:
            with open(inbox_file, "w", encoding="utf-8") as f:
                json.dump(inbox_data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.warning("[delivery] _migrate_inbox_format() failed to persist migration for %s: %s", inbox_file, e)
            return inbox_data

    return inbox_data


def _is_private_branch_email(email: str) -> bool:
    """Check if email belongs to a private branch.

    Reads PRIVATE_BRANCH_REGISTRY.json to determine if the given
    email address is registered to a private (isolated) branch.

    Args:
        email: Email address to check (e.g., "@patrick_private")

    Returns:
        True if email belongs to a private branch, False otherwise
    """
    registry_path = _REPO_ROOT / "PRIVATE_BRANCH_REGISTRY.json"
    if not registry_path.exists():
        return False
    try:
        with open(registry_path, "r", encoding="utf-8") as f:
            registry = json.load(f)
        for branch in registry.get("branches", []):
            if branch.get("email", "") == email:
                return True
    except (json.JSONDecodeError, IOError) as e:
        logger.warning("[delivery] _is_private_branch_email(%s) failed: %s", email, e)
    return False


def _resolve_reply_path() -> str:
    """Detect the caller's ai_mail inbox path from AIPASS_CALLER_CWD env var.

    Used to store a reply_path on delivered messages so cross-project replies
    can bypass registry lookup and write directly to the sender's inbox.

    Returns the absolute path to the caller's inbox.json, or empty string if
    AIPASS_CALLER_CWD is not set or no inbox directory is found.
    """
    caller_cwd = os.environ.get("AIPASS_CALLER_CWD", "")
    if not caller_cwd:
        return ""
    # Check the CWD itself and up to 5 parent directories for .ai_mail.local/
    candidate = Path(caller_cwd)
    for path in [candidate] + list(candidate.parents)[:5]:
        inbox = path / ".ai_mail.local" / "inbox.json"
        if inbox.exists():
            return str(inbox)
    return ""


def deliver_email_to_branch(
    to_branch: str, email_data: Dict, on_delivered: Optional[Callable] = None
) -> Tuple[bool, str]:
    """
    Deliver email to target branch's .ai_mail.local/inbox.json file.

    Appends message to inbox JSON messages array.

    Args:
        to_branch: Target email address (e.g., "@admin")
        email_data: Email data dict with keys:
            - from: Sender email address
            - from_name: Sender display name
            - to: Recipient email address
            - subject: Email subject
            - message: Email body
            - timestamp: Email timestamp string
        on_delivered: Optional callback(branch_path, new_count, opened_count, total)
            for post-delivery actions (dashboard updates, central sync, etc.)

    Returns:
        Tuple of (success: bool, error_message: str)
        error_message is empty string if successful
    """
    json_handler.log_operation("deliver_email", {"to": to_branch, "subject": email_data.get("subject", "")})

    # Handle path input from DRONE's @ resolution
    if to_branch.startswith("/"):
        branches_list = get_all_branches()
        path_to_email = {b["path"]: b["email"] for b in branches_list}
        if to_branch in path_to_email:
            to_branch = path_to_email[to_branch]
        else:
            # Stage 2: Longest-path-first prefix matching against registry
            sorted_branches = sorted(branches_list, key=lambda b: len(b["path"]), reverse=True)
            matched = False
            for b in sorted_branches:
                if to_branch.startswith(b["path"] + "/") or to_branch == b["path"]:
                    to_branch = b["email"]
                    matched = True
                    break
            if not matched:
                return False, f"Could not resolve path to email: {to_branch}"

    # Map email address to branch path (AIPass registry + caller's project registry)
    all_branches = get_all_branches()
    branches = {b["email"]: b["path"] for b in all_branches}

    if to_branch not in branches:
        # Check caller's project registry for local branches (e.g. @strategy in Vera Studio)
        caller_cwd = os.environ.get("AIPASS_CALLER_CWD", "")
        if caller_cwd:
            caller_branches = _load_caller_project_branches(caller_cwd)
            branches.update(caller_branches)

    if to_branch not in branches:
        error_msg = f"Unknown branch email: {to_branch} (available: {len(branches)} branches)"
        return False, error_msg

    # Private branch inbound blocking: reject delivery to private branches
    # Self-send is allowed (private branch can send to itself)
    sender_email = email_data.get("from", "")
    if _is_private_branch_email(to_branch) and sender_email != to_branch:
        return False, f"Cannot deliver to private branch: {to_branch}"

    raw_path = branches[to_branch]
    branch_path = Path(raw_path)
    if not branch_path.is_absolute():
        branch_path = (_REPO_ROOT / branch_path).resolve()

    # Find the branch's .ai_mail.local/inbox.json file
    if branch_path == Path("/") or branch_path == _REPO_ROOT:
        inbox_file = _REPO_ROOT / ".ai_mail.local" / "inbox.json"
    else:
        inbox_file = branch_path / ".ai_mail.local" / "inbox.json"

    if not inbox_file.exists():
        # Auto-provision inbox for new branches (self-healing)
        try:
            mailbox_dir = inbox_file.parent
            mailbox_dir.mkdir(parents=True, exist_ok=True)
            (mailbox_dir / "sent").mkdir(exist_ok=True)
            inbox_data_init = {"mailbox": "inbox", "total_messages": 0, "unread_count": 0, "messages": []}
            with open(inbox_file, "w", encoding="utf-8") as f:
                json.dump(inbox_data_init, f, indent=2)
        except Exception as e:
            logger.warning("[delivery] auto-provision inbox failed for %s: %s", to_branch, e)
            return False, f"Failed to auto-provision inbox for {to_branch}: {e}"

    # Lock inbox.json for the entire read-modify-write cycle
    try:
        with _get_inbox_lock()(inbox_file):
            try:
                with open(inbox_file, "r", encoding="utf-8") as f:
                    inbox_data = json.load(f)
            except Exception as e:
                logger.warning("[delivery] failed to read inbox %s: %s", inbox_file, e)
                return False, f"Failed to read inbox: {e}"

            # Auto-migrate old inbox format {"inbox": []} -> v2 schema
            inbox_data = _migrate_inbox_format(inbox_data, inbox_file)

            # Create message object (v2 schema: status instead of read)
            message = {
                "id": str(uuid.uuid4())[:8],
                "timestamp": email_data["timestamp"],
                "from": email_data["from"],
                "from_name": email_data["from_name"],
                "subject": email_data["subject"],
                "message": email_data["message"],
                "status": "new",
                "auto_execute": email_data.get("auto_execute", False),
                "priority": email_data.get("priority", "normal"),
            }

            if email_data.get("reply_to"):
                message["reply_to"] = email_data["reply_to"]

            if email_data.get("dispatched_to"):
                message["dispatched_to"] = email_data["dispatched_to"]

            # Store reply_path for cross-project replies.
            # Pass-through from email_data, or auto-detect from AIPASS_CALLER_CWD.
            reply_path = email_data.get("reply_path") or _resolve_reply_path()
            if reply_path:
                message["reply_path"] = reply_path

            # Prepend message to inbox (newest first)
            inbox_data["messages"].insert(0, message)
            inbox_data["total_messages"] = len(inbox_data["messages"])
            messages = inbox_data["messages"]
            new_count = sum(
                1
                for msg in messages
                if msg.get("status") == "new" or (msg.get("status") is None and not msg.get("read", False))
            )
            opened_count = sum(1 for msg in messages if msg.get("status") == "opened")
            inbox_data["unread_count"] = new_count

            try:
                with open(inbox_file, "w", encoding="utf-8") as f:
                    json.dump(inbox_data, f, indent=2, ensure_ascii=False)
            except Exception as e:
                logger.warning("[delivery] failed to write inbox %s: %s", inbox_file, e)
                return False, f"Failed to write inbox: {e}"

    except OSError as e:
        logger.warning("[delivery] failed to acquire inbox lock for %s: %s", to_branch, e)
        return False, f"Failed to acquire inbox lock: {e}"

    # Auto-register recipient in contacts for future fast lookup
    _auto_register_contact(to_branch, branch_path, inbox_file)

    # Auto-register sender if external project called with AIPASS_CALLER_BRANCH
    caller_branch = os.environ.get("AIPASS_CALLER_BRANCH", "")
    caller_cwd = os.environ.get("AIPASS_CALLER_CWD", "")
    if caller_branch and caller_cwd:
        _auto_register_sender(caller_branch, caller_cwd)

    # Send desktop notification for new email
    _send_desktop_notification(email_data["from"], to_branch, email_data["subject"], email_data.get("message", ""))

    # Invoke post-delivery callback (dashboard updates, central sync, etc.)
    if on_delivered:
        try:
            on_delivered(branch_path, new_count, opened_count, inbox_data["total_messages"])
        except Exception as e:
            logger.warning("[delivery] on_delivered callback failed for %s: %s", to_branch, e)
            return True, ""

    return True, ""


_NOTIFICATION_TIMESTAMPS: Dict[str, List[float]] = {}

# Rate limit: max notifications per recipient within time window
_NOTIFICATION_MAX = 3
_NOTIFICATION_WINDOW = 30.0  # seconds


def _send_desktop_notification(sender: str, recipient: str, subject: str, message: str = "") -> None:
    """
    Send desktop notification for new email using notify-send.

    Rate-limited: max 3 notifications per recipient within 30 seconds.
    Gracefully handles cases where notify-send is not available.

    Args:
        sender: Email sender address (e.g., @devpulse)
        recipient: Email recipient address (e.g., @ai_mail)
        subject: Email subject line
        message: Email body (first ~100 chars shown in notification)
    """
    import time

    now = time.time()
    cutoff = now - _NOTIFICATION_WINDOW

    if recipient in _NOTIFICATION_TIMESTAMPS:
        _NOTIFICATION_TIMESTAMPS[recipient] = [t for t in _NOTIFICATION_TIMESTAMPS[recipient] if t > cutoff]
    else:
        _NOTIFICATION_TIMESTAMPS[recipient] = []

    if len(_NOTIFICATION_TIMESTAMPS[recipient]) >= _NOTIFICATION_MAX:
        return

    # Build informative notification
    sender_name = sender.replace("@", "").upper()
    recipient_name = recipient.replace("@", "").upper()
    title = f"{sender_name} -> {recipient_name}"
    body = subject
    if message:
        preview = message[:100].replace("\n", " ").strip()
        if preview:
            body = f"{subject}\n{preview}"

    try:
        from aipass.ai_mail.apps.handlers.notify import send_notification

        send_notification(title, body, source=sender_name)
        _NOTIFICATION_TIMESTAMPS[recipient].append(now)
    except Exception as e:
        logger.warning("[delivery] _send_desktop_notification() failed for %s: %s", recipient, e)
        return


if __name__ == "__main__":
    from rich.console import Console

    console = Console()
    console.print("\n" + "=" * 70)
    console.print("EMAIL DELIVERY HANDLER")
    console.print("=" * 70)
    console.print("\nPURPOSE:")
    console.print("  Delivers emails to branch inboxes")
    console.print()
    console.print("FUNCTIONS PROVIDED:")
    console.print("  - get_all_branches() -> List[Dict]")
    console.print("  - deliver_email_to_branch(to_branch, email_data) -> Tuple[bool, str]")
    console.print()
    console.print("HANDLER CHARACTERISTICS:")
    console.print("  - Independent - no module dependencies")
    console.print("  - Uses lazy imports for services")
    console.print("  - Pure business logic")
    console.print("  - CANNOT import parent modules")
    console.print()
    console.print("USAGE FROM MODULES:")
    console.print("  from aipass.ai_mail.apps.handlers.email.delivery import deliver_email_to_branch")
    console.print("  from aipass.ai_mail.apps.handlers.registry.read import get_all_branches")
    console.print()
    console.print("=" * 70 + "\n")
