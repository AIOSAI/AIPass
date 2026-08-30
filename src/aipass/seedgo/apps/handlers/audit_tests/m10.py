# =================== AIPass ====================
# Name: m10.py
# Description: the before/after proof that the real tree was never touched
# Version: 1.0.0
# Created: 2026-08-29
# Modified: 2026-08-29
# =============================================

"""
Law M10, measured rather than asserted.

The instrument must not disturb what it measures. That is this lane's central
promise, and a promise it merely stated would be the same species it exists to
catch — a claim nothing could ever falsify. So the real tree is fingerprinted
before the copy and again after teardown, and the comparison is published
whether it is good news or not.

THIS LIVES IN THE CORE BECAUSE IT IS LANGUAGE-NEUTRAL. Hashing a file tree
involves no pytest concept, and it was briefly written into the pytest pack —
which would have made the core import an adapter to prove its own promise, the
exact dependency direction that turns a second ecosystem into a rewrite. A Rust
adapter needs this proof just as much and should not have to reimplement it.
"""

import hashlib
import os
import stat
from pathlib import Path
from typing import Dict, List, Optional

from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler

#: Files at or below this size are hashed as well as stat'd.
HASH_SIZE_LIMIT = 2 * 1024 * 1024


def snapshot_tree(root: Path, hash_limit: int = HASH_SIZE_LIMIT) -> Dict[str, tuple]:
    """Fingerprint a tree for the before/after proof that M10 held.

    `(st_mtime_ns, st_size, st_ctime_ns, st_ino, md5)`. The research claimed
    `st_ctime_ns` cannot be set from userspace and so catches a
    forge-then-restore round trip. MEASURED, that does not hold in general: the
    kernel's file-timestamp clock advances on a timer tick, so a rewrite and
    its timestamp restoration inside one tick are indistinguishable from no
    change at all, on ext4 and tmpfs alike. So content is HASHED rather than
    inferred; the stat fields stay because they catch a same-content inode swap.
    """
    fingerprints: Dict[str, tuple] = {}

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in ("__pycache__", ".git")]
        for name in filenames:
            full = os.path.join(dirpath, name)
            fingerprint = _fingerprint(full, hash_limit)
            if fingerprint is not None:
                fingerprints[full] = fingerprint

    return fingerprints


def _fingerprint(full: str, hash_limit: int) -> Optional[tuple]:
    """One file's fingerprint, or None if it is no longer there.

    A file that vanished between the walk and the stat is simply absent from
    this snapshot, which is exactly how a removal should read in the diff.
    """
    try:
        info = os.lstat(full)
    except OSError as exc:
        logger.debug(f"[AUDIT-TESTS] gone before stat: {full} ({exc})")
        return None

    digest = ""
    if stat.S_ISREG(info.st_mode) and info.st_size <= hash_limit:
        try:
            digest = hashlib.md5(Path(full).read_bytes()).hexdigest()
        except OSError as exc:
            logger.debug(f"[AUDIT-TESTS] unreadable while hashing: {full} ({exc})")
            digest = "unreadable"

    return (info.st_mtime_ns, info.st_size, info.st_ctime_ns, info.st_ino, digest)


def diff_snapshots(before: Dict[str, tuple], after: Dict[str, tuple]) -> Dict[str, List[str]]:
    """Added / removed / modified paths between two tree snapshots.

    A non-empty diff means the instrument disturbed what it measured, which is
    the most serious thing this lane can discover about ITSELF. It is recorded
    as an operational event here rather than at a call site, so no future
    caller can obtain the diff without the record being written.
    """
    before_keys, after_keys = set(before), set(after)
    diff = {
        "added": sorted(after_keys - before_keys),
        "removed": sorted(before_keys - after_keys),
        "modified": sorted(key for key in before_keys & after_keys if before[key] != after[key]),
    }

    if any(diff.values()):
        logger.error(
            f"[AUDIT-TESTS] M10 VIOLATED: {sum(len(v) for v in diff.values())} path(s) changed in the real tree"
        )
        json_handler.log_operation("m10_violated", {"counts": {k: len(v) for k, v in diff.items()}, "diff": diff})

    return diff
