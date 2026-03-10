# =================== AIPass ====================
# Name: inbox_cleanup.py
# Description: Inbox Cleanup Handler
# Version: 3.3.0
# Created: 2025-11-27
# Modified: 2025-11-27
# =============================================

"""
Inbox Cleanup Handler

Handles marking emails as read and moving to deleted/ folder.
Updates dashboard after cleanup.

v3.0.0: Now uses deleted/ directory with individual JSON files (like sent/).
"""

import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Tuple, Optional, Any

from aipass.prax.apps.modules.logger import system_logger as logger


# Lazy import for inbox file lock
_inbox_lock = None


def _get_inbox_lock():
    """Lazy import inbox_lock context manager."""
    global _inbox_lock
    if _inbox_lock is None:
        from aipass.ai_mail.apps.handlers.email.inbox_lock import inbox_lock
        _inbox_lock = inbox_lock
    return _inbox_lock


def _get_console() -> Any:
    """Lazy import console - only for __main__ block."""
    from rich.console import Console
    return Console()


def _get_update_section() -> Any:
    """Lazy import update_section."""
    try:
        from aipass.devpulse.apps.modules.dashboard import update_section
        return update_section
    except ImportError:
        return None


def _get_push_dashboard_update() -> Any:
    """Lazy import push_dashboard_update from dashboard_sync."""
    from aipass.ai_mail.apps.handlers.email.dashboard_sync import push_dashboard_update
    return push_dashboard_update


def _get_update_central() -> Any:
    """Lazy import update_central."""
    from aipass.ai_mail.apps.handlers.central_writer import update_central
    return update_central


def _save_to_deleted_folder(mailbox_path: Path, message: Dict) -> Path:
    """
    Save a message to the deleted/ folder as individual JSON file.

    Args:
        mailbox_path: Path to .ai_mail.local directory
        message: Email message dict to archive

    Returns:
        Path to created file
    """
    deleted_folder = mailbox_path / "deleted"
    deleted_folder.mkdir(parents=True, exist_ok=True)

    # Generate filename (same pattern as sent/)
    timestamp = datetime.now()
    subject = message.get("subject", "No Subject")
    safe_subject = "".join(c if c.isalnum() or c in (' ', '-', '_') else '_' for c in subject)
    safe_subject = safe_subject[:50].strip()
    filename = f"{timestamp.strftime('%Y%m%d_%H%M%S')}_{safe_subject}.json"

    # Add archived_at timestamp
    message["archived_at"] = timestamp.isoformat()

    email_file = deleted_folder / filename
    with open(email_file, 'w', encoding='utf-8') as f:
        json.dump(message, f, indent=2, ensure_ascii=False)

    return email_file


def _migrate_deleted_json_if_exists(mailbox_path: Path) -> int:
    """
    Migrate existing deleted.json to deleted/ directory on first access.

    Args:
        mailbox_path: Path to .ai_mail.local directory

    Returns:
        Number of messages migrated
    """
    deleted_json = mailbox_path / "deleted.json"

    if not deleted_json.exists():
        return 0

    try:
        with open(deleted_json, 'r', encoding='utf-8') as f:
            data = json.load(f)

        messages = data.get("messages", [])
        if not messages:
            # Empty file, just archive it
            _archive_deleted_json(mailbox_path, deleted_json)
            return 0

        # Migrate each message to deleted/ folder
        for msg in messages:
            _save_to_deleted_folder(mailbox_path, msg)

        # Archive the old deleted.json
        _archive_deleted_json(mailbox_path, deleted_json)

        return len(messages)

    except Exception as e:
        logger.warning("[cleanup] _migrate_deleted_json() failed: %s", e)
        return 0


def _archive_deleted_json(mailbox_path: Path, deleted_json: Path) -> None:
    """Archive the old deleted.json file."""
    archive_dir = mailbox_path / ".archive"
    archive_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_path = archive_dir / f"deleted.json.migrated_{timestamp}"
    deleted_json.rename(archive_path)


