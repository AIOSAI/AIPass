# =================== AIPass ====================
# Name: diff_handler.py
# Description: Scoped git diff for branch directories
# Version: 1.1.0
# Created: 2026-05-12
# Modified: 2026-08-11
# =============================================

"""Scoped git diff for branch directories."""

from __future__ import annotations

import subprocess
from pathlib import Path

from aipass.prax import logger
from aipass.drone.apps.handlers.json import json_handler
from aipass.drone.apps.handlers.git.lock_handler import find_repo_root


def get_branch_diff(branch_dir: Path, staged: bool = False) -> dict:
    """Get git diff filtered to files under branch_dir."""
    repo_root = find_repo_root()

    cmd = ["git", "diff"]
    if staged:
        cmd.append("--staged")

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
