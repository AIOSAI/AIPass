# =================== AIPass ====================
# Name: capsule_ops.py
# Description: Time Capsule Operations Handler
# Version: 1.0.0
# Created: 2026-03-07
# Modified: 2026-03-07
# =============================================

"""
Time Capsule Operations Handler

Implementation logic for sealing, listing, and opening time capsules.
Time capsules are sealed messages that can't be opened until a specified date.
Returns dicts for module display layer.
"""

from typing import List
from datetime import datetime, timezone, timedelta

from aipass.prax.apps.modules.logger import system_logger as logger

from commons.apps.handlers.database.db import get_db, close_db
from commons.apps.handlers.json import json_handler


# =============================================================================
# SEAL A TIME CAPSULE
# =============================================================================

def seal_capsule(args: List[str]) -> dict:
    """
    Seal a time capsule that opens after N days.

    Usage: commons capsule "title" "content" <days>

    Returns:
        Dict with success, capsule_id, title, creator, days, opens_at
    """
    if len(args) < 3:
        return {"success": False, "error": 'Usage: commons capsule "title" "content" <days>'}

    title = args[0]
    content = args[1]

    try:
        days = int(args[2])
    except ValueError:
        return {"success": False, "error": "Days must be a number"}

    days = max(1, min(365, days))

    from commons.apps.modules.commons_identity import get_caller_branch
    caller = get_caller_branch()
    if not caller:
        return {"success": False, "error": "Could not detect calling branch. Run from a branch directory."}

    creator = caller["name"]

    now = datetime.now(timezone.utc)
    opens_at = (now + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")

    try:
        conn = get_db()

        cursor = conn.execute(
            "INSERT INTO time_capsules (creator, title, content, opens_at) "
            "VALUES (?, ?, ?, ?)",
            (creator, title, content, opens_at),
        )
        capsule_id = cursor.lastrowid
        conn.commit()
        close_db(conn)
        json_handler.log_operation("seal_capsule", {"capsule_id": capsule_id, "creator": creator, "days": days})

        return {
            "success": True,
            "capsule_id": capsule_id,
            "title": title,
            "creator": creator,
            "days": days,
            "opens_at": opens_at,
        }

    except Exception as e:
        logger.error(f"Seal capsule failed: {e}")
        return {"success": False, "error": str(e)}


# =============================================================================
# LIST TIME CAPSULES
# =============================================================================

def list_capsules(args: List[str]) -> dict:
    """
    List all time capsules with status info.

    Usage: commons capsules

    Returns:
        Dict with success, capsules list
    """
    try:
        conn = get_db()

        rows = conn.execute(
            "SELECT * FROM time_capsules ORDER BY opens_at ASC"
        ).fetchall()

        close_db(conn)

    except Exception as e:
        logger.error(f"List capsules failed: {e}")
        return {"success": False, "error": str(e)}

    now = datetime.now(timezone.utc)
    capsules = []

    for row in rows:
        capsule = dict(row)
        opens_dt = datetime.strptime(capsule["opens_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)

        if capsule["opened"]:
            capsule["_status"] = "opened"
            capsule["_status_text"] = f"Opened by {capsule['opened_by']}"
        elif now >= opens_dt:
            capsule["_status"] = "ready"
            capsule["_status_text"] = "Ready to open!"
        else:
            delta = opens_dt - now
            days_left = delta.days
            hours_left = delta.seconds // 3600
            capsule["_status"] = "sealed"
            if days_left > 0:
                capsule["_status_text"] = f"Sealed ({days_left}d {hours_left}h remaining)"
            else:
                capsule["_status_text"] = f"Sealed ({hours_left}h remaining)"

        capsules.append(capsule)

    return {"success": True, "capsules": capsules}


# =============================================================================
# OPEN A TIME CAPSULE
# =============================================================================

def open_capsule(args: List[str]) -> dict:
    """
    Open a time capsule if its opens_at date has passed.

    Usage: commons open <capsule_id>

    Returns:
        Dict with success, capsule data, opener, already_opened flag
    """
    if not args:
        return {"success": False, "error": "Usage: commons open <capsule_id>"}

    try:
        capsule_id = int(args[0])
    except ValueError:
        return {"success": False, "error": "Capsule ID must be a number"}

    from commons.apps.modules.commons_identity import get_caller_branch
    caller = get_caller_branch()
    if not caller:
        return {"success": False, "error": "Could not detect calling branch. Run from a branch directory."}

    opener = caller["name"]

    try:
        conn = get_db()

        row = conn.execute(
            "SELECT * FROM time_capsules WHERE id = ?", (capsule_id,)
        ).fetchone()

        if not row:
            close_db(conn)
            return {"success": False, "error": f"Time capsule {capsule_id} not found"}

        capsule = dict(row)

        if capsule["opened"]:
            close_db(conn)
            return {
                "success": True,
                "already_opened": True,
                "capsule": capsule,
            }

        now = datetime.now(timezone.utc)
        opens_dt = datetime.strptime(capsule["opens_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)

        if now < opens_dt:
            delta = opens_dt - now
            days_left = delta.days
            hours_left = delta.seconds // 3600
            close_db(conn)
            return {"success": False, "error": f"This capsule is still sealed. Opens in {days_left}d {hours_left}h."}

        conn.execute(
            "UPDATE time_capsules SET opened = 1, opened_by = ? WHERE id = ?",
            (opener, capsule_id),
        )
        conn.commit()
        close_db(conn)

        return {
            "success": True,
            "already_opened": False,
            "capsule": capsule,
            "opener": opener,
        }

    except Exception as e:
        logger.error(f"Open capsule failed: {e}")
        return {"success": False, "error": str(e)}
