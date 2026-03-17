# =================== AIPass ====================
# Name: feed_ops.py
# Description: Feed display and query operations
# Version: 1.0.0
# Created: 2026-03-07
# Modified: 2026-03-07
# =============================================

"""
Feed Operations Handler

Queries and returns post feed data from The Commons database.
Supports room filtering, multiple sort modes (hot/new/top/activity),
and pagination via limit/offset.
"""

from typing import List

from aipass.prax.apps.modules.logger import system_logger as logger

from commons.apps.handlers.database.db import get_db, close_db
from commons.apps.handlers.json import json_handler


# =============================================================================
# HELPERS
# =============================================================================

def format_time_ago(timestamp: str) -> str:
    """Convert ISO timestamp to human-readable relative time."""
    if not timestamp:
        return "never"
    try:
        from datetime import datetime, timezone
        dt = datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - dt
        total_seconds = int(delta.total_seconds())
        if total_seconds < 60:
            return "just now"
        elif total_seconds < 3600:
            return f"{total_seconds // 60}m ago"
        elif total_seconds < 86400:
            return f"{total_seconds // 3600}h ago"
        elif total_seconds < 604800:
            return f"{total_seconds // 86400}d ago"
        else:
            return timestamp[:10]
    except (ValueError, TypeError):
        return "unknown"


# =============================================================================
# FEED DISPLAY
# =============================================================================

def display_feed(args: List[str]) -> dict:
    """
    Query and return the post feed from The Commons.

    Parses CLI-style flags from args list:
        --room <name>       Filter to a specific room
        --sort <mode>       Sort mode: hot, new, top, activity (default: hot)
        --limit <n>         Posts per page (default: 25)
        --offset <n>        Skip N posts (for pagination)
        --page <n>          Page number (alternative to --offset)

    Args:
        args: List of string arguments with optional flags.

    Returns:
        Dict with keys: success, posts, total, sort, room, limit, offset.
        On error: dict with success=False and error message.
    """

    # Parse flags
    room_name = None
    sort = "hot"
    limit = 25
    offset = 0
    page = None

    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--room" and i + 1 < len(args):
            room_name = args[i + 1]
            i += 2
        elif arg == "--sort" and i + 1 < len(args):
            sort = args[i + 1].lower()
            i += 2
        elif arg == "--limit" and i + 1 < len(args):
            try:
                limit = int(args[i + 1])
            except ValueError:
                pass
            i += 2
        elif arg == "--offset" and i + 1 < len(args):
            try:
                offset = int(args[i + 1])
            except ValueError:
                pass
            i += 2
        elif arg == "--page" and i + 1 < len(args):
            try:
                page = int(args[i + 1])
            except ValueError:
                pass
            i += 2
        else:
            i += 1

    # Validate sort mode
    valid_sorts = ("hot", "new", "top", "activity")
    if sort not in valid_sorts:
        sort = "hot"

    # Clamp limit
    if limit < 1:
        limit = 1
    elif limit > 100:
        limit = 100

    # Convert page to offset if provided
    if page is not None:
        if page < 1:
            page = 1
        offset = (page - 1) * limit

    if offset < 0:
        offset = 0

    try:
        conn = get_db()

        # Build query
        where_clause = ""
        params = []
        if room_name:
            where_clause = "WHERE p.room_name = ?"
            params.append(room_name)

        # Sort order - pinned DESC always first
        if sort == "top":
            order_by = "ORDER BY p.pinned DESC, p.vote_score DESC, p.created_at DESC"
        elif sort == "hot":
            order_by = (
                "ORDER BY p.pinned DESC, "
                "(p.vote_score + 1.0) / "
                "(MAX(1, (julianday('now') - julianday(p.created_at)) * 24 + 1)) DESC"
            )
        elif sort == "activity":
            order_by = "ORDER BY p.pinned DESC, last_activity DESC"
        else:  # "new"
            order_by = "ORDER BY p.pinned DESC, p.created_at DESC"

        # Count
        total = conn.execute(
            f"SELECT COUNT(*) FROM posts p {where_clause}", params
        ).fetchone()[0]

        # Get posts
        rows = conn.execute(
            f"""SELECT p.*, COALESCE(p.last_comment_at, p.created_at) AS last_activity
            FROM posts p {where_clause} {order_by} LIMIT ? OFFSET ?""",
            params + [limit, offset]
        ).fetchall()

        result = {
            "success": True,
            "posts": [dict(r) for r in rows],
            "total": total,
            "sort": sort,
            "room": room_name,
            "limit": limit,
            "offset": offset,
        }

        close_db(conn)
        json_handler.log_operation("feed_query", {"total": total, "sort": sort, "room": room_name})
        return result

    except Exception as e:
        logger.error(f"[commons.feed] Feed query failed: {e}")
        return {"success": False, "error": str(e)}
