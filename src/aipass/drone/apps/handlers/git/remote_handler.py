# =================== AIPass ====================
# Name: remote_handler.py
# Description: Where a repository points — remote names and urls, credentials redacted
# Version: 1.0.0
# Created: 2026-08-18
# Modified: 2026-08-18
# =============================================

"""Read a repository's remotes — the door that did not exist.

@seedgo measured all three surfaces before ruling this absent (FPLAN-0438 round
4a): drone's git verbs, drone's public Python surface, and the fleet gate's
read-only allowlist. None answered "where does this repository point?", so
@api's host lane read ``.git/config`` as an INI file and hand-rolled its own
worktree-following to find that file. This door retires that, and the
worktree-following with it: git resolves a worktree's common directory itself,
so shelling the question is not merely allowed here — it is the reason the
answer is correct in a worktree without anyone writing code for the case.

READ-ONLY, GLOBAL TIER. Listing remotes writes nothing; every citizen may ask
where their repository points. Registered in GIT_ACCESS_TIERS["global"] —
without that entry the auth gate refuses the verb outright as unknown.

CREDENTIALS NEVER TRAVEL. An http(s) url configured with credentials is
answered with the whole userinfo component replaced, and the raw value reaches
no return, no log line, and no audit record. The ENTIRE component goes, not the
password alone: the common personal-access-token form is
``https://<TOKEN>@host/path``, where the secret sits in the username slot and a
password-only redaction would publish it verbatim.

SSH FORMS ARE LEFT ALONE, deliberately. In ``git@github.com:a/b.git`` and
``ssh://git@host/a/b.git`` the user is the standard SSH account name, not a
secret — redacting it would mangle every ordinary remote in the fleet to hide
nothing.
"""

from __future__ import annotations

import subprocess

from aipass.prax import logger
from aipass.drone.apps.handlers.json import json_handler
from aipass.drone.apps.handlers.git.lock_handler import find_repo_root

# `git remote -v` prints one row per direction: name, TAB, url, ' (fetch|push)'.
# Splitting on the tab is safe where splitting on spaces is not — a remote name
# cannot contain a tab, and neither can a url, but a url can be followed by one.
_ROW_SEPARATOR = "\t"
_FETCH_MARKER = "(fetch)"
_PUSH_MARKER = "(push)"

# Only the schemes that actually carry credentials are redacted.
_SCHEME_SEPARATOR = "://"
_CREDENTIAL_SCHEMES = ("http", "https")
_USERINFO_SEPARATOR = "@"
_REDACTION = "***"


def _without_credentials(url: str) -> tuple[str, bool]:
    """Strip any credential component from *url*.

    Args:
        url: A remote url exactly as git reported it.

    Returns:
        (safe_url, redacted) — the url with its userinfo replaced when the
        scheme is one that carries credentials, and whether anything was hidden.
    """
    scheme, separator, rest = url.partition(_SCHEME_SEPARATOR)
    if not separator or scheme.lower() not in _CREDENTIAL_SCHEMES:
        # No scheme at all is the scp-style form (git@host:path); a non-http
        # scheme is ssh or git. Neither carries a secret in its user slot.
        return url, False

    # rsplit: a password may legitimately contain '@', and the LAST one always
    # separates the credentials from the host.
    userinfo, found, host_and_path = rest.rpartition(_USERINFO_SEPARATOR)
    if not found or not userinfo:
        return url, False

    return f"{scheme}{_SCHEME_SEPARATOR}{_REDACTION}{_USERINFO_SEPARATOR}{host_and_path}", True


def _parse_remotes(stdout: str) -> list[dict]:
    """Fold git's two rows per remote into one entry each.

    Args:
        stdout: ``git remote -v`` output.

    Returns:
        A list of {name, fetch, push, redacted}, in the order git named them.
        Fetch and push are kept apart because they genuinely can differ — a
        repository fetching from a mirror and pushing to the real thing is an
        ordinary setup, and collapsing the pair would report the wrong one.
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
            # A direction git did not label; record it rather than drop the row.
            entry["fetch"] = entry["fetch"] or url

    return list(entries.values())


def list_remotes() -> dict:
    """List the repository's remotes, with credentials redacted.

    Returns:
        Dict with ok (bool — False only when git itself failed), remotes (list
        of {name, fetch, push, redacted}), count (int) and message (str).

        Callers MUST check ``ok``: a repository with no remote configured is a
        real answer — two projects in the live tree have none — and it returns
        ok=True with an empty list. An error that returned the same empty list
        would be indistinguishable from that, which is the exact false-green
        that made ``get_branch_status`` grow its own ok flag.
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

    # Names and whether anything was hidden — never a url. A redacted copy is
    # still not a fact worth writing to disk on every read.
    json_handler.log_operation(
        "list_remotes",
        {"count": count, "names": [r["name"] for r in remotes], "redacted": any(r["redacted"] for r in remotes)},
    )
    logger.info(message)

    return {"ok": True, "remotes": remotes, "count": count, "message": message}
