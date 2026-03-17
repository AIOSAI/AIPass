# =================== AIPass ====================
# Name: explore_ops.py
# Description: Secret Room Exploration Handler
# Version: 1.0.0
# Created: 2026-03-07
# Modified: 2026-03-07
# =============================================

"""
Secret Room Exploration Handler

Implementation logic for discovering hidden rooms.
Shows hints, tracks which secret rooms a branch has discovered.
Returns dicts for module display layer.
"""

from typing import List

from aipass.prax.apps.modules.logger import system_logger as logger

from commons.apps.handlers.database.db import get_db, close_db
from commons.apps.handlers.json import json_handler


# =============================================================================
# EXPLORE - SHOW HINTS FOR HIDDEN ROOMS
# =============================================================================

def explore_rooms(args: List[str]) -> dict:
    """
    Show discovery hints for hidden rooms.

    If the caller has visited 3+ different rooms, reveal one secret room name.

    Returns:
        Dict with success, hidden_rooms, rooms_visited, revealed room (if any)
    """
    from commons.apps.modules.commons_identity import get_caller_branch
    caller = get_caller_branch()
    if not caller:
        return {"success": False, "error": "Could not detect calling branch. Run from a branch directory."}

    branch_name = caller["name"]

    try:
        conn = get_db()

        hidden_rows = conn.execute(
            "SELECT name, display_name, description, discovery_hint FROM rooms WHERE hidden = 1"
        ).fetchall()

        if not hidden_rows:
            close_db(conn)
            return {"success": True, "hidden_rooms": [], "rooms_visited": 0}

        hidden_rooms = [dict(r) for r in hidden_rows]

        visited = conn.execute(
            "SELECT COUNT(DISTINCT room_name) as cnt FROM ("
            "  SELECT room_name FROM posts WHERE author = ? "
            "  UNION "
            "  SELECT p.room_name FROM comments c JOIN posts p ON c.post_id = p.id WHERE c.author = ?"
            ")",
            (branch_name, branch_name),
        ).fetchone()

        rooms_visited = visited["cnt"] if visited else 0

        close_db(conn)

        result: dict = {
            "success": True,
            "hidden_rooms": hidden_rooms,
            "rooms_visited": rooms_visited,
            "branch_name": branch_name,
        }

        if rooms_visited >= 3 and hidden_rooms:
            result["revealed"] = hidden_rooms[0]

        json_handler.log_operation("explore_rooms", {"branch": branch_name, "rooms_visited": rooms_visited})
        return result

    except Exception as e:
        logger.error(f"Explore failed: {e}")
        return {"success": False, "error": str(e)}


# =============================================================================
# SECRETS - LIST DISCOVERED SECRET ROOMS
# =============================================================================

def list_secrets(args: List[str]) -> dict:
    """
    List secret rooms the caller has discovered (posted or commented in).

    Returns:
        Dict with success, discovered list, total_hidden count
    """
    from commons.apps.modules.commons_identity import get_caller_branch
    caller = get_caller_branch()
    if not caller:
        return {"success": False, "error": "Could not detect calling branch. Run from a branch directory."}

    branch_name = caller["name"]

    try:
        conn = get_db()

        discovered_rows = conn.execute(
            "SELECT DISTINCT r.name, r.display_name, r.description FROM rooms r "
            "WHERE r.hidden = 1 AND ("
            "  r.name IN (SELECT room_name FROM posts WHERE author = ?) "
            "  OR r.name IN ("
            "    SELECT p.room_name FROM comments c JOIN posts p ON c.post_id = p.id "
            "    WHERE c.author = ?"
            "  )"
            ")",
            (branch_name, branch_name),
        ).fetchall()

        total_hidden = conn.execute(
            "SELECT COUNT(*) as cnt FROM rooms WHERE hidden = 1"
        ).fetchone()["cnt"]

        close_db(conn)

        return {
            "success": True,
            "discovered": [dict(r) for r in discovered_rows],
            "total_hidden": total_hidden,
            "branch_name": branch_name,
        }

    except Exception as e:
        logger.error(f"Secrets listing failed: {e}")
        return {"success": False, "error": str(e)}
