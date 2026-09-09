# =================== AIPass ====================
# Name: tick_lock.py
# Description: Single-instance lock for the scheduler tick
# Version: 1.0.0
# Created: 2026-09-08
# Modified: 2026-09-08
# =============================================

"""One tick at a time: the advisory lock the scheduler runs under.

The systemd timer fires every ~2 minutes and a slow tick can still be firing
wakes when the next one starts. Two ticks at once would each read the runstate,
each decide the same job is due, and each wake its owner — the double-fire this
lock exists to prevent.

Lives in a handler because it is the only thing in the tick lane that TOUCHES THE
FILESYSTEM: the lock directory and the lock file itself. A module may not do
direct file operations (seedgo's modules rule), and ``run.py`` was doing both
inline.

**The path is an argument, never a constant read from here.** ``run.py`` owns
``LOCK_FILE`` and passes it in, so a test that seams the path on the module still
seams what actually gets opened. A copy of the constant in this file would have
quietly re-pointed the suite at the live lock.

Advisory, not mandatory: on a host without ``fcntl`` (Windows) ``available()``
answers False and the caller runs unlocked rather than refusing to tick at all —
stated in the log, never silent.
"""

from typing import Optional

from aipass.prax import logger
from aipass.daemon.apps.handlers.json import json_handler

try:
    import fcntl
except ImportError:
    fcntl = None  # type: ignore[assignment]
    logger.info("[tick_lock] fcntl unavailable (Windows) — ticks run unlocked")


def available() -> bool:
    """Can this host hold the lock at all? False on Windows."""
    return fcntl is not None


def prepare(lock_path) -> None:
    """Make sure the lock's directory exists. Safe to call on every tick."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)


def acquire(lock_path) -> Optional[object]:
    """Take the tick lock. Returns a handle to release, or None if another tick holds it.

    None is the ordinary answer, not an error: the previous tick is still
    working, and this one simply steps aside until the next timer fire.
    """
    if fcntl is None:
        return None

    handle = open(lock_path, "w", encoding="utf-8")  # noqa: SIM115
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as e:
        logger.info("[tick_lock] Lock acquisition failed (another instance running): %s", e)
        handle.close()
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
