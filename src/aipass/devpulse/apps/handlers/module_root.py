# =================== AIPass ====================
# Name: module_root.py
# Description: Resolve a module's __file__ without an import-time cwd read
# Version: 1.1.0
# Created: 2026-08-31
# Modified: 2026-08-31
# =============================================

"""One guarded spelling for module-level __file__ resolution.

ntpath.realpath reads os.getcwd() UNCONDITIONALLY - not only for relative
paths, the way posixpath does - and Path.resolve() routes through it
(measured on the Windows CI gate 2026-08-31, @memory's finding). So on
Windows every module-level Path(__file__).resolve() is an import-time
working-directory dependency: a process whose cwd was deleted cannot import
the module. Devpulse carried six such sites; they route through
module_file() instead of each growing its own try/except.

Shape mirrors @memory's repo_root.module_file - the ratified fleet cure -
sized to this branch: devpulse has no module-level repo-root walk, so only
the resolve guard lives here.
"""

import sys
from pathlib import Path

from aipass.prax.apps.modules.logger import get_system_logger

logger = get_system_logger()

MODULE_NAME = "module_root"


def module_file(file: str) -> Path:
    """A module's own path, absolute, resolved when the filesystem allows.

    .resolve() is still attempted, because normalising symlinks is why the
    call is there and it succeeds on every healthy machine. The fallback is
    only reached in the world where the alternative is a dead import, and it
    is sound: __file__ has been absolute since Python 3.9, so the return is
    the right file either way - just spelled through the symlink rather than
    past it.

    Args:
        file: A module's __file__.

    Returns:
        The module's path, resolved if the filesystem could be asked.
    """
    path = Path(file)
    try:
        return path.resolve()
    except OSError as exc:
        # The diagnostics live inside their own protection (@daemon's finding
        # on this very file, 2026-08-31): the world that reaches this line is
        # exactly the world where the logger may be down too - prax's logger
        # construction reads the cwd. A crashing diagnostic here would BECOME
        # the import crash this module exists to prevent.
        try:
            _record_unresolved(path, exc)
        except Exception as inner:  # noqa: BLE001 - last resort below, never a re-raise
            # stderr is the one channel left that asks nothing of the
            # filesystem; not silent, just not the usual instrument.
            sys.stderr.write(
                f"[{MODULE_NAME}] Cannot resolve {path} and cannot record it ({type(inner).__name__}: {inner})\n"
            )
        return path


def _record_unresolved(path: Path, exc: OSError) -> None:
    """Record the fallback; module_file wraps this call in its own protection.

    Runs at module import time on all six callers. The logger line is the
    primary diagnostic and may itself raise in the world that gets here -
    that raise belongs to module_file's wrapper, which owns the promise
    that no diagnostic becomes an import crash.

    Args:
        path: The __file__ that could not be resolved.
        exc: The OSError resolve() raised.
    """
    # debug, not warning: in the world that reaches this line every module
    # import takes it, and six identical warnings describe one condition -
    # reported once, loudly, by whichever lane actually fails on it.
    logger.debug(f"[{MODULE_NAME}] Cannot resolve {path} ({type(exc).__name__}) — using its absolute spelling")
    try:
        from aipass.devpulse.apps.handlers.json import json_handler

        json_handler.log_operation(
            "module_file_unresolved",
            {"path": str(path), "error": f"{type(exc).__name__}: {exc}"},
            module_name=MODULE_NAME,
        )
    except Exception as inner:  # noqa: BLE001 - an audit line must never take an import down
        logger.debug(f"[{MODULE_NAME}] fallback not recorded: {type(inner).__name__}: {inner}")
