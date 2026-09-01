# =================== AIPass ====================
# Name: module_root.py
# Description: Resolve a module's __file__ without an import-time cwd read
# Version: 1.0.0
# Created: 2026-08-31
# Modified: 2026-08-31
# =============================================

"""One guarded spelling for module-level ``__file__`` resolution.

``ntpath.realpath`` reads ``os.getcwd()`` UNCONDITIONALLY — not only for
relative paths, the way ``posixpath`` does — and ``Path.resolve()`` routes
through it (measured on the Windows CI gate 2026-08-31, @memory's finding).
So on Windows every module-level ``Path(__file__).resolve()`` is an
import-time working-directory dependency: a process whose cwd was deleted
cannot import the module at all, and no amount of guarding INSIDE the module's
functions helps, because the import died before any of them existed.

Drone carried three such sites — ``json_handler``, ``command_registry.ops``
and ``module_registry_handler`` — and ``json_handler`` is imported by nearly
every other module in the branch, so one line took the whole router down.
Measured under the hostile world rather than argued: 63 of 63 drone modules
died on import, 56 of them at ``json_handler.py:41`` once the handlers guard
above it was cured.

Sized to this branch, following @memory's ratified ``repo_root.module_file``.
Drone has no module-level repo-root walk — ``TestTheSweepIsComplete`` has
banned bare working-directory reads outside ``caller_cwd()`` since session 77 —
so only the resolve guard lives here.

WHY THIS IS NOT IN ``handlers/__init__.py``: the package guard runs before any
submodule exists and cannot import one without re-entering itself. It carries
its own two-line ``_safe_resolve`` on purpose. A guard that depends on the
thing it guards is not a guard.
"""

from __future__ import annotations

from pathlib import Path

from aipass.prax import logger

MODULE_NAME = "module_root"


def module_file(file: str) -> Path:
    """A module's own path, absolute, resolved when the filesystem allows.

    ``.resolve()`` is still ATTEMPTED, because normalising symlinks is why the
    call is there and it succeeds on every healthy machine. The fallback is
    reached only in the world where the alternative is a dead import, and it is
    sound: ``__file__`` has been absolute since Python 3.9, so the return names
    the right file either way — just spelled through the symlink rather than
    past it.

    Args:
        file: A module's ``__file__``.

    Returns:
        The module's path, resolved if the filesystem could be asked.
    """
    path = Path(file)
    try:
        return path.resolve()
    except OSError as exc:
        # debug, not warning: in the world that reaches this line EVERY module
        # import takes it, and three identical warnings describe one condition.
        # Whichever lane actually fails on it is the one that should be loud.
        logger.debug(f"[{MODULE_NAME}] Cannot resolve {path} ({type(exc).__name__}) — using its absolute spelling")
        _record_unresolved(path, exc)
        return path


def _record_unresolved(path: Path, exc: OSError) -> None:
    """Record the fallback without ever raising.

    The import is deliberately function-level, and for TWO reasons. It breaks a
    genuine cycle — ``json_handler`` is one of this module's three callers, so a
    module-level import here would be drone importing itself mid-definition —
    and it defers the cost to the only world that reaches this line. When the
    caller IS ``json_handler``'s own line 41, ``sys.modules`` hands back a
    half-built module and ``log_operation`` may not exist yet; that is an
    ``AttributeError``, caught below, and losing one audit line is the right
    trade against turning the import crash back on.

    Args:
        path: The ``__file__`` that could not be resolved.
        exc: The ``OSError`` ``resolve()`` raised.
    """
    try:
        from aipass.drone.apps.handlers.json import json_handler

        json_handler.log_operation(
            "module_file_unresolved",
            {"path": str(path), "error": f"{type(exc).__name__}: {exc}"},
            module_name=MODULE_NAME,
        )
    except Exception as inner:  # noqa: BLE001 - an audit line must never take an import down
        logger.debug(f"[{MODULE_NAME}] fallback not recorded: {type(inner).__name__}: {inner}")
