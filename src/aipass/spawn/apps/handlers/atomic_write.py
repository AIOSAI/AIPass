# =================== AIPass ====================
# Name: atomic_write.py
# Description: Atomic file write helper — stage, fsync, os.replace
# Version: 1.1.0
# Created: 2026-08-16
# Modified: 2026-08-18
# =============================================

"""Atomic text writes for every spawn handler that touches a live file.

A plain truncating write — write mode on the target itself, whether through the
builtin or ``Path.write_text(...)`` — empties the file before the new bytes
arrive. A reader that lands between the truncate and the write sees an empty or
half-written file — measured at 38.17% unusable reads against spawn's passport
write path under two writers and two readers.

The shape here removes that window entirely: the new bytes are staged in a temp
file *in the target's own directory*, flushed to disk, and then swapped in with
``os.replace``. A concurrent reader sees either the whole old file or the whole
new file, never a gap.

Two details are load-bearing:

* ``tempfile.mkstemp(dir=target.parent)`` — staging must share a filesystem with
  the target or ``os.replace`` raises EXDEV instead of renaming. A /tmp-based
  temp file would break the swap on any box where /tmp is its own mount. mkstemp
  also mints a unique name, so two concurrent writers never stage over each
  other the way a fixed ``.tmp`` suffix does.
* ``os.replace`` rather than ``Path.rename`` — rename refuses an existing
  destination on Windows, which is exactly the case every caller here hits.

On any failure the staged temp is removed and the exception is re-raised. This
function never swallows an error: callers own the decision to abort or continue,
and several of them already catch ``OSError``/``IOError`` and carry on.
"""

import os
import tempfile
import time
from pathlib import Path

__all__ = ["atomic_write_text"]


# os.replace on Windows raises PermissionError while ANY reader holds the
# target open (no FILE_SHARE_DELETE on Python's open). Readers hold handles
# for microseconds, so a short bounded retry converges; after the bound the
# error raises honestly. POSIX never takes this path for open files, so a
# genuine permission problem still surfaces — just ~200ms later.
_REPLACE_ATTEMPTS = 40
_REPLACE_BACKOFF_SECONDS = 0.005


def _replace_with_retry(source: str, destination: str) -> None:
    """
    os.replace that tolerates Windows sharing violations, bounded.

    Args:
        source: Staged file to move into place.
        destination: The live document being replaced.

    Raises:
        PermissionError: Still blocked after every attempt.
        OSError: Any non-sharing failure, immediately.
    """
    for attempt in range(_REPLACE_ATTEMPTS):
        try:
            os.replace(source, destination)
            return
        except PermissionError:
            if attempt == _REPLACE_ATTEMPTS - 1:
                raise
            time.sleep(_REPLACE_BACKOFF_SECONDS)


def atomic_write_text(path, content: str, encoding: str = "utf-8") -> None:
    """Write text to ``path`` atomically, replacing any existing file.

    Args:
        path: Target file path. Its parent directory must already exist.
        content: Text to write. Encoded with ``encoding`` before staging.
        encoding: Text encoding for the payload. Defaults to UTF-8.

    Raises:
        OSError: If staging, writing, syncing, or the final swap fails.
        UnicodeEncodeError: If ``content`` cannot be encoded.
        Any other exception raised while staging — nothing is swallowed.

    The target is left untouched whenever the write does not complete, and the
    staged temp file is removed on every failure path.

    The swap goes through _replace_with_retry, not a bare os.replace: on
    Windows a reader holding the target open turns the move into a
    PermissionError, and one stuck move starved a whole CI run (2026-08-18).
    Bounded, then it raises honestly.
    """
    path = Path(path)

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
