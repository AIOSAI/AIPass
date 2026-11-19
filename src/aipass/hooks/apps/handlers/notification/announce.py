# =================== AIPass ====================
# Name: announce.py
# Version: 1.2.0
# Description: Plays announcement tone on Notification events
# Branch: hooks
# Layer: apps/handlers/notification
# Created: 2026-05-20
# Modified: 2026-11-17
# =============================================

"""Plays announcement tone + Piper voice ID on Notification events."""

from aipass.hooks.apps.handlers.json import json_handler


def handle(hook_data: dict) -> dict:
    """Play notification tone and speak hook name for identification; each call leaves one json trail entry.

    Args:
        hook_data: Parsed hook event dict from engine.

    Returns:
        Result dict with stdout (empty) and exit_code.
    """
    result = {"stdout": "", "exit_code": 0, "sound": "notification sound"}
    seat = hook_data.get("cwd", "") if isinstance(hook_data, dict) else ""
    json_handler.log_operation("handle", {"exit_code": result["exit_code"], "seat": seat})
    return result
