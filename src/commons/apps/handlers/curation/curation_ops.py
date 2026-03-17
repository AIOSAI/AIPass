# =================== AIPass ====================
# Name: curation_ops.py
# Description: Curation Operations Handler
# Version: 1.0.0
# Created: 2026-03-07
# Modified: 2026-03-07
# =============================================

"""
Curation Operations Handler

Implementation logic for reactions, pins, and trending commands.
Returns dicts for module display layer.
"""

from typing import List

from aipass.prax.apps.modules.logger import system_logger as logger

from commons.apps.handlers.database.db import get_db, close_db
from commons.apps.modules.commons_identity import get_caller_branch
from commons.apps.handlers.curation.reaction_queries import (
    add_reaction,
    remove_reaction,
    get_reactions_detailed,
    REACTION_EMOJI,
    VALID_REACTIONS,
)
from commons.apps.handlers.curation.pin_queries import (
    pin_post,
    unpin_post,
    get_pinned_posts,
    is_pinned,
)
from commons.apps.handlers.curation.trending_queries import get_trending_posts
from commons.apps.handlers.json import json_handler


# =============================================================================
# REACTION OPERATIONS
# =============================================================================

def add_react(args: List[str]) -> dict:
    """
    Add a reaction to a post or comment.

    Usage: commons react <post|comment> <id> <reaction>

    Returns:
        Dict with success, reaction info, and whether it was new
    """
    if len(args) < 3:
        return {
            "success": False,
            "error": f"Usage: commons react <post|comment> <id> <reaction>\n"
                     f"Valid reactions: {', '.join(VALID_REACTIONS)}",
        }

    target_type = args[0].lower()
    if target_type not in ("post", "comment"):
        return {"success": False, "error": "Target must be 'post' or 'comment'"}

    try:
        target_id = int(args[1])
    except ValueError:
        return {"success": False, "error": "ID must be a number"}

    reaction = args[2].lower()
    if reaction not in VALID_REACTIONS:
        return {
            "success": False,
            "error": f"Invalid reaction: {reaction}\n"
                     f"Valid reactions: {', '.join(VALID_REACTIONS)}",
        }

    caller = get_caller_branch()
    if not caller:
        return {"success": False, "error": "Could not detect calling branch"}

    agent_name = caller["name"]

    try:
        conn = get_db()

        if target_type == "post":
            target = conn.execute("SELECT id FROM posts WHERE id = ?", (target_id,)).fetchone()
        else:
            target = conn.execute("SELECT id FROM comments WHERE id = ?", (target_id,)).fetchone()

        if not target:
            close_db(conn)
            return {"success": False, "error": f"{target_type.title()} {target_id} not found"}

        post_id = target_id if target_type == "post" else None
        comment_id = target_id if target_type == "comment" else None

        is_new = add_reaction(conn, agent_name, reaction, post_id=post_id, comment_id=comment_id)
        close_db(conn)
        json_handler.log_operation("add_reaction", {"reaction": reaction, "target_type": target_type, "target_id": target_id})

        return {
            "success": True,
            "is_new": is_new,
            "reaction": reaction,
            "emoji": REACTION_EMOJI[reaction],
            "target_type": target_type,
            "target_id": target_id,
            "agent": agent_name,
        }

    except Exception as e:
        logger.error(f"React failed: {e}")
        return {"success": False, "error": str(e)}


def remove_react(args: List[str]) -> dict:
    """
    Remove a reaction from a post or comment.

    Usage: commons unreact <post|comment> <id> <reaction>

    Returns:
        Dict with success and whether the reaction was found/removed
    """
    if len(args) < 3:
        return {"success": False, "error": "Usage: commons unreact <post|comment> <id> <reaction>"}

    target_type = args[0].lower()
    if target_type not in ("post", "comment"):
        return {"success": False, "error": "Target must be 'post' or 'comment'"}

    try:
        target_id = int(args[1])
    except ValueError:
        return {"success": False, "error": "ID must be a number"}

    reaction = args[2].lower()
    if reaction not in VALID_REACTIONS:
        return {"success": False, "error": f"Invalid reaction: {reaction}"}

    caller = get_caller_branch()
    if not caller:
        return {"success": False, "error": "Could not detect calling branch"}

    agent_name = caller["name"]

    try:
        conn = get_db()

        post_id = target_id if target_type == "post" else None
        comment_id = target_id if target_type == "comment" else None

        removed = remove_reaction(conn, agent_name, reaction, post_id=post_id, comment_id=comment_id)
        close_db(conn)

        return {
            "success": True,
            "removed": removed,
            "reaction": reaction,
            "emoji": REACTION_EMOJI[reaction],
            "target_type": target_type,
            "target_id": target_id,
            "agent": agent_name,
        }

    except Exception as e:
        logger.error(f"Unreact failed: {e}")
        return {"success": False, "error": str(e)}


