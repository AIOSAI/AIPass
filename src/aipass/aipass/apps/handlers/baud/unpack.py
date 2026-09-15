# =================== AIPass ====================
# Name: unpack.py
# Description: Safely unpack a verified baud phone tarball into staging, then swap it into place
# Version: 1.0.0
# Created: 2026-09-13
# Modified: 2026-09-13
# =============================================

"""
Unpack the phone bundle safely and swap it into place (FPLAN-0587).

THE SAFETY FILTER
-----------------
Every member is judged before a single byte is written. Refused: absolute
names, ``..``, backslashes, symlinks, hardlinks, devices and fifos, any
directory other than ``assets/`` (and anything beneath it) at the root, a file
inside such a directory. Required: ``phone.html`` at the root and an ``assets/``
directory. That is exactly the shape baud's release lane packs
(``tar -C app/dist-phone ... -czf <archive> .``) and exactly what @api's face.py
can serve, so anything else is either a broken release or a hostile one.

Files are written by this code, not by ``tarfile.extract``: the bytes are
copied, and no mode bits, owner or timestamps come from the archive.

THE SWAP
--------
Extraction lands in ``.<dest>.staging`` beside dest, the marker
(``.baud-phone.json``) is written into staging LAST, and only then
dest -> ``<dest>.prev``, staging -> dest, prev dropped. A failure before the swap
leaves the old install untouched; a failure in the swap puts prev back.

What this refuses to replace: a dest that exists, is not empty, and carries no
marker. That is somebody's directory, not an install this command made, and
moving it aside and dropping it would delete their files.
"""

from __future__ import annotations

import os
import shutil
import tarfile
from pathlib import Path, PurePosixPath
from typing import Any, List, Tuple

from aipass.prax import logger
from aipass.aipass.apps.handlers.json import json_handler

MARKER_NAME = ".baud-phone.json"
ENTRY_FILE = "phone.html"
ASSETS_DIR = "assets"


class UnpackError(Exception):
    """The bundle was refused or could not be placed. The message is safe to print."""


def staging_path(dest: Path) -> Path:
    """Where a bundle is extracted before it is swapped in."""
    return dest.parent / f".{dest.name}.staging"


def prev_path(dest: Path) -> Path:
    """Where the previous install waits during the swap."""
    return dest.parent / f"{dest.name}.prev"


def _member_path(member: tarfile.TarInfo) -> PurePosixPath | None:
    """Normalised relative path of a member, or None for the archive root entry."""
    name = member.name
    if name.startswith("/") or "\\" in name or (len(name) > 1 and name[1] == ":"):
        raise UnpackError(f"Refused: member {name!r} has an absolute or non-POSIX name.")
    parts = [part for part in PurePosixPath(name).parts if part != "."]
    if ".." in parts:
        raise UnpackError(f"Refused: member {name!r} climbs out of the bundle.")
    return PurePosixPath(*parts) if parts else None


def validate_members(members: List[tarfile.TarInfo]) -> List[Tuple[PurePosixPath, tarfile.TarInfo]]:
    """Judge every member against the phone-bundle shape.

    Args:
        members: The archive's members, in archive order.

    Returns:
        (relative path, member) for everything to extract, the root entry dropped.

    Raises:
        UnpackError: The first member that breaks the shape, or a missing
            phone.html / assets/.
    """
    plan: List[Tuple[PurePosixPath, tarfile.TarInfo]] = []
    has_entry = False
    has_assets = False
    for member in members:
        rel = _member_path(member)
        if member.issym() or member.islnk():
            raise UnpackError(f"Refused: member {member.name!r} is a link.")
        if not (member.isfile() or member.isdir()):
            raise UnpackError(f"Refused: member {member.name!r} is a device, fifo or other special file.")
        if rel is None:
            if not member.isdir():
                raise UnpackError(f"Refused: root member {member.name!r} is not a directory.")
            continue
        top = rel.parts[0]
        nested = len(rel.parts) > 1
        if member.isdir() and top != ASSETS_DIR:
            raise UnpackError(f"Refused: directory {rel}/ (assets/ is the only directory a phone bundle carries).")
        if member.isfile() and nested and top != ASSETS_DIR:
            raise UnpackError(f"Refused: {rel} sits in a directory other than assets/.")
        if member.isfile() and not nested and top == ASSETS_DIR:
            raise UnpackError("Refused: assets is a file in this bundle, not a directory.")
        has_assets = has_assets or top == ASSETS_DIR
        has_entry = has_entry or (member.isfile() and str(rel) == ENTRY_FILE)
        plan.append((rel, member))
    if not has_entry:
        raise UnpackError(f"Refused: no {ENTRY_FILE} at the bundle root.")
    if not has_assets:
        raise UnpackError(f"Refused: no {ASSETS_DIR}/ directory in the bundle.")
    return plan


