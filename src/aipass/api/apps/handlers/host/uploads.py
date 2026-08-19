# =================== AIPass ====================
# Name: uploads.py
# Description: Host API Upload Handler — bytes from the phone onto disk, named by this server
# Version: 1.0.0
# Created: 2026-08-14
# Modified: 2026-08-14
# =============================================

"""
Host API Upload Handler

The photo lane (DPLAN-0300 Round 20). Patrick wants to send a screenshot from
his phone to an agent, and the mechanism for that already exists on the desktop.

    images by path, so THE PATH IS THE DELIVERY.
    -- @baud, screenshot.rs:3

So this module does exactly one thing: get bytes onto disk somewhere the
operator can find them, and hand back the absolute path. The delivery half is
already built and proven — the phone types the quoted path into the open attach
socket, through @baud's existing `deliverPaths`, and never submits. This module
adds no new mechanism; it adds a file.

THE FILENAME IS THIS SERVER'S TO CHOOSE, AND THAT IS THE WHOLE SECURITY STORY
------------------------------------------------------------------------
The name that arrives with an upload is attacker-controlled. It can be
`../../.ssh/authorized_keys`, it can be `.bashrc`, it can be a 4000-character
unicode confusion, and there is no sanitiser worth trusting against all of that.
So the client's filename is not sanitised, not fenced, not normalised — it is
IGNORED. It never reaches the filesystem in any form. The server generates a
name from a timestamp and a random suffix, and the extension comes from the
bytes rather than from anything the caller said.

This is the same ruling as the name fence in `reads.py`, taken one step further:
there a caller could name a file and the fence refused a path, here a caller
cannot name a file at all. A parameter that does not exist cannot be exploited.

SNIFF THE BYTES, DO NOT BELIEVE THE HEADER
------------------------------------------------------------------------
`Content-Type: image/png` costs a caller nothing to write. The magic bytes at
the front of the file are what the file actually is, so those decide both
whether the upload is accepted and what extension it gets. A caller who declares
PNG and sends a shell script gets refused, and — this is the part that matters —
gets refused with the extension question already settled, so there is no path by
which a `.png` on disk holds something that is not a PNG.

WHERE IT LANDS, AND WHY THERE
------------------------------------------------------------------------
`~/Pictures/BAUD/` — the same directory the desktop's own captures land in
(`screenshot.rs` writes `Pictures/BAUD/baud-<stamp>.png`). One place for images
delivered to agents beats two: the operator has one folder to look in, and a
path from either source reads the same to whoever receives it.

The prefix differs — `phone-` rather than `baud-` — because when the operator is
looking at that folder, "which of these came from my pocket" is a real question
and the filename is the cheapest place to answer it.

THE CAP REFUSES, IT NEVER TRUNCATES
------------------------------------------------------------------------
Same species as every other cap on this server. A truncated image is not a
smaller image, it is a corrupt one — and it would arrive looking like a
successful upload. The size is checked twice on purpose: once against the
declared `Content-Length` so an oversized body is refused before it is read, and
again against the running total while reading, because `Content-Length` is a
claim and a chunked upload has none.

Functions:
    upload_root()  - Where images land
    store_image()  - Write bytes, return the path
    sniff_image()  - What the bytes actually are
"""

import os
import secrets
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Tuple

from aipass.prax import logger
from aipass.api.apps.handlers.json import json_handler

# Mirrors the desktop: screenshot.rs lands captures in Pictures/BAUD, and a
# second directory for the same kind of object would only make the operator
# look in two places.
UPLOAD_SUBDIR = "BAUD"

# Says where it came from, in the one place the operator is already looking.
UPLOAD_PREFIX = "phone"

# ~25MB. A phone screenshot is one to three; a modern phone PHOTO is four to
# twelve. This is generous for the named need and still small enough that a
# runaway upload cannot fill a disk before the cap fires.
MAX_UPLOAD_BYTES = 25 * 1024 * 1024

