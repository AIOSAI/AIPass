# =================== AIPass ====================
# Name: diff_handler.py
# Description: Scoped git diff for branch directories
# Version: 1.3.0
# Created: 2026-05-12
# Modified: 2026-10-04
# =============================================

"""Scoped git diff for branch directories."""

from __future__ import annotations

import subprocess
from pathlib import Path

from aipass.prax import logger
from aipass.drone.apps.handlers.json import json_handler
from aipass.drone.apps.handlers.git.lock_handler import find_repo_root


def get_branch_diff(
    branch_dir: Path,
    staged: bool = False,
    repo_root: Path | None = None,
    paths: list[str] | None = None,
    stat: bool = False,
) -> dict:
    """Get git diff filtered to files under branch_dir, in *repo_root* (default: the standing repo).

    *paths* (absolute) narrow the diff to those files instead, and *stat*
    prints git's summary in place of the patch. Either one hands git a
    pathspec rather than filtering its output: a ``--stat`` table has no
    ``diff --git`` lines to filter by.
    """
    if repo_root is None:
        repo_root = find_repo_root()

    cmd = ["git", "diff"]
    if staged:
        cmd.append("--staged")
    if stat:
        cmd.append("--stat")
    if paths or stat:
        return _diff_by_pathspec(cmd, branch_dir, repo_root, paths, staged)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(repo_root),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.error("git diff failed: %s", exc)
        return {"ok": False, "diff": "", "files_changed": 0, "message": f"git diff failed: {exc}"}

    if result.returncode != 0:
        return {
            "ok": False,
            "diff": "",
            "files_changed": 0,
            "message": f"git diff error: {result.stderr.strip()}",
        }

    try:
        rel_dir = branch_dir.resolve().relative_to(repo_root.resolve())
    except ValueError:
        logger.warning(
            "get_branch_diff: branch_dir %s not relative to repo root %s",
            branch_dir,
            repo_root,
        )
        rel_dir = branch_dir

    rel_prefix = rel_dir.as_posix() + "/"
    show_all = rel_dir == Path(".")

    filtered_lines: list[str] = []
    include_block = False
    files_changed = 0
    for line in result.stdout.splitlines():
        if line.startswith("diff --git"):
            include_block = show_all or rel_prefix in line
            if include_block:
                files_changed += 1
        if include_block:
            filtered_lines.append(line)

    filtered_diff = "\n".join(filtered_lines)
    message = f"{files_changed} file(s) changed under {rel_dir}"

    json_handler.log_operation(
        "get_branch_diff",
        {"branch_dir": str(branch_dir), "files_changed": files_changed, "staged": staged},
    )
    logger.info(message)

    return {"ok": True, "diff": filtered_diff, "files_changed": files_changed, "message": message}


def _diff_by_pathspec(cmd: list[str], branch_dir: Path, repo_root: Path, paths: list[str] | None, staged: bool) -> dict:
    """Run *cmd* limited to *paths*, or to *branch_dir* when none are named (the whole repo when it is the root)."""
    if paths:
        pathspec = paths
    elif branch_dir.resolve() == repo_root.resolve():
        pathspec = []
    else:
        pathspec = [str(branch_dir)]
    try:
        result = subprocess.run(cmd + ["--", *pathspec], capture_output=True, text=True, cwd=str(repo_root))
    except (OSError, subprocess.SubprocessError) as exc:
        logger.error("git diff failed: %s", exc)
        return {"ok": False, "diff": "", "files_changed": 0, "message": f"git diff failed: {exc}"}
    if result.returncode != 0:
        return {"ok": False, "diff": "", "files_changed": 0, "message": f"git diff error: {result.stderr.strip()}"}

    output = result.stdout.rstrip("\n")
    marker = " | " if "--stat" in cmd else "diff --git"
    files_changed = sum(1 for line in output.splitlines() if marker in line)
    scope = f"{len(paths)} path(s)" if paths else str(branch_dir)
    message = f"{files_changed} file(s) changed in {scope}"
    json_handler.log_operation(
        "get_branch_diff",
        {"branch_dir": str(branch_dir), "files_changed": files_changed, "staged": staged, "paths": len(paths or [])},
    )
    logger.info(message)
    return {"ok": True, "diff": output, "files_changed": files_changed, "message": message}
