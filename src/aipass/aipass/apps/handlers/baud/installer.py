# =================== AIPass ====================
# Name: installer.py
# Description: The install chain of aipass baud: a tarball on disk or a fetched release, verified, unpacked, swapped
# Version: 1.0.0
# Created: 2026-09-13
# Modified: 2026-09-13
# =============================================

"""
The install chain behind ``aipass baud install`` (FPLAN-0587 row 2).

Two entries, one chain: ``install_from_file`` takes a tarball the user handed
over with --from, ``install_from_release`` fetches one into a temporary
directory that never outlives the call. Both verify against SHA256SUMS, then
unpack and swap through unpack.install_bundle, and return what landed.

Pointing @api at the result is not here: it crosses a branch, so the module
layer does it.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from aipass.prax import logger
from aipass.aipass.apps.handlers.json import json_handler
from aipass.aipass.apps.handlers.baud.fetch import LATEST, SUMS_ASSET, fetch_release
from aipass.aipass.apps.handlers.baud.unpack import UnpackError, install_bundle
from aipass.aipass.apps.handlers.baud.verify import VerifyError, verify_tarball

_PREFIX = "baud-phone-"
_SUFFIX = ".tar.gz"


@dataclass(frozen=True)
class InstallOutcome:
    """What landed where, verified against which digest, from which source."""

    tag: str
    dest: Path
    sha256: str
    files: int
    source: str


def local_tag(tarball: Path, tag: str) -> str:
    """The tag of a --from tarball: the given tag, else read off baud-phone-<tag>.tar.gz, else "local"."""
    if tag != LATEST:
        return tag
    name = tarball.name
    if name.startswith(_PREFIX) and name.endswith(_SUFFIX) and len(name) > len(_PREFIX) + len(_SUFFIX):
        return name[len(_PREFIX) : -len(_SUFFIX)]
    return "local"


def _verified_install(tag: str, tarball: Path, sums: Path, dest: Path, source: str, downloaded: bool) -> InstallOutcome:
    """Verify, write the marker record, unpack and swap."""
    digest = verify_tarball(tarball, sums, delete_on_mismatch=downloaded)
    record = {
        "tag": tag,
        "sha256": digest,
        "installed_at": datetime.now(timezone.utc).isoformat(),
        "source": source,
    }
    files = install_bundle(tarball, dest, record)
    logger.info("[baud] phone face %s installed at %s from %s", tag, dest, source)
    json_handler.log_operation(
        "baud_install_complete",
        {"tag": tag, "source": source, "files": files},
        module_name="baud",
    )
    return InstallOutcome(tag=tag, dest=dest, sha256=digest, files=files, source=source)


def install_from_file(tarball: Path, sums: Path | None, dest: Path, tag: str) -> InstallOutcome:
    """Verify and install a tarball on disk. It is the user's file, so it is never deleted.

    Args:
        tarball: The phone tarball.
        sums: Its SHA256SUMS file; None means SHA256SUMS.txt beside the tarball.
        dest: The install directory.
        tag: The tag to record, or "latest" to read it off the file name.

    Raises:
        UnpackError, VerifyError: A missing file, no sums, a refused bundle.
    """
    sums_file = sums or tarball.parent / SUMS_ASSET
    if not tarball.is_file():
        raise UnpackError(f"No tarball at {tarball}.")
    if not sums_file.is_file():
        raise VerifyError(f"No {sums_file.name} at {sums_file}. Pass --sums: an unverified bundle is not installed.")
    return _verified_install(local_tag(tarball, tag), tarball, sums_file, dest, f"file:{tarball}", downloaded=False)


def install_from_release(tag: str, dest: Path) -> InstallOutcome:
    """Fetch a release into a temporary directory, verify it, install it.

    Raises:
        FetchError, VerifyError, UnpackError: Any refusal along the chain.
    """
    with tempfile.TemporaryDirectory(prefix="aipass-baud-") as workdir:
        fetched = fetch_release(tag, Path(workdir))
        return _verified_install(fetched.tag, fetched.tarball, fetched.sums, dest, fetched.source, downloaded=True)
