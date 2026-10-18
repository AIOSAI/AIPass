# =================== AIPass ====================
# Name: files.py
# Description: Atomic read/write for hooks arbitrary-path JSON documents, and their directories
# Version: 1.2.0
# Created: 2026-09-03
# Modified: 2026-10-17
# =============================================

"""Arbitrary-path JSON documents hooks owns outside the branch json directory.

These raise where the fleet json service answers None/False: a trust registry read as empty revokes every project.
"""

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

# os.replace on Windows raises PermissionError while any reader holds the target open;
# readers hold handles for microseconds, so a short bounded retry converges.
_REPLACE_ATTEMPTS = 40
_REPLACE_BACKOFF_SECONDS = 0.005


def _replace_with_retry(source: str, destination: str) -> None:
    """
    os.replace that tolerates Windows sharing violations, bounded.
    """
    for attempt in range(_REPLACE_ATTEMPTS):
        try:
            os.replace(source, destination)
            return
        except PermissionError:
            if attempt == _REPLACE_ATTEMPTS - 1:
                raise
            time.sleep(_REPLACE_BACKOFF_SECONDS)


def _atomic_write_json(target_path: Path, data: Any) -> None:
    """Write a JSON document so a reader sees the old one or the new one, never a torn one.

    Staged in the target's directory so os.replace stays an atomic same-filesystem rename.
    """
    descriptor, temporary = tempfile.mkstemp(dir=str(target_path.parent), prefix=target_path.stem, suffix=".tmp")
    succeeded = False
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(data, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
        _replace_with_retry(temporary, str(target_path))
        succeeded = True
    finally:
        if not succeeded and Path(temporary).exists():
            os.unlink(temporary)


def read_json_file(path: Path) -> Any:
    """Read and parse a JSON file at an arbitrary path."""
    return json.loads(path.read_text(encoding="utf-8"))


def make_directory(path: Path) -> None:
    """Create *path* and its parents; an existing directory is left as it is."""
    path.mkdir(parents=True, exist_ok=True)


def write_json_file(path: Path, data: Any) -> None:
    """Write data as JSON to an arbitrary path, atomically; raises OSError when it does not land."""
    _atomic_write_json(path, data)
