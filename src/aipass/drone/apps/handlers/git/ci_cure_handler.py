# =================== AIPass ====================
# Name: ci_cure_handler.py
# Description: ci-cure: commit an owner's CI cure on dev and push dev, fenced to the owner's tree
# Version: 1.0.0
# Created: 2026-10-22
# Modified: 2026-10-22
# =============================================

"""``drone @git ci-cure <run_id> @<owner> "<message>" <path ...>``: one CI cure, committed on dev and pushed.

The ci-cure tier's only verb. Every path must sit under ``src/aipass/<owner>/`` or be
``CHANGELOG.md``; the subject must start ``fix(<owner>): `` and name the run id. Only the named
paths are committed (``--only``), so anything else staged stays staged. No PR, merge, sync, tag
or rerun. Every call, refused or run, is one ledger row in AIPass's .ai_central.
"""

from __future__ import annotations

import os
import re
import subprocess
import time
from pathlib import Path, PurePosixPath

from aipass.prax import logger
from aipass.drone.apps.handlers.deletion_log import append_ledger_line
from aipass.drone.apps.handlers.git.commit_handler import commit_subject, subject_refusal
from aipass.drone.apps.handlers.git.repo_door import GIT_LOCAL_TIMEOUT, GIT_NETWORK_TIMEOUT, home_ledger
from aipass.drone.apps.handlers.json import json_handler

LEDGER_NAME = "git_ci_cures.jsonl"
CHANGELOG = "CHANGELOG.md"
_DEV = "dev"
_RUN_ID = re.compile(r"[0-9]+")
_BRANCH_NAME = re.compile(r"[a-z0-9][a-z0-9_-]*")
_GLOB_CHARS = set("*?[")

USAGE = 'Usage: drone @git ci-cure <run_id> @<owner> "<message>" <path> [<path> ...]'
# Refusal texts, printed exactly as written here; --help renders the same constants.
REFUSE_RUN_ID = "ci-cure refused: the run id is GitHub's numeric run id, not {run_id}. Nothing was committed."
REFUSE_OWNER = "ci-cure refused: the owner is @<branch>, not {owner}. Nothing was committed."
REFUSE_NO_PATHS = "ci-cure refused: no paths. Name every file of the cure. Nothing was committed."
REFUSE_PREFIX = "ci-cure refused: the message's first line must start with 'fix({owner}): '. Nothing was committed."
REFUSE_RUN_UNNAMED = "ci-cure refused: the message's first line must name run {run_id}. Nothing was committed."
REFUSE_PATH = "ci-cure refused: {path} is outside src/aipass/{owner}/ and is not CHANGELOG.md. Nothing was committed."
REFUSE_NOT_DEV = "ci-cure cannot run here: the branch is {branch}, not dev. Nothing was committed."
REFUSE_NO_CHANGE = "ci-cure refused: the named paths hold no change. Nothing was committed."

OUTCOME_PUSHED = "pushed"
OUTCOME_REFUSED = "refused"
OUTCOME_FAILED = "failed"


class _Refusal(Exception):
    """The cure cannot be committed; the message is the refusal, printed exactly. Nothing was committed."""


class _NotDev(_Refusal):
    """The capability species: a held tier, standing on the wrong branch. WARNING, not ERROR."""


def _git(repo_root: Path, *argv: str, timeout: int = GIT_LOCAL_TIMEOUT) -> subprocess.CompletedProcess[str]:
    """One git call in *repo_root*: pathspecs literal, so a path is a file name and never a glob or magic."""
    env = {**os.environ, "GIT_LITERAL_PATHSPECS": "1", "GIT_TERMINAL_PROMPT": "0"}
    return subprocess.run(
        ["git", *argv], cwd=str(repo_root), capture_output=True, text=True, encoding="utf-8", timeout=timeout, env=env
    )


def _fenced(path: str, owner: str) -> str:
    """*path* as repo-relative posix when it is CHANGELOG.md or under src/aipass/<owner>/; else _Refusal."""
    posix = PurePosixPath(path.replace("\\", "/"))
    inside = posix.parts[:3] == ("src", "aipass", owner) and len(posix.parts) > 3
    if posix.is_absolute() or ".." in posix.parts or _GLOB_CHARS & set(path) or not (inside or str(posix) == CHANGELOG):
        raise _Refusal(REFUSE_PATH.format(path=path, owner=owner))
    return str(posix)


