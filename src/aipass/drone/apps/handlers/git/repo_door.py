# =================== AIPass ====================
# Name: repo_door.py
# Description: The external-repo door — git verbs in another repo, admin seat only, every use recorded
# Version: 1.5.0
# Created: 2026-09-13
# Modified: 2026-10-15
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
from urllib.parse import urlsplit

from aipass.prax import logger
from aipass.drone.apps.handlers.json import json_handler
from aipass.drone.apps.handlers.deletion_log import NO_CURRENT_DIRECTORY, append_ledger_line, ledger_beside
from aipass.drone.apps.handlers.git.repo_context import is_aipass_repo
from aipass.drone.apps.handlers.router_handler import caller_cwd, resolve_caller_identity_signal

REPO_FLAG = "--repo"

# The verbs the door serves. Reads so the writer can see the tree it is about to
# commit; commit, push and tag to land it; fetch and a fast-forward-only sync so
# a push the remote rejects can be caught up first (2026-10-13, FPLAN-0642).
# Nothing that encodes AIPass's own dev->PR->main train (merge, pr, smart-sync,
# ...) — a project's PR flow is the project's later choice, not this door's
# (DPLAN-0344 design table). The door's sync is not AIPass's sync: it never
# rebases, never merges, and refuses a diverged branch. tracked and untrack so a
# file a catch-all commit or a soft reset left in the index can be taken out
# again, the working tree untouched (2026-10-15, projects/aipass-site).
DOOR_VERBS = (
    "status",
    "diff",
    "log",
    "tracked",
    "commit",
    "untrack",
    "push",
    "tag",
    "fetch",
    "sync",
    "merge-upstream",
    "run",
)

# gh's run, read side only, so a release build pushed through the door can be
# watched through it (2026-10-13). rerun, cancel, delete and download stay
# home-only. Only a --repo value naming a directory is the door's: anything
# else is gh's own OWNER/NAME and passes through untouched.
RUN_READS = ("list", "view", "watch")
_GITHUB_HOST = "github.com"

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
REFUSE_GIT_FAILED = "--repo {path}: git could not run to read its top level ({reason}). Refused."
REFUSE_NOT_TOP = "--repo {path} sits inside the git repository at {toplevel}, not at its top level. Name the repo root."
REFUSE_AIPASS = (
    "--repo {path} is the AIPass repo. AIPass keeps its own verbs, lock, version guard and merge train; "
    "run the verb without --repo."
)
REFUSE_PUSH_ARGS = "push takes no arguments: drone @git push --repo <path>"
REFUSE_DETACHED = "push refused: HEAD is detached in {repo}. Check out the branch to push first."
REFUSE_NO_ARGS = "{verb} takes no arguments: drone @git {verb} --repo <path>"
REFUSE_HEAD_DETACHED = "{verb} refused: HEAD is detached in {repo}. Check out a branch first."
REFUSE_NO_UPSTREAM = "{verb} refused: '{branch}' in {repo} has no upstream to compare against. Fetched: {fetched}."
REFUSE_DIRTY = (
    "{verb} refused: {repo} has tracked changes. Commit them or set them aside first; "
    "untracked files do not block. Nothing was fetched or moved."
)
REFUSE_CONFLICT = (
    "merge-upstream refused: merging {upstream} into '{branch}' in {repo} conflicts. "
    "The merge was aborted and the tree is as it was; resolving is the owner's, by hand. Conflicted:"
)
REFUSE_DIVERGED = (
    "sync refused: '{branch}' and {upstream} have diverged in {repo} (ahead {ahead}, behind {behind}). "
    "No rebase, no merge commit: that is the owner's call. Nothing was moved."
)
REFUSE_RUN_SUB = (
    "'run {sub}' does not take --repo. The door reads runs only: list, view <id> [--log | --log-failed], "
    "watch <id>. rerun, cancel, delete and download stay home-only."
)
REFUSE_RUN_SHORT_FLAG = "run --repo <path> names the repo already; -R is gh's flag for the same thing. Give one."
REFUSE_NO_GITHUB = (
    "run refused: the origin remote of {repo} does not name a github.com repository, "
    "so there is no OWNER/NAME to hand gh."
)

# The remote fetch reads, and push writes to.
_REMOTE = "origin"

