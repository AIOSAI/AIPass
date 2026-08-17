# =================== AIPass ====================
# Name: json_handler.py
# Description: Auto-Creating JSON Handler
# Version: 1.2.0
# Created: 2026-03-05
# Modified: 2026-08-16
# =============================================

import json
import os
import sys
import tempfile
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional

from aipass.prax import logger

_BRANCH_ROOT = Path(__file__).resolve().parents[3]  # json/ -> handlers/ -> apps/ -> {branch}/
_BRANCH_NAME = _BRANCH_ROOT.name
JSON_DIR = _BRANCH_ROOT / f"{_BRANCH_NAME}_json"


def _atomic_write_json(target_path: Path, data: Any) -> None:
    """
    Write a JSON document so that a reader sees the old one or the new one.

    Args:
        target_path: The document to replace.
        data: What to write.

    Raises:
        OSError: The temp file could not be written or moved into place.

    Note:
        Opening the target with "w" truncates it BEFORE the new content is
        written, so every concurrent reader in that window gets an empty or
        partial file - and ensure_json_exists() answers an unreadable file by
        regenerating a blank template over it, which turns a race into data
        loss. Measured on the unfixed handler: 842 of 1075 concurrent reads
        came back unusable (454 empty, 388 unparseable). os.replace is atomic
        on POSIX and on Windows, so the window does not exist. The staged file
        is a SIBLING of the target - os.replace is only atomic within one
        filesystem. Mirrors the helper @api, @cli, @commons, @daemon, @skills
        and @hooks carry.
    """
    descriptor, temporary = tempfile.mkstemp(dir=str(target_path.parent), prefix=target_path.stem, suffix=".tmp")
    succeeded = False
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(data, stream, indent=2, ensure_ascii=False)
        os.replace(temporary, str(target_path))
        succeeded = True
    finally:
        if not succeeded and Path(temporary).exists():
            # A failed write must not leave a partial document in the directory
            # this handler itself globs and reads.
            os.unlink(temporary)


def _get_caller_module_name() -> str:
    """
    Auto-detect calling module name from call stack

    Returns:
        Module name (e.g., "imports_standard" from imports_standard.py)
    """

    # sys._getframe is O(1); inspect.stack() reads source for every frame and
    # at one call per checker per file it froze fresh audits (~5k calls/branch).
    try:
        caller_frame = sys._getframe(2)
    except ValueError as e:
        logger.info("[json_handler] Caller frame unavailable: %s", e)
        return "unknown"
    module_name = Path(caller_frame.f_code.co_filename).stem

    # Validate module name
    if module_name and not module_name.startswith("_"):
        return module_name

    # Fallback
    return "unknown"


def _create_default(json_type: str, module_name: str) -> Any:
    """Create default JSON structure for a given type."""
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
    return JSON_DIR / filename


def ensure_json_exists(module_name: str, json_type: str) -> bool:
    """Ensure JSON file exists, create from template if missing"""
    JSON_DIR.mkdir(parents=True, exist_ok=True)

    json_path = get_json_path(module_name, json_type)

    if json_path.exists():
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            if validate_json_structure(data, json_type):
                return True
            # If corrupted, fall through to regenerate
        except Exception:
            logger.info("JSON file unreadable or corrupted, regenerating: %s", json_path)

    template = _create_default(json_type, module_name)

    _atomic_write_json(json_path, template)
    return True


def load_json(module_name: str, json_type: str) -> Optional[Any]:
    """Load JSON file, auto-create if missing.

    Guards against an empty/whitespace file — e.g. a concurrent writer caught
    mid-truncate in the TOCTOU window between ensure_json_exists() and this
    read. Rather than raising JSONDecodeError, fall back to the type's default
    template so callers always get a valid structure. A non-empty but malformed
    file still raises (fail honestly — that is real corruption, not a race).
    """
    if not ensure_json_exists(module_name, json_type):
        return None

    json_path = get_json_path(module_name, json_type)

    with open(json_path, "r", encoding="utf-8") as f:
        content = f.read()

    if not content.strip():
        logger.warning("JSON file empty, using default template: %s", json_path)
        return _create_default(json_type, module_name)

    return json.loads(content)


def save_json(module_name: str, json_type: str, data: Any) -> bool:
    """Save JSON file"""
    json_path = get_json_path(module_name, json_type)

    if not validate_json_structure(data, json_type):
        raise ValueError(f"Invalid structure for {json_type} JSON")

    if json_type == "data" and isinstance(data, dict):
        data["last_updated"] = datetime.now().date().isoformat()

    _atomic_write_json(json_path, data)
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
    """Increment a counter in data JSON.

    Note: Public API — used in self-test block below. Not called in production code path.
    """
    ensure_module_jsons(module_name)

    data = load_json(module_name, "data")
    if data is None:
        return False

    if counter_name not in data:
        data[counter_name] = 0

    data[counter_name] += amount

    return save_json(module_name, "data", data)


def update_data_metrics(module_name: str, **metrics) -> bool:
    """Update data metrics.

    Note: Public API — used in self-test block below. Not called in production code path.
    """
    ensure_module_jsons(module_name)

    data = load_json(module_name, "data")
    if data is None:
        return False

    for key, value in metrics.items():
        data[key] = value

    return save_json(module_name, "data", data)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

    from rich.console import Console
    from rich.panel import Panel

    console = Console()

    console.print()
    console.print(Panel.fit("[bold cyan]JSON HANDLER - Working Implementation[/bold cyan]", border_style="bright_blue"))
    console.print()
    console.print(f"[yellow]TESTING:[/yellow] Creating {_BRANCH_NAME} JSONs...")
    console.print(f"[dim]JSON_DIR: {JSON_DIR}[/dim]")

    # Test auto-creation
    log_operation("test_operation", {"test": "data"}, _BRANCH_NAME)
    increment_counter(_BRANCH_NAME, "test_counter", 1)
    update_data_metrics(_BRANCH_NAME, test_metric="working")

    console.print()
    console.print(f"[green]Check {JSON_DIR.relative_to(_BRANCH_ROOT)}/ for created files:[/green]")
    console.print(f"  [dim]•[/dim] {_BRANCH_NAME}_config.json")
    console.print(f"  [dim]•[/dim] {_BRANCH_NAME}_data.json")
    console.print(f"  [dim]•[/dim] {_BRANCH_NAME}_log.json")
    console.print()
