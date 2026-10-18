# =================== AIPass ====================
# Name: module_root.py
# Description: Resolve a module's __file__ without an import-time cwd read
# Version: 1.0.0
# Created: 2026-08-31
# Modified: 2026-10-17
# =============================================

"""One guarded spelling for module-level __file__ resolution."""

from pathlib import Path

from aipass.prax import logger

MODULE_NAME = "module_root"

# Diagnostics that could not be logged (logging is what failed), newest last, bounded. Tests read it.
_UNREPORTED: list = []
_UNREPORTED_CAP = 20


def _retain(what: str, exc: BaseException) -> None:
    """Keep a diagnostic failure that could not be reported anywhere else. Cannot raise."""
    _UNREPORTED.append(f"{what}: {type(exc).__name__}: {exc}")
    del _UNREPORTED[:-_UNREPORTED_CAP]


def module_file(file: str) -> Path:
    """A module's own path, absolute, resolved when the filesystem allows.

    Windows resolve() reads the cwd, so a dead cwd falls back to the absolute __file__ unresolved.
    """
    path = Path(file)
    try:
        return path.resolve()
    except OSError as exc:
        _record_unresolved(path, exc)
        return path


def _record_unresolved(path: Path, exc: OSError) -> None:
    """Record the fallback without ever raising."""
    try:
        logger.debug(
            "[%s] Cannot resolve %s (%s) - using its absolute spelling",
            MODULE_NAME,
            path,
            type(exc).__name__,
        )
    except Exception as inner:  # the logger reads the cwd too; it must never take an import down
        _retain("logger", inner)

    try:
        from aipass.daemon.apps.handlers.json import json_handler

        json_handler.log_operation(
            "module_file_unresolved",
            {"path": str(path), "error": f"{type(exc).__name__}: {exc}"},
            module_name=MODULE_NAME,
        )
    except Exception as inner:  # an audit line must never take an import down
        _retain("audit", inner)
