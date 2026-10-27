# =================== AIPass ====================
# Name: auto_process.py
# Description: Automated pool + rollover entry point
# Version: 1.2.0
# Created: 2026-06-06
# Modified: 2026-10-27
# =============================================

"""
Auto-process handler — session-start pool + rollover entry point.

The hook calls spawn_background() (returns in milliseconds). auto_process() is the
synchronous API and must NOT run from a UserPromptSubmit hook: it takes minutes with
a backlog and feeds the prompt nothing. A detached child, not a @daemon schedule, so
a down service never silently stops vectorizing. Idempotent: pool writes are upserts.
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
from aipass.memory.apps.handlers.repo_root import module_file

_MEMORY_ROOT = module_file(__file__).parent.parent.parent.parent

# Single-flight: two concurrent rollovers would write the same .trinity files.
# Staleness is time-based (cross-platform), so a crashed child frees the lane.
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
    """Create the lock exclusively: True taken, None held elsewhere, False on OS error."""
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

    Never raises: a hook that dies takes the whole prompt with it.
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
        child = subprocess.Popen([sys.executable, str(module_file(__file__))], **kwargs)
    except Exception as e:
        logger.error(f"[auto_process] Spawn failed: {e}")
        json_handler.log_operation("spawn_background", {"success": False, "error": str(e)})
        return {"success": False, "error": str(e), "pid": None}
    finally:
        log_handle.close()

    logger.info(f"[auto_process] Spawned background run (pid {child.pid})")
    json_handler.log_operation("spawn_background", {"success": True, "pid": child.pid})
    return {"success": True, "skipped": False, "pid": child.pid}


def _completion_status(section: Dict[str, Any] | None) -> str:
    """Map one section of the result onto @trigger's ``status`` vocabulary.

    A section that never reported (the crash leg) is ``"unknown"``, never ``"ok"``.
    """
    if not section:
        return "unknown"
    if section.get("skipped"):
        return "skipped"
    if section.get("success") is False:
        return "failed"
    return "ok"


def _fire_completion(result: Dict[str, Any]) -> None:
    """Announce a finished auto-process run on @trigger's bus.

    Only this child is present when the work ends, so the fire lives here. Fired on
    BOTH outcomes: failure becomes @trigger's error_detected (medic dispatch). The
    payload is @trigger's contract (handlers/events/memory_pool.py); branch="memory"
    so the owner is woken. Never raises.
    """
    try:
        from aipass.trigger.apps.modules.core import trigger

        pool = result.get("pool") or {}
        rollover = result.get("rollover") or {}
        trigger.fire(
            "memory_pool_auto_processed",
            success=bool(result.get("success")),
            branch="memory",
            pool={
                "status": _completion_status(pool),
                "files_processed": pool.get("files_processed", 0),
                "total_chunks": pool.get("total_chunks", 0),
            },
            rollover={
                "status": _completion_status(rollover),
                "triggers": rollover.get("triggers", 0),
                "processed": rollover.get("processed", 0),
            },
            error=result.get("error"),
        )
    except Exception as e:
        logger.warning(f"[auto_process] memory_pool_auto_processed fire failed: {e}")


def run_once() -> Dict[str, Any]:
    """Child entry point: take the lock, do the work, always give the lock back."""
    if not _acquire_lock():
        # Not a completion: the lock holder fires its own announcement.
        logger.info("[auto_process] Another run holds the lock -- declining")
        return {"success": True, "skipped": True, "reason": "another run holds the lock"}

    started = time.time()
    try:
        result = auto_process()
        result["duration_s"] = round(time.time() - started, 2)
        logger.info(f"[auto_process] Background run finished in {result['duration_s']}s")
        _fire_completion(result)
        return result
    except Exception as e:
        logger.error(f"[auto_process] Background run failed: {e}")
        json_handler.log_operation("run_once", {"success": False, "error": str(e)})
        failed = {"success": False, "error": str(e)}
        _fire_completion(failed)
        return failed
    finally:
        _release_lock()


def _load_pool_enabled() -> bool:
    return config_loader.section("memory_pool").get("enabled", False)


def run_pool_processing() -> Dict[str, Any]:
    """Process memory pool files if enabled; a fast no-op when empty or disabled."""
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
    """Check all branches for rollover triggers and execute if needed."""
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
    """Single idempotent entry point for session-start auto-processing."""
    result: Dict[str, Any] = {"success": True, "pool": None, "rollover": None}

    if not _load_pool_enabled():
        result["pool"] = {"skipped": True, "reason": "memory_pool disabled in config"}
        result["rollover"] = {"skipped": True}
        logger.info("[auto_process] Skipped — memory_pool disabled in config")
        return result

    pool_result = run_pool_processing()
    result["pool"] = pool_result
    if pool_result.get("success") is False:
        result["success"] = False

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


def run_locked() -> Dict[str, Any]:
    """Run auto_process in the foreground under the lane lock the background child takes.

    A live holder answers held with its pid: two runs on one pool would race the same files.
    """
    if not _acquire_lock():
        holder = _read_lock() or {}
        return {"success": False, "held": True, "pid": holder.get("pid")}
    try:
        return auto_process()
    finally:
        _release_lock()


# This file IS the detached child.

if __name__ == "__main__":
    print(json.dumps(run_once()))
