# =================== AIPass ====================
# Name: json_handler.py
# Description: JSON Auto-Creating Handler
# Version: 1.2.0
# Created: 2025-11-21
# Modified: 2026-01-29
# =============================================

"""
JSON handler for DAEMON branch.

Provides auto-creating JSON file management with templates.
"""

import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional
import inspect

from aipass.prax import logger

# Constants
_DAEMON_ROOT = Path(__file__).resolve().parents[3]  # src/aipass/daemon/
JSON_DIR = _DAEMON_ROOT / "daemon_json"
MAX_LOG_ENTRIES = 100  # Default FIFO limit for log_operation (overridable via config)


def _get_caller_module_name() -> str:
    """
    Auto-detect calling module name from call stack.

    Returns:
        Module name (e.g., "imports_standard" from imports_standard.py)
    """
    stack = inspect.stack()
    if len(stack) > 2:
        caller_frame = stack[2]
        caller_path = Path(caller_frame.filename)
        module_name = caller_path.stem

        if module_name and not module_name.startswith('_'):
            return module_name

    return "unknown"


def _default_template(json_type: str, module_name: str) -> Any:
    """Return inline default structure for a JSON type."""
    current_date = datetime.now().date().isoformat()
    if json_type == "config":
        return {
            "module_name": module_name,
            "version": "1.0.0",
            "timestamp": current_date,
            "config": {"auto_save": True, "enabled": True},
        }
    elif json_type == "data":
        return {
            "module_name": module_name,
            "created": current_date,
            "last_updated": current_date,
            "operations_total": 0,
        }
    elif json_type == "log":
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


def get_json_path(module_name: str, json_type: str) -> Path:
    """Get path for module JSON file."""
    filename = f"{module_name}_{json_type}.json"
    return JSON_DIR / filename


def ensure_json_exists(module_name: str, json_type: str) -> bool:
    """Ensure JSON file exists, create from template if missing."""
    JSON_DIR.mkdir(parents=True, exist_ok=True)

    json_path = get_json_path(module_name, json_type)

    if json_path.exists():
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            if validate_json_structure(data, json_type):
                return True
        except json.JSONDecodeError as e:
            logger.warning("[json_handler] Corrupted JSON file %s, regenerating: %s", json_path.name, e)
        except OSError as e:
            logger.warning("[json_handler] Unreadable JSON file %s, regenerating: %s", json_path.name, e)

    template = _default_template(json_type, module_name)

    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(template, f, indent=2, ensure_ascii=False)
    return True


def load_json(module_name: str, json_type: str) -> Optional[Any]:
    """Load JSON file, auto-create if missing."""
    if not ensure_json_exists(module_name, json_type):
        return None

    json_path = get_json_path(module_name, json_type)

    with open(json_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_json(module_name: str, json_type: str, data: Any) -> bool:
    """Save JSON file."""
    json_path = get_json_path(module_name, json_type)

    if not validate_json_structure(data, json_type):
        raise ValueError(f"Invalid structure for {json_type} JSON")

    if json_type == "data" and isinstance(data, dict):
        data["last_updated"] = datetime.now().date().isoformat()

    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return True


def ensure_module_jsons(module_name: str) -> bool:
    """Ensure all 3 JSON files exist for a module."""
    ensure_json_exists(module_name, "config")
    ensure_json_exists(module_name, "data")
    ensure_json_exists(module_name, "log")
    return True


def log_operation(operation: str, data: Optional[Dict[str, Any]] = None, module_name: Optional[str] = None) -> bool:
    """
    Add entry to module log with automatic rotation.

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
    max_entries = MAX_LOG_ENTRIES
    if config and "config" in config:
        max_entries = config["config"].get("max_log_entries", MAX_LOG_ENTRIES)

    log: List[Dict[str, Any]] = load_json(module_name, "log") or []

    entry: Dict[str, Any] = {
        "timestamp": datetime.now().isoformat(),
        "operation": operation
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
    console.print("[yellow]TESTING:[/yellow] Creating daemon JSONs...")

    log_operation("test_operation", {"test": "data"}, "daemon")
    increment_counter("daemon", "test_counter", 1)
    update_data_metrics("daemon", test_metric="working")

    console.print()
    console.print(f"[green]Check {JSON_DIR}/ for created files:[/green]")
    console.print("  [dim]-[/dim] daemon_config.json")
    console.print("  [dim]-[/dim] daemon_data.json")
    console.print("  [dim]-[/dim] daemon_log.json")
    console.print()
