# =================== AIPass ====================
# Name: inbox_lock.py
# Description: Inbox File Lock Handler
# Version: 1.0.0
# Created: 2026-02-09
# Modified: 2026-02-09
# =============================================

"""
Inbox File Lock Handler

Provides exclusive file locking for inbox.json read-modify-write operations.
Uses fcntl.flock (POSIX advisory locks) to prevent concurrent write corruption.

Usage:
    with inbox_lock(inbox_file):
        data = json.load(open(inbox_file, encoding='utf-8'))
        # ... modify data ...
        json.dump(data, open(inbox_file, 'w', encoding='utf-8'))
"""

import sys
from pathlib import Path
from contextlib import contextmanager

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.ai_mail.apps.handlers.json import json_handler

# fcntl is POSIX-only (Linux/macOS). On Windows, use msvcrt for locking.
if sys.platform == "win32":
    import msvcrt
else:
    import fcntl


@contextmanager
def inbox_lock(inbox_file: Path):
    """
    Context manager that acquires an exclusive lock on an inbox.json file.

    Uses a separate .inbox.lock file adjacent to inbox.json to hold the
    fcntl.flock advisory lock. This avoids issues with truncating the
    locked file itself during writes.

    Args:
        inbox_file: Path to the inbox.json file to lock

    Yields:
        None - lock is held for the duration of the with block

    Raises:
        OSError: If lock cannot be acquired
    """
    json_handler.log_operation("inbox_lock", {"inbox_file": str(inbox_file)})
    lock_file = inbox_file.parent / ".inbox.lock"
    lock_fd = None

    try:
        # Create/open lock file
        lock_fd = open(lock_file, "w", encoding="utf-8")

        # Acquire exclusive lock (blocking - waits for other processes)
        if sys.platform == "win32":
            msvcrt.locking(lock_fd.fileno(), msvcrt.LK_LOCK, 1)
        else:
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX)
        yield

    finally:
        if lock_fd is not None:
            try:
                # Release lock
                if sys.platform == "win32":
                    msvcrt.locking(lock_fd.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
                lock_fd.close()
            except Exception as e:
                logger.warning("[lock] lock release failed: %s", e)
                try:
                    lock_fd.close()
                except Exception as e:
                    logger.warning("[lock] lock file close failed: %s", e)