def mark_read_and_archive(branch_path: Path, message_id: str) -> Tuple[bool, str]:
    """
    Mark an email as read and move it to deleted/ folder.

    Args:
        branch_path: Path to branch directory
        message_id: ID of message to archive (short 8-char ID)

    Returns:
        Tuple of (success: bool, message: str)
    """
    mailbox_path = branch_path / ".ai_mail.local"
    inbox_file = mailbox_path / "inbox.json"

    if not inbox_file.exists():
        return False, f"Inbox not found: {inbox_file}"

    # Run migration if deleted.json exists
    _migrate_deleted_json_if_exists(mailbox_path)

    try:
        with _get_inbox_lock()(inbox_file):
            # Load inbox
            with open(inbox_file, 'r', encoding='utf-8') as f:
                inbox_data = json.load(f)

            # Find message by ID
            messages = inbox_data.get("messages", [])
            message_to_archive = None
            message_index = None

            for i, msg in enumerate(messages):
                if msg.get("id") == message_id:
                    message_to_archive = msg
                    message_index = i
                    break

            if message_to_archive is None:
                return False, f"Message not found: {message_id}"

            # Mark as read
            message_to_archive["read"] = True

            # Remove from inbox
            messages.pop(message_index)

            # Update inbox counts
            inbox_data["messages"] = messages
            inbox_data["total_messages"] = len(messages)
            # v2 status counts
            new_count = sum(
                1 for m in messages
                if m.get("status") == "new" or (m.get("status") is None and not m.get("read", False))
            )
            opened_count = sum(1 for m in messages if m.get("status") == "opened")
            inbox_data["unread_count"] = new_count

            # Save inbox
            with open(inbox_file, 'w', encoding='utf-8') as f:
                json.dump(inbox_data, f, indent=2, ensure_ascii=False)

            # Save to deleted/ folder (new pattern)
            _save_to_deleted_folder(mailbox_path, message_to_archive)

        # Update dashboard (outside lock - not inbox.json)
        _update_dashboard(branch_path, new_count, opened_count, inbox_data["total_messages"])

        # Trigger auto-purge of deleted folder
        _trigger_deleted_purge(branch_path)

        return True, f"Message {message_id} archived"

    except Exception as e:
        return False, f"Failed to archive: {e}"


def mark_all_read_and_archive(branch_path: Path) -> Tuple[bool, str, int]:
    """
    Mark all emails as read and move them to deleted/ folder.

    Args:
        branch_path: Path to branch directory

    Returns:
        Tuple of (success: bool, message: str, count: int)
    """
    mailbox_path = branch_path / ".ai_mail.local"
    inbox_file = mailbox_path / "inbox.json"

    if not inbox_file.exists():
        return False, f"Inbox not found: {inbox_file}", 0

    # Run migration if deleted.json exists
    _migrate_deleted_json_if_exists(mailbox_path)

    try:
        # Load inbox
        with open(inbox_file, 'r', encoding='utf-8') as f:
            inbox_data = json.load(f)

        messages = inbox_data.get("messages", [])
        count = len(messages)

        if count == 0:
            return True, "Inbox already empty", 0

        # Mark all as read and save to deleted/ folder
        for msg in messages:
            msg["read"] = True
            _save_to_deleted_folder(mailbox_path, msg)

        # Clear inbox
        inbox_data["messages"] = []
        inbox_data["total_messages"] = 0
        inbox_data["unread_count"] = 0

        # Save inbox
        with open(inbox_file, 'w', encoding='utf-8') as f:
            json.dump(inbox_data, f, indent=2, ensure_ascii=False)

        # Update dashboard (all zeros - inbox cleared)
        _update_dashboard(branch_path, 0, 0, 0)

        # Trigger auto-purge of deleted folder
        _trigger_deleted_purge(branch_path)

        return True, f"Archived {count} messages", count

    except Exception as e:
        return False, f"Failed to archive: {e}", 0


def _update_dashboard(branch_path: Path, new: int, opened: int, total: int) -> None:
    """Update dashboard ai_mail section with enriched data via write-through API."""
    try:
        _get_push_dashboard_update()(branch_path)
    except Exception as e:
        logger.warning("[cleanup] dashboard update failed for %s: %s", branch_path, e)

    # Update central after any inbox changes
    try:
        _get_update_central()()
    except Exception as e:
        logger.warning("[cleanup] central update failed: %s", e)


def _trigger_deleted_purge(branch_path: Path) -> None:
    """
    Trigger auto-purge of deleted folder if threshold exceeded.

    Non-blocking - failures silently ignored.
    """
    try:
        from aipass.ai_mail.apps.handlers.email.purge import purge_deleted_folder
        mailbox_path = branch_path / ".ai_mail.local"
        purge_deleted_folder(mailbox_path)
    except Exception as e:
        logger.warning("[cleanup] _trigger_deleted_purge() failed: %s", e)


# =============================================================================
# V2 SCHEMA FUNCTIONS (status: new/opened/closed)
# =============================================================================

