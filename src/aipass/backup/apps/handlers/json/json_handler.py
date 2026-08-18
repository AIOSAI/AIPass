# =================== AIPass ====================
# Name: json_handler.py
# Description: Generic JSON ops — read/write, self-healing, atomic writes
# Version: 1.1.0
# Created: 2026-04-17
# Modified: 2026-08-18
# =============================================

"""JSON handler — generic persistence utilities shared across backup modules."""

import json
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from aipass.prax import append_jsonl, logger


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


def log_operation(operation: str, data: dict) -> None:
    """Record an operation entry to the backup system log."""
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "operation": operation,
        **data,
    }
    log_file = Path(__file__).resolve().parents[3] / "logs" / "operations.jsonl"
    try:
        append_jsonl(log_file, entry)
    except OSError as e:
        logger.warning(f"Failed to write operation log: {e}")


def load_json(path: str) -> dict:
    """Load JSON from path with self-healing on corruption."""
    p = Path(path)
    if not p.exists():
        return {}
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning(f"Corrupt JSON at {p}, renaming to .corrupt: {e}")
        corrupt = p.with_suffix(p.suffix + ".corrupt")
        p.rename(corrupt)
        return {}


def save_json(path: str, data: dict) -> None:
    """Atomic write JSON to path (write temp -> rename).

    Note:
        The swap goes through _replace_with_retry, not a bare os.replace: on
        Windows a reader holding the target open turns the move into a
        PermissionError, and one stuck move starved a whole CI run
        (2026-08-18). Bounded, then it raises honestly.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=p.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)
            f.write("\n")
        _replace_with_retry(tmp, str(p))
    except Exception:
        try:
            os.unlink(tmp)
        except OSError as e:
            logger.warning(f"Failed to clean up temp file {tmp}: {e}")
        raise


# =============================================
