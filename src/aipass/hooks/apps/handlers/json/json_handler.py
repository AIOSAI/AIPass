# =================== AIPass ====================
# Name: json_handler.py
# Description: JSON auto-creating handler for hooks data files
# Version: 1.2.0
# Created: 2026-07-15
# Modified: 2026-08-18
# =============================================

"""JSON auto-creating handler for hooks data files."""

import json
import os
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any
import inspect

from aipass.prax.apps.modules.logger import system_logger as logger

if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8", errors="replace")

_BRANCH_ROOT = Path(__file__).resolve().parents[3]
_BRANCH_NAME = _BRANCH_ROOT.name
JSON_DIR = _BRANCH_ROOT / f"{_BRANCH_NAME}_json"


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


def _atomic_write_json(target_path: Path, data: Any, ensure_ascii: bool = False) -> None:
    """Write a JSON document so a reader sees the old one or the new one, never a torn one.

    Args:
        target_path: The document to replace.
        data: What to write.
        ensure_ascii: Escape non-ASCII, matching the call site's existing output.

    Raises:
        OSError: The staged file could not be written or moved into place.

    Note:
        write_text opens the target with "w", which truncates it BEFORE the new
        content lands — every concurrent reader in that window gets an empty
        file, and ensure_json_exists answers an unreadable file by writing a
        blank template over it, turning a race into data loss. Measured on this
        unfixed handler: 587 of 1023 concurrent reads unusable (57.4%), three
        runs 56.7-57.5%. The staged file is created in the TARGET's directory so
        os.replace stays a same-filesystem rename, which is atomic on POSIX and
        on Windows. On Windows it can still raise PermissionError while a
        reader holds the target open, so the move goes through
        _replace_with_retry — bounded, then raises (proven by the Windows CI
        hang of 2026-08-18). Mirrors @api v1.3.0, @cli v1.3.0,
        @commons v1.2.0, @daemon v1.4.0, @skills v1.2.0.
    """
    descriptor, temporary = tempfile.mkstemp(dir=str(target_path.parent), prefix=target_path.stem, suffix=".tmp")
    succeeded = False
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(data, stream, indent=2, ensure_ascii=ensure_ascii)
            stream.write("\n")
        _replace_with_retry(temporary, str(target_path))
        succeeded = True
    finally:
        if not succeeded and Path(temporary).exists():
            # A failed write must not leave a partial document beside the real one
            os.unlink(temporary)


def _get_caller_module_name() -> str:
    """Auto-detect calling module name from call stack."""
    stack = inspect.stack()
    if len(stack) > 2:
        caller_frame = stack[2]
        caller_path = Path(caller_frame.filename)
        module_name = caller_path.stem
        if module_name and not module_name.startswith("_"):
            return module_name
    return "unknown"


def _create_default(json_type: str, module_name: str) -> Any:
    """Create default JSON structure from inline code defaults."""
    today = datetime.now().date().isoformat()
    if json_type == "config":
        return {
            "module_name": module_name,
            "version": "1.0.0",
            "config": {"max_log_entries": 100},
            "created": today,
        }
    elif json_type == "data":
        return {
            "module_name": module_name,
            "created": today,
            "last_updated": today,
        }
    elif json_type == "log":
        return []
    raise ValueError(f"Unknown json_type: {json_type}")


def validate_json_structure(data: Any, json_type: str) -> bool:
    """Validate JSON structure matches expected type."""
    if json_type == "config":
        return isinstance(data, dict) and all(k in data for k in ["module_name", "version", "config"])
    elif json_type == "data":
        return isinstance(data, dict) and all(k in data for k in ["created", "last_updated"])
    elif json_type == "log":
        return isinstance(data, list)
    return False


def get_json_path(module_name: str, json_type: str) -> Path:
    """Get path for module JSON file."""
    return JSON_DIR / f"{module_name}_{json_type}.json"


def ensure_json_exists(module_name: str, json_type: str) -> bool:
    """Ensure JSON file exists, create from template if missing."""
    JSON_DIR.mkdir(parents=True, exist_ok=True)
    json_path = get_json_path(module_name, json_type)
    if json_path.exists():
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
            if validate_json_structure(data, json_type):
                return True
        except Exception as exc:
            logger.warning("[HOOKS] json_handler: ensure_json_exists failed for %s_%s: %s", module_name, json_type, exc)
    template = _create_default(json_type, module_name)
    _atomic_write_json(json_path, template)
    return True


def load_json(module_name: str, json_type: str) -> Any | None:
    """Load JSON file, auto-create if missing."""
    if not ensure_json_exists(module_name, json_type):
        return None
    json_path = get_json_path(module_name, json_type)
    return json.loads(json_path.read_text(encoding="utf-8"))


def save_json(module_name: str, json_type: str, data: Any) -> bool:
    """Save JSON file."""
    json_path = get_json_path(module_name, json_type)
    if not validate_json_structure(data, json_type):
        raise ValueError(f"Invalid structure for {json_type} JSON")
    if json_type == "data" and isinstance(data, dict):
        data["last_updated"] = datetime.now().date().isoformat()
    _atomic_write_json(json_path, data)
    return True


def ensure_module_jsons(module_name: str) -> bool:
    """Ensure all 3 JSON files exist for a module."""
    ensure_json_exists(module_name, "config")
    ensure_json_exists(module_name, "data")
    ensure_json_exists(module_name, "log")
    return True


def log_operation(
    operation: str,
    data: dict[str, Any] | None = None,
    module_name: str | None = None,
) -> bool:
    """Add entry to module log with automatic rotation.

    Auto-detects calling module if module_name not provided.
    """
    if module_name is None:
        module_name = _get_caller_module_name()
    ensure_module_jsons(module_name)

    config = load_json(module_name, "config")
    max_entries = 100
    if config and "config" in config:
        max_entries = config["config"].get("max_log_entries", 100)

    log = load_json(module_name, "log")
    if log is None:
        log = []

    entry: dict[str, Any] = {"timestamp": datetime.now().isoformat(), "operation": operation}
    if data:
        entry["data"] = data

    log.append(entry)
    if len(log) > max_entries:
        log = log[-max_entries:]

    return save_json(module_name, "log", log)


def read_json_file(path: Path) -> Any:
    """Read and parse a JSON file at an arbitrary path."""
    return json.loads(path.read_text(encoding="utf-8"))


def write_json_file(path: Path, data: Any) -> None:
    """Write data as JSON to an arbitrary path.

    Note:
        The third write site in this file — the dispatch named two. This one
        writes the TRUST REGISTRY (trust_registry.py:53) and the persistent
        alerts file (alert_dismiss.py:72). A torn registry read is not a lost
        log entry: it is every hook in the project going dark.
    """
    _atomic_write_json(path, data, ensure_ascii=True)