# fetch talks to the remote and merge may run a merge driver over every file,
# so a slow link or a large history gets two minutes before the door gives up.
GIT_NETWORK_TIMEOUT = 120
# Every other call the door's runner makes is a local read (symbolic-ref,
# rev-parse, status, diff, log, remote get-url): seconds on any tree, so a
# minute is a hang, not a slow answer.
GIT_LOCAL_TIMEOUT = 60
_NETWORK_VERBS = ("fetch", "merge")

# What drone's router stamps onto every routed command, and what the rail reads.
_STAMP_KEYS = ("AIPASS_CALLER_CWD", "AIPASS_CALLER_BRANCH", "AIPASS_CALLER_IDENTITY_SOURCE")


def help_block() -> str:
    """The door's block of the @git help page, its refusals rendered from the constants above.

    Lives beside the constants it renders; it moved here from git_module when
    that file reached its 1,500-line cap (2026-10-01).
    """
    placeholders = {
        "caller": "<caller>",
        "path": "<path>",
        "verb": "<verb>",
        "toplevel": "<toplevel>",
        "repo": "<repo>",
        "branch": "<branch>",
        "upstream": "<upstream>",
        "ahead": "<n>",
        "behind": "<m>",
    }
    refusals = (
        REFUSE_NOT_ADMIN,
        REFUSE_LANE_DARK.replace("{reason}", "<reason>"),
        REFUSE_VERB,
        REFUSE_NO_VALUE,
        REFUSE_TWICE,
        REFUSE_MISSING,
        REFUSE_NOT_DIR,
        REFUSE_NOT_REPO,
        REFUSE_NOT_TOP,
        REFUSE_AIPASS,
        REFUSE_DIRTY,
        REFUSE_DIVERGED,
        REFUSE_CONFLICT,
        REFUSE_RUN_SUB.replace("{sub}", "<sub>"),
        REFUSE_RUN_SHORT_FLAG,
        REFUSE_NO_GITHUB,
    )
    lines = "".join(f"    {text.format(**placeholders)}\n" for text in refusals)
    return (
        "External-repo door — admin seat only (DPLAN-0344):\n"
        "  status | diff [--staged] | log [count] | commit <msg> [--all | files] | push | tag <name>  --repo <path>\n"
        "  fetch | sync | merge-upstream  --repo <path>\n"
        "  tracked <path ...> | untrack [--recursive] <path ...>  --repo <path>  (paths repo-relative)\n"
        "  Runs the verb in another git repo (projects/baud, a clone outside the tree).\n"
        "  fetch fetches origin and prints ahead/behind against the branch's upstream, with\n"
        "  the commits on each side; nothing local moves. sync does the same fetch, then\n"
        "  fast-forwards the branch onto its upstream (git merge --ff-only). It refuses a\n"
        "  tracked change in the tree and a diverged branch (both lists printed): it never\n"
        "  rebases, merges, stashes or resets. AIPass's own sync and smart-sync are not these.\n"
        "  merge-upstream is the cure for diverged: the same checks, then one merge commit\n"
        "  (git merge --no-edit) bringing the upstream in. A conflict is aborted, the tree left\n"
        "  as it was, and the conflicted paths named. It never pushes: push is its own verb.\n"
        "  <path> is absolute, or relative to the AIPass root (not your cwd), and must be\n"
        "  that repo's top level. --repo=<path> works too, in any slot.\n"
        "  Checked on EVERY use against @ai_mail's verified-caller rail — the 5-leg admin\n"
        "  grant, never cached. Project managers keep their own CWD-bound owner tier;\n"
        "  --repo is not theirs. No AIPass PR lock is taken (git's index.lock serialises).\n"
        "  commit never pushes, as at home: push is its own verb. commit --all runs the\n"
        "  same lint and test gate there it runs anywhere; file paths are repo-relative.\n"
        "  gh run list | view <id> [--log | --log-failed] | watch <id>  --repo <path>\n"
        "  reads the repo's GitHub Actions runs: the door derives OWNER/NAME from the repo's\n"
        "  origin URL (https or ssh) and hands gh --repo OWNER/NAME. rerun, cancel, delete and\n"
        "  download stay home-only. Only a --repo value naming a directory is the door's:\n"
        "  anything else, and every --repo on issue and workflow, is gh's own OWNER/NAME.\n"
        "  Every use, refusals included, is one line in .ai_central/git_repo_door.jsonl:\n"
        "  caller, cwd, verb, args, repo, HEAD before and after, exit code.\n"
        "  Refusals, exactly as printed:\n" + lines
    )


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
        # Through @ai_mail's door (DPLAN-0404): the admin contract has one home
        # and this door consumes it rather than mirroring it. Lazy, so a dark
        # lane refuses instead of breaking @git.
        from aipass.ai_mail.apps.modules import door_verified_caller as rail
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
    """The top level of the git work tree *directory* is in, or None if it is in none.

    Raises OSError or SubprocessError when git itself cannot run: that is a
    failure to report, never an answer of "not a repository".
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            cwd=str(directory),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("git repo door: git rev-parse failed in %s: %s", directory, exc)
        raise
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
    try:
        toplevel = _git_toplevel(resolved)
    except (OSError, subprocess.SubprocessError) as exc:
        return RepoTarget(None, REFUSE_GIT_FAILED.format(path=raw, reason=exc))
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


class _GitFailed(Exception):
    """git could not run in the door's repo, or answered a call the door needed with an error."""


