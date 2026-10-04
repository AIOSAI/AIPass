# =================== AIPass ====================
# Name: tracked_handler.py
# Description: Whether git tracks, ignores or has never seen each named path
# Version: 1.0.0
# Created: 2026-10-04
# Modified: 2026-10-04
# =============================================

"""Whether git tracks, ignores or has never seen each named path.

The twin of ``git ls-files`` plus ``git check-ignore``. A commit by paths was
refused because a plan file was gitignored, and with raw git blocked for every
seat the only way to see that was gone (DPLAN-0356, git_gate 5.0.0).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from aipass.prax import logger
from aipass.drone.apps.handlers.json import json_handler
from aipass.drone.apps.handlers.git.log_handler import resolve_log_path

TRACKED = "tracked"
IGNORED = "ignored"
UNTRACKED = "untracked"
MISSING = "missing"
OUTSIDE = "outside"


def _git(repo_root: Path, *argv: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *argv], cwd=str(repo_root), capture_output=True, text=True, encoding="utf-8")


def _state(repo_root: Path, path: Path) -> str:
    """One path's state. A git answer outside the expected codes raises: no guess is printed as a state."""
    try:
        relative = path.resolve().relative_to(repo_root.resolve())
    except ValueError:
        logger.info("git tracked: %s is outside %s", path, repo_root)
        return OUTSIDE
    spec = relative.as_posix()
    listed = _git(repo_root, "ls-files", "--error-unmatch", "--", spec)
    if listed.returncode == 0:
        return TRACKED
    if listed.returncode != 1:
        raise RuntimeError(f"git ls-files failed for {spec}: {listed.stderr.strip()}")
    ignored = _git(repo_root, "check-ignore", "-q", "--", spec)
    if ignored.returncode == 0:
        return IGNORED
    if ignored.returncode != 1:
        raise RuntimeError(f"git check-ignore failed for {spec}: {ignored.stderr.strip()}")
    return UNTRACKED if path.exists() else MISSING


def _locate(repo_root: Path, cwd: Path | None, token: str) -> tuple[Path, str]:
    """The path a token names and its state: the first place it is on disk, else tracked, else the repo root's."""
    found = resolve_log_path(token, repo_root, cwd, must_exist=True)
    if found is not None:
        return Path(found), _state(repo_root, Path(found))
    bases = [base for base in (cwd, repo_root) if base is not None and not Path(token).is_absolute()]
    for base in bases:
        state = _state(repo_root, base / token)
        if state == TRACKED:
            return base / token, state
    path = Path(token) if Path(token).is_absolute() else repo_root / token
    return path, _state(repo_root, path)


def classify(repo_root: Path, cwd: Path | None, tokens: list[str]) -> dict:
    """Name each path tracked, ignored, untracked, missing (neither on disk nor tracked) or outside the repo.

    A relative path is read against the caller's directory first, then the
    repo root, the same rule ``log`` and ``blame`` follow. One on disk in
    neither place is the tracked one if either names a deleted tracked file,
    else the repo root's. Rows come back in the order given, as repo-relative
    paths (absolute for one outside).

    Returns:
        Dict with ok (bool), rows (list of (state, path)) and message (str).
    """
    rows: list[tuple[str, str]] = []
    try:
        for token in tokens:
            path, state = _locate(repo_root, cwd, token)
            shown = str(path) if state == OUTSIDE else path.resolve().relative_to(repo_root.resolve()).as_posix()
            rows.append((state, shown))
    except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
        logger.warning("git tracked failed: %s", exc)
        return {"ok": False, "rows": rows, "message": str(exc)}

    json_handler.log_operation("git_tracked", {"paths": len(rows)})
    return {"ok": True, "rows": rows, "message": f"{len(rows)} path(s) classified"}
