# =================== AIPass ====================
# Name: m10.py
# Description: the before/after proof that the real tree was never touched
# Version: 1.0.1
# Created: 2026-08-29
# Modified: 2026-10-17
# =============================================

"""
Law M10, measured rather than asserted.

Lives in the language-neutral core: the core must never import an adapter pack.
"""

import hashlib
import os
import stat
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler

#: Files at or below this size are hashed as well as stat'd.
HASH_SIZE_LIMIT = 2 * 1024 * 1024


def snapshot_tree(root: Path, hash_limit: int = HASH_SIZE_LIMIT) -> Dict[str, tuple]:
    """Fingerprint a tree for the M10 proof; content is hashed, since ctime misses same-tick rewrites."""
    fingerprints: Dict[str, tuple] = {}

    for dirpath, dirnames, filenames in os.walk(root, onerror=_unreadable):
        dirnames[:] = [d for d in dirnames if d not in ("__pycache__", ".git")]
        for name in filenames:
            full = os.path.join(dirpath, name)
            fingerprint = _fingerprint(full, hash_limit)
            if fingerprint is not None:
                fingerprints[full] = fingerprint

    return fingerprints


def _unreadable(error: OSError) -> None:
    """Raise a directory the walk could not list; every caller reports M10 unproven on OSError.

    A skipped subtree would be missing from BOTH snapshots, so the proof would call it untouched unread.
    """
    raise error


def _fingerprint(full: str, hash_limit: int) -> Optional[tuple]:
    """One file's fingerprint, or None if it is no longer there."""
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


def live_writers(root: Path, hash_limit: int = HASH_SIZE_LIMIT) -> Dict[str, List[str]]:
    """Paths that change while NOTHING of ours is running, measured not assumed.

    Measured, not a log-path exemption, which would blind the proof to forged logs.
    """
    first = snapshot_tree(root, hash_limit)
    second = snapshot_tree(root, hash_limit)
    return diff_snapshots(first, second, record=False)


def diff_snapshots(before: Dict[str, tuple], after: Dict[str, tuple], record: bool = True) -> Dict[str, List[str]]:
    """Added / removed / modified paths between two tree snapshots.

    Recorded here, not at a call site, so no caller gets the diff without the record.
    """
    before_keys, after_keys = set(before), set(after)
    diff = {
        "added": sorted(after_keys - before_keys),
        "removed": sorted(before_keys - after_keys),
        "modified": sorted(key for key in before_keys & after_keys if before[key] != after[key]),
    }

    if record and any(diff.values()):
        logger.error(
            f"[AUDIT-TESTS] M10 VIOLATED: {sum(len(v) for v in diff.values())} path(s) changed in the real tree"
        )
        json_handler.log_operation("m10_violated", {"counts": {k: len(v) for k, v in diff.items()}, "diff": diff})

    return diff


#: Copied, not imported, from `tests_pytest_standards/payload/audit_hygiene_plugin.py`;
#: keep the two in step. `os.replace` raises `os.rename`, so it needs no entry.
CARRIER_PATH_ARGS: Dict[str, Tuple[int, ...]] = {
    "open": (0,),
    "os.rename": (0, 1),
    "os.remove": (0,),
    "os.mkdir": (0,),
    "os.rmdir": (0,),
    "os.truncate": (0,),
    "os.chmod": (0,),
    "os.chown": (0,),
    "os.symlink": (1,),
    "os.link": (1,),
    "shutil.copyfile": (0, 1),
    "shutil.copymode": (1,),
    "shutil.copystat": (1,),
    "shutil.move": (0, 1),
    "shutil.rmtree": (0,),
    "shutil.unpack_archive": (1,),
}

#: `mode` is None via os.open, so `flags` is the one signal always present.
WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC

CARRIER_NOTE = (
    "these paths were written by the audit's OWN machinery, not by the measured suite; "
    "they are subtracted from the diff above and listed here so the subtraction can be audited"
)

#: Carrier surfaces written by another process, which our hook cannot see.
#: Keep it tiny: each entry is trusted, not observed; it must not grow into a path exemption list.
DECLARED_CARRIER_WRITES: Tuple[Dict[str, str], ...] = (
    {
        "path": "src/aipass/hooks/logs/engine.jsonl",
        "surface": "the Claude Code hook engine's event log",
        "owner": "the harness this audit runs inside - a separate process",
        "why": (
            "it is appended by the hook engine on the developer's own keystrokes, in a process "
            "this run never starts and cannot install a hook in; no measured suite invokes the "
            "engine, so a suite cannot be its author"
        ),
    },
)


class CarrierRecorder:
    """Every real-tree path THIS process opens for writing during a run.

    `sys.addaudithook` cannot be removed, so start/stop only toggle `active`.
    """

    def __init__(self) -> None:
        """An idle recorder: nothing watched, nothing recorded, nothing hooked."""
        self.active = False
        self.prefixes: Tuple[str, ...] = ()
        self.writes: Dict[str, str] = {}
        self.swallowed_errors = 0


RECORDER = CarrierRecorder()

#: A second `sys.addaudithook` install would double every event for the process's life.
_HOOK_INSTALLED = False


