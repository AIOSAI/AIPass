# =================== AIPass ====================
# Name: config.py
# Description: Trigger package path configuration
# Version: 1.0.0
# Created: 2026-03-09
# Modified: 2026-03-09
# =============================================

"""
Trigger package path configuration.

Provides package-relative paths for trigger data directories.
Works in both pip-installed and development environments.
"""

import json
import sys
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from datetime import datetime, timezone

# Trigger package root: .../aipass/trigger/
TRIGGER_ROOT = Path(__file__).resolve().parents[1]

_CONFIG_LOG = TRIGGER_ROOT / "logs" / "config.log"


def _log_warning(message: str) -> None:
    """Log warning to file (config cannot import prax logger — circular)."""
    try:
        _CONFIG_LOG.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        with open(_CONFIG_LOG, "a", encoding="utf-8") as f:
            f.write(f"{ts} | WARNING | {message}\n")
    except Exception:
        pass  # Meta-logging: cannot log a failure to log


# AIPass package root: .../aipass/
AIPASS_PKG_ROOT = TRIGGER_ROOT.parent


def atomic_write_json(path: Path, data, indent: int = 2, ensure_ascii: bool = True, encoding: str = "utf-8") -> None:
    """Write JSON data to a file atomically using write-to-tmp + os.replace.

    Prevents file corruption from process crashes mid-write by writing to
    a temp file in the same directory first, then atomically renaming.

    Args:
        path: Target file path
        data: JSON-serializable data
        indent: JSON indent level
        ensure_ascii: JSON ensure_ascii flag
        encoding: File encoding
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding=encoding) as f:
            json.dump(data, f, indent=indent, ensure_ascii=ensure_ascii)
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


@contextmanager
def json_file_lock(path: Path):
    """Acquire exclusive lock for a JSON file's read-modify-write cycle.

    Uses a .lock sidecar file with fcntl.flock to prevent concurrent
    processes from corrupting state during read-modify-write. Combine
    with atomic_write_json for both concurrency and crash safety.

    Args:
        path: The JSON file to lock (lock acquired on path.with_suffix('.lock'))
    """
    lock_path = path.with_suffix(".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        # Windows: no fcntl, skip file locking (single-user typical)
        yield
    else:
        import fcntl

        with open(lock_path, "w", encoding="utf-8") as lock_f:
            fcntl.flock(lock_f, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_f, fcntl.LOCK_UN)


def print_introspection():
    """Display module introspection info."""
    try:
        from aipass.cli.apps.modules.display import console
    except ImportError:
        _log_warning("CLI console not available, using rich fallback")
        from rich.console import Console

        console = Console()

    console.print()
    console.print("config Module")
    console.print("Path constants — TRIGGER_ROOT and AIPASS_PKG_ROOT used by all trigger modules")
    console.print()
