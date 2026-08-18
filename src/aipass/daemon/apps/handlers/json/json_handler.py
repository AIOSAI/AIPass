# =================== AIPass ====================
# Name: json_handler.py
# Description: JSON Auto-Creating Handler
# Version: 1.4.0
# Created: 2025-11-21
# Modified: 2026-08-18
# =============================================

"""
JSON handler for DAEMON branch.

Provides auto-creating JSON file management with templates.
"""

import json
import os
import sys
import tempfile
import time
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional
import inspect

if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8", errors="replace")

from aipass.prax import logger

# Constants
_DAEMON_ROOT = Path(__file__).resolve().parents[3]  # src/aipass/daemon/
JSON_DIR = _DAEMON_ROOT / "daemon_json"
MAX_LOG_ENTRIES = 100  # Default FIFO limit for log_operation (overridable via config)


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
    Write a JSON document so a reader sees either the old one or the new one.

    Args:
        target_path: The document to replace.
        data: What to write.

    Raises:
        OSError: The staged file could not be written or moved into place.

    Note:
        Opening the target with "w" truncates it BEFORE the new content lands,
        so every concurrent reader in that window gets an empty or partial
        file. In this handler that is not merely a bad read: ensure_json_exists
        answers an unreadable document by writing a fresh template over it, so
        a torn read becomes permanent data loss. As the scheduler, @daemon
        reads configs while branches write them - measured on the unfixed
        handler with 2 writers and 2 readers, 12,117 of 13,103 reads (92.5%)
        came back empty or unparseable. os.replace is atomic on POSIX and
        Windows, so the window does not exist. On Windows it can still raise PermissionError while a
        reader holds the target open, so the move goes through
        _replace_with_retry — bounded, then raises (proven by the Windows CI
        hang of 2026-08-18). The staged file MUST live in the
        target's own directory or the rename becomes a cross-device copy.
        Mirrors the helper @api, @cli, @commons, @flow, @drone and @prax carry.
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
            # this handler reads from.
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
        caller_path = Path(caller_frame.filename)
        module_name = caller_path.stem

        if module_name and not module_name.startswith("_"):
            return module_name

    return "unknown"


def _default_template(json_type: str, module_name: str) -> Any:
    """Return inline default structure for a JSON type."""
    current_date = datetime.now().date().isoformat()
    if json_type == "config":
        return {
            "module_name": module_name,
            "version": "1.0.0",
            "timestamp": current_date,
            "config": {"auto_save": True, "enabled": True},
        }
    elif json_type == "data":
        return {
            "module_name": module_name,
            "created": current_date,
            "last_updated": current_date,
            "operations_total": 0,
        }
    elif json_type == "log":
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


def get_json_path(module_name: str, json_type: str) -> Path:
    """Get path for module JSON file."""
    filename = f"{module_name}_{json_type}.json"
    return JSON_DIR / filename


def ensure_json_exists(module_name: str, json_type: str) -> bool:
    """Ensure JSON file exists, create from template if missing."""
    JSON_DIR.mkdir(parents=True, exist_ok=True)

    json_path = get_json_path(module_name, json_type)

    if json_path.exists():
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            if validate_json_structure(data, json_type):
                return True
        except json.JSONDecodeError as e:
            logger.warning("[json_handler] Corrupted JSON file %s, regenerating: %s", json_path.name, e)
        except OSError as e:
            logger.warning("[json_handler] Unreadable JSON file %s, regenerating: %s", json_path.name, e)

    template = _default_template(json_type, module_name)

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


def log_operation(operation: str, data: Optional[Dict[str, Any]] = None, module_name: Optional[str] = None) -> bool:
    """
    Add entry to module log with automatic rotation.

    Auto-detects calling module if module_name not provided.
    Implements config-controlled log limits to prevent unbounded growth.
    When max_log_entries is reached, removes oldest entries (FIFO).

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
    max_entries = MAX_LOG_ENTRIES
    if config and "config" in config:
        max_entries = config["config"].get("max_log_entries", MAX_LOG_ENTRIES)

    log: List[Dict[str, Any]] = load_json(module_name, "log") or []

    entry: Dict[str, Any] = {"timestamp": datetime.now().isoformat(), "operation": operation}

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


if __name__ == "__main__":
    from rich.console import Console
    from rich.panel import Panel

    console = Console()

    console.print()
    console.print(Panel.fit("[bold cyan]JSON HANDLER - Working Implementation[/bold cyan]", border_style="bright_blue"))
    console.print()
    console.print("[yellow]TESTING:[/yellow] Creating daemon JSONs...")

    log_operation("test_operation", {"test": "data"}, "daemon")
    increment_counter("daemon", "test_counter", 1)
    update_data_metrics("daemon", test_metric="working")

    console.print()
    console.print(f"[green]Check {JSON_DIR}/ for created files:[/green]")
    console.print("  [dim]-[/dim] daemon_config.json")
    console.print("  [dim]-[/dim] daemon_data.json")
    console.print("  [dim]-[/dim] daemon_log.json")
    console.print()
