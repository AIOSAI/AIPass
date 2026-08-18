# =================== AIPass ====================
# Name: remotes.py
# Description: Host API Remote Handler — where a repository points, for link-cards out
# Version: 1.0.0
# Created: 2026-08-17
# Modified: 2026-08-17
# =============================================

"""
Host API Remote Handler

Where a repository points, so the phone can offer a link out to it.

THIS LANE SHELLS NOTHING, and that is why it is its own module rather than one
more section of the repository reads. No door exists for it: @drone's surface
has no verb for it, the public Python surface has none, and the fleet's own gate
refuses both of the raw commands that would answer it — all three measured
before a line was written, and a refusal is evidence about intent. So the answer
is read where the tool itself keeps it, out of the repository's own
configuration file, with configparser rather than a subprocess. Worktrees are
followed to the repository that owns that file, because a worktree keeps a FILE
where an ordinary clone keeps a directory.

CREDENTIALS NEVER TRAVEL. A URL configured with a username and password is
answered with the secret replaced, and the raw value never reaches a response, a
log line or an audit record. That was built unasked, because a link-card is
exactly the kind of surface that ends up screenshotted.

The answer is always repo grain — a remote belongs to a repository, and the
branch only names which one.

Functions:
    read_git_remote() - The repository's remote, redacted, with a browsable form
"""

import configparser
from pathlib import Path
from typing import Any, Dict, Optional

from aipass.prax import logger
from aipass.api.apps.handlers.json import json_handler

from aipass.api.apps.handlers.host.reads import (
    GRAIN_REPO,
    ReadRefused,
    ReadUnavailable,
    repository_of,
    resolve_branch_root,
)

# The repository marker, which is a DIRECTORY in an ordinary clone and a FILE
# in a worktree — the shape that has already bitten one lane in this file.
GIT_MARKER = ".git"
CONFIG_FILE = "config"
GITDIR_PREFIX = "gitdir:"
COMMONDIR_FILE = "commondir"

# Configuration names a remote as a subsection: remote "origin".
REMOTE_SECTION_PREFIX = "remote "
REMOTE_URL_KEY = "url"
DEFAULT_REMOTE = "origin"

# Remote URL forms. ssh has no browsable shape of its own, so it is the only
# family converted; http already is one and is left exactly as configured.
SCHEME_SEPARATOR = "://"
BROWSABLE_SCHEMES = ("http", "https")
SSH_SCHEMES = ("ssh", "git", "git+ssh")
WEB_SCHEME = "https"
CLONE_SUFFIX = ".git"
REDACTION = "***"


def read_git_remote(branch: str, project: str = "") -> Dict[str, Any]:
    """
    The repository's remote — what the phone's link-cards are built from.

    THE DOOR WAS MEASURED BEFORE ANY OF THIS WAS DESIGNED, and there is none:
    no verb on drone's git surface, nothing on drone's public Python surface,
    and the fleet's own gate refuses BOTH raw readers because neither sits in
    its read-only allowlist. So this lane shells nothing at all and reads the
    repository's configuration as the INI file it is. That leaves the
    drone-only rule this package documents intact instead of quietly carving an
    exception into it for one lane. A verb on drone retires every line below,
    and it has been asked for.

    A REMOTE IS A REPOSITORY FACT, so the grain says repo and the branch names
    WHICH repository — the same vocabulary the log and commit lanes use.

    Args:
        branch: Branch name, resolved through the same two doors as every other
            read — the local citizen registry for the seat, @baud's census for
            any foreign project.
        project: Optional project name. Empty means the seat.

    Returns:
        Dict with branch, grain, remote (which one answered), url (as
        configured, any password redacted), web (a browsable form, or None) and
        redacted.

    Raises:
        ReadRefused: Unknown branch, or a repository with no remote at all —
            which is not hypothetical, two projects in the real tree have none.
        ReadUnavailable: No repository above the branch, an unreadable
            configuration, or a worktree pointer leading nowhere.
    """
    root = resolve_branch_root(branch, project)
    configuration = _repository_config(root)
    name, configured = _configured_remote(configuration)
    url, redacted = _without_credentials(configured)

    json_handler.log_operation(
        "host_api_git_remote_read",
        # The URL itself never reaches an audit line: it is the one field here
        # that can carry a secret, and a redacted copy is still not a fact worth
        # writing to disk on every read.
        {"branch": branch, "remote": name, "redacted": redacted},
    )

    return {
        "branch": branch,
        "grain": GRAIN_REPO,
        "remote": name,
        "url": url,
        "web": _browsable(configured),
        "redacted": redacted,
    }