def is_write_open(args: tuple) -> bool:
    """True if this `open` event is a write. Reads are never recorded."""
    flags = args[2] if len(args) > 2 else 0
    if isinstance(flags, int) and flags & WRITE_FLAGS:
        return True
    mode = args[1] if len(args) > 1 else None
    return isinstance(mode, str) and any(c in mode for c in "wax+")


def _record_carrier_write(recorder: CarrierRecorder, event: str, path: object) -> None:
    """File one path against the open window, if it lands in the watched tree.

    Runs on every file operation, so the raw-string reject comes first.
    """
    if not isinstance(path, str) or not path.startswith(recorder.prefixes):
        return
    canonical = os.path.normpath(path)
    if canonical not in recorder.writes:
        recorder.writes[canonical] = event


def carrier_hook(event: str, args: tuple) -> None:
    """The PEP 578 hook, in the AUDIT's own process. It never raises; swallowed errors are counted."""
    recorder = RECORDER
    if not recorder.active:
        return
    try:
        indices = CARRIER_PATH_ARGS.get(event)
        if indices is None:
            return
        if event == "open" and not is_write_open(args):
            return
        for index in indices:
            if index < len(args):
                _record_carrier_write(recorder, event, args[index])
    except Exception as exc:  # a hook that raises breaks the process it lives in
        recorder.swallowed_errors += 1
        # Muted while logging: the logger's own write is an audit event and would recurse.
        recorder.active = False
        try:
            logger.debug(f"[AUDIT-TESTS] carrier hook failed on {event}: {type(exc).__name__}: {exc}")
        finally:
            recorder.active = True


def start_carrier_recording(root: Path) -> None:
    """Open the window: record what THIS process writes under `root`."""
    global _HOOK_INSTALLED

    recorder = RECORDER
    recorder.prefixes = (os.path.normpath(str(root)).rstrip(os.sep) + os.sep,)
    recorder.writes = {}
    recorder.swallowed_errors = 0
    recorder.active = True

    if not _HOOK_INSTALLED:
        sys.addaudithook(carrier_hook)
        _HOOK_INSTALLED = True


def stop_carrier_recording() -> Tuple[Dict[str, str], int]:
    """Close the window and hand back `(writes, swallowed_errors)`; only `start` clears the buffer."""
    RECORDER.active = False
    return dict(RECORDER.writes), RECORDER.swallowed_errors


def _declared_for(path: str) -> Optional[Dict[str, str]]:
    """The DECLARED entry covering this path, or None, matched on a separator boundary."""
    normal = path.replace(os.sep, "/")
    for entry in DECLARED_CARRIER_WRITES:
        if normal == entry["path"] or normal.endswith("/" + entry["path"]):
            return entry
    return None


def carrier_partition(
    diff: Dict[str, List[str]],
    writes: Optional[Dict[str, str]] = None,
    swallowed_errors: int = 0,
    gate_recorded: Optional[set] = None,
) -> dict:
    """Split an M10 diff into what the audit itself wrote and what it did not.

    A path the gate saw the suite write is never subtracted: carrier evidence never acquits.
    """
    recorded = dict(writes or {})
    convicted = set(gate_recorded or ())

    observed: List[dict] = []
    declared: List[dict] = []
    subtracted: set = set()

    for path in sorted({path for paths in diff.values() for path in paths}):
        if path in convicted:
            continue
        if path in recorded:
            observed.append({"path": path, "evidence": "carrier audit hook", "event": recorded[path]})
            subtracted.add(path)
            continue
        entry = _declared_for(path)
        if entry is not None:
            declared.append({"path": path, **{key: entry[key] for key in ("surface", "owner", "why")}})
            subtracted.add(path)

    remaining = {kind: [path for path in paths if path not in subtracted] for kind, paths in diff.items()}
    _record_partition(remaining, observed, declared, swallowed_errors)

    return {
        "diff": remaining,
        "diff_before_carrier_subtraction": {kind: list(paths) for kind, paths in diff.items()},
        "carrier_writes": {
            "note": CARRIER_NOTE,
            "observed": observed,
            "declared": declared,
            "total": len(observed) + len(declared),
            "swallowed_errors": swallowed_errors,
        },
        "attribution": "partly declared" if declared else "measured",
    }


def _record_partition(remaining: dict, observed: list, declared: list, swallowed: int) -> None:
    """Log the verdict of a partition: violation, or an audited subtraction."""
    if any(remaining.values()):
        count = sum(len(paths) for paths in remaining.values())
        logger.error(
            f"[AUDIT-TESTS] M10 VIOLATED: {count} path(s) changed in the real tree that this audit did not write"
        )
        json_handler.log_operation(
            "m10_violated",
            {
                "counts": {kind: len(paths) for kind, paths in remaining.items()},
                "diff": remaining,
                "carrier_subtracted": len(observed) + len(declared),
            },
        )
    elif observed or declared:
        logger.info(
            f"[AUDIT-TESTS] M10 held: {len(observed)} observed and {len(declared)} declared carrier "
            f"write(s) subtracted, {swallowed} swallowed hook error(s)"
        )
