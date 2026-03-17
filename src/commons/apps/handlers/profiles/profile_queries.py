# =================== AIPass ====================
# Name: profile_queries.py
# Description: Social Profile Query Handlers
# Version: 1.0.0
# Created: 2026-03-07
# Modified: 2026-03-07
# =============================================

"""
Profile Query Handlers for The Commons

Database operations for social profiles: get/update bio, status, role,
and activity statistics. Pure sqlite3 - no external dependencies.
"""

import sqlite3
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

from commons.apps.handlers.json import json_handler


def get_profile(conn: sqlite3.Connection, branch_name: str) -> Optional[Dict[str, Any]]:
    """
    Get the full social profile for a branch.

    Args:
        conn: Active database connection
        branch_name: The branch to look up

    Returns:
        Dict with all profile fields, or None if agent not found
    """
    row = conn.execute(
        "SELECT branch_name, display_name, description, karma, joined_at, "
        "last_active, bio, status, role, post_count, comment_count "
        "FROM agents WHERE branch_name = ?",
        (branch_name,)
    ).fetchone()

    if not row:
        return None

    return dict(row)


def update_bio(conn: sqlite3.Connection, branch_name: str, bio: str) -> bool:
    """
    Update an agent's bio text.

    Args:
        conn: Active database connection
        branch_name: The branch to update
        bio: New bio text

    Returns:
        True if updated, False if agent not found
    """
    cursor = conn.execute(
        "UPDATE agents SET bio = ? WHERE branch_name = ?",
        (bio, branch_name)
    )
    conn.commit()
    json_handler.log_operation("update_profile", {"branch": branch_name, "field": "bio"})
    return cursor.rowcount > 0


def update_status(conn: sqlite3.Connection, branch_name: str, status: str) -> bool:
    """
    Update an agent's status message.

    Args:
        conn: Active database connection
        branch_name: The branch to update
        status: New status message

    Returns:
        True if updated, False if agent not found
    """
    cursor = conn.execute(
        "UPDATE agents SET status = ? WHERE branch_name = ?",
        (status, branch_name)
    )
    conn.commit()
    return cursor.rowcount > 0


def update_role(conn: sqlite3.Connection, branch_name: str, role: str) -> bool:
    """
    Update an agent's social role.

    Args:
        conn: Active database connection
        branch_name: The branch to update
        role: New role label

    Returns:
        True if updated, False if agent not found
    """
    cursor = conn.execute(
        "UPDATE agents SET role = ? WHERE branch_name = ?",
        (role, branch_name)
    )
    conn.commit()
    return cursor.rowcount > 0


def get_activity_stats(conn: sqlite3.Connection, branch_name: str) -> Optional[Dict[str, Any]]:
    """
    Get activity statistics for a branch.

    Args:
        conn: Active database connection
        branch_name: The branch to look up

    Returns:
        Dict with post_count, comment_count, karma, joined_at, last_active
        or None if agent not found
    """
    row = conn.execute(
        "SELECT post_count, comment_count, karma, joined_at, last_active "
        "FROM agents WHERE branch_name = ?",
        (branch_name,)
    ).fetchone()

    if not row:
        return None

    return dict(row)


def increment_post_count(conn: sqlite3.Connection, branch_name: str) -> None:
    """
    Increment an agent's post_count by 1.

    Args:
        conn: Active database connection
        branch_name: The branch to update
    """
    conn.execute(
        "UPDATE agents SET post_count = post_count + 1 WHERE branch_name = ?",
        (branch_name,)
    )


def increment_comment_count(conn: sqlite3.Connection, branch_name: str) -> None:
    """
    Increment an agent's comment_count by 1.

    Args:
        conn: Active database connection
        branch_name: The branch to update
    """
    conn.execute(
        "UPDATE agents SET comment_count = comment_count + 1 WHERE branch_name = ?",
        (branch_name,)
    )


def get_all_agents_brief(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    """
    Get a brief listing of all agents for the 'who' command.

    Args:
        conn: Active database connection

    Returns:
        List of dicts with branch_name, status, role, karma
    """
    rows = conn.execute(
        "SELECT branch_name, status, role, karma "
        "FROM agents ORDER BY karma DESC"
    ).fetchall()

    return [dict(row) for row in rows]


def format_time_ago(timestamp: str) -> str:
    """
    Convert an ISO timestamp to a human-readable 'time ago' string.

    Args:
        timestamp: ISO format timestamp string (e.g., 2026-02-08T10:00:00Z)

    Returns:
        Human-readable string like '2h ago', '3d ago', or the date if older
    """
    if not timestamp:
        return "never"

    try:
        dt = datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%SZ").replace(
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
        elif total_seconds < 604800:
            days = total_seconds // 86400
            return f"{days}d ago"
        else:
            return timestamp[:10]
    except (ValueError, TypeError):
        return "unknown"
