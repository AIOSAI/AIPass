# =================== AIPass ====================
# Name: module_root.py
# Version: 1.0.0
# Description: Resolve a module's __file__ without an import-time cwd read
# Branch: hooks
# Layer: apps/handlers
# Created: 2026-08-31
# Modified: 2026-10-17
# =============================================

"""One guarded spelling for module-level __file__ resolution.

On Windows Path.resolve() reads os.getcwd() unconditionally: a process whose cwd was deleted cannot import.
"""

from pathlib import Path

from aipass.prax.apps.modules.logger import get_system_logger

logger = get_system_logger()

MODULE_NAME = "module_root"


def module_file(file: str) -> Path:
    """A module's own path, absolute, resolved when the filesystem allows.

    The fallback is sound: __file__ is absolute, so it names the right file, through the symlink.
    """
    path = Path(file)
    try:
        return path.resolve()
    except OSError as exc:
        # debug, not warning: every module import takes this line in that world.
        logger.debug(f"[{MODULE_NAME}] Cannot resolve {path} ({type(exc).__name__}) — using its absolute spelling")
        _record_unresolved(path, exc)
        return path


def _record_unresolved(path: Path, exc: OSError) -> None:
    """Record the fallback without ever raising."""
    try:
        from aipass.hooks.apps.handlers.json import json_handler

        json_handler.log_operation(
            "module_file_unresolved",
            {"path": str(path), "error": f"{type(exc).__name__}: {exc}"},
            module_name=MODULE_NAME,
        )
    except Exception as inner:  # an audit line must never take an import down
        logger.debug(f"[{MODULE_NAME}] fallback not recorded: {type(inner).__name__}: {inner}")
