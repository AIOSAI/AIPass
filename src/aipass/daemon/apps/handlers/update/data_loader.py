# =================== AIPass ====================
# Name: data_loader.py
# Description: DAEMON Data Loading Handler
# Version: 1.0.0
# Created: 2026-01-29
# Modified: 2026-01-29
# =============================================

"""
Handler for loading DAEMON data from inbox and local files.
"""

import json
from pathlib import Path
from typing import Dict, Any, List

from aipass.daemon.apps.handlers.json import json_handler

# =============================================
# CONSTANTS
# =============================================

_DAEMON_ROOT = Path(__file__).resolve().parents[3]  # src/aipass/daemon/
INBOX_PATH = _DAEMON_ROOT / "ai_mail.local" / "inbox.json"
LOCAL_PATH = _DAEMON_ROOT / "DAEMON.local.json"

# =============================================
# DATA LOADING
# =============================================

def load_inbox() -> Dict[str, Any]:
    """Load inbox.json and return parsed data."""
    json_handler.log_operation("data_loaded")
    if not INBOX_PATH.exists():
        return {"messages": [], "total_messages": 0, "unread_count": 0}

    try:
        with open(INBOX_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {"messages": [], "total_messages": 0, "unread_count": 0}


def load_local() -> Dict[str, Any]:
    """Load DAEMON.local.json and return parsed data."""
    if not LOCAL_PATH.exists():
        return {"sessions": [], "active_tasks": {}}

    try:
        with open(LOCAL_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {"sessions": [], "active_tasks": {}}


# =============================================
# DIGEST ANALYSIS
# =============================================

def categorize_messages(messages: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """
    Categorize inbox messages by status.

    Returns:
        Dict with keys: new, opened, actionable, informational
    """
    categories: Dict[str, List[Dict[str, Any]]] = {
        "new": [],
        "opened": [],
        "actionable": [],
        "informational": []
    }

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


def get_session_summary(local_data: Dict[str, Any]) -> Dict[str, Any]:
    """Extract session summary from local.json."""
    sessions = local_data.get("sessions", [])
    active_tasks = local_data.get("active_tasks", {})

    return {
        "total_sessions": len(sessions),
        "today_focus": active_tasks.get("today_focus", "None"),
        "recently_completed": active_tasks.get("recently_completed", []),
        "latest_session": sessions[0] if sessions else None
    }


def get_escalations(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Find messages that need escalation."""
    return [m for m in messages if "BLOCKED" in m.get("subject", "").upper()
            or "URGENT" in m.get("subject", "").upper()]
