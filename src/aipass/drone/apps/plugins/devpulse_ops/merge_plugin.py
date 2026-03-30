# =================== AIPass ====================
# Name: merge_plugin.py
# Description: Squash-merge a PR and sync local main
# Version: 1.0.0
# Created: 2026-03-30
# Modified: 2026-03-30
# =============================================

"""Squash-merge a PR and sync local main.

Squash-merges the given PR number via ``gh``, deletes the remote branch,
pulls to sync local main, and returns the merge commit hash and PR title.
Only authorized callers (verified via :mod:`auth`) may invoke this.
"""

from __future__ import annotations

import subprocess

from aipass.prax import logger
from aipass.drone.apps.handlers.json import json_handler
from aipass.drone.apps.handlers.git.lock_handler import find_repo_root


def merge_pr(pr_number: str, caller: str) -> dict:
    """Squash-merge a PR and sync local main.

    Args:
        pr_number: The PR number to merge (e.g. ``"42"``).
        caller: The verified caller name (e.g. ``"devpulse"``).

    Returns:
        Dict with success, pr_number, title, merge_commit, and message.
    """
    repo_root = find_repo_root()

    result: dict = {
        "success": False,
        "pr_number": pr_number,
        "title": "",
        "merge_commit": "",
        "message": "",
    }

    try:
        # Step 1: Squash-merge the PR
        merge = subprocess.run(
            ["gh", "pr", "merge", pr_number, "--squash", "--delete-branch"],
            capture_output=True, text=True, cwd=str(repo_root),
        )
        if merge.returncode != 0:
            result["message"] = f"Merge failed: {merge.stderr.strip()}"
            logger.error(result["message"])
            return result

        # Step 2: Sync local main
        pull = subprocess.run(
            ["git", "pull", "--rebase"],
            capture_output=True, text=True, cwd=str(repo_root),
        )
        if pull.returncode != 0:
            result["message"] = f"Pull after merge failed: {pull.stderr.strip()}"
            logger.error(result["message"])
            return result

        # Step 3: Get the merge commit hash
        rev = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, cwd=str(repo_root),
        )
        merge_commit = rev.stdout.strip() if rev.returncode == 0 else "unknown"

        # Step 4: Get the PR title
        title_proc = subprocess.run(
            ["gh", "pr", "view", pr_number, "--json", "title", "--jq", ".title"],
            capture_output=True, text=True, cwd=str(repo_root),
        )
        title = title_proc.stdout.strip() if title_proc.returncode == 0 else "unknown"

        result["success"] = True
        result["title"] = title
        result["merge_commit"] = merge_commit
        result["message"] = f"PR #{pr_number} merged: {title} ({merge_commit[:8]})"
        json_handler.log_operation(
            "merge_pr",
            {
                "caller": caller,
                "pr_number": pr_number,
                "title": title,
                "merge_commit": merge_commit,
            },
        )
        logger.info(result["message"])
        return result

    except (OSError, subprocess.SubprocessError) as exc:
        result["message"] = f"Merge workflow error: {exc}"
        logger.error(result["message"])
        return result