class _DoorRefusal(Exception):
    """The repo is in a state the verb refuses to act on; the message is the refusal, printed exactly."""


class Standing(NamedTuple):
    """Where the checked-out branch stands against its upstream, after a fetch."""

    branch: str
    upstream: str
    ahead: list[str]
    behind: list[str]


def _run_git(repo_root: Path, *argv: str) -> subprocess.CompletedProcess:
    """Run git in *repo_root*; raise _GitFailed when git cannot run or does not finish in time.

    The child never prompts: with GIT_TERMINAL_PROMPT=0 a credential prompt
    fails at once instead of waiting on a terminal nobody is at.
    """
    timeout = GIT_NETWORK_TIMEOUT if argv[0] in _NETWORK_VERBS else GIT_LOCAL_TIMEOUT
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    try:
        return subprocess.run(
            ["git", *argv], capture_output=True, text=True, cwd=str(repo_root), timeout=timeout, env=env
        )
    except subprocess.TimeoutExpired as exc:
        raise _GitFailed(f"git {argv[0]} timed out after {timeout} s in {repo_root}") from exc
    except (OSError, subprocess.SubprocessError) as exc:
        raise _GitFailed(f"git {argv[0]} could not run: {exc}") from exc


def _git_out(repo_root: Path, *argv: str) -> str:
    """git's stripped stdout for a call that must succeed; raise _GitFailed with git's own words if it does not."""
    result = _run_git(repo_root, *argv)
    if result.returncode != 0:
        raise _GitFailed(f"git {argv[0]} failed: {(result.stderr or result.stdout).strip()}")
    return result.stdout.strip()


def _commit_lines(repo_root: Path, rev_range: str) -> list[str]:
    """``<short sha> <subject>`` for each commit in *rev_range*, newest first."""
    listing = _git_out(repo_root, "log", "--format=%h %s", rev_range)
    return listing.splitlines() if listing else []


