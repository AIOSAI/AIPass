# =================== AIPass ====================
# Name: room_state_ops.py
# Description: Room State CRUD Handler
# Version: 1.0.0
# Created: 2026-03-07
# Modified: 2026-10-17
# =============================================

"""
Room State CRUD Handler
"""

import sqlite3
from typing import Dict, Optional

from aipass.prax.apps.modules.logger import system_logger as logger

from aipass.commons.apps.handlers.json import json_handler


def set_room_state(conn: sqlite3.Connection, room_name: str, key: str, value: str) -> bool:
    """Upsert a room state key/value pair."""
    try:
        conn.execute(
            "INSERT INTO room_state (room_name, key, value, updated_at) "
            "VALUES (?, ?, ?, strftime('%Y-%m-%dT%H:%M:%SZ', 'now')) "
            "ON CONFLICT(room_name, key) DO UPDATE SET "
            "value = excluded.value, updated_at = excluded.updated_at",
            (room_name, key, value),
        )
        conn.commit()
        json_handler.log_operation("set_room_state", {"room": room_name, "key": key})
        return True
    except Exception:
        logger.error(f"[room_state_ops] Failed to set state key '{key}' for room '{room_name}'")
        return False


def get_room_state(conn: sqlite3.Connection, room_name: str, key: str) -> Optional[str]:
    """Get a specific state value for a room."""
    try:
        row = conn.execute(
            "SELECT value FROM room_state WHERE room_name = ? AND key = ?",
            (room_name, key),
        ).fetchone()
        return row["value"] if row else None
    except Exception:
        logger.error(f"[room_state_ops] Failed to get state key '{key}' for room '{room_name}'")
        return None


def get_all_room_state(conn: sqlite3.Connection, room_name: str) -> Dict[str, str]:
    """Get all state key/value pairs for a room."""
    try:
        rows = conn.execute(
            "SELECT key, value FROM room_state WHERE room_name = ? ORDER BY key",
            (room_name,),
        ).fetchall()
        return {row["key"]: row["value"] for row in rows}
    except Exception:
        logger.error(f"[room_state_ops] Failed to get all state for room '{room_name}'")
        return {}


def set_mood(conn: sqlite3.Connection, room_name: str, mood: str) -> bool:
    """Update a room's mood column."""
    try:
        conn.execute("UPDATE rooms SET mood = ? WHERE name = ?", (mood, room_name))
        conn.commit()
        return True
    except Exception:
        logger.error(f"[room_state_ops] Failed to set mood for room '{room_name}'")
        return False


def set_flavor(conn: sqlite3.Connection, room_name: str, text: str) -> bool:
    """Update a room's flavor text."""
    try:
        conn.execute("UPDATE rooms SET flavor_text = ? WHERE name = ?", (text, room_name))
        conn.commit()
        return True
    except Exception:
        logger.error(f"[room_state_ops] Failed to set flavor text for room '{room_name}'")
        return False


def set_entrance(conn: sqlite3.Connection, room_name: str, message: str) -> bool:
    """Update a room's entrance message."""
    try:
        conn.execute("UPDATE rooms SET entrance_message = ? WHERE name = ?", (message, room_name))
        conn.commit()
        return True
    except Exception:
        logger.error(f"[room_state_ops] Failed to set entrance message for room '{room_name}'")
        return False
