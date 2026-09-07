# =================== AIPass ====================
# Name: auto_process.py
# Version: 1.3.0
# Description: Kicks @memory's auto-process once per session and on pre-compact (TDPLAN-0005)
# Branch: hooks
# Layer: apps/handlers/lifecycle
# Created: 2026-06-06
# Modified: 2026-09-06
# =============================================

"""Kicks @memory's auto_process in a detached child; the work leaves the prompt lane.

DPLAN-0294 phase 1b. This handler used to call auto_process() inline, which put
memory vectorize + rollover on the critical path of the first prompt of every
session — measured at 78-120s and killed by the hook timeout, silently discarding
the injection. spawn_background() detaches the work and returns immediately; the
child reports its own counters to memory_json/auto_process_log.json.
"""

import importlib
import os
import tempfile
from pathlib import Path

from aipass.prax.apps.modules.logger import system_logger as logger

_GUARD_DIR = Path(tempfile.gettempdir())


def _session_guard_path() -> Path | None:
    session_id = os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    if not session_id:
        return None
    return _GUARD_DIR / f"aipass-auto-process-{session_id}"


def _already_ran_this_session() -> bool:
    guard = _session_guard_path()
    return guard is not None and guard.exists()


def _mark_session_ran() -> None:
    guard = _session_guard_path()
    if guard is not None:
        try:
            guard.touch()
        except OSError as exc:
            logger.info("[HOOKS] auto_process: guard write failed: %s", exc)


def handle(hook_data: dict) -> dict:
    """Kick @memory's detached auto-process run and return. Never does the work inline.

    The guard means "kicked once this session", not "ran once" — a refusal counts,
    because a live run is the work already happening. Only a failed kick stays
    retryable on the next prompt.
    """
    _ = hook_data

    if _already_ran_this_session():
        return {"stdout": "", "exit_code": 0}

    # The kick starts @memory's real background worker on the real pool. A probe
    # that fires every wired hook must not put another citizen to work, and the
    # session guard does not stop it — the guard is per session id, so the first
    # probe run of a given mock id spawns for real. Refused here rather than at
    # entry, so the guard path above is still exercised.
    if os.environ.get("AIPASS_HOOK_PROBE") == "1":
        logger.info("[HOOKS] auto_process: probe run — spawn suppressed")
        return {"stdout": "", "exit_code": 0}

    try:
        module = importlib.import_module("aipass.memory.apps.handlers.intake.auto_process")
        result = module.spawn_background()

        if not result.get("success"):
            logger.error("[HOOKS] auto_process: spawn failed: %s", result.get("error"))
            return {"stdout": "", "exit_code": 1}

        _mark_session_ran()

        if result.get("skipped"):
            logger.info("[HOOKS] auto_process: not spawned: %s", result.get("reason"))
            return {"stdout": "", "exit_code": 0}

        logger.info("[HOOKS] auto_process: spawned pid %s", result.get("pid"))
        return {"stdout": "", "exit_code": 0, "sound": "auto process"}

    except Exception as exc:
        logger.error("[HOOKS] auto_process: error: %s", exc)
        return {"stdout": "", "exit_code": 1}
