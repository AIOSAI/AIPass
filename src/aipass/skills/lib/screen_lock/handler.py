# ===================AIPASS====================
# META DATA HEADER
# Name: handler.py - Screen Lock skill handler
# Date: 2026-08-14
# Version: 1.1.0
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

THE READ BESIDE THE LOCK (FPLAN-0585): lock_state() answers whether the screen
IS locked, through the same pair the lock writes through, in the same order.
It is not gated either, it never locks anything, and a read that cannot tell
answers locked None with a reason — never False, because unknown is not
unlocked.

Called by: drone @skills run screen_lock lock | state
"""

import os
import subprocess
from typing import Optional, Tuple

from aipass.prax import logger

METHOD_LOGINCTL = "loginctl"
METHOD_DBUS = "dbus"

LOCK_FAILED_MESSAGE = "Could not lock the screen — loginctl and the D-Bus fallback both failed."

# Why lock_state() could not tell. A code for callers to branch on; the sentence
# beside it is for people.
REASON_NO_SESSION = "no_session"
REASON_NO_READER = "no_reader"
REASON_READ_FAILED = "read_failed"

_GNOME_SCREENSAVER = [
    "gdbus",
    "call",
    "--session",
    "--dest",
    "org.gnome.ScreenSaver",
    "--object-path",
    "/org/gnome/ScreenSaver",
    "--method",
]


def run(action, args=None, config=None):
    """Execute a screen_lock action.

    Args:
        action: "lock" locks the screen; "state" reads whether it is locked.
        args: Dict of action arguments (unused for this skill).
        config: Dict of resolved config values (unused for this skill).

    Returns:
        {"success": bool, "output": str, "error": str|None}
    """
    args = args or {}
    config = config or {}

    if action not in get_actions():
        available = ", ".join(get_actions())
        return {
            "success": False,
            "output": "",
            "error": f"Unknown action: {action}. Available: {available}",
        }

    if action == "state":
        state = lock_state()
        if not state["ok"]:
            return {"success": False, "output": "", "error": f"{state['detail']} (reason={state['reason']})"}
        return {"success": True, "output": state["detail"], "error": None}

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
    return ["lock", "state"]


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


def lock_state() -> dict:
    """Read whether the screen is locked. Changes nothing, never raises.

    Asks logind for LockedHint on the resolved graphical session first — the
    mechanism lock_screen() writes through, so read and write agree — then
    GNOME ScreenSaver's GetActive. Not gated: the lock never is, so its read
    is not either.

    Returns:
        dict: {
            "ok": bool — True when a reader answered,
            "locked": bool|None — None whenever ok is False,
            "method": "loginctl" | "dbus" | None,
            "session": str|None — the resolved logind session id,
            "reason": "no_session" | "no_reader" | "read_failed" | None,
            "detail": str — this skill's sentence for the answer or the absence,
        }
    """
    session_id, logind_reason, logind_why = _resolve_session()
    if session_id:
        locked, logind_reason, logind_why = _read_locked_hint(session_id)
        if locked is not None:
            sentence = f"The screen is {_word(locked)}, per logind session {session_id}."
            return _state(True, locked, METHOD_LOGINCTL, session_id, None, sentence)

    active, dbus_reason, dbus_why = _read_screensaver_active()
    if active is not None:
        sentence = f"The screen is {_word(active)}, per GNOME ScreenSaver."
        return _state(True, active, METHOD_DBUS, session_id, None, sentence)

    reason = _cannot_tell_reason(logind_reason, dbus_reason)
    detail = f"Cannot tell whether the screen is locked. {logind_why} {dbus_why}"
    logger.warning("lock_state cannot tell (%s): %s", reason, detail)
    return _state(False, None, None, session_id, reason, detail)


def resolve_graphical_session() -> Optional[str]:
    """
    Find this user's active graphical logind session id, or None.

    Callers commonly run as a `systemd --user` service, outside the graphical
    session scope — they have no XDG_SESSION_ID, so `loginctl lock-session`
    with no argument has no ambient session to resolve and may refuse. Naming
    the session explicitly makes the call work from any context.
    """
    return _resolve_session()[0]


def _resolve_session() -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """The resolver itself: (session_id, None, None), or (None, reason, sentence) saying why none."""
    try:
        listed = subprocess.run(
            ["loginctl", "list-sessions", "--no-legend"],
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as e:
        logger.warning("Could not list logind sessions: %s", e)
        return None, REASON_NO_READER, "loginctl is not installed."
    except (OSError, subprocess.SubprocessError) as e:
        logger.warning("Could not list logind sessions: %s", e)
        return None, REASON_READ_FAILED, f"loginctl could not list sessions ({_describe(e)})."

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
        except (OSError, subprocess.SubprocessError) as e:
            logger.info("Could not inspect session %s, skipping it: %s", session_id, e)
            continue
        props = dict(p.split("=", 1) for p in shown.stdout.splitlines() if "=" in p)
        if props.get("Type") in ("wayland", "x11") and props.get("State") == "active" and props.get("User") == our_uid:
            return session_id, None, None
    return None, REASON_NO_SESSION, "logind lists no active graphical session of this user."


# ---------------------------------------------------------------------------
# The read's two legs
# ---------------------------------------------------------------------------


def _read_locked_hint(session_id: str) -> Tuple[Optional[bool], Optional[str], Optional[str]]:
    """logind's LockedHint for one session: yes is locked, no is unlocked, anything else is no answer.

    Returns:
        tuple: (True/False, None, None) when it answered, else (None, reason code, sentence).
    """
    try:
        shown = subprocess.run(
            ["loginctl", "show-session", session_id, "-p", "LockedHint"],
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        logger.info("lock_state: loginctl not found, trying the D-Bus screensaver read")
        return None, REASON_NO_READER, "loginctl is not installed."
    except (OSError, subprocess.SubprocessError) as e:
        logger.info("lock_state: LockedHint read of session %s failed: %s", session_id, e)
        return None, REASON_READ_FAILED, f"loginctl could not read LockedHint of session {session_id} ({_describe(e)})."

    said = shown.stdout.strip()
    if said == "LockedHint=yes":
        return True, None, None
    if said == "LockedHint=no":
        return False, None, None
    sentence = f"loginctl answered {said[:80]!r} for session {session_id}, not LockedHint=yes or no."
    logger.info("lock_state: %s", sentence)
    return None, REASON_READ_FAILED, sentence


def _read_screensaver_active() -> Tuple[Optional[bool], Optional[str], Optional[str]]:
    """GNOME ScreenSaver's GetActive: (true,) is locked, (false,) is unlocked, anything else is no answer.

    Returns:
        tuple: (True/False, None, None) when it answered, else (None, reason code, sentence).
    """
    try:
        shown = subprocess.run(
            _GNOME_SCREENSAVER + ["org.gnome.ScreenSaver.GetActive"],
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        logger.info("lock_state: gdbus not found")
        return None, REASON_NO_READER, "gdbus is not installed."
    except (OSError, subprocess.SubprocessError) as e:
        logger.info("lock_state: GNOME ScreenSaver GetActive failed: %s", e)
        return None, REASON_READ_FAILED, f"GNOME ScreenSaver did not answer ({_describe(e)})."

    said = shown.stdout.strip()
    if said == "(true,)":
        return True, None, None
    if said == "(false,)":
        return False, None, None
    sentence = f"GNOME ScreenSaver answered {said[:80]!r}, not (true,) or (false,)."
    logger.info("lock_state: %s", sentence)
    return None, REASON_READ_FAILED, sentence


def _cannot_tell_reason(logind_reason: Optional[str], dbus_reason: Optional[str]) -> str:
    """One code for two silent readers: no session outranks a failure, a failure outranks an absence."""
    if logind_reason == REASON_NO_SESSION:
        return REASON_NO_SESSION
    if REASON_READ_FAILED in (logind_reason, dbus_reason):
        return REASON_READ_FAILED
    return REASON_NO_READER


def _state(ok, locked, method, session, reason, detail) -> dict:
    """The six-key answer lock_state() publishes."""
    return {"ok": ok, "locked": locked, "method": method, "session": session, "reason": reason, "detail": detail}


def _word(locked: bool) -> str:
    """The sentence's word for a reading."""
    return "locked" if locked else "unlocked"


def _describe(exc: Exception) -> str:
    """One line naming what a failed reader said."""
    if isinstance(exc, subprocess.CalledProcessError):
        stderr = exc.stderr
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        said = " ".join((stderr or "").split())
        return f"exit {exc.returncode}: {said}" if said else f"exit {exc.returncode}"
    return str(exc) or type(exc).__name__


# ---------------------------------------------------------------------------
# Fallback path
# ---------------------------------------------------------------------------


def _lock_via_dbus() -> bool:
    """Fallback lock via the GNOME ScreenSaver session-bus method. True if it succeeded."""
    try:
        subprocess.run(
            _GNOME_SCREENSAVER + ["org.gnome.ScreenSaver.Lock"],
            check=True,
            capture_output=True,
        )
        return True
    except (FileNotFoundError, subprocess.CalledProcessError) as e:
        logger.warning("D-Bus screensaver lock failed: %s", e)
        return False
