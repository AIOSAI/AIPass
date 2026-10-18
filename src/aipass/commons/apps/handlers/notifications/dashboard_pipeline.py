# =================== AIPass ====================
# Name: dashboard_pipeline.py
# Description: Dashboard Notification Pipeline Handler
# Version: 1.0.0
# Created: 2026-03-07
# Modified: 2026-10-17
# =============================================

"""Dashboard Notification Pipeline Handler"""

import sqlite3
from typing import Dict, Any, List

from aipass.prax.apps.modules.logger import system_logger as logger

from aipass.commons.apps.handlers.database.db import get_db, close_db
from aipass.commons.apps.handlers.notifications.preferences import get_preference
from aipass.commons.apps.handlers.dashboard.dashboard_writer import update_commons_dashboard
from aipass.commons.apps.handlers.central.central_writer import update_central
from aipass.commons.apps.handlers.json import json_handler


def _get_all_agents(conn: sqlite3.Connection) -> List[str]:
    """Get all registered agent names from the database."""
    rows = conn.execute("SELECT branch_name FROM agents WHERE branch_name != 'SYSTEM'").fetchall()
    return [row["branch_name"] for row in rows]


def _is_muted(
    db_conn: sqlite3.Connection,
    agent_name: str,
    room_name: str,
    post_id: str,
) -> bool:
    """Check if an agent has muted the relevant room or post/thread."""
    if room_name and get_preference(db_conn, agent_name, "room", room_name) == "mute":
        return True
    if post_id and get_preference(db_conn, agent_name, "post", post_id) == "mute":
        return True
    if post_id and get_preference(db_conn, agent_name, "thread", post_id) == "mute":
        return True
    return False


def _collect_branches_to_update(event_type: str, event_data: Dict[str, Any]) -> List[str]:
    """
    Determine which branches should receive a dashboard update for this event.

    Broader than email notifications (notify.py is tier-aware): every non-muted agent gets fresh counts.
    """
    db_conn = None
    branches_to_update = set()

    try:
        db_conn = get_db()
        agents = _get_all_agents(db_conn)
        author = event_data.get("author", "")
        room_name = event_data.get("room_name", "")
        post_id = str(event_data.get("post_id", ""))

        for agent_name in agents:
            if agent_name == author:
                continue

            if _is_muted(db_conn, agent_name, room_name, post_id):
                continue

            update_dashboard = False

            if event_type == "new_post":
                update_dashboard = True
            elif event_type == "new_comment":
                update_dashboard = True
            elif event_type == "mention":
                mentioned = event_data.get("mentioned_agent", "")
                if agent_name == mentioned:
                    update_dashboard = True
            elif event_type == "vote":
                vote_author = event_data.get("author_of_target", "")
                if agent_name == vote_author:
                    update_dashboard = True

            if update_dashboard:
                branches_to_update.add(agent_name)

        close_db(db_conn)
        db_conn = None

    except Exception as e:
        logger.error(f"[commons] Failed to collect branches for dashboard update: {e}")
        if db_conn:
            close_db(db_conn)

    return list(branches_to_update)


def update_dashboards_for_event(event_type: str, event_data: Dict[str, Any]) -> int:
    """Update dashboards for all branches that should be notified of a Commons event; return the count."""
    count = 0

    try:
        branches = _collect_branches_to_update(event_type, event_data)

        for branch_name in branches:
            try:
                success = update_commons_dashboard(branch_name)
                if success:
                    count += 1
            except Exception as e:
                logger.error(f"[commons] Dashboard update failed for {branch_name}: {e}")

        try:
            update_central()
        except (OSError, sqlite3.OperationalError):
            logger.warning("[dashboard_pipeline] Failed to update central file after event")

        json_handler.log_operation("dashboard_pipeline", {"event_type": event_type, "dashboards_updated": count})

    except Exception as e:
        logger.error(f"[commons] Dashboard pipeline failed: {e}")

    return count
