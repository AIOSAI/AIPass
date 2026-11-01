# =================== AIPass ====================
# Name: remote_handler.py
# Description: Where a repository points — remote names and urls, credentials redacted
# Version: 1.1.0
# Created: 2026-08-18
# Modified: 2026-10-30
# =============================================

"""Read a repository's remotes, and point one at a github.com repository.

Reference: docs/git_interface.md
"""

from __future__ import annotations

import re
import subprocess
import time
from pathlib import Path

from aipass.prax import logger
from aipass.drone.apps.handlers.json import json_handler
from aipass.drone.apps.handlers.deletion_log import append_ledger_line
from aipass.drone.apps.handlers.git.lock_handler import find_repo_root
from aipass.drone.apps.handlers.git.repo_door import GIT_LOCAL_TIMEOUT, home_ledger

LEDGER_NAME = "git_remote_sets.jsonl"
_REMOTE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
# No userinfo in the https form: a token in the url would sit in .git/config in clear.
_GITHUB_URL = re.compile(
    r"(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+"
)
REFUSE_SET_USAGE = "Usage: drone @git remote set <name> <url> [--repo <path>]"
REFUSE_NAME = "remote set refused: '{name}' is not a remote name (letters, digits, '.', '_', '-')."
REFUSE_URL = (
    "remote set refused: the url must name a github.com repository with no credentials: "
    "https://github.com/OWNER/NAME, git@github.com:OWNER/NAME or ssh://git@github.com/OWNER/NAME."
)

# Neither a remote name nor a url can contain a tab, so the split is safe where spaces are not.
_ROW_SEPARATOR = "\t"
_FETCH_MARKER = "(fetch)"
_PUSH_MARKER = "(push)"

_SCHEME_SEPARATOR = "://"
_CREDENTIAL_SCHEMES = ("http", "https")
_USERINFO_SEPARATOR = "@"
_REDACTION = "***"


def _without_credentials(url: str) -> tuple[str, bool]:
    """Strip any credential component from *url*.

    The WHOLE userinfo goes: a token in ``https://<TOKEN>@host`` sits in the username slot.
    """
    scheme, separator, rest = url.partition(_SCHEME_SEPARATOR)
    if not separator or scheme.lower() not in _CREDENTIAL_SCHEMES:
        # scp-style and ssh users are the SSH account name, not a secret.
        return url, False

    # The LAST '@' separates credentials from host; a password may contain '@'.
    userinfo, found, host_and_path = rest.rpartition(_USERINFO_SEPARATOR)
    if not found or not userinfo:
        return url, False

    return f"{scheme}{_SCHEME_SEPARATOR}{_REDACTION}{_USERINFO_SEPARATOR}{host_and_path}", True


def _parse_remotes(stdout: str) -> list[dict]:
    """Fold git's two rows per remote into one entry each.

    Fetch and push stay apart: fetching from a mirror and pushing elsewhere is ordinary.
    """
    entries: dict[str, dict] = {}

    for line in stdout.splitlines():
        name, separator, remainder = line.partition(_ROW_SEPARATOR)
        if not separator or not name.strip():
            continue

        raw_url = remainder.rsplit(" ", 1)[0].strip() if remainder.endswith(")") else remainder.strip()
        if not raw_url:
            continue

        url, redacted = _without_credentials(raw_url)
        entry = entries.setdefault(name, {"name": name, "fetch": "", "push": "", "redacted": False})
        entry["redacted"] = entry["redacted"] or redacted

        if remainder.endswith(_PUSH_MARKER):
            entry["push"] = url
        elif remainder.endswith(_FETCH_MARKER):
            entry["fetch"] = url
        else:
            entry["fetch"] = entry["fetch"] or url

    return list(entries.values())


def list_remotes(repo_root: Path | None = None) -> dict:
    """List the repository's remotes, with credentials redacted.

    Callers MUST check ``ok``: no remote is ok=True with an empty list, same shape as an error.
    """
    repo_root = repo_root or find_repo_root()

    try:
        result = subprocess.run(
            ["git", "remote", "-v"],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.error("remote listing failed: %s", exc)
        return {"ok": False, "remotes": [], "count": 0, "message": f"remote listing failed: {exc}"}

    if result.returncode != 0:
        return {
            "ok": False,
            "remotes": [],
            "count": 0,
            "message": f"remote error: {result.stderr.strip()}",
        }

    remotes = _parse_remotes(result.stdout)
    count = len(remotes)
    message = f"{count} remote(s)" if count else "no remote configured"

    # Never a url, even redacted.
    json_handler.log_operation(
        "list_remotes",
        {"count": count, "names": [r["name"] for r in remotes], "redacted": any(r["redacted"] for r in remotes)},
    )
    logger.info(message)

    return {"ok": True, "remotes": remotes, "count": count, "message": message}


def _git(repo_root: Path, *argv: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *argv], capture_output=True, text=True, cwd=str(repo_root), timeout=GIT_LOCAL_TIMEOUT)


def _record_set(record: dict) -> None:
    """One remote-set record to prax and the ledger; a ledger that cannot be written never loses the answer."""
    logger.info(
        "git remote set: %s %s in %s by %s", record["outcome"], record["name"], record["repo"], record["caller"]
    )
    json_handler.log_operation("set_remote", record)
    try:
        append_ledger_line(record, home_ledger(LEDGER_NAME))
    except Exception as exc:
        logger.error("git remote set: failed to write the ledger for %s: %s", record["repo"], exc)


def set_remote(args: list[str], repo_root: Path, caller: str) -> dict:
    """Point remote *name* of *repo_root* at a github.com url: add it when absent, re-point it when present."""
    if len(args) != 2:
        return {"stdout": "", "stderr": REFUSE_SET_USAGE, "exit_code": 1}
    name, url = args
    if not _REMOTE_NAME.fullmatch(name):
        return {"stdout": "", "stderr": REFUSE_NAME.format(name=name), "exit_code": 1}
    if not _GITHUB_URL.fullmatch(url):
        return {"stdout": "", "stderr": REFUSE_URL, "exit_code": 1}

    try:
        current = _git(repo_root, "remote", "get-url", name)
        old = _without_credentials(current.stdout.strip())[0] if current.returncode == 0 else ""
        if old == url:
            outcome, result = "unchanged", None
        else:
            verb = "set-url" if current.returncode == 0 else "add"
            result = _git(repo_root, "remote", verb, name, url)
            outcome = "set" if result.returncode == 0 else "failed"
    except (OSError, subprocess.SubprocessError) as exc:
        logger.error("git remote set failed in %s: %s", repo_root, exc)
        return {"stdout": "", "stderr": f"remote set failed: {exc}", "exit_code": 1}

    record = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "caller": caller,
        "repo": str(repo_root),
        "name": name,
        "old": old,
        "new": url,
        "outcome": outcome,
    }
    _record_set(record)
    if result is not None and result.returncode != 0:
        return {"stdout": "", "stderr": f"remote set failed: {result.stderr.strip()}", "exit_code": 1}
    if outcome == "unchanged":
        return {"stdout": f"Remote '{name}' in {repo_root} already points at {url}.", "stderr": "", "exit_code": 0}
    return {"stdout": f"Remote '{name}' in {repo_root}: {old or '(none)'} -> {url}", "stderr": "", "exit_code": 0}
