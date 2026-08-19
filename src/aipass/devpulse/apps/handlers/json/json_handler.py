# =================== AIPass ====================
# Name: json_handler.py
# Description: JSON auto-creating handler for devpulse data files
# Version: 1.1.0
# Created: 2026-05-15
# Modified: 2026-08-18
# =============================================

"""JSON auto-creating handler for devpulse data files.

Provides log_operation() for structured operation logging and
ensure_json_file() for auto-creating branch-scoped JSON files.
"""

from __future__ import annotations

import inspect
import json
import os
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from aipass.prax import logger

_BRANCH_ROOT: Path = Path(__file__).resolve().parents[3]
_BRANCH_NAME: str = _BRANCH_ROOT.name
JSON_DIR: Path = _BRANCH_ROOT / f"{_BRANCH_NAME}_json"

_JSON_TYPES: tuple[str, ...] = ("config", "data", "log")


def _today() -> str:
    """Return today's date as ISO string."""
    return datetime.now().date().isoformat()


def _get_caller_module_name() -> str:
    stack = inspect.stack()
    if len(stack) > 2:
        caller_path = Path(stack[2].filename)
        module_name = caller_path.stem
        if module_name and not module_name.startswith("_"):
            return module_name
    return "unknown"


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


def _atomic_write_json(path: Path, data: Any) -> None:
    """Stage, then swap — a reader sees the whole old file or the whole new one.

    The rename goes through _replace_with_retry: on Windows a reader holding
    the target open turns the move into a PermissionError, and one stuck move
    starved a whole CI run (2026-08-18). Bounded, then it raises honestly.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp", prefix=".json_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
        _replace_with_retry(tmp_path, str(path))
    except BaseException as exc:
        logger.warning("_atomic_write_json: failed for %s: %s", path, exc)
        try:
            os.unlink(tmp_path)
        except OSError as cleanup_exc:
            logger.warning("_atomic_write_json: cleanup failed for %s: %s", tmp_path, cleanup_exc)
        raise


def _default_config(module_name: str) -> dict[str, Any]:
    today = _today()
    return {
        "module_name": module_name,
        "version": "1.0.0",
        "config": {"max_log_entries": 100},
        "created": today,
        "last_updated": today,
    }


def _default_data(module_name: str) -> dict[str, Any]:  # noqa: ARG001
    today = _today()
    return {"created": today, "last_updated": today}


def _default_log(module_name: str) -> list[Any]:  # noqa: ARG001
    return []


_DEFAULTS: dict[str, Any] = {
    "config": _default_config,
    "data": _default_data,
    "log": _default_log,
}


def validate_json_structure(data: Any, json_type: str) -> bool:
    """Check that data matches expected shape for json_type."""
    if json_type == "config":
        if not isinstance(data, dict):
            return False
        return all(key in data for key in ("module_name", "version", "config"))
    if json_type == "data":
        if not isinstance(data, dict):
            return False
        return all(key in data for key in ("created", "last_updated"))
    if json_type == "log":
        return isinstance(data, list)
    return False


def get_json_path(module_name: str, json_type: str) -> Path:
    """Return filesystem path for a module's JSON file."""
    return JSON_DIR / f"{module_name}_{json_type}.json"


def ensure_json_exists(module_name: str, json_type: str) -> bool:
    """Ensure a single JSON file exists, creating with defaults if missing."""
    JSON_DIR.mkdir(parents=True, exist_ok=True)
    json_path = get_json_path(module_name, json_type)
    if json_path.exists():
        try:
            if json_path.stat().st_size == 0:
                logger.warning("ensure_json_exists: empty file at %s, regenerating", json_path)
            else:
                with open(json_path, encoding="utf-8") as fh:
                    data = json.load(fh)
                if validate_json_structure(data, json_type):
                    return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("ensure_json_exists: failed to read %s, regenerating: %s", json_path, exc)
    factory = _DEFAULTS.get(json_type)
    if factory is None:
        raise ValueError(f"Unknown json_type: {json_type!r}")
    default = factory(module_name)
    _atomic_write_json(json_path, default)
    return True


def ensure_module_jsons(module_name: str) -> bool:
    """Ensure all three JSON files (config, data, log) exist for a module."""
    for json_type in _JSON_TYPES:
        ensure_json_exists(module_name, json_type)
    return True


def load_json(module_name: str, json_type: str) -> Any | None:
    """Load a module's JSON file, auto-creating if missing."""
    if not ensure_json_exists(module_name, json_type):
        return None
    json_path = get_json_path(module_name, json_type)
    try:
        if json_path.stat().st_size == 0:
            factory = _DEFAULTS.get(json_type)
            return factory(module_name) if factory else None
        with open(json_path, encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("load_json: failed to read %s: %s", json_path, exc)
        factory = _DEFAULTS.get(json_type)
        return factory(module_name) if factory else None


def save_json(module_name: str, json_type: str, data: Any) -> bool:
    """Write data to a module's JSON file after validation."""
    if not validate_json_structure(data, json_type):
        raise ValueError(f"Invalid structure for {json_type} JSON")
    if json_type == "data" and isinstance(data, dict):
        data["last_updated"] = _today()
    json_path = get_json_path(module_name, json_type)
    _atomic_write_json(json_path, data)
    return True


def log_operation(
    operation: str,
    data: dict[str, Any] | None = None,
    module_name: str | None = None,
) -> bool:
    """Append an entry to a module's operation log with FIFO rotation."""
    if module_name is None:
        module_name = _get_caller_module_name()
    try:
        ensure_module_jsons(module_name)
        config = load_json(module_name, "config")
        max_entries = 100
        if config and "config" in config:
            max_entries = config["config"].get("max_log_entries", 100)
        log = load_json(module_name, "log")
        if log is None:
            log = []
        entry: dict[str, Any] = {
            "timestamp": datetime.now().isoformat(),
            "operation": operation,
        }
        if data:
            entry["data"] = data
        log.append(entry)
        if len(log) > max_entries:
            log = log[-max_entries:]
        return save_json(module_name, "log", log)
    except Exception as exc:
        logger.warning("log_operation: failed for %s/%s: %s", module_name, operation, exc)
        return False
