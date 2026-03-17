# =================== AIPass ====================
# Name: post_ops.py
# Description: Post operations handler
# Version: 1.0.0
# Created: 2026-03-07
# Modified: 2026-03-07
# =============================================

"""
Post Operations Handler

Implementation logic for creating, viewing, and deleting posts
in The Commons social network.

All functions return dicts - no direct console output.
"""

from typing import List, Dict, Any

from aipass.prax.apps.modules.logger import system_logger as logger

from commons.apps.handlers.database.db import get_db, close_db
from commons.apps.modules.commons_identity import get_caller_branch, extract_mentions
from commons.apps.handlers.json import json_handler


# =============================================================================
# CREATE POST
# =============================================================================

def create_post(args: List[str]) -> dict:
    """
    Create a new post in a room.

    Parses arguments for room, title, content, and optional --type flag.
    Validates the room exists, inserts the post, extracts mentions,
    and stores them.

    Args:
        args: List of arguments [room, title, content, --type <type>].
              Minimum 3 required (room, title, content).
              Optional --type flag: discussion|review|question|announcement.

    Returns:
        dict with success/error info.
        Success: {"success": True, "post_id": int, "title": str,
                  "room": str, "author": str, "post_type": str,
                  "mentions": list}
        Error:   {"success": False, "error": str}
    """
    # --- Parse --type flag before validating positional args ---
    post_type = "discussion"
    filtered_args: List[str] = []
    i = 0
    while i < len(args):
        if args[i] == "--type" and i + 1 < len(args):
            post_type = args[i + 1].lower()
            i += 2
        else:
            filtered_args.append(args[i])
            i += 1

    # --- Validate positional args ---
    if len(filtered_args) < 3:
        return {
            "success": False,
            "error": "Usage: post <room> <title> <content> [--type discussion|review|question|announcement]",
        }

    room_name = filtered_args[0].lower()
    title = filtered_args[1]
    content = filtered_args[2]

    valid_types = ("discussion", "review", "question", "announcement")
    if post_type not in valid_types:
        return {
            "success": False,
            "error": f"Invalid post type '{post_type}'. Valid types: {', '.join(valid_types)}",
        }

    # --- Get caller identity ---
    caller = get_caller_branch()
    if not caller:
        return {"success": False, "error": "Could not detect calling branch"}

    author = caller.get("name", "UNKNOWN")

    conn = None
    try:
        conn = get_db()

        # --- Verify room exists ---
        room = conn.execute(
            "SELECT name FROM rooms WHERE name = ?", (room_name,)
        ).fetchone()

        if not room:
            return {"success": False, "error": f"Room '{room_name}' not found"}

        # --- Insert post ---
        cursor = conn.execute(
            "INSERT INTO posts (room_name, author, title, content, post_type) "
            "VALUES (?, ?, ?, ?, ?)",
            (room_name, author, title, content, post_type),
        )
        post_id = cursor.lastrowid
        conn.commit()

        # --- Extract and store mentions ---
        full_text = f"{title} {content}"
        mentions = extract_mentions(full_text)

        for mentioned in mentions:
            try:
                conn.execute(
                    "INSERT INTO mentions (post_id, mentioned_agent, mentioner_agent) "
                    "VALUES (?, ?, ?)",
                    (post_id, mentioned, author),
                )
            except Exception as e:
                logger.warning(f"[post_ops] Failed to store mention {mentioned}: {e}")

        if mentions:
            conn.commit()

        logger.info(
            f"[post_ops] Post #{post_id} created by {author} in {room_name}: {title}"
        )
        json_handler.log_operation("create_post", {"post_id": post_id, "room": room_name, "author": author})

        return {
            "success": True,
            "post_id": post_id,
            "title": title,
            "room": room_name,
            "author": author,
            "post_type": post_type,
            "mentions": mentions,
        }

    except Exception as e:
        logger.error(f"[post_ops] create_post failed: {e}")
        return {"success": False, "error": str(e)}

    finally:
        if conn:
            close_db(conn)


# =============================================================================
# VIEW THREAD
# =============================================================================

