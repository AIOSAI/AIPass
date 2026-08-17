# =================== AIPass ====================
# Name: json_handler.py
# Description: JSON Auto-Creating Handler
# Version: 1.2.0
# Created: 2025-11-21
# Modified: 2026-08-16
# =============================================

"""JSON auto-creating handler — read, write, and log structured data."""

import json
import os
import sys
import tempfile
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

# Infrastructure

# Constants — package-relative paths
# Navigate: json_handler.py -> json/ -> handlers/ -> apps/ -> api/
API_ROOT = Path(__file__).resolve().parent.parent.parent.parent
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
        window does not exist. Mirrors the helper @flow, @drone, @devpulse,
        @backup and @prax already carry.
    """
    descriptor, temporary = tempfile.mkstemp(dir=str(target_path.parent), prefix=target_path.stem, suffix=".tmp")
    succeeded = False
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(data, stream, indent=2, ensure_ascii=False)
        os.replace(temporary, str(target_path))
        succeeded = True
    finally:
        if not succeeded and Path(temporary).exists():
            # A failed write must not leave a partial document in the directory
            # this handler itself globs and reads.
            os.unlink(temporary)


def _get_caller_module_name() -> str:
    """
    Auto-detect calling module name from call stack

    Returns:
        Module name (e.g., "imports_standard" from imports_standard.py)
    """
    try:
        stack = inspect.stack()
        # Skip frames: [0]=this function, [1]=log_operation, [2]=actual caller
        if len(stack) > 2:
            caller_frame = stack[2]
            caller_path = Path(caller_frame.filename)
            module_name = caller_path.stem

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
    """Ensure JSON file exists, create from template if missing"""
    API_JSON_DIR.mkdir(parents=True, exist_ok=True)

    json_path = get_json_path(module_name, json_type)

    if json_path.exists():
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            if validate_json_structure(data, json_type):
                return True
            else:
                logger.warning(f"Corrupted JSON structure at {json_path}, regenerating")
        except Exception as e:
            logger.warning(f"Unreadable JSON at {json_path}, regenerating: {e}")

    template = _create_default(json_type, module_name)

    # Atomic like every other write here: this path fires on files a running
    # server is already reading, and it is the REGENERATE path — the one that
    # replaces a live document, so a reader must never catch it half-done.
    _atomic_write_json(json_path, template)
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
