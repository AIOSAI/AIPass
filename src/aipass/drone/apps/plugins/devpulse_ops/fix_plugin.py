# =================== AIPass ====================
# Name: fix_plugin.py
# Description: Detect and fix common broken git states
# Version: 1.0.0
# Created: 2026-03-30
# Modified: 2026-03-30
# =============================================

"""Detect and fix common broken git states.

Runs a sequence of checks for stuck rebases, detached HEAD, diverged
branches, and dirty index, applying automatic fixes where safe.
Only authorized callers (verified via :mod:`auth`) may invoke this.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from aipass.prax import logger
from aipass.drone.apps.handlers.json import json_handler
from aipass.drone.apps.handlers.git.lock_handler import find_repo_root


def _fix_divergence(repo_root: Path, actions: list[str]) -> None:
    """Fetch origin and merge if local main has diverged."""
    fetch = subprocess.run(
        ["git", "fetch", "origin"],
        capture_output=True,
        text=True,
        cwd=str(repo_root),
    )
    if fetch.returncode != 0:
        actions.append(f"Fetch failed: {fetch.stderr.strip()}")
        logger.error("fix_git_state: fetch failed: %s", fetch.stderr.strip())
        return

    rev_list = subprocess.run(
        ["git", "rev-list", "--left-right", "--count", "main...origin/main"],
        capture_output=True,
        text=True,
        cwd=str(repo_root),
    )
    if rev_list.returncode != 0:
        return

    parts = rev_list.stdout.strip().split()
    ahead = int(parts[0]) if len(parts) >= 1 else 0
    behind = int(parts[1]) if len(parts) >= 2 else 0
    if ahead == 0 or behind == 0:
        return

    merge = subprocess.run(
        ["git", "merge", "origin/main", "--no-edit"],
        capture_output=True,
        text=True,
        cwd=str(repo_root),
    )
    if merge.returncode == 0:
        actions.append(f"Merged origin/main (was ahead={ahead}, behind={behind})")
        logger.info("fix_git_state: merged origin/main ahead=%d behind=%d", ahead, behind)
        return

    # Merge failed — report conflict files and abort
    diff = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=U"],
        capture_output=True,
        text=True,
        cwd=str(repo_root),
    )
    conflict_files = diff.stdout.strip().splitlines() if diff.stdout.strip() else []
    subprocess.run(
        ["git", "merge", "--abort"],
        capture_output=True,
        text=True,
        cwd=str(repo_root),
    )
    if conflict_files:
        actions.append(
            f"Merge conflict (ahead={ahead}, behind={behind}). Conflicting files: {', '.join(conflict_files)}"
        )
    else:
        actions.append(f"Merge failed (ahead={ahead}, behind={behind}): {merge.stderr.strip()}")
    logger.warning("fix_git_state: merge conflict ahead=%d behind=%d", ahead, behind)


def fix_git_state(caller: str) -> dict:
    """Detect and fix common broken git states.

    Checks are run in sequence; multiple fixes can happen in one call.

    Args:
        caller: The verified caller name (e.g. ``"devpulse"``).

    Returns:
        Dict with success, actions_taken (list[str]), and message.
    """
    repo_root = find_repo_root()
    git_dir = repo_root / ".git"
    actions: list[str] = []

    result: dict = {
        "success": False,
        "actions_taken": actions,
        "message": "",
    }

    try:
        # Check 1: Stuck in rebase
        rebase_merge = git_dir / "rebase-merge"
        rebase_apply = git_dir / "rebase-apply"
        if rebase_merge.exists() or rebase_apply.exists():
            abort = subprocess.run(
                ["git", "rebase", "--abort"],
                capture_output=True,
                text=True,
                cwd=str(repo_root),
            )
            if abort.returncode == 0:
                actions.append("Aborted stuck rebase")
                logger.info("fix_git_state: aborted stuck rebase")
            else:
                actions.append(f"Failed to abort rebase: {abort.stderr.strip()}")
                logger.error("fix_git_state: rebase abort failed: %s", abort.stderr.strip())

        # Check 2: Detached HEAD
        sym_ref = subprocess.run(
            ["git", "symbolic-ref", "-q", "HEAD"],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
        )
        if sym_ref.returncode != 0:
            checkout = subprocess.run(
                ["git", "checkout", "main"],
                capture_output=True,
                text=True,
                cwd=str(repo_root),
            )
            if checkout.returncode == 0:
                actions.append("Checked out main (was detached HEAD)")
                logger.info("fix_git_state: checked out main from detached HEAD")
            else:
                actions.append(f"Failed to checkout main: {checkout.stderr.strip()}")
                logger.error("fix_git_state: checkout main failed: %s", checkout.stderr.strip())

        # Check 3: Diverged from origin — fetch + merge
        _fix_divergence(repo_root, actions)

        # Check 4: Dirty index with no intent
        cached = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
        )
        if cached.returncode == 0 and cached.stdout.strip():
            staged_files = cached.stdout.strip().splitlines()
            reset = subprocess.run(
                ["git", "reset", "HEAD"],
                capture_output=True,
                text=True,
                cwd=str(repo_root),
            )
            if reset.returncode == 0:
                actions.append(f"Unstaged {len(staged_files)} file(s) from index")
                logger.info("fix_git_state: unstaged %d files", len(staged_files))
            else:
                actions.append(f"Failed to reset index: {reset.stderr.strip()}")
                logger.error("fix_git_state: reset failed: %s", reset.stderr.strip())

        result["success"] = True
        if actions:
            result["message"] = f"Fixed {len(actions)} issue(s): {'; '.join(actions)}"
        else:
            result["message"] = "Git state is clean — nothing to fix"

        json_handler.log_operation(
            "fix_git_state",
            {
                "caller": caller,
                "actions_taken": actions,
            },
        )
        logger.info(result["message"])
        return result

    except (OSError, subprocess.SubprocessError) as exc:
        result["message"] = f"Fix git state error: {exc}"
        logger.error(result["message"])
        return result
