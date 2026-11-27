# =================== AIPass ====================
# Name: merge_plugin.py
# Description: Merge a PR into dev or main and sync the branch it lands on
# Version: 1.1.2
# Created: 2026-03-30
# Modified: 2026-11-26
# =============================================

"""Merge a PR into dev or main and sync the branch it lands on.

Merges the PR via ``gh``, pulls, and returns the merge commit hash and PR title.
"""

from __future__ import annotations

import subprocess

from aipass.prax import logger
from aipass.drone.apps.handlers.json import json_handler
from aipass.drone.apps.handlers.git import external_pr_handler
from aipass.drone.apps.handlers.git.lock_handler import find_repo_root
from aipass.drone.apps.handlers.git.repo_context import is_aipass_repo
from aipass.drone.apps.handlers.git.sync_handler import stash_changes


PROTECTED_BRANCHES = ("dev", "main")
# main is the dev->main train; dev is a cloud session's PR. Any other base is refused before the merge.
MERGE_BASES = ("dev", "main")
REFS_JQ = '.baseRefName + " " + .headRefName'
REFUSE_BASE = "PR #{pr} was not merged: its base is {base}, and drone merges only PRs into dev or main."


def _on_dev(repo_root) -> bool:
    """Whether *repo_root*'s checked-out branch is dev; an unreadable answer is not dev."""
    proc = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True, text=True, cwd=str(repo_root)
    )
    return proc.returncode == 0 and proc.stdout.strip() == "dev"


def merge_pr(pr_number: str, caller: str) -> dict:
    """Merge a PR and sync: a main-base PR pulls the checked-out branch, a dev-base PR pulls dev and stays on dev.

    Args:
        pr_number: The PR number to merge (e.g. ``"42"``).
        caller: The verified caller name (e.g. ``"devpulse"``).

    Returns:
        Dict with success, pr_number, title, merge_commit, and message.
    """
    repo_root = find_repo_root()
    if not is_aipass_repo(repo_root):
        return external_pr_handler.merge_pr(repo_root, pr_number, caller)

    result: dict = {
        "success": False,
        "pr_number": pr_number,
        "title": "",
        "merge_commit": "",
        "message": "",
    }

    try:
        refs_proc = subprocess.run(
            ["gh", "pr", "view", pr_number, "--json", "baseRefName,headRefName", "--jq", REFS_JQ],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
        )
        refs = refs_proc.stdout.rstrip() if refs_proc.returncode == 0 else ""
        base_ref, _, head_ref = refs.partition(" ")
        # Read before acting: the base decides what is pulled afterwards, so an unread or foreign base merges nothing.
        if base_ref not in MERGE_BASES:
            result["message"] = REFUSE_BASE.format(pr=pr_number, base=base_ref or "unreadable")
            logger.warning(result["message"])
            return result

        # An unknown head ref (gh lookup failed) never deletes: a protected branch may be behind it.
        merge_cmd = ["gh", "pr", "merge", pr_number, "--merge"]
        if head_ref and head_ref not in PROTECTED_BRANCHES:
            merge_cmd.append("--delete-branch")
        elif not head_ref:
            logger.warning(
                "merge_pr: could not determine PR #%s head ref — skipping --delete-branch (fail-safe)",
                pr_number,
            )

        merge = subprocess.run(
            merge_cmd,
            capture_output=True,
            text=True,
            cwd=str(repo_root),
        )
        if merge.returncode != 0:
            merge_stderr = merge.stderr.strip()
            # A local branch held by a worktree fails gh's cleanup after GitHub already merged.
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

        # Stashed first: git pull --rebase aborts on a dirty working tree.
        stashed, error = stash_changes(repo_root)
        if error:
            result["message"] = f"PR #{pr_number} merged, but local {base_ref} was not pulled: {error}"
            logger.error(result["message"])
            return result

        # A dev-base PR (a cloud session's) lands on dev: dev is pulled onto dev, and main is left as it is.
        if base_ref == "dev" and not _on_dev(repo_root):
            checkout = subprocess.run(["git", "checkout", "dev"], capture_output=True, text=True, cwd=str(repo_root))
            if checkout.returncode != 0:
                if stashed:
                    subprocess.run(["git", "stash", "pop"], capture_output=True, text=True, cwd=str(repo_root))
                reason = checkout.stderr.strip()
                result["message"] = f"PR #{pr_number} merged, but dev could not be checked out: {reason}"
                logger.error(result["message"])
                return result
        pull = subprocess.run(
            ["git", "pull", "--rebase"] + (["origin", "dev"] if base_ref == "dev" else []),
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
                result["message"] = (
                    f"PR #{pr_number} merged and pulled, but stash pop failed — "
                    f"your changes are kept in stash@{{0}}: {pop.stderr.strip()}"
                )
                logger.error(result["message"])
                return result

        rev = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
        )
        merge_commit = rev.stdout.strip() if rev.returncode == 0 else "unknown"

        title_proc = subprocess.run(
            ["gh", "pr", "view", pr_number, "--json", "title", "--jq", ".title"],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
        )
        title = title_proc.stdout.strip() if title_proc.returncode == 0 else "unknown"

        current_branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
        )
        on_branch = current_branch.stdout.strip() if current_branch.returncode == 0 else ""
        if on_branch != "dev":
            checkout_dev = subprocess.run(
                ["git", "checkout", "dev"],
                capture_output=True,
                text=True,
                cwd=str(repo_root),
            )
            if checkout_dev.returncode != 0:
                logger.warning(
                    "merge_pr: WARNING — could not return to dev (on '%s'). Next commit may land on wrong branch!",
                    on_branch,
                )

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
            from aipass.trigger import trigger

            trigger.fire("pr_merged", pr_number=pr_number, title=title)
        except Exception as exc:
            logger.warning("trigger.fire('pr_merged') failed: %s", exc)

        return result

    except (OSError, subprocess.SubprocessError) as exc:
        result["message"] = f"Merge workflow error: {exc}"
        logger.error(result["message"])
        return result
