# =================== AIPass ====================
# Name: uncommit_handler.py
# Description: uncommit: un-record the last n unpushed commits, their changes left staged
# Version: 1.0.0
# Created: 2026-11-03
# Modified: 2026-11-03
# =============================================

"""``drone @git uncommit [n]``: un-record the last n commits and leave their changes staged.

The safe subset of ``git reset --soft HEAD~n``. Only commits the remote tracking branch does not
hold: nothing pushed is ever un-recorded, so no force push can follow. Never a merge, never over
unstaged edits to the files those commits touch, never ``--hard`` or ``--mixed``, never the remote.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from aipass.prax import logger
from aipass.drone.apps.handlers.git.repo_door import GIT_LOCAL_TIMEOUT
from aipass.drone.apps.handlers.json import json_handler

USAGE = "Usage: drone @git uncommit [n]   (n defaults to 1)"
_NOTHING_DONE = " Nothing was un-recorded."
# Refusal texts, printed exactly as written here; --help renders the same constants.
REFUSE_COUNT = "uncommit takes one count, a whole number of 1 or more: {arg}. There is no force or hard flag."
REFUSE_DETACHED = "uncommit refused: HEAD is detached; uncommit runs on a branch." + _NOTHING_DONE
REFUSE_NO_UPSTREAM = (
    "uncommit refused: {branch} tracks no remote branch, so nothing proves its commits unpushed." + _NOTHING_DONE
)
REFUSE_PUSHED = (
    "uncommit refused: {sha} {subject} is already on {upstream}; un-recording it would need a force push."
    + _NOTHING_DONE
)
REFUSE_TOO_MANY = "uncommit refused: {n} asked, but {branch} is {ahead} commit(s) ahead of {upstream}." + _NOTHING_DONE
REFUSE_MERGE = "uncommit refused: {sha} {subject} is a merge commit." + _NOTHING_DONE
REFUSE_DIRTY = (
    "uncommit refused: unstaged edits to {paths}, which the commits touch; a soft reset would mix them. "
    "Stage or restore them first." + _NOTHING_DONE
)


class _Refusal(Exception):
    """The uncommit cannot run; the message is the refusal, printed exactly. Nothing was un-recorded."""


def _git(repo_root: Path, *argv: str) -> subprocess.CompletedProcess[str]:
    """One git call in *repo_root*, timed, its output decoded as UTF-8."""
    return subprocess.run(
        ["git", *argv], cwd=str(repo_root), capture_output=True, text=True, encoding="utf-8", timeout=GIT_LOCAL_TIMEOUT
    )


def _git_out(repo_root: Path, *argv: str) -> str:
    """git's stdout for a call that must succeed; raise _Refusal with git's own words if it does not."""
    result = _git(repo_root, *argv)
    if result.returncode != 0:
        raise _Refusal(f"uncommit failed: git {argv[0]} said: {(result.stderr or result.stdout).strip()}")
    return result.stdout.strip()


def _count(args: list[str]) -> int:
    """The n to un-record; 1 when no argument is given."""
    if not args:
        return 1
    if len(args) > 1 or not args[0].isdigit() or int(args[0]) < 1:
        raise _Refusal(REFUSE_COUNT.format(arg=" ".join(args)))
    return int(args[0])


def _check(repo_root: Path, n: int) -> list[tuple[str, str]]:
    """The (sha, subject) of the n commits to un-record, newest first; raise _Refusal for any unsafe case."""
    branch = _git(repo_root, "symbolic-ref", "--quiet", "--short", "HEAD").stdout.strip()
    if not branch:
        raise _Refusal(REFUSE_DETACHED)
    upstream_call = _git(repo_root, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}")
    if upstream_call.returncode != 0:
        raise _Refusal(REFUSE_NO_UPSTREAM.format(branch=branch))
    upstream = upstream_call.stdout.strip()

    rows = _git_out(repo_root, "log", f"-{n}", "--first-parent", "--format=%H%x00%P%x00%s", "HEAD").splitlines()
    commits = []
    for row in rows:
        sha, parents, subject = row.split("\x00", 2)
        if _git(repo_root, "merge-base", "--is-ancestor", sha, upstream).returncode == 0:
            raise _Refusal(REFUSE_PUSHED.format(sha=sha[:8], subject=subject, upstream=upstream))
        if len(parents.split()) > 1:
            raise _Refusal(REFUSE_MERGE.format(sha=sha[:8], subject=subject))
        commits.append((sha, subject))

    ahead = int(_git_out(repo_root, "rev-list", "--count", f"{upstream}..HEAD"))
    # A root commit has no HEAD~n to fall back to, so fewer rows than asked is too many as well.
    if n > ahead or len(commits) < n:
        raise _Refusal(REFUSE_TOO_MANY.format(n=n, branch=branch, ahead=ahead, upstream=upstream))

    touched = set(_git_out(repo_root, "diff", "--name-only", f"HEAD~{n}", "HEAD").splitlines())
    unstaged = set(_git_out(repo_root, "diff", "--name-only").splitlines())
    if touched & unstaged:
        raise _Refusal(REFUSE_DIRTY.format(paths=", ".join(sorted(touched & unstaged))))
    return commits


def uncommit(repo_root: Path, args: list[str], caller: str) -> dict:
    """Un-record the last n unpushed commits with a soft reset; a routing result."""
    try:
        n = _count(args)
        commits = _check(repo_root, n)
        _git_out(repo_root, "reset", "--soft", f"HEAD~{n}")
        head = _git_out(repo_root, "log", "-1", "--format=%h %s")
        staged = _git_out(repo_root, "diff", "--cached", "--name-status").splitlines()
    except (_Refusal, OSError, subprocess.SubprocessError) as exc:
        logger.warning("git uncommit %s refused for %s: %s", args, caller, exc)
        return {"stdout": "", "stderr": str(exc), "exit_code": 1}

    logger.info("git uncommit: %d commit(s) un-recorded by %s", n, caller)
    json_handler.log_operation(
        "uncommit", {"caller": caller, "count": n, "commits": [sha for sha, _ in commits], "head": head}
    )
    lines = [f"uncommitted  {sha[:8]}  {subject}" for sha, subject in commits]
    lines.append(f"{n} commit(s) un-recorded; HEAD is now {head}. Staged, ready for one commit:")
    lines += [f"  {row}" for row in staged]
    return {"stdout": "\n".join(lines), "stderr": "", "exit_code": 0}
