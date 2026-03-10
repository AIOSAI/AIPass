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
import uuid
import subprocess
from pathlib import Path
from typing import Dict, Tuple, List, Optional, Callable

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.ai_mail.apps.handlers.json_utils.json_handler import load_json, save_json


def _find_repo_root() -> Path:
    """Walk up from this file to find AIPASS_REGISTRY.json (repo root)."""
    current = Path(__file__).resolve().parent
    for parent in [current] + list(current.parents):
        if (parent / "AIPASS_REGISTRY.json").exists():
            return parent
    return Path.cwd()


_REPO_ROOT = _find_repo_root()

# Lazy imports to avoid circular dependencies
_CONSOLE = None
_INBOX_LOCK = None


def _get_inbox_lock():
    """Lazy import inbox_lock context manager."""
    global _INBOX_LOCK
    if _INBOX_LOCK is None:
        from aipass.ai_mail.apps.handlers.email.inbox_lock import inbox_lock
        _INBOX_LOCK = inbox_lock
    return _INBOX_LOCK


def _get_console():
    """Lazy import console - only for __main__ block."""
    global _CONSOLE
    if _CONSOLE is None:
        from rich.console import Console
        _CONSOLE = Console()
    return _CONSOLE


def get_all_branches() -> List[Dict]:
    """
    Get list of all branches for email routing.
    Reads from AIPass branch registry (AIPASS_REGISTRY.json at repo root).

    Returns:
        List of dicts with branch info:
        [{"name": "AIPASS.admin", "path": "/", "email": "@admin"}, ...]
    """
    registry_file = _REPO_ROOT / "AIPASS_REGISTRY.json"
    branches = []

    if not registry_file.exists():
        return []

    try:
        with open(registry_file, 'r', encoding='utf-8') as f:
            registry_data = json.load(f)

        # Parse branch entries from JSON structure
        # Handle both formats: list of dicts or dict keyed by name
        raw_branches = registry_data.get("branches", [])
        if isinstance(raw_branches, dict):
            raw_branches = list(raw_branches.values())
        for branch in raw_branches:
            branch_name = branch.get("name", "")
            path = branch.get("path", "")

            if not branch_name or not path:
                continue

            # Use explicit email from registry if present (preferred)
            # Fall back to derivation only if email field is missing
            explicit_email = branch.get("email", "")
            if explicit_email:
                email = explicit_email
            else:
                # Legacy fallback: derive email from branch name
                if '.' in branch_name:
                    email_part = branch_name.split('.')[-1].lower()
                elif ' ' in branch_name:
                    email_part = branch_name.split()[0].lower()
                elif '-' in branch_name and branch_name.split('-')[0] == 'AIPASS':
                    email_part = branch_name.split('-', 1)[1].lower()
                else:
                    email_part = branch_name.split('-')[0].lower()
                email = f"@{email_part}"

            branches.append({
                "name": branch_name,
                "path": path,
                "email": email
            })

        # COLLISION DETECTION: Check for duplicate email addresses
        email_map = {}
        collisions = []
        for branch in branches:
            if branch["email"] in email_map:
                collision_msg = f"Email collision: {branch['email']} used by both '{email_map[branch['email']]}' and '{branch['name']}'"
                collisions.append(collision_msg)
            else:
                email_map[branch["email"]] = branch["name"]

        return branches

    except Exception as e:
        logger.warning("[delivery] get_all_branches() failed to read registry: %s", e)
        return []


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
            1 for msg in inbox_data["messages"]
            if msg.get("status") == "new" or (msg.get("status") is None and not msg.get("read", False))
        )
        migrated = True

    # Persist migration to disk
    if migrated:
        try:
            with open(inbox_file, 'w', encoding='utf-8') as f:
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
        with open(registry_path, 'r', encoding='utf-8') as f:
            registry = json.load(f)
        for branch in registry.get("branches", []):
            if branch.get("email", "") == email:
                return True
    except (json.JSONDecodeError, IOError) as e:
        logger.warning("[delivery] _is_private_branch_email(%s) failed: %s", email, e)
    return False


