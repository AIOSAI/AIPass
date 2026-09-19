# =================== AIPass ====================
# Name: repo_door.py
# Description: The external-repo door — git verbs in another repo, admin seat only, every use recorded
# Version: 1.0.0
# Created: 2026-09-13
# Modified: 2026-09-13
# =============================================

"""The external-repo door: ``drone @git <verb> --repo <path>``.

The owner, 2026-09-13 23:13 (DPLAN-0344): git write into a repo that is not
AIPass — projects/baud inside the tree, Vera-Studio outside it — goes ONLY
through @devpulse's admin grant. Project managers keep exactly the CWD-bound
owner tier they already had; nobody gains anything else.

Four answers live here so the orchestrator cannot drift from them:

* the flag — ``--repo <path>`` or ``--repo=<path>``, in any slot;
* who may use it — @ai_mail's verified-caller rail, the 5-leg admin grant,
  asked fresh on every use and never cached;
* which repo it names — an existing git top level that is not AIPass;
* the record — one JSONL line per use, refusals included, beside drone rm's
  deletion log in ``.ai_central``.

NO LOCK. The AIPass PR lock serialises AIPass's own merge train; taking it for
someone else's repo stalls that train for nothing. A lock file inside the target
is worse: it is an untracked file in another project's worktree, and the next
``commit --all`` there stages it into their history. Git holds ``index.lock``
for the length of every write it makes in that repo, which is all the
serialisation a single-holder door needs.
"""

from __future__ import annotations

import os
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, NamedTuple

from aipass.prax import logger
from aipass.drone.apps.handlers.json import json_handler
from aipass.drone.apps.handlers.deletion_log import NO_CURRENT_DIRECTORY, append_ledger_line, ledger_beside
from aipass.drone.apps.handlers.git.repo_context import is_aipass_repo
from aipass.drone.apps.handlers.router_handler import caller_cwd, resolve_caller_identity_signal

REPO_FLAG = "--repo"

# The verbs the door serves. Reads so the writer can see the tree it is about to
# commit; commit, push and tag to land it. Nothing that encodes AIPass's own
# dev->PR->main train (merge, pr, sync, ...) — a project's PR flow is the
# project's later choice, not this door's (DPLAN-0344 design table).
DOOR_VERBS = ("status", "diff", "log", "commit", "push", "tag")

LEDGER_NAME = "git_repo_door.jsonl"

OUTCOME_RAN = "ran"
OUTCOME_REFUSED = "refused"

UNKNOWN_CALLER = "unknown"

# Refusal texts, printed exactly as written here. --help renders these same
# constants, so the page cannot promise a sentence the door no longer says.
REFUSE_NOT_ADMIN = (
    "--repo is an admin-seat door; {caller} holds no admin grant. "
    "Git in an external repo goes through @devpulse's verified admin grant only (DPLAN-0344)."
)
REFUSE_LANE_DARK = "--repo is an admin-seat door and the admin lane is dark ({reason}). Refused."
REFUSE_NO_VALUE = "--repo needs a path: drone @git <verb> --repo <path>"
REFUSE_TWICE = "--repo was given more than once. Name one repo."
REFUSE_VERB = "'{verb}' does not take --repo. The external-repo door serves: " + ", ".join(DOOR_VERBS) + "."
REFUSE_MISSING = "--repo {path} does not exist."
REFUSE_NOT_DIR = "--repo {path} is not a directory."
REFUSE_NOT_REPO = "--repo {path} is not a git repository."
REFUSE_NOT_TOP = "--repo {path} sits inside the git repository at {toplevel}, not at its top level. Name the repo root."
REFUSE_AIPASS = (
    "--repo {path} is the AIPass repo. AIPass keeps its own verbs, lock, version guard and merge train; "
    "run the verb without --repo."
)
REFUSE_PUSH_ARGS = "push takes no arguments: drone @git push --repo <path>"
REFUSE_DETACHED = "push refused: HEAD is detached in {repo}. Check out the branch to push first."

# What drone's router stamps onto every routed command, and what the rail reads.
_STAMP_KEYS = ("AIPASS_CALLER_CWD", "AIPASS_CALLER_BRANCH", "AIPASS_CALLER_IDENTITY_SOURCE")


class RepoFlag(NamedTuple):
    """What the caller typed for ``--repo``, with the flag lifted out of the args."""

    present: bool
    path: str
    args: list[str]
    error: str


class AdminVerdict(NamedTuple):
    """The rail's answer, and the caller it was given for."""

    granted: bool
    caller: str
    refusal: str


