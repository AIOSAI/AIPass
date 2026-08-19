# =================== AIPass ====================
# Name: json_handler.py
# Description: JSON auto-creating handler for trigger data files
# Version: 1.2.0
# Created: 2025-11-13
# Modified: 2026-08-09
# =============================================

"""JSON auto-creating handler for trigger data files."""

import json
import os
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional
import inspect

from aipass.trigger.apps.config import (
    atomic_create_json,
    atomic_write_json,
    json_file_lock,
    read_text_with_retry,
    trail_logger,
)

if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8", errors="replace")

# Infrastructure — redirect to temp dir during tests
_test_log_dir = os.environ.get("AIPASS_TEST_LOG_DIR")
if _test_log_dir:
    _LOG_FILE = Path(_test_log_dir) / "trigger" / "json_handler.jsonl"
else:
    _LOG_FILE = Path(__file__).parent.parent.parent.parent / "logs" / "json_handler.jsonl"

# Deliberately NOT prax: json_handler is called from the event handlers that run
# on the path the log watchers read, so a line through prax would be detected and
# fired back at them. The sidecar is `.jsonl` — the watchers read only `*.log`.
logger = trail_logger(_LOG_FILE)


# Constants
TRIGGER_ROOT = Path(__file__).resolve().parents[3]
TRIGGER_JSON_DIR = TRIGGER_ROOT / "trigger_json"


def _get_caller_module_name() -> str:
    """
    Auto-detect calling module name from call stack

    Returns:
        Module name (e.g., "imports_standard" from imports_standard.py)
    """
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


def _get_default_template(json_type: str, module_name: str) -> Any:
    """Return default JSON structure for a given type (inline, no file templates)."""
    today = datetime.now().date().isoformat()
    if json_type == "config":
        return {
            "module_name": module_name,
            "version": "1.0.0",
            "timestamp": today,
            "config": {"auto_save": True, "enabled": True},
        }
    elif json_type == "data":
        return {
            "module_name": module_name,
            "created": today,
            "last_updated": today,
            "operations_total": 0,
            "operations_successful": 0,
            "operations_failed": 0,
        }
    elif json_type == "log":
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
    return TRIGGER_JSON_DIR / filename


def ensure_json_exists(module_name: str, json_type: str) -> bool:
    """Ensure JSON file exists, create from template if missing"""
    TRIGGER_JSON_DIR.mkdir(parents=True, exist_ok=True)

    json_path = get_json_path(module_name, json_type)

    if json_path.exists():
        try:
            data = json.loads(read_text_with_retry(json_path))

            if validate_json_structure(data, json_type):
                return True
            # Known bad: it parsed and the shape is wrong. Regenerate.
        except OSError as exc:
            # COULD NOT READ is not KNOWN BAD. Windows refuses an open while
            # another writer's os.replace is in flight, and regenerating here
            # threw away whole documents: 2 concurrent appends on disk, one
            # refused open, both gone (Windows CI 32167459635, 98 of 100).
            # The file exists; leave it exactly as it is and let the caller's
            # own read — inside the lock — decide.
            logger.warning(f"ensure_json_exists could not read {module_name}_{json_type}, NOT regenerating: {exc}")
            return True
        except Exception as exc:
            # Undecodable bytes: genuinely corrupt, regenerate.
            logger.warning(f"ensure_json_exists found {module_name}_{json_type} corrupt, regenerating: {exc}")

        # A document we READ and judged bad: replacing it is the whole point.
        atomic_write_json(json_path, _get_default_template(json_type, module_name), ensure_ascii=False)
        return True

    # Missing: CREATE, never overwrite — and decide that from what we observed
    # above, not from a second exists() check, which is the same check-then-act
    # race one line further down. Two callers can both arrive here with the
    # document still absent, and this runs outside every lock, so a replacing
    # write lets the slower one bury whatever a lock holder has written since.
    # Linux CI 32228159169: 99 of 100. Reproduced locally, 3 losses in 400.
    atomic_create_json(json_path, _get_default_template(json_type, module_name), ensure_ascii=False)
    return True


