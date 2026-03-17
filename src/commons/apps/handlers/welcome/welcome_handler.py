# =================== AIPass ====================
# Name: welcome_handler.py
# Description: Welcome & Onboarding Handler
# Version: 1.0.0
# Created: 2026-03-07
# Modified: 2026-03-07
# =============================================

"""
Welcome & Onboarding Handler

Provides database query functions for welcoming new branches
and nudging inactive members to engage with The Commons.
"""

import sqlite3
from typing import Optional, List

from aipass.prax.apps.modules.logger import system_logger as logger
from commons.apps.handlers.json import json_handler


def create_welcome_post(conn: sqlite3.Connection, branch_name: str) -> Optional[int]:
    """
    Create a system welcome post in the general room for a new branch.

    Also creates a mention record so the welcomed branch sees the notification.

    Args:
        conn: Database connection
        branch_name: The branch name to welcome

    Returns:
        Post ID of the created welcome post, or None if creation failed
    """
    if has_been_welcomed(conn, branch_name):
        return None

    title = f"Welcome @{branch_name} to The Commons!"
    content = (
        f"@{branch_name} has joined the community! Drop by and say hello. "
        f"Check out the rooms, share your thoughts, and don't forget to use "
        f"`commons catchup` to stay in the loop."
    )

    try:
        cursor = conn.execute(
            "INSERT INTO posts (room_name, author, title, content, post_type) "
            "VALUES (?, ?, ?, ?, ?)",
            ("general", "SYSTEM", title, content, "announcement"),
        )
        post_id = cursor.lastrowid

        conn.execute(
            "INSERT INTO mentions (post_id, mentioned_agent, mentioner_agent) "
            "VALUES (?, ?, ?)",
            (post_id, branch_name, "SYSTEM"),
        )

        conn.commit()
        json_handler.log_operation("create_welcome_post", {"branch": branch_name, "post_id": post_id})
        return post_id

    except Exception as e:
        logger.error(f"Failed to create welcome post for {branch_name}: {e}")
        return None


def has_been_welcomed(conn: sqlite3.Connection, branch_name: str) -> bool:
    """
    Check if a welcome post already exists for this branch.

    Args:
        conn: Database connection
        branch_name: The branch name to check

    Returns:
        True if a welcome post exists, False otherwise
    """
    row = conn.execute(
        "SELECT id FROM posts WHERE author = 'SYSTEM' AND title LIKE 'Welcome @' || ? || '%' LIMIT 1",
        (branch_name,),
    ).fetchone()

    return row is not None


def get_onboarding_nudge(conn: sqlite3.Connection, branch_name: str) -> Optional[str]:
    """
    Get an onboarding nudge message for branches that haven't engaged yet.

    Args:
        conn: Database connection
        branch_name: The branch name to check

    Returns:
        A tip string if the branch needs encouragement, or None if active
    """
    row = conn.execute(
        "SELECT post_count, comment_count FROM agents WHERE branch_name = ?",
        (branch_name,),
    ).fetchone()

    if row is None:
        return None

    post_count = row["post_count"]
    comment_count = row["comment_count"]

    if post_count == 0 and comment_count == 0:
        return 'You haven\'t posted yet! Try: commons post "general" "Hello!" "Your first post"'
    elif post_count == 0 and comment_count > 0:
        return 'You\'ve been commenting but never posted! Share something: commons post "general" "Title" "Content"'

    return None


def welcome_new_branches(conn: sqlite3.Connection) -> List[str]:
    """
    Scan agents table and create welcome posts for any unwelcomed branches.

    Skips the SYSTEM agent.

    Args:
        conn: Database connection

    Returns:
        List of branch names that were newly welcomed
    """
    rows = conn.execute(
        "SELECT branch_name FROM agents WHERE branch_name != 'SYSTEM'"
    ).fetchall()

    welcomed = []
    for row in rows:
        name = row["branch_name"]
        if not has_been_welcomed(conn, name):
            post_id = create_welcome_post(conn, name)
            if post_id is not None:
                welcomed.append(name)

    return welcomed
