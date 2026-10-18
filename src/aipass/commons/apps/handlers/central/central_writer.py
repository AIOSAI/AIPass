# =================== AIPass ====================
# Name: central_writer.py
# Description: COMMONS Central File Writer
# Version: 1.0.0
# Created: 2026-03-07
# Modified: 2026-10-17
# =============================================

"""
Central Writer Handler

COMMONS.central.json is an output contract: DevPulse reads it when refreshing branch dashboards.
"""

import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Dict, Any, Optional

from aipass.prax.apps.modules.logger import system_logger as logger

from aipass.commons.apps.handlers.database.db import get_db, close_db
from aipass.commons.apps.handlers.json import json_handler


def _find_project_root() -> str:
    """Walk up from __file__ to find project root (AIPASS_REGISTRY.json marker)."""
    current = os.path.dirname(os.path.abspath(__file__))
    for _ in range(10):
        if os.path.exists(os.path.join(current, "AIPASS_REGISTRY.json")):
            return current
        current = os.path.dirname(current)
    return os.path.expanduser("~")


_PROJECT_ROOT = _find_project_root()
AI_CENTRAL_DIR = os.path.join(_PROJECT_ROOT, ".ai_central")
CENTRAL_FILE = os.path.join(AI_CENTRAL_DIR, "COMMONS.central.json")
BRANCH_REGISTRY_PATH = os.path.join(_PROJECT_ROOT, "AIPASS_REGISTRY.json")


def get_registered_branches() -> Dict[str, str]:
    """Load registered branches as name -> path; a missing or malformed registry raises."""
    with open(BRANCH_REGISTRY_PATH, "r", encoding="utf-8") as f:
        registry = json.load(f)

    branches = {}
    for branch in registry.get("branches", []):
        name = branch.get("name", "")
        path = branch.get("path", "")
        if name and path:
            branches[name] = path
    return branches


def _read_last_checked(branch_path: str) -> str:
    """Read last_checked from a branch's dashboard commons_activity section, epoch when absent."""
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
        logger.warning(f"[central_writer] Failed to read dashboard last_checked for {branch_path}")
        return epoch


def _count_unread_mentions(conn: sqlite3.Connection, branch_name: str) -> int:
    """Count unread @mentions for a branch."""
    row = conn.execute(
        "SELECT COUNT(*) as cnt FROM mentions WHERE mentioned_agent = ? AND read = 0",
        (branch_name,),
    ).fetchone()
    return row["cnt"] if row else 0


def _count_new_posts(conn: sqlite3.Connection, since_time: str) -> int:
    """Count posts created after a given timestamp."""
    row = conn.execute(
        "SELECT COUNT(*) as cnt FROM posts WHERE created_at > ?",
        (since_time,),
    ).fetchone()
    return row["cnt"] if row else 0


def _count_new_comments(conn: sqlite3.Connection, since_time: str) -> int:
    """Count comments created after a given timestamp."""
    row = conn.execute(
        "SELECT COUNT(*) as cnt FROM comments WHERE created_at > ?",
        (since_time,),
    ).fetchone()
    return row["cnt"] if row else 0


def _query_top_threads(conn: sqlite3.Connection, limit: int = 3) -> list:
    """Query the most recently active threads by last comment timestamp."""
    rows = conn.execute(
        "SELECT p.id, p.title, p.room_name, p.comment_count, "
        "MAX(c.created_at) as last_activity "
        "FROM posts p "
        "LEFT JOIN comments c ON c.post_id = p.id "
        "GROUP BY p.id "
        "ORDER BY last_activity DESC "
        "LIMIT ?",
        (limit,),
    ).fetchall()

    threads = []
    for row in rows:
        if row["last_activity"] is None:
            continue
        threads.append(
            {
                "id": row["id"],
                "title": row["title"],
                "room": row["room_name"],
                "comment_count": row["comment_count"],
                "last_activity": row["last_activity"],
            }
        )
    return threads


def aggregate_branch_stats() -> Dict[str, Dict[str, Any]]:
    """Aggregate commons activity stats for all registered branches."""
    branches = get_registered_branches()
    stats = {}
    now = datetime.now(timezone.utc).isoformat()

    conn = get_db()
    try:
        for branch_name, branch_path in branches.items():
            try:
                last_checked = _read_last_checked(branch_path)
                mentions = _count_unread_mentions(conn, branch_name)
                new_posts = _count_new_posts(conn, last_checked)
                new_comments = _count_new_comments(conn, last_checked)

                stats[branch_name] = {
                    "mentions": mentions,
                    "new_posts_since_last_visit": new_posts,
                    "new_comments_since_last_visit": new_comments,
                    "last_updated": now,
                }
            except Exception as e:
                logger.warning(f"[commons] Failed to aggregate stats for {branch_name}: {e}")
                continue
    finally:
        close_db(conn)

    return stats


def query_top_threads() -> list:
    """Query top threads from aipass.commons.db."""
    conn = get_db()
    try:
        return _query_top_threads(conn, limit=3)
    finally:
        close_db(conn)


def build_central_data(
    branch_stats: Dict[str, Dict[str, Any]],
    top_threads: Optional[list] = None,
) -> Dict[str, Any]:
    """Build the complete COMMONS.central.json data structure."""
    data: Dict[str, Any] = {
        "service": "the_commons",
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "top_threads": top_threads if top_threads is not None else [],
        "branch_stats": branch_stats,
    }
    return data


def write_central_file(data: Dict[str, Any]) -> None:
    """Write data to COMMONS.central.json using atomic temp file + rename."""
    os.makedirs(AI_CENTRAL_DIR, exist_ok=True)

    tmp_path = CENTRAL_FILE + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp_path, CENTRAL_FILE)


def update_central() -> Dict[str, Any]:
    """Update COMMONS.central.json; call after posts, comments, mentions or votes to keep it in sync."""
    branch_stats = aggregate_branch_stats()
    top_threads = query_top_threads()
    central_data = build_central_data(branch_stats, top_threads=top_threads)
    write_central_file(central_data)

    logger.info(f"[commons] Central file updated: {len(branch_stats)} branches")
    json_handler.log_operation("update_central", {"branches_count": len(branch_stats), "success": True})
    return central_data