class RepoTarget(NamedTuple):
    """The repo a ``--repo`` path names, or why it names none."""

    root: Path | None
    refusal: str


def extract_repo_flag(args: list[str]) -> RepoFlag:
    """Lift ``--repo <path>`` / ``--repo=<path>`` out of *args*, from any slot.

    Args:
        args: The verb's arguments exactly as routed.

    Returns:
        RepoFlag. ``present`` is True whenever the flag was typed at all — a
        bare ``--repo`` with no path still means the caller aimed at the door,
        and silently running the verb in the standing repo instead would be the
        one outcome they did not ask for.
    """
    remaining: list[str] = []
    values: list[str] = []
    missing = False
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == REPO_FLAG:
            following = args[index + 1] if index + 1 < len(args) else ""
            if following and not following.startswith("--"):
                values.append(following)
                index += 2
                continue
            missing = True
        elif arg.startswith(REPO_FLAG + "="):
            value = arg[len(REPO_FLAG) + 1 :]
            if value:
                values.append(value)
            else:
                missing = True
        else:
            remaining.append(arg)
        index += 1

    error = REFUSE_NO_VALUE if missing else (REFUSE_TWICE if len(values) > 1 else "")
    return RepoFlag(bool(values) or missing, values[0] if values else "", remaining, error)


@contextmanager
def _drone_caller_stamp() -> Iterator[None]:
    """Stamp this process the way drone's router stamps every command it routes.

    @git runs INSIDE drone rather than as a routed child, so the variables the
    rail reads were never set for this process — asked bare, it would answer
    "unprovable" for every seat alike. They are written here from the same two
    sources, by the same resolver, as ``router_handler`` writes them for a
    child: the assigned identity first, the cwd passport after it.

    Always fresh: an inherited stamp was written by another hop for another
    process and proves nothing about this one. Every prior value is put back.
    """
    saved = {key: os.environ.get(key) for key in _STAMP_KEYS}
    cwd = caller_cwd()
    signal = resolve_caller_identity_signal(cwd)
    fresh: dict[str, str] = {}
    if cwd is not None:
        fresh["AIPASS_CALLER_CWD"] = str(cwd)
    if signal.name:
        fresh["AIPASS_CALLER_BRANCH"] = signal.name
        fresh["AIPASS_CALLER_IDENTITY_SOURCE"] = signal.source or "unknown"
    for key in _STAMP_KEYS:
        if key in fresh:
            os.environ[key] = fresh[key]
        else:
            os.environ.pop(key, None)
    try:
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def admin_verdict() -> AdminVerdict:
    """Ask @ai_mail's verified-caller rail whether this caller holds the admin grant.

    The rail, not a name: a directory called devpulse proves nothing, and the
    rail is what hooks' edit_gate and testwrite_gate already trust. Asked on
    every use — a revoked grant must bite on the next call. Fails closed on an
    unimportable rail and on any raise.

    Returns:
        AdminVerdict with the verified caller (``@name``, or ``unknown``) and,
        when refused, the exact refusal text.
    """
    try:
        # Cross-branch handler import, named by @devpulse in the DPLAN-0344 brief:
        # the admin contract has one home and this door consumes it rather than
        # mirroring it. Lazy, so a dark lane refuses instead of breaking @git.
        from aipass.ai_mail.apps.handlers.users import verified_caller as rail
    except Exception as exc:
        logger.warning("git repo door: admin lane dark — verified-caller rail unavailable: %s", exc)
        return AdminVerdict(
            False, UNKNOWN_CALLER, REFUSE_LANE_DARK.format(reason=f"verified-caller rail unavailable: {exc}")
        )

    with _drone_caller_stamp():
        try:
            caller = rail.resolve_verified_caller()
            granted = bool(rail.is_verified_admin_caller())
        except Exception as exc:
            logger.warning("git repo door: admin verification raised, refusing: %s", exc)
            return AdminVerdict(
                False, UNKNOWN_CALLER, REFUSE_LANE_DARK.format(reason=f"admin verification raised: {exc}")
            )

    if granted:
        return AdminVerdict(True, caller or UNKNOWN_CALLER, "")
    return AdminVerdict(
        False, caller or UNKNOWN_CALLER, REFUSE_NOT_ADMIN.format(caller=caller or "an unverified caller")
    )


