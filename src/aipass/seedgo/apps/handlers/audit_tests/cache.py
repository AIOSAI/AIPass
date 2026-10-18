# =================== AIPass ====================
# Name: cache.py
# Description: the lane's own cache stamp - computed and published, never served
# Version: 1.0.0
# Created: 2026-08-29
# Modified: 2026-10-17
# =============================================

"""
The lane's cache stamp. COMPUTED AND PUBLISHED FROM DAY ONE, SERVED BY NOTHING.
Stamp: AT_CACHE_VERSION : adapter : core : payload : interpreter : siblings.
`core` covers this lane's machinery, which the audit's MACHINERY_DIRS does not;
`payload` is carved out of the pack hash so each segment can move alone.
"""

import hashlib
import sys
from pathlib import Path
from typing import List, Optional

from aipass.prax import logger

#: Bump when the meaning of a cached entry changes.
AT_CACHE_VERSION = "at1"

HASHED_SUFFIXES: tuple = (".py", ".json")

SKIP_DIRS: frozenset = frozenset({"__pycache__", ".ruff_cache", ".pytest_cache", ".mypy_cache"})

#: What a file fingerprint structurally cannot cover; published on every run.
NOT_FINGERPRINTED: tuple = (
    "the lane serves nothing from cache in this release - every run is a full measurement",
    "installed third-party distributions: a dependency upgrade changes a suite's result with "
    "no file in the target changing",
    "the machine's own state - open file limits, clock, locale, available memory",
    "a sibling branch's RUNTIME behaviour beyond the bytes of its .py files",
    "anything a test reads from the network or from a service outside this repo",
)


def _hash_tree(root: Path, exclude: Optional[Path] = None) -> str:
    """A stable content hash of one directory tree; names are hashed so a rename changes it."""
    digest = hashlib.sha256()
    if not root.is_dir():
        return ""

    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix not in HASHED_SUFFIXES:
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if exclude is not None and exclude in path.parents:
            continue
        try:
            digest.update(str(path.relative_to(root)).encode("utf-8"))
            digest.update(path.read_bytes())
        except OSError as exc:
            # Recorded, not skipped: an unrecorded hole lets two trees share a key.
            logger.warning(f"[AUDIT-TESTS] cache stamp could not read {path}: {exc}")
            digest.update(f"unreadable:{path.name}".encode("utf-8"))

    return digest.hexdigest()[:16]


def _interpreter_stamp() -> str:
    """The interpreter's identity, hashed."""
    return hashlib.sha256(f"{sys.version}|{sys.executable}".encode("utf-8")).hexdigest()[:12]


def _sibling_stamp(siblings: List[str]) -> str:
    """The sibling set copied into the env, hashed by name."""
    return hashlib.sha256("|".join(sorted(siblings)).encode("utf-8")).hexdigest()[:12]


def compute_stamp(
    pack_dir: Optional[Path],
    core_dir: Optional[Path] = None,
    siblings: Optional[List[str]] = None,
) -> str:
    """The full cache key for one run. Computed always, consulted by nothing."""
    core = core_dir or Path(__file__).resolve().parent
    payload = (pack_dir / "payload") if pack_dir else None

    return ":".join(
        [
            AT_CACHE_VERSION,
            _hash_tree(pack_dir, exclude=payload) if pack_dir else "no-pack",
            _hash_tree(core),
            _hash_tree(payload) if payload else "no-payload",
            _interpreter_stamp(),
            _sibling_stamp(siblings or []),
        ]
    )


def cache_block(
    pack_dir: Optional[Path] = None,
    siblings: Optional[List[str]] = None,
) -> dict:
    """The artifact's `cache` block. `served_from_cache` is always False here."""
    return {
        "served_from_cache": False,
        "stamp": compute_stamp(pack_dir, siblings=siblings),
        "not_fingerprinted": list(NOT_FINGERPRINTED),
        "note": (
            "The stamp is computed on every run and consulted by nothing. Serving is "
            "deliberately not enabled in this release: an execution lane's stale green is "
            "worse than a slow audit, and this branch has the FPLAN-0382 scar to prove it - "
            "17/17 cached green while CI showed the real 99%."
        ),
    }
