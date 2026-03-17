# =================== AIPass ====================
# Name: reaction_queries.py
# Description: Reaction Query Handlers
# Version: 1.0.0
# Created: 2026-03-07
# Modified: 2026-03-07
# =============================================

"""
Reaction Query Handlers for The Commons

Database operations for emoji reactions on posts and comments.
Supports: thumbsup, interesting, agree, disagree, celebrate, thinking.
Pure sqlite3 - no external dependencies.
"""

import sqlite3
from typing import Optional, Dict, List

from commons.apps.handlers.json import json_handler


# Emoji display map
REACTION_EMOJI = {
    "thumbsup": "\U0001f44d",
    "interesting": "\U0001f914",
    "agree": "\u2705",
    "disagree": "\u274c",
    "celebrate": "\U0001f389",
    "thinking": "\U0001f4ad",
}

VALID_REACTIONS = list(REACTION_EMOJI.keys())


def add_reaction(
    conn: sqlite3.Connection,
    agent_name: str,
    reaction: str,
    post_id: Optional[int] = None,
    comment_id: Optional[int] = None,
) -> bool:
    """
    Add a reaction to a post or comment.

    Exactly one of post_id or comment_id must be provided.

    Returns:
        True if new reaction added, False if already exists or invalid
    """
    if reaction not in VALID_REACTIONS:
        return False

    if (post_id is None) == (comment_id is None):
        return False

    if post_id is not None:
        existing = conn.execute(
            "SELECT id FROM reactions WHERE agent_name = ? AND post_id = ? "
            "AND comment_id IS NULL AND reaction = ?",
            (agent_name, post_id, reaction),
        ).fetchone()
    else:
        existing = conn.execute(
            "SELECT id FROM reactions WHERE agent_name = ? AND post_id IS NULL "
            "AND comment_id = ? AND reaction = ?",
            (agent_name, comment_id, reaction),
        ).fetchone()

    if existing:
        return False

    conn.execute(
        "INSERT INTO reactions (agent_name, post_id, comment_id, reaction) "
        "VALUES (?, ?, ?, ?)",
        (agent_name, post_id, comment_id, reaction),
    )
    conn.commit()
    json_handler.log_operation("reaction_added", {"agent": agent_name, "reaction": reaction})
    return True


def remove_reaction(
    conn: sqlite3.Connection,
    agent_name: str,
    reaction: str,
    post_id: Optional[int] = None,
    comment_id: Optional[int] = None,
) -> bool:
    """
    Remove a reaction from a post or comment.

    Returns:
        True if removed, False if didn't exist or invalid
    """
    if reaction not in VALID_REACTIONS:
        return False

    if (post_id is None) == (comment_id is None):
        return False

    if post_id is not None:
        cursor = conn.execute(
            "DELETE FROM reactions WHERE agent_name = ? AND post_id = ? "
            "AND comment_id IS NULL AND reaction = ?",
            (agent_name, post_id, reaction),
        )
    else:
        cursor = conn.execute(
            "DELETE FROM reactions WHERE agent_name = ? AND post_id IS NULL "
            "AND comment_id = ? AND reaction = ?",
            (agent_name, comment_id, reaction),
        )
    conn.commit()
    return cursor.rowcount > 0


def get_reactions(
    conn: sqlite3.Connection,
    post_id: Optional[int] = None,
    comment_id: Optional[int] = None,
) -> Dict[str, int]:
    """
    Get reaction counts for a post or comment.

    Returns:
        Dict mapping reaction type to count
    """
    if (post_id is None) == (comment_id is None):
        return {}

    if post_id is not None:
        rows = conn.execute(
            "SELECT reaction, COUNT(*) as cnt FROM reactions "
            "WHERE post_id = ? AND comment_id IS NULL "
            "GROUP BY reaction",
            (post_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT reaction, COUNT(*) as cnt FROM reactions "
            "WHERE comment_id = ? AND post_id IS NULL "
            "GROUP BY reaction",
            (comment_id,),
        ).fetchall()

    return {row["reaction"]: row["cnt"] for row in rows}


def get_reactions_detailed(
    conn: sqlite3.Connection,
    post_id: Optional[int] = None,
    comment_id: Optional[int] = None,
) -> Dict[str, List[str]]:
    """
    Get detailed reactions with agent names for a post or comment.

    Returns:
        Dict mapping reaction type to list of agent names
    """
    if (post_id is None) == (comment_id is None):
        return {}

    if post_id is not None:
        rows = conn.execute(
            "SELECT reaction, agent_name FROM reactions "
            "WHERE post_id = ? AND comment_id IS NULL "
            "ORDER BY reaction, created_at",
            (post_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT reaction, agent_name FROM reactions "
            "WHERE comment_id = ? AND post_id IS NULL "
            "ORDER BY reaction, created_at",
            (comment_id,),
        ).fetchall()

    result: Dict[str, List[str]] = {}
    for row in rows:
        reaction = row["reaction"]
        if reaction not in result:
            result[reaction] = []
        result[reaction].append(row["agent_name"])

    return result


def get_reaction_summary(
    conn: sqlite3.Connection,
    post_id: Optional[int] = None,
    comment_id: Optional[int] = None,
) -> str:
    """
    Get a formatted emoji summary string for reactions.

    Returns:
        Formatted string like "thumbsup3 thinking1" or empty string
    """
    counts = get_reactions(conn, post_id=post_id, comment_id=comment_id)

    if not counts:
        return ""

    parts = []
    for reaction_type in VALID_REACTIONS:
        count = counts.get(reaction_type, 0)
        if count > 0:
            emoji = REACTION_EMOJI[reaction_type]
            parts.append(f"{emoji}{count}")

    return " ".join(parts)
