# =================== AIPass ====================
# Name: git_section.py
# Description: Git status section builder for devpulse dashboard
# Version: 1.0.0
# Created: 2026-05-16
# Modified: 2026-05-16
# =============================================

"""Git section builder for devpulse dashboard plugin.

Gathers current git state (branch, changes, commits ahead of main)
and writes to devpulse's DASHBOARD.local.json via write_section().
"""

from pathlib import Path
from typing import Dict
import subprocess

from aipass.prax.apps.modules.dashboard import write_section
from aipass.prax.apps.modules.logger import system_logger as logger


def _find_git_root(start: Path) -> Path:
    """Walk up from start to find a .git directory.

    RENAMED from _find_repo_root on 2026-08-31. It asks a different question from
    the branch's other _find_repo_root functions — .git, not AIPASS_REGISTRY.json
    — and sharing their name made it a false positive in the sweep that keeps
    those honest. It was never the same defect: it takes an explicit start and
    raises rather than falling back to the working directory.

    A relative ``start`` is refused rather than resolved, because resolve() reads
    the working directory and a process whose cwd was deleted would die here.
    """
    if not start.is_absolute():
        raise ValueError("start must be absolute; resolving a relative path reads the cwd")
    current = start
    while current != current.parent:
        if (current / ".git").exists():
            return current
        current = current.parent
    raise FileNotFoundError("No .git found above " + str(start))


def _run_git(repo_root: Path, *args: str) -> str:
    """Run a git command and return stdout. Returns empty string on failure."""
    try:
        result = subprocess.run(
            ["git"] + list(args),
            capture_output=True,
            text=True,
            cwd=str(repo_root),
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
        return ""
    except (subprocess.SubprocessError, OSError) as e:
        logger.info(f"git command failed: {args} — {e}")
        return ""


def build_git_section(branch_path: Path) -> bool:
    """Build git section data and write to dashboard.

    Args:
        branch_path: Path to devpulse branch root.

    Returns:
        True if write_section succeeded, False otherwise.
    """
    repo_root = _find_git_root(branch_path)

    # Current branch
    branch = _run_git(repo_root, "rev-parse", "--abbrev-ref", "HEAD") or "unknown"

    # Files changed (porcelain counts all modified/untracked)
    status_output = _run_git(repo_root, "status", "--porcelain")
    files_changed = len(status_output.splitlines()) if status_output else 0

    # Commits ahead of origin/main
    ahead_str = _run_git(repo_root, "rev-list", "--count", "origin/main..HEAD")
    try:
        ahead_of_main = int(ahead_str)
    except (ValueError, TypeError) as e:
        logger.info(f"Could not parse ahead count '{ahead_str}': {e}")
        ahead_of_main = 0

    # Last commit message and date
    last_commit_msg = _run_git(repo_root, "log", "-1", "--format=%s") or ""
    last_commit_date = _run_git(repo_root, "log", "-1", "--format=%cs") or ""

    section_data: Dict = {
        "managed_by": "devpulse",
        "branch": branch,
        "files_changed": files_changed,
        "ahead_of_main": ahead_of_main,
        "last_commit_msg": last_commit_msg,
        "last_commit_date": last_commit_date,
    }

    return write_section(branch_path, "git", section_data)
