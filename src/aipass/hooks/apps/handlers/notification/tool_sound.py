# =================== AIPass ====================
# Name: tool_sound.py
# Version: 1.2.0
# Description: Announces hook name via Piper TTS on tool use
# Branch: hooks
# Layer: apps/handlers/notification
# Created: 2026-05-19
# Modified: 2026-11-17
# =============================================

"""Announces hook name via Piper TTS when the AI uses tools (PreToolUse event)."""

from aipass.hooks.apps.handlers.json import json_handler


def handle(hook_data: dict) -> dict:
    """Announce the tool's hook name; each call leaves one json trail entry."""
    result = _handle(hook_data)
    seat = hook_data.get("cwd", "") if isinstance(hook_data, dict) else ""
    json_handler.log_operation("handle", {"exit_code": result.get("exit_code"), "seat": seat})
    return result


def _handle(hook_data: dict) -> dict:
    """Announce hook name for matching tool use events.

    Args:
        hook_data: Parsed hook event dict from engine (tool_name, etc.)

    Returns:
        Result dict with stdout (empty) and exit_code.
    """
    tool_name = hook_data.get("tool_name", "")
    if not tool_name:
        return {"stdout": "", "exit_code": 0}

    return {"stdout": "", "exit_code": 0, "sound": f"tool sound: {tool_name}"}
