# =================== AIPass ====================
# Name: dashboard_sync.py
# Description: Dashboard Write-Through Helper
# Version: 1.0.0
# Created: 2026-02-25
# Modified: 2026-02-25
# =============================================

"""
Dashboard Write-Through Helper

Reads a branch's inbox.json and pushes the ai_mail section to
DASHBOARD.local.json via devpulse write_section() API.

Called as a side-effect after email operations (deliver, close, view, inbox).
Failures never propagate - email operations must not break due to dashboard.
"""

import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional

from aipass.prax.apps.modules.logger import system_logger as logger

# Lazy-loaded write_section reference
_write_section = None


def _get_write_section():
    """Lazy import write_section from devpulse module API."""
    global _write_section
    if _write_section is None:
        from aipass.devpulse.apps.modules.dashboard import write_section
        _write_section = write_section
    return _write_section


def _human_readable_age(seconds: float) -> str:
    """
    Convert seconds to human-readable age string.

    Args:
        seconds: Number of seconds

    Returns:
        Human-readable string like "2 hours", "3 days", "1 week"
    """
    if seconds < 60:
        return "just now"
    elif seconds < 3600:
        mins = int(seconds / 60)
        return f"{mins} minute{'s' if mins != 1 else ''}"
    elif seconds < 86400:
        hours = int(seconds / 3600)
        return f"{hours} hour{'s' if hours != 1 else ''}"
    elif seconds < 604800:
        days = int(seconds / 86400)
        return f"{days} day{'s' if days != 1 else ''}"
    elif seconds < 2592000:
        weeks = int(seconds / 604800)
        return f"{weeks} week{'s' if weeks != 1 else ''}"
    else:
        months = int(seconds / 2592000)
        return f"{months} month{'s' if months != 1 else ''}"


def _calculate_section_data(inbox_data: Dict) -> Dict:
    """
    Calculate ai_mail dashboard section from inbox data.

    Args:
        inbox_data: Parsed inbox.json dict with "messages" list

    Returns:
        Section data dict with new, opened, total, oldest_unread_age,
        last_dispatch_received
    """
    messages = inbox_data.get("messages", [])
    now = datetime.now()

    new_count = 0
    opened_count = 0
    oldest_unread_ts: Optional[datetime] = None
    last_dispatch_ts: Optional[str] = None

    for msg in messages:
        status = msg.get("status")
        is_new = status == "new" or (status is None and not msg.get("read", False))
        is_opened = status == "opened"

        if is_new:
            new_count += 1
            # Track oldest unread timestamp
            ts_str = msg.get("timestamp", "")
            if ts_str:
                try:
                    msg_ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
                    if oldest_unread_ts is None or msg_ts < oldest_unread_ts:
                        oldest_unread_ts = msg_ts
                except (ValueError, TypeError):
                    pass  # Malformed timestamp - skip for age calculation

        if is_opened:
            opened_count += 1

        # Track most recent dispatch email
        if msg.get("auto_execute", False):
            ts_str = msg.get("timestamp", "")
            if ts_str:
                if last_dispatch_ts is None or ts_str > last_dispatch_ts:
                    last_dispatch_ts = ts_str

    total_count = len(messages)

    # Calculate oldest unread age
    oldest_unread_age: Optional[str] = None
    if oldest_unread_ts is not None:
        age_seconds = (now - oldest_unread_ts).total_seconds()
        oldest_unread_age = _human_readable_age(age_seconds)

    # Convert last_dispatch_received to ISO format if present
    last_dispatch_iso: Optional[str] = None
    if last_dispatch_ts:
        try:
            dt = datetime.strptime(last_dispatch_ts, "%Y-%m-%d %H:%M:%S")
            last_dispatch_iso = dt.isoformat()
        except (ValueError, TypeError):
            last_dispatch_iso = last_dispatch_ts

    return {
        "managed_by": "ai_mail",
        "new": new_count,
        "opened": opened_count,
        "total": total_count,
        "oldest_unread_age": oldest_unread_age,
        "last_dispatch_received": last_dispatch_iso
    }


def push_dashboard_update(branch_path: Path) -> bool:
    """
    Read branch inbox and push ai_mail section to dashboard.

    This is the primary public function. It:
    1. Reads the branch's .ai_mail.local/inbox.json
    2. Calculates section data (new, opened, total, oldest_unread_age, etc.)
    3. Calls write_section() to update DASHBOARD.local.json

    Failures are silently caught - email operations must not break.

    Args:
        branch_path: Path to branch root directory

    Returns:
        True if update succeeded, False on any error (never raises)
    """
    try:
        branch_path = Path(branch_path)

        # Determine inbox path
        if branch_path == Path("/"):
            inbox_file = Path.cwd() / ".ai_mail.local" / "inbox.json"
        else:
            inbox_file = branch_path / ".ai_mail.local" / "inbox.json"

        # Read inbox (BYPASS: direct json.load - this is a data file, not a template)
        if not inbox_file.exists():
            # No inbox = all zeros
            section_data = {
                "managed_by": "ai_mail",
                "new": 0,
                "opened": 0,
                "total": 0,
                "oldest_unread_age": None,
                "last_dispatch_received": None
            }
        else:
            with open(inbox_file, 'r', encoding='utf-8') as f:
                inbox_data = json.load(f)
            section_data = _calculate_section_data(inbox_data)

        write_section = _get_write_section()
        return write_section(branch_path, "ai_mail", section_data)

    except Exception as e:
        logger.warning("[dashboard] push_dashboard_update failed for %s: %s", branch_path, e)
        return False
