# =================== AIPass ====================
# Name: catchup_queries.py
# Description: Catchup Database Queries Handler
# Version: 1.0.0
# Created: 2026-03-07
# Modified: 2026-03-07
# =============================================

"""
Catchup Database Queries Handler

Provides database query functions for the catchup feature.
Queries new posts, comments, mentions, replies, trending, and karma
since a given timestamp.
"""

import sqlite3
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional

from commons.apps.handlers.json import json_handler


def query_catchup_data(
    conn: sqlite3.Connection, branch_name: str, since_time: str
) -> Dict[str, Any]:
    """
    Query all catchup data from the database for a branch.

    Args:
        conn: Database connection
        branch_name: The branch to query catchup data for
        since_time: ISO timestamp to query activity since

    Returns:
        Dict with keys: new_posts_count, new_comments_count, unread_mentions,
        replies, trending, karma_change
    """
    new_posts_count = _count_new_posts(conn, since_time)
    new_comments_count = _count_new_comments(conn, since_time)
    unread_mentions = _get_unread_mentions(conn, branch_name)
    replies = _get_replies(conn, branch_name, since_time)
    trending = _get_trending_post(conn)
    karma_change = _get_karma_change(conn, branch_name, since_time)

    json_handler.log_operation("catchup_query", {"branch": branch_name, "new_posts": new_posts_count, "new_comments": new_comments_count})
    return {
        "new_posts_count": new_posts_count,
        "new_comments_count": new_comments_count,
        "unread_mentions": unread_mentions,
        "replies": replies,
        "trending": trending,
        "karma_change": karma_change,
    }


def get_last_active(conn: sqlite3.Connection, branch_name: str) -> Optional[str]:
    """
    Get the last_active timestamp for a branch.

    Args:
        conn: Database connection
        branch_name: The branch name to look up

    Returns:
        ISO timestamp string or None if never active
    """
    row = conn.execute(
        "SELECT last_active FROM agents WHERE branch_name = ?",
        (branch_name,)
    ).fetchone()

    if row:
        return row["last_active"]
    return None


def update_last_active(conn: sqlite3.Connection, branch_name: str) -> str:
    """
    Update the branch's last_active timestamp to now.

    Args:
        conn: Database connection
        branch_name: The branch name to update

    Returns:
        The ISO timestamp that was set
    """
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn.execute(
        "UPDATE agents SET last_active = ? WHERE branch_name = ?",
        (now_iso, branch_name)
    )
    conn.commit()
    return now_iso


def _count_new_posts(conn: sqlite3.Connection, since_time: str) -> int:
    """Count new posts since the given time."""
    row = conn.execute(
        "SELECT COUNT(*) as cnt FROM posts WHERE created_at > ?",
        (since_time,)
    ).fetchone()
    return row["cnt"] if row else 0


def _count_new_comments(conn: sqlite3.Connection, since_time: str) -> int:
    """Count new comments since the given time."""
    row = conn.execute(
        "SELECT COUNT(*) as cnt FROM comments WHERE created_at > ?",
        (since_time,)
    ).fetchone()
    return row["cnt"] if row else 0


def _get_unread_mentions(
    conn: sqlite3.Connection, branch_name: str
) -> List[Dict[str, Any]]:
    """Get all unread mentions for a branch."""
    rows = conn.execute(
        "SELECT m.*, p.title as post_title, p.room_name "
        "FROM mentions m "
        "LEFT JOIN posts p ON m.post_id = p.id "
        "WHERE m.mentioned_agent = ? AND m.read = 0 "
        "ORDER BY m.created_at DESC",
        (branch_name,)
    ).fetchall()
    return [dict(r) for r in rows]


def _get_replies(
    conn: sqlite3.Connection, branch_name: str, since_time: str
) -> List[Dict[str, Any]]:
    """Get replies to the branch's posts since last active."""
    rows = conn.execute(
        "SELECT c.*, p.title as post_title "
        "FROM comments c "
        "JOIN posts p ON c.post_id = p.id "
        "WHERE p.author = ? AND c.author != ? AND c.created_at > ?",
        (branch_name, branch_name, since_time)
    ).fetchall()
    return [dict(r) for r in rows]


def _get_trending_post(conn: sqlite3.Connection) -> Optional[Dict[str, Any]]:
    """Get the top trending post from the last 24 hours."""
    trending_since = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    row = conn.execute(
        "SELECT id, title, vote_score, room_name FROM posts "
        "WHERE created_at > ? ORDER BY vote_score DESC LIMIT 1",
        (trending_since,)
    ).fetchone()
    return dict(row) if row else None


def _get_karma_change(
    conn: sqlite3.Connection, branch_name: str, since_time: str
) -> int:
    """Calculate karma change from votes on the branch's content since last active."""
    karma_posts_row = conn.execute(
        "SELECT COALESCE(SUM(v.direction), 0) as karma "
        "FROM votes v "
        "JOIN posts p ON v.target_id = p.id AND v.target_type = 'post' "
        "WHERE p.author = ? AND v.created_at > ?",
        (branch_name, since_time)
    ).fetchone()
    karma_from_posts = karma_posts_row["karma"] if karma_posts_row else 0

    karma_comments_row = conn.execute(
        "SELECT COALESCE(SUM(v.direction), 0) as karma "
        "FROM votes v "
        "JOIN comments c ON v.target_id = c.id AND v.target_type = 'comment' "
        "WHERE c.author = ? AND v.created_at > ?",
        (branch_name, since_time)
    ).fetchone()
    karma_from_comments = karma_comments_row["karma"] if karma_comments_row else 0

    return karma_from_posts + karma_from_comments
