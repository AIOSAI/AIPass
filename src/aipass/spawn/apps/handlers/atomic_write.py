# =================== AIPass ====================
# Name: atomic_write.py
# Description: Atomic file write helper — stage, fsync, os.replace
# Version: 1.1.1
# Created: 2026-08-16
# Modified: 2026-11-14
# =============================================

"""Atomic text writes for every spawn handler that touches a live file."""

import os
import tempfile
from pathlib import Path

__all__ = ["atomic_write_text"]


def atomic_write_text(path, content: str, encoding: str = "utf-8") -> None:
    """Write text to ``path`` atomically, replacing any existing file."""
    path = Path(path)
    # mkstemp stages at 0600; the swap keeps the target's mode, or a plain open()'s for a new file.
    if path.exists():
        mode = path.stat().st_mode & 0o7777
    else:
        umask = os.umask(0)
        os.umask(umask)
        mode = 0o666 & ~umask

    # Stage in the target's own directory: os.replace across filesystems raises EXDEV.
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    closed = False
    try:
        os.write(fd, content.encode(encoding))
        os.fsync(fd)
        os.close(fd)
        closed = True
        os.chmod(tmp_path, mode)
        os.replace(tmp_path, str(path))
    except BaseException:
        if not closed:
            os.close(fd)
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise
