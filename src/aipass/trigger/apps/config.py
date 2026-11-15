# =================== AIPass ====================
# Name: config.py
# Description: Trigger package paths, atomic JSON writes, recursion-safe trail logger
# Version: 1.8.0
# Created: 2026-03-09
# Modified: 2026-11-15
# =============================================

"""
Trigger package path configuration.
"""

import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from aipass.prax import append_jsonl as _append_jsonl

TRIGGER_ROOT = Path(__file__).resolve().parents[1]

_CONFIG_LOG = TRIGGER_ROOT / "logs" / "config.jsonl"


def append_trail(path: Path, entry: dict) -> bool:
    """Append one JSONL line to a sidecar file, reporting whether it landed."""
    # Never raises. Use a `.jsonl` path: the log watcher reads only `*.log` and would feed it back.
    try:
        _append_jsonl(path, entry)
        return True
    except Exception:
        # A failure to log cannot be logged; callers surface the return value.
        return False


class TrailLogger:
    """A logger that writes JSONL to a sidecar file instead of through prax."""

    # Code on the watched event path would re-enter itself through prax; watchers skip `.jsonl`.

    def __init__(self, path: Path) -> None:
        self.path = path
        self.dropped = 0

    def _emit(self, level: str, message: str, fields: dict) -> None:
        """Append one line to the sidecar, counting the write if it is lost."""
        entry: dict[str, Any] = {"ts": datetime.now().isoformat(), "level": level, "msg": message}
        entry.update(fields)
        if not append_trail(self.path, entry):
            self.dropped += 1

    def info(self, message: str, **fields: Any) -> None:
        """Record an INFO line on the trail."""
        self._emit("INFO", message, fields)

    def warning(self, message: str, **fields: Any) -> None:
        """Record a WARNING line on the trail."""
        self._emit("WARNING", message, fields)

    def error(self, message: str, **fields: Any) -> None:
        """Record an ERROR line on the trail."""
        self._emit("ERROR", message, fields)


def trail_logger(path: Path) -> TrailLogger:
    """Build a recursion-safe logger writing to *path*."""
    return TrailLogger(path)


logger = TrailLogger(_CONFIG_LOG)


AIPASS_PKG_ROOT = TRIGGER_ROOT.parent

# json_handler creates any absent `<module>_<config|data|log>.json` here; a misshaped one raises, never overwritten.
TRIGGER_JSON_DIR = TRIGGER_ROOT / "trigger_json"

ARCHIVE_DIR_NAME = ".archive"


def atomic_write_json(path: Path, data, indent: int = 2, ensure_ascii: bool = True, encoding: str = "utf-8") -> None:
    """Write JSON data to a file atomically using write-to-tmp + os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding=encoding) as f:
            json.dump(data, f, indent=indent, ensure_ascii=ensure_ascii)
        os.replace(tmp_path, str(path))
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


@contextmanager
def json_file_lock(path: Path):
    """Acquire exclusive lock for a JSON file's read-modify-write cycle."""
    # Pair with atomic_write_json: atomic stops a torn file, this stops a lost update.
    lock_path = path.with_suffix(".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a+", encoding="utf-8") as lock_f:
        fcntl.flock(lock_f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_f, fcntl.LOCK_UN)


def _archive_legacy_file(path: Path) -> bool:
    """Move a retired state file into a sibling .archive/ directory."""
    archive_dir = path.parent / ARCHIVE_DIR_NAME
    archive_dir.mkdir(parents=True, exist_ok=True)
    target = archive_dir / path.name
    try:
        if target.exists():
            stamp = int(path.stat().st_mtime)
            target = archive_dir / f"{path.stem}.{stamp}{path.suffix}"
        os.replace(str(path), str(target))
        return True
    except OSError as exc:
        logger.warning(f"archive of {path.name} failed: {exc}")
        return False


def migrate_json_file(legacy_path: Path, new_path: Path) -> bool | None:
    """Move live JSON state from a legacy path to its new home, losslessly."""
    # New present is a no-op: the legacy name is json_handler's again. None means unreadable, left in place.
    # Locks the LEGACY path: callers already hold the new file's lock, and a second flock would deadlock.
    if new_path.exists() or not legacy_path.exists():
        return False
    with json_file_lock(legacy_path):
        if new_path.exists() or not legacy_path.exists():  # another process won the race
            return False
        try:
            data = json.loads(legacy_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, ValueError) as exc:
            logger.warning(f"migration of {legacy_path.name} skipped, unreadable: {exc}")
            return None
        atomic_write_json(new_path, data)
        return _archive_legacy_file(legacy_path)


def read_text_file(path: Path, encoding: str = "utf-8") -> str:
    """Read a text file safely with encoding specification."""
    with open(path, "r", encoding=encoding) as f:
        return f.read()


def write_text_file(path: Path, content: str, encoding: str = "utf-8") -> None:
    """Write text content to a file, creating parent directories as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding=encoding) as f:
        f.write(content)


def print_introspection():
    """Display module introspection info."""
    try:
        from aipass.cli.apps.modules.display import console
    # OSError too: an uncured peer's import guard raises FileNotFoundError.
    except (ImportError, OSError):
        logger.warning("CLI console not available, using rich fallback")
        from rich.console import Console

        console = Console()

    console.print()
    console.print("[bold cyan]config Module[/bold cyan]")
    console.print("[dim]Path constants — TRIGGER_ROOT and AIPASS_PKG_ROOT used by all trigger modules[/dim]")
    console.print()
