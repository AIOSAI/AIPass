# =================== AIPass ====================
# Name: storage.py
# Description: JSON persistence layer for feedback inbox
# Version: 1.1.0
# Created: 2026-04-11
# Modified: 2026-10-22
# =============================================

"""
Feedback Storage — JSON persistence for devpulse feedback inbox.
"""

import json
import os
import secrets
from pathlib import Path

from aipass.prax import logger
from aipass.devpulse.apps.handlers.file_lock import FileLock
from aipass.devpulse.apps.handlers.json import json_handler
from aipass.devpulse.apps.handlers.module_root import module_file

_DEVPULSE_ROOT = module_file(__file__).parents[3]

FEEDBACK_DIR = _DEVPULSE_ROOT / ".feedback.local"


def get_inbox_path() -> Path:
    """Return the path to the feedback inbox.json file."""
    return FEEDBACK_DIR / "inbox.json"


def inbox_lock() -> FileLock:
    """Hold this across a load-then-save: two senders at once otherwise drop one message."""
    return FileLock(get_inbox_path())


def _ensure_dir() -> None:
    """Ensure the .feedback.local/ directory exists."""
    FEEDBACK_DIR.mkdir(parents=True, exist_ok=True)


def load_inbox() -> dict:
    """Load the feedback inbox from disk, creating an empty one if the file does not exist."""
    json_handler.log_operation("load_inbox")
    _ensure_dir()
    inbox_path = get_inbox_path()

    if not inbox_path.exists():
        empty_inbox = {
            "mailbox": "feedback",
            "total_messages": 0,
            "unread_count": 0,
            "messages": [],
        }
        save_inbox(empty_inbox)
        return empty_inbox

    try:
        with open(inbox_path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        # Never answer an empty inbox here: the next save would overwrite the real one.
        logger.error(f"[FEEDBACK] Failed to load inbox: {e}")
        raise RuntimeError(f"feedback inbox unreadable at {inbox_path}: {e}") from e


def save_inbox(data: dict) -> None:
    """Write the feedback inbox to disk via a .tmp sibling and os.replace, so a crash never leaves half a file."""
    _ensure_dir()
    inbox_path = get_inbox_path()
    tmp_path = inbox_path.with_suffix(".json.tmp")

    try:
        tmp_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp_path, inbox_path)
    except OSError as e:
        logger.error(f"[FEEDBACK] Failed to save inbox: {e}")
        raise
    finally:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


def generate_id() -> str:
    """Generate an 8-character hex message ID."""
    return secrets.token_hex(4)
