# =================== AIPass ====================
# Name: json_handler.py
# Description: JSON auto-creating handler for drone data files
# Version: 1.0.0
# Created: 2026-03-17
# Modified: 2026-03-17
# =============================================

"""JSON auto-creating handler for drone data files.

Provides log_operation() for structured operation logging and
ensure_json_file() for auto-creating branch-scoped JSON files.
"""

from __future__ import annotations

import inspect
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from aipass.prax import logger

# ---------------------------------------------------------------------------
# Infrastructure — auto-detect branch root from file location
# json_handler.py -> json/ -> handlers/ -> apps/ -> drone/
# ---------------------------------------------------------------------------

_BRANCH_ROOT: Path = Path(__file__).resolve().parents[3]
_BRANCH_NAME: str = _BRANCH_ROOT.name  # "drone"
JSON_DIR: Path = _BRANCH_ROOT / f"{_BRANCH_NAME}_json"

_JSON_TYPES: tuple[str, ...] = ("config", "data", "log")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _today() -> str:
    """Return today's date as ISO string."""
    return datetime.now().date().isoformat()


def _get_caller_module_name() -> str:
    """Auto-detect calling module name from call stack.

    Walks past internal frames ([0] = this function, [1] = public function,
    [2] = actual caller) and returns the stem of the caller's filename.

    Returns:
        Module name (e.g. ``"flight_controller"`` from ``flight_controller.py``).
    """
    stack = inspect.stack()
    # Skip frames: [0]=this function, [1]=public wrapper, [2]=actual caller
    if len(stack) > 2:
        caller_path = Path(stack[2].filename)
        module_name = caller_path.stem
        if module_name and not module_name.startswith("_"):
            return module_name
    return "unknown"


