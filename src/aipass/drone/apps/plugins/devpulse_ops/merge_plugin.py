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
            capture_output=True,
            text=True,
            cwd=str(repo_root),
        )
        if merge.returncode != 0:
            merge_stderr = merge.stderr.strip()
            # gh pr merge --delete-branch fails with non-zero if the local branch
            # can't be deleted (e.g. checked out in a worktree). The GitHub-side
            # merge + remote branch deletion already completed — only local
            # cleanup failed. Treat this as a warning and continue.
            if "cannot delete branch" in merge_stderr and "worktree" in merge_stderr:
                logger.warning(
                    "merge_pr: PR #%s merged but local branch cleanup skipped (branch in use by worktree): %s",
                    pr_number,
                    merge_stderr,
                )
            else:
                result["message"] = f"Merge failed: {merge_stderr}"
                logger.error(result["message"])
                return result

        # Step 2: Sync local main — stash any unstaged changes first so
        # git pull --rebase doesn't abort on a dirty working tree.
        stash = subprocess.run(
            ["git", "stash"],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
        )
        stashed = "No local changes to save" not in stash.stdout

        pull = subprocess.run(
            ["git", "pull", "--rebase"],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
        )
        if pull.returncode != 0:
            if stashed:
                subprocess.run(
                    ["git", "stash", "pop"],
                    capture_output=True,
                    text=True,
                    cwd=str(repo_root),
                )
            result["message"] = f"Pull after merge failed: {pull.stderr.strip()}"
            logger.error(result["message"])
            return result

        if stashed:
            pop = subprocess.run(
                ["git", "stash", "pop"],
                capture_output=True,
                text=True,
                cwd=str(repo_root),
            )
            if pop.returncode != 0:
                logger.warning(
                    "merge_pr: stash pop after pull failed (manual restore may be needed): %s",
                    pop.stderr.strip(),
                )

        # Step 3: Get the merge commit hash
        rev = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
        )
        merge_commit = rev.stdout.strip() if rev.returncode == 0 else "unknown"

        # Step 4: Get the PR title
        title_proc = subprocess.run(
            ["gh", "pr", "view", pr_number, "--json", "title", "--jq", ".title"],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
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

        # Fire pr_merged event (non-blocking — never fail the merge workflow)
        try:
            from aipass.trigger.apps.modules.core import trigger

            trigger.fire("pr_merged", pr_number=pr_number, title=title)
        except Exception as exc:
            logger.warning("trigger.fire('pr_merged') failed: %s", exc)

        return result

    except (OSError, subprocess.SubprocessError) as exc:
        result["message"] = f"Merge workflow error: {exc}"
        logger.error(result["message"])
        return result
