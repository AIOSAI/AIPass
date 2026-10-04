# =================== AIPass ====================
# Name: log_handler.py
# Description: Git log handler
# Version: 1.3.0
# Created: 2026-05-12
# Modified: 2026-10-04
# =============================================

"""Git log handler."""

from __future__ import annotations

import subprocess
from pathlib import Path

from aipass.prax import logger
from aipass.drone.apps.handlers.json import json_handler
from aipass.drone.apps.handlers.git.lock_handler import find_repo_root


def resolve_log_path(token: str, repo_root: Path, cwd: Path | None, must_exist: bool) -> str | None:
    """A path filter for git log, made absolute so it means the same from the repo root git runs in.

    A relative token is read against the caller's directory first, then the
    repo root. With *must_exist* False (a token after ``--``), a path found in
    neither place is still a pathspec, such as the history of a deleted file,
    and is read against the caller's directory the way git itself reads it.

    Returns the absolute path, or None only when *must_exist* is True and the
    path is in neither place: the caller then refuses the token by name.
    """
    path = Path(token)
    if path.is_absolute():
        if must_exist and not path.exists():
            return None
        return str(path)
    bases = [base for base in (cwd, repo_root) if base is not None]
    for base in bases:
        if (base / path).exists():
            return str(base / path)
    if must_exist:
        return None
    return str(bases[0] / path)


def _is_commit(side: str, repo_root: Path) -> bool:
    """Whether *side* names a commit. A flag-shaped name is never one: it would reach git as an option."""
    if side.startswith("-"):
        return False
    verify = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", "--end-of-options", f"{side}^{{commit}}"],
        capture_output=True,
        text=True,
        cwd=str(repo_root),
    )
    return verify.returncode == 0


def is_commit_range(token: str, repo_root: Path) -> bool:
    """Whether *token* is ``a..b`` or ``a...b`` with a commit on each side (an empty side is HEAD, as in git)."""
    separator = "..." if "..." in token else ".."
    if separator not in token:
        return False
    left, _, right = token.partition(separator)
    return all(_is_commit(side or "HEAD", repo_root) for side in (left, right))


def get_git_log(
    count: int | None = 10,
    repo_root: Path | None = None,
    paths: list[str] | None = None,
    rev_range: str | None = None,
) -> dict:
    """Get recent git log entries from *repo_root* (default: the standing repo).

    *paths* keeps only the commits that touch them (``git log -- <paths>``).
    *rev_range* (``origin/dev..HEAD``) lists the commits in it, read-only;
    the caller verifies it with :func:`is_commit_range` first. A *count* of
    None lists them all. ``success`` is False when git could not answer; an
    empty history is a success with no entries.
    """
    if repo_root is None:
        repo_root = find_repo_root()

    cmd = ["git", "log", "--oneline"]
    if count is not None:
        cmd.append(f"-{count}")
    if rev_range is not None:
        cmd += ["--end-of-options", rev_range]
    if paths:
        cmd += ["--", *paths]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(repo_root),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.error("git log failed: %s", exc)
        return {"success": False, "entries": [], "count": 0, "message": f"git log failed: {exc}"}

    if result.returncode != 0:
        return {
            "success": False,
            "entries": [],
            "count": 0,
            "message": f"git log error: {result.stderr.strip()}",
        }

    entries = [line for line in result.stdout.splitlines() if line.strip()]

    json_handler.log_operation("get_git_log", {"count": len(entries), "paths": len(paths or []), "range": rev_range})
    logger.info("Retrieved %d log entries", len(entries))

    return {"success": True, "entries": entries, "count": len(entries), "message": f"{len(entries)} log entries"}
