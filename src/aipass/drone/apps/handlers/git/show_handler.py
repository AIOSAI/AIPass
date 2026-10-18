# =================== AIPass ====================
# Name: show_handler.py
# Description: Git show handler — read repository history at a commit
# Version: 1.0.0
# Created: 2026-08-13
# Modified: 2026-10-17
# =============================================

"""Git show handler — read repository history at a commit.

Global read tier and NOT branch-scoped like status/diff/log: its use is auditing another's history.
"""

from __future__ import annotations

import subprocess

from aipass.prax import logger
from aipass.drone.apps.handlers.json import json_handler
from aipass.drone.apps.handlers.git.lock_handler import find_repo_root


def _rejects_as_flag(token: str) -> bool:
    """True if git would read this token as an option (a smuggled flag turns a read verb into a write)."""
    return not token or token.startswith("-")


def show_object(ref: str, path: str | None = None) -> dict:
    """Show a commit, or with repo-relative *path* the file's contents at that commit."""
    if _rejects_as_flag(ref):
        msg = f"Refusing ref that git would read as a flag: {ref!r}"
        logger.warning(msg)
        return {"success": False, "content": "", "message": msg}

    if path is not None and _rejects_as_flag(path):
        msg = f"Refusing path that git would read as a flag: {path!r}"
        logger.warning(msg)
        return {"success": False, "content": "", "message": msg}

    target = f"{ref}:{path}" if path else ref
    repo_root = find_repo_root()

    try:
        result = subprocess.run(
            ["git", "show", target],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.error("git show failed: %s", exc)
        return {"success": False, "content": "", "message": f"git show failed: {exc}"}

    if result.returncode != 0:
        stderr = result.stderr.strip()
        logger.warning("git show %s returned %d: %s", target, result.returncode, stderr)
        return {"success": False, "content": "", "message": f"git show error: {stderr}"}

    json_handler.log_operation("show_object", {"ref": ref, "path": path, "bytes": len(result.stdout)})
    logger.info("Showed %s (%d bytes)", target, len(result.stdout))

    return {"success": True, "content": result.stdout, "message": f"showed {target}"}
