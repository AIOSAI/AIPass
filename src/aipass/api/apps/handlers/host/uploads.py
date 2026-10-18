# =================== AIPass ====================
# Name: uploads.py
# Description: Host API Upload Handler — bytes from the phone onto disk, named by this server
# Version: 1.0.0
# Created: 2026-08-14
# Modified: 2026-10-17
# =============================================

"""
Host API Upload Handler

Reference: docs/host_surfaces.md (the photo lane).
The client's filename is ignored, never sanitised: it must not reach the filesystem in any form.
"""

import os
import secrets
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Tuple

from aipass.prax import logger
from aipass.api.apps.handlers.json import json_handler

# Mirrors the desktop: @baud's screenshot.rs lands captures in Pictures/BAUD.
UPLOAD_SUBDIR = "BAUD"

UPLOAD_PREFIX = "phone"

MAX_UPLOAD_BYTES = 25 * 1024 * 1024

CHUNK_BYTES = 64 * 1024

# What the BYTES say, never the header. (offset, magic, extension).
IMAGE_SIGNATURES: Tuple[Tuple[int, bytes, str], ...] = (
    (0, b"\x89PNG\r\n\x1a\n", "png"),
    (0, b"\xff\xd8\xff", "jpg"),
    (0, b"GIF87a", "gif"),
    (0, b"GIF89a", "gif"),
    (0, b"BM", "bmp"),
    # RIFF<size>WEBP: the brand sits after a four-byte size field.
    (8, b"WEBP", "webp"),
    (4, b"ftypheic", "heic"),
    (4, b"ftypheix", "heic"),
    (4, b"ftyphevc", "heic"),
    (4, b"ftypmif1", "heic"),
    (4, b"ftypavif", "avif"),
)

SNIFF_BYTES = 32


class UploadRefused(Exception):
    """The caller sent something this lane will not store. Their fault."""


class UploadUnavailable(Exception):
    """The upload could not happen for a reason that is not the caller's."""


def upload_root() -> Path:
    """Where uploaded images land."""
    return _pictures_dir() / UPLOAD_SUBDIR


def sniff_image(head: bytes) -> str:
    """Decide what an upload actually is, from its first bytes."""
    for offset, magic, extension in IMAGE_SIGNATURES:
        if head[offset : offset + len(magic)] == magic:
            return extension

    raise UploadRefused(
        "This is not an image — the first bytes match no image format this lane stores. "
        "The declared content type is not consulted; the bytes decide."
    )


def store_image(source: object, declared_length: Optional[int] = None) -> Dict[str, object]:
    """Write an uploaded image to disk under a name this server chooses."""
    # Content-Length is a claim: checked here, then again for real while streaming.
    _require_within_cap(declared_length, "The upload declares")

    head = source.read(SNIFF_BYTES)  # type: ignore[attr-defined]
    if not head:
        raise UploadRefused("The upload is empty — there are no bytes to store")

    extension = sniff_image(head)

    root = upload_root()
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logger.error("[host_api] could not create the upload directory %s: %s", root, e)
        raise UploadUnavailable(f"Could not create the upload directory {root}: {e}") from e

    destination = root / _generated_name(extension)

    written = _write_stream(destination, head, source)

    json_handler.log_operation(
        "host_api_upload_stored",
        {"path": str(destination), "bytes": written, "type": extension},
    )
    logger.info("[host_api] stored a %s upload of %s bytes at %s", extension, written, destination)

    return {"path": str(destination), "bytes": written, "type": extension}


def _write_stream(destination: Path, head: bytes, source: object) -> int:
    """Stream a body to disk, enforcing the cap as it goes."""
    # 0o600 at create, not chmod-after: a narrowed-later file was world-readable for that moment.
    handle = None
    created = False
    written = 0
    try:
        handle = os.open(str(destination), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        created = True
        with os.fdopen(handle, "wb") as sink:
            handle = None
            chunk = head
            while chunk:
                written += len(chunk)
                if written > MAX_UPLOAD_BYTES:
                    raise UploadRefused(
                        f"The upload is over the {MAX_UPLOAD_BYTES // (1024 * 1024)}MB cap. "
                        "Refused, not truncated — a truncated image is a corrupt one that looks like a success."
                    )
                sink.write(chunk)
                chunk = source.read(CHUNK_BYTES)  # type: ignore[attr-defined]
    except UploadRefused:
        _discard(destination)
        raise
    except OSError as e:
        if handle is not None:
            os.close(handle)
        # Only discard what this write created: an O_EXCL refusal means the name is an EARLIER upload.
        if created:
            _discard(destination)
        logger.error("[host_api] could not write the upload to %s: %s", destination, e)
        raise UploadUnavailable(f"Could not write the upload: {e}") from e

    return written


def _discard(destination: Path) -> None:
    """Remove a partial upload."""
    try:
        destination.unlink(missing_ok=True)
    except OSError as e:
        # Not raised: a cleanup failure must not replace the caller's real refusal.
        logger.warning("[host_api] could not remove the partial upload %s: %s", destination, e)


def _generated_name(extension: str) -> str:
    """The filename, chosen entirely by this server."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"{UPLOAD_PREFIX}-{stamp}-{secrets.token_hex(3)}.{extension}"


def _require_within_cap(declared: Optional[int], subject: str) -> None:
    """Refuse an oversized upload before reading it."""
    if declared is None:
        return

    if declared > MAX_UPLOAD_BYTES:
        raise UploadRefused(
            f"{subject} {declared} bytes, over the {MAX_UPLOAD_BYTES // (1024 * 1024)}MB cap. Refused, not truncated."
        )


def _pictures_dir() -> Path:
    """The operator's Pictures directory, the way the desktop finds it."""
    # Tauri's picture_dir() lookup; the ~/Pictures fallback is right on Windows and macOS too.
    from_env = os.environ.get("XDG_PICTURES_DIR", "").strip()
    if from_env:
        return Path(os.path.expandvars(from_env)).expanduser()

    configured = _pictures_from_user_dirs()
    if configured is not None:
        return configured

    return Path.home() / "Pictures"


def _pictures_from_user_dirs() -> Optional[Path]:
    """Parse XDG_PICTURES_DIR out of the user-dirs config."""
    config = Path.home() / ".config" / "user-dirs.dirs"

    try:
        lines = config.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as e:
        logger.debug("[host_api] no readable XDG user-dirs config at %s: %s", config, e)
        return None

    for line in lines:
        if not line.startswith("XDG_PICTURES_DIR="):
            continue
        value = line.split("=", 1)[1].strip().strip('"')
        if not value:
            continue
        # The file holds "$HOME/Pictures" literally.
        return Path(os.path.expandvars(value)).expanduser()

    return None
