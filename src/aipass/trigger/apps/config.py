# =================== AIPass ====================
# Name: config.py
# Description: Trigger package paths, cwd-free module resolve, atomic JSON writes, recursion-safe trail logger
# Version: 1.8.0
# Created: 2026-03-09
# Modified: 2026-10-17
# =============================================

"""
Trigger package path configuration.
"""

import json
import sys
import os
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

try:
    from aipass.prax import append_jsonl as _append_jsonl
except Exception:
    _append_jsonl = None

# Recorded, not logged: module_file runs before any logger exists, once per module import.
UNRESOLVED: list[str] = []


def module_file(file: str) -> Path:
    """A module's own path, absolute, resolved when the filesystem allows."""
    # On Windows Path.resolve() always calls os.getcwd(), so a deleted cwd kills the import;
    # the fallback is sound because __file__ is absolute (3.9+), just not symlink-resolved.
    path = Path(file)
    try:
        return path.resolve()
    except OSError as exc:
        UNRESOLVED.append(f"{path}: {type(exc).__name__}: {exc}")
        return path


# module_file, not resolve(): this line runs at IMPORT.
TRIGGER_ROOT = module_file(__file__).parents[1]

_CONFIG_LOG = TRIGGER_ROOT / "logs" / "config.jsonl"


def append_trail(path: Path, entry: dict) -> bool:
    """Append one JSONL line to a sidecar file, reporting whether it landed."""
    # Never raises. Use a `.jsonl` path: the log watcher reads only `*.log` and would feed it back.
    if _append_jsonl is None:
        return False
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

# json_handler regenerates any `<module>_<config|data|log>.json` here whose shape mismatches.
TRIGGER_JSON_DIR = TRIGGER_ROOT / "trigger_json"

ARCHIVE_DIR_NAME = ".archive"


# Windows raises PermissionError while an AV scanner holds the file; bounded so it raises, not hangs.
_REPLACE_ATTEMPTS = 40
_REPLACE_BACKOFF_SECONDS = 0.005

# win32 only: no blocking flock there, so it polls.
_LOCK_ATTEMPTS = 100
_LOCK_BACKOFF_SECONDS = 0.05


def replace_with_retry(
    source: str,
    destination: str,
    replace_fn: Optional[Callable[[str, str], None]] = None,
    sleep_fn: Optional[Callable[[float], None]] = None,
) -> None:
    """Move a staged file into place, tolerating Windows sharing violations."""
    # replace_fn and sleep_fn are test seams; None is os.replace and time.sleep.
    replace = replace_fn or os.replace
    sleep = sleep_fn or time.sleep
    for attempt in range(_REPLACE_ATTEMPTS):
        try:
            replace(source, destination)
            return
        except PermissionError:
            if attempt == _REPLACE_ATTEMPTS - 1:
                raise
            sleep(_REPLACE_BACKOFF_SECONDS)


def read_text_with_retry(
    path: Path,
    encoding: str = "utf-8",
    read_fn: Optional[Callable[..., str]] = None,
    sleep_fn: Optional[Callable[[float], None]] = None,
) -> str:
    """Read a document, tolerating Windows sharing violations."""
    # Windows refuses a read mid-replace, and json_handler answers a refused open by regenerating.
    sleep = sleep_fn or time.sleep
    for attempt in range(_REPLACE_ATTEMPTS):
        try:
            if read_fn is None:
                return path.read_text(encoding=encoding)
            return read_fn(path, encoding=encoding)
        except PermissionError:
            if attempt == _REPLACE_ATTEMPTS - 1:
                raise
            sleep(_REPLACE_BACKOFF_SECONDS)
    raise AssertionError("unreachable: the loop above either returns or raises")


