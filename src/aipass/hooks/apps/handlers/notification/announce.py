# =================== AIPass ====================
# Name: announce.py
# Version: 1.1.1
# Description: Plays announcement tone on Notification events
# Branch: hooks
# Layer: apps/handlers/notification
# Created: 2026-05-20
# Modified: 2026-11-15
# =============================================

"""Plays announcement tone + Piper voice ID on Notification events."""


def handle(hook_data: dict) -> dict:
    """Play notification tone and speak hook name for identification.

    Args:
        hook_data: Parsed hook event dict from engine.

    Returns:
        Result dict with stdout (empty) and exit_code.
    """
    return {"stdout": "", "exit_code": 0, "sound": "notification sound"}
