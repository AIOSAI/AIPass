# =================== AIPass ====================
# Name: cache.py
# Description: the lane's own cache stamp - computed and published, never served
# Version: 1.0.0
# Created: 2026-08-29
# Modified: 2026-08-29
# =============================================

"""
The lane's cache stamp. COMPUTED AND PUBLISHED FROM DAY ONE, SERVED BY NOTHING.

THE DELIBERATE HALF-STEP, AND WHY IT IS THE RIGHT ONE. Design section 5 quotes
this branch's own scar back at it: FPLAN-0382, where *"the fleet read 17/17
cached green while CI, which has no cache, showed the real 99%. A stale green
is worse than a slow audit."* An execution lane's cache is strictly more
dangerous than the audit's, because a suite's result depends on things no file
fingerprint can see. So the requirement lands before the capability — exactly
as it did for `kill_cause` — and the artifact carries a real stamp, computed
on every run, while `served_from_cache` stays false and every run is a full
measurement.

That is not a placeholder. The stamp is the load-bearing part: turning serving
on later is one branch in the runner, and the key it would use has by then
been exercised on every run the lane has ever done. Shipping the serving first
and the key afterwards is how a stale green happens.

THE STAMP, and every component exists because something it covers can change a
measurement without changing the target:

    AT_CACHE_VERSION : adapter : core : payload : interpreter : siblings

  adapter      the whole `tests_<eco>_standards/` pack
  core         `handlers/audit_tests/` — the lane's own machinery. The audit's
               MACHINERY_DIRS covers `audit/` and `bypass/` and would NOT bust
               on a change to this lane's runner, which is the FPLAN-0382 shape
  payload      hashed SEPARATELY and CARVED OUT of the pack hash, because it
               is the one artefact that runs inside the copy and a change to it
               changes every measurement. Separate only counts if the two are
               disjoint: overlapping components always move together, and a
               reader learns nothing from a segment that cannot move alone
  interpreter  `sys.version` plus the resolved interpreter path
  siblings     the sibling set actually copied into the env — a change in
               branch A's runtime behaviour changes branch B's suite result
               while B's own fingerprint is untouched

WHAT THE FINGERPRINT CANNOT SEE is published as a list rather than left to a
reader to work out. Law S5 says a cache-served artifact is stamped; this lane
extends it to say the stamp also names its own blind spots, because a cache
key that quietly stopped covering something is the same species of defect as a
gate that quietly stopped watching.
"""

import hashlib
import sys
from pathlib import Path
from typing import List, Optional

from aipass.prax import logger

#: Bump when the meaning of a cached entry changes.
AT_CACHE_VERSION = "at1"

#: Files whose bytes go into a directory hash.
HASHED_SUFFIXES: tuple = (".py", ".json")

#: Directories never hashed.
SKIP_DIRS: frozenset = frozenset({"__pycache__", ".ruff_cache", ".pytest_cache", ".mypy_cache"})

#: What a file fingerprint structurally cannot cover. Published in the
#: artifact's cache block on every run, served or not.
NOT_FINGERPRINTED: tuple = (
    "the lane serves nothing from cache in this release - every run is a full measurement",
    "installed third-party distributions: a dependency upgrade changes a suite's result with "
    "no file in the target changing",
    "the machine's own state - open file limits, clock, locale, available memory",
    "a sibling branch's RUNTIME behaviour beyond the bytes of its .py files",
    "anything a test reads from the network or from a service outside this repo",
)


def _hash_tree(root: Path, exclude: Optional[Path] = None) -> str:
    """A stable content hash of one directory tree.

    Names are hashed alongside bytes, so a file RENAMED to an identical twin
    changes the stamp. A hash over contents alone would call a rename a no-op,
    and a rename is exactly how a checker stops being discovered.

    `exclude` carves a subtree out. The payload lives INSIDE the pack, so
    without this the pack component would cover it and the payload component
    would be a second hash of bytes already hashed - two segments that always
    move together, which tells a reader nothing about WHICH half changed. The
    two components are only worth publishing separately if they are disjoint.
    """
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
            # Recorded in the stamp rather than skipped: a file that could not
            # be read is a hole in the key, and a key with an unrecorded hole
            # is how two different trees end up sharing a cache entry.
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
    """The artifact's `cache` block. `served_from_cache` is always False here.

    Law S5 requires a cache-served artifact to be stamped and to name what it
    cannot see. This run is not cache-served, and it still carries both —
    because a stamp that has only ever been computed on the day serving is
    switched on is a stamp nobody has tested.
    """
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
