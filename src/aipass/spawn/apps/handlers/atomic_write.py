# =================== AIPass ====================
# Name: atomic_write.py
# Description: Atomic file write helper — stage, fsync, os.replace
# Version: 1.1.0
# Created: 2026-08-16
# Modified: 2026-10-17
# =============================================

"""Atomic text writes for every spawn handler that touches a live file."""

import os
import tempfile
import time
from pathlib import Path

__all__ = ["atomic_write_text"]


# Windows os.replace raises PermissionError while any reader holds the target open;
# readers hold handles for microseconds, so a bounded retry converges, then raises.
_REPLACE_ATTEMPTS = 40
_REPLACE_BACKOFF_SECONDS = 0.005


def _replace_with_retry(source: str, destination: str) -> None:
    """os.replace that tolerates Windows sharing violations, bounded."""
    for attempt in range(_REPLACE_ATTEMPTS):
        try:
            os.replace(source, destination)
            return
        except PermissionError:
            if attempt == _REPLACE_ATTEMPTS - 1:
                raise
            time.sleep(_REPLACE_BACKOFF_SECONDS)


def atomic_write_text(path, content: str, encoding: str = "utf-8") -> None:
    """Write text to ``path`` atomically, replacing any existing file."""
    path = Path(path)

    # Stage in the target's own directory: os.replace across filesystems raises EXDEV.
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    closed = False
    try:
        os.write(fd, content.encode(encoding))
        os.fsync(fd)
        os.close(fd)
        closed = True
        _replace_with_retry(tmp_path, str(path))
    except BaseException:
        if not closed:
            os.close(fd)
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise
