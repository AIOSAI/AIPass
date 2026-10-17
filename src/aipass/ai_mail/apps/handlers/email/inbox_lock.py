# =================== AIPass ====================
# Name: inbox_lock.py
# Description: Inbox File Lock Handler
# Version: 1.0.0
# Created: 2026-02-09
# Modified: 2026-10-17
# =============================================

"""
Inbox File Lock Handler
"""

import sys
from pathlib import Path
from contextlib import contextmanager

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.ai_mail.apps.handlers.json import json_handler


if sys.platform == "win32":
    import msvcrt
else:
    import fcntl


@contextmanager
def inbox_lock(inbox_file: Path):
    """Context manager that acquires an exclusive lock on an inbox.json file.

    The lock lives on a sibling .inbox.lock so writers can truncate inbox.json while holding it.
    """
    json_handler.log_operation("inbox_lock", {"inbox_file": str(inbox_file)})
    lock_file = inbox_file.parent / ".inbox.lock"
    lock_fd = None

    try:
        lock_fd = open(lock_file, "w", encoding="utf-8")

        if sys.platform == "win32":
            msvcrt.locking(lock_fd.fileno(), msvcrt.LK_LOCK, 1)
        else:
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX)
        yield

    finally:
        if lock_fd is not None:
            try:
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
