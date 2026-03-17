# =================== AIPass ====================
# Name: profile_ops.py
# Description: Profile Operations Handler
# Version: 1.0.0
# Created: 2026-03-07
# Modified: 2026-03-07
# =============================================

"""
Profile Operations Handler

Implementation logic for profile viewing/editing and member listing.
Returns dicts for module display layer.
"""

from typing import List

from aipass.prax.apps.modules.logger import system_logger as logger

from commons.apps.handlers.database.db import get_db, close_db
from commons.apps.handlers.profiles.profile_queries import (
    get_profile,
    update_bio,
    update_status,
    update_role,
    get_all_agents_brief,
    format_time_ago,
)
from commons.apps.modules.commons_identity import get_caller_branch
from commons.apps.handlers.json import json_handler


# =============================================================================
# PROFILE OPERATIONS
# =============================================================================

def show_profile(args: List[str]) -> dict:
    """
    View or edit social profiles.

    Usage:
        commons profile                      - Show your profile
        commons profile <branch_name>        - Show someone's profile
        commons profile set bio "text"       - Set your bio
        commons profile set status "text"    - Set your status
        commons profile set role "text"      - Set your role

    Args:
        args: Command arguments

    Returns:
        Dict with success and profile/update data
    """
    # Handle 'set' subcommand
    if len(args) >= 3 and args[0].lower() == "set":
        return _handle_profile_set(args)

    # Determine which branch to show
    if args:
        target_branch = args[0].upper()
    else:
        caller = get_caller_branch()
        if not caller:
            return {"success": False, "error": "Could not detect calling branch. Run from a branch directory."}
        target_branch = caller["name"]

    try:
        conn = get_db()
        profile = get_profile(conn, target_branch)
        close_db(conn)

        if not profile:
            return {"success": False, "error": f"Agent '{target_branch}' not found"}

        # Enrich with display values
        profile["last_active_display"] = format_time_ago(profile.get("last_active", "")) if profile.get("last_active") else "never"
        profile["joined_display"] = profile["joined_at"][:10] if profile.get("joined_at") else "unknown"

        json_handler.log_operation("view_profile", {"branch": target_branch})
        return {"success": True, "action": "view", "profile": profile}

    except Exception as e:
        logger.error(f"Profile fetch failed: {e}")
        return {"success": False, "error": str(e)}


def _handle_profile_set(args: List[str]) -> dict:
    """Handle profile set subcommand."""
    field = args[1].lower()
    value = args[2] if len(args) > 2 else ""

    valid_fields = ("bio", "status", "role")
    if field not in valid_fields:
        return {"success": False, "error": f"Unknown field '{field}'. Must be one of: {', '.join(valid_fields)}"}

    caller = get_caller_branch()
    if not caller:
        return {"success": False, "error": "Could not detect calling branch. Run from a branch directory."}

    branch_name = caller["name"]

    try:
        conn = get_db()
        update_fn = {"bio": update_bio, "status": update_status, "role": update_role}[field]
        success = update_fn(conn, branch_name, value)
        close_db(conn)

        if success:
            return {"success": True, "action": "set", "field": field, "branch": branch_name}
        else:
            return {"success": False, "error": f"Agent '{branch_name}' not found"}

    except Exception as e:
        logger.error(f"Profile update failed: {e}")
        return {"success": False, "error": str(e)}


def list_members(args: List[str]) -> dict:
    """
    List all agents with brief profile info.

    Usage: commons who

    Args:
        args: Command arguments (currently unused)

    Returns:
        Dict with success and agents list
    """
    try:
        conn = get_db()
        agents = get_all_agents_brief(conn)
        close_db(conn)

        return {"success": True, "agents": agents}

    except Exception as e:
        logger.error(f"Who listing failed: {e}")
        return {"success": False, "error": str(e)}
