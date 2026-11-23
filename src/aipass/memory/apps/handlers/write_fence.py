# =================== AIPass ====================
# Name: write_fence.py
# Description: The one fence on memory's writes — services write where they serve: the AIPass root and declared external branches
# Version: 1.1.1
# Created: 2026-09-18
# Modified: 2026-11-23
# =============================================

"""The write fence, defined once: containment on resolved paths, never startswith."""

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
    return f"{target} is outside the AIPass root {root}"


def _in_declared_branch(target: Path, home: Path) -> bool:
    """Is resolved *target* in a declared external branch, or in that branch's own todo backlog dir?"""
    from aipass.memory.apps.handlers.monitor import registry_scope
    from aipass.memory.apps.handlers.rollover import todo_roll

    for item in registry_scope.external_branches(home):
        backups = todo_roll.project_root_of(item["path"], home) / todo_roll.BACKUP_DIR
        allowed = [Path(item["path"]).resolve(), (backups / todo_roll.TODO_DIR / item["name"]).resolve()]
        if any(target == spot or spot in target.parents for spot in allowed):
            return True
    return False


def fence_write(target: str | Path, *, lane: str) -> str | None:
    """Refuse, loudly, a write that lands outside the AIPass root and every declared external branch."""
    home = Path(ROOT)
    try:
        resolved = Path(target).resolve()
        home = home.resolve()
        refusal = outside_root(resolved, home)
        if refusal is not None and home != home.parent:
            if _in_declared_branch(resolved, home):
                return None
            refusal += " or any declared external branch — services write where they serve, nowhere else"
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
