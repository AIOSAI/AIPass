# =================== AIPass ====================
# Name: write_fence.py
# Description: The one fence on memory's writes — @memory may read another project, never write one
# Version: 1.0.1
# Created: 2026-09-18
# Modified: 2026-09-18
# =============================================

"""The write fence, defined once.

WHY THIS FILE EXISTS
--------------------
On 2026-09-17 07:47 one drone call made from Vera-Studio's working directory
persisted Vera-Studio's registry into ``memory_json/known_registries.json``.
From that minute every rollover wrote Vera-Studio's ``.trinity`` files, its
rollover backups and its ``.chroma`` store: a project nobody had put in scope,
reached through a list nobody reviewed.

The owner's ruling: @memory may READ another project and must never WRITE one.
Reading is how a caller's registry is understood; writing is ownership, and a
working directory grants none.

THE ROOT IS THE SOURCE TREE, NEVER THE CALLER
---------------------------------------------
``ROOT`` comes from ``repo_root.find_repo_root()`` — the AIPass root THIS file
sits in. There is no allow-list and no environment override: a declared root in
``AIPASS_ROOTS.json`` says where citizens live, not where @memory may write, and
production has exactly one root. Tests move the fence by monkeypatching
``ROOT``, which is the only seam.

THE VERDICT IS CONTAINMENT, ON RESOLVED PATHS
---------------------------------------------
``/x/aipass_other`` shares a prefix with ``/x/aipass`` and is not inside it, so
the verdict is ``root in target.parents``, never ``startswith``. Both sides are
resolved first, so a symlink inside the root cannot carry a write out of it. A
path that cannot be resolved is refused: a fence that fails open is a door.
"""

from pathlib import Path

from aipass.prax import logger
from aipass.memory.apps.handlers import repo_root

MODULE_NAME = "write_fence"

# The one root @memory writes under. Tests monkeypatch it; nothing else moves it.
ROOT = repo_root.find_repo_root(caller=MODULE_NAME)


def outside_root(target: Path, root: Path) -> str | None:
    """The verdict alone: None when *target* is *root* or under it, else why not.

    Pure — no filesystem, no logging. Callers resolve both paths first.

    Args:
        target: The path about to be written, resolved.
        root: The AIPass root, resolved.

    Returns:
        None when the write may land, otherwise a refusal naming both paths.
    """
    # repo_root's last resort is the filesystem root, and "/" contains every
    # path on the machine. An anchor with no parent is not a project: fail shut.
    if root == root.parent:
        return f"{target} refused: the AIPass root resolved to the filesystem root {root}, which fences nothing"
    if target == root or root in target.parents:
        return None
    return f"{target} is outside the AIPass root {root} — @memory may read another project, never write one"


def fence_write(target: str | Path, *, lane: str) -> str | None:
    """Refuse a write that would land outside the AIPass root, loudly.

    On refusal: an ERROR naming the path and the root, and an operation-log
    record. Nothing is written here; the caller fails the way it already fails.

    Args:
        target: The path about to be written (file or directory).
        lane: The writer asking, named in the log.

    Returns:
        None when the write may proceed, otherwise the refusal text.
    """
    home = Path(ROOT)
    try:
        resolved = Path(target).resolve()
        home = home.resolve()
        refusal = outside_root(resolved, home)
    except (OSError, RuntimeError) as exc:
        resolved = Path(target)
        refusal = f"{target} cannot be resolved against the AIPass root {home} ({type(exc).__name__}) — refused"
    if refusal is None:
        return None
    logger.error(f"[{MODULE_NAME}] REFUSED {lane}: {refusal}")
    try:
        from aipass.memory.apps.handlers.json import json_handler

        json_handler.log_operation(
            "write_fence_refused",
            {"lane": lane, "path": str(resolved), "root": str(home)},
            module_name=MODULE_NAME,
        )
    except Exception as exc:  # noqa: BLE001 - the refusal stands whether or not its record lands
        logger.debug(f"[{MODULE_NAME}] refusal not recorded: {type(exc).__name__}: {exc}")
    return refusal