def extract_bundle(tarball: Path, target: Path) -> int:
    """Validate the whole archive, then write its files under `target`.

    Args:
        tarball: A .tar.gz already verified against SHA256SUMS.
        target: A directory that must not exist yet.

    Returns:
        The number of files written.

    Raises:
        UnpackError: Unreadable archive or a refused member (nothing written).
    """
    try:
        with tarfile.open(tarball, "r:gz") as archive:
            plan = validate_members(archive.getmembers())
            target.mkdir(parents=True)
            written = 0
            for rel, member in plan:
                out = target.joinpath(*rel.parts)
                if member.isdir():
                    out.mkdir(parents=True, exist_ok=True)
                    continue
                source = archive.extractfile(member)
                if source is None:
                    raise UnpackError(f"Could not read member {member.name!r} from the archive.")
                out.parent.mkdir(parents=True, exist_ok=True)
                with source, out.open("wb") as sink:
                    shutil.copyfileobj(source, sink)
                written += 1
    except (tarfile.TarError, EOFError) as exc:
        raise UnpackError(f"{tarball.name} is not a readable .tar.gz: {exc}") from exc
    return written


def _is_ours_or_empty(path: Path) -> bool:
    """True for an empty directory or one carrying this command's marker."""
    return (path / MARKER_NAME).is_file() or not any(path.iterdir())


def _drop_dir(path: Path, why: str) -> None:
    """Remove a directory this command made."""
    shutil.rmtree(path)
    logger.info("[baud] removed %s (%s)", path, why)


def check_dest(dest: Path) -> None:
    """Refuse a dest this command must not replace.

    Raises:
        UnpackError: dest (or a leftover prev) is a file, a link, or someone
            else's non-empty directory.
    """
    for path, label in ((dest, "the install directory"), (prev_path(dest), "a leftover previous install")):
        if path.is_symlink() or (path.exists() and not path.is_dir()):
            raise UnpackError(f"Refused: {path} ({label}) exists and is not a plain directory.")
        if path.is_dir() and not _is_ours_or_empty(path):
            raise UnpackError(
                f"Refused: {path} ({label}) is not empty and has no {MARKER_NAME}, "
                "so it is not a phone install this command made. Pick another --dest."
            )


def swap_in(staging: Path, dest: Path) -> None:
    """dest -> prev, staging -> dest, drop prev; put prev back if the second move fails."""
    prev = prev_path(dest)
    if prev.is_dir():
        _drop_dir(prev, "leftover previous install")
    had_dest = dest.is_dir()
    if had_dest:
        os.replace(dest, prev)
    try:
        os.replace(staging, dest)
    except OSError:
        if had_dest:
            os.replace(prev, dest)
            logger.warning("[baud] swap failed, previous install restored at %s", dest)
        raise
    if had_dest:
        _drop_dir(prev, "replaced by the new install")


def install_bundle(tarball: Path, dest: Path, record: dict[str, Any]) -> int:
    """Extract into staging beside dest, write the marker, then swap it in.

    Args:
        tarball: A verified phone tarball.
        dest: The install directory (created if absent).
        record: The marker content: tag, sha256, installed_at, source.

    Returns:
        The number of bundle files installed.

    Raises:
        UnpackError: Refused dest, refused member, unwritable marker.
        OSError: The filesystem failed under the swap (the old install is restored).
    """
    check_dest(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    staging = staging_path(dest)
    if staging.exists():
        if staging.is_symlink() or not staging.is_dir():
            raise UnpackError(f"Refused: {staging} exists and is not a plain directory.")
        _drop_dir(staging, "leftover staging from an interrupted install")
    try:
        written = extract_bundle(tarball, staging)
        if not json_handler.write_json(staging / MARKER_NAME, record):
            raise UnpackError(f"Could not write {MARKER_NAME} into {staging}.")
    except BaseException:
        if staging.is_dir():
            _drop_dir(staging, "install did not complete")
        raise
    try:
        swap_in(staging, dest)
    except BaseException:
        if staging.is_dir():
            _drop_dir(staging, "swap did not complete")
        raise
    json_handler.log_operation(
        "baud_bundle_installed",
        {"dest": str(dest), "files": written, "tag": record.get("tag")},
        module_name="baud",
    )
    return written


def read_install(dest: Path) -> dict[str, Any]:
    """What is installed at `dest`: the marker fields plus whether phone.html is there."""
    marker = json_handler.read_json(dest / MARKER_NAME)
    record = marker if isinstance(marker, dict) else {}
    return {
        "dest": str(dest),
        "installed": bool(record),
        "tag": record.get("tag"),
        "sha256": record.get("sha256"),
        "installed_at": record.get("installed_at"),
        "source": record.get("source"),
        "phone_html": (dest / ENTRY_FILE).is_file(),
    }
