# =================== AIPass ====================
# Name: sync_plugin.py
# Description: Smart sync — fetch, detect divergence, rebase if needed
# Version: 1.0.0
# Created: 2026-03-30
# Modified: 2026-03-30
# =============================================

"""Smart sync — fetch, detect divergence, rebase if needed.

Fetches the latest remote state, checks whether local main has diverged
from ``origin/main``, and rebases if behind.  Aborts cleanly on conflict.
Only authorized callers (verified via :mod:`auth`) may invoke this.
"""

from __future__ import annotations

import subprocess

from aipass.prax import logger
from aipass.drone.apps.handlers.json import json_handler
from aipass.drone.apps.handlers.git.lock_handler import find_repo_root


def smart_sync(caller: str) -> dict:
    """Fetch origin and rebase local main if behind.

    Args:
        caller: The verified caller name (e.g. ``"devpulse"``).

    Returns:
        Dict with success, ahead, behind, rebased, and message.
    """
    repo_root = find_repo_root()

    result: dict = {
        "success": False,
        "ahead": 0,
        "behind": 0,
        "rebased": False,
        "message": "",
    }

    try:
        # Step 1: Fetch origin
        fetch = subprocess.run(
            ["git", "fetch", "origin"],
            capture_output=True, text=True, cwd=str(repo_root),
        )
        if fetch.returncode != 0:
            result["message"] = f"Fetch failed: {fetch.stderr.strip()}"
            logger.error(result["message"])
            return result

        # Step 2: Check divergence
        rev_list = subprocess.run(
            ["git", "rev-list", "--left-right", "--count", "main...origin/main"],
            capture_output=True, text=True, cwd=str(repo_root),
        )
        if rev_list.returncode != 0:
            result["message"] = f"Divergence check failed: {rev_list.stderr.strip()}"
            logger.error(result["message"])
            return result

        parts = rev_list.stdout.strip().split()
        ahead = int(parts[0]) if len(parts) >= 1 else 0
        behind = int(parts[1]) if len(parts) >= 2 else 0
        result["ahead"] = ahead
        result["behind"] = behind

        # Step 3: Rebase if behind
        if behind > 0:
            rebase = subprocess.run(
                ["git", "rebase", "origin/main"],
                capture_output=True, text=True, cwd=str(repo_root),
            )
            if rebase.returncode != 0:
                # Conflict — abort rebase
                subprocess.run(
                    ["git", "rebase", "--abort"],
                    capture_output=True, text=True, cwd=str(repo_root),
                )
                result["message"] = (
                    f"Rebase conflict (ahead={ahead}, behind={behind}). "
                    "Rebase aborted. Manual resolution required."
                )
                logger.error(result["message"])
                return result

            result["rebased"] = True
            result["success"] = True
            result["message"] = (
                f"Rebased onto origin/main (was {behind} behind, {ahead} ahead)"
            )
        else:
            result["success"] = True
            result["message"] = "Already up to date"

        json_handler.log_operation(
            "smart_sync",
            {
                "caller": caller,
                "ahead": ahead,
                "behind": behind,
                "rebased": result["rebased"],
            },
        )
        logger.info(result["message"])
        return result

    except (OSError, subprocess.SubprocessError) as exc:
        result["message"] = f"Smart sync error: {exc}"
        logger.error(result["message"])
        return result
