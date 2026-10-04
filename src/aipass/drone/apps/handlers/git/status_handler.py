# =================== AIPass ====================
# Name: status_handler.py
# Description: Scoped git status for branch directories
# Version: 1.3.0
# Created: 2026-03-17
# Modified: 2026-10-04
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


def get_branch_status(branch_dir: Path, repo_root: Path | None = None) -> dict:
    """Get git status filtered to files under branch_dir.

    Args:
        branch_dir: Absolute path to the branch directory.
        repo_root: The repo to run in. Defaults to the one the caller stands in;
            the external-repo door names another one outright.

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
    if repo_root is None:
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


def _git(repo_root: Path, *argv: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *argv], capture_output=True, text=True, cwd=str(repo_root))


def _no_count(branch: str | None, message: str) -> dict:
    return {"ok": True, "branch": branch, "upstream": None, "ahead": None, "behind": None, "message": message}


def get_ahead_behind(repo_root: Path) -> dict:
    """How far the current branch is from its origin twin, as of the last fetch: no network.

    The twin of ``git rev-list --left-right --count origin/<b>...HEAD``.

    Returns:
        Dict with ok (bool), branch (str, or None when HEAD is detached),
        upstream (``origin/<b>``, or None when origin has no such branch),
        ahead and behind (int, or None with no upstream), and message (str).
    """
    head = _git(repo_root, "symbolic-ref", "--quiet", "--short", "HEAD")
    if head.returncode == 1:
        return _no_count(None, "HEAD is detached: no branch to compare with origin")
    if head.returncode != 0:
        logger.error("git symbolic-ref failed in %s: %s", repo_root, head.stderr.strip())
        return {**_no_count(None, f"git symbolic-ref error: {head.stderr.strip()}"), "ok": False}
    branch = head.stdout.strip()
    upstream = f"origin/{branch}"
    known = _git(repo_root, "rev-parse", "--verify", "--quiet", f"refs/remotes/{upstream}")
    if known.returncode != 0:
        return _no_count(branch, f"{branch}: no {upstream} to compare with")
    counted = _git(repo_root, "rev-list", "--left-right", "--count", f"refs/remotes/{upstream}...HEAD")
    if counted.returncode != 0:
        logger.error("git rev-list failed for %s: %s", upstream, counted.stderr.strip())
        return {**_no_count(branch, f"git rev-list error: {counted.stderr.strip()}"), "ok": False}
    behind, ahead = (int(n) for n in counted.stdout.split())
    message = f"{branch}: {ahead} ahead, {behind} behind {upstream} (as of the last fetch)"
    json_handler.log_operation("get_ahead_behind", {"branch": branch, "ahead": ahead, "behind": behind})
    return {"ok": True, "branch": branch, "upstream": upstream, "ahead": ahead, "behind": behind, "message": message}
