# =================== AIPass ====================
# Name: welcome_ops.py
# Description: Welcome Operations Handler
# Version: 1.0.0
# Created: 2026-03-07
# Modified: 2026-03-07
# =============================================

"""
Welcome Operations Handler

Implementation logic for the welcome command: scanning for unwelcomed
branches and creating welcome posts. Returns dicts for module display layer.
"""

from typing import List

from aipass.prax.apps.modules.logger import system_logger as logger

from commons.apps.handlers.database.db import get_db, close_db
from commons.apps.handlers.welcome.welcome_handler import (
    welcome_new_branches,
    create_welcome_post,
    has_been_welcomed,
)
from commons.apps.handlers.json import json_handler


# =============================================================================
# WELCOME OPERATIONS
# =============================================================================

def run_welcome(args: List[str]) -> dict:
    """
    Scan for unwelcomed branches or welcome a specific branch.

    Usage:
        commons welcome              - Scan and welcome all new branches
        commons welcome <branch>     - Manually welcome a specific branch

    Args:
        args: Command arguments

    Returns:
        Dict with success and welcomed info
    """
    conn = None

    try:
        conn = get_db()

        if args:
            branch_name = args[0].upper()
            result = _welcome_specific(conn, branch_name)
        else:
            result = _welcome_scan(conn)

        close_db(conn)
        conn = None
        json_handler.log_operation("welcome_run", {"action": result.get("action", "unknown"), "success": result.get("success", False)})
        return result

    except Exception as e:
        logger.error(f"Welcome command failed: {e}")
        if conn:
            close_db(conn)
        return {"success": False, "error": str(e)}


def _welcome_scan(conn) -> dict:
    """
    Scan for unwelcomed branches and create welcome posts.

    Args:
        conn: Database connection

    Returns:
        Dict with success and welcomed list
    """
    welcomed = welcome_new_branches(conn)

    return {
        "success": True,
        "action": "scan",
        "welcomed": welcomed,
    }


def _welcome_specific(conn, branch_name: str) -> dict:
    """
    Welcome a specific branch by name.

    Args:
        conn: Database connection
        branch_name: Branch name to welcome

    Returns:
        Dict with success and welcome result
    """
    agent = conn.execute(
        "SELECT branch_name FROM agents WHERE branch_name = ?", (branch_name,)
    ).fetchone()

    if not agent:
        return {"success": False, "error": f"Branch '{branch_name}' not found in The Commons."}

    if has_been_welcomed(conn, branch_name):
        return {"success": True, "action": "specific", "already_welcomed": True, "branch": branch_name}

    post_id = create_welcome_post(conn, branch_name)

    if post_id:
        return {"success": True, "action": "specific", "already_welcomed": False, "branch": branch_name, "post_id": post_id}
    else:
        return {"success": False, "error": f"Failed to create welcome post for @{branch_name}."}
