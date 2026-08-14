# =================== AIPass ====================
# Name: auto_process.py
# Description: Automated pool + rollover entry point
# Version: 1.0.0
# Created: 2026-06-06
# Modified: 2026-06-06
# =============================================

"""
Auto-process handler — session-start pool + rollover entry point.

Single callable the hook engine fires each session to:
1. Process any files dropped into memory_pool/ (vectorize + archive)
2. Check/run rollover for .trinity/ files exceeding limits

Idempotent: safe to call every session. Fast no-op when nothing to do.
Pool uses upsert with content-hash IDs — re-processing same files is a no-op.

HOOK ENGINE CONTRACT:
  Module: aipass.memory.apps.handlers.intake.auto_process
  Function: spawn_background()   <- what the hook calls (returns in milliseconds)
  Invocation: importlib.import_module(
      'aipass.memory.apps.handlers.intake.auto_process').spawn_background()
  Returns: dict with success + pid, or skipped + reason

  auto_process() remains the synchronous API for callers that genuinely want to
  wait. It must NOT be called from a UserPromptSubmit hook: measured 78.5-120.5s
  with a backlog, while its stdout is always empty -- so by Patrick's test
  (compass #272) it was blocking a prompt it never fed. DPLAN-0295 item 1.

WHY A DETACHED CHILD rather than a @daemon schedule:
  The work must still happen promptly when a file is dropped into the pool, and
  it must not depend on another service being up. A daemon that is down would
  stop vectorizing silently -- the exact failure mode this branch exists to
  prevent. The hook stays the trigger; only the waiting goes away.
"""

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict

from aipass.prax import logger
from aipass.memory.apps.handlers.json import json_handler, config_loader

_MEMORY_ROOT = Path(__file__).resolve().parent.parent.parent.parent

# Single-flight lock. Two sessions can start seconds apart, and two concurrent
# rollovers would write the same .trinity files. Staleness is time-based rather
# than PID-liveness based, to stay cross-platform: a crashed child frees the
# lane by itself instead of wedging it forever.
_LOCK_PATH = Path(tempfile.gettempdir()) / "aipass-memory-auto-process.lock"
_LOCK_STALE_SECONDS = 900
_CHILD_LOG = Path(tempfile.gettempdir()) / "aipass-memory-auto-process.log"


def _lock_is_stale(data: Dict[str, Any] | None) -> bool:
    """A missing, unreadable, or old lock is stale. Guard the read, not just the parse."""
    if not isinstance(data, dict):
        return True
    started = data.get("started")
    if not isinstance(started, (int, float)):
        return True
    return (time.time() - started) > _LOCK_STALE_SECONDS


