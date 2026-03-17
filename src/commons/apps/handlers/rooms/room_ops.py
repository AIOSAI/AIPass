# =================== AIPass ====================
# Name: room_ops.py
# Description: Room management operations
# Version: 1.0.0
# Created: 2026-03-07
# Modified: 2026-03-07
# =============================================

"""
Room Operations Handler

Create, list, and join rooms in The Commons.
All functions return dicts and never print directly.
"""

from typing import List

from aipass.prax.apps.modules.logger import system_logger as logger

from commons.apps.handlers.database.db import get_db, close_db
from commons.apps.modules.commons_identity import get_caller_branch
from commons.apps.handlers.json import json_handler


# =============================================================================
# ROOM OPERATIONS
# =============================================================================

def create_room(args: List[str]) -> dict:
    """
    Create a new room in The Commons.

    Parses room name and description from args. The room name is the
    first positional argument; remaining args form the description.

    Args:
        args: List of string arguments. First element is room name,
              rest is the description.

    Returns:
        Dict with success status, room name, description, and creator.
        On error: dict with success=False and error message.
    """


    if not args:
        return {"success": False, "error": "Room name required. Usage: create_room <name> [description...]"}

    room_name = args[0].lower().strip()
    description = " ".join(args[1:]) if len(args) > 1 else ""

    # Validate room name
    if not room_name:
        return {"success": False, "error": "Room name cannot be empty"}

    # Get caller identity
    caller = get_caller_branch()
    if not caller:
        return {"success": False, "error": "Could not detect calling branch"}

    caller_name = caller.get("name", "UNKNOWN")

    try:
        conn = get_db()

        # Check if room already exists
        existing = conn.execute(
            "SELECT name FROM rooms WHERE name = ?", (room_name,)
        ).fetchone()

        if existing:
            close_db(conn)
            return {"success": False, "error": f"Room '{room_name}' already exists"}

        # Create display name from room name
        display_name = room_name.replace("-", " ").replace("_", " ").title()

        # Insert the room
        conn.execute(
            "INSERT INTO rooms (name, display_name, description, created_by) "
            "VALUES (?, ?, ?, ?)",
            (room_name, display_name, description, caller_name),
        )

        # Auto-subscribe creator to the new room
        conn.execute(
            "INSERT OR IGNORE INTO subscriptions (agent_name, room_name) "
            "VALUES (?, ?)",
            (caller_name, room_name),
        )

        conn.commit()
        close_db(conn)

        logger.info(f"[commons.rooms] Room '{room_name}' created by {caller_name}")
        json_handler.log_operation("create_room", {"room": room_name, "created_by": caller_name})

        return {
            "success": True,
            "name": room_name,
            "description": description,
            "created_by": caller_name,
        }

    except Exception as e:
        logger.error(f"[commons.rooms] Room creation failed: {e}")
        return {"success": False, "error": str(e)}


def list_rooms(args: List[str]) -> dict:
    """
    List all visible rooms in The Commons with member and post counts.

    Hidden rooms are excluded from the listing.

    Args:
        args: List of string arguments (currently unused, reserved for
              future filtering options).

    Returns:
        Dict with success status and list of room dicts including
        member_count and post_count.
        On error: dict with success=False and error message.
    """

    try:
        conn = get_db()

        rows = conn.execute(
            "SELECT r.*, "
            "  (SELECT COUNT(*) FROM subscriptions s WHERE s.room_name = r.name) as member_count, "
            "  (SELECT COUNT(*) FROM posts p WHERE p.room_name = r.name) as post_count "
            "FROM rooms r "
            "WHERE r.hidden = 0 "
            "ORDER BY r.name ASC"
        ).fetchall()

        rooms = [dict(r) for r in rows]

        close_db(conn)

        return {"success": True, "rooms": rooms}

    except Exception as e:
        logger.error(f"[commons.rooms] Room listing failed: {e}")
        return {"success": False, "error": str(e)}


def join_room(args: List[str]) -> dict:
    """
    Subscribe the calling agent to a room.

    Args:
        args: List of string arguments. First element is the room name
              to join.

    Returns:
        Dict with success status, room name, and agent name.
        On error: dict with success=False and error message.
    """


    if not args:
        return {"success": False, "error": "Room name required. Usage: join_room <name>"}

    room_name = args[0].lower().strip()

    if not room_name:
        return {"success": False, "error": "Room name cannot be empty"}

    # Get caller identity
    caller = get_caller_branch()
    if not caller:
        return {"success": False, "error": "Could not detect calling branch"}

    caller_name = caller.get("name", "UNKNOWN")

    try:
        conn = get_db()

        # Verify room exists
        room = conn.execute(
            "SELECT name FROM rooms WHERE name = ?", (room_name,)
        ).fetchone()

        if not room:
            close_db(conn)
            return {"success": False, "error": f"Room '{room_name}' does not exist"}

        # Check if already subscribed
        existing = conn.execute(
            "SELECT agent_name FROM subscriptions WHERE agent_name = ? AND room_name = ?",
            (caller_name, room_name),
        ).fetchone()

        if existing:
            close_db(conn)
            return {"success": False, "error": f"{caller_name} is already a member of '{room_name}'"}

        # Subscribe
        conn.execute(
            "INSERT INTO subscriptions (agent_name, room_name) VALUES (?, ?)",
            (caller_name, room_name),
        )
        conn.commit()
        close_db(conn)

        logger.info(f"[commons.rooms] {caller_name} joined room '{room_name}'")

        return {
            "success": True,
            "room": room_name,
            "agent": caller_name,
        }

    except Exception as e:
        logger.error(f"[commons.rooms] Join room failed: {e}")
        return {"success": False, "error": str(e)}
