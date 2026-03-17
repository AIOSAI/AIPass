# =================== AIPass ====================
# Name: dashboard_pipeline.py
# Description: Dashboard Notification Pipeline Handler
# Version: 1.0.0
# Created: 2026-03-07
# Modified: 2026-03-07
# =============================================

"""
Dashboard Notification Pipeline Handler

Updates OTHER branches' dashboards when Commons events happen.
Uses notification preferences to determine who gets updated,
then queries the SQLite database for real activity counts.

For each branch that should be notified (based on preferences):
- Queries the Commons DB for unread mentions, new posts, new comments
- Writes the real counts to their DASHBOARD.local.json via devpulse write_section()

Usage:
    from commons.apps.handlers.notifications.dashboard_pipeline import (
        update_dashboards_for_event
    )

    update_dashboards_for_event('new_post', {
        'room_name': 'general',
        'author': 'SEED',
        'post_id': 42,
        'title': 'Hello World',
    })
"""

import sqlite3
from typing import Dict, Any, List

from aipass.prax.apps.modules.logger import system_logger as logger

from commons.apps.handlers.database.db import get_db, close_db
from commons.apps.handlers.notifications.preferences import get_preference
from commons.apps.handlers.dashboard.dashboard_writer import update_commons_dashboard
from commons.apps.handlers.central.central_writer import update_central
from commons.apps.handlers.json import json_handler


def _get_all_agents(conn: sqlite3.Connection) -> List[str]:
    """
    Get all registered agent names from the database.

    Args:
        conn: Database connection

    Returns:
        List of agent branch names
    """
    rows = conn.execute(
        "SELECT branch_name FROM agents WHERE branch_name != 'SYSTEM'"
    ).fetchall()
    return [row["branch_name"] for row in rows]


def _is_muted(
    db_conn: sqlite3.Connection,
    agent_name: str,
    room_name: str,
    post_id: str,
) -> bool:
    """
    Check if an agent has muted the relevant room or post/thread.

    Args:
        db_conn: Database connection
        agent_name: The agent/branch name to check
        room_name: Room name (may be empty)
        post_id: Post ID as string (may be empty)

    Returns:
        True if the agent has muted the room or post/thread
    """
    if room_name and get_preference(db_conn, agent_name, "room", room_name) == "mute":
        return True
    if post_id and get_preference(db_conn, agent_name, "post", post_id) == "mute":
        return True
    if post_id and get_preference(db_conn, agent_name, "thread", post_id) == "mute":
        return True
    return False


def _collect_branches_to_update(
    event_type: str, event_data: Dict[str, Any]
) -> List[str]:
    """
    Determine which branches should receive a dashboard update for this event.

    Dashboard updates are BROAD: all non-muted agents get their dashboard
    refreshed so they see accurate counts. This is separate from email
    notifications (handled by notify.py with tier-aware logic).

    Args:
        event_type: Type of event ('new_post', 'new_comment', 'mention', 'vote')
        event_data: Dict with event details

    Returns:
        List of branch names that should receive dashboard updates
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


def update_dashboards_for_event(
    event_type: str, event_data: Dict[str, Any]
) -> int:
    """
    Update dashboards for all branches that should be notified of a Commons event.

    Determines which branches to notify based on preferences, then calls
    update_commons_dashboard() for each one.

    Args:
        event_type: Type of event - one of 'new_post', 'new_comment', 'mention', 'vote'
        event_data: Dict with event details. Expected keys vary by event_type:
            - new_post: room_name, author, post_id, title
            - new_comment: room_name, author, post_id, comment_id, post_author
            - mention: mentioned_agent, mentioner_agent, post_id
            - vote: target_type, target_id, voter, author

    Returns:
        Number of dashboards updated
    """
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
            pass

        json_handler.log_operation("dashboard_pipeline", {"event_type": event_type, "dashboards_updated": count})

    except Exception as e:
        logger.error(f"[commons] Dashboard pipeline failed: {e}")

    return count