# Read size while streaming a body to disk. The point of streaming at all is
# that the whole upload never has to exist in memory at once.
CHUNK_BYTES = 64 * 1024

# What the BYTES say, never what the header says. Each entry is
# (offset, magic, extension) — the offset is there for the container formats
# that put a size field before their brand.
IMAGE_SIGNATURES: Tuple[Tuple[int, bytes, str], ...] = (
    (0, b"\x89PNG\r\n\x1a\n", "png"),
    (0, b"\xff\xd8\xff", "jpg"),
    (0, b"GIF87a", "gif"),
    (0, b"GIF89a", "gif"),
    (0, b"BM", "bmp"),
    # RIFF....WEBP — the four bytes between are the file size, so the brand
    # check has to skip them rather than match a single run.
    (8, b"WEBP", "webp"),
    # ISO base media brands. A phone camera roll is full of these, and an
    # iPhone screenshot arrives as one.
    (4, b"ftypheic", "heic"),
    (4, b"ftypheix", "heic"),
    (4, b"ftyphevc", "heic"),
    (4, b"ftypmif1", "heic"),
    (4, b"ftypavif", "avif"),
)

# Enough bytes to reach the longest signature above with room to spare.
SNIFF_BYTES = 32


class UploadRefused(Exception):
    """The caller sent something this lane will not store. Their fault."""


class UploadUnavailable(Exception):
    """The upload could not happen for a reason that is not the caller's."""


def upload_root() -> Path:
    """
    Where uploaded images land.

    Mirrors the desktop's own destination rather than inventing a second one.
    The XDG lookup is what Tauri's `picture_dir()` does on Linux, reproduced
    here so a machine with a relocated Pictures directory does not end up with
    phone uploads in one place and desktop captures in another.

    Returns:
        The absolute directory. Not created — that is `store_image()`'s job,
        so a read of this value never has a side effect.
    """
    return _pictures_dir() / UPLOAD_SUBDIR


def sniff_image(head: bytes) -> str:
    """
    Decide what an upload actually is, from its first bytes.

    Args:
        head: The start of the file, at least SNIFF_BYTES long where possible.

    Returns:
        The extension this content should be stored under.

    Raises:
        UploadRefused: The bytes are not a recognised image. Refused rather
            than stored under a generic extension: a file this server cannot
            name is a file it has no business writing, and "some bytes" is not
            a thing the operator asked to send.
    """
    for offset, magic, extension in IMAGE_SIGNATURES:
        if head[offset : offset + len(magic)] == magic:
            return extension

    raise UploadRefused(
        "This is not an image — the first bytes match no image format this lane stores. "
        "The declared content type is not consulted; the bytes decide."
    )


def store_image(source: object, declared_length: Optional[int] = None) -> Dict[str, object]:
    """
    Write an uploaded image to disk under a name this server chooses.

    Args:
        source: A file-like object with a blocking `read(size)`. Streamed
            rather than handed over whole, so an upload never has to exist in
            memory in one piece.
        declared_length: The request's Content-Length, when it sent one. A
            claim, not a fact — checked first so an oversized body is refused
            before it is read, then checked again for real while reading.

    Returns:
        {"path": str, "bytes": int, "type": str} — `path` is absolute, and it
        is the entire product of this endpoint.

    Raises:
        UploadRefused: Empty body, over the cap, or not an image.
        UploadUnavailable: The destination could not be written.
    """
    _require_within_cap(declared_length, "The upload declares")

    head = source.read(SNIFF_BYTES)  # type: ignore[attr-defined]
    if not head:
        raise UploadRefused("The upload is empty — there are no bytes to store")

    # Before a single byte reaches disk. An unrecognised upload never becomes a
    # file that has to be cleaned up afterwards.
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


# ==============================================
# INTERNALS
# ==============================================


