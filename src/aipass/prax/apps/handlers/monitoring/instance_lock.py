# =================== AIPass ====================
# Name: instance_lock.py
# Description: Single-instance lock for the prax monitor
# Version: 2.0.0
# Created: 2026-07-10
# Modified: 2026-10-24
# =============================================

"""Single-instance lock for the prax monitor's fleet-wide duties (the log rate tracker).

An flock held on an open fd for the process lifetime: the kernel drops it when the
process dies, so there is no stale pidfile to judge. The file lives outside
system_logs/: inside, the tailed directory would feed back on itself.
"""

import os
from pathlib import Path
from typing import IO, Optional

try:
    import fcntl
except ImportError:  # Windows: no lock, every monitor takes the duties
    fcntl = None  # type: ignore[assignment]

from aipass.prax.apps.modules.logger import get_direct_logger
from aipass.prax.apps.handlers.json import json_handler

logger = get_direct_logger()

_lock_path_override: Optional[Path] = None
_held_file: Optional[IO[str]] = None


def get_lock_path() -> Path:
    """Return the path for the monitor lock file (prax/prax_json/monitor.lock)."""
    if _lock_path_override is not None:
        return _lock_path_override
    return Path(__file__).resolve().parents[3] / "prax_json" / "monitor.lock"


def try_acquire() -> bool:
    """Take the lock without blocking. True if this process now holds it."""
    global _held_file
    json_handler.log_operation("instance_lock_acquire", {"pid": os.getpid()})
    if fcntl is None:
        return True
    lock_path = get_lock_path()
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_file = open(lock_path, "a+", encoding="utf-8")
    try:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        lock_file.close()
        logger.info("[instance_lock] Another monitor holds %s", lock_path)
        return False
    lock_file.truncate(0)
    lock_file.write(str(os.getpid()))
    lock_file.flush()
    _held_file = lock_file
    logger.info("[instance_lock] Acquired (PID %d)", os.getpid())
    return True


def release() -> None:
    """Drop the lock if held. The file stays: unlinking it would race a waiting opener."""
    global _held_file
    if _held_file is not None:
        _held_file.close()
        _held_file = None
        logger.info("[instance_lock] Released")
    json_handler.log_operation("instance_lock_release", {"pid": os.getpid()})
