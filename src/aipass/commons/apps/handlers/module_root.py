# =================== AIPass ====================
# Name: module_root.py
# Description: Resolve a module's __file__ without an import-time cwd read
# Version: 1.0.0
# Created: 2026-08-31
# Modified: 2026-08-31
# =============================================

"""One guarded spelling for module-level __file__ resolution.

ntpath.realpath reads os.getcwd() UNCONDITIONALLY - not only for relative
paths, the way posixpath does - and Path.resolve() routes through it (measured
on the Windows CI gate 2026-08-31, @memory's finding). So on Windows every
Path(__file__).resolve() REACHED AT IMPORT is a working-directory dependency:
a process whose cwd was deleted cannot import the module. Commons carried
three such sites; they route through module_file() rather than each growing
its own try/except.

Shape mirrors @devpulse's module_root and @memory's repo_root.module_file -
the ratified fleet cure - sized to this branch. The handlers package guard in
__init__.py keeps its own inline spelling on purpose: it runs BEFORE this
module can be imported, because importing it is what triggers the guard.
"""

from pathlib import Path

from aipass.prax.apps.modules.logger import system_logger as logger

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
        # debug, not warning: in the world that reaches this line every commons
        # import takes it, and three identical warnings describe one condition -
        # reported once, loudly, by whichever lane actually fails on it.
        logger.debug(f"[{MODULE_NAME}] Cannot resolve {path} ({type(exc).__name__}) — using its absolute spelling")
        _record_unresolved(path, exc)
        return path


def _record_unresolved(path: Path, exc: OSError) -> None:
    """Record the fallback without ever raising.

    Runs at module import time on all three callers; a diagnostic write that
    fails in a bare world must not become the import crash this module exists
    to prevent. json_handler is imported lazily because json_handler is itself
    one of the three callers - a module-level import here would be a cycle.

    Args:
        path: The __file__ that could not be resolved.
        exc: The OSError resolve() raised.
    """
    try:
        from aipass.commons.apps.handlers.json import json_handler

        json_handler.log_operation(
            "module_file_unresolved",
            {"path": str(path), "error": f"{type(exc).__name__}: {exc}"},
            module_name=MODULE_NAME,
        )
    except Exception as inner:  # noqa: BLE001 - an audit line must never take an import down
        logger.debug(f"[{MODULE_NAME}] fallback not recorded: {type(inner).__name__}: {inner}")
