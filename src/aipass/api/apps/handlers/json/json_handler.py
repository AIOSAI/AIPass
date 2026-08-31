# =================== AIPass ====================
# Name: json_handler.py
# Description: JSON Auto-Creating Handler
# Version: 1.3.0
# Created: 2025-11-21
# Modified: 2026-08-18
# =============================================

"""JSON auto-creating handler — read, write, and log structured data.

Functions:
    load_json()          - Read a module document, creating it if absent
    save_json()          - Replace a module document atomically
    log_operation()      - Append one entry under the document's lock
    atomic_create_json() - Create a document only if nobody else already has
"""

import json
import os
import sys
import tempfile
import time
import threading
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional
import inspect

if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8", errors="replace")

# Logging
from aipass.prax import logger

from aipass.api.apps.handlers.module_root import module_file

# Infrastructure

# Constants — package-relative paths
# Navigate: json_handler.py -> json/ -> handlers/ -> apps/ -> api/
API_ROOT = module_file(__file__).parent.parent.parent.parent
API_JSON_DIR = API_ROOT / "api_json"

# One lock per document, handed out on demand. Every module in this branch logs
# through this handler, and the host API logs on a thread pool — a single global
# lock would queue unrelated modules behind whichever write is slowest.
_DOCUMENT_LOCKS: Dict[Path, threading.Lock] = {}
_LOCK_REGISTRY_GUARD = threading.Lock()


def _document_lock(json_path: Path) -> threading.Lock:
    """
    The lock that serializes read-modify-write on one document.

    Args:
        json_path: The document being appended to.

    Returns:
        A lock unique to that path, created on first use.

    Note:
        In-process only. Two SEPARATE processes appending to the same document
        can still lose each other's entries — the atomic write below keeps the
        file readable through it, but ordering across processes needs a lock
        file. @trigger carries one: json_file_lock in their apps/config.py,
        fcntl-based with a .lock sidecar and a Windows-safe no-op. Adopting it
        here waits on @devpulse's ruling of 2026-08-16, which queued the
        cross-process axis as a fleet design item rather than 16 branches each
        inventing a lock.
    """
    with _LOCK_REGISTRY_GUARD:
        return _DOCUMENT_LOCKS.setdefault(json_path, threading.Lock())


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


def _atomic_write_json(target_path: Path, data: Any) -> None:
    """
    Write a JSON document so that a reader sees the old one or the new one.

    Args:
        target_path: The document to replace.
        data: What to write.

    Raises:
        OSError: The temp file could not be written or moved into place.

    Note:
        Opening the target with "w" truncates it BEFORE the new content is
        written, so every concurrent reader in that window gets an empty file —
        and this handler answers an unreadable file by regenerating an empty
        template over it, which turns a race into data loss. Measured on the
        unfixed handler: 8,279 of 36,129 concurrent reads came back
        unparseable. os.replace is atomic on POSIX and on Windows, so the
        window does not exist. On Windows it can still raise PermissionError while a
        reader holds the target open, so the move goes through
        _replace_with_retry — bounded, then raises (proven by the Windows CI
        hang of 2026-08-18). Mirrors the helper @flow,
        @drone, @devpulse, @backup and @prax already carry.
    """
    descriptor, temporary = tempfile.mkstemp(dir=str(target_path.parent), prefix=target_path.stem, suffix=".tmp")
    succeeded = False
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(data, stream, indent=2, ensure_ascii=False)
        _replace_with_retry(temporary, str(target_path))
        succeeded = True
    finally:
        if not succeeded and Path(temporary).exists():
            # A failed write must not leave a partial document in the directory
            # this handler itself globs and reads.
            os.unlink(temporary)


