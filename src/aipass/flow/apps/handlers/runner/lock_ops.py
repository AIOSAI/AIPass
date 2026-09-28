# =================== AIPass ====================
# Name: lock_ops.py
# Description: Process lock file operations handler
# Version: 1.1.0
# Created: 2026-04-22
# Modified: 2026-09-28
# =============================================

"""
Lock File Operations Handler

Provides atomic lock file management for background runners.
Uses O_CREAT | O_EXCL to avoid TOCTOU races between existence check and write.

On Windows a create against a lock the previous runner is still removing
(delete-pending) raises PermissionError, not FileExistsError. That is a lock
being released, so try_create_lock retries it on a short bounded budget and
raises only when the denial outlasts it.

Usage:
    from aipass.flow.apps.handlers.runner.lock_ops import (
        acquire_lock, release_lock
    )
"""

import os
import sys
import time
from pathlib import Path

from aipass.prax import logger

from aipass.flow.apps.handlers.json import json_handler

# A delete-pending lock clears in milliseconds; a detached runner should not
# sit out a long budget before reporting a real permissions problem.
_CREATE_RETRIES = 5
_CREATE_BACKOFF_BASE = 0.05
# A lock with no pid in it is a writer between its exclusive create and its pid
# write (microseconds) or a writer that died there. Past this age it is the latter.
_UNREADABLE_LOCK_GRACE = 10.0


def _sleep(seconds: float) -> None:
    """time.sleep(seconds), the create backoff's wait.

    The reason is the tests alone: they patch this name so the backoff neither
    waits nor replaces time.sleep for the whole process.
    """
    time.sleep(seconds)


def _pid_alive_windows(pid: int) -> bool:
    """Windows-safe liveness check via OpenProcess + GetExitCodeProcess."""
    import ctypes
    from ctypes import wintypes

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    STILL_ACTIVE = 259

    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]  # Windows-only
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False
    try:
        exit_code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return False
        return exit_code.value == STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def _pid_alive(pid: int) -> bool:
    """Return True if the process is alive. Platform-guarded: win32 uses
    OpenProcess instead of os.kill (which terminates on Windows)."""
    if sys.platform == "win32":
        try:
            return _pid_alive_windows(pid)
        except Exception as exc:
            logger.info("PID %s Windows check failed (assuming alive): %s", pid, exc)
            return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError as exc:
        logger.info("PID %s not found: %s", pid, exc)
        return False
    except PermissionError as exc:
        logger.info("PID %s permission denied (alive): %s", pid, exc)
        return True
    except OSError as exc:
        logger.info("PID %s os.kill error (assuming dead): %s", pid, exc)
        return False
    return True


def try_create_lock(lock_file: Path) -> bool:
    """Atomically create lock file with current PID. Returns True on success.

    FileExistsError returns False at once: acquire_lock's stale check reads
    the holder next. A Windows delete-pending PermissionError means the
    previous holder is mid-release, so it is retried with backoff.

    Raises:
        PermissionError: Still denied after the retry budget. Chained from
            the last denial, so a real permissions problem surfaces.
    """
    denial: PermissionError | None = None
    waited = 0.0
    for attempt in range(_CREATE_RETRIES):
        try:
            fd = os.open(str(lock_file), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            return True
        except FileExistsError:
            logger.info("Lock file already exists, cannot acquire: %s", lock_file)
            return False
        except PermissionError as exc:
            denial = exc
            logger.info("Lock file create denied (delete-pending?), retry %d: %s: %s", attempt + 1, lock_file, exc)
        delay = _CREATE_BACKOFF_BASE * (2**attempt)
        _sleep(delay)
        waited += delay
    raise PermissionError(
        f"Lock {lock_file} still denied after {_CREATE_RETRIES} attempts ({waited:.2f}s waited)"
    ) from denial


def _pidless_lock_is_stale(lock_file: Path) -> bool:
    """Age a lock that holds no pid: held inside _UNREADABLE_LOCK_GRACE, stale past it.

    Raises:
        OSError: The stat fails for any reason but the lock being gone.
    """
    try:
        age = time.time() - lock_file.stat().st_mtime
    except FileNotFoundError:
        logger.info("Lock released before it could be aged, taking over: %s", lock_file)
        return True
    if age < _UNREADABLE_LOCK_GRACE:
        logger.info("Lock without a pid is %.1fs old, treating as held: %s", age, lock_file)
        return False
    logger.info("Stale lock found (no pid for %.1fs), taking over: %s", age, lock_file)
    return True


def is_lock_stale(lock_file: Path) -> bool:
    """Check if existing lock file belongs to a dead process.

    A lock gone before it is read was released: stale, take over. A lock
    without a pid (empty, or not an integer) is held while younger than
    _UNREADABLE_LOCK_GRACE: try_create_lock creates the file before it writes
    the pid, and a reader in that gap must not unlink a live holder's lock.
    Older than the grace, its writer died mid-create: stale.

    Raises:
        OSError: The lock exists but cannot be read or stat'ed (not
            FileNotFoundError). That is no proof the holder is dead, so it is
            not reported as stale (flow's decision, leg 3).
    """
    try:
        text = lock_file.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        logger.info("Lock released before it could be read, taking over: %s", lock_file)
        return True
    pid: int | None
    try:
        pid = int(text)
    except ValueError as exc:
        logger.info("Lock holds no pid, ageing it: %s: %s", lock_file, exc)
        pid = None
    if pid is None:
        return _pidless_lock_is_stale(lock_file)
    if _pid_alive(pid):
        logger.info("Another instance running (PID %d), lock valid: %s", pid, lock_file)
        return False
    logger.info("Stale lock found (PID %d dead), taking over: %s", pid, lock_file)
    return True


def acquire_lock(lock_file: Path) -> bool:
    """Try to acquire lock file. Returns True if acquired.

    Uses atomic O_CREAT | O_EXCL to avoid TOCTOU race. False means another
    live process holds the lock (or a lock without a pid, inside its grace).

    Raises:
        PermissionError: From try_create_lock, when the create is still denied
            after its retry budget. Not contention, so never reported as False.
        OSError: From is_lock_stale, when the lock exists but cannot be read;
            or from removing a stale lock, when the unlink is refused. Neither
            is a live holder, so neither is reported as False (flow's decision,
            leg 3).
    """
    if try_create_lock(lock_file):
        json_handler.log_operation("lock_acquired", {"lock_file": str(lock_file)})
        return True

    if not is_lock_stale(lock_file):
        return False

    # Gone already (released between the read and here) is fine; refused is raised.
    lock_file.unlink(missing_ok=True)

    if not try_create_lock(lock_file):
        logger.info("Another process grabbed lock during retry: %s", lock_file)
        return False

    json_handler.log_operation("lock_acquired", {"lock_file": str(lock_file), "stale_recovery": True})
    return True


def release_lock(lock_file: Path) -> None:
    """Release the lock file."""
    try:
        lock_file.unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("Failed to release lock file %s: %s", lock_file, exc)
