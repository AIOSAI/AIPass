# =================== AIPass ====================
# Name: json_handler.py
# Description: Auto-Creating JSON Handler
# Version: 2.1.0
# Created: 2025-11-21
# Modified: 2025-11-21
# =============================================

"""
JSON Handler - Auto-Creating & Self-Healing JSON System

Handles default JSON files (config, data, log) for flow modules.
Never manually create JSONs - they build themselves.
"""

import json
import os
import tempfile
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional
import inspect

from aipass.prax.apps.modules.logger import system_logger as logger

# Infrastructure
_PKG_ROOT = Path(__file__).resolve().parents[4]

# Constants
FLOW_ROOT = _PKG_ROOT / "flow"
FLOW_JSON_DIR = FLOW_ROOT / "flow_json"


def _get_caller_module_name() -> str:
    """
    Auto-detect calling module name from call stack

    Returns:
        Module name (e.g., "create_plan" from create_plan.py)
    """
    try:
        stack = inspect.stack()
        # Skip frames: [0]=this function, [1]=log_operation, [2]=actual caller
        if len(stack) > 2:
            caller_frame = stack[2]
            caller_path = Path(caller_frame.filename)
            module_name = caller_path.stem

            # Validate module name
            if module_name and not module_name.startswith('_'):
                return module_name

        # Fallback
        return "unknown"
    except Exception as exc:
        logger.warning("[json_handler] Failed to detect caller module name: %s", exc)
        return "unknown"


def _default_template(json_type: str, module_name: str) -> Any:
    """Return inline default structure for a JSON type — no file templates needed."""
    today = datetime.now().date().isoformat()
    if json_type == "config":
        return {
            "module_name": module_name,
            "version": "1.0.0",
            "config": {
                "max_log_entries": 100,
            },
            "created": today,
        }
    if json_type == "data":
        return {
            "created": today,
            "last_updated": today,
        }
    if json_type == "log":
        return []
    return None


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


def _atomic_write_json(target_path: Path, data: Any) -> None:
    """Write JSON data atomically via temp file + rename.

    Prevents corruption from concurrent processes writing the same file.
    """
    fd, tmp_path = tempfile.mkstemp(
        dir=str(target_path.parent), suffix=".tmp", prefix=target_path.stem
    )
    succeeded = False
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, str(target_path))
        succeeded = True
    finally:
        if not succeeded and Path(tmp_path).exists():
            logger.warning("[json_handler] Cleaning up temp file after write failure: %s", tmp_path)
            os.unlink(tmp_path)


def get_json_path(module_name: str, json_type: str) -> Path:
    """Get path for module JSON file"""
    filename = f"{module_name}_{json_type}.json"
    return FLOW_JSON_DIR / filename


def ensure_json_exists(module_name: str, json_type: str) -> bool:
    """Ensure JSON file exists, create from template if missing"""
    FLOW_JSON_DIR.mkdir(parents=True, exist_ok=True)

    json_path = get_json_path(module_name, json_type)

    if json_path.exists():
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            if validate_json_structure(data, json_type):
                return True
        except Exception as exc:
            # File exists but is corrupted - will regenerate below
            logger.warning("[json_handler] Corrupted JSON file for '%s/%s', regenerating: %s", module_name, json_type, exc)

    template = _default_template(json_type, module_name)
    if template is None:
        return False

    try:
        _atomic_write_json(json_path, template)
        return True
    except Exception as exc:
        logger.error("[json_handler] Failed to write JSON template for '%s/%s': %s", module_name, json_type, exc)
        return False


def load_json(module_name: str, json_type: str) -> Optional[Any]:
    """Load JSON file, auto-create if missing"""
    if not ensure_json_exists(module_name, json_type):
        return None

    json_path = get_json_path(module_name, json_type)

    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as exc:
        logger.error("[json_handler] Failed to load JSON for '%s/%s': %s", module_name, json_type, exc)
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
    except Exception as exc:
        logger.error("[json_handler] Failed to save JSON for '%s/%s': %s", module_name, json_type, exc)
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
    """
    # Auto-detect module name if not provided
    if module_name is None:
        module_name = _get_caller_module_name()

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
    entry: Dict[str, Any] = {
        "timestamp": datetime.now().isoformat(),
        "operation": operation
    }

    if data:
        entry["data"] = data

    # Add new entry
    log.append(entry)

    # Rotate if exceeds max (keep most recent entries)
    if len(log) > max_entries:
        log = log[-max_entries:]

    return save_json(module_name, "log", log)


def increment_counter(module_name: str, counter_name: str, amount: int = 1) -> bool:
    """Increment a counter in data JSON"""
    ensure_module_jsons(module_name)

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
    console.print(Panel.fit(
        "[bold cyan]JSON HANDLER - Working Implementation[/bold cyan]",
        border_style="bright_blue"
    ))
    console.print()
    console.print("[yellow]TESTING:[/yellow] Creating FLOW JSONs...")

    # Test auto-creation
    log_operation("test_operation", {"test": "data"}, "flow")
    increment_counter("flow", "test_counter", 1)
    update_data_metrics("flow", test_metric="working")

    console.print()
    console.print("[green]Check flow/flow_json/ for created files:[/green]")
    console.print("  [dim]•[/dim] flow_config.json")
    console.print("  [dim]•[/dim] flow_data.json")
    console.print("  [dim]•[/dim] flow_log.json")
    console.print()
