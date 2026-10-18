# =================== AIPass ====================
# Name: preferences.py
# Description: Notification Preferences Handler
# Version: 1.1.0
# Created: 2026-03-07
# Modified: 2026-10-17
# =============================================

"""
Notification Preferences Handler
"""

import sqlite3
from typing import Optional, List, Dict, Any

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.commons.apps.handlers.json import json_handler


def get_preference(conn: sqlite3.Connection, agent_name: str, target_type: str, target_id: str) -> Optional[str]:
    """Get an agent's preference level on a target; None means the default, 'track'."""
    row = conn.execute(
        "SELECT level FROM notification_preferences WHERE agent_name = ? AND target_type = ? AND target_id = ?",
        (agent_name, target_type, target_id),
    ).fetchone()

    if row:
        return row["level"]
    return None


def set_preference(
    conn: sqlite3.Connection,
    agent_name: str,
    target_type: str,
    target_id: str,
    level: str,
) -> bool:
    """Set a preference; False only for an invalid type or level, a failed write raises."""
    valid_types = ("room", "post", "thread")
    valid_levels = ("watch", "track", "mute")

    if target_type not in valid_types:
        logger.warning(f"Invalid target_type: {target_type}")
        return False

    if level not in valid_levels:
        logger.warning(f"Invalid level: {level}")
        return False

    try:
        conn.execute(
            "INSERT OR REPLACE INTO notification_preferences "
            "(agent_name, target_type, target_id, level) VALUES (?, ?, ?, ?)",
            (agent_name, target_type, target_id, level),
        )
        conn.commit()
        json_handler.log_operation("set_preference", {"agent": agent_name, "target_type": target_type, "level": level})
        return True
    except Exception as e:
        logger.error(f"[preferences] Failed to set preference: {e}")
        raise


def get_all_preferences(conn: sqlite3.Connection, agent_name: str) -> List[Dict[str, Any]]:
    """Get all notification preferences for an agent."""
    rows = conn.execute(
        "SELECT target_type, target_id, level, created_at "
        "FROM notification_preferences WHERE agent_name = ? "
        "ORDER BY target_type, target_id",
        (agent_name,),
    ).fetchall()

    return [dict(r) for r in rows]


def should_notify(
    conn: sqlite3.Connection,
    agent_name: str,
    target_type: str,
    target_id: str,
    event_type: str,
) -> bool:
    """Determine whether an agent should be notified for an event on a target."""
    level = get_preference(conn, agent_name, target_type, target_id)

    if level is None:
        level = "track"

    if level == "mute":
        return False
    elif level == "watch":
        return True
    else:
        return event_type in ("mention", "reply")


def get_watchers(conn: sqlite3.Connection, target_type: str, target_id: str) -> List[str]:
    """Get all agent names that are watching a specific target."""
    rows = conn.execute(
        "SELECT agent_name FROM notification_preferences WHERE target_type = ? AND target_id = ? AND level = 'watch'",
        (target_type, target_id),
    ).fetchall()

    return [row["agent_name"] for row in rows]
