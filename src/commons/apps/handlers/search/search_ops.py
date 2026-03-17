# =================== AIPass ====================
# Name: search_ops.py
# Description: Search Operations Handler
# Version: 1.0.0
# Created: 2026-03-07
# Modified: 2026-03-07
# =============================================

"""
Search Operations Handler

Implementation logic for search and log export commands.
Returns dicts for module display layer.
"""

from typing import List

from aipass.prax.apps.modules.logger import system_logger as logger

from commons.apps.handlers.database.db import get_db, close_db
from commons.apps.handlers.search.search_queries import (
    search_posts,
    search_comments,
    search_all,
)
from commons.apps.handlers.search.log_export import export_room_log
from commons.apps.handlers.json import json_handler


# =============================================================================
# PRIVATE HELPERS
# =============================================================================

def _parse_search_args(args: List[str]) -> dict:
    """
    Parse search command arguments.

    Args:
        args: Raw argument list

    Returns:
        Dict with query, room, author, search_type keys
    """
    result = {
        "query": "",
        "room": None,
        "author": None,
        "search_type": "all",
    }

    if not args:
        return result

    result["query"] = args[0]
    remaining = args[1:]

    i = 0
    while i < len(remaining):
        flag = remaining[i]
        if flag == "--room" and i + 1 < len(remaining):
            result["room"] = remaining[i + 1].lower()
            i += 2
        elif flag == "--author" and i + 1 < len(remaining):
            result["author"] = remaining[i + 1].upper()
            i += 2
        elif flag == "--type" and i + 1 < len(remaining):
            search_type = remaining[i + 1].lower()
            if search_type in ("posts", "comments"):
                result["search_type"] = search_type
            i += 2
        else:
            i += 1

    return result


# =============================================================================
# SEARCH OPERATIONS
# =============================================================================

def run_search(args: List[str]) -> dict:
    """
    Full-text search across posts and comments.

    Usage: commons search "query" [--room ROOM] [--author AUTHOR] [--type posts|comments]

    Args:
        args: Command arguments

    Returns:
        Dict with success, posts, comments, query keys
    """
    if not args:
        return {"success": False, "error": 'Usage: commons search "query" [--room ROOM] [--author AUTHOR] [--type posts|comments]'}

    parsed = _parse_search_args(args)
    query = parsed["query"]

    if not query:
        return {"success": False, "error": "Search query cannot be empty"}

    try:
        conn = get_db()

        if parsed["search_type"] == "posts":
            posts = search_posts(conn, query, room=parsed["room"], author=parsed["author"])
            comments_list: list = []
        elif parsed["search_type"] == "comments":
            posts = []
            comments_list = search_comments(conn, query, author=parsed["author"])
        else:
            results = search_all(conn, query, room=parsed["room"], author=parsed["author"])
            posts = results["posts"]
            comments_list = results["comments"]

        close_db(conn)

    except Exception as e:
        logger.error(f"Search failed: {e}")
        return {"success": False, "error": str(e)}

    json_handler.log_operation("search_query", {"query": query, "post_results": len(posts), "comment_results": len(comments_list)})
    return {
        "success": True,
        "query": query,
        "posts": posts,
        "comments": comments_list,
    }


def run_log_export(args: List[str]) -> dict:
    """
    Export a room's post/comment history as plaintext.

    Usage: commons log <room_name> [--limit N]

    Args:
        args: Command arguments

    Returns:
        Dict with success and log_text keys
    """
    if not args:
        return {"success": False, "error": "Usage: commons log <room_name> [--limit N]"}

    room_name = args[0].lower()

    limit = 100
    remaining = args[1:]
    if "--limit" in remaining:
        idx = remaining.index("--limit")
        if idx + 1 < len(remaining):
            try:
                limit = int(remaining[idx + 1])
            except ValueError:
                return {"success": False, "error": "Limit must be a number"}

    try:
        conn = get_db()

        row = conn.execute("SELECT name FROM rooms WHERE name = ?", (room_name,)).fetchone()
        if not row:
            close_db(conn)
            return {"success": False, "error": f"Room '{room_name}' not found"}

        log_text = export_room_log(conn, room_name, limit=limit)
        close_db(conn)

    except Exception as e:
        logger.error(f"Log export failed: {e}")
        return {"success": False, "error": str(e)}

    return {
        "success": True,
        "log_text": log_text,
        "room": room_name,
    }
