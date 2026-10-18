# =================== AIPass ====================
# Name: module_root.py
# Description: Resolve a module's __file__ without an import-time cwd read
# Version: 1.0.0
# Created: 2026-08-31
# Modified: 2026-10-17
# =============================================

"""One guarded spelling for module-level __file__ resolution.

On Windows Path.resolve() always reads os.getcwd(): a module-level resolve fails import once the cwd is deleted."""

import sys
from pathlib import Path

from aipass.prax.apps.modules.logger import get_system_logger

logger = get_system_logger()

MODULE_NAME = "module_root"


def _record_unresolved(path: Path, exc: OSError) -> None:
    """Record the fallback; module_file wraps this call in its own protection."""
    # debug, not warning: every module import in this world takes this line, one condition.
    logger.debug(f"[{MODULE_NAME}] Cannot resolve {path} ({type(exc).__name__}) — using its absolute spelling")
    try:
        from aipass.api.apps.handlers.json import json_handler

        json_handler.log_operation(
            "module_file_unresolved",
            {"path": str(path), "error": f"{type(exc).__name__}: {exc}"},
            module_name=MODULE_NAME,
        )
    except Exception as inner:  # an audit line must never take an import down
        logger.debug(f"[{MODULE_NAME}] fallback not recorded: {type(inner).__name__}: {inner}")


def module_file(file: str) -> Path:
    """A module's own path, absolute, resolved when the filesystem allows."""
    path = Path(file)
    try:
        return path.resolve()
    except OSError as exc:
        # The logger may be down here too (it reads the cwd); a crashing diagnostic would become the import crash.
        try:
            _record_unresolved(path, exc)
        except Exception as inner:  # last resort below, never a re-raise
            sys.stderr.write(
                f"[{MODULE_NAME}] Cannot resolve {path} and cannot record it ({type(inner).__name__}: {inner})\n"
            )
        return path
