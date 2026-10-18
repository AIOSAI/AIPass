# =================== AIPass ====================
# Name: welcome_ops.py
# Description: Welcome Operations Handler
# Version: 1.1.0
# Created: 2026-03-07
# Modified: 2026-10-17
# =============================================

"""
Welcome Operations Handler

Returns dicts for the module display layer; never prints.
"""

import sqlite3
from typing import List

from aipass.prax.apps.modules.logger import system_logger as logger

from aipass.commons.apps.handlers.database.db import get_db, close_db
from aipass.commons.apps.handlers.welcome.welcome_handler import (
    welcome_new_branches,
    create_welcome_post,
    has_been_welcomed,
)
from aipass.commons.apps.handlers.json import json_handler


def run_welcome(args: List[str]) -> dict:
    """Scan for unwelcomed branches, or welcome the one branch named in args."""
    conn = None

    dry_run = "--dry-run" in args
    filtered_args = [a for a in args if a != "--dry-run"]

    try:
        conn = get_db()

        if filtered_args:
            branch_name = filtered_args[0].lower()
            if dry_run:
                already = has_been_welcomed(conn, branch_name)
                close_db(conn)
                return {"success": True, "dry_run": True, "branch": branch_name, "would_welcome": not already}
            result = _welcome_specific(conn, branch_name)
        else:
            if dry_run:
                rows = conn.execute("SELECT branch_name FROM agents WHERE branch_name != 'SYSTEM'").fetchall()
                unwelcomed = [r["branch_name"] for r in rows if not has_been_welcomed(conn, r["branch_name"])]
                close_db(conn)
                return {"success": True, "dry_run": True, "would_welcome": unwelcomed}
            result = _welcome_scan(conn)

        close_db(conn)
        conn = None
        json_handler.log_operation(
            "welcome_run", {"action": result.get("action", "unknown"), "success": result.get("success", False)}
        )
        return result

    except Exception as e:
        logger.error(f"[welcome_ops] Welcome command failed: {e}")
        if conn:
            close_db(conn)
        return {"success": False, "error": str(e)}


def _welcome_scan(conn) -> dict:
    """
    Scan for unwelcomed branches and create welcome posts.

    Any failed branch makes the answer success False (the command refuses, exit 2), while the
    welcomed list stays in it so the partial work is still reported.
    """
    failed: List[str] = []
    welcomed = welcome_new_branches(conn, failed)

    if failed:
        names = ", ".join(f"@{name}" for name in failed)
        done = ", ".join(f"@{name}" for name in welcomed) or "none"
        return {
            "success": False,
            "action": "scan",
            "partial": True,
            "welcomed": welcomed,
            "failed": failed,
            "error": f"Welcome scan partial: database error welcoming {names} (see log). Welcomed: {done}.",
        }

    return {
        "success": True,
        "action": "scan",
        "welcomed": welcomed,
        "failed": failed,
    }


def _welcome_specific(conn, branch_name: str) -> dict:
    """Welcome a specific branch by name."""
    agent = conn.execute("SELECT branch_name FROM agents WHERE LOWER(branch_name) = ?", (branch_name,)).fetchone()

    if not agent:
        return {"success": False, "error": f"Branch '{branch_name}' not found in The Commons."}

    if has_been_welcomed(conn, branch_name):
        return {"success": True, "action": "specific", "already_welcomed": True, "branch": branch_name}

    try:
        post_id = create_welcome_post(conn, branch_name)
    except sqlite3.Error as e:
        logger.error(f"[welcome_ops] Welcome post for @{branch_name} failed: {e}")
        return {"success": False, "error": f"Failed to create welcome post for @{branch_name}: database error: {e}"}

    if post_id:
        return {
            "success": True,
            "action": "specific",
            "already_welcomed": False,
            "branch": branch_name,
            "post_id": post_id,
        }
    else:
        return {"success": False, "error": f"Failed to create welcome post for @{branch_name}."}
