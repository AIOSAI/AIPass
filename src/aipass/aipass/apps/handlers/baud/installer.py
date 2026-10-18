# =================== AIPass ====================
# Name: installer.py
# Description: The install chain of aipass baud: face and baud-cli from disk or a fetched release, verified, placed
# Version: 1.1.0
# Created: 2026-09-13
# Modified: 2026-10-17
# =============================================

"""
The install chain behind ``aipass baud install`` (FPLAN-0587 row 2, FPLAN-0589 row 3).

The order is the safety property: every file is verified and the binary's place checked
before anything lands, so a bad binary never leaves a new face beside an old one.
Pointing @api at the result crosses a branch, so the module layer does it.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

from aipass.prax import logger
from aipass.aipass.apps.handlers.json import json_handler
from aipass.aipass.apps.handlers.baud.binary import baud_root, check_bin_dest, install_binary, no_binary_note
from aipass.aipass.apps.handlers.baud.fetch import LATEST, SUMS_ASSET, fetch_release
from aipass.aipass.apps.handlers.baud.unpack import UnpackError, install_bundle
from aipass.aipass.apps.handlers.baud.verify import VerifyError, verify_tarball

_PREFIX = "baud-phone-"
_SUFFIX = ".tar.gz"
_NO_BINARY_GIVEN = "No --binary given: installed the phone face only."


@dataclass(frozen=True)
class BinaryOutcome:
    """The baud-cli that landed, and the digest it was verified against."""

    path: Path
    sha256: str


@dataclass(frozen=True)
class InstallOutcome:
    """What landed where, verified against which digest, from which source.

    binary is None when no baud-cli was installed; binary_note then says why in one line.
    """

    tag: str
    dest: Path
    sha256: str
    files: int
    source: str
    binary: BinaryOutcome | None = None
    binary_note: str = ""


@dataclass(frozen=True)
class _Binary:
    """A binary to verify and land, with the source its marker records."""

    path: Path
    source: str


def local_tag(tarball: Path, tag: str) -> str:
    """The tag of a --from tarball: the given tag, else read off baud-phone-<tag>.tar.gz, else "local"."""
    if tag != LATEST:
        return tag
    name = tarball.name
    if name.startswith(_PREFIX) and name.endswith(_SUFFIX) and len(name) > len(_PREFIX) + len(_SUFFIX):
        return name[len(_PREFIX) : -len(_SUFFIX)]
    return "local"


def _record(tag: str, digest: str, stamp: str, source: str) -> dict[str, str]:
    """A marker: tag, sha256, installed_at, source."""
    return {"tag": tag, "sha256": digest, "installed_at": stamp, "source": source}


def _verified_install(
    tag: str,
    tarball: Path,
    sums: Path,
    dest: Path,
    source: str,
    downloaded: bool,
    binary: _Binary | None = None,
) -> InstallOutcome:
    """Verify every file and check the binary's place, then unpack and swap the face, then land the binary."""
    digest = verify_tarball(tarball, sums, delete_on_mismatch=downloaded)
    bin_digest = verify_tarball(binary.path, sums, delete_on_mismatch=downloaded) if binary else ""
    root = baud_root(dest)
    if binary:
        check_bin_dest(root)
    stamp = datetime.now(timezone.utc).isoformat()
    files = install_bundle(tarball, dest, _record(tag, digest, stamp, source))
    landed = None
    if binary:
        path = install_binary(binary.path, root, _record(tag, bin_digest, stamp, binary.source))
        landed = BinaryOutcome(path=path, sha256=bin_digest)
    logger.info("[baud] phone face %s installed at %s from %s (baud-cli: %s)", tag, dest, source, bool(landed))
    json_handler.log_operation(
        "baud_install_complete",
        {"tag": tag, "source": source, "files": files, "binary": landed is not None},
        module_name="baud",
    )
    return InstallOutcome(tag=tag, dest=dest, sha256=digest, files=files, source=source, binary=landed)


def install_from_file(
    tarball: Path,
    sums: Path | None,
    dest: Path,
    tag: str,
    binary: Path | None = None,
) -> InstallOutcome:
    """Verify and install a tarball, and a baud-cli binary when given, from disk. The user's files are never deleted.

    ``sums`` None means SHA256SUMS.txt beside the tarball; the binary's line is read from it too.
    """
    sums_file = sums or tarball.parent / SUMS_ASSET
    if not tarball.is_file():
        raise UnpackError(f"No tarball at {tarball}.")
    if binary is not None and not binary.is_file():
        raise UnpackError(f"No binary at {binary}.")
    if not sums_file.is_file():
        raise VerifyError(f"No {sums_file.name} at {sums_file}. Pass --sums: an unverified bundle is not installed.")
    chosen = _Binary(binary, f"file:{binary}") if binary is not None else None
    outcome = _verified_install(
        local_tag(tarball, tag), tarball, sums_file, dest, f"file:{tarball}", downloaded=False, binary=chosen
    )
    return outcome if chosen else _with_note(outcome, _NO_BINARY_GIVEN)


def install_from_release(tag: str, dest: Path) -> InstallOutcome:
    """Fetch a release into a temporary directory, verify it, install the face and, when there is one, the binary."""
    with tempfile.TemporaryDirectory(prefix="aipass-baud-") as workdir:
        fetched = fetch_release(tag, Path(workdir))
        chosen = _Binary(fetched.binary, fetched.source) if fetched.binary is not None else None
        outcome = _verified_install(
            fetched.tag, fetched.tarball, fetched.sums, dest, fetched.source, downloaded=True, binary=chosen
        )
    return outcome if chosen else _with_note(outcome, no_binary_note(fetched.tag))


def _with_note(outcome: InstallOutcome, note: str) -> InstallOutcome:
    """The same outcome, carrying the line that says why no binary landed."""
    return replace(outcome, binary_note=note)
