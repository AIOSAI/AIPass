# =================== AIPass ====================
# Name: delete_branch_handler.py
# Description: Delete branch handler — remove remote branches with safety guards
# Version: 1.0.1
# Created: 2026-05-12
# Modified: 2026-10-23
# =============================================

"""Delete branch handler — remove remote branches with safety guards."""

from __future__ import annotations

import subprocess

from aipass.prax import logger
from aipass.drone.apps.handlers.json import json_handler
from aipass.drone.apps.handlers.git.lock_handler import find_repo_root

_PROTECTED_BRANCHES = ("main", "dev")


def delete_remote_branch(branch_name: str) -> dict:
    """Delete a remote branch with hard guards on protected branches.

    Returns:
        Dict with success and message keys.
    """
    if branch_name in _PROTECTED_BRANCHES:
        return {"success": False, "message": f"Refusing to delete protected branch '{branch_name}'."}
    if not branch_name or branch_name.startswith(("-", "refs/")) or ":" in branch_name:
        return {"success": False, "message": f"Refusing to delete '{branch_name}': not a plain branch name."}

    repo_root = find_repo_root()

    try:
        result = subprocess.run(
            ["git", "push", "--delete", "origin", branch_name],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.error("git push origin --delete %s failed: %s", branch_name, exc)
        return {"success": False, "message": f"Delete failed: {exc}"}

    if result.returncode != 0:
        return {"success": False, "message": f"Delete failed: {result.stderr.strip()}"}

    json_handler.log_operation("delete_remote_branch", {"branch": branch_name})
    logger.info("Deleted remote branch: %s", branch_name)

    return {"success": True, "message": f"Deleted remote branch '{branch_name}'."}
