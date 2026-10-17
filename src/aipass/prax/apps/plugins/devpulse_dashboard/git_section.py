# =================== AIPass ====================
# Name: git_section.py
# Description: Git status section builder for devpulse dashboard
# Version: 1.2.0
# Created: 2026-05-16
# Modified: 2026-10-17
# =============================================

"""Git section builder for devpulse dashboard plugin."""

from pathlib import Path
from typing import Callable, Dict, List, Optional
import subprocess

from aipass.prax.apps.modules.dashboard import SUBJECT_CAP, cap_subject, write_section
from aipass.prax.apps.modules.logger import system_logger as logger

# SUBJECT_CAP is re-exported because this module's tests read it.
__all__ = ["SUBJECT_CAP", "build_git_section"]


def _subject_line(message: str) -> str:
    """First line of a commit subject, capped — an essay subject stays one glance here."""
    return cap_subject(message)


def _find_git_root(start: Path) -> Path:
    """Walk up from start to find a .git directory."""
    # Not named _find_repo_root: the repo-root sweep matches that name, and this one seeks .git.
    if not start.is_absolute():
        raise ValueError("start must be absolute; resolving a relative path reads the cwd")
    current = start
    while current != current.parent:
        if (current / ".git").exists():
            return current
        current = current.parent
    raise FileNotFoundError("No .git found above " + str(start))


def _run_git(repo_root: Path, *args: str, errors: Optional[List[str]] = None) -> Optional[str]:
    """Run a git command and return its stripped stdout, or None when it failed."""
    # "" is git's own answer (a clean tree), never a failure.
    command = " ".join(("git",) + args)
    try:
        result = subprocess.run(
            ["git"] + list(args),
            capture_output=True,
            text=True,
            cwd=str(repo_root),
            timeout=10,
        )
    except (subprocess.SubprocessError, OSError) as e:
        reason = f"{type(e).__name__}: {e}"
    else:
        if result.returncode == 0:
            return result.stdout.strip()
        stderr_tail = (result.stderr or "").strip()[-200:]
        reason = f"exit {result.returncode}: {stderr_tail}"
    logger.warning(f"git command failed: {command} — {reason}")
    if errors is not None:
        errors.append(f"{command}: {reason}")
    return None


def build_git_section(branch_path: Path, run_git: Callable[..., Optional[str]] = _run_git) -> bool:
    """Build git section data and write to dashboard."""
    # A failed read is null plus ``error``, never 0 or "", and the write is never
    # skipped: a card that stops refreshing looks current (devpulse owns this contract).
    repo_root = _find_git_root(branch_path)
    errors: List[str] = []

    branch = run_git(repo_root, "rev-parse", "--abbrev-ref", "HEAD", errors=errors)

    status_output = run_git(repo_root, "status", "--porcelain", errors=errors)
    files_changed = None if status_output is None else len(status_output.splitlines())

    ahead_str = run_git(repo_root, "rev-list", "--count", "origin/main..HEAD", errors=errors)
    ahead_of_main: Optional[int] = None
    if ahead_str is not None:
        try:
            ahead_of_main = int(ahead_str)
        except ValueError as e:
            errors.append(f"git rev-list --count origin/main..HEAD: unreadable count {ahead_str!r} ({e})")

    subject = run_git(repo_root, "log", "-1", "--format=%s", errors=errors)
    last_commit_msg = None if subject is None else _subject_line(subject)
    last_commit_date = run_git(repo_root, "log", "-1", "--format=%cs", errors=errors)

    section_data: Dict = {
        "managed_by": "devpulse",
        "branch": branch,
        "files_changed": files_changed,
        "ahead_of_main": ahead_of_main,
        "last_commit_msg": last_commit_msg,
        "last_commit_date": last_commit_date,
    }
    if errors:
        section_data["error"] = errors[0]

    return write_section(branch_path, "git", section_data)
