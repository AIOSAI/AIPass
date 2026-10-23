# =================== AIPass ====================
# Name: file_lock.py
# Description: One exclusive file lock for this branch's read-modify-write JSON stores
# Version: 1.0.0
# Created: 2026-10-22
# Modified: 2026-10-22
# =============================================

"""One exclusive file lock, shared by the watch registry and the feedback inbox."""

from pathlib import Path

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.devpulse.apps.handlers.json import json_handler

try:
    import fcntl  # POSIX advisory locks: absent on Windows, so the lock door reads this, not sys.platform
except ImportError as exc:  # pragma: no cover - the host that lacks it is the Windows runner
    fcntl = None  # type: ignore[assignment]
    logger.info("[file_lock] fcntl absent on this host, store writes run unlocked: %s", exc)


class FileLock:
    """Exclusive lock on a sibling .lock file (fcntl where it exists, no-op without it).

    A sibling, because os.replace on the data file would swap the inode out from under the lock.
    """

    def __init__(self, storage_path: Path) -> None:
        self._lock_path = storage_path.with_suffix(storage_path.suffix + ".lock")
        self._fh = None

    def __enter__(self) -> "FileLock":
        if fcntl is None:
            json_handler.log_operation("file_lock_unavailable", {"path": str(self._lock_path)})
            return self
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self._lock_path, "a+", encoding="utf-8")
        fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if fcntl is not None and self._fh is not None:
            try:
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
            finally:
                self._fh.close()
                self._fh = None
