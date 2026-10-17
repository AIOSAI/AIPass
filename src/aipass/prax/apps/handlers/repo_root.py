# =================== AIPass ====================
# Name: repo_root.py
# Description: Repo-Root Resolution That Never Reads The Process CWD
# Version: 1.0.1
# Created: 2026-08-31
# Modified: 2026-10-17
# =============================================

"""
Repo-Root Resolution Handler

The walk runs at import time fleet-wide (module-level loggers), so it never reads
the process cwd: a deleted cwd raises, and the gitignored registry is absent on
every clean checkout. The fallback derives from ``__file__``; the last resort is
the filesystem root. Reached from inside logger construction, so this module
imports nothing from prax and uses stdlib ``logging`` only.
"""

import logging
from pathlib import Path, PurePath
from typing import Optional

logger = logging.getLogger(__name__)

REGISTRY_MARKER = "AIPASS_REGISTRY.json"
SOURCE_DIR_NAME = "src"


def resolved_file(path: Path) -> Path:
    """``Path.resolve()`` that cannot need a working directory.

    On Windows ``ntpath.realpath`` calls ``os.getcwd()`` even for absolute paths;
    the input is already absolute, so the unresolved path is a correct fallback.
    """
    try:
        return path.resolve()
    except OSError as exc:
        # debug, not warning: the unresolved absolute path is a correct answer.
        logger.debug("[repo_root] %s could not be resolved (%s); using it unresolved", path, exc)
        return path


try:
    _THIS_FILE = Path(__file__).resolve()
except OSError as _exc:
    logger.debug("[repo_root] this module's own path could not be resolved (%s); using it unresolved", _exc)
    _THIS_FILE = Path(__file__)

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


def find_repo_root(start: Optional[Path] = None) -> Path:
    """Find the repo root by marker, falling back to the source root — never cwd."""
    anchor = start if (start is not None and start.is_absolute()) else _THIS_FILE
    for parent in [anchor] + list(anchor.parents):
        try:
            if (parent / REGISTRY_MARKER).exists():
                return parent
        except OSError as exc:
            # Unreadable is not "no repo here": keep walking.
            logger.info("[repo_root] %s is unreadable, continuing the walk: %s", parent, exc)
            continue

    fallback = source_root(anchor)
    _announce_fallback(anchor, fallback)
    return fallback


def _announce_fallback(anchor: Path, fallback: Path) -> None:
    """Say once that the marker was never found: a warning for a checkout, a note for an installed package.

    INFO for the package case: stdlib's last-resort handler prints WARNING to the terminal.
    """
    if _ANNOUNCED:
        return
    _ANNOUNCED.add(REGISTRY_MARKER)
    if fallback == Path(fallback.anchor):
        logger.info(
            "[repo_root] %s not found above %s and no src/ either: an installed package, logs go under the user's home",
            REGISTRY_MARKER,
            anchor,
        )
        return
    logger.warning(
        "[repo_root] %s not found above %s — falling back to the source root %s. "
        "Paths derived from the repo root are resolved against the checkout, "
        "not the working directory.",
        REGISTRY_MARKER,
        anchor,
        fallback,
    )
