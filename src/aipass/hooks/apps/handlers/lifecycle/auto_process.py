# =================== AIPass ====================
# Name: auto_process.py
# Version: 1.4.1
# Description: Kicks @memory's auto-process once per session and on pre-compact (TDPLAN-0005)
# Branch: hooks
# Layer: apps/handlers/lifecycle
# Created: 2026-06-06
# Modified: 2026-11-22
# =============================================

"""Kicks @memory's auto_process in a detached child; the work leaves the prompt lane.

Inline, vectorize + rollover outlasts the hook timeout and the injection is lost.
"""

import os
import tempfile
from pathlib import Path

from aipass.hooks.apps.handlers.json import json_handler
from aipass.prax import logger

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
            logger.warning("[hooks] auto_process: guard write failed: %s", exc)


def handle(hook_data: dict) -> dict:
    """Kick @memory's detached auto-process; each call leaves one json trail entry."""
    result = _handle()
    seat = hook_data.get("cwd", "") if isinstance(hook_data, dict) else ""
    json_handler.log_operation("handle", {"exit_code": result.get("exit_code"), "seat": seat})
    return result


def _handle() -> dict:
    """Kick @memory's detached auto-process, never inline. A refusal marks the guard; a failed kick or raise retries."""
    if _already_ran_this_session():
        return {"stdout": "", "exit_code": 0}

    # A probe must not start @memory's real worker; the per-session guard does not stop a new mock id.
    if os.environ.get("AIPASS_HOOK_PROBE") == "1":
        logger.info("[hooks] auto_process: probe run — spawn suppressed")
        return {"stdout": "", "exit_code": 0}

    from aipass.memory import spawn_background

    result = spawn_background()

    if not result.get("success"):
        logger.error("[hooks] auto_process: spawn failed: %s", result.get("error"))
        return {"stdout": "", "exit_code": 1}

    _mark_session_ran()

    if result.get("skipped"):
        logger.info("[hooks] auto_process: not spawned: %s", result.get("reason"))
        return {"stdout": "", "exit_code": 0}

    logger.info("[hooks] auto_process: spawned pid %s", result.get("pid"))
    return {"stdout": "", "exit_code": 0, "sound": "auto process"}