def _atomic_write_json(path: Path, data: Any) -> None:
    """Write JSON atomically — write to temp file then rename.

    Prevents truncation/corruption during concurrent access.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp", prefix=".json_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
        os.replace(tmp_path, str(path))
    except BaseException as exc:
        logger.warning("_atomic_write_json: failed for %s: %s", path, exc)
        # Clean up temp file on failure — BaseException covers KeyboardInterrupt
        try:
            os.unlink(tmp_path)
        except OSError as cleanup_exc:
            logger.warning("_atomic_write_json: cleanup failed for %s: %s", tmp_path, cleanup_exc)
        raise


def _default_config(module_name: str) -> dict[str, Any]:
    """Return inline default for a *_config.json file."""
    today = _today()
    return {
        "module_name": module_name,
        "version": "1.0.0",
        "config": {
            "max_log_entries": 100,
        },
        "created": today,
        "last_updated": today,
    }


def _default_data(module_name: str) -> dict[str, Any]:
    """Return inline default for a *_data.json file."""
    today = _today()
    return {
        "created": today,
        "last_updated": today,
    }


def _default_log(module_name: str) -> list[Any]:  # noqa: ARG001
    """Return inline default for a *_log.json file."""
    return []


_DEFAULTS: dict[str, Any] = {
    "config": _default_config,
    "data": _default_data,
    "log": _default_log,
}


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_json_structure(data: Any, json_type: str) -> bool:
    """Validate that *data* matches the expected shape for *json_type*.

    Args:
        data: Parsed JSON data to validate.
        json_type: One of ``"config"``, ``"data"``, ``"log"``.

    Returns:
        ``True`` when the structure is valid, ``False`` otherwise.
    """
    if json_type == "config":
        if not isinstance(data, dict):
            return False
        required = ("module_name", "version", "config")
        return all(key in data for key in required)

    if json_type == "data":
        if not isinstance(data, dict):
            return False
        required = ("created", "last_updated")
        return all(key in data for key in required)

    if json_type == "log":
        return isinstance(data, list)

    return False


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def get_json_path(module_name: str, json_type: str) -> Path:
    """Return the filesystem path for *module_name*'s JSON of *json_type*.

    Args:
        module_name: Logical module name (e.g. ``"flight_controller"``).
        json_type: One of ``"config"``, ``"data"``, ``"log"``.

    Returns:
        Absolute :class:`~pathlib.Path` to the JSON file.
    """
    return JSON_DIR / f"{module_name}_{json_type}.json"


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


def ensure_json_exists(module_name: str, json_type: str) -> bool:
    """Ensure a single JSON file exists; create with inline defaults if missing.

    If the file exists but fails validation it is regenerated.

    Args:
        module_name: Logical module name.
        json_type: One of ``"config"``, ``"data"``, ``"log"``.

    Returns:
        ``True`` after the file is confirmed present and valid.
    """
    JSON_DIR.mkdir(parents=True, exist_ok=True)
    json_path = get_json_path(module_name, json_type)

    if json_path.exists():
        try:
            # Guard: empty or zero-byte files cause JSONDecodeError
            if json_path.stat().st_size == 0:
                logger.warning("ensure_json_exists: empty file at %s, regenerating", json_path)
            else:
                with open(json_path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                if validate_json_structure(data, json_type):
                    return True
                # Corrupted — fall through to regenerate
        except Exception as exc:  # noqa: BLE001
            logger.warning("ensure_json_exists: failed to read %s, regenerating: %s", json_path, exc)

    # Create from inline default
    factory = _DEFAULTS.get(json_type)
    if factory is None:
        raise ValueError(f"Unknown json_type: {json_type!r}")

    default = factory(module_name)
    _atomic_write_json(json_path, default)

    return True


def ensure_module_jsons(module_name: str) -> bool:
    """Ensure all three JSON files (config, data, log) exist for *module_name*.

    Args:
        module_name: Logical module name.

    Returns:
        ``True`` when all files are present and valid.
    """
    for json_type in _JSON_TYPES:
        ensure_json_exists(module_name, json_type)
    return True


def load_json(module_name: str, json_type: str) -> Any | None:
    """Load a module's JSON file, auto-creating it if missing.

    Args:
        module_name: Logical module name.
        json_type: One of ``"config"``, ``"data"``, ``"log"``.

    Returns:
        Parsed JSON data, or ``None`` on failure.
    """
    if not ensure_json_exists(module_name, json_type):
        return None

    json_path = get_json_path(module_name, json_type)
    try:
        if json_path.stat().st_size == 0:
            logger.warning("load_json: empty file at %s, returning default", json_path)
            factory = _DEFAULTS.get(json_type)
            return factory(module_name) if factory else None
        with open(json_path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("load_json: failed to read %s, returning default: %s", json_path, exc)
        factory = _DEFAULTS.get(json_type)
        return factory(module_name) if factory else None


def save_json(module_name: str, json_type: str, data: Any) -> bool:
    """Write *data* to the module's JSON file after validation.

    For ``"data"`` type files the ``last_updated`` field is refreshed
    automatically.

    Args:
        module_name: Logical module name.
        json_type: One of ``"config"``, ``"data"``, ``"log"``.
        data: The data structure to persist.

    Returns:
        ``True`` on success.

    Raises:
        ValueError: When *data* fails structure validation.
    """
    if not validate_json_structure(data, json_type):
        raise ValueError(f"Invalid structure for {json_type} JSON")

    if json_type == "data" and isinstance(data, dict):
        data["last_updated"] = _today()

    json_path = get_json_path(module_name, json_type)
    _atomic_write_json(json_path, data)
    return True


# ---------------------------------------------------------------------------
# High-level operations
# ---------------------------------------------------------------------------


def log_operation(
    operation: str,
    data: dict[str, Any] | None = None,
    module_name: str | None = None,
) -> bool:
    """Append an entry to a module's log with automatic FIFO rotation.

    Auto-detects the calling module when *module_name* is not supplied.
    Reads ``max_log_entries`` from the module's config (default 100) and
    trims oldest entries when the limit is exceeded.

    Args:
        operation: Short label for the logged action.
        data: Optional payload dict attached to the log entry.
        module_name: Explicit module name; auto-detected from stack if ``None``.

    Returns:
        ``True`` on success, ``False`` otherwise.
    """
    if module_name is None:
        module_name = _get_caller_module_name()

    try:
        ensure_module_jsons(module_name)

        # Read rotation limit from config
        config = load_json(module_name, "config")
        max_entries = 100
        if config and "config" in config:
            max_entries = config["config"].get("max_log_entries", 100)

        # Load existing log
        log = load_json(module_name, "log")
        if log is None:
            log = []

        # Build entry
        entry: dict[str, Any] = {
            "timestamp": datetime.now().isoformat(),
            "operation": operation,
        }
        if data:
            entry["data"] = data

        log.append(entry)

        # FIFO rotation — keep only the most recent entries
        if len(log) > max_entries:
            log = log[-max_entries:]

        return save_json(module_name, "log", log)
    except Exception as exc:
        logger.warning("log_operation: failed for %s/%s, skipping: %s", module_name, operation, exc)
        return False


def increment_counter(
    module_name: str,
    counter_name: str,
    amount: int = 1,
) -> bool:
    """Increment a named counter in a module's data JSON.

    Creates the counter initialised to ``0`` if it does not yet exist.

    Args:
        module_name: Logical module name.
        counter_name: Key within the data dict.
        amount: Value to add (default ``1``).

    Returns:
        ``True`` on success, ``False`` otherwise.
    """
    ensure_module_jsons(module_name)

    data = load_json(module_name, "data")
    if data is None:
        return False

    if counter_name not in data:
        data[counter_name] = 0

    data[counter_name] += amount
    return save_json(module_name, "data", data)


def update_data_metrics(module_name: str, **metrics: Any) -> bool:
    """Merge arbitrary key/value pairs into a module's data JSON.

    Args:
        module_name: Logical module name.
        **metrics: Keyword arguments written directly into the data dict.

    Returns:
        ``True`` on success, ``False`` otherwise.
    """
    ensure_module_jsons(module_name)

    data = load_json(module_name, "data")
    if data is None:
        return False

    for key, value in metrics.items():
        data[key] = value

    return save_json(module_name, "data", data)


# ---------------------------------------------------------------------------
# __all__ — controls `from .json_handler import *`
# ---------------------------------------------------------------------------

__all__ = [
    "JSON_DIR",
    "ensure_json_exists",
    "ensure_module_jsons",
    "get_json_path",
    "increment_counter",
    "load_json",
    "log_operation",
    "save_json",
    "update_data_metrics",
    "validate_json_structure",
]


# ---------------------------------------------------------------------------
# Quick smoke-test when run directly
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from rich.console import Console
    from rich.panel import Panel

    console = Console()
    console.print()
    console.print(
        Panel.fit(
            "[bold cyan]JSON HANDLER (drone) — Smoke Test[/bold cyan]",
            border_style="bright_blue",
        )
    )
    console.print()
    console.print(f"[dim]Branch root:[/dim]  {_BRANCH_ROOT}")
    console.print(f"[dim]JSON dir:[/dim]     {JSON_DIR}")
    console.print()

    console.print("[yellow]TESTING:[/yellow] Creating drone JSONs...")
    log_operation("smoke_test", {"status": "ok"}, "drone")
    increment_counter("drone", "smoke_runs", 1)
    update_data_metrics("drone", smoke_metric="working")

    console.print()
    console.print("[green]Check drone/drone_json/ for created files:[/green]")
    for jt in _JSON_TYPES:
        console.print(f"  [dim]>[/dim] drone_{jt}.json")
    console.print()