def _repository_config(root: Path) -> Path:
    """
    The configuration file of the repository a branch lives in.

    Args:
        root: The branch directory.

    Returns:
        Path to the configuration file.

    Raises:
        ReadUnavailable: No repository above it, or no readable configuration.
    """
    repository = repository_of(root.resolve())

    if repository is None:
        raise ReadUnavailable(f"No repository above {root.name} — nothing here has a remote to name")

    marker = repository / GIT_MARKER
    directory = marker if marker.is_dir() else _pointed_at(marker)
    configuration = directory / CONFIG_FILE

    if not configuration.is_file():
        raise ReadUnavailable(f"The repository above {root.name} has no readable configuration")

    return configuration


def _pointed_at(marker: Path) -> Path:
    """
    Follow a worktree's pointer file to the directory that holds configuration.

    Args:
        marker: The repository marker, here a FILE rather than a directory.

    Returns:
        The directory whose configuration governs this tree.

    Raises:
        ReadUnavailable: The file points nowhere, or points at something absent.
            A fallback here would invent a repository, which is worse than a
            503 that names what was actually found.

    Note:
        A worktree's own directory holds NO configuration — the repository it
        was cut from does, and commondir is the pointer across to it. Following
        only the first hop would answer with a file that is not there.
    """
    text = marker.read_text(encoding="utf-8", errors="replace").strip()

    if not text.startswith(GITDIR_PREFIX):
        raise ReadUnavailable(f"{marker.name} is a file, but it does not point anywhere")

    pointed = Path(text[len(GITDIR_PREFIX) :].strip())
    if not pointed.is_absolute():
        pointed = marker.parent / pointed

    if not pointed.is_dir():
        raise ReadUnavailable(f"{marker.name} points at {pointed}, which is not there")

    shared = pointed / COMMONDIR_FILE
    if not shared.is_file():
        return pointed

    common = Path(shared.read_text(encoding="utf-8", errors="replace").strip())
    if not common.is_absolute():
        common = pointed / common

    if not common.is_dir():
        raise ReadUnavailable(f"{COMMONDIR_FILE} points at {common}, which is not there")

    return common.resolve()


def _configured_remote(configuration: Path) -> Any:
    """
    Which remote answers for this repository, and the URL it carries.

    Args:
        configuration: Path to the repository's configuration file.

    Returns:
        (name, url).

    Raises:
        ReadRefused: No remote is configured at all. An empty string would
            render as a link card pointing nowhere.
        ReadUnavailable: The configuration could not be parsed.

    Note:
        origin wins by convention when several exist, but the name TRAVELS
        either way — refusing a repository that simply called its remote
        something else would be this lane inventing a rule that does not exist,
        and answering silently would make the choice invisible to the caller.
    """
    parser = configparser.ConfigParser(strict=False)

    try:
        parser.read(configuration, encoding="utf-8")
    except configparser.Error as e:
        logger.error("[host_api] repository configuration would not parse: %s", e)
        raise ReadUnavailable(f"The repository configuration could not be read: {e}") from e

    remotes = []
    for section in parser.sections():
        if not section.startswith(REMOTE_SECTION_PREFIX):
            continue
        url = parser.get(section, REMOTE_URL_KEY, fallback="").strip()
        if not url:
            continue
        remotes.append((section[len(REMOTE_SECTION_PREFIX) :].strip().strip('"'), url))

    if not remotes:
        raise ReadRefused("This repository has no remote configured — there is no forge to link to")

    for name, url in remotes:
        if name == DEFAULT_REMOTE:
            return name, url

    return remotes[0]


