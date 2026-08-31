# =================== AIPass ====================
# Name: json_handler.py
# Description: Branch-local shim — delegates to aipass.aipass.shared.json_handler
# Version: 2.1.0
# Created: 2026-04-16
# Modified: 2026-08-31
# =============================================

"""Branch-local JSON handler — thin shim over the shared ``aipass.aipass.shared`` library.

All logic lives in ``aipass.aipass.shared.json_handler.JsonHandler``.
This module binds a ``JsonHandler`` instance to the aipass branch's
``aipass_json/`` directory and re-exports the public API as module-level
functions so existing callers (``json_handler.log_operation(...)``) keep working.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, Optional

from aipass.aipass.apps.handlers.module_root import module_file
from aipass.aipass.shared.json_handler import JsonHandler


def _get_caller_module_name() -> str:
    """Auto-detect calling module name from call stack.

    Walks the frame chain with ``sys._getframe`` rather than
    ``inspect.stack()``.  MEASURED 2026-08-31 (@canary's exposure report,
    @devpulse's round-4 follow-up): ``inspect.stack()`` builds a FrameInfo per
    frame, and for any frame whose filename is not on disk — ``<string>`` from
    a ``-c`` command-line source, a ``compile()``d source, the frozen
    importlib frames —
    ``getsourcefile()`` falls through to ``getmodule()``, whose module-scanning
    loop calls ``os.path.realpath`` OUTSIDE the ``try`` that wraps
    ``getabsfile``.  ``ntpath.realpath`` then reads ``os.getcwd()``
    unconditionally.

    On this hot path that made LOGGING TAKE DOWN THE CALLER IT LOGS FOR:
    ``log_operation`` resolves the module name BEFORE its own ``try``, so the
    raise escaped every handler below it.  A frame's ``co_filename`` is already
    a string in memory; reading it touches no filesystem.

    Returns:
        The calling module's filename stem, or ``"unknown"`` when the stack is
        too shallow or the name is private. Behaviour is unchanged from the
        ``inspect.stack()`` form — only the mechanism moved.
    """
    try:
        frame = sys._getframe(2)
    except ValueError:
        # Stack shallower than the caller-of-log_operation depth; the
        # inspect.stack() form spelled this as `len(stack) > 2`.
        return "unknown"
    module_name = Path(frame.f_code.co_filename).stem
    if module_name and not module_name.startswith("_"):
        return module_name
    return "unknown"


# module_file, not resolve(): this line runs at IMPORT, and on Windows
# resolve() reads the working directory (see handlers/module_root.py).
_PKG_ROOT = module_file(__file__).parents[4]

AIPASS_BRANCH_ROOT = _PKG_ROOT / "aipass"
AIPASS_JSON_DIR = AIPASS_BRANCH_ROOT / "aipass_json"


def _handler() -> JsonHandler:
    """Create a handler bound to the current AIPASS_JSON_DIR."""
    return JsonHandler(AIPASS_JSON_DIR)


def load_path(file_path: Path) -> Optional[dict]:
    """Load JSON from an arbitrary file path."""
    return JsonHandler.read_json(file_path)


def save_path(file_path: Path, data: Any, indent: int = 2) -> bool:
    """Write JSON data to an arbitrary file path atomically."""
    return JsonHandler.write_json(file_path, data, indent)


def validate_json_structure(data: Any, json_type: str) -> bool:
    """Validate that data matches the expected shape for json_type."""
    return JsonHandler.validate_json_structure(data, json_type)


def get_json_path(module_name: str, json_type: str) -> Path:
    """Return the filesystem path for a module's JSON file."""
    return _handler().get_json_path(module_name, json_type)


def ensure_json_exists(module_name: str, json_type: str) -> bool:
    """Ensure a single JSON file exists; create with defaults if missing."""
    return _handler().ensure_json_exists(module_name, json_type)


def ensure_module_jsons(module_name: str) -> bool:
    """Ensure all three JSON files (config, data, log) exist for a module."""
    return _handler().ensure_module_jsons(module_name)


def load_json(module_name: str, json_type: str) -> Optional[Any]:
    """Load a module's JSON file, auto-creating it if missing."""
    return _handler().load_json(module_name, json_type)


def save_json(module_name: str, json_type: str, data: Any) -> bool:
    """Save JSON file. Raises ValueError on invalid structure."""
    return _handler().save_json(module_name, json_type, data)


def log_operation(
    operation: str,
    data: Dict[str, Any] | None = None,
    module_name: str | None = None,
) -> bool:
    """Add entry to module operation log with automatic rotation."""
    if module_name is None:
        module_name = _get_caller_module_name()
    return _handler().log_operation(operation, data, module_name)
