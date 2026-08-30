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
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

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


def live_writers(root: Path, hash_limit: int = HASH_SIZE_LIMIT) -> Dict[str, List[str]]:
    """Paths that change while NOTHING of ours is running, measured not assumed.

    THE PROBLEM THIS SOLVES. A target that is a live citizen writes its own
    operational logs continuously - its daemon ticks, its server serves, its
    logger rotates. Those writes land in the REAL tree during the measurement
    window, and a before/after fingerprint cannot tell them from a test that
    forged a log file. Measured on @api: eight paths under `api_json/` and
    `logs/` moved during one run, and check 12 reported the instrument had
    disturbed what it measured.

    WHY NOT JUST EXEMPT LOG PATHS. Because `logs/operations.jsonl` is exactly
    what this campaign convicted @backup for forging - 35 test nodeids writing
    into the real one. An exemption keyed on the path would blind the proof to
    the precise species it was built to catch. So the discriminator has to be
    measured rather than declared.

    HOW. Two back-to-back snapshots with no suite between them. Anything that
    moves in that window is being written by something that is not us, and its
    path is published as such. A path in the post-run diff that is NOT in this
    set is unattributable to concurrent activity - which is the hard finding.

    The window is short, so this UNDER-detects: a service that writes once a
    minute will not show up, and its path will be reported as unattributed.
    That direction is the safe one - it over-reports violations rather than
    explaining them away - and it is stated here rather than left to be found.
    """
    first = snapshot_tree(root, hash_limit)
    second = snapshot_tree(root, hash_limit)
    return diff_snapshots(first, second, record=False)


def diff_snapshots(before: Dict[str, tuple], after: Dict[str, tuple], record: bool = True) -> Dict[str, List[str]]:
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

    if record and any(diff.values()):
        logger.error(
            f"[AUDIT-TESTS] M10 VIOLATED: {sum(len(v) for v in diff.values())} path(s) changed in the real tree"
        )
        json_handler.log_operation("m10_violated", {"counts": {k: len(v) for k, v in diff.items()}, "diff": diff})

    return diff


# =============================================================================
# THE CARRIER'S OWN WRITES
# =============================================================================

#: Write-relevant audit events, and which positional args carry a path. COPIED
#: from `tests_pytest_standards/payload/audit_hygiene_plugin.py` rather than
#: imported: this package is ecosystem-neutral core and may not import an
#: adapter pack, because a core that imports an adapter turns a second
#: ecosystem into a rewrite instead of a directory. One vocabulary held in two
#: places on purpose - inventing a second one here would let the gate and the
#: carrier disagree about what a write is. `os.replace` needs no entry of its
#: own: CPython raises `os.rename` for it.
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

#: `open` reports (path, mode, flags). `mode` is None when the call arrived
#: through os.open, so `flags` is the only universally present signal. Copied
#: alongside the vocabulary above, for the same reason.
WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC

#: One plain sentence, published beside every subtraction.
CARRIER_NOTE = (
    "these paths were written by the audit's OWN machinery, not by the measured suite; "
    "they are subtracted from the diff above and listed here so the subtraction can be audited"
)

