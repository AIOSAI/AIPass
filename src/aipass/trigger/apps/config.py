# =================== AIPass ====================
# Name: config.py
# Description: Trigger package paths, atomic JSON writes, recursion-safe trail logger
# Version: 1.3.0
# Created: 2026-03-09
# Modified: 2026-08-09
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
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from aipass.prax import append_jsonl as _append_jsonl
except Exception:
    _append_jsonl = None

# Trigger package root: .../aipass/trigger/
TRIGGER_ROOT = Path(__file__).resolve().parents[1]

_CONFIG_LOG = TRIGGER_ROOT / "logs" / "config.jsonl"


def append_trail(path: Path, entry: dict) -> bool:
    """Append one JSONL line to a sidecar file, reporting whether it landed.

    The raw counterpart to TrailLogger, for the trails whose readers parse
    named fields and so cannot carry a level/msg shape — medic_suppressed,
    rate_limited, runaway_suppressed. Returns False rather than raising, so a
    caller reports the miss through its own recursion-safe logger instead of
    wrapping every call in an except block that has nothing to call.

    It lives here because config.py is the one trigger module that cannot
    import the prax logger at all (circular dependency), so the guarded import
    and the one unloggable except block exist once, here, rather than repeated
    in every handler that needs a sidecar.

    Args:
        path: Sidecar file to append to — use a `.jsonl` name so the branch log
            watcher, which reads only `*.log`, cannot feed it back.
        entry: JSON-serialisable line to append.

    Returns:
        True if the line was written, False if prax is absent or the write failed
    """
    if _append_jsonl is None:
        return False
    try:
        _append_jsonl(path, entry)
        return True
    except Exception:
        # You cannot log a failure to log. Reported by return value instead —
        # callers surface it (TrailLogger.dropped, escalation.get_stats()).
        return False


class TrailLogger:
    """A logger that writes JSONL to a sidecar file instead of through prax.

    Trigger's log watchers read prax output. Code that runs ON that path —
    the event handlers and the config readers they call — cannot log through
    prax without being detected, fired back as an event, and re-entering
    itself. So it logs here: `.jsonl`, which the watchers skip because they
    only read `*.log`.

    config.py is where this lives because config.py is the one trigger module
    that CANNOT import the prax logger at all (circular dependency), so the
    single except block that has no logger to call — the sidecar's own write
    failure — is already accounted for here rather than repeated in every
    caller. Failed writes are counted on `.dropped`, not discarded silently.

    The method names are the fleet's logger API on purpose: call sites read
    the same as everywhere else in AIPass.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self.dropped = 0

    def _emit(self, level: str, message: str, fields: dict) -> None:
        """Append one line to the sidecar, counting the write if it is lost."""
        entry: dict[str, Any] = {"ts": datetime.now().isoformat(), "level": level, "msg": message}
        entry.update(fields)
        if not append_trail(self.path, entry):
            # Counted rather than vanished — callers surface .dropped
            # (see escalation.get_stats()).
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
    """Build a recursion-safe logger writing to *path*.

    Args:
        path: Sidecar file to append to — use a `.jsonl` name so the branch
            log watcher, which reads only `*.log`, cannot feed it back.

    Returns:
        A logger exposing .info/.warning/.error
    """
    return TrailLogger(path)


logger = TrailLogger(_CONFIG_LOG)


# AIPass package root: .../aipass/
AIPASS_PKG_ROOT = TRIGGER_ROOT.parent

# Runtime state directory — also the directory json_handler's trio machinery owns.
TRIGGER_JSON_DIR = TRIGGER_ROOT / "trigger_json"

# Retired files land here rather than being deleted.
ARCHIVE_DIR_NAME = ".archive"


# Bounded retry for os.replace. Windows raises PermissionError while an AV
# scanner or indexer holds the destination open; POSIX never takes this path.
# Bounded and raising on exhaustion because one stuck replace ate the whole
# Windows CI lane at the 45-minute wall (2026-08-18). Mirrors the canonical
# helper @commons, @api, @flow, @drone and @prax already carry.
_REPLACE_ATTEMPTS = 40
_REPLACE_BACKOFF_SECONDS = 0.005

# Bounded wait for a contended lock. Windows has no blocking flock, so the
# win32 path polls; POSIX blocks in the kernel and never uses these.
_LOCK_ATTEMPTS = 100
_LOCK_BACKOFF_SECONDS = 0.05


def replace_with_retry(source: str, destination: str) -> None:
    """Move a staged file into place, tolerating Windows sharing violations.

    Public, where the fleet's copies are module-private: config.py IS this
    branch's shared helper module, and config_loader imports this by name
    rather than staging its own move.

    Args:
        source: Staged file to move.
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


def read_text_with_retry(path: Path, encoding: str = "utf-8") -> str:
    """Read a document, tolerating Windows sharing violations.

    The mirror of replace_with_retry, and the half that was missing. While one
    writer swaps a document into place, another process opening that same
    document is refused by Windows with PermissionError — the identical
    transient, seen from the reading side. Hardening only the write left every
    reader exposed, and json_handler's readers answered a refused open by
    regenerating the file from a template.

    Args:
        path: Document to read.
        encoding: Text encoding.

    Returns:
        The file's contents.

    Raises:
        PermissionError: Still refused after every attempt.
        OSError: Any non-sharing failure, immediately.
    """
    for attempt in range(_REPLACE_ATTEMPTS):
        try:
            return path.read_text(encoding=encoding)
        except PermissionError:
            if attempt == _REPLACE_ATTEMPTS - 1:
                raise
            time.sleep(_REPLACE_BACKOFF_SECONDS)
    raise AssertionError("unreachable: the loop above either returns or raises")


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
        replace_with_retry(tmp_path, str(path))
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _try_lock_win32(lock_file) -> bool:
    """One non-blocking attempt at the sidecar's byte lock.

    Args:
        lock_file: Open file object for the sidecar.

    Returns:
        True if the lock was taken, False if someone else holds it.
    """
    # typeshed gates msvcrt's members behind sys.platform == "win32", so a
    # checker running on Linux cannot see them. They exist where this runs.
    import msvcrt

    try:
        lock_file.seek(0)
        msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)  # type: ignore[attr-defined]
        return True
    except OSError:
        return False


