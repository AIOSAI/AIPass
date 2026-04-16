# =================== AIPass ====================
# Name: pr_plugin.py
# Description: System-wide PR creation for devpulse operations
# Version: 2.0.0
# Created: 2026-03-30
# Modified: 2026-03-31
# =============================================

"""System-wide PR creation for devpulse operations.

Creates PRs from local main commits that are ahead of origin/main.
If there are uncommitted tracked changes, commits them first (like a
normal commit), then creates a feature branch at main's current tip,
pushes it, and opens a PR.  Local main is never moved — after squash-
merge and pull, git detects the commits are already applied and skips
them cleanly.

Only authorized callers (verified via :mod:`auth`) may invoke this.
"""

from __future__ import annotations

import re
import subprocess

from aipass.prax import logger
from aipass.drone.apps.handlers.json import json_handler
from aipass.drone.apps.handlers.git.lock_handler import (
    acquire_lock,
    find_repo_root,
    release_lock,
)


def slugify(description: str) -> str:
    """Convert a description into a branch-safe slug.

    Lowercase, spaces to hyphens, strip non-alphanumeric except hyphens,
    collapse multiple hyphens, and truncate to 50 characters.

    Args:
        description: The raw description string.

    Returns:
        A URL/branch-safe slug string.
    """
    slug = description.lower().strip()
    slug = slug.replace(" ", "-")
    slug = re.sub(r"[^a-z0-9-]", "", slug)
    slug = re.sub(r"-{2,}", "-", slug)
    slug = slug.strip("-")
    return slug[:50]


def create_system_pr(description: str, caller: str) -> dict:
    """Execute the system-wide PR creation workflow.

    If there are uncommitted tracked changes, commits them on main first
    (just a normal commit).  Then creates a feature branch at main's tip,
    pushes it, and opens a PR.  Local main is never artificially moved.

    After GitHub squash-merges the PR, ``git pull --rebase`` detects that
    the local commits are already applied and skips them cleanly.

    Args:
        description: Short description for the PR title/commit.
        caller: The verified caller name (e.g. ``"devpulse"``).

    Returns:
        Dict with success, pr_url, feature_branch, and message.
    """
    repo_root = find_repo_root()
    slug = slugify(description)
    feature_branch = f"system/{caller}-{slug}"
    lock_acquired = False

    result: dict = {
        "success": False,
        "pr_url": "",
        "feature_branch": feature_branch,
        "message": "",
    }

    try:
        # Step 1: Check we are on main
        current = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
        )
        if current.stdout.strip() != "main":
            result["message"] = (
                f"Not on main branch (currently on {current.stdout.strip()}). "
                "Checkout main before creating a system PR."
            )
            logger.error(result["message"])
            return result

        # Step 2: Acquire lock
        lock_result = acquire_lock(caller)
        if not lock_result["success"]:
            result["message"] = lock_result["message"]
            return result
        lock_acquired = True

        # Step 3: Sync STATUS.md before staging so the fresh state is committed
        sync_result = subprocess.run(
            ["drone", "@prax", "status", "sync"],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
        )
        if sync_result.returncode != 0:
            logger.warning("create_system_pr: status sync failed (non-fatal): %s", sync_result.stderr.strip())

        # Stage all changes including untracked new files
        subprocess.run(
            ["git", "add", "-A"],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
        )

        # Unstage .git_pr.lock — it is acquired (created) for this workflow
        # and must never be committed. Belt-and-suspenders alongside .gitignore.
        subprocess.run(
            ["git", "reset", "HEAD", ".git_pr.lock"],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
        )

        # Step 4: If anything is staged, commit it (normal commit on main)
        diff_check = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
        )
        if diff_check.returncode != 0:
            # There are staged changes — commit them
            commit_msg = f"feat(system): {description}\n\nCo-Authored-By: @{caller} <{caller}@aipass>"
            commit = subprocess.run(
                ["git", "commit", "-m", commit_msg],
                capture_output=True,
                text=True,
                cwd=str(repo_root),
            )
            if commit.returncode != 0:
                result["message"] = f"Commit failed: {commit.stderr.strip()}"
                logger.error(result["message"])
                return result

        # Step 5: Check if main is ahead of origin/main
        subprocess.run(
            ["git", "fetch", "origin", "main"],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
        )
        ahead_check = subprocess.run(
            ["git", "rev-list", "--count", "origin/main..HEAD"],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
        )
        ahead_count = int(ahead_check.stdout.strip() or "0")
        if ahead_count == 0:
            result["message"] = "Nothing to PR: local main is up to date with origin"
            logger.warning(result["message"])
            return result

        # Step 6: Create feature branch at current main tip
        branch_create = subprocess.run(
            ["git", "branch", "-f", feature_branch],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
        )
        if branch_create.returncode != 0:
            result["message"] = f"Failed to create branch: {branch_create.stderr.strip()}"
            logger.error(result["message"])
            return result

        # Step 7: Push feature branch
        push = subprocess.run(
            ["git", "push", "--force-with-lease", "origin", feature_branch],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
        )
        if push.returncode != 0:
            result["message"] = f"Push failed: {push.stderr.strip()}"
            logger.error(result["message"])
            return result

        # Step 8: Create PR via gh
        pr_body = (
            "## Summary\n\n"
            f"System-wide PR by @{caller}\n\n"
            f"- {description}\n"
            f"- {ahead_count} commit(s) ahead of origin/main\n"
        )
        pr_create = subprocess.run(
            [
                "gh",
                "pr",
                "create",
                "--head",
                feature_branch,
                "--title",
                f"feat(system): {description}",
                "--body",
                pr_body,
            ],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
        )
        if pr_create.returncode != 0:
            result["message"] = f"PR creation failed: {pr_create.stderr.strip()}"
            logger.error(result["message"])
            subprocess.run(
                ["git", "branch", "-D", feature_branch],
                capture_output=True,
                text=True,
                cwd=str(repo_root),
            )
            return result

        pr_url = pr_create.stdout.strip()

        # Step 9: Clean up local feature branch (main stays untouched)
        subprocess.run(
            ["git", "branch", "-D", feature_branch],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
        )

        result["success"] = True
        result["pr_url"] = pr_url
        result["message"] = f"System PR created: {pr_url}"
        json_handler.log_operation(
            "create_system_pr",
            {
                "caller": caller,
                "feature_branch": feature_branch,
                "pr_url": pr_url,
                "commits_ahead": ahead_count,
            },
        )
        logger.info(result["message"])

        # pr_created trigger intentionally skipped — firing it causes prax to
        # re-sync STATUS.md post-commit, creating a perpetual dirty loop.
        # Run `drone @prax status sync` manually if needed after a system-pr.

        return result

    except (OSError, subprocess.SubprocessError) as exc:
        result["message"] = f"System PR workflow error: {exc}"
        logger.error(result["message"])
        return result

    finally:
        if lock_acquired:
            release_lock(force=True)
