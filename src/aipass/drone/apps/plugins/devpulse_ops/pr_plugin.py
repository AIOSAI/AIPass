# =================== AIPass ====================
# Name: pr_plugin.py
# Description: System-wide PR creation for devpulse operations
# Version: 1.0.0
# Created: 2026-03-30
# Modified: 2026-03-30
# =============================================

"""System-wide PR creation for devpulse operations.

Creates PRs that stage ALL tracked changes (``git add -u``) rather than
scoping to a single branch directory.  Only authorized callers (verified
via :mod:`auth`) may invoke this workflow.
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

    Stages all tracked changes (``git add -u``), commits on main locally,
    creates a disposable feature branch, pushes it, opens a PR via ``gh``,
    and cleans up the local branch.

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
            capture_output=True, text=True, cwd=str(repo_root),
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

        # Step 3: Stage all tracked changes
        add_result = subprocess.run(
            ["git", "add", "-u"],
            capture_output=True, text=True, cwd=str(repo_root),
        )
        if add_result.returncode != 0:
            result["message"] = f"Failed to stage files: {add_result.stderr.strip()}"
            logger.error(result["message"])
            return result

        # Step 4: Check if anything was staged
        diff_check = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            capture_output=True, text=True, cwd=str(repo_root),
        )
        if diff_check.returncode == 0:
            result["message"] = "Nothing to commit: no tracked changes staged"
            logger.warning(result["message"])
            return result

        # Step 5: Commit on main (local only)
        commit_msg = (
            f"feat(system): {description}\n\n"
            f"Co-Authored-By: @{caller} <{caller}@aipass>"
        )
        commit = subprocess.run(
            ["git", "commit", "-m", commit_msg],
            capture_output=True, text=True, cwd=str(repo_root),
        )
        if commit.returncode != 0:
            result["message"] = f"Commit failed: {commit.stderr.strip()}"
            logger.error(result["message"])
            return result

        # Step 6: Create feature branch pointing to same commit
        branch_create = subprocess.run(
            ["git", "branch", "-f", feature_branch],
            capture_output=True, text=True, cwd=str(repo_root),
        )
        if branch_create.returncode != 0:
            result["message"] = f"Failed to create branch: {branch_create.stderr.strip()}"
            logger.error(result["message"])
            return result

        # Step 7: Push feature branch
        push = subprocess.run(
            ["git", "push", "--force-with-lease", "origin", feature_branch],
            capture_output=True, text=True, cwd=str(repo_root),
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
        )
        pr_create = subprocess.run(
            [
                "gh", "pr", "create",
                "--head", feature_branch,
                "--title", f"feat(system): {description}",
                "--body", pr_body,
            ],
            capture_output=True, text=True, cwd=str(repo_root),
        )
        if pr_create.returncode != 0:
            result["message"] = f"PR creation failed: {pr_create.stderr.strip()}"
            logger.error(result["message"])
            # Clean up local feature branch before returning
            subprocess.run(
                ["git", "branch", "-D", feature_branch],
                capture_output=True, text=True, cwd=str(repo_root),
            )
            return result

        pr_url = pr_create.stdout.strip()

        # Step 9: Clean up local feature branch
        subprocess.run(
            ["git", "branch", "-D", feature_branch],
            capture_output=True, text=True, cwd=str(repo_root),
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
            },
        )
        logger.info(result["message"])
        return result

    except (OSError, subprocess.SubprocessError) as exc:
        result["message"] = f"System PR workflow error: {exc}"
        logger.error(result["message"])
        return result

    finally:
        if lock_acquired:
            release_lock(force=True)