def _git_toplevel(directory: Path) -> Path | None:
    """The top level of the git work tree *directory* is in, or None if it is in none."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            cwd=str(directory),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("git repo door: git rev-parse failed in %s: %s", directory, exc)
        return None
    if result.returncode != 0 or not result.stdout.strip():
        return None
    return Path(result.stdout.strip()).resolve()


def resolve_repo(raw: str, aipass_root: Path) -> RepoTarget:
    """Resolve what ``--repo`` names into a repo the door may run in.

    Args:
        raw: The path exactly as typed.
        aipass_root: The project root drone resolves for the caller. Relative
            paths join to it, never to the cwd, so the same call means the same
            repo from anywhere in the seat.

    Returns:
        RepoTarget with the resolved top level, or the refusal. AIPass is
        refused two ways — by its registry at the top level, and by being the
        caller's own root — because a clean clone carries no registry, and
        either alone would let ``--repo`` walk around AIPass's own guards.
    """
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = aipass_root / candidate
    if not candidate.exists():
        return RepoTarget(None, REFUSE_MISSING.format(path=raw))
    if not candidate.is_dir():
        return RepoTarget(None, REFUSE_NOT_DIR.format(path=raw))

    resolved = candidate.resolve()
    toplevel = _git_toplevel(resolved)
    if toplevel is None:
        return RepoTarget(None, REFUSE_NOT_REPO.format(path=raw))
    if is_aipass_repo(toplevel) or toplevel == aipass_root.resolve():
        return RepoTarget(None, REFUSE_AIPASS.format(path=raw))
    if toplevel != resolved:
        return RepoTarget(None, REFUSE_NOT_TOP.format(path=raw, toplevel=toplevel))
    return RepoTarget(resolved, "")


def head_sha(repo_root: Path) -> str:
    """HEAD's full sha in *repo_root*, or "" when there is none to read."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--verify", "-q", "HEAD"],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("git repo door: could not read HEAD in %s: %s", repo_root, exc)
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def push_current_branch(repo_root: Path) -> dict:
    """Push the branch checked out in *repo_root* to its ``origin``, same name, never forced.

    The project's own branch model decides what that branch is; a rejected
    non-fast-forward comes back as git's own refusal, untouched.
    """
    try:
        branch = subprocess.run(
            ["git", "symbolic-ref", "--quiet", "--short", "HEAD"],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
        )
        if branch.returncode != 0 or not branch.stdout.strip():
            return {"stdout": "", "stderr": REFUSE_DETACHED.format(repo=repo_root), "exit_code": 1}
        name = branch.stdout.strip()
        result = subprocess.run(
            ["git", "push", "origin", name],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.error("git push failed in %s: %s", repo_root, exc)
        return {"stdout": "", "stderr": f"git push failed: {exc}", "exit_code": 1}

    if result.returncode != 0:
        return {"stdout": "", "stderr": f"git push failed: {result.stderr.strip()}", "exit_code": result.returncode}
    # git reports what it pushed on stderr; on success that report is the answer.
    report = result.stderr.strip()
    message = f"Pushed '{name}' to origin in {repo_root}."
    return {"stdout": f"{message}\n{report}" if report else message, "stderr": "", "exit_code": 0}


def ledger_path() -> Path:
    """Where door records are kept: beside the deletion log, wherever that is in force."""
    return ledger_beside(LEDGER_NAME)


def record_use(
    *,
    caller: str,
    verb: str,
    args: list[str],
    requested: str,
    repo: Path | str,
    head_before: str,
    head_after: str,
    exit_code: int,
    outcome: str,
    reason: str,
) -> dict:
    """Write one door record to prax and the ledger, and return it.

    Prax first, so the event reaches the logs even if the store cannot be
    written. Refusals are recorded too: a refused attempt at another repo
    leaves no other trace, which is what makes it worth finding later.
    Never raises — losing the record must not turn into losing the result.
    """
    cwd = caller_cwd()
    record = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "outcome": outcome,
        "caller": caller,
        "cwd": str(cwd) if cwd is not None else NO_CURRENT_DIRECTORY,
        "verb": verb,
        "args": args,
        "requested": requested,
        "repo": str(repo),
        "head_before": head_before,
        "head_after": head_after,
        "exit_code": exit_code,
        "reason": reason,
    }

    logger.info(
        "git repo door: %s %s in %s by %s — exit %s, HEAD %s -> %s%s",
        outcome,
        verb,
        record["repo"],
        caller,
        exit_code,
        head_before or "-",
        head_after or "-",
        f" ({reason})" if reason else "",
    )
    json_handler.log_operation(
        "git_repo_door",
        {"outcome": outcome, "verb": verb, "repo": record["repo"], "caller": caller, "exit_code": exit_code},
    )

    try:
        append_ledger_line(record, ledger_path())
    except Exception as exc:
        logger.error("git repo door: failed to write the ledger for %s %s: %s", verb, record["repo"], exc)

    return record
