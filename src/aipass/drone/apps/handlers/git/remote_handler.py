# =================== AIPass ====================
# Name: remote_handler.py
# Description: Where a repository points — remote names and urls, credentials redacted
# Version: 1.0.0
# Created: 2026-08-18
# Modified: 2026-10-17
# =============================================

"""Read a repository's remotes — the door that did not exist.

Reference: docs/git_interface.md
"""

from __future__ import annotations

import subprocess

from aipass.prax import logger
from aipass.drone.apps.handlers.json import json_handler
from aipass.drone.apps.handlers.git.lock_handler import find_repo_root

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


def list_remotes() -> dict:
    """List the repository's remotes, with credentials redacted.

    Callers MUST check ``ok``: no remote is ok=True with an empty list, same shape as an error.
    """
    repo_root = find_repo_root()

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
