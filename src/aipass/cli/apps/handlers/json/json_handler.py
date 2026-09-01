# =================== AIPass ====================
# Name: json_handler.py
# Description: JSON auto-creating handler — manages CLI JSON files with templates and rotation
# Version: 1.3.0
# Created: 2025-11-13
# Modified: 2026-08-18
# =============================================

"""JSON Auto-Creating Handler - manages CLI JSON files with templates and auto-rotation."""

import json
import os
import tempfile
import time
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional
import sys

# Constants — resolved via __file__ (portable across any machine).
# The resolve is guarded: it runs at IMPORT time, and Path.resolve() routes
# through ntpath.realpath on Windows, which reads os.getcwd() unconditionally.
# A process whose cwd was deleted cannot import this module otherwise, and most
# of the fleet imports it. __file__ is already absolute; resolve only normalises.
try:
    _BRANCH_ROOT = Path(__file__).resolve().parents[3]  # json/ -> handlers/ -> apps/ -> cli/
except OSError:
    _BRANCH_ROOT = Path(__file__).parents[3]
_BRANCH_NAME = _BRANCH_ROOT.name
JSON_DIR = _BRANCH_ROOT / f"{_BRANCH_NAME}_json"


def _get_caller_module_name() -> str:
    """
    Auto-detect calling module name from call stack

    Returns:
        Module name (e.g., "imports_standard" from imports_standard.py)

    Uses sys._getframe rather than inspect.stack() for the same reason the
    handler guard does: inspect.stack() builds a FrameInfo per frame, which
    reaches os.path.realpath() through getmodule(), and ntpath's realpath reads
    os.getcwd() unconditionally. This one is CALL-time rather than import-time,
    so it never blocked an import — but log_operation() is called from across the
    fleet, and a branch logging an operation in a dead-cwd world would have died
    here. Reading f_code.co_filename touches the filesystem not at all.
    """
    # Skip frames: [0]=this function, [1]=log_operation, [2]=actual caller
    try:
        caller_frame = sys._getframe(2)
    except ValueError:
        # Stack shallower than 3 frames — the old len(stack) > 2 guard.
        return "unknown"

    module_name = Path(caller_frame.f_code.co_filename).stem

    # Validate module name
    if module_name and not module_name.startswith("_"):
        return module_name

    # Fallback
    return "unknown"


def _create_default(json_type: str, module_name: str) -> Any:
    """Create default JSON structure from inline code defaults."""
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
    elif json_type == "data":
        return {
            "module_name": module_name,
            "created": today,
            "last_updated": today,
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
    Write a JSON document so that a reader sees the old one or the new one.

    Args:
        target_path: The document to replace.
        data: What to write.

    Raises:
        OSError: The temp file could not be written or moved into place.

    Note:
        Opening the target with "w" truncates it BEFORE the new content is
        written, so every concurrent reader in that window gets an empty file —
        and ensure_json_exists answers an unreadable file by regenerating an
        empty template over it, which turns a race into data loss. Measured on
        this handler before the fix: 550 of 949 concurrent reads came back
        truncated (58%). os.replace is atomic on POSIX and on Windows, so the
        window does not exist. On Windows it can still raise PermissionError while a
        reader holds the target open, so the move goes through
        _replace_with_retry — bounded, then raises (proven by the Windows CI
        hang of 2026-08-18). Mirrors the helper @api, @flow,
        @drone and @prax already carry.

        No logging here, deliberately: this handler cannot import prax
        (circular — prax depends on cli), so a failed write RAISES rather than
        being swallowed. Callers log.
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
            # this handler itself globs and reads.
            os.unlink(temporary)


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
            pass

    template = _create_default(json_type, module_name)

    _atomic_write_json(json_path, template)
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


if __name__ == "__main__":
    import sys

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
    console.print("[yellow]TESTING:[/yellow] Creating CLI JSONs...")

    # Test auto-creation
    log_operation("test_operation", {"test": "data"}, "cli")

    console.print()
    console.print(f"[green]Check {JSON_DIR}/ for created files:[/green]")
    console.print("  [dim]•[/dim] cli_config.json")
    console.print("  [dim]•[/dim] cli_data.json")
    console.print("  [dim]•[/dim] cli_log.json")
    console.print()
