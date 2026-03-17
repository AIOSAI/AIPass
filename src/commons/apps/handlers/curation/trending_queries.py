# =================== AIPass ====================
# Name: trending_queries.py
# Description: Trending Query Handlers
# Version: 1.0.0
# Created: 2026-03-07
# Modified: 2026-03-07
# =============================================

"""
Trending Query Handlers for The Commons

Database operations for detecting trending posts based on
engagement metrics (votes + comments + reactions) within a time window.
Pure sqlite3 - no external dependencies.
"""

import sqlite3
from typing import List, Dict, Any

from commons.apps.handlers.json import json_handler


def get_trending_posts(
    conn: sqlite3.Connection,
    hours: int = 1,
    min_engagement: int = 3,
    limit: int = 5,
) -> List[Dict[str, Any]]:
    """
    Get trending posts based on total engagement within a time window.

    A post is "trending" if it has at least min_engagement total actions
    (votes + comments + reactions) within the last N hours.

    Returns:
        List of dicts with: id, title, room_name, author, engagement_count,
        vote_score, vote_count, comment_count, reaction_count
    """
    query = """
        SELECT
            p.id,
            p.title,
            p.room_name,
            p.author,
            p.vote_score,
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
        WHERE (COALESCE(v.vote_count, 0) + COALESCE(c.comment_count, 0) + COALESCE(r.reaction_count, 0)) >= ?
        ORDER BY engagement_count DESC, p.vote_score DESC
        LIMIT ?
    """

    hours_offset = f"-{hours}"
    rows = conn.execute(
        query, (hours_offset, hours_offset, hours_offset, min_engagement, limit)
    ).fetchall()

    json_handler.log_operation("trending_query", {"hours": hours, "results": len(rows)})
    return [dict(row) for row in rows]
