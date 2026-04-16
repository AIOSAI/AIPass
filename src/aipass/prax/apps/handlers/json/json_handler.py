# =================== AIPass ====================
# Name: json_handler.py
# Description: Auto-Creating & Self-Healing JSON System
# Version: 1.0.0
# Created: 2025-11-15
# Modified: 2026-03-09
# =============================================

"""
JSON Handler - Auto-Creating & Self-Healing JSON System

Handles default JSON files (config, data, log) for prax modules.
Never manually create JSONs - they build themselves.
"""

import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional
import inspect

logger = logging.getLogger(__name__)

# Resolve paths relative to this file (no hardcoded paths)
_HANDLER_DIR = Path(__file__).resolve().parent  # .../handlers/json/
_HANDLERS_DIR = _HANDLER_DIR.parent  # .../handlers/
_PRAX_ROOT = _HANDLERS_DIR.parent.parent  # .../prax/
PRAX_JSON_DIR = _PRAX_ROOT / "prax_json"
JSON_TEMPLATES_DIR = _HANDLERS_DIR / "json_templates"


def _get_caller_module_name() -> str:
    """
    Auto-detect calling module name from call stack

    Returns:
        Module name (e.g., "imports_standard" from imports_standard.py)
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
        logger.warning("json_handler: failed to detect caller module name: %s", e)
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
        logger.warning("json_handler: failed to load template '%s' for module '%s': %s", json_type, module_name, e)
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
    return PRAX_JSON_DIR / filename


def ensure_json_exists(module_name: str, json_type: str) -> bool:
    """Ensure JSON file exists, create from template if missing"""
    PRAX_JSON_DIR.mkdir(parents=True, exist_ok=True)

    json_path = get_json_path(module_name, json_type)

    if json_path.exists():
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            if validate_json_structure(data, json_type):
                return True
            else:
                pass  # Corrupted - will regenerate
        except Exception as e:
            logger.warning("json_handler: unreadable json for '%s/%s', will regenerate: %s", module_name, json_type, e)

    template = load_template(json_type, module_name)
    if template is None:
        return False

    try:
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(template, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        logger.error("json_handler: failed to write json file '%s/%s': %s", module_name, json_type, e)
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
        logger.warning("json_handler: failed to load json '%s/%s': %s", module_name, json_type, e)
        return None


def _atomic_write(json_path: Path, content: str) -> None:
    """Write content to file atomically via temp file + rename.

    On Windows, ``os.replace`` can fail with PermissionError (WinError 5)
    when another process briefly holds the target file open (e.g. a reader
    scan). Retry with exponential backoff before giving up.
    """
    import os
    import tempfile
    import time

    fd, tmp_path = tempfile.mkstemp(dir=json_path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())

        last_exc: Exception | None = None
        for attempt in range(5):
            try:
                os.replace(tmp_path, json_path)
                return
            except PermissionError as exc:
                last_exc = exc
                logger.info(
                    "json_handler: os.replace attempt %d failed (PermissionError), retrying: %s", attempt + 1, exc
                )
                time.sleep(0.05 * (2**attempt))
        if last_exc is not None:
            raise last_exc
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError as cleanup_err:
            logger.warning("json_handler: temp file cleanup failed: %s", cleanup_err)
        raise


def save_json(module_name: str, json_type: str, data: Any) -> bool:
    """Save JSON file using atomic write (temp file + rename) to prevent corruption."""
    json_path = get_json_path(module_name, json_type)

    if not validate_json_structure(data, json_type):
        return False

    if json_type == "data" and isinstance(data, dict):
        data["last_updated"] = datetime.now().date().isoformat()

    try:
        content = json.dumps(data, indent=2, ensure_ascii=False)
        _atomic_write(json_path, content)
        return True
    except Exception as e:
        logger.error("json_handler: failed to save json '%s/%s': %s", module_name, json_type, e)
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


if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("JSON HANDLER - Working Implementation")
    print("=" * 70)
    print("\n[TESTING] Creating prax JSONs...")

    # Test auto-creation
    log_operation("test_operation", {"test": "data"}, "prax")

    print("\nCheck src/aipass/prax/prax_json/ for created files:")
    print("  - prax_config.json")
    print("  - prax_data.json")
    print("  - prax_log.json")
    print("\n" + "=" * 70 + "\n")