def deliver_email_to_branch(
    to_branch: str,
    email_data: Dict,
    on_delivered: Optional[Callable] = None
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
    # Handle path input from DRONE's @ resolution
    if to_branch.startswith('/'):
        branches_list = get_all_branches()
        path_to_email = {b["path"]: b["email"] for b in branches_list}
        if to_branch in path_to_email:
            to_branch = path_to_email[to_branch]
        else:
            # Stage 2: Longest-path-first prefix matching against registry
            sorted_branches = sorted(branches_list, key=lambda b: len(b['path']), reverse=True)
            matched = False
            for b in sorted_branches:
                if to_branch.startswith(b['path'] + '/') or to_branch == b['path']:
                    to_branch = b['email']
                    matched = True
                    break
            if not matched:
                return False, f"Could not resolve path to email: {to_branch}"

    # Map email address to branch path
    all_branches = get_all_branches()
    branches = {b["email"]: b["path"] for b in all_branches}

    if to_branch not in branches:
        error_msg = f"Unknown branch email: {to_branch} (available: {len(branches)} branches)"
        return False, error_msg

    # Private branch inbound blocking: reject delivery to private branches
    # Self-send is allowed (private branch can send to itself)
    sender_email = email_data.get('from', '')
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
            inbox_data_init = {
                "mailbox": "inbox",
                "total_messages": 0,
                "unread_count": 0,
                "messages": []
            }
            with open(inbox_file, 'w', encoding='utf-8') as f:
                json.dump(inbox_data_init, f, indent=2)
        except Exception as e:
            return False, f"Failed to auto-provision inbox for {to_branch}: {e}"

    # Lock inbox.json for the entire read-modify-write cycle
    try:
        with _get_inbox_lock()(inbox_file):
            try:
                with open(inbox_file, 'r', encoding='utf-8') as f:
                    inbox_data = json.load(f)
            except Exception as e:
                return False, f"Failed to read inbox: {e}"

            # Auto-migrate old inbox format {"inbox": []} -> v2 schema
            inbox_data = _migrate_inbox_format(inbox_data, inbox_file)

            # Create message object (v2 schema: status instead of read)
            message = {
                "id": str(uuid.uuid4())[:8],
                "timestamp": email_data['timestamp'],
                "from": email_data['from'],
                "from_name": email_data['from_name'],
                "subject": email_data['subject'],
                "message": email_data['message'],
                "status": "new",
                "auto_execute": email_data.get('auto_execute', False),
                "priority": email_data.get('priority', 'normal')
            }

            if email_data.get('reply_to'):
                message["reply_to"] = email_data['reply_to']

            if email_data.get('dispatched_to'):
                message["dispatched_to"] = email_data['dispatched_to']

            # Prepend message to inbox (newest first)
            inbox_data["messages"].insert(0, message)
            inbox_data["total_messages"] = len(inbox_data["messages"])
            messages = inbox_data["messages"]
            new_count = sum(
                1 for msg in messages
                if msg.get("status") == "new" or (msg.get("status") is None and not msg.get("read", False))
            )
            opened_count = sum(1 for msg in messages if msg.get("status") == "opened")
            inbox_data["unread_count"] = new_count

            try:
                with open(inbox_file, 'w', encoding='utf-8') as f:
                    json.dump(inbox_data, f, indent=2, ensure_ascii=False)
            except Exception as e:
                return False, f"Failed to write inbox: {e}"

    except OSError as e:
        return False, f"Failed to acquire inbox lock: {e}"

    # Send desktop notification for new email
    _send_desktop_notification(email_data['from'], to_branch, email_data['subject'], email_data.get('message', ''))

    # Invoke post-delivery callback (dashboard updates, central sync, etc.)
    if on_delivered:
        try:
            on_delivered(branch_path, new_count, opened_count, inbox_data["total_messages"])
        except Exception as e:
            logger.warning("[delivery] on_delivered callback failed for %s: %s", to_branch, e)
            return True, ""

    return True, ""


def _get_summary_file_path(branch_path: Path) -> Path:
    """
    Get the summary file path for a branch.

    Pattern: [BRANCH_NAME].ai_mail.json
    Example: src/aipass/drone/DRONE.ai_mail.json

    Args:
        branch_path: Path to branch directory

    Returns:
        Path to summary file
    """
    branch_name = branch_path.name.upper()

    if branch_path == Path("/") or branch_path == _REPO_ROOT:
        branch_name = "AIPASS"

    summary_file = branch_path / f"{branch_name}.ai_mail.json"
    return summary_file


def _update_summary_file(summary_file: Path, message: Dict, total: int, unread: int) -> None:
    """
    Update branch summary file with new email data.

    Updates:
    - summary.inbox.total
    - summary.inbox.unread
    - summary.inbox.recent_preview (adds message preview)

    Args:
        summary_file: Path to summary JSON file
        message: Message dict to add to preview
        total: Total inbox message count
        unread: Unread message count
    """
    try:
        with open(summary_file, 'r', encoding='utf-8') as f:
            summary_data = json.load(f)

        if "summary" not in summary_data:
            summary_data["summary"] = {}
        if "inbox" not in summary_data["summary"]:
            summary_data["summary"]["inbox"] = {}

        summary_data["summary"]["inbox"]["total"] = total
        summary_data["summary"]["inbox"]["unread"] = unread

        if "recent_preview" not in summary_data["summary"]["inbox"]:
            summary_data["summary"]["inbox"]["recent_preview"] = []

        message_words = message["message"].split()[:15]
        preview = {
            "from": message["from"],
            "subject": message["subject"],
            "summary": " ".join(message_words) + ("..." if len(message["message"].split()) > 15 else ""),
            "timestamp": message["timestamp"],
            "status": "new",
            "message_id": message["id"]
        }

        summary_data["summary"]["inbox"]["recent_preview"].insert(0, preview)
        summary_data["summary"]["inbox"]["recent_preview"] = summary_data["summary"]["inbox"]["recent_preview"][:5]

        with open(summary_file, 'w', encoding='utf-8') as f:
            json.dump(summary_data, f, indent=2, ensure_ascii=False)

    except Exception as e:
        logger.warning("[delivery] _update_summary_file(%s) failed: %s", summary_file, e)
        return


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
        sender: Email sender address (e.g., @dev_central)
        recipient: Email recipient address (e.g., @ai_mail)
        subject: Email subject line
        message: Email body (first ~100 chars shown in notification)
    """
    import time

    now = time.time()
    cutoff = now - _NOTIFICATION_WINDOW

    if recipient in _NOTIFICATION_TIMESTAMPS:
        _NOTIFICATION_TIMESTAMPS[recipient] = [
            t for t in _NOTIFICATION_TIMESTAMPS[recipient] if t > cutoff
        ]
    else:
        _NOTIFICATION_TIMESTAMPS[recipient] = []

    if len(_NOTIFICATION_TIMESTAMPS[recipient]) >= _NOTIFICATION_MAX:
        return

    # Build informative notification
    sender_name = sender.replace('@', '').upper()
    recipient_name = recipient.replace('@', '').upper()
    title = f"{sender_name} -> {recipient_name}"
    body = subject
    if message:
        preview = message[:100].replace('\n', ' ').strip()
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
    console = _get_console()
    console.print("\n" + "="*70)
    console.print("EMAIL DELIVERY HANDLER")
    console.print("="*70)
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
    console.print("  from aipass.ai_mail.apps.handlers.email.delivery import get_all_branches")
    console.print()
    console.print("="*70 + "\n")
