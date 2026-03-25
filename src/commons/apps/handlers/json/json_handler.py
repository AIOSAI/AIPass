# =================== AIPass ====================
# Name: json_handler.py
# Description: JSON Auto-Creating Handler
# Version: 1.0.0
# Created: 2026-03-07
# Modified: 2026-03-07
# =============================================

"""
JSON auto-creating handler for The Commons.

Manages per-module JSON files (config, data, log) with template-based
auto-creation, validation, and log rotation.
"""

import json
import os
import inspect
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional

from aipass.prax.apps.modules.logger import system_logger as logger

# Constants - relative path resolution (pip-safe, no hardcoded absolutes)
_HANDLER_DIR = Path(__file__).resolve().parent          # .../commons/apps/handlers/json/
_APPS_DIR = _HANDLER_DIR.parent.parent                  # .../commons/apps/
_COMMONS_ROOT = _APPS_DIR.parent                        # .../commons/
BRANCH_JSON_DIR = str(_COMMONS_ROOT / "commons_json")


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

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(template, f, indent=2, ensure_ascii=False)
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

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
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
