# =================== AIPass ====================
# Name: lock.py
# Description: Host API Lock Handler — the screen lock's position, proxied from @skills
# Version: 1.0.2
# Created: 2026-09-13
# Modified: 2026-10-17
# =============================================

"""Host API Lock Handler
Reference: docs/host_api.md. The meaning is @skills'; a second reader here would be a second answer.
Known limit: the skill's reads carry no timeout, so a hung logind holds every queued request's worker thread."""

from typing import Any, Dict

from aipass.prax import logger
from aipass.api.apps.handlers.json import json_handler
from aipass.api.apps.handlers.host.read_cache import ReadCache

LOCK_TTL_SECONDS = 1.0

_STATE_KEY = "state"

DOOR_RAISED = "@skills' lock_state() raised; the error is in this host's log"

_state = ReadCache("lock_state", LOCK_TTL_SECONDS)


class LockDoorFailed(Exception):
    """The door raised, or answered outside its published shape."""


def read_lock() -> Dict[str, Any]:
    """The screen lock's position, as @skills' screen_lock answers it."""
    return _state.get(_STATE_KEY, _ask_the_skill)


def forget() -> None:
    """Drop the cached reading so the next read asks @skills' lock_state() again."""
    _state.clear()


def _ask_the_skill() -> Dict[str, Any]:
    """One read through @skills' published door."""
    # Imported here so a server that never serves this route imports nothing new.
    from aipass.skills.lib.screen_lock import handler as screen_lock

    try:
        answer = screen_lock.lock_state()
    except Exception as exc:
        logger.error("[host_api] @skills' lock_state() raised %s: %s", type(exc).__name__, exc, exc_info=True)
        json_handler.log_operation("host_api_lock_door_failed", {"error": type(exc).__name__})
        raise LockDoorFailed(DOOR_RAISED) from exc

    fault = _shape_fault(answer)
    if fault:
        message = f"@skills' lock_state() answered outside its published shape: {fault}"
        logger.error("[host_api] %s", message)
        json_handler.log_operation("host_api_lock_door_failed", {"error": "shape"})
        raise LockDoorFailed(message)

    return answer


def _shape_fault(answer: Any) -> str:
    """What breaks the published shape, or "" when nothing does.
    `ok: False` with `locked: False` is refused: a client would draw it as unlocked."""
    if not isinstance(answer, dict):
        return f"a {type(answer).__name__}, not a dict"

    ok = answer.get("ok")
    if not isinstance(ok, bool):
        return "no boolean 'ok'"
    if "locked" not in answer:
        return "no 'locked' key"

    locked = answer["locked"]
    if ok and not isinstance(locked, bool):
        return f"ok True with 'locked' {locked!r}, not a bool"
    if not ok and locked is not None:
        return f"ok False with 'locked' {locked!r}, not None"
    return ""
