# =================== AIPass ====================
# Name: space_ops.py
# Description: Spatial Navigation Data Handler
# Version: 1.0.0
# Created: 2026-03-07
# Modified: 2026-10-17
# =============================================

"""
Spatial Navigation Data Handler

Returns structured dicts for module-layer rendering; never prints.
"""

from datetime import datetime, timedelta, timezone
from typing import Dict, Any

from aipass.prax.apps.modules.logger import system_logger as logger

from aipass.commons.apps.handlers.database.db import get_db, close_db
from aipass.commons.apps.handlers.rooms.room_state_ops import get_all_room_state, set_room_state
from aipass.commons.apps.handlers.json import json_handler


def get_room_enter_data(room_name: str) -> Dict[str, Any]:
    """Gather all data needed to render the 'enter' view for a room."""
    result: Dict[str, Any] = {"found": False, "error": None}

    try:
        conn = get_db()

        row = conn.execute("SELECT * FROM rooms WHERE name = ?", (room_name,)).fetchone()
        if not row:
            close_db(conn)
            result["error"] = f"Room '{room_name}' not found"
            return result

        room = dict(row)
        state = get_all_room_state(conn, room_name)

        post_count = conn.execute("SELECT COUNT(*) FROM posts WHERE room_name = ?", (room_name,)).fetchone()[0]

        cutoff = (datetime.now(timezone.utc) - timedelta(hours=48)).strftime("%Y-%m-%dT%H:%M:%SZ")
        recent_count = conn.execute(
            "SELECT COUNT(*) FROM posts WHERE room_name = ? AND created_at > ?",
            (room_name, cutoff),
        ).fetchone()[0]

        close_db(conn)

        decorations = {k: v for k, v in state.items() if k.startswith("decor_")}

        result.update(
            {
                "found": True,
                "room": room,
                "state": state,
                "post_count": post_count,
                "recent_count": recent_count,
                "decorations": decorations,
            }
        )
        json_handler.log_operation("room_enter", {"room": room_name, "post_count": post_count})

    except Exception as e:
        logger.error(f"[space_ops] Failed to get room enter data for '{room_name}': {e}")
        result["error"] = str(e)

    return result


def record_visit(room_name: str, visitor: str) -> None:
    """Record a branch entering a room; no deduplication, every enter is a visit."""
    try:
        conn = get_db()
        conn.execute(
            "INSERT INTO room_visits (room_name, visitor) VALUES (?, ?)",
            (room_name, visitor),
        )
        conn.commit()
        close_db(conn)
    except Exception as e:
        logger.warning(f"[commons.space_ops] Failed to record visit: {e}")


def get_room_look_data(room_name: str) -> Dict[str, Any]:
    """Gather all data needed to render the 'look' view for a room."""
    result: Dict[str, Any] = {"found": False, "error": None}

    try:
        conn = get_db()

        row = conn.execute("SELECT * FROM rooms WHERE name = ?", (room_name,)).fetchone()
        if not row:
            close_db(conn)
            result["error"] = f"Room '{room_name}' not found"
            return result

        room = dict(row)
        state = get_all_room_state(conn, room_name)

        recent_rows = conn.execute(
            "SELECT id, title, author, created_at FROM posts WHERE room_name = ? ORDER BY created_at DESC LIMIT 5",
            (room_name,),
        ).fetchall()

        close_db(conn)

        decorations = {k: v for k, v in state.items() if k.startswith("decor_")}
        recent_posts = [dict(r) for r in recent_rows]

        result.update(
            {
                "found": True,
                "room": room,
                "state": state,
                "decorations": decorations,
                "recent_posts": recent_posts,
            }
        )

    except Exception as e:
        logger.error(f"[space_ops] Failed to get room look data for '{room_name}': {e}")
        result["error"] = str(e)

    return result


def place_decoration(room_name: str, item_name: str, description: str, branch_name: str) -> Dict[str, Any]:
    """Place a decoration in a room (stored as room_state key=decor_<name>)."""
    result: Dict[str, Any] = {"success": False, "error": None}

    try:
        conn = get_db()

        room = conn.execute("SELECT name FROM rooms WHERE name = ?", (room_name,)).fetchone()
        if not room:
            close_db(conn)
            result["error"] = f"Room '{room_name}' not found"
            return result

        state_key = f"decor_{item_name}"
        state_value = f"{description} (placed by {branch_name})"
        ok = set_room_state(conn, room_name, state_key, state_value)

        close_db(conn)

        display_name = item_name.replace("_", " ").title()
        result.update({"success": ok, "display_name": display_name})
        if not ok:
            result["error"] = "Failed to store decoration"

    except Exception as e:
        logger.error(f"[space_ops] Failed to place decoration '{item_name}' in room '{room_name}': {e}")
        result["error"] = str(e)

    return result


def get_visitors_data(room_name: str) -> Dict[str, Any]:
    """Get distinct visitors in a room in the last 48h (room_visits plus post/comment authors)."""
    result: Dict[str, Any] = {"found": False, "visitors": [], "error": None}

    try:
        conn = get_db()

        room = conn.execute("SELECT name FROM rooms WHERE name = ?", (room_name,)).fetchone()
        if not room:
            close_db(conn)
            result["error"] = f"Room '{room_name}' not found"
            return result

        cutoff = (datetime.now(timezone.utc) - timedelta(hours=48)).strftime("%Y-%m-%dT%H:%M:%SZ")

        visit_rows = conn.execute(
            "SELECT DISTINCT visitor FROM room_visits WHERE room_name = ? AND visited_at > ?",
            (room_name, cutoff),
        ).fetchall()

        # Authors count too: activity from before room_visits existed has no visit rows.
        post_authors = conn.execute(
            "SELECT DISTINCT author FROM posts WHERE room_name = ? AND created_at > ?",
            (room_name, cutoff),
        ).fetchall()

        comment_authors = conn.execute(
            "SELECT DISTINCT c.author FROM comments c "
            "JOIN posts p ON c.post_id = p.id "
            "WHERE p.room_name = ? AND c.created_at > ?",
            (room_name, cutoff),
        ).fetchall()

        close_db(conn)

        visitors = set()
        for row in visit_rows:
            visitors.add(row["visitor"])
        for row in post_authors:
            visitors.add(row["author"])
        for row in comment_authors:
            visitors.add(row["author"])

        result.update({"found": True, "visitors": sorted(visitors)})

    except Exception as e:
        logger.error(f"[space_ops] Failed to get visitors data for room '{room_name}': {e}")
        result["error"] = str(e)

    return result
