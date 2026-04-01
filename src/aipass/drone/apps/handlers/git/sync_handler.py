# =================== AIPass ====================
# Name: sync_handler.py
# Description: Safe main branch synchronization
# Version: 1.0.0
# Created: 2026-03-17
# Modified: 2026-03-17
# =============================================

"""
Safe main branch synchronization.

Checks out main and pulls latest, with error handling for dirty
working trees and other common failure modes.
"""

from __future__ import annotations

import subprocess

from aipass.prax import logger
from aipass.drone.apps.handlers.json import json_handler
from aipass.drone.apps.handlers.git.lock_handler import find_repo_root


def sync_main() -> dict:
    """Checkout main and pull latest changes.

    Returns:
        Dict with success (bool), message (str), and stdout (str).
    """
    repo_root = find_repo_root()

    try:
        result = subprocess.run(
            ["git", "checkout", "main"],
            capture_output=True, text=True, cwd=str(repo_root),
        )
        if result.returncode != 0:
            msg = f"Failed to checkout main: {result.stderr.strip()}"
            logger.error(msg)
            return {"success": False, "message": msg, "stdout": result.stdout}

        result = subprocess.run(
            ["git", "pull", "--rebase"],
            capture_output=True, text=True, cwd=str(repo_root),
        )
        if result.returncode != 0:
            msg = f"Failed to pull: {result.stderr.strip()}"
            logger.error(msg)
            return {"success": False, "message": msg, "stdout": result.stdout}

        stdout = result.stdout.strip()
        msg = f"Synced main: {stdout}"
        json_handler.log_operation("sync_main", {"result": stdout})
        logger.info(msg)
        return {"success": True, "message": msg, "stdout": stdout}

    except (OSError, subprocess.SubprocessError) as exc:
        msg = f"Sync failed: {exc}"
        logger.error(msg)
        return {"success": False, "message": msg, "stdout": ""}
