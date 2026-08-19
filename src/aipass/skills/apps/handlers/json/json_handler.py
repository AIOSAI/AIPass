# =================== AIPass ====================
# Name: json_handler.py
# Description: Auto-Creating JSON Handler
# Version: 1.2.0
# Created: 2026-03-17
# Modified: 2026-08-18
# =============================================

"""
JSON Handler - Auto-Creating & Self-Healing JSON System

Handles default JSON files (config, data, log) for skills modules.
Never manually create JSONs - they build themselves.
"""

import json
import os
import tempfile
import time
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional
import inspect

from aipass.prax import logger


# Infrastructure
_BRANCH_ROOT = Path(__file__).resolve().parents[3]

# Constants
SKILLS_JSON_DIR = _BRANCH_ROOT / "skills_json"


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
        file. Here that is not merely a bad read: ensure_json_exists answers an
        unreadable document by writing a fresh template over it, so a torn read
        becomes permanent data loss. Measured on this handler unfixed, with 2
        writers and 2 readers, three runs: 86.9%, 90.2% and 91.4% of concurrent
        reads came back empty or unparseable. os.replace is atomic on POSIX and
        Windows, so the window does not exist. On Windows it can still raise PermissionError while a
        reader holds the target open, so the move goes through
        _replace_with_retry — bounded, then raises (proven by the Windows CI
        hang of 2026-08-18). The staged file MUST live in the
        target's own directory or the rename becomes a cross-device copy.
        Mirrors the helper @api, @cli, @commons and @daemon carry.
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


def atomic_write_json(target_path: Path, data: Any) -> None:
    """
    Public entry to this branch's single atomic JSON writer.

    Callers that own a bespoke document (one outside the config/data/log
    trio) write through here rather than growing a second writer. The
    torn-write measurement and the Windows sharing-violation retry in
    _atomic_write_json apply to every caller, so there is exactly one
    place where write durability is true or false for @skills.

    Args:
        target_path: The document to replace.
        data: What to write.

    Raises:
        OSError: The staged file could not be written or moved into place.
    """
    _atomic_write_json(target_path, data)


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
            if module_name and not module_name.startswith("_"):
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
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            if validate_json_structure(data, json_type):
                return True
        except Exception:
            logger.warning(f"Corrupt JSON file, will recreate: {json_path}")

    template = _get_default(json_type, module_name)
    if template is None:
        return False

    try:
        # Atomic like every write here: this is the REGENERATE path, the one
        # that replaces a document other modules may be reading right now. A
        # torn read lands here and gets answered with a template, so a partial
        # write would turn a bad read into permanent data loss.
        _atomic_write_json(json_path, template)
        return True
    except Exception as e:
        logger.error(f"Failed to write JSON file: {json_path}: {e}")
        return False


def load_json(module_name: str, json_type: str) -> Optional[Any]:
    """Load JSON file, auto-create if missing."""
    if not ensure_json_exists(module_name, json_type):
        return None

    json_path = get_json_path(module_name, json_type)

    try:
        with open(json_path, "r", encoding="utf-8") as f:
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
        _atomic_write_json(json_path, data)
        return True
    except Exception as e:
        logger.error(f"Failed to save JSON for {module_name}/{json_type}: {e}")
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
    entry: Dict[str, Any] = {"timestamp": datetime.now().isoformat(), "operation": operation}

    if data:
        entry["data"] = data

    log.append(entry)

    # Rotate if exceeds max
    if len(log) > max_entries:
        log = log[-max_entries:]

    return save_json(module_name, "log", log)