def _parse(args: list[str]) -> tuple[str, str, str, list[str]]:
    """``(run_id, owner, message, paths)``, every rule of the contract checked before git runs."""
    if len(args) < 3:
        raise _Refusal(USAGE)
    run_id, owner_arg, message, *paths = args
    if not _RUN_ID.fullmatch(run_id):
        raise _Refusal(REFUSE_RUN_ID.format(run_id=run_id))
    owner = owner_arg[1:]
    if not owner_arg.startswith("@") or not _BRANCH_NAME.fullmatch(owner):
        raise _Refusal(REFUSE_OWNER.format(owner=owner_arg))
    if not paths:
        raise _Refusal(REFUSE_NO_PATHS)
    subject = commit_subject(message)
    if not subject.startswith(f"fix({owner}): "):
        raise _Refusal(REFUSE_PREFIX.format(owner=owner))
    if not re.search(rf"(?<![0-9]){run_id}(?![0-9])", subject):
        raise _Refusal(REFUSE_RUN_UNNAMED.format(run_id=run_id))
    over_cap = subject_refusal(message)
    if over_cap:
        raise _Refusal(over_cap)
    return run_id, owner, message, list(dict.fromkeys(_fenced(path, owner) for path in paths))


def _checked(result: subprocess.CompletedProcess[str], step: str) -> str:
    """stdout of a git call that must succeed; else _Refusal carrying git's own words."""
    if result.returncode != 0:
        raise _Refusal(f"ci-cure failed at git {step}: {(result.stderr or result.stdout).strip()}")
    return result.stdout.strip()


def record(*, caller: str, args: list[str], outcome: str, **detail) -> None:
    """One ci-cure record to prax and the ledger. Never raises: the ledger must not undo a push."""
    row = {"timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "caller": caller, "args": args, "outcome": outcome}
    row.update(detail)
    json_handler.log_operation("git_ci_cure", {"caller": caller, "outcome": outcome})
    try:
        append_ledger_line(row, home_ledger(LEDGER_NAME))
    except Exception as exc:
        logger.error("git ci-cure: failed to write the ledger for %s: %s", args, exc)


def cure(repo_root: Path, args: list[str], caller: str) -> dict:
    """Commit exactly the named paths on dev with the message, push dev, print the sha; a routing result."""
    try:
        run_id, owner, message, paths = _parse(args)
        branch = _git(repo_root, "symbolic-ref", "--quiet", "--short", "HEAD").stdout.strip()
        if branch != _DEV:
            raise _NotDev(REFUSE_NOT_DEV.format(branch=branch or "detached"))
        if not _checked(_git(repo_root, "status", "--porcelain", "--", *paths), "status"):
            raise _Refusal(REFUSE_NO_CHANGE)
        _checked(_git(repo_root, "add", "--", *paths), "add")
        _checked(_git(repo_root, "commit", "--only", "-m", message, "--", *paths), "commit")
        sha = _checked(_git(repo_root, "rev-parse", "HEAD"), "rev-parse")
    except (_Refusal, OSError, subprocess.SubprocessError) as exc:
        (logger.warning if isinstance(exc, _NotDev) else logger.error)("git ci-cure refused %s: %s", args, exc)
        record(caller=caller, args=args, outcome=OUTCOME_REFUSED, reason=str(exc))
        return {"stdout": "", "stderr": str(exc), "exit_code": 1}

    detail = {"run_id": run_id, "owner": owner, "paths": paths, "sha": sha}
    try:
        push = _git(repo_root, "push", "origin", f"{_DEV}:{_DEV}", timeout=GIT_NETWORK_TIMEOUT)
        pushed, said = push.returncode == 0, (push.stderr or push.stdout).strip()
    except (OSError, subprocess.SubprocessError) as exc:
        pushed, said = False, str(exc)
    if not pushed:
        logger.error("git ci-cure: committed %s for run %s, push failed: %s", sha, run_id, said)
        record(caller=caller, args=args, outcome=OUTCOME_FAILED, reason=f"push failed: {said}", **detail)
        return {"stdout": sha, "stderr": f"ci-cure committed {sha} on dev; the push failed: {said}", "exit_code": 1}

    logger.info("git ci-cure: %s for run %s (@%s) pushed by %s", sha, run_id, owner, caller)
    record(caller=caller, args=args, outcome=OUTCOME_PUSHED, **detail)
    summary = f"ci-cure: {len(paths)} path(s) for run {run_id} (@{owner}) committed on dev and pushed to origin/dev."
    return {"stdout": f"{sha}\n{summary}", "stderr": "", "exit_code": 0}
