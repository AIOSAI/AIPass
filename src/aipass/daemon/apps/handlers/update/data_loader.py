# =================== AIPass ====================
# Name: data_loader.py
# Description: DAEMON Data Loading Handler
# Version: 1.1.1
# Created: 2026-01-29
# Modified: 2026-10-24
# =============================================

"""
Handler for loading DAEMON data from inbox and local files.
"""

import json
from typing import Dict, Any, List

from aipass.prax import logger
from aipass.daemon.apps.handlers.json import json_handler
from aipass.daemon.apps.handlers.module_root import module_file

_DAEMON_ROOT = module_file(__file__).parents[3]  # src/aipass/daemon/
INBOX_PATH = _DAEMON_ROOT / ".ai_mail.local" / "inbox.json"


def load_inbox() -> Dict[str, Any]:
    """Load inbox.json; a missing one is empty. An unreadable one raises: a digest of zeros would be false."""
    json_handler.log_operation("data_loaded")
    if not INBOX_PATH.exists():
        return {"messages": [], "total_messages": 0, "unread_count": 0}

    try:
        with open(INBOX_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.error("[data_loader] Failed to load inbox.json: %s", e)
        raise


def categorize_messages(messages: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Categorize inbox messages into new, opened, actionable and informational."""
    categories: Dict[str, List[Dict[str, Any]]] = {"new": [], "opened": [], "actionable": [], "informational": []}

    for msg in messages:
        status = msg.get("status", "new")
        subject = msg.get("subject", "").upper()

        if status == "new":
            categories["new"].append(msg)
        elif status == "opened":
            categories["opened"].append(msg)

        if any(kw in subject for kw in ["TASK:", "BUILD:", "FIX:", "PROPOSAL:", "REQUEST:"]):
            categories["actionable"].append(msg)
        elif any(kw in subject for kw in ["INFO", "RE:", "FYI", "NOTIFICATION"]):
            categories["informational"].append(msg)

    return categories


def get_escalations(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Find messages that need escalation."""
    return [
        m for m in messages if "BLOCKED" in m.get("subject", "").upper() or "URGENT" in m.get("subject", "").upper()
    ]
