# =================== AIPass ====================
# Name: module_root.py
# Description: Resolve a module's __file__ without an import-time cwd read
# Version: 1.0.0
# Created: 2026-08-31
# Modified: 2026-08-31
# =============================================

"""One guarded spelling for module-level __file__ resolution.

ntpath.realpath reads the working directory UNCONDITIONALLY - not only for
relative paths, the way posixpath does - and Path.resolve() routes through it
(measured on the Windows CI gate 2026-08-31, @memory's finding). So on Windows
every module-level Path(__file__).resolve() is an import-time working-directory
dependency: a process whose cwd was deleted cannot import the module.

MEASURED IN DAEMON, not assumed: with the handlers guard cured, 25 of 35
importable daemon modules still died under the dead-cwd world, and every one of
them died on the SAME line - json_handler.py's _DAEMON_ROOT. Ten module-level
resolve sites exist in the tree; only the import-reached ones can kill an
import, and they route through here now instead of each growing its own
try/except.

Shape mirrors @devpulse's module_root.module_file - the minimal ratified form -
because daemon has no module-level repo-root walk ending in a working-directory
fallback. Every daemon root constant is parents[N] off __file__, so the resolve
guard is the whole cure here; there is nothing for @trigger's SOURCE_ROOT
treatment to fix.
"""

from pathlib import Path

from aipass.prax import logger

MODULE_NAME = "module_root"

# Diagnostics this module could not emit, newest last. A swallow that RETAINS
# the error is not a silent catch: the failure stays readable from the process
# that took it, and tests assert on it. The list is the only sanctioned landing
# place because the obvious one - log it - is exactly what failed. Bounded, so a
# pathological caller cannot grow it without limit.
_UNREPORTED: list = []
_UNREPORTED_CAP = 20


def _retain(what: str, exc: BaseException) -> None:
    """Keep a diagnostic failure that could not be reported anywhere else.

    Cannot raise, by construction: a list append and a slice. Every caller is a
    handler running in a world where the filesystem, the logger, or both have
    already failed, so anything that could itself fail belongs somewhere else.

    Args:
        what: Which lane failed ("logger" or "audit").
        exc: The exception that lane raised.
    """
    _UNREPORTED.append(f"{what}: {type(exc).__name__}: {exc}")
    del _UNREPORTED[:-_UNREPORTED_CAP]


def module_file(file: str) -> Path:
    """A module's own path, absolute, resolved when the filesystem allows.

    .resolve() is still attempted, because normalising symlinks is why the call
    is there and it succeeds on every healthy machine. The fallback is only
    reached in the world where the alternative is a dead import, and it is
    sound: __file__ has been absolute since Python 3.9, so the return is the
    right file either way - just spelled through the symlink rather than past
    it.

    Args:
        file: A module's __file__.

    Returns:
        The module's path, resolved if the filesystem could be asked.
    """
    path = Path(file)
    try:
        return path.resolve()
    except OSError as exc:
        _record_unresolved(path, exc)
        return path


def _record_unresolved(path: Path, exc: OSError) -> None:
    """Record the fallback without ever raising.

    EVERYTHING diagnostic lives inside this function's protection, the logger
    call included. That placement is a fix, not a style choice: the first cut
    logged from module_file() itself, one line above this call and OUTSIDE any
    try, and a pin with a raising logger caught it. The world that reaches this
    code is a machine whose filesystem cannot answer a basic question, and
    @prax's logger construction reads the working directory - so "the logger is
    also down" is the SAME world, not a contrived one. A guard that dies in its
    own diagnostic is worse than no guard: it converts a survivable import into
    a crash while claiming to prevent exactly that.

    debug, not warning: in the world that reaches this line every module import
    takes it, and eight identical warnings describe one condition - reported
    once, loudly, by whichever lane fails on it.

    Args:
        path: The __file__ that could not be resolved.
        exc: The OSError resolve() raised.
    """
    try:
        logger.debug(
            "[%s] Cannot resolve %s (%s) - using its absolute spelling",
            MODULE_NAME,
            path,
            type(exc).__name__,
        )
    except Exception as inner:  # noqa: BLE001 - a log line must never take an import down
        _retain("logger", inner)

    try:
        from aipass.daemon.apps.handlers.json import json_handler

        json_handler.log_operation(
            "module_file_unresolved",
            {"path": str(path), "error": f"{type(exc).__name__}: {exc}"},
            module_name=MODULE_NAME,
        )
    except Exception as inner:  # noqa: BLE001 - an audit line must never take an import down
        _retain("audit", inner)
