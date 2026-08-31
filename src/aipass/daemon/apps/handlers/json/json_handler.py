# =================== AIPass ====================
# Name: json_handler.py
# Description: JSON Auto-Creating Handler
# Version: 1.6.0
# Created: 2025-11-21
# Modified: 2026-08-31
# =============================================

"""
JSON handler for DAEMON branch.

Provides auto-creating JSON file management with templates.
"""

import json
import os
import sys
import tempfile
import time
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional

if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8", errors="replace")

from aipass.prax import logger
from aipass.daemon.apps.handlers.module_root import module_file

# Constants
_DAEMON_ROOT = module_file(__file__).parents[3]  # src/aipass/daemon/

# The real directory, kept under its own name so the resolver below can tell an
# explicit test patch from the untouched default. Recomputed on a module
# reload exactly like JSON_DIR is, which is what makes the comparison survive
# one (see _current_json_dir).
_IMPORT_TIME_JSON_DIR = _DAEMON_ROOT / "daemon_json"

# Still a module attribute: ~20 existing tests redirect by monkeypatching this,
# and the fleet contract (@prax, mail 01fb09c6) keeps that door open on purpose.
JSON_DIR = _IMPORT_TIME_JSON_DIR

# The fleet-wide test redirect, @trigger's spelling. NOT read into a constant
# here: daemon's own conftest sets it at module scope, yet something imports
# this handler first, so a value captured at import time resolves to the live
# tree anyway. A seam that has to win an import race is not a seam - so the
# read happens inside _current_json_dir(), at call time, every call.
_TEST_LOG_DIR_ENV = "AIPASS_TEST_LOG_DIR"

MAX_LOG_ENTRIES = 100  # Default FIFO limit for log_operation (overridable via config)


def _current_json_dir() -> Path:
    """Resolve the JSON directory NOW - never at import.

    Precedence, each step pinned in test_json_log_dir_seam.py:
      1. An explicit monkeypatch of JSON_DIR wins outright, detected by
         VALUE rather than by identity. @prax's recipe compares by identity;
         that breaks here, and the failure is not theoretical - test_contracts
         calls importlib.reload(json_handler) while its autouse monkeypatch is
         active, so the patch is undone by writing the PRE-reload object back
         onto the POST-reload module. JSON_DIR is then equal to the default and
         not identical to it, every later call reads "explicitly patched", and
         the redirect silently stops working for the rest of the session. The
         cost of value comparison is one lost distinction: a test that patches
         JSON_DIR to the real directory on purpose is indistinguishable from
         one that never patched at all. Pinned by name below.
      2. AIPASS_TEST_LOG_DIR redirects, under <root>/daemon/daemon_json/ so a
         root shared with other branches never collides.
      3. Otherwise the real directory.

    An EMPTY or blank value is absence, not a redirect - Path("") / "x" is
    relative and would scatter daemon state wherever the process happens to be
    standing.
    """
    patched = Path(JSON_DIR)  # coerced: some callers patch it with a str
    if patched != _IMPORT_TIME_JSON_DIR:
        return patched

    test_root = os.environ.get(_TEST_LOG_DIR_ENV)
    if test_root and test_root.strip():
        return Path(test_root.strip()) / "daemon" / "daemon_json"

    return _IMPORT_TIME_JSON_DIR


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
        file. In this handler that is not merely a bad read: ensure_json_exists
        answers an unreadable document by writing a fresh template over it, so
        a torn read becomes permanent data loss. As the scheduler, @daemon
        reads configs while branches write them - measured on the unfixed
        handler with 2 writers and 2 readers, 12,117 of 13,103 reads (92.5%)
        came back empty or unparseable. os.replace is atomic on POSIX and
        Windows, so the window does not exist. On Windows it can still raise PermissionError while a
        reader holds the target open, so the move goes through
        _replace_with_retry — bounded, then raises (proven by the Windows CI
        hang of 2026-08-18). The staged file MUST live in the
        target's own directory or the rename becomes a cross-device copy.
        Mirrors the helper @api, @cli, @commons, @flow, @drone and @prax carry.
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