def _read_lock() -> Dict[str, Any] | None:
    """Read the lock file, or None if it is missing or cannot be read at all."""
    try:
        return json.loads(_LOCK_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        logger.debug("[auto_process] No lock file present")
        return None
    except Exception as e:
        logger.warning(f"[auto_process] Lock unreadable, treating as stale: {e}")
        return None


def _create_lock_file() -> bool | None:
    """
    Try to create the lock exclusively.

    Returns:
        True if taken, None if someone else holds it, False on a real OS error.
    """
    try:
        fd = os.open(str(_LOCK_PATH), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        logger.debug("[auto_process] Lock is held by another run")
        return None
    except OSError as e:
        logger.error(f"[auto_process] Cannot create lock: {e}")
        return False

    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump({"pid": os.getpid(), "started": time.time()}, handle)
    return True


def _reclaim_stale_lock() -> bool:
    """Remove a lock whose holder went stale. Returns True if the lane is now free."""
    if not _lock_is_stale(_read_lock()):
        return False

    logger.warning("[auto_process] Reclaiming stale lock")
    try:
        _LOCK_PATH.unlink()
    except OSError as e:
        logger.error(f"[auto_process] Could not reclaim stale lock: {e}")
        return False
    return True


def _acquire_lock() -> bool:
    """Take the lock atomically, reclaiming it once if the holder went stale."""
    taken = _create_lock_file()
    if taken is not None:
        return taken

    if not _reclaim_stale_lock():
        return False

    return _create_lock_file() is True


def _release_lock() -> None:
    """Drop the lock. A failure here is logged, never raised over the real result."""
    try:
        _LOCK_PATH.unlink()
    except FileNotFoundError:
        logger.debug("[auto_process] Lock already released")
    except OSError as e:
        logger.error(f"[auto_process] Could not release lock: {e}")


def spawn_background() -> Dict[str, Any]:
    """
    Kick auto-processing in a detached child and return immediately.

    This is what the hook engine calls. It never does the work inline and never
    raises: a hook that dies takes the whole prompt with it.

    Returns:
        dict with success + pid, or skipped + reason when a run is already live.
    """
    holder = _read_lock()
    if holder is not None and not _lock_is_stale(holder):
        reason = f"already running (pid {holder.get('pid')})"
        logger.info(f"[auto_process] Spawn skipped -- {reason}")
        return {"success": True, "skipped": True, "reason": reason, "pid": None}

    try:
        log_handle = open(_CHILD_LOG, "a", encoding="utf-8")
    except OSError as e:
        logger.error(f"[auto_process] Cannot open child log: {e}")
        return {"success": False, "error": str(e), "pid": None}

    kwargs: Dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": log_handle,
        "stderr": subprocess.STDOUT,
        "cwd": str(_MEMORY_ROOT),
    }
    if sys.platform == "win32":
        # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        kwargs["creationflags"] = 0x00000008 | 0x00000200
    else:
        kwargs["start_new_session"] = True

    try:
        child = subprocess.Popen([sys.executable, str(Path(__file__).resolve())], **kwargs)
    except Exception as e:
        logger.error(f"[auto_process] Spawn failed: {e}")
        json_handler.log_operation("spawn_background", {"success": False, "error": str(e)})
        return {"success": False, "error": str(e), "pid": None}
    finally:
        log_handle.close()

    logger.info(f"[auto_process] Spawned background run (pid {child.pid})")
    json_handler.log_operation("spawn_background", {"success": True, "pid": child.pid})
    return {"success": True, "skipped": False, "pid": child.pid}


def run_once() -> Dict[str, Any]:
    """
    Child entry point: take the lock, do the work, always give the lock back.

    Returns:
        dict with the auto_process result, or skipped when another run holds it.
    """
    if not _acquire_lock():
        logger.info("[auto_process] Another run holds the lock -- declining")
        return {"success": True, "skipped": True, "reason": "another run holds the lock"}

    started = time.time()
    try:
        result = auto_process()
        result["duration_s"] = round(time.time() - started, 2)
        logger.info(f"[auto_process] Background run finished in {result['duration_s']}s")
        return result
    except Exception as e:
        logger.error(f"[auto_process] Background run failed: {e}")
        json_handler.log_operation("run_once", {"success": False, "error": str(e)})
        return {"success": False, "error": str(e)}
    finally:
        _release_lock()


def _load_pool_enabled() -> bool:
    return config_loader.section("memory_pool").get("enabled", False)


def run_pool_processing() -> Dict[str, Any]:
    """
    Process memory pool files if enabled.

    Checks config, calls process_memory_pool(), returns summary.
    Fast no-op when pool is empty or disabled.

    Returns:
        dict with success/skipped, files_processed, total_chunks
    """
    if not _load_pool_enabled():
        return {"skipped": True, "reason": "memory_pool disabled in config"}

    try:
        from aipass.memory.apps.handlers.intake.pool_processor import process_memory_pool

        pool_result = process_memory_pool()
        result = {
            "success": pool_result.get("success", False),
            "files_processed": pool_result.get("files_processed", 0),
            "total_chunks": pool_result.get("total_chunks", 0),
        }
        if pool_result.get("files_processed", 0) > 0:
            logger.info(
                f"[auto_process] Pool: {pool_result['files_processed']} files, "
                f"{pool_result.get('total_chunks', 0)} chunks"
            )

        json_handler.log_operation(
            "run_pool_processing",
            {
                "files_processed": result.get("files_processed", 0),
                "success": result.get("success", False),
            },
        )

        return result
    except Exception as e:
        logger.warning(f"[auto_process] Pool processing failed: {e}")
        return {"success": False, "error": str(e)}


def _run_rollover_check() -> Dict[str, Any]:
    """
    Check all branches for rollover triggers and execute if needed.

    Returns:
        dict with success/skipped and rollover details
    """
    try:
        from aipass.memory.apps.handlers.monitor.detector import check_all_branches

        check_result = check_all_branches()
        triggers = check_result.get("triggers", []) if check_result else []

        if not triggers:
            return {"skipped": True, "reason": "no rollover triggers"}

        from aipass.memory.apps.handlers.rollover.orchestrator import execute_rollover

        rollover_result = execute_rollover()
        result = {
            "success": rollover_result.get("success", False),
            "triggers": rollover_result.get("triggers_count", 0),
            "processed": rollover_result.get("success_count", 0),
        }
        logger.info(f"[auto_process] Rollover: {result['processed']}/{result['triggers']} triggers processed")
        return result
    except Exception as e:
        logger.warning(f"[auto_process] Rollover check failed: {e}")
        return {"success": False, "error": str(e)}


def auto_process() -> Dict[str, Any]:
    """
    Single idempotent entry point for session-start auto-processing.

    Processes memory pool files and checks/runs rollover if needed.
    Fast no-op when pool is empty and no rollover triggers.
    Safe to call every session.

    Returns:
        dict with success, pool, and rollover results
    """
    result: Dict[str, Any] = {"success": True, "pool": None, "rollover": None}

    if not _load_pool_enabled():
        result["pool"] = {"skipped": True, "reason": "memory_pool disabled in config"}
        result["rollover"] = {"skipped": True}
        logger.info("[auto_process] Skipped — memory_pool disabled in config")
        return result

    # 1. Process pool files
    pool_result = run_pool_processing()
    result["pool"] = pool_result
    if pool_result.get("success") is False:
        result["success"] = False

    # 2. Check/run rollover
    rollover_result = _run_rollover_check()
    result["rollover"] = rollover_result
    if rollover_result.get("success") is False:
        result["success"] = False

    json_handler.log_operation(
        "auto_process",
        {
            "pool_files": result.get("pool", {}).get("files_processed", 0),
            "rollover_triggered": not result.get("rollover", {}).get("skipped", False),
            "success": result["success"],
        },
    )

    return result


# =============================================================================
# STANDALONE EXECUTION -- this file IS the detached child
# =============================================================================

if __name__ == "__main__":
    print(json.dumps(run_once()))
