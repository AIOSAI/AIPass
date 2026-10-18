# =================== AIPass ====================
# Name: comment_ops.py
# Description: Comment and voting operations handler
# Version: 1.1.0
# Created: 2026-03-07
# Modified: 2026-10-17
# =============================================

"""
Comment and Voting Operations Handler

All functions return dicts - no direct console output.
"""

from typing import List, Optional

from aipass.prax.apps.modules.logger import system_logger as logger

from aipass.commons.apps.handlers.database.db import get_db, close_db
from aipass.commons.apps.modules.commons_identity import CallerLookupFailed, get_caller_branch, extract_mentions
from aipass.commons.apps.handlers.json import json_handler
from aipass.commons.apps.handlers.search.search_queries import sync_comment_to_fts
from aipass.commons.apps.handlers.profiles.profile_queries import increment_comment_count


def add_comment(args: List[str]) -> dict:
    """Add a comment to a post, with optional nested reply support (--parent <id>)."""
    parent_id: Optional[int] = None
    filtered_args: List[str] = []
    i = 0
    while i < len(args):
        if args[i] == "--parent" and i + 1 < len(args):
            try:
                parent_id = int(args[i + 1])
            except ValueError:
                logger.warning(f"[comment_ops] Invalid --parent value: {args[i + 1]!r}")
                return {"success": False, "error": "Invalid --parent value - must be an integer"}
            i += 2
        else:
            filtered_args.append(args[i])
            i += 1

    if len(filtered_args) < 2:
        return {
            "success": False,
            "error": "Usage: comment <post_id> <content> [--parent <parent_id>]",
        }

    try:
        post_id = int(filtered_args[0])
    except ValueError:
        logger.warning(f"[comment_ops] Invalid post_id for add_comment: {filtered_args[0]!r}")
        return {"success": False, "error": "Invalid post_id - must be an integer"}

    content = filtered_args[1]

    try:
        caller = get_caller_branch()
    except CallerLookupFailed as exc:
        return {"success": False, "error": str(exc)}
    if not caller:
        return {
            "success": False,
            "error": ("Could not detect calling branch. Run from a branch directory or use drone routing."),
        }

    author = caller.get("name", "UNKNOWN")

    conn = None
    try:
        conn = get_db()

        post_row = conn.execute(
            "SELECT id, author, title, room_name FROM posts WHERE id = ?",
            (post_id,),
        ).fetchone()

        if not post_row:
            return {"success": False, "error": f"Post #{post_id} not found"}

        post_title = post_row["title"]

        if parent_id is not None:
            parent_row = conn.execute(
                "SELECT id FROM comments WHERE id = ? AND post_id = ?",
                (parent_id, post_id),
            ).fetchone()

            if not parent_row:
                return {
                    "success": False,
                    "error": f"Parent comment #{parent_id} not found on post #{post_id}",
                }

        existing = conn.execute(
            "SELECT id FROM comments "
            "WHERE post_id = ? AND author = ? AND content = ? "
            "AND created_at > strftime('%Y-%m-%dT%H:%M:%SZ', 'now', '-5 minutes')",
            (post_id, author, content),
        ).fetchone()

        if existing:
            return {
                "success": False,
                "error": "Duplicate comment detected (same content within 5 minutes)",
            }

        cursor = conn.execute(
            "INSERT INTO comments (post_id, parent_id, author, content) VALUES (?, ?, ?, ?)",
            (post_id, parent_id, author, content),
        )
        comment_id = cursor.lastrowid
        assert comment_id is not None, "INSERT must return a lastrowid"

        conn.execute(
            "UPDATE posts SET comment_count = comment_count + 1, "
            "last_comment_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') "
            "WHERE id = ?",
            (post_id,),
        )

        conn.commit()

        mentions = extract_mentions(content)
        mentions_error = ""
        if mentions is None:
            # The comment is committed: still a success, the lost mentions named.
            mentions_error = "mentions not delivered: the agents lookup failed"
            logger.warning(f"[comment_ops] Comment #{comment_id}: {mentions_error}")
            mentions = []

        for mentioned in mentions:
            try:
                conn.execute(
                    "INSERT INTO mentions (comment_id, mentioned_agent, mentioner_agent) VALUES (?, ?, ?)",
                    (comment_id, mentioned, author),
                )
            except Exception as e:
                logger.warning(f"[comment_ops] Failed to store mention {mentioned}: {e}")

        if mentions:
            conn.commit()

        try:
            sync_comment_to_fts(conn, comment_id, content, author)
            conn.commit()
        except Exception as e:
            logger.warning(f"[comment_ops] FTS sync failed for comment #{comment_id}: {e}")

        try:
            increment_comment_count(conn, author)
            conn.commit()
        except Exception as e:
            logger.warning(f"[comment_ops] Comment count increment failed for {author}: {e}")

        logger.info(f"[comment_ops] Comment #{comment_id} on post #{post_id} by {author}")
        json_handler.log_operation("add_comment", {"comment_id": comment_id, "post_id": post_id, "author": author})

        return {
            "success": True,
            "comment_id": comment_id,
            "post_id": post_id,
            "author": author,
            "mentions": mentions,
            "mentions_error": mentions_error,
            "parent_id": parent_id,
            "post_title": post_title,
        }

    except Exception as e:
        logger.error(f"[comment_ops] add_comment failed: {e}")
        return {"success": False, "error": str(e)}

    finally:
        if conn:
            close_db(conn)


