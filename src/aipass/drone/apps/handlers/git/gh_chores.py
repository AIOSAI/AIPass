# =================== AIPass ====================
# Name: gh_chores.py
# Description: The owner tier's GitHub chores: the repo's OWNER/NAME, the gh call, the write ledger
# Version: 1.0.0
# Created: 2026-10-19
# Modified: 2026-10-19
# =============================================

"""Shared by ``release edit``, ``label`` and ``alerts``: one repo's GitHub, through gh.

OWNER/NAME is read from the repo's own origin, never taken from an argument, so a
write lands on the repo whose ownership the gate checked and on no other.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from aipass.prax import logger
from aipass.drone.apps.handlers.deletion_log import append_ledger_line
from aipass.drone.apps.handlers.git.repo_door import GIT_LOCAL_TIMEOUT, github_slug, home_ledger
from aipass.drone.apps.handlers.json import json_handler

LEDGER_NAME = "git_gh_writes.jsonl"
GH_TIMEOUT = 60

OUTCOME_WRITTEN = "written"
OUTCOME_UNCHANGED = "unchanged"

# Printed exactly; --help renders these same constants.
REFUSE_NO_GH = "{verb} needs the gh CLI, and gh is not installed here. Install: https://cli.github.com/"
REFUSE_NO_GITHUB = (
    "{verb} refused: the origin remote of {repo} does not name a github.com repository, "
    "so there is no OWNER/NAME to hand gh."
)
REFUSE_TIMEOUT = "{verb}: gh did not answer within {seconds} s for github.com/{slug}."
REFUSE_GH_FAILED = "{verb}: gh could not complete for github.com/{slug}: {reason}"
REFUSE_FLAG = "Unknown argument for '{verb}': {arg}"
REFUSE_NO_VALUE = "{verb} {flag} needs a value."


class ChoreRefusal(Exception):
    """The chore cannot run; the message is the refusal, printed exactly."""


def parse_flags(args: list[str], value_flags: tuple[str, ...], verb: str) -> tuple[list[str], dict[str, str]]:
    """``(positionals, {flag: value})``, each flag spaced or ``--flag=value``; raise ChoreRefusal."""
    positionals: list[str] = []
    values: dict[str, str] = {}
    rest = list(args)
    while rest:
        arg = rest.pop(0)
        if not arg.startswith("-"):
            positionals.append(arg)
            continue
        flag, equals, value = arg.partition("=")
        if flag not in value_flags:
            raise ChoreRefusal(REFUSE_FLAG.format(verb=verb, arg=arg))
        if not equals:
            if not rest:
                raise ChoreRefusal(REFUSE_NO_VALUE.format(verb=verb, flag=flag))
            value = rest.pop(0)
        values[flag] = value
    return positionals, values


def repo_slug(repo_root: Path, verb: str) -> str:
    """OWNER/NAME of *repo_root*'s origin on github.com; raise ChoreRefusal when it names none."""
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
            timeout=GIT_LOCAL_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("git %s: could not read the origin of %s: %s", verb, repo_root, exc)
        raise ChoreRefusal(REFUSE_NO_GITHUB.format(verb=verb, repo=repo_root)) from exc
    slug = github_slug(result.stdout) if result.returncode == 0 else None
    if slug is None:
        raise ChoreRefusal(REFUSE_NO_GITHUB.format(verb=verb, repo=repo_root))
    return slug


def gh(argv: list[str], *, verb: str, slug: str, stdin: str | None = None) -> str:
    """gh's stdout for one call; raise ChoreRefusal with gh's own words when it fails."""
    try:
        result = subprocess.run(["gh", *argv], capture_output=True, text=True, timeout=GH_TIMEOUT, input=stdin)
    except FileNotFoundError as exc:
        logger.warning("git %s: gh not found: %s", verb, exc)
        raise ChoreRefusal(REFUSE_NO_GH.format(verb=verb)) from exc
    except subprocess.TimeoutExpired as exc:
        logger.warning("git %s: gh %s timed out for %s", verb, argv[0], slug)
        raise ChoreRefusal(REFUSE_TIMEOUT.format(verb=verb, seconds=GH_TIMEOUT, slug=slug)) from exc
    if result.returncode != 0:
        reason = (result.stderr or result.stdout).strip()
        logger.warning("git %s: gh %s failed for %s: %s", verb, argv[0], slug, reason)
        raise ChoreRefusal(REFUSE_GH_FAILED.format(verb=verb, slug=slug, reason=reason))
    return result.stdout


def gh_json(argv: list[str], *, verb: str, slug: str) -> object:
    """gh's stdout parsed as JSON; raise ChoreRefusal when gh fails or answers something else."""
    text = gh(argv, verb=verb, slug=slug)
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        logger.warning("git %s: gh %s answered non-JSON for %s: %s", verb, argv[0], slug, exc)
        raise ChoreRefusal(
            REFUSE_GH_FAILED.format(verb=verb, slug=slug, reason=f"the answer was not JSON ({exc})")
        ) from exc


def is_not_found(refusal: ChoreRefusal) -> bool:
    """Whether gh's failure was GitHub answering 404."""
    return "HTTP 404" in str(refusal)


def record_write(*, caller: str, verb: str, repo_root: Path, slug: str, outcome: str, details: dict) -> dict:
    """Write one chore record to prax and the ledger, and return it. Never raises."""
    record = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "outcome": outcome,
        "caller": caller,
        "verb": verb,
        "repo": str(repo_root),
        "github": slug,
        **details,
    }
    logger.info("git %s: %s on github.com/%s by %s %s", verb, outcome, slug, caller, details)
    json_handler.log_operation("git_gh_write", {"verb": verb, "outcome": outcome, "github": slug, "caller": caller})
    try:
        append_ledger_line(record, home_ledger(LEDGER_NAME))
    except Exception as exc:
        logger.error("git %s: failed to write the ledger for github.com/%s: %s", verb, slug, exc)
    return record


def answer(text: str, exit_code: int = 0) -> dict:
    """A routing result: *text* on stdout when it succeeded, on stderr when it did not."""
    if exit_code:
        return {"stdout": "", "stderr": text, "exit_code": exit_code}
    return {"stdout": text, "stderr": "", "exit_code": 0}


def json_answer(document: dict, exit_code: int = 0) -> dict:
    """A --json routing result: one document on stdout, refusals included."""
    return {"stdout": json.dumps(document, indent=2), "stderr": "", "exit_code": exit_code}
