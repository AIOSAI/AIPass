# =================== AIPass ====================
# Name: json_handler.py
# Description: Auto-Creating JSON Handler
# Version: 2.2.0
# Created: 2025-11-21
# Modified: 2026-08-18
# =============================================

"""
JSON Handler - Auto-Creating & Self-Healing JSON System

Handles default JSON files (config, data, log) for flow modules.
Never manually create JSONs - they build themselves.
"""

# ruff: noqa: E402
import json
import sys
import os

if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8", errors="replace")

import tempfile
import time
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional

from aipass.prax.apps.modules.logger import system_logger as logger

# Infrastructure
from aipass.flow.apps.handlers.repo_root import module_file

_PKG_ROOT = module_file(__file__).parents[4]

# Constants
FLOW_ROOT = _PKG_ROOT / "flow"
FLOW_JSON_DIR = FLOW_ROOT / "flow_json"


def _get_caller_module_name() -> str:
    """
    Auto-detect calling module name from call stack

    Returns:
        Module name (e.g., "create_plan" from create_plan.py)

    Reads one frame with ``sys._getframe`` rather than building the whole stack
    with ``inspect.stack()``. MEASURED on the Windows CI gate 2026-08-31
    (@memory's finding, relayed by @devpulse and reproduced here): building a
    ``FrameInfo`` per frame calls ``getsourcefile() -> getmodule() ->
    os.path.realpath()``, and ``ntpath.realpath`` reads ``os.getcwd()``
    unconditionally on its first lines. That call site inside ``getmodule`` is
    not wrapped in a try. On POSIX the equivalent raise happens earlier, inside
    ``getabsfile()``, where inspect catches it — which is why a call on flow's
    every-write audit path carried this invisibly for as long as it existed.

    No import probe reaches this line: ``log_operation`` is called at RUNTIME,
    and the stack it walks is the CALLER'S. The shape that convicts it is a
    ``<string>`` frame — a routed subprocess, a hook, anything exec'd — which is
    exactly what drone's router produces when it invokes flow.

    A frame's ``f_code.co_filename`` is already a string in memory; reading it
    touches no filesystem at all.
    """
    try:
        # Skip frames: [0]=this function, [1]=log_operation, [2]=actual caller
        caller_frame = sys._getframe(2)
        caller_path = Path(caller_frame.f_code.co_filename)
        module_name = caller_path.stem

        # Validate module name
        if module_name and not module_name.startswith("_"):
            return module_name

        # Fallback
        return "unknown"
    except ValueError:
        # sys._getframe raises when the stack is shallower than the requested
        # depth — a direct call with no caller above log_operation.
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
    """Write JSON data atomically via temp file + rename.

    Prevents corruption from concurrent processes writing the same file. The
    rename goes through _replace_with_retry: on Windows a reader holding the
    target open turns the move into a PermissionError, and one stuck move
    starved a whole CI run (2026-08-18). Bounded, then it raises honestly.
    """
    fd, tmp_path = tempfile.mkstemp(dir=str(target_path.parent), suffix=".tmp", prefix=target_path.stem)
    succeeded = False
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        _replace_with_retry(tmp_path, str(target_path))
        succeeded = True
    finally:
        if not succeeded and Path(tmp_path).exists():
            logger.warning("[json_handler] Cleaning up temp file after write failure: %s", tmp_path)
            os.unlink(tmp_path)


def get_json_path(module_name: str, json_type: str) -> Path:
    """Get path for module JSON file"""
    filename = f"{module_name}_{json_type}.json"
    return FLOW_JSON_DIR / filename


def ensure_json_exists(module_name: str, json_type: str) -> bool:
    """Ensure JSON file exists, create from template if missing"""
    FLOW_JSON_DIR.mkdir(parents=True, exist_ok=True)

    json_path = get_json_path(module_name, json_type)

    if json_path.exists():
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            if validate_json_structure(data, json_type):
                return True
        except Exception as exc:
            # File exists but is corrupted - will regenerate below
            logger.warning(
                "[json_handler] Corrupted JSON file for '%s/%s', regenerating: %s", module_name, json_type, exc
            )

    template = _default_template(json_type, module_name)
    if template is None:
        return False

    try:
        _atomic_write_json(json_path, template)
        return True
    except Exception as exc:
        logger.error("[json_handler] Failed to write JSON template for '%s/%s': %s", module_name, json_type, exc)
        return False


def load_json(module_name: str, json_type: str) -> Optional[Any]:
    """Load JSON file, auto-create if missing"""
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
    """Save JSON file"""
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
    from rich.console import Console
    from rich.panel import Panel

    console = Console()

    console.print()
    console.print(Panel.fit("[bold cyan]JSON HANDLER - Working Implementation[/bold cyan]", border_style="bright_blue"))
    console.print()
    console.print("[yellow]TESTING:[/yellow] Creating FLOW JSONs...")

    # Test auto-creation
    log_operation("test_operation", {"test": "data"}, "flow")
    increment_counter("flow", "test_counter", 1)
    update_data_metrics("flow", test_metric="working")

    console.print()
    console.print("[green]Check flow/flow_json/ for created files:[/green]")
    console.print("  [dim]•[/dim] flow_config.json")
    console.print("  [dim]•[/dim] flow_data.json")
    console.print("  [dim]•[/dim] flow_log.json")
    console.print()
