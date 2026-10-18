# =================== AIPass ====================
# Name: write_fence.py
# Description: The one fence on memory's writes — @memory may read another project, never write one
# Version: 1.0.1
# Created: 2026-09-18
# Modified: 2026-10-17
# =============================================

"""The write fence, defined once.

Containment on resolved paths, never startswith: /x/aipass_other is not in /x/aipass.
"""

from pathlib import Path

from aipass.prax import logger
from aipass.memory.apps.handlers import repo_root

MODULE_NAME = "write_fence"

# The source tree's root, never the caller's cwd. Tests monkeypatch it; nothing else moves it.
ROOT = repo_root.find_repo_root(caller=MODULE_NAME)


def outside_root(target: Path, root: Path) -> str | None:
    """The verdict alone: None when *target* is *root* or under it, else why not."""
    # repo_root's last resort is "/", which contains every path: fail shut.
    if root == root.parent:
        return f"{target} refused: the AIPass root resolved to the filesystem root {root}, which fences nothing"
    if target == root or root in target.parents:
        return None
    return f"{target} is outside the AIPass root {root} — @memory may read another project, never write one"


def fence_write(target: str | Path, *, lane: str) -> str | None:
    """Refuse a write that would land outside the AIPass root, loudly."""
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
    except Exception as exc:  # the refusal stands whether or not its record lands
        logger.debug(f"[{MODULE_NAME}] refusal not recorded: {type(exc).__name__}: {exc}")
    return refusal
