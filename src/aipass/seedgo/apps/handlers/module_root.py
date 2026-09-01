# =================== AIPass ====================
# Name: module_root.py
# Description: Resolve a module's __file__ without an import-time cwd read
# Version: 1.0.0
# Created: 2026-08-31
# Modified: 2026-08-31
# =============================================

"""One guarded spelling for module-level ``__file__`` resolution.

THE MECHANISM. ``ntpath.realpath`` calls ``os.getcwd()`` UNCONDITIONALLY — on
its first lines, before it checks whether the path is even relative, which is
where it differs from ``posixpath`` — and ``Path.resolve()`` routes straight
through it. So on Windows every module-level ``Path(__file__).resolve()`` is an
import-time working-directory read, and a process whose cwd was deleted cannot
import the module at all. Measured on the Windows CI gate 2026-08-31
(@memory's finding, relayed by @devpulse).

WHAT IT COST HERE. Twelve seedgo modules resolved ``__file__`` at import to
build a constant, and the guard in ``handlers/__init__.py`` did it a thirteenth
time before any of them. The audit is the one instrument that must survive a
broken world in order to describe it: a standards auditor that cannot be
imported without a readable cwd cannot report that anything else needs one.

THE DISCRIMINATOR IS *REACHED AT IMPORT*, not *written at module scope* — a
default argument counts if import-time code calls it, and a module-scope line
inside a function body does not. Which is why the twelve sites were found by
RUNNING the world (``Path.resolve`` wrapped to record its caller while every
seedgo module was imported), never by grepping: the tree holds 75 ``.resolve()``
call sites and 61 of them are call-time.

Shape mirrors @memory's ``repo_root.module_file`` — the ratified fleet cure —
sized to this branch: seedgo has no module-level repo-root walk, so only the
resolve guard lives here.
"""

from pathlib import Path

from aipass.prax import logger

MODULE_NAME = "module_root"


def module_file(file: str) -> Path:
    """A module's own path, absolute, resolved when the filesystem allows.

    ``.resolve()`` is still ATTEMPTED, because normalising symlinks is why the
    call is there and it succeeds on every healthy machine. The fallback is only
    reached in the world where the alternative is a dead import, and it is
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
        # info, not warning: in the world that reaches this line EVERY module
        # import takes it, and twelve identical warnings describe one condition.
        # Whichever lane actually fails on it is the one that should be loud.
        logger.info("%s: cannot resolve %s (%s) — using its absolute spelling", MODULE_NAME, path, type(exc).__name__)
        _record_unresolved(path, exc)
        return path


def _record_unresolved(path: Path, exc: OSError) -> None:
    """Record the fallback without ever raising.

    Runs at module import time on all twelve callers; a diagnostic write that
    fails in a bare world must not become the import crash this module exists to
    prevent. The bare ``Exception`` is the point, not an oversight.

    Args:
        path: The ``__file__`` that could not be resolved.
        exc: The OSError ``resolve()`` raised.
    """
    try:
        from aipass.seedgo.apps.handlers.json import json_handler

        json_handler.log_operation(
            "module_file_unresolved",
            {"path": str(path), "error": f"{type(exc).__name__}: {exc}"},
            module_name=MODULE_NAME,
        )
    except Exception as inner:  # noqa: BLE001 - an audit line must never take an import down
        logger.info("%s: fallback not recorded: %s: %s", MODULE_NAME, type(inner).__name__, inner)