def _acquire_lock_win32(lock_file) -> None:
    """Poll for the lock — Windows has no blocking flock.

    Locking a byte past EOF is legal on Windows, which is why the sidecar
    needs no contents.

    Args:
        lock_file: Open file object for the sidecar.

    Raises:
        OSError: Still held after _LOCK_ATTEMPTS tries.
    """
    import msvcrt

    for _attempt in range(_LOCK_ATTEMPTS - 1):
        if _try_lock_win32(lock_file):
            return
        time.sleep(_LOCK_BACKOFF_SECONDS)

    # The final attempt is deliberately unguarded: the caller gets the real
    # OSError from the OS rather than a synthesised one, and the one outcome
    # this function must never have is returning without the lock.
    lock_file.seek(0)
    msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)  # type: ignore[attr-defined]


def _acquire_lock(lock_file) -> None:
    """Take an exclusive OS lock on an open .lock sidecar.

    Args:
        lock_file: Open file object for the sidecar.

    Raises:
        OSError: The lock was still held after every attempt.
    """
    if sys.platform == "win32":
        _acquire_lock_win32(lock_file)
    else:
        import fcntl

        fcntl.flock(lock_file, fcntl.LOCK_EX)


def _release_lock(lock_file) -> None:
    """Release the lock taken by _acquire_lock.

    Args:
        lock_file: The same open file object that was locked.
    """
    if sys.platform == "win32":
        import msvcrt

        lock_file.seek(0)
        msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(lock_file, fcntl.LOCK_UN)


@contextmanager
def json_file_lock(path: Path):
    """Acquire exclusive lock for a JSON file's read-modify-write cycle.

    A .lock sidecar is held for the whole cycle, so two processes cannot each
    read a document, change it, and write back a copy missing the other's
    change. Pair with atomic_write_json: atomic stops a TORN file, this stops
    a LOST update, and having only the first is what makes the second look
    handled.

    On win32 this used to `yield` with no lock at all — every caller believed
    it was serialised and none of them were. Windows CI measured the result on
    2026-08-18, the first run that ever completed there: 26 of 100 concurrent
    increments survived. The win32 path now locks a byte of the sidecar through
    msvcrt and RAISES when its bounded wait is exhausted. Running unlocked is
    not one of the outcomes.

    Args:
        path: The JSON file to lock (lock acquired on path.with_suffix('.lock'))

    Raises:
        OSError: The lock could not be acquired within the bounded wait.
    """
    lock_path = path.with_suffix(".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    # "a+" not "w": truncating a sidecar another process holds a byte lock on
    # is a sharing violation on Windows, and the file's contents are irrelevant.
    with open(lock_path, "a+", encoding="utf-8") as lock_f:
        _acquire_lock(lock_f)
        try:
            yield
        finally:
            _release_lock(lock_f)


def atomic_create_json(path: Path, data, indent: int = 2, ensure_ascii: bool = True, encoding: str = "utf-8") -> bool:
    """Create a JSON document ONLY if nothing is there. Never overwrites.

    "Ensure this file exists" and "write this file" are different operations,
    and implementing the first as the second loses data: two callers that both
    find a document missing both stage a template, and the loser's empty
    template lands on top of whatever the winner has written in between.

    Measured on Linux before this existed — 4 threads x 25 appends through
    log_operation, 3 losing runs in 400, one of them the 99-of-100 signature CI
    reported (run 32228159169). The write order proved it: two empty-template
    writes staged first, and one of them completed AFTER a lock holder's first
    real entry. No lock could have stopped it; the template write is outside
    every critical section by construction.

    The staged file is LINKED into place rather than replaced, so the document
    is complete the instant it appears and a second creator is refused instead
    of overwriting.

    Args:
        path: Document to create.
        data: Contents to write if this call wins the create.
        indent: json.dump indent.
        ensure_ascii: json.dump ensure_ascii.
        encoding: Text encoding.

    Returns:
        True if this call created the file, False if it was already there.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding=encoding) as f:
            json.dump(data, f, indent=indent, ensure_ascii=ensure_ascii)
        try:
            os.link(tmp_path, str(path))
            return True
        except FileExistsError:
            return False
        except OSError as exc:
            # No hard links here (some network mounts, FAT). Create-or-fail is
            # not available, so this degrades to the replacing write and the
            # race above is open again on such a filesystem. Said out loud
            # rather than hidden: a silent fallback is how the first version
            # of this looked correct.
            logger.warning(f"atomic_create_json: no link support at {path.parent}, falling back to replace: {exc}")
            replace_with_retry(tmp_path, str(path))
            return True
    except BaseException:
        raise
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


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
        replace_with_retry(str(path), str(target))
        return True
    except OSError as exc:
        logger.warning(f"archive of {path.name} failed: {exc}")
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
            logger.warning(f"migration of {legacy_path.name} skipped, unreadable: {exc}")
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
        logger.warning("CLI console not available, using rich fallback")
        from rich.console import Console

        console = Console()

    console.print()
    console.print("[bold cyan]config Module[/bold cyan]")
    console.print("[dim]Path constants — TRIGGER_ROOT and AIPASS_PKG_ROOT used by all trigger modules[/dim]")
    console.print()
