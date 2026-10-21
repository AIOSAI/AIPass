# =================== AIPass ====================
# Name: restore_handler.py
# Description: restore: named tracked files back to HEAD's content, or a given commit's, index included
# Version: 1.0.0
# Created: 2026-10-21
# Modified: 2026-10-21
# =============================================

"""``drone @git restore [--source <ref>] <path ...>``: named tracked files back to a commit's content.

The door to ``git restore --staged --worktree``. Explicit paths only, never on main, and it
never deletes: a path the source commit does not hold is refused, since restoring it would
remove the file (deletion is drone rm's, with its record). Untracked files are left in place
and named. Every call is one ledger row in AIPass's .ai_central.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

from aipass.prax import logger
from aipass.drone.apps.handlers.deletion_log import NO_CURRENT_DIRECTORY, append_ledger_line
from aipass.drone.apps.handlers.git.repo_door import GIT_LOCAL_TIMEOUT, home_ledger
from aipass.drone.apps.handlers.git.tracked_handler import IGNORED, TRACKED, UNTRACKED, classify
from aipass.drone.apps.handlers.json import json_handler

LEDGER_NAME = "git_restores.jsonl"
SOURCE_FLAG = "--source"
_DEFAULT_SOURCE = "HEAD"
_MAIN = "main"
_GLOB_CHARS = set("*?[")

USAGE = "Usage: drone @git restore [--source <ref>] <path> [<path> ...]"
# Refusal texts, printed exactly as written here; --help renders the same constants.
REFUSE_GLOB = "restore names files or directories, never . or a glob: {path}"
REFUSE_FLAG = "restore takes no flag but --source <ref>: {arg}. There is no force or bypass flag."
REFUSE_NO_SOURCE = "restore --source needs a commit: --source <ref>"
REFUSE_SOURCE = "restore refused: --source {ref} names no commit in this repo."
REFUSE_MAIN = "restore refused: the branch is main. Restore runs on dev only; nothing was touched."
REFUSE_OUTSIDE = "restore refused: {path} is outside the repo at {repo}. Nothing was touched."
REFUSE_MISSING = "restore refused: {path} is neither tracked nor on disk. Nothing was touched."
REFUSE_NOT_AT_SOURCE = (
    "restore refused: {path} is tracked here but not at {source}; restoring it would delete it, "
    "and deletion is drone rm's. Nothing was touched."
)
NOTHING = "nothing to restore: every named path already matches {source}."


class _Refusal(Exception):
    """The restore cannot run; the message is the refusal, printed exactly. Nothing was touched."""


def _git(repo_root: Path, *argv: str) -> subprocess.CompletedProcess[str]:
    """One git call in *repo_root*, timed, its output decoded as UTF-8."""
    return subprocess.run(
        ["git", *argv], cwd=str(repo_root), capture_output=True, text=True, encoding="utf-8", timeout=GIT_LOCAL_TIMEOUT
    )


def _git_lines(repo_root: Path, *argv: str) -> list[str]:
    """git's stdout lines for a call that must succeed; raise _Refusal with git's own words if it does not."""
    result = _git(repo_root, *argv)
    if result.returncode != 0:
        raise _Refusal(f"restore failed: git {argv[0]} said: {(result.stderr or result.stdout).strip()}")
    return [line for line in result.stdout.splitlines() if line]


def _parse(args: list[str]) -> tuple[str, list[str]]:
    """``(source, paths)``; raise _Refusal for any flag but --source and for a glob or a bare dot."""
    source, paths, rest = _DEFAULT_SOURCE, [], list(args)
    while rest:
        arg = rest.pop(0)
        flag, equals, value = arg.partition("=")
        if flag == SOURCE_FLAG:
            if not equals:
                value = rest.pop(0) if rest else ""
            if not value or value.startswith("-"):
                raise _Refusal(REFUSE_NO_SOURCE)
            source = value
        elif arg.startswith("-"):
            raise _Refusal(REFUSE_FLAG.format(arg=arg))
        elif arg in (".", "./") or _GLOB_CHARS & set(arg):
            raise _Refusal(REFUSE_GLOB.format(path=arg))
        else:
            paths.append(arg)
    if not paths:
        raise _Refusal(USAGE)
    return source, paths


def _plan(repo_root: Path, cwd: Path | None, source: str, paths: list[str]) -> tuple[list[str], list[str]]:
    """``(tracked files to restore, untracked paths left in place)``, every path checked before any is touched."""
    classified = classify(repo_root, cwd, paths)
    if not classified["ok"]:
        raise _Refusal(f"restore failed: {classified['message']}")
    targets: list[str] = []
    left: list[str] = []
    for state, shown in classified["rows"]:
        if state == "outside":
            raise _Refusal(REFUSE_OUTSIDE.format(path=shown, repo=repo_root))
        if shown in ("", "."):
            raise _Refusal(REFUSE_GLOB.format(path=shown or "."))
        if state in (UNTRACKED, IGNORED):
            left.append(shown)
            continue
        if state != TRACKED:
            raise _Refusal(REFUSE_MISSING.format(path=shown))
        at_source = set(_git_lines(repo_root, "ls-tree", "-r", "--name-only", source, "--", shown))
        for path in _git_lines(repo_root, "ls-files", "--", shown):
            if path not in at_source:
                raise _Refusal(REFUSE_NOT_AT_SOURCE.format(path=path, source=source))
        targets += sorted(at_source)
        left += _git_lines(repo_root, "ls-files", "--others", "--exclude-standard", "--", shown)
    return list(dict.fromkeys(targets)), list(dict.fromkeys(left))


def _record(*, caller: str, repo_root: Path, cwd: Path | None, source: str, requested: list[str], **result) -> None:
    """One restore record to prax and the ledger. Never raises: the files are already back."""
    record = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "caller": caller,
        "cwd": str(cwd) if cwd is not None else NO_CURRENT_DIRECTORY,
        "repo": str(repo_root),
        "source": source,
        "requested": requested,
        **result,
    }
    json_handler.log_operation("git_restore", {"source": source, "restored": len(result.get("restored", []))})
    try:
        append_ledger_line(record, home_ledger(LEDGER_NAME))
    except Exception as exc:
        logger.error("git restore: failed to write the ledger for %s: %s", repo_root, exc)


def restore(repo_root: Path, cwd: Path | None, args: list[str], caller: str) -> dict:
    """Put each named tracked file at *source*'s content, worktree and index; a routing result."""
    source, paths = _DEFAULT_SOURCE, list(args)
    try:
        source, paths = _parse(args)
        branch = _git(repo_root, "symbolic-ref", "--quiet", "--short", "HEAD").stdout.strip()
        if branch == _MAIN:
            raise _Refusal(REFUSE_MAIN)
        if _git(repo_root, "rev-parse", "--verify", "--quiet", f"{source}^{{commit}}").returncode != 0:
            raise _Refusal(REFUSE_SOURCE.format(ref=source))
        targets, left = _plan(repo_root, cwd, source, paths)
        changed: list[str] = []
        if targets:
            # Worktree and index each against the source: a staged edit with a clean worktree is still not back.
            worktree = _git_lines(repo_root, "diff", "--name-only", source, "--", *targets)
            staged = _git_lines(repo_root, "diff", "--cached", "--name-only", source, "--", *targets)
            changed = sorted(set(worktree) | set(staged))
        if changed:
            _git_lines(repo_root, "restore", f"--source={source}", "--staged", "--worktree", "--", *changed)
    except (_Refusal, OSError, subprocess.SubprocessError) as exc:
        logger.warning("git restore refused %s from %s: %s", paths, source, exc)
        _record(caller=caller, repo_root=repo_root, cwd=cwd, source=source, requested=paths, refused=str(exc))
        return {"stdout": "", "stderr": str(exc), "exit_code": 1}

    logger.info("git restore: %d file(s) back to %s by %s", len(changed), source, caller)
    _record(caller=caller, repo_root=repo_root, cwd=cwd, source=source, requested=paths, restored=changed, left=left)
    lines = [f"restored  {path}  (from {source})" for path in changed]
    lines.append(f"{len(changed)} file(s) restored to {source}." if changed else NOTHING.format(source=source))
    lines += [f"untracked, left in place: {path}" for path in left]
    return {"stdout": "\n".join(lines), "stderr": "", "exit_code": 0}
