# =================== AIPass ====================
# Name: json_handler.py
# Description: JSON Handler
# Version: 1.1.0
# Created: 2025-11-15
# Modified: 2026-09-02
# =============================================

"""
JSON Handler - Auto-Creating & Self-Healing JSON System

Handles default JSON files (config, data, log) for AI_MAIL modules.
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
        # Atomic for the same reason save_json is, and arguably more urgently:
        # this is the SELF-HEALING path, so it fires exactly when the document
        # is already suspect. A truncating write here replaces a damaged file
        # with a half-written one and loses the evidence with it. Beyond
        # FPLAN-0481's brief (which named save_json) — same file, same defect,
        # found because the source guard below refuses the SHAPE, not one line.
        _atomic_write_json(json_path, template)
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


# Bounded retry for the rename. Same body and same constants as the other
# fifteen copies in the fleet (drone's handler is the reference) — seedgo's
# durability contract asserts all of them are assertion-identical, so a local
# "improvement" here would show up as fleet divergence, not as a better handler.
_REPLACE_ATTEMPTS = 40
_REPLACE_BACKOFF_SECONDS = 0.005


def _replace_with_retry(source: str, destination: str) -> None:
    """os.replace that tolerates Windows sharing violations, bounded.

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


def _atomic_write_json(path: Path, data: Any) -> None:
    """Stage beside the target, fsync, then swap it into place.

    THIS FILE IS THE CITIZEN MAIL STORE, which is why it is worth the syscalls.
    Until 2026-09-02 the write was ``open(path, "w")`` + ``json.dump`` — the
    truncation happens the moment the file is opened, so any failure during the
    dump left the LIVE document destroyed and unparseable while ``save_json``
    returned False. The caller heard "did not save"; the truth was "your
    previous document is gone too". Reproduced on the real handler: a 101-byte
    inbox became 83 bytes of unparseable text with the stored message lost, and
    seedgo's contract observed a concurrent reader seeing an EMPTY mailbox six
    times in one four-writer run (FPLAN-0481).

    Staging removes the window entirely: readers see the old document until
    ``os.replace`` swaps the new one in whole, and a failed write destroys only
    the temp file. The fsync is here rather than in drone's reference because
    ``os.replace`` orders the rename, not the DATA — without it a crash after
    the swap can leave a renamed-but-empty file, which is the same lost mailbox
    reached by a different route.

    Raises:
        Anything the staging, dump or replace raises, after removing the temp.
        Never returns having failed — a caller must not read "wrote nothing" as
        success.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp", prefix=".json_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
            fh.flush()
            os.fsync(fh.fileno())
        _replace_with_retry(tmp_path, str(path))
    except BaseException as exc:
        logger.warning("[json] atomic write failed for %s: %s", path, exc)
        # BaseException, so a KeyboardInterrupt mid-write does not strand the
        # temp beside the live document.
        try:
            os.unlink(tmp_path)
        except OSError as cleanup_exc:
            logger.warning("[json] temp cleanup failed for %s: %s", tmp_path, cleanup_exc)
        raise


def save_json(module_name: str, json_type: str, data: Any) -> bool:
    """Save JSON file.

    The write is atomic (see :func:`_atomic_write_json`). The public contract is
    unchanged: True only when the document landed, False otherwise. An exhausted
    replace retry RAISES out of the helper — matching the fleet's helper
    contract, which seedgo pins directly — and is caught here, so this function
    still answers False rather than propagating. A write that did not land can
    never return True.
    """
    json_path = get_json_path(module_name, json_type)

    if not validate_json_structure(data, json_type):
        return False

    if json_type == "data" and isinstance(data, dict):
        data["last_updated"] = datetime.now().date().isoformat()

    try:
        _atomic_write_json(Path(json_path), data)
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
