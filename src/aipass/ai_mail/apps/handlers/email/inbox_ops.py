# =================== AIPass ====================
# Name: inbox_ops.py
# Description: Inbox Operations Handler
# Version: 1.1.0
# Created: 2025-11-15
# Modified: 2025-11-15
# =============================================

"""
Inbox Operations Handler

Handles inbox file I/O operations for AI_Mail system.
Independent handler - no module dependencies.
"""

import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.ai_mail.apps.handlers.json import json_handler

if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8", errors="replace")

# Lazy import for inbox file lock
_inbox_lock = None


def _get_inbox_lock():
    """Lazy import inbox_lock context manager."""
    global _inbox_lock
    if _inbox_lock is None:
        from aipass.ai_mail.apps.handlers.email.inbox_lock import inbox_lock

        _inbox_lock = inbox_lock
    return _inbox_lock


def find_message(messages: List[Dict], message_id: str) -> Optional[Dict]:
    """Resolve a user-supplied id against a message list.

    A delivered message has TWO names: the id the recipient's mailbox minted
    (authoritative — it is what view/reply/close print back) and ``sent_id``,
    the id in the sender's ``sent/`` record. An operator holding either one
    means the same message, so both must resolve.

    The inbox id wins outright: every inbox id is checked before any sent_id,
    so resolution never depends on message order. A sender cannot shadow a
    recipient's message by choosing a colliding id.

    This is the single resolution site for all three commands. Bolting a
    fallback onto each of them separately is how S143's outage was built —
    two resolvers for one question, disagreeing under load.

    Args:
        messages: Inbox message dicts
        message_id: Either the recipient's inbox id or the sender's sent_id

    Returns:
        The matching message dict, or None
    """
    for msg in messages:
        if isinstance(msg, dict) and msg.get("id") == message_id:
            return msg

    for msg in messages:
        if isinstance(msg, dict) and msg.get("sent_id") == message_id:
            return msg

    return None


def load_inbox(inbox_file: Path) -> Dict:
    """
    Load inbox data from inbox.json file.

    Args:
        inbox_file: Path to inbox.json file

    Returns:
        Inbox data dict with 'messages' key (empty list if file doesn't exist or error)

    Raises:
        Exception: If file cannot be read or parsed
    """
    json_handler.log_operation("load_inbox", {"inbox_file": str(inbox_file)})
    if not inbox_file.exists():
        return {"messages": []}

    try:
        with open(inbox_file, "r", encoding="utf-8") as f:
            inbox_data = json.load(f)

        # Validate structure
        if not isinstance(inbox_data, dict):
            return {"mailbox": "inbox", "total_messages": 0, "unread_count": 0, "messages": []}

        # Auto-migrate old format {"inbox": []} → v2 schema
        migrated = False

        if "inbox" in inbox_data and "messages" not in inbox_data:
            inbox_data["messages"] = inbox_data.pop("inbox", [])
            migrated = True

        if "messages" not in inbox_data:
            inbox_data["messages"] = []
            migrated = True

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

        try:
            from aipass.ai_mail.apps.handlers.email.inbox_cleanup import _sweep_closed

            swept = _sweep_closed(inbox_data, inbox_file.parent)
            if swept > 0:
                migrated = True
        except Exception as e:
            logger.warning("[inbox] sweep_closed in load_inbox failed: %s", e)

        # Persist migration under lock to prevent concurrent write races
        if migrated:
            try:
                with _get_inbox_lock()(inbox_file):
                    with open(inbox_file, "w", encoding="utf-8") as f:
                        json.dump(inbox_data, f, indent=2, ensure_ascii=False)
            except Exception as e:
                logger.warning("[inbox] Migration persist failed for %s: %s", inbox_file, e)

        return inbox_data

    except json.JSONDecodeError as e:
        raise Exception(f"Invalid inbox JSON format: {e}")
    except Exception as e:
        raise Exception(f"Failed to load inbox: {e}")


if __name__ == "__main__":
    from aipass.cli.apps.modules import console

    console.print("\n" + "=" * 70)
    console.print("INBOX OPERATIONS HANDLER")
    console.print("=" * 70)
    console.print("\nPURPOSE:")
    console.print("  Handles inbox file I/O operations")
    console.print()
    console.print("FUNCTIONS PROVIDED:")
    console.print("  - load_inbox(inbox_file) -> Dict")
    console.print()
    console.print("HANDLER CHARACTERISTICS:")
    console.print("  [green]+[/green] Independent - no module dependencies")
    console.print("  [green]+[/green] Can import Prax (service provider)")
    console.print("  [green]+[/green] Pure business logic")
    console.print("  [dim]-[/dim] CANNOT import parent modules")
    console.print()
    console.print("USAGE FROM MODULES:")
    console.print("  from aipass.ai_mail.apps.handlers.email.inbox_ops import load_inbox")
    console.print("  inbox_data = load_inbox(Path('/path/to/inbox.json'))")
    console.print()
    console.print("=" * 70 + "\n")
