# =================== AIPass ====================
# Name: show_handler.py
# Description: Git show handler — read repository history at a commit
# Version: 1.0.0
# Created: 2026-08-13
# Modified: 2026-08-13
# =============================================

"""Git show handler — read repository history at a commit.

Granted at the GLOBAL read tier: reading history is not a write. Auditing a
deletion means reading what was deleted, and status/diff/log only describe the
present — @seedgo could not verify another branch's committed bypass prune at
all without it (requested via @devpulse, 2026-08-13).

Deliberately NOT scoped to the caller's own branch directory the way status,
diff and log are. Those scope for convenience — they hide other branches' noise.
Scoping here would refuse the exact use case the verb was granted for: one
citizen auditing another's history. The working tree is already readable by any
agent; its past is the same repository.
"""

from __future__ import annotations

import subprocess

from aipass.prax import logger
from aipass.drone.apps.handlers.json import json_handler
from aipass.drone.apps.handlers.git.lock_handler import find_repo_root


def _rejects_as_flag(token: str) -> bool:
    """True if git would read this token as an option rather than a value.

    Checked before any argv is built. An empty or leading-dash token smuggled
    into a subprocess arg list is how a read verb grows a write (S49: names git
    would read as a flag are refused before the argv exists).
    """
    return not token or token.startswith("-")


def show_object(ref: str, path: str | None = None) -> dict:
    """Show a commit, or a file's contents at that commit.

    Args:
        ref: Any commit-ish git accepts — sha, HEAD~3, a tag, a branch.
        path: Optional repo-relative path. When given, reads the file AT that
            commit (``git show <ref>:<path>``) rather than showing the diff.

    Returns:
        dict with success (bool), content (str) and message (str).
    """
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
