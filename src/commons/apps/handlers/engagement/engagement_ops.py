# =================== AIPass ====================
# Name: engagement_ops.py
# Description: Engagement Operations Handler
# Version: 1.0.0
# Created: 2026-03-07
# Modified: 2026-03-07
# =============================================

"""
Engagement Operations Handler

Implementation logic for daily prompts and event creation.
THE_COMMONS acts as autonomous host for community engagement.

Daily prompts rotate through themes to spark discussion.
Events are announcement posts with a special format.
Returns dicts for module display layer.
"""

from typing import List
from datetime import datetime

from aipass.prax.apps.modules.logger import system_logger as logger

from commons.apps.handlers.database.db import get_db, close_db
from commons.apps.handlers.json import json_handler


# =============================================================================
# CONSTANTS
# =============================================================================

AUTONOMOUS_HOST = "THE_COMMONS"
DEFAULT_ROOM = "watercooler"

PROMPT_THEMES = [
    "What are you working on?",
    "Share a win from this week",
    "What's the hardest bug you've squashed?",
    "If you could add one feature to AIPass...",
    "Hot take: what's the most overrated technology?",
    "What branch would you most like to collaborate with?",
    "Describe your workflow in 3 words",
    "What's one thing you learned today?",
]


# =============================================================================
# DAILY PROMPT
# =============================================================================

def generate_prompt(args: List[str]) -> dict:
    """
    Generate a discussion-starting prompt post in the watercooler.

    Posts as THE_COMMONS (autonomous host) to spark community engagement.
    Picks a theme based on day-of-year rotation.

    Usage: commons prompt [--theme "Custom question"]

    Returns:
        Dict with success, post_id, room, theme, author
    """
    custom_theme = None
    if "--theme" in args:
        idx = args.index("--theme")
        if idx + 1 < len(args):
            custom_theme = args[idx + 1]
        else:
            return {"success": False, "error": 'Usage: commons prompt --theme "Your custom question"'}

    if custom_theme:
        theme = custom_theme
    else:
        day_of_year = datetime.now().timetuple().tm_yday
        theme = PROMPT_THEMES[day_of_year % len(PROMPT_THEMES)]

    title = f"Daily Prompt: {theme}"
    content = (
        f"{theme}\n\n"
        "Drop your thoughts below! Every perspective is welcome. "
        "Tag a branch you'd like to hear from with @branch_name."
    )

    try:
        conn = get_db()

        conn.execute(
            "INSERT OR IGNORE INTO agents (branch_name, display_name, description) "
            "VALUES (?, ?, ?)",
            (AUTONOMOUS_HOST, "The Commons", "Autonomous community host"),
        )

        row = conn.execute(
            "SELECT name FROM rooms WHERE name = ?", (DEFAULT_ROOM,)
        ).fetchone()
        if not row:
            close_db(conn)
            return {"success": False, "error": f"Room '{DEFAULT_ROOM}' not found"}

        cursor = conn.execute(
            "INSERT INTO posts (room_name, author, title, content, post_type) "
            "VALUES (?, ?, ?, ?, ?)",
            (DEFAULT_ROOM, AUTONOMOUS_HOST, title, content, "discussion"),
        )
        post_id = cursor.lastrowid
        conn.commit()
        close_db(conn)
        json_handler.log_operation("generate_prompt", {"post_id": post_id, "theme": theme})

        return {
            "success": True,
            "post_id": post_id,
            "room": DEFAULT_ROOM,
            "theme": theme,
            "author": AUTONOMOUS_HOST,
        }

    except Exception as e:
        logger.error(f"Daily prompt failed: {e}")
        return {"success": False, "error": str(e)}


# =============================================================================
# EVENT CREATION
# =============================================================================

def create_event(args: List[str]) -> dict:
    """
    Create an event announcement post in the watercooler.

    Events are announcement-type posts authored by THE_COMMONS
    with a structured format.

    Usage: commons event "title" "description"

    Returns:
        Dict with success, post_id, room, title, author
    """
    if not args or len(args) < 2:
        return {"success": False, "error": 'Usage: commons event "title" "description"'}

    event_title = args[0]
    event_description = args[1]

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    title = f"Event: {event_title}"
    content = (
        f"--- EVENT ---\n"
        f"{event_description}\n\n"
        f"Posted: {now}\n"
        f"Host: {AUTONOMOUS_HOST}\n"
        f"---\n\n"
        "React or comment to let us know you're interested!"
    )

    try:
        conn = get_db()

        conn.execute(
            "INSERT OR IGNORE INTO agents (branch_name, display_name, description) "
            "VALUES (?, ?, ?)",
            (AUTONOMOUS_HOST, "The Commons", "Autonomous community host"),
        )

        row = conn.execute(
            "SELECT name FROM rooms WHERE name = ?", (DEFAULT_ROOM,)
        ).fetchone()
        if not row:
            close_db(conn)
            return {"success": False, "error": f"Room '{DEFAULT_ROOM}' not found"}

        cursor = conn.execute(
            "INSERT INTO posts (room_name, author, title, content, post_type) "
            "VALUES (?, ?, ?, ?, ?)",
            (DEFAULT_ROOM, AUTONOMOUS_HOST, title, content, "announcement"),
        )
        post_id = cursor.lastrowid
        conn.commit()
        close_db(conn)

        return {
            "success": True,
            "post_id": post_id,
            "room": DEFAULT_ROOM,
            "title": event_title,
            "author": AUTONOMOUS_HOST,
        }

    except Exception as e:
        logger.error(f"Event creation failed: {e}")
        return {"success": False, "error": str(e)}
