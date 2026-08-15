# ===================AIPASS====================
# META DATA HEADER
# Name: handler.py - Screen Lock skill handler
# Date: 2026-08-14
# Version: 1.0.0
# Category: skills/lib/screen_lock
# =============================================

"""
Screen Lock skill handler.

Password-locks the graphical session and leaves everything running. No root, no
sudoers grant, no polkit rule, and nothing sleeps — unlike /suspend there is no
wake, grace-window or reachability story to get wrong (Patrick's ruling #217).

Extracted from the Telegram control bot (DPLAN-0300) so any caller — the host
API's verb lane, drone, another skill — can lock the machine without importing
the Telegram stack. Stdlib + the Prax logger only; that isolation is a test.

DOCTRINE: a destructive action never fires from a locked screen. Lock is the
exception that MUST work from anywhere — so this verb is never gated on screen
state, session env, or a caller's desktop context. It tries, then reports.

Called by: drone @skills run screen_lock lock
"""

import os
import subprocess
from typing import Optional

from aipass.prax import logger

METHOD_LOGINCTL = "loginctl"
METHOD_DBUS = "dbus"

LOCK_FAILED_MESSAGE = "Could not lock the screen — loginctl and the D-Bus fallback both failed."


def run(action, args=None, config=None):
    """Execute a screen_lock action.

    Args:
        action: Only "lock" is supported.
        args: Dict of action arguments (unused for this skill).
        config: Dict of resolved config values (unused for this skill).

    Returns:
        {"success": bool, "output": str, "error": str|None}
    """
    args = args or {}
    config = config or {}

    if action != "lock":
        available = ", ".join(get_actions())
        return {
            "success": False,
            "output": "",
            "error": f"Unknown action: {action}. Available: {available}",
        }

    result = lock_screen()
    if not result["locked"]:
        return {"success": False, "output": "", "error": result["error"]}

    where = result["session"] or "ambient"
    return {
        "success": True,
        "output": f"Screen locked via {result['method']} (session={where})",
        "error": None,
    }


def get_actions():
    """List available actions for this skill."""
    return ["lock"]


# ---------------------------------------------------------------------------
# Public API — what the Telegram bot and the host verb lane call
# ---------------------------------------------------------------------------


def lock_screen() -> dict:
    """Password-lock the screen, leaving every process running.

    Tries `loginctl lock-session` against the explicitly resolved graphical
    session first, then the GNOME ScreenSaver D-Bus method. Never reports a
    lock it did not achieve.

    Returns:
        dict: {
            "locked": bool,
            "method": "loginctl" | "dbus" | None,
            "session": str|None — the logind session id, None if unresolved,
            "error": str|None,
        }
    """
    session_id = resolve_graphical_session()
    target = ["loginctl", "lock-session"] + ([session_id] if session_id else [])

    try:
        subprocess.run(target, check=True, capture_output=True)
        logger.info("Screen locked via loginctl (session=%s)", session_id or "ambient")
        return {"locked": True, "method": METHOD_LOGINCTL, "session": session_id, "error": None}
    except FileNotFoundError:
        logger.warning("loginctl not found, trying the D-Bus screensaver fallback")
    except subprocess.CalledProcessError as e:
        stderr = (e.stderr or b"").decode("utf-8", errors="replace").strip()
        logger.warning("loginctl lock refused (%s), trying the D-Bus fallback", stderr or e)

    if _lock_via_dbus():
        logger.info("Screen locked via the GNOME ScreenSaver D-Bus fallback")
        return {"locked": True, "method": METHOD_DBUS, "session": session_id, "error": None}

    logger.error("Lock failed: neither loginctl nor the D-Bus fallback could lock the screen")
    return {"locked": False, "method": None, "session": session_id, "error": LOCK_FAILED_MESSAGE}


def resolve_graphical_session() -> Optional[str]:
    """
    Find this user's active graphical logind session id, or None.

    Callers commonly run as a `systemd --user` service, outside the graphical
    session scope — they have no XDG_SESSION_ID, so `loginctl lock-session`
    with no argument has no ambient session to resolve and may refuse. Naming
    the session explicitly makes the call work from any context.
    """
    try:
        listed = subprocess.run(
            ["loginctl", "list-sessions", "--no-legend"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as e:
        logger.warning("Could not list logind sessions: %s", e)
        return None

    our_uid = str(os.getuid())
    for line in listed.stdout.splitlines():
        parts = line.split()
        if not parts:
            continue
        session_id = parts[0]
        try:
            shown = subprocess.run(
                ["loginctl", "show-session", session_id, "-p", "Type", "-p", "State", "-p", "User"],
                check=True,
                capture_output=True,
                text=True,
            )
        except (FileNotFoundError, subprocess.CalledProcessError) as e:
            logger.info("Could not inspect session %s, skipping it: %s", session_id, e)
            continue
        props = dict(p.split("=", 1) for p in shown.stdout.splitlines() if "=" in p)
        if props.get("Type") in ("wayland", "x11") and props.get("State") == "active" and props.get("User") == our_uid:
            return session_id
    return None


# ---------------------------------------------------------------------------
# Fallback path
# ---------------------------------------------------------------------------


def _lock_via_dbus() -> bool:
    """Fallback lock via the GNOME ScreenSaver session-bus method. True if it succeeded."""
    try:
        subprocess.run(
            [
                "gdbus",
                "call",
                "--session",
                "--dest",
                "org.gnome.ScreenSaver",
                "--object-path",
                "/org/gnome/ScreenSaver",
                "--method",
                "org.gnome.ScreenSaver.Lock",
            ],
            check=True,
            capture_output=True,
        )
        return True
    except (FileNotFoundError, subprocess.CalledProcessError) as e:
        logger.warning("D-Bus screensaver lock failed: %s", e)
        return False
