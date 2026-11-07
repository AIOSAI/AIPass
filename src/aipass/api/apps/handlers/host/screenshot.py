# =================== AIPass ====================
# Name: screenshot.py
# Description: Host API Screenshot — the desktop's own screenshot picker, the saved file's path back to the client
# Version: 1.0.0
# Created: 2026-11-05
# Modified: 2026-11-05
# =============================================

"""
Host API Screenshot
Reference: docs/host_agent_chat.md. The XDG desktop portal's interactive Screenshot call opens the desktop's picker
on the host; the portal answers by D-Bus signal, and with no D-Bus client here this waits for the new file where
the desktop saves it. shortcut: Linux desktops with xdg-desktop-portal only; macOS or Windows need their own call.
"""

import shutil
import subprocess
import time
from pathlib import Path

from aipass.prax import logger
from aipass.api.apps.handlers.json import json_handler

SAVED = Path("Pictures") / "Screenshots"
WAIT_SECONDS = 120.0  # the picker stays open while the shot is framed
POLL_SECONDS = 0.25
PORTAL_CALL = [
    "call",
    "--session",
    "--dest",
    "org.freedesktop.portal.Desktop",
    "--object-path",
    "/org/freedesktop/portal/desktop",
    "--method",
    "org.freedesktop.portal.Screenshot.Screenshot",
    "",
    "{'interactive': <true>}",
]


class ScreenshotUnavailable(Exception):
    """No picker could open, or no shot was taken; the words are for the host log only."""


def folders() -> tuple[Path, Path]:
    """Where the desktop saves: the interactive picker into Pictures/Screenshots, a plain one into Pictures."""
    saved = Path.home() / SAVED
    return saved.parent, saved


def _newest_since(start: float) -> Path | None:
    """The newest PNG written after *start* in either folder."""
    shots = [p for folder in folders() for p in folder.glob("*.png") if p.stat().st_mtime >= start]
    return max(shots, key=lambda p: p.stat().st_mtime) if shots else None


def take() -> Path:
    """Open the picker and wait for the shot; ScreenshotUnavailable when none opens, or none is taken."""
    gdbus = shutil.which("gdbus")
    if not gdbus:
        raise ScreenshotUnavailable("gdbus was not found; the host cannot open the screenshot picker")
    start = time.time() - 1
    try:
        done = subprocess.run([gdbus, *PORTAL_CALL], capture_output=True, text=True, timeout=10, check=False)
    except subprocess.TimeoutExpired as e:
        logger.warning("[host_api] the screenshot portal did not answer: %s", e)
        raise ScreenshotUnavailable("the screenshot picker did not answer in 10s") from e
    if done.returncode != 0:
        logger.warning("[host_api] the screenshot portal refused: %s", done.stderr.strip())
        raise ScreenshotUnavailable(f"the screenshot picker did not open: {done.stderr.strip()}")
    deadline = time.time() + WAIT_SECONDS
    while time.time() < deadline:
        shot = _newest_since(start)
        if shot is not None:
            time.sleep(POLL_SECONDS)  # let the portal finish writing it
            json_handler.log_operation("host_api_screenshot", {"path": str(shot)})
            return shot
        time.sleep(POLL_SECONDS)
    raise ScreenshotUnavailable("no screenshot was taken")
