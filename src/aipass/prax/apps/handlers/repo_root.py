# =================== AIPass ====================
# Name: repo_root.py
# Description: Repo-Root Resolution That Never Reads The Process CWD
# Version: 1.4.0
# Created: 2026-08-31
# Modified: 2026-11-26
# =============================================

"""Repo-root walk that never reads the process cwd: it runs at import time inside logger construction, so trail only."""

import os
from pathlib import Path, PurePath
from typing import Optional

from aipass.prax.apps.handlers.logging.trail import PraxTrail

logger = PraxTrail("repo_root")

REGISTRY_MARKER = "AIPASS_REGISTRY.json"
SOURCE_DIR_NAME = "src"


_THIS_FILE = Path(__file__).resolve()

# Announce the fallback once per process: every module reaches this during import.
_ANNOUNCED: set = set()


def source_root(start: Optional[Path] = None) -> Path:
    """Derive the checkout root from a file path, reading no process state."""
    anchor = start if (start is not None and start.is_absolute()) else _THIS_FILE
    return Path(_walk_to_source_root(anchor))


def _walk_to_source_root(anchor: PurePath) -> PurePath:
    """The component walk, with no filesystem and no process state in it."""
    for parent in anchor.parents:
        if parent.name == SOURCE_DIR_NAME:
            return parent.parent
    # Deliberately absurd: fails loudly downstream instead of writing somewhere plausible.
    return anchor.parents[-1]


def _disk_has(path: Path) -> bool:
    """The disk's own answer, which a case-blind disk (WSL /mnt/c) gives for any case of the name."""
    return path.exists()


def _holds_marker(directory: Path) -> bool:
    """The marker by its exact name: exists() says yes to aipass_registry.json on a case-blind disk."""
    if not _disk_has(directory / REGISTRY_MARKER):
        return False
    with os.scandir(directory) as entries:
        return any(entry.name == REGISTRY_MARKER for entry in entries)


def find_repo_root(start: Optional[Path] = None) -> Path:
    """Find the repo root by marker, falling back to the source root — never cwd."""
    anchor = start if (start is not None and start.is_absolute()) else _THIS_FILE
    for parent in [anchor] + list(anchor.parents):
        try:
            if _holds_marker(parent):
                return parent
        except OSError as exc:
            # Unreadable is not "no repo here": keep walking.
            logger.warning("[repo_root] unreadable directory, continuing the walk", path=str(parent), error=str(exc))
            continue

    fallback = source_root(anchor)
    _announce_fallback(anchor, fallback)
    return fallback


def _announce_fallback(anchor: Path, fallback: Path) -> None:
    """Say once that the marker was never found: a warning for a checkout, a note for an installed package."""
    if _ANNOUNCED:
        return
    _ANNOUNCED.add(REGISTRY_MARKER)
    if fallback == Path(fallback.anchor):
        logger.info(
            f"[repo_root] {REGISTRY_MARKER} not found and no src/ either: an installed package, "
            "logs go under the user's home",
            anchor=str(anchor),
        )
        return
    logger.warning(
        f"[repo_root] {REGISTRY_MARKER} not found — falling back to the source root. Paths derived from "
        "the repo root are resolved against the checkout, not the working directory.",
        anchor=str(anchor),
        fallback=str(fallback),
    )
