# =================== AIPass ====================
# Name: json_handler.py
# Description: Auto-Creating JSON Handler
# Version: 1.0.0
# Created: 2026-03-17
# Modified: 2026-03-17
# =============================================

"""
JSON Handler - Auto-Creating & Self-Healing JSON System

Handles default JSON files (config, data, log) for skills modules.
Never manually create JSONs - they build themselves.
"""

import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional
import inspect

from aipass.prax import logger


# Infrastructure
_BRANCH_ROOT = Path(__file__).resolve().parents[3]

# Constants
SKILLS_JSON_DIR = _BRANCH_ROOT / "skills_json"


def _get_caller_module_name() -> str:
    """
    Auto-detect calling module name from call stack.

    Returns:
        Module name (e.g., "discovery" from discovery.py)
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

        return "unknown"
    except Exception:
        logger.warning("Failed to detect caller module name from stack")
        return "unknown"


def _get_default(json_type: str, module_name: str) -> Any:
    """Return inline default structure for a JSON type."""
    now = datetime.now().date().isoformat()
    if json_type == "config":
        return {
            "module_name": module_name,
            "version": "1.0.0",
            "timestamp": now,
            "config": {"auto_save": True, "enabled": True},
        }
    if json_type == "data":
        return {
            "module_name": module_name,
            "created": now,
            "last_updated": now,
            "operations_total": 0,
            "operations_successful": 0,
            "operations_failed": 0,
        }
    if json_type == "log":
        return []
    return None


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
    return SKILLS_JSON_DIR / filename


def ensure_json_exists(module_name: str, json_type: str) -> bool:
    """Ensure JSON file exists, create from template if missing."""
    SKILLS_JSON_DIR.mkdir(parents=True, exist_ok=True)

    json_path = get_json_path(module_name, json_type)

    if json_path.exists():
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            if validate_json_structure(data, json_type):
                return True
        except Exception:
            logger.warning(f"Corrupt JSON file, will recreate: {json_path}")

    template = _get_default(json_type, module_name)
    if template is None:
        return False

    try:
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(template, f, indent=2, ensure_ascii=False)
        return True
    except Exception:
        logger.error(f"Failed to write JSON file: {json_path}")
        return False


def load_json(module_name: str, json_type: str) -> Optional[Any]:
    """Load JSON file, auto-create if missing."""
    if not ensure_json_exists(module_name, json_type):
        return None

    json_path = get_json_path(module_name, json_type)

    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        logger.warning(f"Failed to load JSON: {json_path}")
        return None


def save_json(module_name: str, json_type: str, data: Any) -> bool:
    """Save JSON file."""
    json_path = get_json_path(module_name, json_type)

    if not validate_json_structure(data, json_type):
        return False

    if json_type == "data" and isinstance(data, dict):
        data["last_updated"] = datetime.now().date().isoformat()

    try:
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except Exception:
        logger.error(f"Failed to save JSON for {module_name}/{json_type}")
        return False


def ensure_module_jsons(module_name: str) -> bool:
    """Ensure all 3 JSON files exist for a module."""
    ensure_json_exists(module_name, "config")
    ensure_json_exists(module_name, "data")
    ensure_json_exists(module_name, "log")
    return True


def log_operation(operation: str, data: Dict[str, Any] | None = None, module_name: str | None = None) -> bool:
    """
    Add entry to module log with automatic rotation.

    Auto-detects calling module if module_name not provided.
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

    # Load config to get max_log_entries
    config = load_json(module_name, "config")
    max_entries = 100
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

    log.append(entry)

    # Rotate if exceeds max
    if len(log) > max_entries:
        log = log[-max_entries:]

    return save_json(module_name, "log", log)
