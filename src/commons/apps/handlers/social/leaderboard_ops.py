# =================== AIPass ====================
# Name: leaderboard_ops.py
# Description: Leaderboard Operations Handler
# Version: 1.0.0
# Created: 2026-03-07
# Modified: 2026-03-07
# =============================================

"""
Leaderboard Operations Handler

Implementation logic for displaying rankings across categories:
most artifacts, most trades, most posts, most active room, top karma.
Returns dicts for module display layer.
"""

import sqlite3
from typing import List, Dict, Any

from aipass.prax.apps.modules.logger import system_logger as logger

from commons.apps.handlers.database.db import get_db, close_db
from commons.apps.handlers.json import json_handler


# =============================================================================
# LEADERBOARD CATEGORIES
# =============================================================================

VALID_CATEGORIES = ["artifacts", "trades", "posts", "rooms", "karma"]


def _query_artifacts(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    """Get branches with the highest artifact count."""
    rows = conn.execute(
        "SELECT owner, COUNT(*) as cnt FROM artifacts "
        "GROUP BY owner ORDER BY cnt DESC LIMIT 10"
    ).fetchall()
    return [{"branch": row["owner"], "count": row["cnt"]} for row in rows]


def _query_trades(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    """Get branches with the most gift/trade activity."""
    rows = conn.execute(
        "SELECT from_agent as branch, COUNT(*) as cnt FROM artifact_history "
        "WHERE action IN ('traded', 'gifted') "
        "GROUP BY from_agent ORDER BY cnt DESC LIMIT 10"
    ).fetchall()
    return [{"branch": row["branch"], "count": row["cnt"]} for row in rows]


def _query_posts(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    """Get branches with the highest post_count."""
    rows = conn.execute(
        "SELECT branch_name, post_count FROM agents "
        "WHERE post_count > 0 "
        "ORDER BY post_count DESC LIMIT 10"
    ).fetchall()
    return [{"branch": row["branch_name"], "count": row["post_count"]} for row in rows]


def _query_rooms(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    """Get rooms with the most posts in the last 7 days."""
    rows = conn.execute(
        "SELECT room_name, COUNT(*) as cnt FROM posts "
        "WHERE created_at > strftime('%Y-%m-%dT%H:%M:%SZ', 'now', '-7 days') "
        "GROUP BY room_name ORDER BY cnt DESC LIMIT 10"
    ).fetchall()
    return [{"room": row["room_name"], "count": row["cnt"]} for row in rows]


def _query_karma(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    """Get branches with the highest karma."""
    rows = conn.execute(
        "SELECT branch_name, karma FROM agents "
        "WHERE karma > 0 "
        "ORDER BY karma DESC LIMIT 10"
    ).fetchall()
    return [{"branch": row["branch_name"], "count": row["karma"]} for row in rows]


# =============================================================================
# PUBLIC API
# =============================================================================

def show_leaderboard(args: List[str]) -> dict:
    """
    Query leaderboard data.

    Usage: commons leaderboard [--category CATEGORY]
    Categories: artifacts, trades, posts, rooms, karma
    Default: show all categories.

    Returns:
        Dict with success, category, and boards data
    """
    category = None
    i = 0
    while i < len(args):
        if args[i] == "--category" and i + 1 < len(args):
            category = args[i + 1].lower()
            i += 2
        else:
            i += 1

    if category and category not in VALID_CATEGORIES:
        return {
            "success": False,
            "error": f"Invalid category '{category}'. Must be one of: {', '.join(VALID_CATEGORIES)}",
        }

    try:
        conn = get_db()

        boards: Dict[str, List[Dict[str, Any]]] = {}

        query_map = {
            "artifacts": _query_artifacts,
            "trades": _query_trades,
            "posts": _query_posts,
            "rooms": _query_rooms,
            "karma": _query_karma,
        }

        if category:
            boards[category] = query_map[category](conn)
        else:
            for cat in VALID_CATEGORIES:
                boards[cat] = query_map[cat](conn)

        close_db(conn)
        json_handler.log_operation("leaderboard_query", {"category": category or "all"})

        return {
            "success": True,
            "category": category or "all",
            "boards": boards,
        }

    except Exception as e:
        logger.error(f"Leaderboard query failed: {e}")
        return {"success": False, "error": str(e)}