def _fetch_standing(repo_root: Path, verb: str) -> Standing:
    """Fetch origin, then read where the checked-out branch stands against its upstream.

    Moves only the remote-tracking refs. Raises _DoorRefusal for a detached HEAD
    or a branch with no upstream, _GitFailed when git cannot do what was asked.
    """
    branch = _run_git(repo_root, "symbolic-ref", "--quiet", "--short", "HEAD")
    name = branch.stdout.strip() if branch.returncode == 0 else ""
    if not name:
        raise _DoorRefusal(REFUSE_HEAD_DETACHED.format(verb=verb, repo=repo_root))
    _git_out(repo_root, "fetch", _REMOTE)
    upstream = _run_git(repo_root, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    upstream_name = upstream.stdout.strip() if upstream.returncode == 0 else ""
    if not upstream_name:
        raise _DoorRefusal(REFUSE_NO_UPSTREAM.format(verb=verb, branch=name, repo=repo_root, fetched=_REMOTE))
    return Standing(
        name,
        upstream_name,
        _commit_lines(repo_root, f"{upstream_name}..HEAD"),
        _commit_lines(repo_root, f"HEAD..{upstream_name}"),
    )


def _commit_block(title: str, commits: list[str]) -> str:
    """A titled list of commits, one per line, indented; empty when there are none."""
    if not commits:
        return ""
    return f"\n{title} (newest first):\n" + "\n".join(f"  {line}" for line in commits)


def _standing_text(standing: Standing) -> str:
    """The ahead/behind line and both commit lists, for the reader to decide on."""
    return (
        f"'{standing.branch}' against {standing.upstream}: "
        f"ahead {len(standing.ahead)}, behind {len(standing.behind)}."
        + _commit_block(f"Behind: on {standing.upstream}, not here", standing.behind)
        + _commit_block(f"Ahead: here, not on {standing.upstream}", standing.ahead)
    )


def _door_failure(verb: str, repo_root: Path, exc: Exception) -> dict:
    """The answer for a fetch or sync git could not complete, logged once."""
    logger.warning("git repo door: %s in %s did not complete: %s", verb, repo_root, exc)
    return {"stdout": "", "stderr": f"{verb} failed in {repo_root}: {exc}", "exit_code": 1}


def fetch_report(repo_root: Path) -> dict:
    """``fetch --repo``: fetch origin, then show ahead/behind and the commits on each side.

    Changes no working tree and no local branch; only the remote-tracking refs move.
    """
    try:
        standing = _fetch_standing(repo_root, "fetch")
    except _DoorRefusal as refusal:
        return {"stdout": "", "stderr": str(refusal), "exit_code": 1}
    except _GitFailed as exc:
        return _door_failure("fetch", repo_root, exc)
    return {"stdout": f"Fetched {_REMOTE} in {repo_root}.\n{_standing_text(standing)}", "stderr": "", "exit_code": 0}


def sync_fast_forward(repo_root: Path) -> dict:
    """``sync --repo``: fetch, then fast-forward the checked-out branch onto its upstream.

    Refuses a tracked change in the working tree (before fetching), and refuses a
    branch that has diverged, printing both lists. Never rebases, never makes a
    merge commit, never stashes or resets: ``git merge --ff-only`` or nothing.
    """
    try:
        if _git_out(repo_root, "status", "--porcelain", "--untracked-files=no"):
            raise _DoorRefusal(REFUSE_DIRTY.format(verb="sync", repo=repo_root))
        standing = _fetch_standing(repo_root, "sync")
        if standing.ahead and standing.behind:
            raise _DoorRefusal(
                REFUSE_DIVERGED.format(
                    branch=standing.branch,
                    upstream=standing.upstream,
                    repo=repo_root,
                    ahead=len(standing.ahead),
                    behind=len(standing.behind),
                )
                + _commit_block(f"Behind: on {standing.upstream}, not here", standing.behind)
                + _commit_block(f"Ahead: here, not on {standing.upstream}", standing.ahead)
            )
        if not standing.behind:
            text = f"Nothing to fast-forward in {repo_root}. {_standing_text(standing)}"
            return {"stdout": text, "stderr": "", "exit_code": 0}
        _git_out(repo_root, "merge", "--ff-only", standing.upstream)
    except _DoorRefusal as refusal:
        return {"stdout": "", "stderr": str(refusal), "exit_code": 1}
    except _GitFailed as exc:
        return _door_failure("sync", repo_root, exc)
    text = (
        f"Fast-forwarded '{standing.branch}' onto {standing.upstream} in {repo_root}: "
        f"{len(standing.behind)} commit(s)." + _commit_block("Now here", standing.behind)
    )
    return {"stdout": text, "stderr": "", "exit_code": 0}


def _merge_or_abort(repo_root: Path, standing: Standing) -> str:
    """Merge the upstream with a merge commit and return its short sha; on a conflict, abort and refuse.

    The conflicted paths are read BEFORE the abort, which is what puts HEAD,
    index and tree back exactly as they were.
    """
    merge = _run_git(repo_root, "merge", "--no-edit", standing.upstream)
    if merge.returncode == 0:
        return _git_out(repo_root, "rev-parse", "--short", "HEAD")
    conflicted = _run_git(repo_root, "diff", "--name-only", "--diff-filter=U").stdout.split()
    abort = _run_git(repo_root, "merge", "--abort")
    if not conflicted:
        raise _GitFailed(f"git merge failed: {(merge.stderr or merge.stdout).strip()}")
    if abort.returncode != 0:
        raise _GitFailed(f"git merge --abort failed after a conflict: {abort.stderr.strip()}")
    raise _DoorRefusal(
        REFUSE_CONFLICT.format(branch=standing.branch, upstream=standing.upstream, repo=repo_root)
        + "".join(f"\n  {path}" for path in conflicted)
    )


def merge_upstream(repo_root: Path) -> dict:
    """``merge-upstream --repo``: bring the upstream into a diverged branch with one merge commit.

    The ordinary cure when the owner merged on GitHub while this seat committed
    locally. Refuses a tracked change first (sync's check), fast-forwards when
    only behind, does nothing when nothing is behind, and on a conflict aborts and
    names the paths. Never rebases, resets, stashes or pushes.
    """
    try:
        if _git_out(repo_root, "status", "--porcelain", "--untracked-files=no"):
            raise _DoorRefusal(REFUSE_DIRTY.format(verb="merge-upstream", repo=repo_root))
        standing = _fetch_standing(repo_root, "merge-upstream")
        if not standing.behind:
            text = f"Nothing to merge in {repo_root}. {_standing_text(standing)}"
            return {"stdout": text, "stderr": "", "exit_code": 0}
        if not standing.ahead:
            _git_out(repo_root, "merge", "--ff-only", standing.upstream)
            text = (
                f"Fast-forwarded '{standing.branch}' onto {standing.upstream} in {repo_root}: "
                f"{len(standing.behind)} commit(s); no merge commit was needed."
                + _commit_block("Now here", standing.behind)
            )
            return {"stdout": text, "stderr": "", "exit_code": 0}
        merge_sha = _merge_or_abort(repo_root, standing)
    except _DoorRefusal as refusal:
        return {"stdout": "", "stderr": str(refusal), "exit_code": 1}
    except _GitFailed as exc:
        return _door_failure("merge-upstream", repo_root, exc)
    text = (
        f"Merged {standing.upstream} into '{standing.branch}' in {repo_root}: merge commit {merge_sha}, "
        f"{len(standing.behind)} commit(s) brought in."
        + _commit_block("Brought in", standing.behind)
        + "\nNothing was pushed: push is its own verb (drone @git push --repo <path>)."
    )
    return {"stdout": text, "stderr": "", "exit_code": 0}


def run_aims_at_door(flag: RepoFlag, aipass_root: Path) -> bool:
    """Whether a ``run`` --repo value is the door's path rather than gh's OWNER/NAME.

    ``projects/baud`` reads as either, so the disk decides: a value naming a
    directory (absolute, or relative to the AIPass root) is the door's, and
    anything else reaches gh untouched, as it always has.
    """
    if not flag.path:
        return False
    candidate = Path(flag.path).expanduser()
    if not candidate.is_absolute():
        candidate = aipass_root / candidate
    return candidate.is_dir()


def github_slug(url: str) -> str | None:
    """OWNER/NAME from a github.com remote URL, https or ssh, with or without ``.git``.

    None for any other host and for a local path: gh's --repo OWNER/NAME means
    github.com, so naming another host's repo that way would aim at a stranger.
    The URL is parsed, never printed: an https remote can carry a token.
    """
    url = url.strip()
    if "://" in url:
        parts = urlsplit(url)
        host, path = parts.hostname or "", parts.path
    else:
        user_host, colon, path = url.partition(":")
        if not colon:
            return None
        host = user_host.rpartition("@")[2]
    if host.lower() != _GITHUB_HOST:
        return None
    path = path.strip("/")
    if path.endswith(".git"):
        path = path[: -len(".git")]
    segments = path.split("/")
    if len(segments) != 2 or not all(segments):
        return None
    return path


def gh_run_args(args: list[str], repo_root: Path) -> tuple[list[str], str]:
    """The ``gh run`` args aimed at *repo_root*'s GitHub repo, or the refusal.

    Returns:
        ``(args + ["--repo", "OWNER/NAME"], "")`` for a read subcommand, or
        ``([], refusal)``. The write subcommands are refused here, after the
        admin grant and the repo were checked, and before gh is called.
    """
    if not args or args[0] not in RUN_READS:
        return [], REFUSE_RUN_SUB.format(sub=args[0] if args else "")
    # gh's only -R short flag is --repo: -R VALUE, -R=VALUE and the attached -RVALUE all name a repo.
    if any(arg.startswith("-R") for arg in args):
        return [], REFUSE_RUN_SHORT_FLAG
    try:
        slug = github_slug(_git_out(repo_root, "remote", "get-url", _REMOTE))
    except _GitFailed as exc:
        logger.warning("git repo door: no origin URL to name the GitHub repo in %s: %s", repo_root, exc)
        slug = None
    if slug is None:
        return [], REFUSE_NO_GITHUB.format(repo=repo_root)
    return [*args, REPO_FLAG, slug], ""


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
