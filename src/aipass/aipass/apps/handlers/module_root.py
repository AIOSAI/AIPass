# =================== AIPass ====================
# Name: module_root.py
# Description: Resolve a module's __file__ without an import-time cwd read
# Version: 1.0.0
# Created: 2026-08-31
# Modified: 2026-10-17
# =============================================

"""One guarded spelling for module-level ``__file__`` resolution."""

from __future__ import annotations

from pathlib import Path

from aipass.prax import logger

MODULE_NAME = "module_root"


def module_file(file: str) -> Path:
    """A module's own path, absolute, resolved when the filesystem allows.

    Windows resolve() reads cwd, fatal at import if dead; ``__file__`` is absolute, never raise."""
    path = Path(file)
    try:
        return path.resolve()
    except OSError as exc:
        # debug, not warning: every import in that world lands here; the failing lane reports it.
        logger.debug("[%s] cannot resolve %s (%s) — using its absolute spelling", MODULE_NAME, path, type(exc).__name__)
        _record_unresolved(path, exc)
        return path


def _record_unresolved(path: Path, exc: OSError) -> None:
    """Record the fallback without ever raising; json_handler is imported late as it is a caller."""
    try:
        from aipass.aipass.apps.handlers.json import json_handler

        json_handler.log_operation(
            "module_file_unresolved",
            {"path": str(path), "error": f"{type(exc).__name__}: {exc}"},
            module_name=MODULE_NAME,
        )
    except Exception as inner:  # an audit line must never take an import down
        logger.debug("[%s] fallback not recorded: %s: %s", MODULE_NAME, type(inner).__name__, inner)
