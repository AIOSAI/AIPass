# =================== AIPass ====================
# Name: git_section.py
# Description: Git status section builder for devpulse dashboard
# Version: 1.2.0
# Created: 2026-05-16
# Modified: 2026-10-05
# =============================================

"""Git section builder for devpulse dashboard plugin.

Gathers current git state (branch, changes, commits ahead of main)
and writes to devpulse's DASHBOARD.local.json via write_section().

last_commit_msg is the subject's first line, capped at SUBJECT_CAP chars: the
dashboard is a glance, and the full message is one ``git log -1`` away.
"""

from pathlib import Path
from typing import Callable, Dict, List, Optional
import subprocess

from aipass.prax.apps.modules.dashboard import SUBJECT_CAP, cap_subject, write_section
from aipass.prax.apps.modules.logger import system_logger as logger

# SUBJECT_CAP and the cut itself now live once, beside the dashboard handlers
# (DPLAN-0347): a commit subject and a plan subject are the same glance, so they
# are the same number. Re-exported here because this module's tests read it.
__all__ = ["SUBJECT_CAP", "build_git_section"]


def _subject_line(message: str) -> str:
    """First line of a commit subject, capped — an essay subject stays one glance here."""
    return cap_subject(message)


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


def _run_git(repo_root: Path, *args: str, errors: Optional[List[str]] = None) -> Optional[str]:
    """Run a git command and return its stripped stdout, or None when it failed.

    None is a non-zero exit, a SubprocessError or an OSError: each is logged at
    warning with the args and the reason, and the reason is appended to
    ``errors`` as ``git <args>: <reason>`` when a list is handed in. An empty
    string is git's own answer (a clean tree), never a failure (devpulse's
    ruling as the section's owner, 10-04; prax, leg 16).
    """
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
    """Build git section data and write to dashboard.

    A field whose git read failed is written as null, never as 0 or an empty
    string, and the section then carries ``error``, the first failed command
    and its reason; when every read answered there is no ``error`` key. The
    write is never skipped: a card that stops refreshing looks current
    (devpulse's ruling, 10-04; prax, leg 16).

    Args:
        branch_path: Path to devpulse branch root.
        run_git: The git runner, ``_run_git``. A parameter so the tests hand
            in a stand-in rather than patching subprocess for the whole process.

    Returns:
        True if write_section succeeded, False otherwise.
    """
    repo_root = _find_git_root(branch_path)
    errors: List[str] = []

    # Current branch
    branch = run_git(repo_root, "rev-parse", "--abbrev-ref", "HEAD", errors=errors)

    # Files changed (porcelain counts all modified/untracked)
    status_output = run_git(repo_root, "status", "--porcelain", errors=errors)
    files_changed = None if status_output is None else len(status_output.splitlines())

    # Commits ahead of origin/main
    ahead_str = run_git(repo_root, "rev-list", "--count", "origin/main..HEAD", errors=errors)
    ahead_of_main: Optional[int] = None
    if ahead_str is not None:
        try:
            ahead_of_main = int(ahead_str)
        except ValueError as e:
            errors.append(f"git rev-list --count origin/main..HEAD: unreadable count {ahead_str!r} ({e})")

    # Last commit message and date
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
