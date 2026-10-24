# =================== AIPass ====================
# Name: deletion_log.py
# Description: Durable record of every delete drone performs
# Version: 1.3.1
# Created: 2026-08-14
# Modified: 2026-10-24
# =============================================

"""Durable record of every delete drone performs.

Reference: docs/rm_and_the_record.md
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
from aipass.drone.apps.handlers.router_handler import (
    caller_cwd,
    find_project_root,
    resolve_caller_identity_signal,
)

_LOG_DIR_NAME = ".ai_central"
_LOG_NAME = "deletions.jsonl"

# Relocates the durable store only; the prax line is emitted first and cannot be silenced.
_PATH_ENV_VAR = "AIPASS_DELETION_LOG"

# Bounded: an unbounded delete log becomes the runaway log monitoring exists to catch.
_MAX_BYTES = 2 * 1024 * 1024
_ROTATIONS = 1

# A delete of something enormous must not pay an unbounded walk before it starts.
_MEASURE_ENTRY_CAP = 10_000

OUTCOME_DELETED = "deleted"
OUTCOME_REFUSED = "refused"
OUTCOME_FAILED = "failed"
OUTCOME_NOT_FOUND = "not_found"

LANE_RM = "rm"
LANE_BROKER = "broker"

UNKNOWN_CALLER = "unknown"

# The cwd field once a delete removed the cwd; "/" or the deleted path would read as a real place.
NO_CURRENT_DIRECTORY = "<none: deleted during this operation>"


def _resolve_citizen_caller(cwd: Path | None) -> str:
    """Name the CITIZEN who deleted, or say ``unknown`` — never a directory.

    The resolver's ``project`` source is refused: it answers "where", and this field asks "who".
    """
    signal = resolve_caller_identity_signal(cwd)
    if signal.name and signal.source in ("assigned", "passport"):
        return signal.name
    return UNKNOWN_CALLER


def _temp_dir() -> Path:
    """The host's temp directory, where a deletion outside any project is recorded.

    Named so tests can patch it instead of replacing tempfile.tempdir process-wide.
    """
    return Path(tempfile.gettempdir())


def deletion_log_path(project_root: Path | None = None) -> Path:
    """Return the deletion log path for the project the deletion belongs to.

    One log per project, temp dir when there is none; ``AIPASS_DELETION_LOG`` overrides both.
    The broker passes ``project_root`` because it may serve a repo it is not standing in.
    """
    override = os.environ.get(_PATH_ENV_VAR)
    if override:
        return Path(override)

    root = project_root if project_root is not None else find_project_root()
    if root is None:
        return _temp_dir() / _LOG_NAME
    return root / _LOG_DIR_NAME / _LOG_NAME


def measure(path: Path) -> dict:
    """Describe *path* before it is deleted: kind, size, entry count.

    Symlinks are measured, never followed: following would report a file that survives.
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
    # Without onerror an unlistable folder drops out silently and the size reads as exact.
    unlisted: list[OSError] = []

    for dirpath, dirnames, filenames in os.walk(path, onerror=unlisted.append):
        here = Path(dirpath)
        for name in (*dirnames, *filenames):
            if entries >= _MEASURE_ENTRY_CAP:
                measured = "capped"
                break
            entries += 1
            try:
                st = (here / name).lstat()
            except OSError as exc:
                # DEBUG per entry, one INFO total after the walk: per-file INFO buries the signal.
                logger.debug("deletion record: cannot stat %s: %s", here / name, exc)
                unreadable += 1
                continue
            if not stat.S_ISDIR(st.st_mode):
                total += st.st_size
        if measured == "capped":
            break

    unreadable += len(unlisted)
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

    Uses ``replace``, never unlink: the delete ledger performs no delete of its own.
    """
    try:
        if not log_path.exists() or log_path.stat().st_size < _MAX_BYTES:
            return
    except OSError as exc:
        # Loud: a silently skipped rotation is how the bounded log grows without limit.
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


def ledger_beside(name: str, project_root: Path | None = None) -> Path:
    """Path for another of drone's ledgers, kept in the same folder as this one.

    It follows ``AIPASS_DELETION_LOG``, so one variable keeps a test run out of every live store.
    """
    return deletion_log_path(project_root).parent / name


def append_ledger_line(record: dict, log_path: Path) -> None:
    """Append one JSON line to a ledger, with the same bound this store keeps."""
    _append_record(record, log_path)


def record_deletion(
    *,
    lane: str,
    outcome: str,
    requested: str,
    resolved: Path | str,
    reason: str,
    measurement: dict | None = None,
    caller: str | None = None,
    project_root: Path | None = None,
    mode: str | None = None,
    age: str | None = None,
    target: Path | str | None = None,
) -> dict:
    """Write one deletion record to both channels and return it.

    ``caller``/``project_root``: the broker passes its HMAC-authenticated requester and served repo.
    ``mode``/``age``/``target`` add keys only when given; a plain delete keeps its twelve.
    Never raises: losing the log must not turn into losing the delete.
    """
    cwd = caller_cwd()
    caller = caller or _resolve_citizen_caller(cwd)
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
    if mode is not None:
        record["mode"] = mode
        record["age"] = age
    if target is not None:
        record["target"] = str(target)

    logger.info(
        "deletion record: %s %s%s by %s — %s (%s, size=%s, entries=%s)%s",
        outcome,
        record["path"],
        f" -> {target}" if target is not None else "",
        caller,
        lane,
        record["kind"],
        record["size_bytes"],
        record["entry_count"],
        f" mode={mode} age={age}" if mode is not None else "",
    )

    json_handler.log_operation(
        "deletion_record",
        {"lane": lane, "outcome": outcome, "path": record["path"], "caller": caller},
    )

    try:
        _append_record(record, deletion_log_path(project_root))
    except Exception as exc:
        # The prax line already landed, but an unwritable store is its own fault to fix.
        logger.error("deletion record: failed to write store for %s: %s", record["path"], exc)

    return record


_MEASUREMENT_KEYS = frozenset({"kind", "size_bytes", "entry_count", "measured"})


def record_foreign_deletion(
    *,
    lane: str,
    outcome: str,
    caller: str,
    requested: str,
    resolved: Path | str,
    target: Path | str,
    reason: str,
    measurement: dict | None = None,
    project_root: Path | None = None,
) -> dict:
    """Record another branch's removal in drone rm's row shape; ValueError on a half row, never written."""
    for name, value in (
        ("lane", lane),
        ("outcome", outcome),
        ("caller", caller),
        ("resolved", resolved),
        ("target", target),
    ):
        if not str(value or "").strip():
            raise ValueError(f"record_deletion: {name} is required, got {value!r}")
    if measurement is not None and set(measurement) != _MEASUREMENT_KEYS:
        raise ValueError(
            f"record_deletion: measurement keys must be {sorted(_MEASUREMENT_KEYS)}, got {sorted(measurement)}"
        )
    return record_deletion(
        lane=lane,
        outcome=outcome,
        caller=caller,
        requested=requested,
        resolved=resolved,
        target=target,
        reason=reason,
        measurement=measurement,
        project_root=project_root,
    )