def atomic_create_json(target_path: Path, data: Any) -> bool:
    """
    Create a JSON document only if nobody else already has. Never overwrite.

    Args:
        target_path: The document to bring into existence.
        data: What to write if this caller is the one that creates it.

    Returns:
        True when this call created the document, False when someone else did
        and this caller wrote nothing. LOSING IS NOT AN ERROR — the loser got
        what it asked for (the document exists), so it neither raises nor
        overwrites.

    Raises:
        OSError: The temp file could not be written, or the move failed for a
            reason other than the target already existing.

    Note:
        THE THIRD WAY A DOCUMENT IS LOST, found on @trigger's tree 2026-08-19
        and reported here: "create if missing" implemented as a replacing write
        is a check-then-act. Two callers both find the document absent, both
        stage an empty template, and the slower one's template lands on top of
        whatever was written in between — no corruption, no refused read, no
        unusual timing. Their Linux CI lost 1 of 100 concurrent appends to it.

        os.link is the whole mechanism, for two reasons rather than one. It
        FAILS if the target exists, which makes create-or-fail atomic in the
        filesystem rather than in a check one line earlier — and a linked file
        is complete the instant the name appears, so there is no empty window
        for a reader to catch, which matters here because this handler answers
        an unreadable document by regenerating a template over it.

        It needs no lock, which is why it is worth taking now: this branch's
        _document_lock is a threading.Lock and every `drone @api` run is its
        own process, so the create race is open across processes today. Being
        lockless, it also does not pre-empt whatever the fleet standardises for
        the cross-process axis (@devpulse's ruling, still open).
    """
    target_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=str(target_path.parent), prefix=target_path.stem, suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(data, stream, indent=2, ensure_ascii=False)

        try:
            os.link(temporary, str(target_path))
            return True
        except FileExistsError:
            # Someone else created it first. They win, and this caller writes
            # NOTHING — which is the entire point of the exercise. DEBUG, not
            # warning: losing is the normal, correct outcome of a race two
            # healthy processes are allowed to enter. Logged at all because
            # "who created this document" is otherwise unanswerable after the
            # fact, and this is the only place that knows.
            logger.debug("[json_handler] %s was created by another process first — writing nothing", target_path)
            return False
        except (OSError, AttributeError, NotImplementedError) as e:
            # No hard links here (some network and container filesystems, and
            # Windows outside NTFS). Degrade to the replacing write so the
            # handler still works, and SAY SO — a guarantee that quietly got
            # weaker is the one somebody keeps relying on.
            logger.warning(
                "[json_handler] %s cannot hard-link (%s) — falling back to a replacing create, "
                "which can overwrite a document another process created first",
                target_path.parent,
                e,
            )
            _replace_with_retry(temporary, str(target_path))
            return True
    finally:
        # The link leaves a SECOND name for the same bytes; the fallback moved
        # the file and this is a no-op. Either way nothing is left in a
        # directory the handler itself globs.
        try:
            os.unlink(temporary)
        except OSError as e:
            # Nothing to abort — the document itself is already correct. But a
            # stranded .tmp sits in a directory this handler globs, so it gets
            # named rather than swallowed.
            logger.debug("[json_handler] could not remove the staging file %s: %s", temporary, e)


def _get_caller_module_name() -> str:
    """
    Auto-detect calling module name from call stack

    Returns:
        Module name (e.g., "imports_standard" from imports_standard.py)

    Note:
        ONE frame is fetched, not the whole stack. inspect.stack() builds a
        FrameInfo for every frame below this one — resolving each filename and
        reading source lines through linecache — so its cost grows with how
        deep the caller is. Measured 2026-08-18: 0.21ms two frames down, 1.77ms
        at fifty, which is ordinary depth inside a FastAPI request, and the
        host lane makes 37 auto-detecting calls. sys._getframe(2) is the same
        answer for 0.006ms because it never touches the frames it is not asked
        about (DPLAN-0305 Audit 2).

        _getframe is a CPython implementation detail, so its absence falls back
        to the old walk rather than to "unknown" — a different interpreter
        should be slower here, never wrong.
    """
    try:
        # Skip frames: [0]=this function, [1]=log_operation, [2]=actual caller
        getframe = getattr(sys, "_getframe", None)
        if getframe is not None:
            module_name = Path(getframe(2).f_code.co_filename).stem
        else:
            stack = inspect.stack()
            if len(stack) <= 2:
                return "unknown"
            module_name = Path(stack[2].filename).stem

        # Validate module name
        if module_name and not module_name.startswith("_"):
            return module_name

        # Fallback
        return "unknown"
    except Exception as e:
        logger.warning(f"Failed to detect module name: {e}")
        return "unknown"


def _create_default(json_type: str, module_name: str) -> Any:
    """Create default JSON structure for a given type."""
    today = datetime.now().date().isoformat()

    if json_type == "config":
        return {
            "module_name": module_name,
            "version": "1.0.0",
            "timestamp": today,
            "config": {
                "auto_save": True,
                "enabled": True,
            },
        }

    if json_type == "data":
        return {
            "module_name": module_name,
            "created": today,
            "last_updated": today,
            "operations_total": 0,
            "operations_successful": 0,
            "operations_failed": 0,
        }

    if json_type == "log":
        return []

    raise ValueError(f"Unknown json_type: {json_type}")


def validate_json_structure(data: Any, json_type: str) -> bool:
    """Validate JSON structure matches expected type"""
    if json_type == "config":
        if not isinstance(data, dict):
            return False
        required = ["module_name", "version", "config"]
        return all(key in data for key in required)

    elif json_type == "data":
        if not isinstance(data, dict):
            return False
        required = ["created", "last_updated"]
        return all(key in data for key in required)

    elif json_type == "log":
        return isinstance(data, list)

    return False


def get_json_path(module_name: str, json_type: str) -> Path:
    """Get path for module JSON file"""
    filename = f"{module_name}_{json_type}.json"
    return API_JSON_DIR / filename


