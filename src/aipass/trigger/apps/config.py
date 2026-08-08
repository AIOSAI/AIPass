# =================== AIPass ====================
# Name: config.py
# Description: Trigger package path configuration
# Version: 1.1.0
# Created: 2026-03-09
# Modified: 2026-08-07
# =============================================

"""
Trigger package path configuration.

Provides package-relative paths for trigger data directories.
Works in both pip-installed and development environments.

Also provides migrate_json_file() — the lossless move used to get
hand-written live state OFF the trio-owned filename pattern in
trigger_json/. json_handler owns every `<module>_<config|data|log>.json`
in that directory: it validates such a file against a template and
REGENERATES it when the shape does not match. Live state parked on one of
those names is one caller-name resolution away from being overwritten with
a blank template.
"""

import json
import sys
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path

try:
    from aipass.prax import append_jsonl as _append_jsonl
except Exception:
    _append_jsonl = None

# Trigger package root: .../aipass/trigger/
TRIGGER_ROOT = Path(__file__).resolve().parents[1]

_CONFIG_LOG = TRIGGER_ROOT / "logs" / "config.jsonl"


def _log_warning(message: str) -> None:
    """Log warning to file (recursion-safe prax path)."""
    if _append_jsonl is None:
        return
    try:
        _append_jsonl(_CONFIG_LOG, {"level": "WARNING", "msg": message})
    except Exception:
        pass


# AIPass package root: .../aipass/
AIPASS_PKG_ROOT = TRIGGER_ROOT.parent

# Runtime state directory — also the directory json_handler's trio machinery owns.
TRIGGER_JSON_DIR = TRIGGER_ROOT / "trigger_json"

# Retired files land here rather than being deleted.
ARCHIVE_DIR_NAME = ".archive"


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


def _archive_legacy_file(path: Path) -> bool:
    """Move a retired state file into a sibling .archive/ directory.

    Never deletes. A name collision keeps both copies by suffixing the
    archived file with the source mtime.

    Args:
        path: The file to retire (must exist)

    Returns:
        True if the file was moved
    """
    archive_dir = path.parent / ARCHIVE_DIR_NAME
    archive_dir.mkdir(parents=True, exist_ok=True)
    target = archive_dir / path.name
    try:
        if target.exists():
            stamp = int(path.stat().st_mtime)
            target = archive_dir / f"{path.stem}.{stamp}{path.suffix}"
        os.replace(path, target)
        return True
    except OSError as exc:
        _log_warning(f"archive of {path.name} failed: {exc}")
        return False


def migrate_json_file(legacy_path: Path, new_path: Path) -> bool:
    """Move live JSON state from a legacy path to its new home, losslessly.

    Idempotent and safe to call on every read — it stats the legacy path and
    returns immediately when there is nothing to move. Behaviour:

    - new present               -> no-op, whatever the legacy name holds. The
                                   move already happened, so that name belongs
                                   to json_handler's trio machinery again — a
                                   blank template it regenerates there is its
                                   file, not stale state of ours. Archiving it
                                   on every read would fight the trio owner
                                   forever and grow .archive/ without bound.
    - new absent, legacy present-> copy contents to new, archive legacy
    - legacy missing            -> no-op
    - legacy unreadable         -> left in place untouched, warning logged.
                                   Fail honest: a human decides, not a guess.

    The lock is taken on the LEGACY path, not the new one: the legacy file is
    the resource being claimed, and callers already hold the new file's lock
    around their own read-modify-write cycles — flock on a second descriptor
    for the same file would deadlock the process against itself.

    Args:
        legacy_path: Old file location
        new_path: New file location

    Returns:
        True if the legacy file was migrated or archived on this call
    """
    if new_path.exists() or not legacy_path.exists():
        return False
    with json_file_lock(legacy_path):
        if new_path.exists() or not legacy_path.exists():  # another process won the race
            return False
        try:
            data = json.loads(legacy_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, ValueError) as exc:
            _log_warning(f"migration of {legacy_path.name} skipped, unreadable: {exc}")
            return False
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
    except ImportError:
        _log_warning("CLI console not available, using rich fallback")
        from rich.console import Console

        console = Console()

    console.print()
    console.print("[bold cyan]config Module[/bold cyan]")
    console.print("[dim]Path constants — TRIGGER_ROOT and AIPASS_PKG_ROOT used by all trigger modules[/dim]")
    console.print()
