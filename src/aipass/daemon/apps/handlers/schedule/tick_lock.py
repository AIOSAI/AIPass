# =================== AIPass ====================
# Name: tick_lock.py
# Description: Single-instance lock for the scheduler tick
# Version: 1.0.0
# Created: 2026-09-08
# Modified: 2026-10-17
# =============================================

"""One tick at a time: the advisory lock the scheduler runs under.

Reference: docs/scheduler_tick.md
"""

import errno
from typing import Optional

from aipass.prax import logger
from aipass.daemon.apps.handlers.json import json_handler

try:
    import fcntl
except ImportError:
    fcntl = None  # type: ignore[assignment]
    logger.info("[tick_lock] fcntl unavailable (Windows) — ticks run unlocked")

_CONTENDED = frozenset({errno.EAGAIN, errno.EWOULDBLOCK, errno.EACCES})


def available() -> bool:
    """Can this host hold the lock at all? False on Windows."""
    return fcntl is not None


def prepare(lock_path) -> None:
    """Make sure the lock's directory exists. Safe to call on every tick."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)


def acquire(lock_path) -> Optional[object]:
    """Take the tick lock. Returns a handle to release, or None if another tick holds it.

    Raises OSError on a non-contention flock failure: None there would report a running tick forever.
    """
    if fcntl is None:
        return None

    handle = open(lock_path, "w", encoding="utf-8")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as e:
        handle.close()
        if e.errno not in _CONTENDED:
            logger.error("[tick_lock] Lock acquisition failed, not contention: %s", e)
            raise
        logger.info("[tick_lock] Lock acquisition failed (another instance running): %s", e)
        return None

    json_handler.log_operation("tick_lock_acquired", {"path": str(lock_path)})
    return handle


def release(handle) -> None:
    """Drop the lock and close the file. Never raises — a tick must not fail on teardown."""
    if handle is None:
        return
    try:
        if fcntl is not None:
            fcntl.flock(handle, fcntl.LOCK_UN)
    except OSError as e:
        logger.warning("[tick_lock] could not unlock cleanly: %s", e)
    finally:
        handle.close()
