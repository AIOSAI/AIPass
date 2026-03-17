# =================== AIPass ====================
# Name: dashboard_writer.py
# Description: Dashboard Write-Through Handler
# Version: 1.0.0
# Created: 2026-03-07
# Modified: 2026-03-07
# =============================================

"""
Dashboard Write-Through Handler

Updates branch DASHBOARD.local.json files via the devpulse write_section() API.
Queries the Commons SQLite database for real activity counts (mentions,
new posts, new comments) and pushes them to each branch's dashboard.

Usage:
    from commons.apps.handlers.dashboard.dashboard_writer import (
        write_commons_activity, update_commons_dashboard
    )

    # Low-level: write arbitrary activity dict
    write_commons_activity("SEED", {"managed_by": "the_commons", "mentions": 3})

    # High-level: query DB and push real counts for a branch
    update_commons_dashboard("SEED")
"""

import json
import os
import sqlite3
from typing import Any, Callable, Dict, Optional

from aipass.prax.apps.modules.logger import system_logger as logger

from commons.apps.handlers.database.db import get_db, close_db
from commons.apps.handlers.json import json_handler

# Constants
AIPASS_ROOT = os.environ.get("AIPASS_ROOT", os.path.expanduser("~"))
BRANCH_REGISTRY_PATH = os.path.join(AIPASS_ROOT, "BRANCH_REGISTRY.json")

# Lazy-loaded write_section reference
_write_section_fn: Optional[Callable[..., Any]] = None
_write_section_loaded = False


def _get_write_section() -> Optional[Callable[..., Any]]:
    """Lazy import write_section from devpulse module API. Returns callable or None."""
    global _write_section_fn, _write_section_loaded
    if not _write_section_loaded:
        _write_section_loaded = True
        try:
            from aipass.devpulse.apps.modules import dashboard as _dashboard  # type: ignore[import-not-found]
            _write_section_fn = _dashboard.write_section
        except ImportError:
            _write_section_fn = None
    return _write_section_fn


def _find_branch_path(branch_name: str) -> Optional[str]:
    """
    Look up a branch's directory path from BRANCH_REGISTRY.json.

    Args:
        branch_name: The branch name to look up (e.g., "SEED")

    Returns:
        Path string to the branch directory, or None if not found
    """
    if not os.path.exists(BRANCH_REGISTRY_PATH):
        return None

    try:
        with open(BRANCH_REGISTRY_PATH, "r", encoding="utf-8") as f:
            registry = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None

    for branch in registry.get("branches", []):
        if branch.get("name") == branch_name:
            return branch["path"]

    return None


def write_commons_activity(branch_name: str, activity: Dict[str, Any]) -> bool:
    """
    Write the commons_activity section to a branch's DASHBOARD.local.json.

    Uses the devpulse write_section() API for atomic, consistent dashboard writes.
    Failures are logged but never raised.

    Args:
        branch_name: The branch name whose dashboard to update (e.g., "SEED")
        activity: The commons_activity dict to write

    Returns:
        True if written successfully, False otherwise
    """
    try:
        branch_path = _find_branch_path(branch_name)
        if not branch_path:
            logger.warning(f"[commons] Branch path not found for {branch_name}")
            return False

        write_section = _get_write_section()
        if write_section is None:
            logger.warning(f"[commons] write_section unavailable, skipping dashboard for {branch_name}")
            return False
        result = write_section(branch_path, "commons_activity", activity)

        if result:
            logger.info(f"[commons] Dashboard updated for {branch_name}")
        else:
            logger.warning(f"[commons] Dashboard write_section returned False for {branch_name}")

        return result

    except Exception as e:
        logger.error(f"[commons] Dashboard write failed for {branch_name}: {e}")
        return False


