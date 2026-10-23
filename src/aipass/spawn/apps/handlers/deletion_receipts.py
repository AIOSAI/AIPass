# =================== AIPass ====================
# Name: deletion_receipts.py
# Description: Receipt rows for delete and retire-project, written to the fleet deletion trail through drone's door
# Version: 1.0.0
# Created: 2026-10-22
# Modified: 2026-10-22
# =============================================

"""Receipt rows for spawn's removals: measured and validated before anything goes, written after.

drone's door writes the moment it is called, so validation here is what lets a bad row stop the removal.
"""

import os
from pathlib import Path

from aipass.prax.apps.modules.logger import system_logger as logger

from aipass.drone.apps.modules.door_deletion_log import record_deletion
from aipass.spawn.apps.handlers.json import json_handler

# The door refuses a row missing any of these; the measurement must carry exactly drone's four keys.
_REQUIRED = ("lane", "caller", "resolved", "target")
_MEASUREMENT_KEYS = frozenset({"kind", "size_bytes", "entry_count", "measured"})


def measure(path: Path) -> dict:
    """Describe *path* before it goes: kind, size, entry count, in drone rm's measurement shape."""
    path = Path(path)
    if path.is_file():
        return {"kind": "file", "size_bytes": path.stat().st_size, "entry_count": None, "measured": "exact"}
    if not path.is_dir():
        return {"kind": "unknown", "size_bytes": None, "entry_count": None, "measured": "none"}
    failures: list[OSError] = []
    size = entries = 0
    for dirpath, dirnames, filenames in os.walk(path, onerror=failures.append):
        entries += len(dirnames) + len(filenames)
        for name in filenames:
            try:
                size += (Path(dirpath) / name).lstat().st_size
            except OSError as exc:
                failures.append(exc)
    if failures:
        logger.warning("[receipts] %d unreadable entries under %s: %s", len(failures), path, failures[0])
    return {
        "kind": "directory",
        "size_bytes": size,
        "entry_count": entries,
        "measured": "partial" if failures else "exact",
    }


def build_receipt(*, lane, caller, requested, resolved, target, reason, measurement) -> dict:
    """One row's fields, every value a string except the measurement; the outcome is added at write time."""
    return {
        "lane": lane,
        "caller": caller,
        "requested": str(requested),
        "resolved": str(resolved),
        "target": str(target),
        "reason": reason,
        "measurement": measurement,
    }


def receipt_problem(rows: list[dict]) -> str | None:
    """The first reason drone's door would refuse a row, None when every row would be written."""
    for row in rows:
        for name in _REQUIRED:
            if not str(row.get(name) or "").strip():
                return f"receipt row for {row.get('resolved') or '?'} has no {name} - nothing removed"
        if set(row.get("measurement") or {}) != _MEASUREMENT_KEYS:
            return f"receipt row for {row['resolved']} has a malformed measurement - nothing removed"
    return None


def write_receipts(rows: list[dict], outcome: str, project_root: Path) -> int:
    """Write each row to the fleet deletion trail under *project_root*; returns how many landed."""
    written = 0
    for row in rows:
        try:
            record_deletion(outcome=outcome, project_root=project_root, **row)
            written += 1
        except ValueError as exc:
            logger.error("[receipts] drone refused the row for %s after removal: %s", row["resolved"], exc)
    json_handler.log_operation("receipts_written", data={"outcome": outcome, "rows": len(rows), "written": written})
    return written