def _get_caller_module_name() -> str:
    """
    Auto-detect calling module name from call stack.

    Walks past internal frames ([0] = this function, [1] = public function,
    [2] = actual caller) and returns the stem of the caller's filename.

    Reads the frame directly rather than through inspect.stack(). MEASURED
    2026-08-31 in the hostile world that emulates a Windows box with no working
    directory: inspect.stack() builds a FrameInfo per frame, and for any frame
    whose filename is a PSEUDO-file - <string>, which every interpreter -c
    invocation and every exec'd hook puts on the stack - it reaches getmodule(),
    whose os.path.realpath sits outside that function's every try. The whole
    call then raises FileNotFoundError, so log_operation - the audit line daemon
    writes on essentially every scheduler tick - took the caller down from inside
    its own logging. On POSIX the equivalent raise happens earlier, where inspect
    catches it, which is why this stood on Linux for as long as it existed.

    FrameInfo.filename is getsourcefile(frame) or getfile(frame), and both fall
    back to co_filename for the frames this walk looks at, so the stem is the
    same string by a route that touches no filesystem at all.

    Returns:
        Module name (e.g., "imports_standard" from imports_standard.py)
    """
    # Skip frames: [0]=this function, [1]=public wrapper, [2]=actual caller
    try:
        caller_frame = sys._getframe(2)
    except ValueError:
        # Fewer than three frames - the old form's `len(stack) > 2` guard.
        return "unknown"

    module_name = Path(caller_frame.f_code.co_filename).stem
    if module_name and not module_name.startswith("_"):
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
    return _current_json_dir() / filename


def ensure_json_exists(module_name: str, json_type: str) -> bool:
    """Ensure JSON file exists, create from template if missing."""
    _current_json_dir().mkdir(parents=True, exist_ok=True)

    json_path = get_json_path(module_name, json_type)

    if json_path.exists():
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            if validate_json_structure(data, json_type):
                return True
        except json.JSONDecodeError as e:
            logger.warning("[json_handler] Corrupted JSON file %s, regenerating: %s", json_path.name, e)
        except OSError as e:
            logger.warning("[json_handler] Unreadable JSON file %s, regenerating: %s", json_path.name, e)

    template = _default_template(json_type, module_name)

    _atomic_write_json(json_path, template)
    return True


def load_json(module_name: str, json_type: str) -> Optional[Any]:
    """Load JSON file, auto-create if missing."""
    if not ensure_json_exists(module_name, json_type):
        return None

    json_path = get_json_path(module_name, json_type)

    with open(json_path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(module_name: str, json_type: str, data: Any) -> bool:
    """Save JSON file."""
    json_path = get_json_path(module_name, json_type)

    if not validate_json_structure(data, json_type):
        raise ValueError(f"Invalid structure for {json_type} JSON")

    if json_type == "data" and isinstance(data, dict):
        data["last_updated"] = datetime.now().date().isoformat()

    # save_json was the one writer that never created its own directory - it
    # only ever worked because the live daemon_json/ is committed and therefore
    # always present. The moment the directory is resolved (a redirected test
    # root, a fresh checkout), _atomic_write_json's tempfile raises
    # FileNotFoundError before a single byte is written. Found by the redirect,
    # not by a review.
    json_path.parent.mkdir(parents=True, exist_ok=True)

    _atomic_write_json(json_path, data)
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

    entry: Dict[str, Any] = {"timestamp": datetime.now().isoformat(), "operation": operation}

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
    console.print(Panel.fit("[bold cyan]JSON HANDLER - Working Implementation[/bold cyan]", border_style="bright_blue"))
    console.print()
    console.print("[yellow]TESTING:[/yellow] Creating daemon JSONs...")

    log_operation("test_operation", {"test": "data"}, "daemon")
    increment_counter("daemon", "test_counter", 1)
    update_data_metrics("daemon", test_metric="working")

    console.print()
    console.print(f"[green]Check {_current_json_dir()}/ for created files:[/green]")
    console.print("  [dim]-[/dim] daemon_config.json")
    console.print("  [dim]-[/dim] daemon_data.json")
    console.print("  [dim]-[/dim] daemon_log.json")
    console.print()