def _without_credentials(url: str) -> Any:
    """
    The configured URL with any password replaced, and whether one was there.

    Args:
        url: The URL exactly as configured.

    Returns:
        (url, redacted).

    Note:
        THIS WAS NOT IN THE ASK. A remote may carry user:token@ — that is how a
        machine clones a private repository with no human present — and this
        lane's whole job is handing that URL to a client over a network. The
        user survives so an operator still recognises their own configuration;
        only the secret half is replaced, and the boolean is what stops the
        change being silent. A bare user with no colon is the standard ssh form
        and carries no secret: flagging it would cry wolf on the commonest
        remote there is, and an alarm that fires on everything is unread.
    """
    separator = url.find(SCHEME_SEPARATOR)
    if separator == -1:
        return url, False

    scheme = url[:separator]
    rest = url[separator + len(SCHEME_SEPARATOR) :]

    at = rest.rfind("@")
    if at == -1:
        return url, False

    userinfo = rest[:at]
    if ":" not in userinfo:
        return url, False

    user = userinfo.split(":", 1)[0]
    logger.info("[host_api] a credential in a remote URL was redacted before it left this process")

    return f"{scheme}{SCHEME_SEPARATOR}{user}:{REDACTION}@{rest[at + 1 :]}", True


def _browsable(url: str) -> Optional[str]:
    """
    A URL a person can open, or None when there honestly is not one.

    Args:
        url: The URL exactly as configured.

    Returns:
        The browsable form, or None for anything that is not a web address —
        a filesystem path is a directory, not a page, and putting a scheme in
        front of one would be a link card leading somewhere never existed.
    """
    scheme, host, path = _url_parts(url)

    if scheme is None:
        return None

    if scheme in BROWSABLE_SCHEMES:
        # http is NOT upgraded. ssh has no browsable form of its own so
        # converting it is forced; http already is one, and changing it would be
        # this lane deciding something about a host it cannot know.
        target = scheme
    elif scheme in SSH_SCHEMES:
        target = WEB_SCHEME
    else:
        logger.info("[host_api] no browsable form for a %r remote", scheme)
        return None

    trimmed = path[: -len(CLONE_SUFFIX)] if path.endswith(CLONE_SUFFIX) else path

    return f"{target}{SCHEME_SEPARATOR}{host}/{trimmed}"


def _url_parts(url: str) -> Any:
    """
    Split a remote URL into scheme, host and path.

    Args:
        url: The URL exactly as configured.

    Returns:
        (scheme, host, path), or (None, "", "") for anything with no host in it.
        Any userinfo is dropped here — a browsable link needs no identity, and
        this is the one place that guarantees none reaches one.
    """
    separator = url.find(SCHEME_SEPARATOR)

    if separator == -1:
        return _short_form_parts(url)

    scheme = url[:separator]
    authority, _, path = url[separator + len(SCHEME_SEPARATOR) :].partition("/")

    return scheme, authority.rsplit("@", 1)[-1], path


def _short_form_parts(url: str) -> Any:
    """
    The scp-like form, host-colon-path, told apart from a filesystem path.

    Args:
        url: The URL exactly as configured.

    Returns:
        (scheme, host, path), or (None, "", "").

    Note:
        THE TRAP: a Windows path carries a colon too, so both halves are checked
        rather than assumed. The host half may hold no separator and the path
        half may not START with one — which is exactly what a drive letter
        followed by a backslash does, and reading that as a host would emit a
        link card pointing at a machine named C.
    """
    host_part, separator, path = url.partition(":")

    if not separator or not path:
        return None, "", ""

    if "/" in host_part or "\\" in host_part:
        return None, "", ""

    if path[0] in ("/", "\\"):
        return None, "", ""

    host = host_part.rsplit("@", 1)[-1]
    if not host:
        return None, "", ""

    return WEB_SCHEME, host, path