def show_reactions(args: List[str]) -> dict:
    """
    Show reactions on a post or comment.

    Usage: commons reactions <post|comment> <id>

    Returns:
        Dict with success and detailed reactions mapping
    """
    if len(args) < 2:
        return {"success": False, "error": "Usage: commons reactions <post|comment> <id>"}

    target_type = args[0].lower()
    if target_type not in ("post", "comment"):
        return {"success": False, "error": "Target must be 'post' or 'comment'"}

    try:
        target_id = int(args[1])
    except ValueError:
        return {"success": False, "error": "ID must be a number"}

    try:
        conn = get_db()

        post_id = target_id if target_type == "post" else None
        comment_id = target_id if target_type == "comment" else None

        detailed = get_reactions_detailed(conn, post_id=post_id, comment_id=comment_id)
        close_db(conn)

        return {
            "success": True,
            "target_type": target_type,
            "target_id": target_id,
            "reactions": detailed,
        }

    except Exception as e:
        logger.error(f"Reactions query failed: {e}")
        return {"success": False, "error": str(e)}


# =============================================================================
# PIN OPERATIONS
# =============================================================================

def pin_post_cmd(args: List[str]) -> dict:
    """
    Pin a post. Only the post author or SYSTEM can pin.

    Usage: commons pin <post_id>

    Returns:
        Dict with success and post info
    """
    if len(args) < 1:
        return {"success": False, "error": "Usage: commons pin <post_id>"}

    try:
        post_id = int(args[0])
    except ValueError:
        return {"success": False, "error": "Post ID must be a number"}

    caller = get_caller_branch()
    if not caller:
        return {"success": False, "error": "Could not detect calling branch"}

    agent_name = caller["name"]

    try:
        conn = get_db()

        post = conn.execute(
            "SELECT id, author, title FROM posts WHERE id = ?", (post_id,)
        ).fetchone()

        if not post:
            close_db(conn)
            return {"success": False, "error": f"Post {post_id} not found"}

        post_dict = dict(post)

        if post_dict["author"] != agent_name and agent_name != "SYSTEM":
            close_db(conn)
            return {"success": False, "error": "Only the post author or SYSTEM can pin a post"}

        if is_pinned(conn, post_id):
            close_db(conn)
            return {"success": False, "error": f"Post {post_id} is already pinned"}

        result = pin_post(conn, post_id)
        close_db(conn)

        if result:
            return {
                "success": True,
                "action": "pinned",
                "post_id": post_id,
                "title": post_dict["title"],
                "agent": agent_name,
            }
        else:
            return {"success": False, "error": f"Failed to pin post {post_id}"}

    except Exception as e:
        logger.error(f"Pin failed: {e}")
        return {"success": False, "error": str(e)}


def unpin_post_cmd(args: List[str]) -> dict:
    """
    Unpin a post.

    Usage: commons unpin <post_id>

    Returns:
        Dict with success and post info
    """
    if len(args) < 1:
        return {"success": False, "error": "Usage: commons unpin <post_id>"}

    try:
        post_id = int(args[0])
    except ValueError:
        return {"success": False, "error": "Post ID must be a number"}

    caller = get_caller_branch()
    if not caller:
        return {"success": False, "error": "Could not detect calling branch"}

    agent_name = caller["name"]

    try:
        conn = get_db()

        post = conn.execute(
            "SELECT id, author, title FROM posts WHERE id = ?", (post_id,)
        ).fetchone()

        if not post:
            close_db(conn)
            return {"success": False, "error": f"Post {post_id} not found"}

        post_dict = dict(post)

        if post_dict["author"] != agent_name and agent_name != "SYSTEM":
            close_db(conn)
            return {"success": False, "error": "Only the post author or SYSTEM can unpin a post"}

        result = unpin_post(conn, post_id)
        close_db(conn)

        if result:
            return {
                "success": True,
                "action": "unpinned",
                "post_id": post_id,
                "title": post_dict["title"],
                "agent": agent_name,
            }
        else:
            return {"success": False, "error": f"Failed to unpin post {post_id}"}

    except Exception as e:
        logger.error(f"Unpin failed: {e}")
        return {"success": False, "error": str(e)}


def show_pinned(args: List[str]) -> dict:
    """
    Get all pinned posts.

    Usage: commons pinned [--room <room_name>]

    Returns:
        Dict with success and list of pinned posts
    """
    room_name = None
    if "--room" in args:
        idx = args.index("--room")
        if idx + 1 < len(args):
            room_name = args[idx + 1]

    try:
        conn = get_db()
        pinned = get_pinned_posts(conn, room_name=room_name)
        close_db(conn)

        return {
            "success": True,
            "posts": pinned,
            "room": room_name,
        }

    except Exception as e:
        logger.error(f"Pinned query failed: {e}")
        return {"success": False, "error": str(e)}


# =============================================================================
# TRENDING OPERATIONS
# =============================================================================

def show_trending(args: List[str]) -> dict:
    """
    Get trending posts.

    Usage: commons trending

    Returns:
        Dict with success and list of trending posts
    """
    try:
        conn = get_db()
        trending = get_trending_posts(conn, hours=1, min_engagement=3, limit=5)
        close_db(conn)

        return {
            "success": True,
            "posts": trending,
        }

    except Exception as e:
        logger.error(f"Trending query failed: {e}")
        return {"success": False, "error": str(e)}
