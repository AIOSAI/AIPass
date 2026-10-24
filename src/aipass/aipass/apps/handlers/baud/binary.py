# =================== AIPass ====================
# Name: binary.py
# Description: Land a verified baud-cli beside the phone face: staging, rename, 0755, marker, previous kept
# Version: 1.0.1
# Created: 2026-09-14
# Modified: 2026-10-24
# =============================================

"""
Land the headless baud binary beside the phone face (FPLAN-0589 row 3).

Reference: docs/baud_phone_face.md (layout, swap, the marker refusal).
"""

from __future__ import annotations

import os
import platform
import shutil
from pathlib import Path
from typing import Any

from aipass.prax import logger
from aipass.aipass.apps.handlers.json import json_handler
from aipass.aipass.apps.handlers.baud.unpack import UnpackError
from aipass.aipass.apps.handlers.baud.verify import sha256_file

BIN_DIR = "bin"
BIN_NAME = "baud-cli"
BIN_MARKER = ".baud-cli.json"
RELEASE_PLATFORM = "linux-x86_64"
_MODE = 0o755
_MACHINE_ALIASES = {"amd64": "x86_64", "x64": "x86_64"}


def platform_slug(system: str | None = None, machine: str | None = None) -> str:
    """This machine as <os>-<arch>, lowercase: linux-x86_64, darwin-arm64, windows-x86_64."""
    os_name = (system or platform.system()).lower()
    arch = (machine or platform.machine()).lower()
    return f"{os_name}-{_MACHINE_ALIASES.get(arch, arch)}"


def binary_asset_name(tag: str, slug: str | None = None) -> str | None:
    """``baud-cli-<tag>-linux-x86_64`` on a platform releases build for, else None."""
    here = slug or platform_slug()
    return f"{BIN_NAME}-{tag}-{here}" if here == RELEASE_PLATFORM else None


def no_binary_note(tag: str, slug: str | None = None) -> str:
    """The one honest line for an install that lands the face only."""
    here = slug or platform_slug()
    asset = binary_asset_name(tag, here)
    if asset is None:
        return f"No baud-cli build for {here} (releases carry {RELEASE_PLATFORM} only): installed the phone face only."
    return f"Release {tag} carries no {asset}: installed the phone face only."


def baud_root(dest: Path) -> Path:
    """The directory the face and the binary share: the face's parent."""
    return dest.parent


def bin_path(root: Path) -> Path:
    """Where baud-cli lands."""
    return root / BIN_DIR / BIN_NAME


def bin_prev_path(root: Path) -> Path:
    """Where the binary it replaced is kept."""
    return root / BIN_DIR / f"{BIN_NAME}.prev"


def bin_staging_path(root: Path) -> Path:
    """Where the bytes wait before the rename."""
    return root / BIN_DIR / f".{BIN_NAME}.staging"


def bin_marker_path(root: Path) -> Path:
    """The marker beside the face: tag, sha256, installed_at, source."""
    return root / BIN_MARKER


def check_bin_dest(root: Path) -> None:
    """Refuse a binary location this command must not write.

    Called before anything is installed, so a refusal leaves the face untouched too.
    """
    bin_dir = root / BIN_DIR
    if bin_dir.is_symlink() or (bin_dir.exists() and not bin_dir.is_dir()):
        raise UnpackError(f"Refused: {bin_dir} exists and is not a plain directory.")
    labels = ((bin_path(root), "the installed baud-cli"), (bin_prev_path(root), "the previous baud-cli"))
    for path, label in (*labels, (bin_staging_path(root), "leftover staging")):
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise UnpackError(f"Refused: {path} ({label}) exists and is not a regular file.")
    if bin_path(root).exists() and not bin_marker_path(root).is_file():
        raise UnpackError(
            f"Refused: {bin_path(root)} exists and {BIN_MARKER} does not, "
            "so it is not a baud-cli this command installed. Move it, or pick another --dest."
        )


def _stage(source: Path, staging: Path, digest: str) -> None:
    """Copy the bytes, check them against the verified digest (the source may change after verify), set 0755."""
    staging.unlink(missing_ok=True)
    try:
        shutil.copyfile(source, staging)
        if sha256_file(staging) != digest:
            raise UnpackError(f"{source.name} changed after it was verified. Refusing.")
        os.chmod(staging, _MODE)
    except BaseException:
        staging.unlink(missing_ok=True)
        raise


def install_binary(source: Path, root: Path, record: dict[str, Any]) -> Path:
    """Land a verified binary at root/bin/baud-cli, keep the old one as .prev, write the marker.

    ``record["sha256"]`` must be the verified digest; the staged bytes are checked against it.
    OSError from the rename propagates after the previous binary is restored.
    """
    check_bin_dest(root)
    target, staging, prev = bin_path(root), bin_staging_path(root), bin_prev_path(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    _stage(source, staging, str(record["sha256"]))
    had_target = target.is_file()
    if had_target:
        os.replace(target, prev)
    try:
        os.replace(staging, target)
    except BaseException:
        if had_target:
            os.replace(prev, target)
            logger.warning("[baud] baud-cli rename failed, previous binary restored at %s", target)
        staging.unlink(missing_ok=True)
        raise
    if not json_handler.write_json(bin_marker_path(root), record):
        # A binary with no marker would refuse every later install, so the previous state comes back.
        if had_target:
            os.replace(prev, target)
        else:
            target.unlink(missing_ok=True)
        raise UnpackError(f"{BIN_MARKER} could not be written at {root}, so baud-cli was not installed.")
    json_handler.log_operation(
        "baud_cli_installed",
        {"path": str(target), "tag": record.get("tag"), "kept_prev": had_target},
        module_name="baud",
    )
    return target


def read_binary_install(root: Path) -> dict[str, Any]:
    """What is installed under `root`: the marker fields, and whether the binary is there and executable."""
    target = bin_path(root)
    marker = json_handler.read_json(bin_marker_path(root))
    record = marker if isinstance(marker, dict) else {}
    return {
        "path": str(target),
        "installed": bool(record),
        "tag": record.get("tag"),
        "sha256": record.get("sha256"),
        "installed_at": record.get("installed_at"),
        "source": record.get("source"),
        "present": target.is_file(),
        "executable": target.is_file() and os.access(target, os.X_OK),
    }
