# =================== AIPass ====================
# Name: json_handler.py
# Description: Auto-Creating JSON Handler
# Version: 1.1.0
# Created: 2026-03-05
# Modified: 2026-03-17
# =============================================

import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional
import inspect

from aipass.prax import logger

_BRANCH_ROOT = Path(__file__).resolve().parents[3]  # json/ -> handlers/ -> apps/ -> {branch}/
_BRANCH_NAME = _BRANCH_ROOT.name
JSON_DIR = _BRANCH_ROOT / f"{_BRANCH_NAME}_json"


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

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(template, f, indent=2, ensure_ascii=False)
    return True


def load_json(module_name: str, json_type: str) -> Optional[Any]:
    """Load JSON file, auto-create if missing"""
    if not ensure_json_exists(module_name, json_type):
        return None

    json_path = get_json_path(module_name, json_type)

    with open(json_path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(module_name: str, json_type: str, data: Any) -> bool:
    """Save JSON file"""
    json_path = get_json_path(module_name, json_type)

    if not validate_json_structure(data, json_type):
        raise ValueError(f"Invalid structure for {json_type} JSON")

    if json_type == "data" and isinstance(data, dict):
        data["last_updated"] = datetime.now().date().isoformat()

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
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
