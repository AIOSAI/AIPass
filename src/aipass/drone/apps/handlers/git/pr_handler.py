# =================== AIPass ====================
# Name: pr_handler.py
# Description: Full PR workflow with atomic lockfile
# Version: 1.0.0
# Created: 2026-03-17
# Modified: 2026-03-17
# =============================================

"""
Full PR workflow with atomic lockfile.

Orchestrates the complete PR creation lifecycle: lock acquisition,
branch creation, scoped staging, commit, push, PR creation via gh,
and cleanup (checkout main + release lock) in a finally block.
"""

from __future__ import annotations

import json as _json
import subprocess
from pathlib import Path

from aipass.prax import logger
from aipass.drone.apps.handlers.json import json_handler
from aipass.drone.apps.handlers.git.lock_handler import (
    acquire_lock,
    find_repo_root,
    release_lock,
)


def create_pr(branch_name: str, description: str, branch_dir: Path) -> dict:
    """Execute the full PR creation workflow.

    Changes are committed on main locally first, so they never disappear
    from the working tree. A feature branch is created as a pointer to
    the same commit (without checkout) and pushed for GitHub's PR system.

    Steps:
        1. Verify we are on main
        2. Acquire lock
        3. Stage only files under branch_dir (on main)
        4. Check if anything staged
        5. Commit on main (local only — not pushed to origin/main)
        6. Create feature branch pointing to same commit (no checkout)
        7. Push feature branch to origin
        8. Create PR via gh
        9. Delete local feature branch (remote copy is what matters)
        10. Release lock

    Args:
        branch_name: The calling branch name (e.g. "api").
        description: Short description for the PR.
        branch_dir: Absolute path to the caller's branch directory.

    Returns:
        Dict with success, pr_url, feature_branch, and message.
    """
    repo_root = find_repo_root()
    feature_branch = f"citizen/{branch_name}"
    lock_acquired = False

    result = {
        "success": False,
        "pr_url": "",
        "feature_branch": feature_branch,
        "message": "",
    }

    try:
        # Step 1: Check we're on main
        current = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
        )
        if current.stdout.strip() != "main":
            result["message"] = (
                f"Not on main branch (currently on {current.stdout.strip()}). Checkout main before creating a PR."
            )
            logger.error(result["message"])
            return result

        # Step 2: Acquire lock
        lock_result = acquire_lock(branch_name)
        if not lock_result["success"]:
            result["message"] = lock_result["message"]
            return result
        lock_acquired = True

        # Step 3: Stage only files under branch_dir (on main)
        try:
            rel_dir = branch_dir.resolve().relative_to(repo_root.resolve())
        except ValueError:
            logger.warning(
                "create_pr: branch_dir %s not relative to repo root %s, using absolute", branch_dir, repo_root
            )
            rel_dir = branch_dir

        add_result = subprocess.run(
            ["git", "add", str(rel_dir) + "/"],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
        )
        if add_result.returncode != 0:
            result["message"] = f"Failed to stage files: {add_result.stderr.strip()}"
            logger.error(result["message"])
            return result

        # Step 4: Check if anything was staged
        diff_check = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
        )
        if diff_check.returncode == 0:
            result["message"] = "Nothing to commit: no changes staged under branch directory"
            logger.warning(result["message"])
            return result

        # Step 5: Commit on main (changes stay local)
        # Pathspec ('-- rel_dir/') scopes the commit to branch_dir only,
        # preventing pre-staged files from other concurrent PRs from being
        # swept in. The staging step already scoped git add, but another
        # drone @git pr could stage its own files into the shared index
        # between our add and our commit.
        commit_msg = f"feat({branch_name}): {description}\n\nCo-Authored-By: @{branch_name} <{branch_name}@aipass>"
        commit = subprocess.run(
            ["git", "commit", "-m", commit_msg, "--", str(rel_dir) + "/"],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
        )
        if commit.returncode != 0:
            result["message"] = f"Commit failed: {commit.stderr.strip()}"
            logger.error(result["message"])
            return result

        # Step 6: Create/update feature branch pointing to same commit (no checkout)
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

        # Step 7: Push feature branch (force-with-lease for persistent citizen branches)
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
        pr_body = f"## Summary\n\n- {description}\n\n## Branch\n\nCreated by @{branch_name} via `drone @git pr`\n"
        pr_create = subprocess.run(
            [
                "gh",
                "pr",
                "create",
                "--head",
                feature_branch,
                "--title",
                f"feat({branch_name}): {description}",
                "--body",
                pr_body,
            ],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
        )
        if pr_create.returncode != 0:
            # Check if PR already exists — force-push already updated it
            existing = subprocess.run(
                ["gh", "pr", "list", "--head", feature_branch, "--json", "url", "--limit", "1"],
                capture_output=True,
                text=True,
                cwd=str(repo_root),
            )
            try:
                existing_prs = _json.loads(existing.stdout)
            except (ValueError, TypeError) as exc:
                logger.warning("Failed to parse existing PR list: %s", exc)
                existing_prs = []
            if existing_prs:
                pr_url = existing_prs[0]["url"]
                logger.info("Existing PR updated via force-push: %s", pr_url)
            else:
                result["message"] = f"PR creation failed: {pr_create.stderr.strip()}"
                logger.error(result["message"])
                # Clean up local feature branch before returning
                subprocess.run(
                    ["git", "branch", "-D", feature_branch],
                    capture_output=True,
                    text=True,
                    cwd=str(repo_root),
                )
                return result
        else:
            pr_url = pr_create.stdout.strip()

        # Step 9: Clean up local feature branch (remote copy is what matters)
        subprocess.run(
            ["git", "branch", "-D", feature_branch],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
        )

        result["success"] = True
        result["pr_url"] = pr_url
        result["message"] = f"PR created: {pr_url}"
        json_handler.log_operation(
            "create_pr",
            {"branch": branch_name, "feature_branch": feature_branch, "pr_url": pr_url},
        )
        logger.info(result["message"])

        # Fire pr_created event (non-blocking — never fail the PR workflow)
        try:
            from aipass.trigger.apps.modules.core import trigger

            trigger.fire("pr_created", branch=branch_name, pr_url=pr_url)
        except Exception as exc:
            logger.warning("trigger.fire('pr_created') failed: %s", exc)

        return result

    except (OSError, subprocess.SubprocessError) as exc:
        result["message"] = f"PR workflow error: {exc}"
        logger.error(result["message"])
        return result

    finally:
        # Always release lock — no checkout needed, we never left main
        if lock_acquired:
            release_lock(force=True)
