#!/usr/bin/env python3
"""Tool Use Hook — Plays key press sound when AI uses tools."""

import json
import sys
import subprocess
from pathlib import Path

SOUNDS_DIR = Path(__file__).parent.parent / "sounds"
SOUND_FILE = SOUNDS_DIR / "mixkit-atm-cash-machine-key-press-2841.wav"

SOUND_TOOLS = ["Bash", "Edit", "MultiEdit", "Write", "Read", "Grep", "Glob"]


def play_sound() -> None:
    if not SOUND_FILE.exists():
        return
    try:
        subprocess.Popen(
            ["aplay", "-q", str(SOUND_FILE)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


def main():
    try:
        hook_data = json.loads(sys.stdin.read())
        if hook_data.get("hook_event_name") == "PreToolUse":
            if hook_data.get("tool_name", "") in SOUND_TOOLS:
                play_sound()
    except Exception:
        pass
    sys.exit(0)


if __name__ == "__main__":
    main()
