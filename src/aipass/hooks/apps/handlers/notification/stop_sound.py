# =================== AIPass ====================
# Name: stop_sound.py
# Version: 1.2.0
# Description: Plays achievement bell + Piper voice on Stop events
# Branch: hooks
# Layer: apps/handlers/notification
# Created: 2026-05-20
# Modified: 2026-11-17
# =============================================

"""Plays achievement bell when the AI finishes responding (Stop event)."""

from aipass.hooks.apps.handlers.json import json_handler


def handle(hook_data: dict) -> dict:
    """Play the achievement bell on Stop; each call leaves one json trail entry."""
    result = _handle(hook_data)
    seat = hook_data.get("cwd", "") if isinstance(hook_data, dict) else ""
    json_handler.log_operation("handle", {"exit_code": result.get("exit_code"), "seat": seat})
    return result


def _handle(hook_data: dict) -> dict:
    """Play achievement bell and speak hook name on Stop event.

    Args:
        hook_data: Parsed hook event dict from engine.

    Returns:
        Result dict with stdout (empty) and exit_code.
    """
    if hook_data.get("stop_hook_active", False):
        return {"stdout": "", "exit_code": 0}

    return {"stdout": "", "exit_code": 0, "sound": "stop sound"}