def _write_stream(destination: Path, head: bytes, source: object) -> int:
    """
    Stream a body to disk, enforcing the cap as it goes.

    Args:
        destination: Where to write.
        head: Bytes already read for sniffing, which still belong to the file.
        source: The rest of the body.

    Returns:
        Bytes written.

    Raises:
        UploadRefused: The body exceeded the cap while being read.
        UploadUnavailable: The write failed.
    """
    # 0o600 via os.open rather than chmod-after: a file created world-readable
    # and narrowed a moment later was world-readable for that moment. Same rule
    # as the token store. It is the operator's own image in the operator's own
    # directory, so this is belt-and-braces rather than a threat model — but
    # the cheap habit is the one that holds when the object is not.
    handle = None
    written = 0
    try:
        handle = os.open(str(destination), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
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
        # The partial file is this server's mess, not a delivery. Removed here
        # so a refused upload never leaves a path the operator could be handed.
        _discard(destination)
        raise
    except OSError as e:
        if handle is not None:
            os.close(handle)
        _discard(destination)
        logger.error("[host_api] could not write the upload to %s: %s", destination, e)
        raise UploadUnavailable(f"Could not write the upload: {e}") from e

    return written


def _discard(destination: Path) -> None:
    """
    Remove a partial upload.

    Args:
        destination: The file to drop.
    """
    try:
        destination.unlink(missing_ok=True)
    except OSError as e:
        # Dropped, not raised: the caller is already being told why their
        # upload failed, and a cleanup failure must not replace that sentence
        # with a less useful one.
        logger.warning("[host_api] could not remove the partial upload %s: %s", destination, e)


def _generated_name(extension: str) -> str:
    """
    The filename, chosen entirely by this server.

    The client's filename is not an input here — it is not sanitised or fenced,
    it is absent. A stamp answers "when did I send this" from the folder
    listing; the random suffix is what makes two uploads inside one second two
    files rather than a collision.

    Args:
        extension: Extension derived from the sniffed bytes.

    Returns:
        A filename, never a path.
    """
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"{UPLOAD_PREFIX}-{stamp}-{secrets.token_hex(3)}.{extension}"


def _require_within_cap(declared: Optional[int], subject: str) -> None:
    """
    Refuse an oversized upload before reading it.

    Args:
        declared: Content-Length, if the request carried one.
        subject: Sentence opener naming what was measured.

    Raises:
        UploadRefused: The declared size is over the cap.
    """
    if declared is None:
        return

    if declared > MAX_UPLOAD_BYTES:
        raise UploadRefused(
            f"{subject} {declared} bytes, over the {MAX_UPLOAD_BYTES // (1024 * 1024)}MB cap. Refused, not truncated."
        )


def _pictures_dir() -> Path:
    """
    The operator's Pictures directory, the way the desktop finds it.

    Returns:
        `$XDG_PICTURES_DIR` if set, else the value in `~/.config/user-dirs.dirs`,
        else `~/Pictures`. The fallback is also the correct answer on Windows
        and macOS, which is why there is no platform branch here.
    """
    from_env = os.environ.get("XDG_PICTURES_DIR", "").strip()
    if from_env:
        return Path(os.path.expandvars(from_env)).expanduser()

    configured = _pictures_from_user_dirs()
    if configured is not None:
        return configured

    return Path.home() / "Pictures"


def _pictures_from_user_dirs() -> Optional[Path]:
    """
    Parse XDG_PICTURES_DIR out of the user-dirs config.

    Returns:
        The configured directory, or None if there is no readable answer.
    """
    config = Path.home() / ".config" / "user-dirs.dirs"

    try:
        lines = config.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as e:
        # No config, unreadable, or not text. Not an error — most machines have
        # no such file, and the caller has a correct fallback.
        logger.debug("[host_api] no readable XDG user-dirs config at %s: %s", config, e)
        return None

    for line in lines:
        if not line.startswith("XDG_PICTURES_DIR="):
            continue
        value = line.split("=", 1)[1].strip().strip('"')
        if not value:
            continue
        # The file writes "$HOME/Pictures" literally, so the expansion is the
        # whole reason for reading it rather than joining a name.
        return Path(os.path.expandvars(value)).expanduser()

    return None
