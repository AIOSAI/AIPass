# =================== AIPass ====================
# Name: module_root.py
# Version: 1.0.0
# Description: Resolve a module's __file__ without an import-time cwd read
# Branch: hooks
# Layer: apps/handlers
# Created: 2026-08-31
# Modified: 2026-08-31
# =============================================

"""One guarded spelling for module-level __file__ resolution.

ntpath.realpath reads os.getcwd() UNCONDITIONALLY - not only for relative
paths, the way posixpath does - and Path.resolve() routes through it
(measured on the Windows CI gate 2026-08-31, @memory's finding, routed here
by @devpulse). So on Windows every module-level Path(__file__).resolve() is
an import-time working-directory dependency: a process whose cwd was deleted
cannot import the module.

Hooks carried FIVE such sites, and they were invisible until the guard in
apps/handlers/__init__.py was cured: that guard runs on every hooks import
and died first, so every module reported the same line and none of these
five could be seen. Curing the loudest site is what MADE the rest
measurable - the count before the guard cure was one, and it was wrong.

Shape mirrors @memory's repo_root.module_file - the ratified fleet cure -
sized to this branch, as @devpulse's module_root already is: hooks has no
module-level repo-root walk, so only the resolve guard lives here.
"""

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
        # debug, not warning: in the world that reaches this line every
        # module import takes it, and five identical warnings describe one
        # condition — reported once, loudly, by whichever lane fails on it.
        logger.debug(f"[{MODULE_NAME}] Cannot resolve {path} ({type(exc).__name__}) — using its absolute spelling")
        _record_unresolved(path, exc)
        return path


def _record_unresolved(path: Path, exc: OSError) -> None:
    """Record the fallback without ever raising.

    Runs at module import time on all five callers; a diagnostic write that
    fails in a bare world must not become the import crash this module
    exists to prevent.

    Args:
        path: The __file__ that could not be resolved.
        exc: The OSError resolve() raised.
    """
    try:
        from aipass.hooks.apps.handlers.json import json_handler

        json_handler.log_operation(
            "module_file_unresolved",
            {"path": str(path), "error": f"{type(exc).__name__}: {exc}"},
            module_name=MODULE_NAME,
        )
    except Exception as inner:  # noqa: BLE001 - an audit line must never take an import down
        logger.debug(f"[{MODULE_NAME}] fallback not recorded: {type(inner).__name__}: {inner}")