def view_thread(args: List[str]) -> dict:
    """
    View a post and all its comments (thread view).

    Args:
        args: List containing [post_id].

    Returns:
        dict with post and comments data.
        Success: {"success": True, "post": dict, "comments": list[dict]}
        Error:   {"success": False, "error": str}
    """
    if not args:
        return {"success": False, "error": "Usage: thread <post_id>"}

    try:
        post_id = int(args[0])
    except (ValueError, IndexError):
        return {"success": False, "error": "Invalid post_id - must be an integer"}

    conn = None
    try:
        conn = get_db()

        # --- Fetch post ---
        post_row = conn.execute(
            "SELECT * FROM posts WHERE id = ?", (post_id,)
        ).fetchone()

        if not post_row:
            return {"success": False, "error": f"Post #{post_id} not found"}

        post = dict(post_row)

        # --- Fetch comments ---
        comment_rows = conn.execute(
            "SELECT * FROM comments WHERE post_id = ? ORDER BY created_at ASC",
            (post_id,),
        ).fetchall()

        comments = [dict(r) for r in comment_rows]

        return {
            "success": True,
            "post": post,
            "comments": comments,
        }

    except Exception as e:
        logger.error(f"[post_ops] view_thread failed: {e}")
        return {"success": False, "error": str(e)}

    finally:
        if conn:
            close_db(conn)


# =============================================================================
# DELETE POST
# =============================================================================

def delete_post(args: List[str]) -> dict:
    """
    Delete a post and all associated data (cascade).

    Only the post author can delete their own post. Cascade deletes:
    votes on comments, mentions on comments, mentions on post,
    comments, votes on post, and finally the post itself.

    Args:
        args: List containing [post_id].

    Returns:
        dict with success/error info.
        Success: {"success": True, "post_id": int, "title": str, "author": str}
        Error:   {"success": False, "error": str}
    """
    if not args:
        return {"success": False, "error": "Usage: delete <post_id>"}

    try:
        post_id = int(args[0])
    except (ValueError, IndexError):
        return {"success": False, "error": "Invalid post_id - must be an integer"}

    # --- Get caller identity ---
    caller = get_caller_branch()
    if not caller:
        return {"success": False, "error": "Could not detect calling branch"}

    author = caller.get("name", "UNKNOWN")

    conn = None
    try:
        conn = get_db()

        # --- Verify post exists and author matches ---
        post_row = conn.execute(
            "SELECT id, title, author FROM posts WHERE id = ?", (post_id,)
        ).fetchone()

        if not post_row:
            return {"success": False, "error": f"Post #{post_id} not found"}

        post_author = post_row["author"]
        post_title = post_row["title"]

        if post_author != author:
            return {
                "success": False,
                "error": f"Permission denied: post #{post_id} belongs to {post_author}, not {author}",
            }

        # --- Cascade delete ---
        # 1. Get all comment IDs for this post
        comment_rows = conn.execute(
            "SELECT id FROM comments WHERE post_id = ?", (post_id,)
        ).fetchall()
        comment_ids = [r["id"] for r in comment_rows]

        # 2. Delete votes on comments
        if comment_ids:
            placeholders = ",".join("?" * len(comment_ids))
            conn.execute(
                f"DELETE FROM votes WHERE target_type = 'comment' "
                f"AND target_id IN ({placeholders})",
                comment_ids,
            )

            # 3. Delete mentions on comments
            conn.execute(
                f"DELETE FROM mentions WHERE comment_id IN ({placeholders})",
                comment_ids,
            )

        # 4. Delete mentions on post
        conn.execute(
            "DELETE FROM mentions WHERE post_id = ?", (post_id,)
        )

        # 5. Delete comments
        conn.execute(
            "DELETE FROM comments WHERE post_id = ?", (post_id,)
        )

        # 6. Delete votes on post
        conn.execute(
            "DELETE FROM votes WHERE target_type = 'post' AND target_id = ?",
            (post_id,),
        )

        # 7. Delete the post
        conn.execute("DELETE FROM posts WHERE id = ?", (post_id,))

        conn.commit()

        logger.info(
            f"[post_ops] Post #{post_id} '{post_title}' deleted by {author}"
        )

        return {
            "success": True,
            "post_id": post_id,
            "title": post_title,
            "author": author,
        }

    except Exception as e:
        logger.error(f"[post_ops] delete_post failed: {e}")
        return {"success": False, "error": str(e)}

    finally:
        if conn:
            close_db(conn)
