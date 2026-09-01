# =================== AIPass ====================
# Name: module_root.py
# Description: Resolve a module's __file__ without an import-time cwd read
# Version: 1.0.0
# Created: 2026-08-31
# Modified: 2026-08-31
# =============================================

"""One guarded spelling for module-level ``__file__`` resolution.

``ntpath.realpath`` computes ``os.getcwd()`` UNCONDITIONALLY — on its first
lines, before it checks whether the path is even absolute, unlike
``posixpath`` — and ``Path.resolve()`` routes through it.  So on Windows every
``Path(__file__).resolve()`` REACHED AT IMPORT is an import-time
working-directory dependency: a process whose cwd was deleted, or whose cwd is
a disconnected network share, cannot import the module at all.  Measured on the
Windows CI gate 2026-08-31 (@memory's finding, @devpulse's fleet dispatch).

The discriminator is *reached at import*, not *written at module scope*: a call
inside a function counts whenever import-time code calls that function.  This
branch carried five such sites; they route through :func:`module_file` instead
of each growing its own ``try``/``except``.

Shape mirrors @memory's ``repo_root.module_file`` — the ratified fleet cure —
sized to this branch: aipass resolves no repo root at import time (readme_map's
walk and ping_sweep's registry walk are both call-time), so only the resolve
guard lives here.

IMPORTING THIS MODULE MUST NEVER RAISE.  Its callers resolve at module level,
so anything this file does at import time happens during THEIR import — which
is why the audit line on the fallback path is written defensively.  The
``json_handler`` import is function-local for the same reason: ``json_handler``
is itself a caller, so a module-level edge back would be a cycle.
"""

from __future__ import annotations

from pathlib import Path

from aipass.prax import logger

MODULE_NAME = "module_root"


def module_file(file: str) -> Path:
    """A module's own path, absolute, resolved when the filesystem allows.

    ``.resolve()`` is still attempted, because normalising symlinks is why the
    call is there and it succeeds on every healthy machine.  The fallback is
    only reached in the world where the alternative is a dead import, and it is
    sound: ``__file__`` has been absolute since Python 3.9, so the return is the
    right file either way — just spelled through the symlink rather than past
    it.

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
        # import takes it, and five identical warnings describe one condition.
        # The condition is reported once, loudly, by whichever lane fails on it.
        logger.debug("[%s] cannot resolve %s (%s) — using its absolute spelling", MODULE_NAME, path, type(exc).__name__)
        _record_unresolved(path, exc)
        return path


def _record_unresolved(path: Path, exc: OSError) -> None:
    """Record the fallback without ever raising.

    Runs at module import time on every caller; a diagnostic write that fails
    in a bare world must not become the import crash this module exists to
    prevent.

    Args:
        path: The ``__file__`` that could not be resolved.
        exc: The ``OSError`` ``resolve()`` raised.
    """
    try:
        from aipass.aipass.apps.handlers.json import json_handler

        json_handler.log_operation(
            "module_file_unresolved",
            {"path": str(path), "error": f"{type(exc).__name__}: {exc}"},
            module_name=MODULE_NAME,
        )
    except Exception as inner:  # noqa: BLE001 - an audit line must never take an import down
        logger.debug("[%s] fallback not recorded: %s: %s", MODULE_NAME, type(inner).__name__, inner)
