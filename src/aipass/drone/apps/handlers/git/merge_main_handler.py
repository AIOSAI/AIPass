# =================== AIPass ====================
# Name: merge_main_handler.py
# Description: Bring origin/main into dev with a merge commit, never a rewrite
# Version: 1.0.0
# Created: 2026-10-01
# Modified: 2026-10-17
# =============================================

"""Bring origin/main into dev with a merge commit: never a rebase, a push, a force or a stash.

``sync`` is fast-forward only, and rebasing pushed history needs a force push, which the fleet never does.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from aipass.prax import logger
from aipass.drone.apps.handlers.json import json_handler

MAIN_REF = "origin/main"
DEV_BRANCH = "dev"

HELP = (
    "git merge-main — Merge origin/main into dev (no rewrite) [owner]\n"
    "  For dev diverged from main (main took commits dev never saw). On dev only:\n"
    "  fetches origin, then git merge --no-ff --no-edit origin/main.\n"
    "  Refuses, touching nothing: off dev, a merge already in progress, staged\n"
    "  changes, or a file main changes that is uncommitted here (listed).\n"
    "  On conflict: merge --abort, the conflicted files listed, exit 1.\n"
    "  It never pushes (dev-pr pushes), never forces, never stashes.\n"
)


class _ReadFailed(Exception):
    """A git read the decision rests on did not answer; the verb refuses rather than guess."""


def _git(repo_root: Path, *argv: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *argv], cwd=str(repo_root), capture_output=True, text=True, encoding="utf-8")


def _paths(repo_root: Path, *argv: str) -> set[str]:
    """The paths a ``-z`` listing names. A listing that fails raises: an empty set would read as no overlap."""
    result = _git(repo_root, *argv)
    if result.returncode != 0:
        raise _ReadFailed(f"git {' '.join(argv)} failed: {result.stderr.strip()}")
    return {name for name in result.stdout.split("\0") if name}


def _merge_in_progress(repo_root: Path) -> bool:
    return _git(repo_root, "rev-parse", "--quiet", "--verify", "MERGE_HEAD").returncode == 0


def _listed(paths: list[str]) -> str:
    return "\n  " + "\n  ".join(paths)


def _refused(message: str) -> dict:
    logger.warning("merge-main refused: %s", message)
    return {"success": False, "message": message}


def merge_main(repo_root: Path) -> dict:
    """Merge origin/main into dev with ``git merge --no-ff --no-edit``.

    Refuses untouched on a merge already in progress: aborting a conflict would throw that merge away.
    """
    try:
        return _merge_main(repo_root)
    except _ReadFailed as exc:
        return _refused(f"{exc}. Nothing was merged.")
    except (OSError, subprocess.SubprocessError) as exc:
        return _refused(f"git could not run: {exc}. Nothing was merged.")


def _merge_main(repo_root: Path) -> dict:
    head = _git(repo_root, "symbolic-ref", "--quiet", "--short", "HEAD")
    branch = head.stdout.strip() if head.returncode == 0 else "detached"
    if branch != DEV_BRANCH:
        return _refused(f"merge-main runs on dev only; HEAD is {branch}. Nothing was touched.")
    if _merge_in_progress(repo_root):
        return _refused(
            "A merge is already in progress (MERGE_HEAD exists). Finish or abort it first; nothing was touched."
        )

    fetch = _git(repo_root, "fetch", "origin")
    if fetch.returncode != 0:
        return _refused(f"git fetch origin failed: {fetch.stderr.strip()}")

    behind = _git(repo_root, "rev-list", "--count", f"HEAD..{MAIN_REF}")
    if behind.returncode != 0:
        return _refused(f"Cannot read {MAIN_REF}: {behind.stderr.strip()}")
    commits = behind.stdout.strip()
    if commits == "0":
        return {"success": True, "message": f"dev already contains {MAIN_REF}; nothing to merge."}

    staged = sorted(_paths(repo_root, "diff", "--cached", "--name-only", "-z"))
    if staged:
        return _refused(
            "Staged changes in the index; git merge refuses them so the merge commit never carries them. "
            f"Commit or unstage first:{_listed(staged)}"
        )

    from_main = _paths(repo_root, "diff", "--name-only", "-z", f"HEAD...{MAIN_REF}")
    local = _paths(repo_root, "diff", "--name-only", "-z") | _paths(
        repo_root, "ls-files", "--others", "--exclude-standard", "-z"
    )
    overlap = sorted(from_main & local)
    if overlap:
        return _refused(f"main changes files that are uncommitted here; commit or move them first:{_listed(overlap)}")

    merge = _git(repo_root, "merge", "--no-ff", "--no-edit", MAIN_REF)
    if merge.returncode == 0:
        sha = _git(repo_root, "rev-parse", "--short", "HEAD").stdout.strip()
        message = (
            f"Merged {MAIN_REF} into dev as {sha}: {commits} commit(s), {len(from_main)} file(s) from main. "
            "Not pushed; dev-pr pushes."
        )
        json_handler.log_operation("merge_main", {"commit": sha, "commits": commits, "files": sorted(from_main)})
        logger.info(message)
        return {"success": True, "message": message}

    return _abort(repo_root, merge)


def _abort(repo_root: Path, merge: subprocess.CompletedProcess[str]) -> dict:
    """Name what conflicted, then abort, so the tree is as it was before the merge."""
    conflicted_read = _git(repo_root, "diff", "--name-only", "--diff-filter=U", "-z")
    conflicted = sorted(name for name in conflicted_read.stdout.split("\0") if name)
    detail = (
        f"Conflicted files:{_listed(conflicted)}"
        if conflicted
        else f"git said: {merge.stderr.strip() or merge.stdout.strip()}"
    )

    if _merge_in_progress(repo_root):
        abort = _git(repo_root, "merge", "--abort")
        if abort.returncode != 0:
            message = (
                f"Merge of {MAIN_REF} failed AND git merge --abort failed: {abort.stderr.strip()}. "
                f"The tree is mid-merge; ask @devpulse.\n{detail}"
            )
            logger.error("merge-main: %s", message)
            return {"success": False, "message": message}

    message = f"Merge of {MAIN_REF} into dev failed and was aborted; the tree is as before.\n{detail}"
    logger.warning("merge-main: %s", message)
    return {"success": False, "message": message}