#: Carrier surfaces written by a DIFFERENT PROCESS, which this process's own
#: hook cannot see and therefore cannot measure. Each entry names the surface,
#: its owner, and why the measured suite cannot be its author.
#:
#: DELIBERATELY TINY, AND IT STAYS THAT WAY. Every entry here is a claim taken
#: on trust, which is exactly what an observed write is not. A path that is
#: neither observed nor declared stays in the diff and reads red - the honest
#: direction, and the one thing that keeps this constant from silently becoming
#: the path-shaped exemption list this design refuses to be.
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

    THE DEFECT THIS ANSWERS. A fleet baseline reported real-tree diffs on 5 of
    21 targets and not one of them was test forgery: they were the audit's own
    machinery - its logger, its json handler - writing while it measured. The
    instrument disturbing what it measures is worth an ERROR; an ERROR that
    fires on every fleet run is how an alarm dies.

    WHY NOT A PATH RULE. The same fleet run showed an ADDED source file under a
    target, `entry_point_diff_check.py`, written by a human editing the branch
    while the audit ran. Any classification keyed on path shape - "anything
    under the branch", "any *_log.json" - swallows that too, and with it every
    real escape. So the discriminator is PROVENANCE: this records what OUR OWN
    PROCESS wrote, and nothing else is ever subtracted on its evidence.

    `sys.addaudithook` CANNOT BE REMOVED. So the hook is installed at most once
    per process and does nothing at all while `active` is false; start and stop
    toggle that flag rather than pretending to uninstall anything.
    """

    def __init__(self) -> None:
        """An idle recorder: nothing watched, nothing recorded, nothing hooked."""
        self.active = False
        self.prefixes: Tuple[str, ...] = ()
        self.writes: Dict[str, str] = {}
        self.swallowed_errors = 0


RECORDER = CarrierRecorder()

#: Module-level because `sys.addaudithook` is irreversible: a second install
#: would double every event for the rest of the process's life.
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

    THE REJECT COMES FIRST AND TAKES THE RAW STRING. This runs on every single
    file operation the audit process performs, so nothing may be constructed
    before the paths that are none of our business are gone.

    `normpath` is the fingerprinter's own form - `os.walk` joins onto the root
    it was given and never resolves - so a recorded path is comparable with a
    diff entry as a plain string. A write that reaches the tree through a
    SYMLINK normalises to a different string and is not recorded, which leaves
    that path in the diff reading red: the under-detecting direction, on
    purpose.
    """
    if not isinstance(path, str) or not path.startswith(recorder.prefixes):
        return
    canonical = os.path.normpath(path)
    if canonical not in recorder.writes:
        recorder.writes[canonical] = event


def carrier_hook(event: str, args: tuple) -> None:
    """The PEP 578 hook, in the AUDIT's own process. It never raises.

    An exception here fires inside somebody else's own write call, so every one
    is caught - and COUNTED, because a swallowed error nobody sees is a
    fail-open mode: it would shorten the observed list without shortening the
    diff, and a reader must be able to weigh that against the subtraction.
    """
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
        # MUTED WHILE IT COMPLAINS. The logger writes a file, that write is an
        # audit event, and this hook would be handling its own report of its
        # own failure. The window is microseconds and it is the only way to
        # make a swallowed error visible without risking recursion.
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
    """Close the window and hand back `(writes, swallowed_errors)`.

    The buffer is cleared by the next `start`, never here, so a second call
    returns the same record rather than an empty one that would silently
    subtract nothing.
    """
    RECORDER.active = False
    return dict(RECORDER.writes), RECORDER.swallowed_errors


def _declared_for(path: str) -> Optional[Dict[str, str]]:
    """The DECLARED entry covering this path, or None.

    Matched on a path-separator boundary so a declared `.../logs/engine.jsonl`
    cannot be stretched over `.../my_engine.jsonl`.
    """
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

    Returns the subtracted diff, the FULL diff before subtraction, the carrier
    block naming every path taken out with the evidence for it, and how the
    attribution was reached. The unsubtracted truth stays in the document
    because that is what makes the subtraction auditable: a subtraction a
    reader cannot check is just a smaller number.

    A PATH THE GATE SAW THE MEASURED SUITE WRITE IS NEVER SUBTRACTED, even when
    this process wrote it too - both are true at once on a cross-branch log.
    The carrier's evidence may EXPLAIN a path; it may never acquit one, because
    the suite's own record is the finding this whole lane exists to make.

    The operational record is written HERE rather than at a call site: the
    error belongs to the diff nobody can account for, not to the raw diff, and
    an alarm that fires on the audit's own logs teaches everyone to ignore it.
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
