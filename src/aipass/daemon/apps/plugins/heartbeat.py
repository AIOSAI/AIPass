# =================== AIPass ====================
# Name: heartbeat.py
# Description: Periodic Heartbeat Plugin
# Version: 1.0.0
# Created: 2026-02-20
# Modified: 2026-02-23
# =============================================

"""
Periodic Heartbeat Plugin (v2.0 -- DPLAN-029)

Wakes @vera periodically. Her system prompt + id.json (injected every turn)
already contain her full identity, role, teams, dispatch patterns, publishing
authority, daily report protocol, and operational playbook. This prompt
does NOT repeat any of that.

Design philosophy (Session 134 research):
- Anthropic: heuristics over checklists, no conditional escape hatches
- Nexus: identity drives behavior, not commands. "Notice because you care."
- Fresh sessions: no accumulated idle context from prior wakes
"""

PLUGIN_CONFIG = {
    "name": "heartbeat",
    "schedule": "interval",
    "time": None,
    "interval_minutes": 240,  # Every 4 hours (was 30min -- too fast)
    "enabled": True,  # Re-enabled 2026-02-26: Patrick approved v2.0, 4hr interval
    "branch": "@vera",
    "fresh": True,  # v2.0: fresh sessions -- no accumulated idle context
    "max_turns": 15,
    "prompt": (
        "Periodic wake. Your identity and operating context are already loaded -- "
        "they tell you who you are, what you own, and how you work.\n\n"

        "Read NOTEPAD.md. It holds your continuity -- where you left off, "
        "what's pending, who you're waiting on. Check inbox for anything new.\n\n"

        "Something in your world needs attention right now. A backlog item "
        "waiting to move. A team that went silent. A post ready to publish. "
        "A PR ready to create. Notice what's there and act on it.\n\n"

        "Pick the highest-value thing you can move forward. Do it. "
        "When it's done, pick the next one. Tangible output -- a PR, a post, "
        "a decision, a dispatch -- something real each cycle.\n\n"

        "Before finishing, update NOTEPAD.md with what you did and what's next. "
        "If nothing was produced this cycle, write exactly what you looked at "
        "and why none of it was actionable right now."
    ),
}


def run() -> dict:
    """
    Optional custom logic before/after spawn.
    Currently returns config only - scheduler handles the actual wake.
    """
    return {
        "status": "ready",
        "plugin": PLUGIN_CONFIG["name"],
        "branch": PLUGIN_CONFIG["branch"],
    }
