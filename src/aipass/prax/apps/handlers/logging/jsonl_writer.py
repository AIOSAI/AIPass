# =================== AIPass ====================
# Name: jsonl_writer.py
# Description: JSONL append with size-based rotation
# Version: 1.0.0
# Created: 2026-07-10
# Modified: 2026-10-23
# =============================================

"""PRAX JSONL Writer

Standalone: no prax logging pipeline, event system or stack introspection, so any
branch can call it, including @trigger event handlers where importing the prax
logger would recurse. Import it as `from aipass.prax import append_jsonl`.
"""

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Union

from aipass.prax.apps.handlers.logging.setup import rotation_lock

logger = logging.getLogger(__name__)

JSONL_MAX_BYTES = 500_000  # 500 KB per file
JSONL_BACKUP_COUNT = 1


def append_jsonl(
    filepath: Union[str, Path],
    data: Dict[str, Any],
    *,
    max_bytes: int = JSONL_MAX_BYTES,
    backup_count: int = JSONL_BACKUP_COUNT,
) -> None:
    """Append a JSON object as a single line, rotating when the file exceeds max_bytes."""
    filepath = Path(filepath)
    filepath.parent.mkdir(parents=True, exist_ok=True)

    _maybe_rotate(filepath, max_bytes, backup_count)

    line = json.dumps(data, default=str, ensure_ascii=False) + "\n"
    with open(filepath, "a", encoding="utf-8") as f:
        f.write(line)


def _rotate_with_backup(filepath: Path) -> None:
    """Rename file to .1 backup; fall back to unlink on failure."""
    backup = filepath.parent / f"{filepath.name}.1"
    try:
        os.replace(str(filepath), str(backup))
    except OSError as exc:
        logger.warning("JSONL rotation rename failed for %s: %s — unlinking instead", filepath, exc)
        _unlink_safe(filepath)


def _unlink_safe(filepath: Path) -> None:
    """Remove file, logging on failure."""
    try:
        filepath.unlink()
    except OSError as exc:
        logger.warning("Failed to unlink oversized JSONL %s: %s", filepath, exc)


def _over_limit(filepath: Path, max_bytes: int) -> bool:
    """True when the file exists and has reached max_bytes."""
    try:
        return filepath.stat().st_size >= max_bytes
    except FileNotFoundError:
        return False
    except OSError as exc:
        logger.warning("Cannot stat %s for rotation check: %s", filepath, exc)
        return False


def _maybe_rotate(filepath: Path, max_bytes: int, backup_count: int) -> None:
    """Rotate the file if it exceeds max_bytes, once across processes."""
    if not _over_limit(filepath, max_bytes):
        return

    with rotation_lock(filepath):
        # Checked again under the lock: another writer may have just rotated it.
        if not _over_limit(filepath, max_bytes):
            return
        if backup_count >= 1:
            _rotate_with_backup(filepath)
        else:
            _unlink_safe(filepath)
