# =================== AIPass ====================
# Name: fetch.py
# Description: Fetch a baud phone-bundle release: public download first, then the token API route
# Version: 1.0.0
# Created: 2026-09-13
# Modified: 2026-09-13
# =============================================

"""
Fetch the phone bundle and its SHA256SUMS from a baud release (FPLAN-0587).

Two doors, tried in order:

1. The public release download, ``github.com/AIOSAI/baud/releases/download/<tag>/<asset>``.
   Works once the repo is public; answers 404 while it is private.
2. With a token (``GITHUB_TOKEN``, else the gh CLI's stored token when gh is on
   PATH), the GitHub API: read the release record, find each asset's API url,
   download it with ``Accept: application/octet-stream``.

No token and a 404 is reported as what it is: the repo is private or the asset
is missing. The message names ``--from``.

WHY "latest" RESOLVES THE TAG FIRST
-----------------------------------
The tarball's asset name carries the tag (``baud-phone-<tag>.tar.gz``), so
``releases/latest/download/<asset>`` cannot name it without already knowing the
tag. The public door follows ``releases/latest``'s redirect to
``releases/tag/<tag>``; the API door reads ``tag_name``. Both files are then
fetched from that ONE tag, so a release published mid-fetch cannot pair one
tag's tarball with another tag's SHA256SUMS.

WHY THE TOKEN IS AN UNREDIRECTED HEADER
---------------------------------------
The API answers an asset download with a redirect to a signed storage URL on
another host. urllib copies ordinary headers onto the redirected request, which
would hand the token to that host (and make the signed URL refuse the double
auth). ``add_unredirected_header`` keeps it on the api.github.com hop only.
The token is never logged and never printed.

stdlib urllib only: no new dependency.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from aipass.prax import logger
from aipass.aipass.apps.handlers.json import json_handler

REPO = "AIOSAI/baud"
LATEST = "latest"
SUMS_ASSET = "SHA256SUMS.txt"
PUBLIC_BASE = f"https://github.com/{REPO}/releases"
API_BASE = f"https://api.github.com/repos/{REPO}/releases"
_API_HOST_PREFIX = "https://api.github.com/"
_USER_AGENT = "aipass-baud-install"
_JSON_ACCEPT = "application/vnd.github+json"
_OCTET_ACCEPT = "application/octet-stream"

_META_TIMEOUT = 20
_DOWNLOAD_TIMEOUT = 120
_CHUNK = 1 << 16

_TAG_SHAPE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_TAG_FROM_URL = re.compile(r"/releases/tag/([^/?#]+)/?$")


class FetchError(Exception):
    """A release could not be fetched. The message is safe to print."""


@dataclass(frozen=True)
class FetchedRelease:
    """Two files on disk, both from one tag, and which door delivered them."""

    tag: str
    tarball: Path
    sums: Path
    source: str


def phone_asset_name(tag: str) -> str:
    """The release asset name of the phone bundle for `tag`."""
    return f"baud-phone-{tag}.tar.gz"


def validate_tag(tag: str) -> str:
    """Return `tag` when it is a safe release tag, else raise FetchError.

    A tag becomes part of a file name and a URL path, so anything outside
    letters, digits, dot, dash and underscore is refused (no ``..``, no ``/``).
    """
    if tag == LATEST or (_TAG_SHAPE.match(tag) and ".." not in tag):
        return tag
    raise FetchError(f"'{tag}' is not a release tag (expected something like v0.2.0, or 'latest').")


def resolve_token() -> str | None:
    """A GitHub token from GITHUB_TOKEN, else from the gh CLI, else None.

    Never logs the token or gh's output: only whether one was found.
    """
    env_token = os.environ.get("GITHUB_TOKEN", "").strip()
    if env_token:
        return env_token
    gh = shutil.which("gh")
    if gh is None:
        return None
    try:
        proc = subprocess.run([gh, "auth", "token"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError) as exc:
        logger.info("[baud] gh token lookup did not run: %s", type(exc).__name__)
        return None
    token = (proc.stdout or "").strip()
    if proc.returncode != 0 or not token:
        logger.info("[baud] gh token lookup gave no token (exit %s)", proc.returncode)
        return None
    return token


def _download(req: urllib.request.Request, target: Path) -> Path:
    """Stream one response body to `target`."""
    with urllib.request.urlopen(req, timeout=_DOWNLOAD_TIMEOUT) as resp, target.open("wb") as out:
        shutil.copyfileobj(resp, out, _CHUNK)
    return target


def _public_request(url: str) -> urllib.request.Request:
    """An unauthenticated request."""
    return urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})


def _api_request(url: str, token: str, accept: str) -> urllib.request.Request:
    """An api.github.com request whose token never follows a redirect."""
    if not url.startswith(_API_HOST_PREFIX):
        raise FetchError(f"Refusing to send a token to a non-API url: {url}")
    req = urllib.request.Request(url, headers={"Accept": accept, "User-Agent": _USER_AGENT})
    req.add_unredirected_header("Authorization", f"Bearer {token}")
    return req


def _resolve_public_latest() -> str:
    """Follow releases/latest's redirect and read the tag off the final url."""
    with urllib.request.urlopen(_public_request(f"{PUBLIC_BASE}/latest"), timeout=_META_TIMEOUT) as resp:
        final_url = resp.geturl()
    match = _TAG_FROM_URL.search(final_url)
    if match is None:
        raise FetchError(f"Could not read the latest baud tag from {final_url}.")
    return validate_tag(match.group(1))


