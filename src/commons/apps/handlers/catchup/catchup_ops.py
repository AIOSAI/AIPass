# =================== AIPass ====================
# Name: catchup_ops.py
# Description: Catchup Operations Handler
# Version: 1.0.0
# Created: 2026-03-07
# Modified: 2026-03-07
# =============================================

"""
Catchup Operations Handler

Implementation logic for the catchup command: showing branches what
they missed since their last visit. Returns dicts for module display layer.
"""

from datetime import datetime, timezone, timedelta
from typing import List

from aipass.prax.apps.modules.logger import system_logger as logger

from commons.apps.handlers.database.db import get_db, close_db
from commons.apps.handlers.database.catchup_queries import (
    query_catchup_data,
    get_last_active,
    update_last_active,
)
from commons.apps.modules.commons_identity import get_caller_branch
from commons.apps.handlers.json import json_handler


# =============================================================================
# PRIVATE HELPERS
# =============================================================================

def _calculate_time_label(last_active: str) -> str:
    """
    Calculate a human-readable time label from a last_active timestamp.

    Args:
        last_active: ISO format timestamp string

    Returns:
        Human-readable time delta string
    """
    try:
        last_dt = datetime.strptime(last_active, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
        delta = datetime.now(timezone.utc) - last_dt
        hours = int(delta.total_seconds() / 3600)
        if hours < 1:
            minutes = int(delta.total_seconds() / 60)
            return f"{minutes} minutes ago"
        elif hours < 24:
            return f"{hours} hours ago"
        else:
            days = hours // 24
            return f"{days} days ago"
    except (ValueError, TypeError):
        return "your last visit"


# =============================================================================
# CATCHUP OPERATIONS
# =============================================================================

def run_catchup(args: List[str]) -> dict:
    """
    Show what the branch missed since last visit.

    Usage: commons catchup

    Args:
        args: Command arguments (currently unused)

    Returns:
        Dict with success, is_first_visit, time_label, data, nudge keys
    """
    caller = get_caller_branch()
    if not caller:
        return {"success": False, "error": "Could not detect calling branch. Run from a branch directory."}

    branch_name = caller["name"]
    conn = None

    try:
        conn = get_db()

        last_active = get_last_active(conn, branch_name)
        is_first_visit = last_active is None

        if is_first_visit:
            since_time = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
            time_label = "the last 24 hours"
        else:
            since_time = last_active
            time_label = _calculate_time_label(last_active)

        data = query_catchup_data(conn, branch_name, since_time)

        update_last_active(conn, branch_name)

        close_db(conn)
        conn = None

    except Exception as e:
        logger.error(f"Catchup query failed: {e}")
        if conn:
            close_db(conn)
        return {"success": False, "error": str(e)}

    # Onboarding nudge
    nudge = None
    try:
        from commons.apps.handlers.welcome.welcome_handler import get_onboarding_nudge
        conn_nudge = get_db()
        nudge = get_onboarding_nudge(conn_nudge, branch_name)
        close_db(conn_nudge)
    except Exception:
        pass

    json_handler.log_operation("catchup_run", {"branch": branch_name, "is_first_visit": is_first_visit})
    return {
        "success": True,
        "is_first_visit": is_first_visit,
        "time_label": time_label,
        "data": data,
        "nudge": nudge,
    }