def vote_on_content(args: List[str]) -> dict:
    """Vote on a post or comment; a repeat vote toggles off, a reversed one moves score and karma by 2."""
    if len(args) < 3:
        return {
            "success": False,
            "error": "Usage: vote <post|comment> <id> <up|down>",
        }

    target_type = args[0].lower()
    direction_str = args[2].lower()

    if target_type not in ("post", "comment"):
        return {
            "success": False,
            "error": f"Invalid target type '{target_type}'. Must be 'post' or 'comment'",
        }

    try:
        target_id = int(args[1])
    except ValueError:
        logger.warning(f"[comment_ops] Invalid target_id for vote: {args[1]!r}")
        return {"success": False, "error": "Invalid target_id - must be an integer"}

    if direction_str not in ("up", "down"):
        return {
            "success": False,
            "error": f"Invalid direction '{direction_str}'. Must be 'up' or 'down'",
        }

    direction_value = 1 if direction_str == "up" else -1

    try:
        caller = get_caller_branch()
    except CallerLookupFailed as exc:
        return {"success": False, "error": str(exc)}
    if not caller:
        return {
            "success": False,
            "error": ("Could not detect calling branch. Run from a branch directory or use drone routing."),
        }

    voter = caller.get("name", "UNKNOWN")

    conn = None
    try:
        conn = get_db()

        if target_type == "post":
            target_row = conn.execute(
                "SELECT id, author, vote_score FROM posts WHERE id = ?",
                (target_id,),
            ).fetchone()
        else:
            target_row = conn.execute(
                "SELECT id, author, vote_score FROM comments WHERE id = ?",
                (target_id,),
            ).fetchone()

        if not target_row:
            return {
                "success": False,
                "error": f"{target_type.capitalize()} #{target_id} not found",
            }

        target_author = target_row["author"]

        if voter == target_author:
            return {"success": False, "error": "Cannot vote on your own content"}

        existing_vote = conn.execute(
            "SELECT id, direction FROM votes WHERE agent_name = ? AND target_id = ? AND target_type = ?",
            (voter, target_id, target_type),
        ).fetchone()

        if existing_vote:
            existing_direction = existing_vote["direction"]

            if existing_direction == direction_value:
                conn.execute("DELETE FROM votes WHERE id = ?", (existing_vote["id"],))

                score_delta = -direction_value
                action = "removed"
            else:
                conn.execute(
                    "UPDATE votes SET direction = ?, created_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = ?",
                    (direction_value, existing_vote["id"]),
                )

                score_delta = direction_value * 2
                action = "changed"
        else:
            conn.execute(
                "INSERT INTO votes (agent_name, target_id, target_type, direction) VALUES (?, ?, ?, ?)",
                (voter, target_id, target_type, direction_value),
            )

            score_delta = direction_value
            action = "voted"

        if target_type == "post":
            conn.execute(
                "UPDATE posts SET vote_score = vote_score + ? WHERE id = ?",
                (score_delta, target_id),
            )
        else:
            conn.execute(
                "UPDATE comments SET vote_score = vote_score + ? WHERE id = ?",
                (score_delta, target_id),
            )

        conn.execute(
            "UPDATE agents SET karma = karma + ? WHERE branch_name = ?",
            (score_delta, target_author),
        )

        conn.commit()

        if target_type == "post":
            updated = conn.execute("SELECT vote_score FROM posts WHERE id = ?", (target_id,)).fetchone()
        else:
            updated = conn.execute("SELECT vote_score FROM comments WHERE id = ?", (target_id,)).fetchone()

        new_score = updated["vote_score"] if updated else 0

        logger.info(
            f"[comment_ops] Vote {action} by {voter}: "
            f"{direction_str} on {target_type} #{target_id} (score: {new_score})"
        )

        return {
            "success": True,
            "action": action,
            "direction": direction_str,
            "target_type": target_type,
            "target_id": target_id,
            "new_score": new_score,
        }

    except Exception as e:
        logger.error(f"[comment_ops] vote_on_content failed: {e}")
        return {"success": False, "error": str(e)}

    finally:
        if conn:
            close_db(conn)
