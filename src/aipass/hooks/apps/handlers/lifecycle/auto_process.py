# =================== AIPass ====================
# Name: auto_process.py
# Version: 1.1.0
# Description: Fires @memory's auto-process once per session and on pre-compact (TDPLAN-0005)
# Branch: hooks
# Layer: apps/handlers/lifecycle
# Created: 2026-06-06
# Modified: 2026-06-06
# =============================================

"""Calls @memory's auto_process() to vectorize pool drops and run rollover."""

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
    """Invoke @memory's auto_process entry point. Idempotent, fast no-op when nothing to do."""
    _ = hook_data

    if _already_ran_this_session():
        return {"stdout": "", "exit_code": 0}

    try:
        module = importlib.import_module("aipass.memory.apps.handlers.intake.auto_process")
        result = module.auto_process()

        pool = result.get("pool", {})
        rollover = result.get("rollover", {})
        pool_files = pool.get("files_processed", 0)
        rollover_processed = rollover.get("processed", 0)

        if pool_files or rollover_processed:
            logger.info(
                "[HOOKS] auto_process: pool=%d files, rollover=%d processed",
                pool_files,
                rollover_processed,
            )
        else:
            logger.info("[HOOKS] auto_process: no-op (nothing to process)")

        _mark_session_ran()
        return {"stdout": "", "exit_code": 0, "sound": "auto process"}

    except Exception as exc:
        logger.error("[HOOKS] auto_process: error: %s", exc)
        return {"stdout": "", "exit_code": 1}
