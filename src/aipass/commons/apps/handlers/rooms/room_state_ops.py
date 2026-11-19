# =================== AIPass ====================
# Name: room_state_ops.py
# Description: Room State CRUD Handler
# Version: 1.0.1
# Created: 2026-03-07
# Modified: 2026-11-14
# =============================================

"""
Room State CRUD Handler
"""

import sqlite3
from typing import Dict, Optional

from aipass.commons.apps.handlers.json import json_handler


def set_room_state(conn: sqlite3.Connection, room_name: str, key: str, value: str) -> bool:
    """Upsert a room state key/value pair; True or raises."""
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


def get_room_state(conn: sqlite3.Connection, room_name: str, key: str) -> Optional[str]:
    """Get a specific state value for a room."""
    row = conn.execute(
        "SELECT value FROM room_state WHERE room_name = ? AND key = ?",
        (room_name, key),
    ).fetchone()
    return row["value"] if row else None


def get_all_room_state(conn: sqlite3.Connection, room_name: str) -> Dict[str, str]:
    """Get all state key/value pairs for a room."""
    rows = conn.execute(
        "SELECT key, value FROM room_state WHERE room_name = ? ORDER BY key",
        (room_name,),
    ).fetchall()
    return {row["key"]: row["value"] for row in rows}


def set_mood(conn: sqlite3.Connection, room_name: str, mood: str) -> bool:
    """Update a room's mood column."""
    conn.execute("UPDATE rooms SET mood = ? WHERE name = ?", (mood, room_name))
    conn.commit()
    return True


def set_flavor(conn: sqlite3.Connection, room_name: str, text: str) -> bool:
    """Update a room's flavor text."""
    conn.execute("UPDATE rooms SET flavor_text = ? WHERE name = ?", (text, room_name))
    conn.commit()
    return True


def set_entrance(conn: sqlite3.Connection, room_name: str, message: str) -> bool:
    """Update a room's entrance message."""
    conn.execute("UPDATE rooms SET entrance_message = ? WHERE name = ?", (message, room_name))
    conn.commit()
    return True
