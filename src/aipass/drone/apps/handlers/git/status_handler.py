# =================== AIPass ====================
# Name: status_handler.py
# Description: Scoped git status for branch directories
# Version: 1.1.0
# Created: 2026-03-17
# Modified: 2026-08-11
# =============================================

"""
Scoped git status for branch directories.

Runs ``git status --porcelain`` and filters results to files under the
caller's branch directory, providing a focused view of changes.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from aipass.prax import logger
from aipass.drone.apps.handlers.json import json_handler
from aipass.drone.apps.handlers.git.lock_handler import find_repo_root


def get_branch_status(branch_dir: Path) -> dict:
    """Get git status filtered to files under branch_dir.

    Args:
        branch_dir: Absolute path to the branch directory.

    Returns:
        Dict with ok (bool — False when git itself failed), files (list of
        {status, path, index, worktree}), total (int), and message (str).
        Callers must check ``ok``: an error return is otherwise
        indistinguishable from a clean empty tree, which false-greened
        `drone @git status` for months.

        ``status`` carries porcelain's TWO COLUMNS VERBATIM — index first, then
        worktree. It used to be stripped here, which made ``M `` (staged) and
        `` M`` (unstaged) the same answer, so every consumer downstream read a
        staged modification as an unstaged one. Stripping is a rendering
        choice and now lives in the renderer that wants it; this function
        reports what git said. ``index`` and ``worktree`` carry the columns
        split, because that split is what consumers actually branch on and
        re-slicing a padded string is where they get it wrong.
    """
    repo_root = find_repo_root()

    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.error("git status failed: %s", exc)
        return {"ok": False, "files": [], "total": 0, "message": f"git status failed: {exc}"}

    if result.returncode != 0:
        return {
            "ok": False,
            "files": [],
            "total": 0,
            "message": f"git status error: {result.stderr.strip()}",
        }

    # Compute relative path for filtering
    try:
        rel_dir = branch_dir.resolve().relative_to(repo_root.resolve())
    except ValueError:
        logger.warning(
            "get_branch_status: branch_dir %s not relative to repo root %s, using absolute", branch_dir, repo_root
        )
        rel_dir = branch_dir

    rel_prefix = rel_dir.as_posix() + "/"
    show_all = rel_dir == Path(".")

    files = []
    for line in result.stdout.splitlines():
        if len(line) < 4:
            continue
        status_code = line[:2]
        file_path = line[3:]
        if show_all or file_path.startswith(rel_prefix) or file_path == str(rel_dir):
            files.append(
                {
                    "status": status_code,
                    "path": file_path,
                    "index": status_code[0],
                    "worktree": status_code[1],
                }
            )

    total = len(files)
    message = f"{total} file(s) changed under {rel_dir}"
    json_handler.log_operation("get_branch_status", {"branch_dir": str(branch_dir), "total": total})
    logger.info(message)

    return {"ok": True, "files": files, "total": total, "message": message}
