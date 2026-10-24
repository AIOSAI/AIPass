# =================== AIPass ====================
# Name: verify.py
# Description: Verify a baud phone tarball against a sha256sum-format SHA256SUMS file
# Version: 1.0.1
# Created: 2026-09-13
# Modified: 2026-10-24
# =============================================

"""
Verify the phone tarball and the baud-cli binary (FPLAN-0589) against the release's one SHA256SUMS.
No line or a digest mismatch refuses, never warns; a mismatched download is deleted so nothing uses it.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from aipass.prax import logger
from aipass.aipass.apps.handlers.json import json_handler

_SUMS_LINE = re.compile(r"^([0-9a-fA-F]{64}) [ *](.+)$")
_CHUNK = 1 << 16


class VerifyError(Exception):
    """The tarball could not be verified. The message is safe to print."""


def parse_sums(text: str) -> dict[str, str]:
    """Map file name -> lowercase sha256 from sha256sum-format text."""
    sums: dict[str, str] = {}
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.rstrip()
        if not line:
            continue
        match = _SUMS_LINE.match(line)
        if match is None:
            logger.warning("[baud] SHA256SUMS line %d is not sha256sum format, skipped", number)
            continue
        digest = match.group(1).lower()
        name = match.group(2)
        if name.startswith("./"):
            name = name[2:]
        if sums.get(name, digest) != digest:
            raise VerifyError(f"SHA256SUMS lists {name} twice with different digests. Refusing.")
        sums[name] = digest
    return sums


def sha256_file(path: Path) -> str:
    """Lowercase hex sha256 of a file, read in chunks."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_tarball(tarball: Path, sums_file: Path, delete_on_mismatch: bool) -> str:
    """Check `tarball` (or any release file) against `sums_file`; a --from file is the user's to keep."""
    try:
        text = sums_file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise VerifyError(f"Could not read {sums_file}: {exc}") from exc

    expected = parse_sums(text).get(tarball.name)
    if expected is None:
        raise VerifyError(
            f"{sums_file.name} has no line for {tarball.name}. Refusing to install a file that cannot be verified."
        )

    # shortcut: sums come from the same release, so this catches corruption not tampering;
    # sign SHA256SUMS (minisign) when releases are signed
    actual = sha256_file(tarball)
    if actual != expected:
        if delete_on_mismatch:
            tarball.unlink(missing_ok=True)
            logger.warning("[baud] sha256 mismatch for %s, download deleted", tarball.name)
        json_handler.log_operation(
            "baud_verify_refused",
            {"file": tarball.name, "expected": expected, "actual": actual, "deleted": delete_on_mismatch},
            module_name="baud",
        )
        raise VerifyError(f"SHA256 mismatch for {tarball.name}: expected {expected}, got {actual}. Refusing.")
    json_handler.log_operation("baud_verified", {"file": tarball.name, "sha256": actual}, module_name="baud")
    return actual
