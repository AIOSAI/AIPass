# =================== AIPass ====================
# Name: pin_queries.py
# Description: Pin Query Handlers
# Version: 1.0.0
# Created: 2026-03-07
# Modified: 2026-03-07
# =============================================

"""
Pin Query Handlers for The Commons

Database operations for pinning and unpinning posts.
Pinned posts appear at the top of feeds and can be filtered by room.
Pure sqlite3 - no external dependencies.
"""

import sqlite3
from typing import Optional, List, Dict, Any

from commons.apps.handlers.json import json_handler


def pin_post(conn: sqlite3.Connection, post_id: int) -> bool:
    """Pin a post (sets pinned=1)."""
    cursor = conn.execute(
        "UPDATE posts SET pinned = 1 WHERE id = ?",
        (post_id,),
    )
    conn.commit()
    json_handler.log_operation("pin_post", {"post_id": post_id, "success": cursor.rowcount > 0})
    return cursor.rowcount > 0


def unpin_post(conn: sqlite3.Connection, post_id: int) -> bool:
    """Unpin a post (sets pinned=0)."""
    cursor = conn.execute(
        "UPDATE posts SET pinned = 0 WHERE id = ?",
        (post_id,),
    )
    conn.commit()
    return cursor.rowcount > 0


def get_pinned_posts(
    conn: sqlite3.Connection, room_name: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Get all pinned posts, optionally filtered by room."""
    if room_name:
        rows = conn.execute(
            "SELECT id, title, room_name, author, vote_score, comment_count, created_at "
            "FROM posts WHERE pinned = 1 AND room_name = ? "
            "ORDER BY created_at DESC",
            (room_name,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, title, room_name, author, vote_score, comment_count, created_at "
            "FROM posts WHERE pinned = 1 "
            "ORDER BY created_at DESC"
        ).fetchall()

    return [dict(row) for row in rows]


def is_pinned(conn: sqlite3.Connection, post_id: int) -> bool:
    """Check if a post is currently pinned."""
    row = conn.execute(
        "SELECT pinned FROM posts WHERE id = ?",
        (post_id,),
    ).fetchone()

    if not row:
        return False

    return row["pinned"] == 1
