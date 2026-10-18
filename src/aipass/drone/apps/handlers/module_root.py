# =================== AIPass ====================
# Name: module_root.py
# Description: Resolve a module's __file__ without an import-time cwd read
# Version: 1.0.0
# Created: 2026-08-31
# Modified: 2026-10-17
# =============================================

"""One guarded spelling for module-level ``__file__`` resolution.

Windows ``Path.resolve()`` always reads ``os.getcwd()``: a module-level resolve dies on a deleted cwd.
"""

from __future__ import annotations

from pathlib import Path

from aipass.prax import logger

MODULE_NAME = "module_root"


def module_file(file: str) -> Path:
    """A module's own path, absolute (``__file__`` is, since 3.9), resolved when the filesystem allows."""
    path = Path(file)
    try:
        return path.resolve()
    except OSError as exc:
        # debug: every import takes this path in that world; the lane that fails should be loud.
        logger.debug(f"[{MODULE_NAME}] Cannot resolve {path} ({type(exc).__name__}) — using its absolute spelling")
        _record_unresolved(path, exc)
        return path


def _record_unresolved(path: Path, exc: OSError) -> None:
    """Record the fallback without ever raising.

    Function-level import: json_handler calls module_file, so it may be half-built here.
    """
    try:
        from aipass.drone.apps.handlers.json import json_handler

        json_handler.log_operation(
            "module_file_unresolved",
            {"path": str(path), "error": f"{type(exc).__name__}: {exc}"},
            module_name=MODULE_NAME,
        )
    except Exception as inner:  # an audit line must never take an import down
        logger.debug(f"[{MODULE_NAME}] fallback not recorded: {type(inner).__name__}: {inner}")