def _fetch_public(tag: str, workdir: Path) -> FetchedRelease:
    """Door 1: the public release download."""
    real_tag = _resolve_public_latest() if tag == LATEST else tag
    base = f"{PUBLIC_BASE}/download/{real_tag}"
    asset = phone_asset_name(real_tag)
    sums = _download(_public_request(f"{base}/{SUMS_ASSET}"), workdir / SUMS_ASSET)
    tarball = _download(_public_request(f"{base}/{asset}"), workdir / asset)
    return FetchedRelease(tag=real_tag, tarball=tarball, sums=sums, source="github-release")


def _fetch_api(tag: str, workdir: Path, token: str) -> FetchedRelease:
    """Door 2: the API release record, then each asset as octet-stream."""
    url = f"{API_BASE}/latest" if tag == LATEST else f"{API_BASE}/tags/{tag}"
    with urllib.request.urlopen(_api_request(url, token, _JSON_ACCEPT), timeout=_META_TIMEOUT) as resp:
        release = json.loads(resp.read().decode("utf-8"))
    if not isinstance(release, dict):
        raise FetchError("GitHub's release record was not a JSON object.")
    real_tag = str(release.get("tag_name") or "")
    if not real_tag or real_tag == LATEST:
        raise FetchError("GitHub's release record carried no usable tag name.")
    validate_tag(real_tag)
    assets: dict[str, str] = {
        str(a["name"]): str(a["url"])
        for a in release.get("assets", [])
        if isinstance(a, dict) and a.get("name") and a.get("url")
    }
    asset = phone_asset_name(real_tag)
    missing = [name for name in (SUMS_ASSET, asset) if name not in assets]
    if missing:
        raise FetchError(
            f"Release {real_tag} has no {' or '.join(missing)} (a release older than the phone bundle carries none)."
        )
    sums = _download(_api_request(assets[SUMS_ASSET], token, _OCTET_ACCEPT), workdir / SUMS_ASSET)
    tarball = _download(_api_request(assets[asset], token, _OCTET_ACCEPT), workdir / asset)
    return FetchedRelease(tag=real_tag, tarball=tarball, sums=sums, source="github-api")


def _logged(release: FetchedRelease) -> FetchedRelease:
    """Record which tag arrived through which door, then hand the release back."""
    json_handler.log_operation(
        "baud_release_fetched",
        {"tag": release.tag, "source": release.source},
        module_name="baud",
    )
    return release


def fetch_release(
    tag: str,
    workdir: Path,
    token_provider: Callable[[], str | None] = resolve_token,
) -> FetchedRelease:
    """Download the phone tarball and SHA256SUMS for `tag` into `workdir`.

    Args:
        tag: A release tag, or "latest".
        workdir: An existing directory the two files land in.
        token_provider: Returns a GitHub token or None (seam for tests).

    Returns:
        The fetched release.

    Raises:
        FetchError: Offline, private repo without a token, missing asset, or
            any other refusal. The message is printable and names --from.
    """
    validate_tag(tag)
    hint = "Or install from a file: aipass baud install --from <tarball> --sums <SHA256SUMS.txt>"
    try:
        return _logged(_fetch_public(tag, workdir))
    except urllib.error.HTTPError as exc:
        if exc.code not in (403, 404):
            raise FetchError(f"GitHub answered HTTP {exc.code} for the baud release. {hint}") from exc
        public_code = exc.code
        logger.info("[baud] public release download answered %s, trying the API door", exc.code)
    except OSError as exc:
        raise FetchError(f"Could not reach GitHub ({getattr(exc, 'reason', exc)}). {hint}") from exc

    token = token_provider()
    if not token:
        raise FetchError(
            f"No public baud release asset found (HTTP {public_code}) and no GitHub token to try the API: "
            f"the repo may still be private, or this release has no phone bundle. "
            f"Set GITHUB_TOKEN or log in with the gh CLI. {hint}"
        )
    try:
        return _logged(_fetch_api(tag, workdir, token))
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise FetchError(f"GitHub rejected the token (HTTP 401). {hint}") from exc
        raise FetchError(
            f"GitHub answered HTTP {exc.code} for release '{tag}': not found, or the token cannot see {REPO}. {hint}"
        ) from exc
    except (OSError, ValueError) as exc:
        raise FetchError(f"The GitHub API download failed ({getattr(exc, 'reason', exc)}). {hint}") from exc