def mark_as_opened(branch_path: Path, message_id: str) -> Tuple[bool, str, Optional[Dict]]:
    """
    Mark an email as opened (viewed). Does NOT archive.

    v2 schema: changes status from "new" to "opened"

    Args:
        branch_path: Path to branch directory
        message_id: ID of message to mark as opened

    Returns:
        Tuple of (success: bool, message: str, email_data: dict or None)
    """
    inbox_file = branch_path / ".ai_mail.local" / "inbox.json"

    if not inbox_file.exists():
        return False, f"Inbox not found: {inbox_file}", None

    try:
        with open(inbox_file, 'r', encoding='utf-8') as f:
            inbox_data = json.load(f)

        messages = inbox_data.get("messages", [])
        target_msg = None

        for msg in messages:
            if msg.get("id") == message_id:
                target_msg = msg
                break

        if target_msg is None:
            return False, f"Message not found: {message_id}", None

        # Update status to opened (v2 schema)
        target_msg["status"] = "opened"
        # Keep backward compat
        target_msg["read"] = True

        # Recalculate status counts (v2 schema)
        new_count = sum(
            1 for m in messages
            if m.get("status") == "new" or (m.get("status") is None and not m.get("read", False))
        )
        opened_count = sum(1 for m in messages if m.get("status") == "opened")
        inbox_data["unread_count"] = new_count

        with open(inbox_file, 'w', encoding='utf-8') as f:
            json.dump(inbox_data, f, indent=2, ensure_ascii=False)

        # Update dashboard
        _update_dashboard(branch_path, new_count, opened_count, inbox_data["total_messages"])

        return True, f"Message {message_id} marked as opened", target_msg

    except Exception as e:
        return False, f"Failed to mark as opened: {e}", None


def mark_as_closed_and_archive(branch_path: Path, message_id: str, skip_post_ops: bool = False) -> Tuple[bool, str]:
    """
    Mark an email as closed and archive to deleted/ folder.

    v2 schema: changes status to "closed", moves to deleted/

    Args:
        branch_path: Path to branch directory
        message_id: ID of message to close and archive
        skip_post_ops: If True, skip dashboard update and purge (caller handles them)

    Returns:
        Tuple of (success: bool, message: str)
    """
    mailbox_path = branch_path / ".ai_mail.local"
    inbox_file = mailbox_path / "inbox.json"

    if not inbox_file.exists():
        return False, f"Inbox not found: {inbox_file}"

    # Run migration if deleted.json exists
    _migrate_deleted_json_if_exists(mailbox_path)

    try:
        with open(inbox_file, 'r', encoding='utf-8') as f:
            inbox_data = json.load(f)

        messages = inbox_data.get("messages", [])
        message_to_archive = None
        message_index = None

        for i, msg in enumerate(messages):
            if msg.get("id") == message_id:
                message_to_archive = msg
                message_index = i
                break

        if message_to_archive is None:
            return False, f"Message not found: {message_id}"

        # Mark as closed (v2 schema)
        message_to_archive["status"] = "closed"
        message_to_archive["read"] = True  # backward compat

        # Remove from inbox
        messages.pop(message_index)

        # Update inbox counts
        inbox_data["messages"] = messages
        inbox_data["total_messages"] = len(messages)
        # v2 status counts
        new_count = sum(
            1 for m in messages
            if m.get("status") == "new" or (m.get("status") is None and not m.get("read", False))
        )
        opened_count = sum(1 for m in messages if m.get("status") == "opened")
        inbox_data["unread_count"] = new_count

        with open(inbox_file, 'w', encoding='utf-8') as f:
            json.dump(inbox_data, f, indent=2, ensure_ascii=False)

        # Save to deleted/ folder (new pattern)
        _save_to_deleted_folder(mailbox_path, message_to_archive)

        if not skip_post_ops:
            # Update dashboard
            _update_dashboard(branch_path, new_count, opened_count, inbox_data["total_messages"])

            # Trigger auto-purge of deleted folder
            _trigger_deleted_purge(branch_path)

        return True, f"Message {message_id} closed and archived"

    except Exception as e:
        return False, f"Failed to close: {e}"


if __name__ == "__main__":
    c = _get_console()
    c.print("\n" + "="*70)
    c.print("INBOX CLEANUP HANDLER")
    c.print("="*70)
    c.print("\nPURPOSE:")
    c.print("  Marks emails as read and moves them to deleted/ folder")
    c.print()
    c.print("FUNCTIONS PROVIDED:")
    c.print("  - mark_read_and_archive(branch_path, message_id) -> (bool, str)")
    c.print("  - mark_all_read_and_archive(branch_path) -> (bool, str, int)")
    c.print("  - mark_as_opened(branch_path, message_id) -> (bool, str, dict)")
    c.print("  - mark_as_closed_and_archive(branch_path, message_id) -> (bool, str)")
    c.print()
    c.print("WORKFLOW (v3.0):")
    c.print("  1. Find message in inbox.json")
    c.print("  2. Mark as read=True / status=closed")
    c.print("  3. Save to deleted/ folder (individual JSON files)")
    c.print("  4. Update dashboard ai_mail section")
    c.print("  5. Auto-purge deleted/ folder if > 10 items")
    c.print()
    c.print("MIGRATION:")
    c.print("  - Automatically migrates deleted.json to deleted/ on first access")
    c.print("  - Old deleted.json archived to .archive/")
    c.print()
    c.print("="*70 + "\n")
