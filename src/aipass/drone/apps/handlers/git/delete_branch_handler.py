# =================== AIPass ====================
# Name: delete_branch_handler.py
# Description: Delete branch handler — remove remote branches with safety guards
# Version: 1.1.0
# Created: 2026-05-12
# Modified: 2026-11-20
# =============================================

"""Delete branch handler — remove remote branches with safety guards."""

from __future__ import annotations

import subprocess
from pathlib import Path

from aipass.prax import logger
from aipass.drone.apps.handlers.json import json_handler
from aipass.drone.apps.handlers.git.lock_handler import find_repo_root
from aipass.drone.apps.handlers.git.repo_door import GIT_LOCAL_TIMEOUT, GIT_NETWORK_TIMEOUT, github_slug

_PROTECTED_BRANCHES = ("main", "dev")
_OPEN_PR_NUMBERS = ("--json", "number", "--jq", ".[].number")


def _git(repo_root: Path, *args: str, timeout: int = GIT_LOCAL_TIMEOUT) -> subprocess.CompletedProcess:
    """Run git in *repo_root*, timed."""
    return subprocess.run(["git", *args], capture_output=True, text=True, cwd=str(repo_root), timeout=timeout)


def _refusal(repo_root: Path, branch_name: str) -> str | None:
    """Why *branch_name* stays on origin: it is checked out here, or it has an open PR, or that cannot be checked."""
    current = _git(repo_root, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    if branch_name == current:
        return f"Refusing to delete '{branch_name}': it is the branch checked out in {repo_root}."
    slug = github_slug(_git(repo_root, "remote", "get-url", "origin").stdout)
    if slug is None:
        return f"Refusing to delete '{branch_name}': origin of {repo_root} names no github.com repo to ask about PRs."
    argv = ["gh", "pr", "list", "-R", slug, "--head", branch_name, "--state", "open", *_OPEN_PR_NUMBERS]
    found = subprocess.run(argv, capture_output=True, text=True, cwd=str(repo_root), timeout=GIT_NETWORK_TIMEOUT)
    if found.returncode != 0:
        logger.warning("delete-branch: open-PR check for %s failed: %s", branch_name, found.stderr.strip())
        return f"Refusing to delete '{branch_name}': could not check for an open PR ({found.stderr.strip()})."
    numbers = found.stdout.split()
    if numbers:
        return f"Refusing to delete '{branch_name}': it has an open pull request #{numbers[0]} on {slug}."
    return None


def delete_remote_branch(branch_name: str) -> dict:
    """Delete a remote branch: never main, dev, the checked-out branch or one with an open PR.

    Returns:
        Dict with success and message keys.
    """
    if branch_name in _PROTECTED_BRANCHES:
        return {"success": False, "message": f"Refusing to delete protected branch '{branch_name}'."}
    if not branch_name or branch_name.startswith(("-", "refs/")) or ":" in branch_name:
        return {"success": False, "message": f"Refusing to delete '{branch_name}': not a plain branch name."}

    repo_root = find_repo_root()

    try:
        refusal = _refusal(repo_root, branch_name)
        if refusal is not None:
            logger.info("delete-branch: %s", refusal)
            return {"success": False, "message": refusal}
        result = _git(repo_root, "push", "--delete", "origin", branch_name, timeout=GIT_NETWORK_TIMEOUT)
    except (OSError, subprocess.SubprocessError) as exc:
        logger.error("delete-branch %s in %s could not run: %s", branch_name, repo_root, exc)
        return {"success": False, "message": f"Delete failed: {exc}"}

    if result.returncode != 0:
        return {"success": False, "message": f"Delete failed: {result.stderr.strip()}"}

    json_handler.log_operation("delete_remote_branch", {"branch": branch_name, "repo": str(repo_root)})
    logger.info("Deleted remote branch: %s in %s", branch_name, repo_root)

    return {"success": True, "message": f"Deleted remote branch '{branch_name}'."}