def update_commons_dashboard(branch_name: str) -> bool:
    """
    Query the Commons SQLite database for real activity counts and push
    them to the branch's dashboard via write_section().

    Counts:
    - mentions: unread @mentions for this branch (read=0)
    - new_posts_since_last_visit: posts created after last_checked
    - new_comments_since_last_visit: comments created after last_checked

    Args:
        branch_name: The branch name to update (e.g., "SEED")

    Returns:
        True if dashboard was updated, False otherwise
    """
    try:
        branch_path = _find_branch_path(branch_name)
        if not branch_path:
            logger.warning(f"[commons] Branch path not found for {branch_name}")
            return False

        last_checked = _read_last_checked(branch_path)

        conn = get_db()
        try:
            mentions_count = _count_unread_mentions(conn, branch_name)
            mention_details = _get_mention_details(conn, branch_name)
            new_posts = _count_new_posts(conn, last_checked)
            new_comments = _count_new_comments(conn, last_checked)
        finally:
            close_db(conn)

        section_data = {
            "managed_by": "the_commons",
            "mentions": mentions_count,
            "mention_details": mention_details,
            "new_posts_since_last_visit": new_posts,
            "new_comments_since_last_visit": new_comments,
            "last_checked": last_checked,
        }

        write_section = _get_write_section()
        if write_section is None:
            logger.warning(f"[commons] write_section unavailable, skipping dashboard for {branch_name}")
            return False
        result = write_section(branch_path, "commons_activity", section_data)

        if result:
            logger.info(
                f"[commons] Dashboard counts for {branch_name}: "
                f"mentions={mentions_count}, posts={new_posts}, comments={new_comments}"
            )
            json_handler.log_operation("update_dashboard", {"branch": branch_name, "mentions": mentions_count, "success": True})
        else:
            logger.warning(f"[commons] Dashboard write failed for {branch_name}")

        return result

    except Exception as e:
        logger.error(f"[commons] update_commons_dashboard failed for {branch_name}: {e}")
        return False


def _read_last_checked(branch_path: str) -> str:
    """
    Read the last_checked timestamp from the branch's current dashboard.

    Falls back to epoch if the dashboard doesn't exist or has no last_checked field.

    Args:
        branch_path: Path to the branch directory

    Returns:
        ISO timestamp string
    """
    epoch = "1970-01-01T00:00:00Z"
    dashboard_file = os.path.join(branch_path, "DASHBOARD.local.json")

    if not os.path.exists(dashboard_file):
        return epoch

    try:
        with open(dashboard_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        sections = data.get("sections", {})
        commons = sections.get("commons_activity", {})
        last_checked = commons.get("last_checked", "")
        if not last_checked:
            last_checked = commons.get("last_updated", "")
        return last_checked if last_checked else epoch
    except (json.JSONDecodeError, OSError):
        return epoch


def _count_unread_mentions(conn: sqlite3.Connection, branch_name: str) -> int:
    """Count unread mentions for a branch."""
    row = conn.execute(
        "SELECT COUNT(*) as cnt FROM mentions "
        "WHERE mentioned_agent = ? AND read = 0",
        (branch_name,),
    ).fetchone()
    return row["cnt"] if row else 0


def _get_mention_details(
    conn: sqlite3.Connection, branch_name: str, limit: int = 5
) -> list:
    """
    Get recent unread mention details for a branch.

    Returns up to `limit` unread mentions with mentioner, thread title,
    post_id, and timestamp.

    Args:
        conn: SQLite database connection
        branch_name: The branch name to get mentions for
        limit: Max number of mention details to return

    Returns:
        List of dicts with mention details
    """
    rows = conn.execute(
        "SELECT m.mentioner_agent, m.post_id, m.created_at, p.title "
        "FROM mentions m "
        "LEFT JOIN posts p ON m.post_id = p.id "
        "WHERE m.mentioned_agent = ? AND m.read = 0 "
        "ORDER BY m.created_at DESC LIMIT ?",
        (branch_name, limit),
    ).fetchall()

    return [
        {
            "from": row["mentioner_agent"],
            "thread_title": row["title"] or "Unknown",
            "post_id": row["post_id"],
            "timestamp": row["created_at"],
        }
        for row in rows
    ]


def _count_new_posts(conn: sqlite3.Connection, since_time: str) -> int:
    """Count new posts created after a given timestamp."""
    row = conn.execute(
        "SELECT COUNT(*) as cnt FROM posts WHERE created_at > ?",
        (since_time,),
    ).fetchone()
    return row["cnt"] if row else 0


def _count_new_comments(conn: sqlite3.Connection, since_time: str) -> int:
    """Count new comments created after a given timestamp."""
    row = conn.execute(
        "SELECT COUNT(*) as cnt FROM comments WHERE created_at > ?",
        (since_time,),
    ).fetchone()
    return row["cnt"] if row else 0


__all__ = ["write_commons_activity", "update_commons_dashboard"]
