# =================== AIPass ====================
# Name: room_ops.py
# Description: Room management operations
# Version: 1.1.0
# Created: 2026-03-07
# Modified: 2026-10-17
# =============================================

"""
Room Operations Handler

All functions return dicts and never print directly.
"""

from typing import List

from aipass.prax.apps.modules.logger import system_logger as logger

from aipass.commons.apps.handlers.database.db import get_db, close_db
from aipass.commons.apps.modules.commons_identity import CallerLookupFailed, get_caller_branch
from aipass.commons.apps.handlers.json import json_handler


def create_room(args: List[str]) -> dict:
    """Create a new room in The Commons: args[0] is the name, the rest the description."""

    if not args:
        return {"success": False, "error": "Room name required. Usage: create_room <name> [description...]"}

    room_name = args[0].lower().strip()
    description = " ".join(args[1:]) if len(args) > 1 else ""

    if not room_name:
        return {"success": False, "error": "Room name cannot be empty"}

    try:
        caller = get_caller_branch()
    except CallerLookupFailed as exc:
        return {"success": False, "error": str(exc)}
    if not caller:
        return {
            "success": False,
            "error": ("Could not detect calling branch. Run from a branch directory or use drone routing."),
        }

    caller_name = caller.get("name", "UNKNOWN")

    try:
        conn = get_db()

        existing = conn.execute("SELECT name FROM rooms WHERE name = ?", (room_name,)).fetchone()

        if existing:
            close_db(conn)
            return {"success": False, "error": f"Room '{room_name}' already exists"}

        display_name = room_name.replace("-", " ").replace("_", " ").title()

        conn.execute(
            "INSERT INTO rooms (name, display_name, description, created_by) VALUES (?, ?, ?, ?)",
            (room_name, display_name, description, caller_name),
        )

        conn.execute(
            "INSERT OR IGNORE INTO subscriptions (agent_name, room_name) VALUES (?, ?)",
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


def list_rooms() -> dict:
    """List all non-hidden rooms in The Commons with member and post counts."""

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
    """Subscribe the calling agent to the room named in args[0]."""

    if not args:
        return {"success": False, "error": "Room name required. Usage: join_room <name>"}

    room_name = args[0].lower().strip()

    if not room_name:
        return {"success": False, "error": "Room name cannot be empty"}

    try:
        caller = get_caller_branch()
    except CallerLookupFailed as exc:
        return {"success": False, "error": str(exc)}
    if not caller:
        return {
            "success": False,
            "error": ("Could not detect calling branch. Run from a branch directory or use drone routing."),
        }

    caller_name = caller.get("name", "UNKNOWN")

    try:
        conn = get_db()

        room = conn.execute("SELECT name FROM rooms WHERE name = ?", (room_name,)).fetchone()

        if not room:
            close_db(conn)
            return {"success": False, "error": f"Room '{room_name}' does not exist"}

        existing = conn.execute(
            "SELECT agent_name FROM subscriptions WHERE agent_name = ? AND room_name = ?",
            (caller_name, room_name),
        ).fetchone()

        if existing:
            close_db(conn)
            return {"success": False, "error": f"{caller_name} is already a member of '{room_name}'"}

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


def leave_room(args: List[str]) -> dict:
    """Unsubscribe the calling agent from the room named in args[0]."""
    if not args:
        return {"success": False, "error": "Room name required. Usage: leave_room <name>"}

    room_name = args[0].lower().strip()

    if not room_name:
        return {"success": False, "error": "Room name cannot be empty"}

    try:
        caller = get_caller_branch()
    except CallerLookupFailed as exc:
        return {"success": False, "error": str(exc)}
    if not caller:
        return {
            "success": False,
            "error": ("Could not detect calling branch. Run from a branch directory or use drone routing."),
        }

    caller_name = caller.get("name", "UNKNOWN")

    try:
        conn = get_db()

        room = conn.execute("SELECT name FROM rooms WHERE name = ?", (room_name,)).fetchone()

        if not room:
            close_db(conn)
            return {"success": False, "error": f"Room '{room_name}' does not exist"}

        existing = conn.execute(
            "SELECT agent_name FROM subscriptions WHERE agent_name = ? AND room_name = ?",
            (caller_name, room_name),
        ).fetchone()

        if not existing:
            close_db(conn)
            return {
                "success": False,
                "error": f"{caller_name} is not a member of '{room_name}'",
            }

        conn.execute(
            "DELETE FROM subscriptions WHERE agent_name = ? AND room_name = ?",
            (caller_name, room_name),
        )
        conn.commit()
        close_db(conn)

        logger.info(f"[commons.rooms] {caller_name} left room '{room_name}'")

        return {
            "success": True,
            "room": room_name,
            "agent": caller_name,
        }

    except Exception as e:
        logger.error(f"[commons.rooms] Leave room failed: {e}")
        return {"success": False, "error": str(e)}
