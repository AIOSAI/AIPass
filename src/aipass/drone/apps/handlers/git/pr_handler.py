# =================== AIPass ====================
# Name: pr_handler.py
# Description: Full PR workflow with atomic lockfile
# Version: 1.1.0
# Created: 2026-03-17
# Modified: 2026-09-15
# =============================================

"""
Full PR workflow with atomic lockfile.

Orchestrates the complete PR creation lifecycle: lock acquisition,
branch creation, scoped staging, commit, push, PR creation via gh,
and cleanup (checkout main + release lock) in a finally block.
"""

from __future__ import annotations

import json as _json
import re
import subprocess
from pathlib import Path

from aipass.prax import logger
from aipass.drone.apps.handlers.json import json_handler
from aipass.drone.apps.handlers.git.lock_handler import (
    acquire_lock,
    find_repo_root,
    release_lock,
)
from aipass.drone.apps.handlers.git.commit_handler import (
    commit_subject,
    stage_branch_dir,
    subject_refusal,
)


def _has_credential_helper() -> bool:
    """Check whether git has a credential.helper configured at any level."""
    try:
        r = subprocess.run(
            ["git", "config", "--get-all", "credential.helper"],
            capture_output=True,
            text=True,
        )
        return r.returncode == 0 and bool(r.stdout.strip())
    except OSError as exc:
        logger.warning("credential helper check failed: %s", exc)
        return False


def _diagnose_push_failure(stderr: str, branch: str) -> str:
    """Produce an actionable error message for a failed git push.

    Distinguishes between:
    - No credential helper (most common on fresh setups)
    - Expired or invalid token
    - Actual permission / fork issues
    """
    lower = stderr.lower()
    auth_indicators = ["403", "could not read username", "terminal prompts disabled"]
    permission_indicators = ["permission", "denied"]

    if not _has_credential_helper():
        return (
            "Push failed: no git credential helper configured.\n"
            "  git cannot obtain auth tokens for push.\n"
            "  Fix: gh auth setup-git\n"
            '  Then retry: drone @git pr "<description>"'
        )

    if any(ind in lower for ind in auth_indicators):
        return (
            "Push failed: authentication error (token may be expired or invalid).\n"
            f"  stderr: {stderr}\n"
            "  Check: gh auth status\n"
            "  Fix:   gh auth login"
        )

    if any(ind in lower for ind in permission_indicators):
        return (
            f"Push failed: permission denied for branch '{branch}'.\n"
            f"  stderr: {stderr}\n"
            "  Check repo write access: gh api repos/:owner/:repo --jq '.permissions'"
        )

    return f"Push failed: {stderr}"


def _slugify(description: str) -> str:
    """Convert description to a branch-safe slug."""
    slug = description.lower().strip().replace(" ", "-")
    slug = re.sub(r"[^a-z0-9-]", "", slug)
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    return slug[:50]


def _resolve_git_branch(branch_name: str, branch_dir: Path, slug: str = "") -> str:
    """Read git_branch from passport as prefix, append slug for uniqueness."""
    passport_path = branch_dir / ".trinity" / "passport.json"
    if passport_path.is_file():
        try:
            data = _json.loads(passport_path.read_text())
            git_branch = data.get("branch_info", {}).get("git_branch", "")
            if git_branch:
                return f"{git_branch}-{slug}" if slug else git_branch
        except (ValueError, OSError) as exc:
            logger.warning("Failed to read git_branch from passport %s: %s", passport_path, exc)
    return f"citizen/{branch_name}-{slug}" if slug else f"citizen/{branch_name}"


def create_pr(branch_name: str, description: str, branch_dir: Path) -> dict:
    """Execute the full PR creation workflow.

    Changes are committed on main locally first, so they never disappear
    from the working tree. A feature branch is created as a pointer to
    the same commit (without checkout) and pushed for GitHub's PR system.

    Steps:
        0. Refuse an over-cap subject (before the lock — see below)
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
    slug = _slugify(description)
    feature_branch = _resolve_git_branch(branch_name, branch_dir, slug)
    lock_acquired = False

    result = {
        "success": False,
        "pr_url": "",
        "feature_branch": feature_branch,
        "message": "",
    }

    # Step 0: the message this workflow will commit, composed once and measured
    # BEFORE the lock. A PR commit lands in the same oneline log as any other,
    # so it obeys the same subject cap — and a refusal that has taken the
    # repo-wide PR lock blocks every other citizen while it teaches.
    commit_msg = f"feat({branch_name}): {description}\n\nCo-Authored-By: @{branch_name} <{branch_name}@aipass>"
    refusal = subject_refusal(commit_msg)
    if refusal is not None:
        result["message"] = refusal
        logger.error("PR refused: commit subject over the cap (%s chars)", len(commit_subject(commit_msg)))
        return result

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
        stage_result = stage_branch_dir(branch_dir, repo_root)
        if not stage_result["success"]:
            result["message"] = stage_result["message"]
            logger.error(result["message"])
            return result
        rel_dir = stage_result["rel_dir"]

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

        # Step 7: Push feature branch
        push = subprocess.run(
            ["git", "push", "-u", "origin", feature_branch],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
        )
        if push.returncode != 0:
            result["message"] = _diagnose_push_failure(push.stderr.strip(), feature_branch)
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
            # Check if PR already exists for this branch
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
                logger.info("Existing PR found: %s", pr_url)
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