def load_json(module_name: str, json_type: str) -> Optional[Any]:
    """Load JSON file, auto-create if missing.

    Guards against empty or corrupt JSON files by regenerating from template.
    """
    if not ensure_json_exists(module_name, json_type):
        return None

    json_path = get_json_path(module_name, json_type)

    try:
        content = read_text_with_retry(json_path).strip()
        if not content:
            logger.warning(f"load_json empty file for {module_name}_{json_type}, will regenerate")
            ensure_json_exists(module_name, json_type)
            content = read_text_with_retry(json_path).strip()
        return json.loads(content)
    except OSError as exc:
        # Cannot-read is reported as cannot-read. Regenerating here would hand
        # the caller an empty document that it would then save over the real
        # one — the read failure laundered into data loss. See ensure_json_exists.
        logger.warning(f"load_json could not read {module_name}_{json_type}, declining: {exc}")
        return None
    except json.JSONDecodeError as exc:
        logger.warning(f"load_json found {module_name}_{json_type} corrupt, regenerating: {exc}")
        ensure_json_exists(module_name, json_type)
        try:
            return json.loads(read_text_with_retry(json_path))
        except Exception as regen_exc:
            # Regeneration itself came back unreadable — the caller still gets a
            # usable shape, but the disk is in a state somebody should know about.
            logger.error(f"load_json regeneration failed for {module_name}_{json_type}: {regen_exc}")
            return _get_default_template(json_type, module_name)


def save_json(module_name: str, json_type: str, data: Any) -> bool:
    """Save JSON file"""
    json_path = get_json_path(module_name, json_type)

    if not validate_json_structure(data, json_type):
        raise ValueError(f"Invalid structure for {json_type} JSON")

    if json_type == "data" and isinstance(data, dict):
        data["last_updated"] = datetime.now().date().isoformat()

    atomic_write_json(json_path, data, ensure_ascii=False)
    return True


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
    """
    # Auto-detect module name if not provided
    if module_name is None:
        module_name = _get_caller_module_name()

    ensure_module_jsons(module_name)

    # The whole read-append-write cycle is one critical section. atomic_write_json
    # already stops a torn file, but atomic is not serialised: two callers that
    # each read this log, append their own entry and write the result back both
    # succeed, and the second one's document has no trace of the first. Measured
    # unlocked on this handler — 100 appends asked, 62 on disk, 38 lost silently
    # with every call returning True. Not theoretical: prax fires `startup` on the
    # first log call of every process, and startup_log.json takes ~14 writes a
    # minute from concurrent short-lived processes.
    with json_file_lock(get_json_path(module_name, "log")):
        # Load config to get max_log_entries
        config = load_json(module_name, "config")
        max_entries = 100  # Default
        if config and "config" in config:
            max_entries = config["config"].get("max_log_entries", 100)

        # Load existing log. None means the read could not be performed —
        # writing here would put a one-entry document over a full one, which
        # is exactly how Windows CI lost two appends. increment_counter and
        # update_data_metrics already refuse; this path did not.
        log = load_json(module_name, "log")
        if log is None:
            return False

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


def increment_counter(module_name: str, counter_name: str, amount: int = 1) -> bool:
    """Increment a counter in data JSON"""
    ensure_module_jsons(module_name)

    # Read-modify-write — the classic lost update. See log_operation.
    with json_file_lock(get_json_path(module_name, "data")):
        data = load_json(module_name, "data")
        if data is None:
            return False

        if counter_name not in data:
            data[counter_name] = 0

        data[counter_name] += amount

        return save_json(module_name, "data", data)


def update_data_metrics(module_name: str, **metrics) -> bool:
    """Update data metrics"""
    ensure_module_jsons(module_name)

    # Read-modify-write — two writers of DIFFERENT keys still lose one. See log_operation.
    with json_file_lock(get_json_path(module_name, "data")):
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
    console.print("[yellow]TESTING:[/yellow] Creating trigger JSONs...")

    # Test auto-creation
    log_operation("test_operation", {"test": "data"}, "trigger")
    increment_counter("trigger", "test_counter", 1)
    update_data_metrics("trigger", test_metric="working")

    console.print()
    console.print("[green]Check trigger/trigger_json/ for created files:[/green]")
    console.print("  [dim]•[/dim] trigger_config.json")
    console.print("  [dim]•[/dim] trigger_data.json")
    console.print("  [dim]•[/dim] trigger_log.json")
    console.print()
