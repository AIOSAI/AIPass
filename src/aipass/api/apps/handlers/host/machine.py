# =================== AIPass ====================
# Name: machine.py
# Description: Host API Machine Handler — the phone's vitals and process list, proxied from @skills
# Version: 1.1.0
# Created: 2026-09-13
# Modified: 2026-10-17
# =============================================

"""
Host API Machine Handler
Reference: docs/host_api.md. Verbatim relay; a refusal is raised out of the producer, so ReadCache never stores it.
The skill import sits inside each call: an idle server imports nothing, and the skill reads its off-switch per call."""

from typing import Any, Dict

from aipass.prax import logger
from aipass.api.apps.handlers.json import json_handler
from aipass.api.apps.handlers.host.read_cache import ReadCache

# 1.0 s, not the git lane's 1.5: vitals are a live gauge.
MACHINE_TTL_SECONDS = 1.0

_VITALS_KEY = "vitals"

# Only in place of no detail at all; a detail the skill gave travels untouched.
NO_DETAIL = "@skills refused the machine read and gave no detail"

# Fixed, never the exception's words: those can carry host paths, and this travels to a handset.
DOOR_RAISED = "@skills' machine_vitals() raised; the error is in this host's log"

PROCESSES_DOOR_FAILED = "@skills' machine_processes() could not answer; the reason is in this host's log"

_vitals = ReadCache("machine_vitals", MACHINE_TTL_SECONDS)


class MachineRefused(Exception):
    """The skill refused the whole read."""

    def __init__(self, reason: Any, detail: str) -> None:
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


class MachineDoorFailed(Exception):
    """The door raised, or answered outside its published shape."""


def read_machine() -> Dict[str, Any]:
    """The machine's vitals, as @skills' system_status answers them."""
    return _vitals.get(_VITALS_KEY, _ask_the_skill)


def read_processes(limit: int) -> Dict[str, Any]:
    """The busiest processes, as @skills' system_status answers them."""
    from aipass.skills.lib.system_status import handler as system_status

    try:
        answer = system_status.machine_processes(limit)
    except Exception as exc:
        logger.error("[host_api] @skills' machine_processes() raised %s: %s", type(exc).__name__, exc, exc_info=True)
        json_handler.log_operation("host_api_processes_door_failed", {"error": type(exc).__name__})
        raise MachineDoorFailed(PROCESSES_DOOR_FAILED) from exc

    if not isinstance(answer, dict):
        message = f"@skills' machine_processes() answered outside its published shape: a {type(answer).__name__}"
        logger.error("[host_api] %s", message)
        json_handler.log_operation("host_api_processes_door_failed", {"error": "shape"})
        raise MachineDoorFailed(message)

    # A success carries no `ok`; only an explicit False is a refusal.
    if answer.get("ok") is False:
        reason = answer.get("reason")
        detail = answer.get("detail")
        logger.warning("[host_api] @skills refused the process read: %s", reason)
        json_handler.log_operation("host_api_processes_refused", {"reason": reason})
        raise MachineRefused(reason, detail if isinstance(detail, str) and detail else NO_DETAIL)

    return answer


def forget() -> None:
    """Drop the cached reading so the next read asks @skills' machine_vitals() again."""
    _vitals.clear()


def _ask_the_skill() -> Dict[str, Any]:
    """One read through @skills' published door."""
    from aipass.skills.lib.system_status import handler as system_status

    try:
        vitals = system_status.machine_vitals()
    except Exception as exc:
        logger.error("[host_api] @skills' machine_vitals() raised %s: %s", type(exc).__name__, exc, exc_info=True)
        json_handler.log_operation("host_api_machine_door_failed", {"error": type(exc).__name__})
        raise MachineDoorFailed(DOOR_RAISED) from exc

    ok = vitals.get("ok") if isinstance(vitals, dict) else None
    if not isinstance(ok, bool):
        message = (
            f"@skills' machine_vitals() answered outside its published shape: "
            f"no boolean 'ok' in a {type(vitals).__name__}"
        )
        logger.error("[host_api] %s", message)
        json_handler.log_operation("host_api_machine_door_failed", {"error": "shape"})
        raise MachineDoorFailed(message)

    if not ok:
        reason = vitals.get("reason")
        detail = vitals.get("detail")
        logger.warning("[host_api] @skills refused the machine read: %s", reason)
        json_handler.log_operation("host_api_machine_refused", {"reason": reason})
        raise MachineRefused(reason, detail if isinstance(detail, str) and detail else NO_DETAIL)

    return vitals
