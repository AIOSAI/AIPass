# =================== AIPass ====================
# Name: json_handler.py
# Description: JSON Handler
# Version: 1.0.0
# Created: 2025-11-15
# Modified: 2025-11-15
# =============================================

"""
JSON Handler - Auto-Creating & Self-Healing JSON System

Handles default JSON files (config, data, log) for AI_MAIL modules.
Never manually create JSONs - they build themselves.
"""

import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional
import inspect

from aipass.prax.apps.modules.logger import system_logger as logger

# Infrastructure paths (package-relative)
_AI_MAIL_ROOT = Path(__file__).resolve().parents[3]  # ai_mail/

# Constants - Updated for AI_MAIL
AI_MAIL_JSON_DIR = _AI_MAIL_ROOT / "ai_mail_json"
JSON_TEMPLATES_DIR = _AI_MAIL_ROOT / "apps" / "json_templates"


def _get_caller_module_name() -> str:
    """
    Auto-detect calling module name from call stack

    Returns:
        Module name (e.g., "email" from email.py)
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
        logger.warning("[json] Failed to detect caller module: %s", e)
        return "unknown"


def load_template(json_type: str, module_name: str) -> Any:
    """Load JSON template from template file"""
    template_path = JSON_TEMPLATES_DIR / "default" / f"{json_type}.json"

    if not template_path.exists():
        return None

    try:
        with open(template_path, "r", encoding="utf-8") as f:
            template = json.load(f)

        # Replace placeholders
        template_str = json.dumps(template)
        template_str = template_str.replace("{{MODULE_NAME}}", module_name)
        template_str = template_str.replace("{{TIMESTAMP}}", datetime.now().date().isoformat())

        return json.loads(template_str)
    except Exception as e:
        logger.warning("[json] Failed to load template: %s", e)
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


def get_json_path(module_name: str, json_type: str) -> Path:
    """Get path for module JSON file"""
    filename = f"{module_name}_{json_type}.json"
    return AI_MAIL_JSON_DIR / filename


def ensure_json_exists(module_name: str, json_type: str) -> bool:
    """Ensure JSON file exists, create from template if missing"""
    AI_MAIL_JSON_DIR.mkdir(parents=True, exist_ok=True)

    json_path = get_json_path(module_name, json_type)

    if json_path.exists():
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            if validate_json_structure(data, json_type):
                return True
        except Exception as e:
            logger.warning("[json] Failed to validate existing JSON for %s: %s", module_name, e)

    template = load_template(json_type, module_name)
    if template is None:
        return False

    try:
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(template, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        logger.warning("[json] Failed to write JSON template for %s: %s", module_name, e)
        return False


def load_json(module_name: str, json_type: str) -> Optional[Any]:
    """Load JSON file, auto-create if missing"""
    if not ensure_json_exists(module_name, json_type):
        return None

    json_path = get_json_path(module_name, json_type)

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning("[json] Failed to load JSON for %s: %s", module_name, e)
        return None


def save_json(module_name: str, json_type: str, data: Any) -> bool:
    """Save JSON file"""
    json_path = get_json_path(module_name, json_type)

    if not validate_json_structure(data, json_type):
        return False

    if json_type == "data" and isinstance(data, dict):
        data["last_updated"] = datetime.now().date().isoformat()

    try:
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        logger.warning("[json] Failed to save JSON for %s: %s", module_name, e)
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
    entry: Dict[str, Any] = {"timestamp": datetime.now().isoformat(), "operation": operation}

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
    print("\n" + "=" * 70)
    print("JSON HANDLER - AI_MAIL Working Implementation")
    print("=" * 70)
    print("\n[TESTING] Creating AI_MAIL JSONs...")

    # Test auto-creation
    log_operation("test_operation", {"test": "data"}, "ai_mail")
    increment_counter("ai_mail", "test_counter", 1)
    update_data_metrics("ai_mail", test_metric="working")

    print(f"\nCheck {AI_MAIL_JSON_DIR}/ for created files:")
    print("  - ai_mail_config.json")
    print("  - ai_mail_data.json")
    print("  - ai_mail_log.json")
    print("\n" + "=" * 70 + "\n")
