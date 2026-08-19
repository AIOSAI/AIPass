# =================== AIPass ====================
# Name: json_handler.py
# Description: JSON Auto-Creating Handler
# Version: 1.2.0
# Created: 2026-03-07
# Modified: 2026-08-18
# =============================================

"""
JSON auto-creating handler for The Commons.

Manages per-module JSON files (config, data, log) with template-based
auto-creation, validation, and log rotation. Every write is atomic —
see _atomic_write_json.
"""

import json
import os
import inspect
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional

from aipass.prax.apps.modules.logger import system_logger as logger

# Constants - relative path resolution (pip-safe, no hardcoded absolutes)
_HANDLER_DIR = Path(__file__).resolve().parent  # .../commons/apps/handlers/json/
_APPS_DIR = _HANDLER_DIR.parent.parent  # .../commons/apps/
_COMMONS_ROOT = _APPS_DIR.parent  # .../commons/
BRANCH_JSON_DIR = str(_COMMONS_ROOT / "commons_json")


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


def _atomic_write_json(target_path: Any, data: Any) -> None:
    """
    Write a JSON document so a reader sees either the old one or the new one.

    Args:
        target_path: The document to replace.
        data: What to write.

    Raises:
        OSError: The staged file could not be written or moved into place.

    Note:
        Opening the target with "w" truncates it BEFORE the new bytes land, so
        every concurrent reader in that window gets an empty or partial file —
        and ensure_json_exists answers an unreadable document by writing
        template defaults over it, turning a transient race into permanent
        data loss. Measured on this handler unfixed: 1,038 of 1,297 concurrent
        reads came back unusable (553 empty, 485 partial). os.replace is
        atomic on POSIX and Windows, so the window closes. On Windows it can
        raise PermissionError while a reader holds the target open, so the
        move goes through _replace_with_retry (bounded, then raises — proven
        by the Windows CI hang of 2026-08-18). The staged file lives in the
        TARGET directory — os.replace is only atomic within one filesystem.
        Mirrors the helper @api, @flow, @drone and @prax carry.
    """
    target = Path(target_path)
    descriptor, temporary = tempfile.mkstemp(dir=str(target.parent), prefix=target.stem, suffix=".tmp")
    succeeded = False
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(data, stream, indent=2, ensure_ascii=False)
        _replace_with_retry(temporary, str(target))
        succeeded = True
    finally:
        if not succeeded and os.path.exists(temporary):
            # A failed write must not leave a partial document in the directory
            # this handler itself reads.
            os.unlink(temporary)


def _get_caller_module_name() -> str:
    """
    Auto-detect calling module name from call stack.

    Returns:
        Module name (e.g., "imports_standard" from imports_standard.py)
    """
    stack = inspect.stack()
    if len(stack) > 2:
        caller_frame = stack[2]
        caller_path = caller_frame.filename
        module_name = os.path.splitext(os.path.basename(caller_path))[0]
        if module_name and not module_name.startswith("_"):
            return module_name
    return "unknown"


def _get_default(json_type: str, module_name: str) -> Any:
    """Create default JSON structure for a given type (inline, no file templates)."""
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
    """Validate JSON structure matches expected type."""
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


def get_json_path(module_name: str, json_type: str) -> str:
    """Get path for module JSON file."""
    filename = f"{module_name}_{json_type}.json"
    return os.path.join(BRANCH_JSON_DIR, filename)


def ensure_json_exists(module_name: str, json_type: str) -> bool:
    """Ensure JSON file exists, create from template if missing."""
    os.makedirs(BRANCH_JSON_DIR, exist_ok=True)

    json_path = get_json_path(module_name, json_type)

    if os.path.exists(json_path):
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if validate_json_structure(data, json_type):
                return True
        except (json.JSONDecodeError, OSError):
            logger.warning(f"[json_handler] Corrupt or unreadable JSON file: {json_path}")

    template = _get_default(json_type, module_name)

    # Atomic like every other write here, and the one that matters most: this is
    # the REGENERATE path, replacing a live document a reader may already hold.
    _atomic_write_json(json_path, template)
    return True


def load_json(module_name: str, json_type: str) -> Optional[Any]:
    """Load JSON file, auto-create if missing."""
    if not ensure_json_exists(module_name, json_type):
        return None

    json_path = get_json_path(module_name, json_type)

    with open(json_path, "r", encoding="utf-8") as f:
        return json.load(f)


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
    data: Optional[Dict[str, Any]] = None,
    module_name: Optional[str] = None,
) -> bool:
    """
    Add entry to module log with automatic rotation.

    Auto-detects calling module if module_name not provided.
    Implements config-controlled log limits to prevent unbounded growth.

    Args:
        operation: Operation name to log
        data: Optional data dict
        module_name: Optional module name (auto-detected if not provided)

    Returns:
        True if successful, False otherwise
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

    entry: Dict[str, Any] = {
        "timestamp": datetime.now().isoformat(),
        "operation": operation,
    }

    if data:
        entry["data"] = data

    log.append(entry)

    if len(log) > max_entries:
        log = log[-max_entries:]

    return save_json(module_name, "log", log)


def increment_counter(module_name: str, counter_name: str, amount: int = 1) -> bool:
    """Increment a counter in data JSON."""
    ensure_module_jsons(module_name)

    data = load_json(module_name, "data")
    if data is None:
        return False

    if counter_name not in data:
        data[counter_name] = 0

    data[counter_name] += amount

    return save_json(module_name, "data", data)


def update_data_metrics(module_name: str, **metrics: Any) -> bool:
    """Update data metrics."""
    ensure_module_jsons(module_name)

    data = load_json(module_name, "data")
    if data is None:
        return False

    for key, value in metrics.items():
        data[key] = value

    return save_json(module_name, "data", data)
