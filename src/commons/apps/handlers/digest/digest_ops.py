# =================== AIPass ====================
# Name: digest_ops.py
# Description: Digest Operations Handler
# Version: 1.0.0
# Created: 2026-03-07
# Modified: 2026-03-07
# =============================================

"""
Digest Operations Handler

Implementation logic for the trending + highlights digest.
Queries recent activity across posts, comments, votes, and reactions
to produce a summary of community engagement over the last 24 hours.
Returns dicts for module display layer.
"""

import sqlite3
from typing import List, Dict, Any

from aipass.prax.apps.modules.logger import system_logger as logger

from commons.apps.handlers.database.db import get_db, close_db
from commons.apps.handlers.json import json_handler


# =============================================================================
# QUERY HELPERS
# =============================================================================

def _get_top_posts(conn: sqlite3.Connection, hours: int = 24, limit: int = 3) -> List[Dict[str, Any]]:
    """
    Get top posts by engagement in the last N hours.

    Args:
        conn: Active database connection
        hours: Lookback window in hours
        limit: Max posts to return

    Returns:
        List of dicts with post info and engagement counts
    """
    hours_offset = f"-{hours}"
    query = """
        SELECT
            p.id,
            p.title,
            p.room_name,
            p.author,
            p.vote_score,
            p.created_at,
            COALESCE(v.vote_count, 0) AS vote_count,
            COALESCE(c.comment_count, 0) AS comment_count,
            COALESCE(r.reaction_count, 0) AS reaction_count,
            (COALESCE(v.vote_count, 0) + COALESCE(c.comment_count, 0) + COALESCE(r.reaction_count, 0)) AS engagement_count
        FROM posts p
        LEFT JOIN (
            SELECT target_id, COUNT(*) AS vote_count
            FROM votes
            WHERE target_type = 'post'
              AND created_at >= strftime('%Y-%m-%dT%H:%M:%SZ', 'now', ? || ' hours')
            GROUP BY target_id
        ) v ON p.id = v.target_id
        LEFT JOIN (
            SELECT post_id, COUNT(*) AS comment_count
            FROM comments
            WHERE created_at >= strftime('%Y-%m-%dT%H:%M:%SZ', 'now', ? || ' hours')
            GROUP BY post_id
        ) c ON p.id = c.post_id
        LEFT JOIN (
            SELECT post_id, COUNT(*) AS reaction_count
            FROM reactions
            WHERE post_id IS NOT NULL
              AND created_at >= strftime('%Y-%m-%dT%H:%M:%SZ', 'now', ? || ' hours')
            GROUP BY post_id
        ) r ON p.id = r.post_id
        WHERE p.created_at >= strftime('%Y-%m-%dT%H:%M:%SZ', 'now', ? || ' hours')
           OR (COALESCE(v.vote_count, 0) + COALESCE(c.comment_count, 0) + COALESCE(r.reaction_count, 0)) > 0
        ORDER BY engagement_count DESC, p.vote_score DESC
        LIMIT ?
    """
    rows = conn.execute(
        query, (hours_offset, hours_offset, hours_offset, hours_offset, limit)
    ).fetchall()
    return [dict(row) for row in rows]


def _get_most_active_branches(conn: sqlite3.Connection, hours: int = 24, limit: int = 5) -> List[Dict[str, Any]]:
    """
    Get most active branches by post + comment count in the last N hours.

    Args:
        conn: Active database connection
        hours: Lookback window in hours
        limit: Max branches to return

    Returns:
        List of dicts with branch activity counts
    """
    hours_offset = f"-{hours}"
    query = """
        SELECT
            agent,
            SUM(post_count) AS post_count,
            SUM(comment_count) AS comment_count,
            SUM(post_count) + SUM(comment_count) AS total_activity
        FROM (
            SELECT author AS agent, COUNT(*) AS post_count, 0 AS comment_count
            FROM posts
            WHERE created_at >= strftime('%Y-%m-%dT%H:%M:%SZ', 'now', ? || ' hours')
            GROUP BY author
            UNION ALL
            SELECT author AS agent, 0 AS post_count, COUNT(*) AS comment_count
            FROM comments
            WHERE created_at >= strftime('%Y-%m-%dT%H:%M:%SZ', 'now', ? || ' hours')
            GROUP BY author
        )
        GROUP BY agent
        ORDER BY total_activity DESC
        LIMIT ?
    """
    rows = conn.execute(query, (hours_offset, hours_offset, limit)).fetchall()
    return [dict(row) for row in rows]


def _get_new_branches(conn: sqlite3.Connection, hours: int = 24) -> List[str]:
    """
    Get branches that joined in the last N hours.

    Args:
        conn: Active database connection
        hours: Lookback window in hours

    Returns:
        List of branch names
    """
    hours_offset = f"-{hours}"
    query = """
        SELECT branch_name
        FROM agents
        WHERE joined_at >= strftime('%Y-%m-%dT%H:%M:%SZ', 'now', ? || ' hours')
          AND branch_name NOT IN ('SYSTEM', 'THE_COMMONS')
        ORDER BY joined_at DESC
    """
    rows = conn.execute(query, (hours_offset,)).fetchall()
    return [row["branch_name"] for row in rows]


def _get_activity_totals(conn: sqlite3.Connection, hours: int = 24) -> Dict[str, int]:
    """
    Get total posts and comments in the last N hours.

    Args:
        conn: Active database connection
        hours: Lookback window in hours

    Returns:
        Dict with total_posts and total_comments
    """
    hours_offset = f"-{hours}"

    post_count = conn.execute(
        "SELECT COUNT(*) FROM posts WHERE created_at >= strftime('%Y-%m-%dT%H:%M:%SZ', 'now', ? || ' hours')",
        (hours_offset,),
    ).fetchone()[0]

    comment_count = conn.execute(
        "SELECT COUNT(*) FROM comments WHERE created_at >= strftime('%Y-%m-%dT%H:%M:%SZ', 'now', ? || ' hours')",
        (hours_offset,),
    ).fetchone()[0]

    return {"total_posts": post_count, "total_comments": comment_count}


# =============================================================================
# PUBLIC API
# =============================================================================

def show_digest(args: List[str]) -> dict:
    """
    Query community digest data (last 24 hours).

    Args:
        args: Command arguments (currently unused)

    Returns:
        Dict with success, top_posts, active_branches, new_branches, totals
    """
    try:
        conn = get_db()

        top_posts = _get_top_posts(conn, hours=24, limit=3)
        active_branches = _get_most_active_branches(conn, hours=24, limit=5)
        new_branches = _get_new_branches(conn, hours=24)
        totals = _get_activity_totals(conn, hours=24)

        close_db(conn)

    except Exception as e:
        logger.error(f"Digest query failed: {e}")
        return {"success": False, "error": str(e)}

    json_handler.log_operation("digest_query", {"top_posts": len(top_posts), "totals": totals})
    return {
        "success": True,
        "top_posts": top_posts,
        "active_branches": active_branches,
        "new_branches": new_branches,
        "totals": totals,
    }
