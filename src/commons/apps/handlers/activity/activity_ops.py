# =================== AIPass ====================
# Name: activity_ops.py
# Description: Activity Feed Operations Handler
# Version: 1.0.0
# Created: 2026-03-07
# Modified: 2026-03-07
# =============================================

"""
Activity Feed Operations Handler

Implementation logic for the activity command: showing recent comments
across ALL threads in The Commons, with optional room filtering.
Returns dicts for module display layer.
"""

from datetime import datetime, timezone
from typing import List, Optional

from aipass.prax.apps.modules.logger import system_logger as logger

from commons.apps.handlers.database.db import get_db, close_db
from commons.apps.handlers.json import json_handler


# =============================================================================
# PRIVATE HELPERS
# =============================================================================

def _relative_time(timestamp_str: str) -> str:
    """
    Convert an ISO timestamp to a human-readable relative time string.

    Args:
        timestamp_str: ISO format timestamp

    Returns:
        Human-readable relative time (e.g., "3h ago", "2d ago")
    """
    try:
        dt = datetime.strptime(timestamp_str, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
        delta = datetime.now(timezone.utc) - dt
        total_seconds = int(delta.total_seconds())

        if total_seconds < 60:
            return "just now"
        elif total_seconds < 3600:
            minutes = total_seconds // 60
            return f"{minutes}m ago"
        elif total_seconds < 86400:
            hours = total_seconds // 3600
            return f"{hours}h ago"
        else:
            days = total_seconds // 86400
            return f"{days}d ago"
    except (ValueError, TypeError):
        return "unknown"


def _truncate(text: str, max_len: int = 60) -> str:
    """
    Truncate text to a maximum length, adding ellipsis if needed.

    Args:
        text: The text to truncate
        max_len: Maximum character length

    Returns:
        Truncated string
    """
    if not text:
        return ""
    text = text.replace("\n", " ").strip()
    if len(text) <= max_len:
        return text
    return text[:max_len - 3] + "..."


# =============================================================================
# PUBLIC API
# =============================================================================

def run_activity(args: List[str]) -> dict:
    """
    Query recent comment activity across all threads.

    Usage: commons activity [--limit N] [--room ROOM]

    Args:
        args: Command arguments

    Returns:
        Dict with success, activities list, room_filter
    """
    limit = 20
    room: Optional[str] = None

    i = 0
    while i < len(args):
        if args[i] == "--limit" and i + 1 < len(args):
            try:
                limit = int(args[i + 1])
                limit = max(1, min(100, limit))
            except ValueError:
                return {"success": False, "error": "Limit must be a number"}
            i += 2
        elif args[i] == "--room" and i + 1 < len(args):
            room = args[i + 1]
            i += 2
        elif args[i] in ("--help", "-h"):
            return {
                "success": True,
                "help": True,
                "help_text": (
                    "Activity Feed\n\n"
                    "Show recent comments across all threads.\n\n"
                    "Usage:\n"
                    "  commons activity [--limit N] [--room ROOM]\n\n"
                    "Options:\n"
                    "  --limit N     Max results (default: 20, max: 100)\n"
                    "  --room ROOM   Filter by room name"
                ),
            }
        else:
            i += 1

    conn = None
    try:
        conn = get_db()

        if room:
            rows = conn.execute(
                "SELECT c.id, c.author, c.content, c.created_at, "
                "p.id as post_id, p.title, p.room_name "
                "FROM comments c "
                "JOIN posts p ON c.post_id = p.id "
                "WHERE p.room_name = ? "
                "ORDER BY c.created_at DESC "
                "LIMIT ?",
                (room, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT c.id, c.author, c.content, c.created_at, "
                "p.id as post_id, p.title, p.room_name "
                "FROM comments c "
                "JOIN posts p ON c.post_id = p.id "
                "ORDER BY c.created_at DESC "
                "LIMIT ?",
                (limit,),
            ).fetchall()

        close_db(conn)
        conn = None

    except Exception as e:
        logger.error(f"Activity feed error: {e}")
        if conn:
            close_db(conn)
        return {"success": False, "error": str(e)}

    activities = []
    for row in rows:
        activities.append({
            "id": row["id"],
            "author": row["author"],
            "content": _truncate(row["content"], 60),
            "time": _relative_time(row["created_at"]),
            "post_id": row["post_id"],
            "title": _truncate(row["title"], 28),
            "room_name": row["room_name"],
        })

    json_handler.log_operation("activity_query", {"count": len(activities), "room_filter": room})

    return {
        "success": True,
        "activities": activities,
        "room_filter": room,
    }
