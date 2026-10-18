# =================== AIPass ====================
# Name: dev_pr_handler.py
# Description: Dev branch PR handler — push dev and create PR to main
# Version: 1.1.1
# Created: 2026-05-12
# Modified: 2026-10-17
# =============================================

"""Branch PR handlers — generic and dev-specific."""

from __future__ import annotations

import re
import subprocess

from aipass.prax import logger
from aipass.drone.apps.handlers.json import json_handler
from aipass.drone.apps.handlers.git import external_pr_handler
from aipass.drone.apps.handlers.git.lock_handler import find_repo_root
from aipass.drone.apps.handlers.git.repo_context import is_aipass_repo


# gh prints the open PR's URL in its refusal; only a whole GitHub PR URL counts, not any line naming the host.
_PR_URL = re.compile(r"https://github\.com/[\w.-]+/[\w.-]+/pull/\d+")


def _slugify(text: str) -> str:
    """Convert text to a branch-safe slug."""
    slug = text.lower().strip().replace(" ", "-")
    slug = re.sub(r"[^a-z0-9-]", "", slug)
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    return slug[:40]


def create_branch_pr(description: str, target_branch: str = "main") -> dict:
    """Push current branch and create a PR to target.

    Works from any branch. Detects HEAD, pushes to origin, creates PR via gh CLI.

    Returns:
        Dict with success, message, and pr_url keys.
    """
    repo_root = find_repo_root()

    try:
        head = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.error("Failed to detect current branch: %s", exc)
        return {"success": False, "message": f"Failed to detect current branch: {exc}", "pr_url": ""}

    pr_branch = head.stdout.strip()

    if pr_branch == target_branch:
        pr_branch = _slugify(description)
        if not pr_branch:
            return {"success": False, "message": "Description required to generate branch name.", "pr_url": ""}
        push_refspec = f"{target_branch}:{pr_branch}"
    else:
        push_refspec = pr_branch

    try:
        push = subprocess.run(
            ["git", "push", "origin", push_refspec],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.error("git push failed: %s", exc)
        return {"success": False, "message": f"Push failed: {exc}", "pr_url": ""}

    if push.returncode != 0:
        return {"success": False, "message": f"Push failed: {push.stderr.strip()}", "pr_url": ""}

    try:
        pr = subprocess.run(
            ["gh", "pr", "create", "--head", pr_branch, "--base", target_branch, "--title", description, "--body", ""],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
        )
    except FileNotFoundError as exc:
        logger.warning("gh CLI not found: %s", exc)
        return {"success": False, "message": "gh CLI not found. Install: https://cli.github.com/", "pr_url": ""}
    except (OSError, subprocess.SubprocessError) as exc:
        logger.error("gh pr create failed: %s", exc)
        return {"success": False, "message": f"PR creation failed: {exc}", "pr_url": ""}

    if pr.returncode != 0:
        stderr = pr.stderr.strip()
        if "already exists" in stderr:
            existing_url = ""
            for line in stderr.splitlines():
                found = _PR_URL.search(line)
                if found:
                    existing_url = found.group(0)
                    break
            msg = (
                f"Pushed to {pr_branch}. PR already open: {existing_url}"
                if existing_url
                else f"Pushed to {pr_branch}. PR already open."
            )
            json_handler.log_operation(
                "branch_pr_push_existing", {"pr_url": existing_url, "branch": pr_branch, "description": description}
            )
            return {"success": True, "message": msg, "pr_url": existing_url}
        return {"success": False, "message": f"PR creation failed: {stderr}", "pr_url": ""}

    pr_url = pr.stdout.strip()
    json_handler.log_operation(
        "create_branch_pr", {"pr_url": pr_url, "branch": pr_branch, "target": target_branch, "description": description}
    )
    logger.info("PR created from %s: %s", pr_branch, pr_url)

    return {"success": True, "message": f"PR created: {pr_url}", "pr_url": pr_url}


def create_dev_pr(description: str) -> dict:
    """Push dev branch and create a PR to main.

    Verifies HEAD is on dev, pushes to origin, then creates a PR via gh CLI.
    An external project's repo takes its own lane, aimed at its own GitHub slug.

    Returns:
        Dict with success, message, and pr_url keys.
    """
    repo_root = find_repo_root()
    if not is_aipass_repo(repo_root):
        return external_pr_handler.create_dev_pr(repo_root, description)

    try:
        head = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.error("Failed to detect current branch: %s", exc)
        return {"success": False, "message": f"Failed to detect current branch: {exc}", "pr_url": ""}

    current_branch = head.stdout.strip()
    if current_branch != "dev":
        return {
            "success": False,
            "message": f"Not on dev branch (current: {current_branch}). Switch to dev first.",
            "pr_url": "",
        }

    try:
        push = subprocess.run(
            ["git", "push", "origin", "dev"],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.error("git push origin dev failed: %s", exc)
        return {"success": False, "message": f"Push failed: {exc}", "pr_url": ""}

    if push.returncode != 0:
        return {"success": False, "message": f"Push failed: {push.stderr.strip()}", "pr_url": ""}

    try:
        pr = subprocess.run(
            ["gh", "pr", "create", "--head", "dev", "--base", "main", "--title", description, "--body", ""],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
        )
    except FileNotFoundError as exc:
        logger.warning("gh CLI not found: %s", exc)
        return {"success": False, "message": "gh CLI not found. Install: https://cli.github.com/", "pr_url": ""}
    except (OSError, subprocess.SubprocessError) as exc:
        logger.error("gh pr create failed: %s", exc)
        return {"success": False, "message": f"PR creation failed: {exc}", "pr_url": ""}

    if pr.returncode != 0:
        stderr = pr.stderr.strip()
        if "already exists" in stderr:
            existing_url = ""
            for line in stderr.splitlines():
                found = _PR_URL.search(line)
                if found:
                    existing_url = found.group(0)
                    break
            msg = (
                f"Pushed to dev. PR already open: {existing_url}" if existing_url else "Pushed to dev. PR already open."
            )
            json_handler.log_operation("dev_pr_push_existing", {"pr_url": existing_url, "description": description})
            return {"success": True, "message": msg, "pr_url": existing_url}
        return {"success": False, "message": f"PR creation failed: {stderr}", "pr_url": ""}

    pr_url = pr.stdout.strip()
    json_handler.log_operation("create_dev_pr", {"pr_url": pr_url, "description": description})
    logger.info("Dev PR created: %s", pr_url)

    return {"success": True, "message": f"PR created: {pr_url}", "pr_url": pr_url}
