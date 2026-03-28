#!/usr/bin/env python3
"""Notification Hook — Plays sound when AI needs permission."""

import json
import sys
import subprocess
from pathlib import Path

SOUNDS_DIR = Path(__file__).parent.parent / "sounds"
SOUND_FILE = SOUNDS_DIR / "mixkit-clear-announce-tones-2861.wav"


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
        if hook_data.get("hook_event_name") == "Notification":
            play_sound()
    except Exception:
        pass
    sys.exit(0)


if __name__ == "__main__":
    main()
