# =================== AIPass ====================
# Name: deletion_log.py
# Description: Durable record of every delete drone performs
# Version: 1.0.0
# Created: 2026-08-14
# Modified: 2026-08-14
# =============================================

"""Durable record of every delete drone performs.

Patrick's ruling: "if something deletes, there should be a record of it."
``drone rm`` is the fleet's only sanctioned delete path — raw recursive rm is
gate-blocked — so this is the choke point where the record belongs.

Two channels, deliberately:

  - a JSONL store under the project's ``.ai_central/``, machine-readable and
    findable months later;
  - a prax INFO line, so a deletion flows through normal observability without
    anyone having to know this file exists.

The prax line is emitted FIRST. If the store write fails, the event still
reached the logs — a deletion that leaves no trace anywhere is the one outcome
worth engineering against.

Refusals are recorded too. A blocked delete leaves no other trace of what was
attempted, which makes it exactly the kind of event worth finding later.

Severity is INFO on both channels (compass #273): a deletion through the
sanctioned path is chosen behaviour, not a fault. The guards keep their own
WARNING when they refuse — that is the guard speaking, and it is separate from
the record.
"""

from __future__ import annotations

import json
import os
import stat
import tempfile
import time
from pathlib import Path

from aipass.prax import logger
from aipass.drone.apps.handlers.json import json_handler
from aipass.drone.apps.handlers.router_handler import caller_cwd, resolve_caller_identity

_LOG_DIR_NAME = ".ai_central"
_LOG_NAME = "deletions.jsonl"

# Redirects the durable store only. The prax INFO line is emitted before the
# store is touched and this cannot silence it — so pointing the store somewhere
# else relocates the record, it does not erase the event. Exists because a test
# run and a container both need somewhere other than the live project's log.
_PATH_ENV_VAR = "AIPASS_DELETION_LOG"

# Bounded on purpose. A delete log that grows without limit becomes the runaway
# log the monitoring lane exists to catch, and the newest records — the ones
# anyone actually reaches for — are the first thing a full disk costs you.
_MAX_BYTES = 2 * 1024 * 1024
_ROTATIONS = 1

# Measuring a tree means walking it. A delete of something enormous should not
# pay an unbounded walk before it starts, so the count stops here and says so.
_MEASURE_ENTRY_CAP = 10_000

OUTCOME_DELETED = "deleted"
OUTCOME_REFUSED = "refused"
OUTCOME_FAILED = "failed"
OUTCOME_NOT_FOUND = "not_found"

LANE_RM = "rm"
LANE_BROKER = "broker"

UNKNOWN_CALLER = "unknown"

# What the cwd field records when the process has no working directory left.
# Deleting the directory you are standing in is an ordinary thing to do with a
# scratch dir, and every os.getcwd() after it raises ENOENT. A defined value
# for "there is none" is not a substitute answer — inventing "/" or reusing the
# deleted path would be, and both would read as a real location months later.
NO_CURRENT_DIRECTORY = "<none: deleted during this operation>"


def _find_project_root() -> Path | None:
    """Walk up from CWD to find *_REGISTRY.json; return its parent as project root.

    No cwd means no walk — and the ENOENT used to raise here, past the two
    homes that could still have answered. AIPASS_HOME and the tempdir below
    do not need a cwd, so a delete that removes its own directory keeps the
    durable half of its record instead of surviving as a prax line alone.
    """
    cwd = caller_cwd()
    for parent in [cwd, *cwd.parents] if cwd is not None else []:
        if list(parent.glob("*_REGISTRY.json")):
            return parent.resolve()
    aipass_home = os.environ.get("AIPASS_HOME")
    if aipass_home:
        home = Path(aipass_home)
        if home.is_dir() and list(home.glob("*_REGISTRY.json")):
            return home.resolve()
    return None


def deletion_log_path() -> Path:
    """Return the deletion log path for the project the caller is standing in.

    One log per project, not one per branch: ``drone rm`` runs from whichever
    branch is deleting, and a record split across seventeen mailboxes is not a
    record. Falls back to the temp dir when there is no project — a deletion
    outside any project still gets written down somewhere.

    ``AIPASS_DELETION_LOG`` overrides the location outright.
    """
    override = os.environ.get(_PATH_ENV_VAR)
    if override:
        return Path(override)

    root = _find_project_root()
    if root is None:
        return Path(tempfile.gettempdir()) / _LOG_NAME
    return root / _LOG_DIR_NAME / _LOG_NAME


def measure(path: Path) -> dict:
    """Describe *path* before it is deleted: kind, size, entry count.

    Must be called BEFORE the delete — afterwards there is nothing left to ask.

    Symlinks are measured, never followed: the link is what is being removed,
    and following it would report the size of a file that survives.
    """
    try:
        if path.is_symlink():
            return {
                "kind": "symlink",
                "size_bytes": path.lstat().st_size,
                "entry_count": None,
                "measured": "exact",
            }
        if path.is_dir():
            return _measure_tree(path)
        if path.exists():
            return {
                "kind": "file",
                "size_bytes": path.stat().st_size,
                "entry_count": None,
                "measured": "exact",
            }
    except OSError as exc:
        logger.info("deletion record: could not measure %s: %s", path, exc)
        return {"kind": "unknown", "size_bytes": None, "entry_count": None, "measured": "failed"}

    return {"kind": "unknown", "size_bytes": None, "entry_count": None, "measured": "none"}


