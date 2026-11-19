# =================== AIPass ====================
# Name: jsonl_writer.py
# Description: JSONL append with size-based rotation
# Version: 1.2.0
# Created: 2026-07-10
# Modified: 2026-11-15
# =============================================

"""PRAX JSONL Writer: stdlib only, so code where the prax logger would recurse can call it; every failure raises."""

import fcntl
import json
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, Union

JSONL_MAX_BYTES = 500_000  # 500 KB per file
JSONL_BACKUP_COUNT = 1


@contextmanager
def rotation_lock(path: Path) -> Iterator[None]:
    """Exclusive cross-process lock on '<path>.lock' while a file rotates or is appended."""
    with open(f"{path}.lock", "a", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        yield


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
    line = json.dumps(data, default=str, ensure_ascii=False) + "\n"

    # Check, rotate and append under one lock, or a racing writer's line lands in the renamed backup.
    with rotation_lock(filepath):
        if _over_limit(filepath, max_bytes):
            _rotate(filepath, backup_count)
        with open(filepath, "a", encoding="utf-8") as f:
            f.write(line)


def _backup(filepath: Path, n: int) -> Path:
    """The n-th backup of filepath: name.n."""
    return filepath.parent / f"{filepath.name}.{n}"


def _rotate(filepath: Path, backup_count: int) -> None:
    """Shift .N-1 -> .N ... .1 -> .2, then file -> .1; the oldest beyond N is overwritten. 0 deletes the file."""
    if backup_count < 1:
        filepath.unlink()
        return
    for n in range(backup_count - 1, 0, -1):
        older = _backup(filepath, n)
        if older.exists():
            os.replace(older, _backup(filepath, n + 1))
    os.replace(filepath, _backup(filepath, 1))


def _over_limit(filepath: Path, max_bytes: int) -> bool:
    """True when the file exists and has reached max_bytes."""
    try:
        return filepath.stat().st_size >= max_bytes
    except FileNotFoundError:
        return False