def ensure_json_exists(module_name: str, json_type: str) -> bool:
    """
    Ensure JSON file exists, create from template if missing.

    Args:
        module_name: Which module's document.
        json_type: config, data or log.

    Returns:
        True — the document exists when this returns, whoever made it.

    Note:
        TWO DIFFERENT WRITES LIVE HERE and conflating them is the defect. A
        document that is ABSENT is created with atomic_create_json, which
        cannot overwrite: a second process arriving at the same moment writes
        nothing rather than burying an entry the winner already appended. A
        document that is PRESENT and unusable is regenerated, which genuinely
        must replace what is there.

        The branch follows what the FIRST read observed, deliberately. Deciding
        create-vs-regenerate with a second exists() check is the same
        check-then-act one line lower — the racing writer creates the file
        inside that window, this call takes the overwrite path, and the entry
        dies exactly as before. @trigger's own first cure had that shape and
        their red-first pin caught it; this one follows the observation.
    """
    API_JSON_DIR.mkdir(parents=True, exist_ok=True)

    json_path = get_json_path(module_name, json_type)
    observed_present = json_path.exists()

    if observed_present:
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            if validate_json_structure(data, json_type):
                return True
            else:
                logger.warning(f"Corrupted JSON structure at {json_path}, regenerating")
        except Exception as e:
            logger.warning(f"Unreadable JSON at {json_path}, regenerating: {e}")

        # REGENERATE. Atomic like every other write here: this fires on files a
        # running server is already reading, so a reader must never catch it
        # half-done. Still an unlocked overwrite of a live document — narrower
        # than it was (it can no longer fire on a merely-absent file) but the
        # cross-process axis still owns the rest of it.
        _atomic_write_json(json_path, _create_default(json_type, module_name))
        return True

    # CREATE. Observed absent, so this is create-or-fail: losing means somebody
    # else made it, which is the outcome this function exists to reach.
    atomic_create_json(json_path, _create_default(json_type, module_name))
    return True


def load_json(module_name: str, json_type: str) -> Optional[Any]:
    """Load JSON file, auto-create if missing"""
    if not ensure_json_exists(module_name, json_type):
        return None

    json_path = get_json_path(module_name, json_type)

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load JSON from {json_path}: {e}")
        return None


def save_json(module_name: str, json_type: str, data: Any) -> bool:
    """Save JSON file"""
    json_path = get_json_path(module_name, json_type)

    if not validate_json_structure(data, json_type):
        return False

    if json_type == "data" and isinstance(data, dict):
        data["last_updated"] = datetime.now().date().isoformat()

    try:
        _atomic_write_json(json_path, data)
        return True
    except Exception as e:
        logger.error(f"Failed to save JSON to {json_path}: {e}")
        return False


def ensure_module_jsons(module_name: str) -> bool:
    """Ensure all 3 JSON files exist for a module"""
    ensure_json_exists(module_name, "config")
    ensure_json_exists(module_name, "data")
    ensure_json_exists(module_name, "log")
    return True


def log_operation(operation: str, data: Dict[str, Any] | None = None, module_name: str | None = None) -> bool:
    """
    Add entry to module log with automatic rotation

    Auto-detects calling module if module_name not provided.
    Implements config-controlled log limits to prevent unbounded growth.
    When max_log_entries is reached, removes oldest entries (FIFO).

    Args:
        operation: Operation name to log
        data: Optional data dict
        module_name: Optional module name (auto-detected if not provided)

    Returns:
        True if successful, False otherwise

    Note:
        Read-modify-write: the whole log is read, one entry appended, the whole
        log written back. Two callers doing that at once each write a version
        missing the other's entry, so the append is held under this document's
        lock. Measured below the rotation cap on the unlocked handler: 4 threads
        asking for 80 entries left 4 on disk.
    """
    # Auto-detect module name if not provided
    if module_name is None:
        module_name = _get_caller_module_name()

    with _document_lock(get_json_path(module_name, "log")):
        ensure_module_jsons(module_name)

        # Load config to get max_log_entries
        config = load_json(module_name, "config")
        max_entries = 100  # Default
        if config and "config" in config:
            max_entries = config["config"].get("max_log_entries", 100)

        # Load existing log
        log = load_json(module_name, "log")
        if log is None:
            log = []

        # Create new entry
        entry = {"timestamp": datetime.now().isoformat(), "operation": operation}

        if data:
            entry["data"] = data  # type: ignore[assignment]

        # Add new entry
        log.append(entry)

        # Rotate if exceeds max (keep most recent entries)
        if len(log) > max_entries:
            log = log[-max_entries:]

        return save_json(module_name, "log", log)


if __name__ == "__main__":
    from rich.console import Console
    from rich.panel import Panel

    console = Console()

    console.print()
    console.print(Panel.fit("[bold cyan]JSON HANDLER - Working Implementation[/bold cyan]", border_style="bright_blue"))
    console.print()
    console.print("[yellow]TESTING:[/yellow] Creating API JSONs...")

    # Test auto-creation
    log_operation("test_operation", {"test": "data"}, "api")

    console.print()
    console.print(f"[green]Check {API_JSON_DIR}/ for created files:[/green]")
    console.print("  [dim]•[/dim] api_config.json")
    console.print("  [dim]•[/dim] api_data.json")
    console.print("  [dim]•[/dim] api_log.json")
    console.print()
