# =================== AIPass ====================
# Name: json_handler.py
# Description: Auto-Creating JSON Handler for aipass branch
# Version: 1.0.0
# Created: 2026-04-16
# Modified: 2026-04-16
# =============================================

"""
JSON Handler - Auto-Creating & Self-Healing JSON System

Handles default JSON files (config, data, log) for aipass modules.
Never manually create JSONs - they build themselves.
"""

from __future__ import annotations

import inspect
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from aipass.prax import logger

# =============================================================================
# INFRASTRUCTURE SETUP
# =============================================================================

# json_handler.py lives at: src/aipass/aipass/apps/handlers/json/json_handler.py
# parents[0] = json/, [1] = handlers/, [2] = apps/, [3] = aipass/, [4] = src/aipass/
_PKG_ROOT = Path(__file__).resolve().parents[4]

# Constants
AIPASS_BRANCH_ROOT = _PKG_ROOT / "aipass"
AIPASS_JSON_DIR = AIPASS_BRANCH_ROOT / "aipass_json"


# =============================================================================
# INTERNAL HELPERS
# =============================================================================


def _get_caller_module_name() -> str:
    """Auto-detect calling module name from call stack.

    Returns:
        Module name (e.g., "doctor" from doctor.py)
    """
    try:
        stack = inspect.stack()
        # Skip frames: [0]=this function, [1]=log_operation, [2]=actual caller
        if len(stack) > 2:
            caller_frame = stack[2]
            caller_path = Path(caller_frame.filename)
            module_name = caller_path.stem

            if module_name and not module_name.startswith("_"):
                return module_name

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


def _atomic_write_json(target_path: Path, data: Any) -> None:
    """Write JSON data atomically via temp file + rename.

    Prevents corruption from concurrent processes writing the same file.
    """
    fd, tmp_path = tempfile.mkstemp(dir=str(target_path.parent), suffix=".tmp", prefix=target_path.stem)
    succeeded = False
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, str(target_path))
        succeeded = True
    finally:
        if not succeeded and Path(tmp_path).exists():
            logger.warning("[json_handler] Cleaning up temp file after write failure: %s", tmp_path)
            os.unlink(tmp_path)


# =============================================================================
# VALIDATION
# =============================================================================


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


# =============================================================================
# PUBLIC API
# =============================================================================


def load_path(path: Path) -> Any:
    """Load JSON from an arbitrary file path with consistent error handling."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("[json_handler] Failed to load %s: %s", path, exc)
        return None


def save_path(path: Path, data: Any) -> bool:
    """Write JSON data to an arbitrary file path atomically."""
    os.makedirs(path.parent, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp", prefix=path.stem)
    succeeded = False
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp_path, str(path))
        succeeded = True
        return True
    except OSError as exc:
        logger.warning("[json_handler] Failed to save %s: %s", path, exc)
        return False
    finally:
        if not succeeded and Path(tmp_path).exists():
            os.unlink(tmp_path)


def get_json_path(module_name: str, json_type: str) -> Path:
    """Get path for module JSON file."""
    filename = f"{module_name}_{json_type}.json"
    return AIPASS_JSON_DIR / filename


def ensure_json_exists(module_name: str, json_type: str) -> bool:
    """Ensure JSON file exists, create from template if missing."""
    AIPASS_JSON_DIR.mkdir(parents=True, exist_ok=True)

    json_path = get_json_path(module_name, json_type)

    if json_path.exists():
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            if validate_json_structure(data, json_type):
                return True
        except Exception as exc:
            logger.warning(
                "[json_handler] Corrupted JSON file for '%s/%s', regenerating: %s",
                module_name,
                json_type,
                exc,
            )

    template = _default_template(json_type, module_name)
    if template is None:
        return False

    try:
        _atomic_write_json(json_path, template)
        return True
    except Exception as exc:
        logger.error(
            "[json_handler] Failed to write JSON template for '%s/%s': %s",
            module_name,
            json_type,
            exc,
        )
        return False


def load_json(module_name: str, json_type: str) -> Optional[Any]:
    """Load JSON file, auto-create if missing."""
    if not ensure_json_exists(module_name, json_type):
        return None

    json_path = get_json_path(module_name, json_type)

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        logger.error("[json_handler] Failed to load JSON for '%s/%s': %s", module_name, json_type, exc)
        return None


def save_json(module_name: str, json_type: str, data: Any) -> bool:
    """Save JSON file."""
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
    """Ensure all 3 JSON files exist for a module."""
    ensure_json_exists(module_name, "config")
    ensure_json_exists(module_name, "data")
    ensure_json_exists(module_name, "log")
    return True


def log_operation(
    operation: str,
    data: Dict[str, Any] | None = None,
    module_name: str | None = None,
) -> bool:
    """Add entry to module log with automatic rotation.

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
    max_entries = 100
    if config and "config" in config:
        max_entries = config["config"].get("max_log_entries", 100)

    log = load_json(module_name, "log")
    if log is None:
        log = []

    entry: Dict[str, Any] = {"timestamp": datetime.now().isoformat(), "operation": operation}

    if data:
        entry["data"] = data

    log.append(entry)

    if len(log) > max_entries:
        log = log[-max_entries:]

    return save_json(module_name, "log", log)
