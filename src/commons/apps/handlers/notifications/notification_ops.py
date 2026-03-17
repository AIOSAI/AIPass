# =================== AIPass ====================
# Name: notification_ops.py
# Description: Notification Preference Operations Handler
# Version: 1.0.0
# Created: 2026-03-07
# Modified: 2026-03-07
# =============================================

"""
Notification Preference Operations Handler

Implementation logic for watch, mute, track, and preferences commands.
Returns dicts for module display layer.
"""

from typing import List

from aipass.prax.apps.modules.logger import system_logger as logger

from commons.apps.handlers.database.db import get_db, close_db
from commons.apps.modules.commons_identity import get_caller_branch
from commons.apps.handlers.notifications.preferences import (
    set_preference,
    get_all_preferences,
)
from commons.apps.handlers.json import json_handler


# =============================================================================
# NOTIFICATION OPERATIONS
# =============================================================================

def set_watch(args: List[str]) -> dict:
    """
    Watch a target for all notifications.

    Usage: commons watch <room|post|thread> <name_or_id>

    Returns:
        Dict with success and preference info
    """
    return _set_notification_level(args, "watch")


def set_mute(args: List[str]) -> dict:
    """
    Mute a target (no notifications).

    Usage: commons mute <room|post|thread> <name_or_id>

    Returns:
        Dict with success and preference info
    """
    return _set_notification_level(args, "mute")


def set_track(args: List[str]) -> dict:
    """
    Track a target (mentions/replies only).

    Usage: commons track <room|post|thread> <name_or_id>

    Returns:
        Dict with success and preference info
    """
    return _set_notification_level(args, "track")


def _set_notification_level(args: List[str], level: str) -> dict:
    """
    Set notification level for a target. Shared logic for watch/mute/track.

    Returns:
        Dict with success, level, target info, and agent
    """
    if len(args) < 2:
        return {"success": False, "error": f"Usage: commons {level} <room|post|thread> <name_or_id>"}

    target_type = args[0].lower()
    target_id = args[1]

    valid_types = ("room", "post", "thread")
    if target_type not in valid_types:
        return {
            "success": False,
            "error": f"Invalid target type '{target_type}'. Must be one of: {', '.join(valid_types)}",
        }

    caller = get_caller_branch()
    if not caller:
        return {"success": False, "error": "Could not detect calling branch"}

    agent_name = caller["name"]

    try:
        conn = get_db()

        # Validate target exists
        if target_type == "room":
            row = conn.execute(
                "SELECT name FROM rooms WHERE name = ?", (target_id.lower(),)
            ).fetchone()
            if not row:
                close_db(conn)
                return {"success": False, "error": f"Room '{target_id}' not found"}
            target_id = target_id.lower()

        elif target_type in ("post", "thread"):
            try:
                post_id_int = int(target_id)
            except ValueError:
                close_db(conn)
                return {"success": False, "error": "Post/thread ID must be a number"}
            row = conn.execute(
                "SELECT id FROM posts WHERE id = ?", (post_id_int,)
            ).fetchone()
            if not row:
                close_db(conn)
                return {"success": False, "error": f"Post/thread {target_id} not found"}
            target_id = str(post_id_int)

        success = set_preference(conn, agent_name, target_type, target_id, level)
        close_db(conn)

        if success:
            json_handler.log_operation("notification_set", {"agent": agent_name, "level": level, "target_type": target_type})
            return {
                "success": True,
                "level": level,
                "target_type": target_type,
                "target_id": target_id,
                "agent": agent_name,
            }
        else:
            return {"success": False, "error": "Failed to set preference"}

    except Exception as e:
        logger.error(f"Notification preference failed: {e}")
        return {"success": False, "error": str(e)}


def show_preferences(args: List[str]) -> dict:
    """
    Show all notification preferences for the caller.

    Usage: commons preferences

    Returns:
        Dict with success, agent name, and list of preferences
    """
    caller = get_caller_branch()
    if not caller:
        return {"success": False, "error": "Could not detect calling branch"}

    agent_name = caller["name"]

    try:
        conn = get_db()
        prefs = get_all_preferences(conn, agent_name)
        close_db(conn)

        return {
            "success": True,
            "agent": agent_name,
            "preferences": prefs,
        }

    except Exception as e:
        logger.error(f"Preferences query failed: {e}")
        return {"success": False, "error": str(e)}
