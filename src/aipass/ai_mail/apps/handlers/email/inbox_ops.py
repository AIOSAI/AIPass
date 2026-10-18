# =================== AIPass ====================
# Name: inbox_ops.py
# Description: Inbox Operations Handler
# Version: 1.1.1
# Created: 2025-11-15
# Modified: 2026-10-17
# =============================================

"""
Inbox Operations Handler
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

    Matches the inbox id first, then sent_id, so a sender cannot shadow a recipient's id.
    The one resolver for view/reply/close: never bolt a separate fallback onto a command.
    """
    for msg in messages:
        if isinstance(msg, dict) and msg.get("id") == message_id:
            return msg

    for msg in messages:
        if isinstance(msg, dict) and msg.get("sent_id") == message_id:
            return msg

    return None


def load_inbox(inbox_file: Path) -> Dict:
    """Load inbox data from inbox.json file."""
    json_handler.log_operation("load_inbox", {"inbox_file": str(inbox_file)})
    if not inbox_file.exists():
        return {"messages": []}

    try:
        with open(inbox_file, "r", encoding="utf-8") as f:
            inbox_data = json.load(f)

        if not isinstance(inbox_data, dict):
            return {"mailbox": "inbox", "total_messages": 0, "unread_count": 0, "messages": []}

        # Old format {"inbox": []} migrates to the v2 schema.
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
            from aipass.ai_mail.apps.handlers.email.inbox_cleanup import sweep_closed

            swept = sweep_closed(inbox_data, inbox_file.parent)
            if swept > 0:
                migrated = True
        except Exception as e:
            logger.warning("[inbox] sweep_closed in load_inbox failed: %s", e)

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