def atomic_write_json(path: Path, data, indent: int = 2, ensure_ascii: bool = True, encoding: str = "utf-8") -> None:
    """Write JSON data to a file atomically using write-to-tmp + os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding=encoding) as f:
            json.dump(data, f, indent=indent, ensure_ascii=ensure_ascii)
        replace_with_retry(tmp_path, str(path))
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# Bound once at import, before any test pretends another platform; a missing one raises at use.
try:
    import fcntl
except ImportError:
    fcntl = None  # type: ignore[assignment]

try:
    import msvcrt
except ImportError:
    msvcrt = None  # type: ignore[assignment]


def _lock_primitive(module: Any, name: str) -> Any:
    """The module-level lock primitive, or an ImportError naming the host."""
    if module is None:
        raise ImportError(f"{name} is unavailable on this host ({sys.platform}); json_file_lock cannot lock")
    return module


def _try_lock_win32(lock_file, msvcrt_module: Any = None) -> bool:
    """One non-blocking attempt at the sidecar's byte lock."""
    if msvcrt_module is None:
        msvcrt_module = _lock_primitive(msvcrt, "msvcrt")

    try:
        lock_file.seek(0)
        msvcrt_module.locking(lock_file.fileno(), msvcrt_module.LK_NBLCK, 1)
        return True
    except OSError:
        return False


def _acquire_lock_win32(
    lock_file, msvcrt_module: Any = None, sleep_fn: Optional[Callable[[float], None]] = None
) -> None:
    """Poll for the lock — Windows has no blocking flock."""
    # Locking a byte past EOF is legal on Windows, so the sidecar needs no contents.
    if msvcrt_module is None:
        msvcrt_module = _lock_primitive(msvcrt, "msvcrt")
    sleep = sleep_fn or time.sleep

    for _attempt in range(_LOCK_ATTEMPTS - 1):
        if _try_lock_win32(lock_file, msvcrt_module):
            return
        sleep(_LOCK_BACKOFF_SECONDS)

    # Unguarded on purpose: the caller gets the real OSError; never return without the lock.
    lock_file.seek(0)
    msvcrt_module.locking(lock_file.fileno(), msvcrt_module.LK_NBLCK, 1)


def _acquire_lock(
    lock_file,
    platform: Optional[str] = None,
    msvcrt_module: Any = None,
    sleep_fn: Optional[Callable[[float], None]] = None,
) -> None:
    """Take an exclusive OS lock on an open .lock sidecar."""
    if platform == "win32" or (platform is None and sys.platform == "win32"):
        _acquire_lock_win32(lock_file, msvcrt_module, sleep_fn)
    else:
        posix_lock = _lock_primitive(fcntl, "fcntl")
        posix_lock.flock(lock_file, posix_lock.LOCK_EX)


def _release_lock(lock_file, platform: Optional[str] = None, msvcrt_module: Any = None) -> None:
    """Release the lock taken by _acquire_lock."""
    if platform == "win32" or (platform is None and sys.platform == "win32"):
        if msvcrt_module is None:
            msvcrt_module = _lock_primitive(msvcrt, "msvcrt")

        lock_file.seek(0)
        msvcrt_module.locking(lock_file.fileno(), msvcrt_module.LK_UNLCK, 1)
    else:
        posix_lock = _lock_primitive(fcntl, "fcntl")
        posix_lock.flock(lock_file, posix_lock.LOCK_UN)


@contextmanager
def json_file_lock(
    path: Path,
    platform: Optional[str] = None,
    msvcrt_module: Any = None,
    sleep_fn: Optional[Callable[[float], None]] = None,
):
    """Acquire exclusive lock for a JSON file's read-modify-write cycle."""
    # Pair with atomic_write_json: atomic stops a torn file, this stops a lost update.
    # win32 raises OSError when its bounded wait runs out; it never yields unlocked.
    lock_path = path.with_suffix(".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    # "a+" not "w": truncating a byte-locked sidecar is a sharing violation on Windows.
    with open(lock_path, "a+", encoding="utf-8") as lock_f:
        _acquire_lock(lock_f, platform, msvcrt_module, sleep_fn)
        try:
            yield
        finally:
            _release_lock(lock_f, platform, msvcrt_module)


def _archive_legacy_file(path: Path) -> bool:
    """Move a retired state file into a sibling .archive/ directory."""
    archive_dir = path.parent / ARCHIVE_DIR_NAME
    archive_dir.mkdir(parents=True, exist_ok=True)
    target = archive_dir / path.name
    try:
        if target.exists():
            stamp = int(path.stat().st_mtime)
            target = archive_dir / f"{path.stem}.{stamp}{path.suffix}"
        replace_with_retry(str(path), str(target))
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
