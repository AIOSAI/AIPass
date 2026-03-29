# =================== AIPass ====================
# Name: json_handler.py
# Description: JSON Auto-Creating Handler
# Version: 3.1.0
# Created: 2025-11-22
# Modified: 2026-03-09
# =============================================

import json
import os
import inspect
import tempfile
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional

from aipass.prax import logger

# Constants
_BACKUP_ROOT = Path(__file__).resolve().parents[3]  # src/aipass/backup/
BACKUP_JSON_DIR = _BACKUP_ROOT / "backup_json"


def _atomic_json_write(file_path: Path, data: Any) -> None:
    """Write JSON atomically via temp file + rename to prevent corruption."""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(suffix='.tmp', dir=str(file_path.parent))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, str(file_path))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError as cleanup_err:
            logger.warning(f"[json_handler] Failed to clean up temp file: {cleanup_err}")
        raise


def _get_caller_module_name() -> str:
    """
    Auto-detect calling module name from call stack

    Returns:
        Module name (e.g., "backup_core" from backup_core.py)
    """
    stack = inspect.stack()
    # Skip frames: [0]=this function, [1]=log_operation, [2]=actual caller
    if len(stack) > 2:
        caller_frame = stack[2]
        caller_path = Path(caller_frame.filename)
        module_name = caller_path.stem

        # Validate module name
        if module_name and not module_name.startswith('_'):
            return module_name

    # Fallback
    return "unknown"


def _get_default_template(json_type: str, module_name: str) -> Any:
    """Return inline default structure for a JSON type"""
    today = datetime.now().date().isoformat()
    if json_type == "config":
        return {
            "module_name": module_name,
            "version": "1.0.0",
            "config": {
                "enabled": True,
                "max_log_entries": 100
            }
        }
    elif json_type == "data":
        return {
            "created": today,
            "last_updated": today
        }
    elif json_type == "log":
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
    return BACKUP_JSON_DIR / filename


def ensure_json_exists(module_name: str, json_type: str) -> bool:
    """Ensure JSON file exists, create from template if missing"""
    BACKUP_JSON_DIR.mkdir(parents=True, exist_ok=True)

    json_path = get_json_path(module_name, json_type)

    if json_path.exists():
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            if validate_json_structure(data, json_type):
                return True
            # If corrupted, fall through to regenerate
        except Exception as e:
            logger.warning(f"[json_handler] Failed to read {json_path}, regenerating: {e}")

    template = _get_default_template(json_type, module_name)

    _atomic_json_write(json_path, template)
    return True


def load_json(module_name: str, json_type: str) -> Optional[Any]:
    """Load JSON file, auto-create if missing. Self-heals corrupt files."""
    if not ensure_json_exists(module_name, json_type):
        return None

    json_path = get_json_path(module_name, json_type)

    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"[json_handler] Corrupt JSON at {json_path}, regenerating: {e}")
        template = _get_default_template(json_type, module_name)
        try:
            _atomic_json_write(json_path, template)
        except Exception as write_err:
            logger.error(f"[json_handler] Failed to regenerate {json_path}: {write_err}")
        return template


def save_json(module_name: str, json_type: str, data: Any) -> bool:
    """Save JSON file atomically."""
    json_path = get_json_path(module_name, json_type)

    if not validate_json_structure(data, json_type):
        raise ValueError(f"Invalid structure for {json_type} JSON")

    if json_type == "data" and isinstance(data, dict):
        data["last_updated"] = datetime.now().date().isoformat()

    _atomic_json_write(json_path, data)
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
    entry = {
        "timestamp": datetime.now().isoformat(),
        "operation": operation
    }

    if data:
        entry["data"] = data  # type: ignore[assignment]

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
    from rich.console import Console
    from rich.panel import Panel

    console = Console()

    console.print()
    console.print(Panel.fit(
        "[bold cyan]JSON HANDLER - Working Implementation[/bold cyan]",
        border_style="bright_blue"
    ))
    console.print()
    console.print("[yellow]TESTING:[/yellow] Creating backup JSONs...")

    # Test auto-creation
    log_operation("test_operation", {"test": "data"}, "backup_system")
    increment_counter("backup_system", "test_counter", 1)
    update_data_metrics("backup_system", test_metric="working")

    console.print()
    console.print("[green]Check backup_json/ directory for created files:[/green]")
    console.print("  [dim]-[/dim] backup_system_config.json")
    console.print("  [dim]-[/dim] backup_system_data.json")
    console.print("  [dim]-[/dim] backup_system_log.json")
    console.print()