def _measure_tree(path: Path) -> dict:
    """Walk a directory counting entries and bytes, stopping at the cap."""
    entries = 0
    total = 0
    unreadable = 0
    measured = "exact"

    for dirpath, dirnames, filenames in os.walk(path):
        here = Path(dirpath)
        for name in (*dirnames, *filenames):
            if entries >= _MEASURE_ENTRY_CAP:
                measured = "capped"
                break
            entries += 1
            try:
                st = (here / name).lstat()
            except OSError as exc:
                # Normal in a live tree — an entry can vanish between the walk
                # and the stat. Two levels on purpose: which entry at DEBUG,
                # for whoever is actually chasing one, and the TOTAL once after
                # the walk at INFO. An INFO line per file would bury the very
                # signal it is meant to raise on a large directory.
                logger.debug("deletion record: cannot stat %s: %s", here / name, exc)
                unreadable += 1
                continue
            if not stat.S_ISDIR(st.st_mode):
                total += st.st_size
        if measured == "capped":
            break

    if unreadable:
        if measured == "exact":
            measured = "partial"
        logger.info(
            "deletion record: %d of %d entries under %s could not be measured — size is a floor",
            unreadable,
            entries,
            path,
        )

    return {"kind": "directory", "size_bytes": total, "entry_count": entries, "measured": measured}


def _rotate_if_needed(log_path: Path) -> None:
    """Roll the log over once it passes the cap, keeping _ROTATIONS generations.

    Uses ``replace`` rather than unlink so the oldest generation is overwritten
    in one step — nothing here ever calls a delete of its own.
    """
    try:
        if not log_path.exists() or log_path.stat().st_size < _MAX_BYTES:
            return
    except OSError as exc:
        # Skipping rotation silently is how a bounded log stops being bounded:
        # every future append would take this same path and the file would grow
        # without limit, which is the failure this function exists to prevent.
        logger.warning("deletion record: cannot check size of %s, skipping rotation: %s", log_path, exc)
        return

    for generation in range(_ROTATIONS, 0, -1):
        older = log_path.with_suffix(log_path.suffix + f".{generation}")
        newer = log_path if generation == 1 else log_path.with_suffix(log_path.suffix + f".{generation - 1}")
        if newer.exists():
            newer.replace(older)


def _append_record(record: dict, log_path: Path) -> None:
    """Append one JSON line to the store, rotating first if the cap is hit."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    _rotate_if_needed(log_path)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, separators=(",", ":")) + "\n")


def record_deletion(
    *,
    lane: str,
    outcome: str,
    requested: str,
    resolved: Path | str,
    reason: str,
    measurement: dict | None = None,
    caller: str | None = None,
) -> dict:
    """Write one deletion record to both channels and return it.

    Args:
        lane: Which delete path this came through — ``rm`` or ``broker``.
        outcome: One of deleted / refused / failed / not_found.
        requested: Exactly what the caller typed, before resolution.
        resolved: The absolute path the request actually pointed at.
        reason: Human-readable outcome detail (the guard's own message).
        measurement: Result of :func:`measure`, taken before the delete.
        caller: An identity the lane already established more strongly than
            cwd can. The broker authenticates its requester over HMAC and then
            deletes on their behalf, so resolving from cwd there would record
            the daemon's own location instead of whoever asked. Left unset,
            the shared resolver answers.

    Never raises. A failed record is reported at ERROR and the caller carries
    on: losing the log must not turn into losing the delete.
    """
    cwd = caller_cwd()
    caller = caller or resolve_caller_identity(cwd) or UNKNOWN_CALLER
    shape = measurement or {"kind": "unknown", "size_bytes": None, "entry_count": None, "measured": "none"}

    record = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "lane": lane,
        "outcome": outcome,
        "caller": caller,
        "cwd": str(cwd) if cwd is not None else NO_CURRENT_DIRECTORY,
        "requested": requested,
        "path": str(resolved),
        "reason": reason,
        **shape,
    }

    logger.info(
        "deletion record: %s %s by %s — %s (%s, size=%s, entries=%s)",
        outcome,
        record["path"],
        caller,
        lane,
        record["kind"],
        record["size_bytes"],
        record["entry_count"],
    )

    json_handler.log_operation(
        "deletion_record",
        {"lane": lane, "outcome": outcome, "path": record["path"], "caller": caller},
    )

    try:
        _append_record(record, deletion_log_path())
    except Exception as exc:
        # Loud, because the durable half of the record is the half that
        # survives to be searched. The prax line above already landed, so the
        # event is not lost — but the store being unwritable is its own fault
        # to fix and must not pass in silence.
        logger.error("deletion record: failed to write store for %s: %s", record["path"], exc)

    return record
