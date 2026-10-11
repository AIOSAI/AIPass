# =================== AIPass ====================
# Name: announce.py
# Version: 1.1.0
# Description: Plays announcement tone on Notification events
# Branch: hooks
# Layer: apps/handlers/notification
# Created: 2026-05-20
# Modified: 2026-05-20
# =============================================

"""Plays announcement tone + Piper voice ID on Notification events."""

import os
from pathlib import Path

AIPASS_HOME = Path(os.environ.get("AIPASS_HOME", ""))
SOUNDS_DIR = AIPASS_HOME / ".claude" / "sounds"
SOUND_FILE = SOUNDS_DIR / "mixkit-clear-announce-tones-2861.wav"


def handle(hook_data: dict) -> dict:
    """Play notification tone and speak hook name for identification.

    Args:
        hook_data: Parsed hook event dict from engine.

    Returns:
        Result dict with stdout (empty) and exit_code.
    """
    return {"stdout": "", "exit_code": 0, "sound": "notification sound"}
