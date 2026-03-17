# =================== AIPass ====================
# Name: json_handler.py
# Description: JSON file read/write and operation logging for spawn
# Version: 1.1.0
# Created: 2026-03-07
# Modified: 2026-03-17
# =============================================

"""JSON handler for spawn module.

Provides JSON I/O utilities and operation logging for the three-JSON system.
"""

import inspect
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

_SPAWN_ROOT = Path(__file__).resolve().parents[3]
_JSON_DIR = _SPAWN_ROOT / "spawn_json"


def read_json(file_path: Path) -> Optional[dict]:
    """Read and parse a JSON file."""
    try:
        return json.loads(file_path.read_text())
    except (json.JSONDecodeError, FileNotFoundError):
        return None


def write_json(file_path: Path, data: Any, indent: int = 2) -> bool:
    """Write data to a JSON file."""
    try:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(json.dumps(data, indent=indent) + "\n")
        return True
    except OSError:
        return False


def _get_caller_module_name() -> str:
    """Auto-detect calling module name from call stack."""
    stack = inspect.stack()
    if len(stack) > 2:
        caller_path = Path(stack[2].filename)
        module_name = caller_path.stem
        if module_name and not module_name.startswith('_'):
            return module_name
    return "unknown"


def log_operation(operation: str, data: Dict[str, Any] | None = None, module_name: str | None = None) -> bool:
    """Add entry to module operation log with automatic rotation.

    Auto-detects calling module if module_name not provided.

    Args:
        operation: Operation name to log
        data: Optional data dict
        module_name: Optional module name (auto-detected if not provided)

    Returns:
        True if successful, False otherwise
    """
    if module_name is None:
        module_name = _get_caller_module_name()

    _JSON_DIR.mkdir(parents=True, exist_ok=True)
    log_path = _JSON_DIR / f"{module_name}_log.json"

    log: list = []
    if log_path.exists():
        try:
            log = json.loads(log_path.read_text())
        except (json.JSONDecodeError, OSError):
            log = []

    entry: Dict[str, Any] = {
        "timestamp": datetime.now().isoformat(),
        "operation": operation,
    }
    if data:
        entry["data"] = data

    log.append(entry)

    # Rotate at 100 entries
    if len(log) > 100:
        log = log[-100:]

    try:
        log_path.write_text(json.dumps(log, indent=2) + "\n")
        return True
    except OSError:
        return False
