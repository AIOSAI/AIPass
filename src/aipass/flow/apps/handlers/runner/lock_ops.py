# =================== AIPass ====================
# Name: lock_ops.py
# Description: Process lock file operations handler
# Version: 1.3.0
# Created: 2026-04-22
# Modified: 2026-10-23
# =============================================

"""
Lock File Operations Handler
"""

import os
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO, Iterator

from aipass.prax import logger

from aipass.flow.apps.handlers.json import json_handler

try:
    import fcntl
except ImportError as exc:
    logger.debug("fcntl unavailable, using msvcrt: %s", exc)
    fcntl = None  # type: ignore[assignment]
try:
    import msvcrt
except ImportError as exc:
    logger.debug("msvcrt unavailable, using fcntl: %s", exc)
    msvcrt = None  # type: ignore[assignment]

# Delete-pending clears in milliseconds; a real permissions problem should surface fast.
_CREATE_RETRIES = 5
_CREATE_BACKOFF_BASE = 0.05
# A pidless lock is a writer between create and pid write, or one that died there; past this, dead.
_UNREADABLE_LOCK_GRACE = 10.0


def _sleep(seconds: float) -> None:
    """time.sleep(seconds), the create backoff's wait; a seam so tests never patch time.sleep."""
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


def _create_exclusive(lock_file: Path) -> int:
    """os.open(lock_file, O_CREAT | O_EXCL | O_WRONLY): the lock's one create.

    A seam: tests hand in Windows' delete-pending PermissionError here, which Linux cannot produce.
    """
    return os.open(str(lock_file), os.O_CREAT | os.O_EXCL | os.O_WRONLY)


def try_create_lock(lock_file: Path) -> bool:
    """Atomically create lock file with current PID. Returns True on success.

    FileExistsError: False at once. Delete-pending PermissionError: retried, then raised chained.
    """
    denial: PermissionError | None = None
    waited = 0.0
    for attempt in range(_CREATE_RETRIES):
        try:
            fd = _create_exclusive(lock_file)
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
    """Age a lock that holds no pid: held inside _UNREADABLE_LOCK_GRACE, stale past it."""
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

    Raises OSError when the lock exists but cannot be read: no proof the holder is dead.
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

    False only for a live holder; denied, unreadable or unremovable locks raise OSError instead.
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


def _try_os_lock(fh: BinaryIO) -> bool:
    """Take an exclusive OS lock on fh without blocking; True when taken."""
    if msvcrt is not None:
        try:
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)  # type: ignore[attr-defined]  # Windows-only
            return True
        except OSError:
            return False
    assert fcntl is not None
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except BlockingIOError:
        return False


def _os_unlock(fh: BinaryIO) -> None:
    """Drop the OS lock _try_os_lock took."""
    if msvcrt is not None:
        fh.seek(0)
        msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)  # type: ignore[attr-defined]  # Windows-only
        return
    assert fcntl is not None
    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


@contextmanager
def os_file_lock(lock_file: Path, timeout: float = 30.0, poll: float = 0.05) -> Iterator[None]:
    """Hold an exclusive OS lock on lock_file, polling until timeout; raises TimeoutError past it.

    The OS drops the lock when its holder dies, so it is never stale and the file is never deleted.
    """
    with open(lock_file, "a+b") as fh:
        deadline = time.monotonic() + timeout
        while not _try_os_lock(fh):
            if time.monotonic() >= deadline:
                raise TimeoutError(f"{lock_file} is held by another process past {timeout:.0f}s")
            _sleep(poll)
        try:
            yield
        finally:
            _os_unlock(fh)


def release_lock(lock_file: Path) -> None:
    """Release the lock file."""
    try:
        lock_file.unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("Failed to release lock file %s: %s", lock_file, exc)
