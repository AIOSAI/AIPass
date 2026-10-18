# =================== AIPass ====================
# Name: tracker.py
# Description: Drive upload tracker — mtime+size dedup for file sync
# Version: 1.2.0
# Created: 2026-04-16
# Modified: 2026-10-17
# =============================================

"""Drive upload tracker.

An unstamped tracker keys versioned-store paths, wrong for the snapshot lane:
set_aside_foreign_tracker moves it aside (kept, never deleted).
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from aipass.prax import logger

from ..audit import trail
from ..json import json_handler

TRACKER_FILENAME = "drive_tracker.json"
SET_ASIDE_FILENAME = "drive_tracker.versioned.json"
# Every key but LANE_KEY is a file entry.
LANE_KEY = "_lane"
DRIVE_LANE = "snapshot"


def _tracker_path(project_root: str) -> Path:
    """Return the tracker file path for a project."""
    from ..path.builder import backup_root

    return backup_root(project_root) / TRACKER_FILENAME


def load_tracker(project_root: str) -> dict:
    """Load tracker from .backup/drive_tracker.json, without the lane stamp.

    Unreadable raises: an empty answer would re-upload all and let save overwrite it.
    """
    path = _tracker_path(project_root)
    data = json_handler.read_json(path)
    if data is None:
        if path.exists():
            raise json_handler.InvalidDocument(f"Drive tracker unreadable: {path}")
        data = {}
    if not isinstance(data, dict):
        raise json_handler.InvalidDocument(f"Drive tracker is not a JSON object: {path}")
    data.pop(LANE_KEY, None)
    trail.log_operation(
        "load_tracker",
        {"project_root": project_root, "entries": len(data)},
    )
    return data


def save_tracker(project_root: str, tracker: dict) -> None:
    """Save tracker to .backup/drive_tracker.json, stamped with DRIVE_LANE; WriteFailed on failure."""
    path = _tracker_path(project_root)
    if not json_handler.write_json(path, {LANE_KEY: DRIVE_LANE, **tracker}):
        raise json_handler.WriteFailed(f"Drive tracker write failed: {path}")
    trail.log_operation(
        "save_tracker",
        {"project_root": project_root, "entries": len(tracker)},
    )


def set_aside_foreign_tracker(project_root: str) -> Path | None:
    """Move a non-empty tracker that does not answer for DRIVE_LANE out of the way.

    An existing SET_ASIDE_FILENAME raises WriteFailed: overwriting it deletes an earlier kept tracker.
    """
    path = _tracker_path(project_root)
    data = json_handler.read_json(path)
    if data is None:
        if path.exists():
            raise json_handler.InvalidDocument(f"Drive tracker unreadable: {path}")
        return None
    if not isinstance(data, dict):
        raise json_handler.InvalidDocument(f"Drive tracker is not a JSON object: {path}")
    lane = data.get(LANE_KEY)
    entries = len(data) - (LANE_KEY in data)
    if lane == DRIVE_LANE or entries == 0:
        return None

    aside = path.with_name(SET_ASIDE_FILENAME)
    if aside.exists():
        raise json_handler.WriteFailed(
            f"Drive tracker {path} tracks lane {lane or 'versioned (unstamped)'}, "
            f"and {aside} already exists; move one of them by hand"
        )
    path.rename(aside)
    logger.info(
        f"[backup] Drive tracker for lane {lane or 'versioned (unstamped)'} set aside as {aside} "
        f"({entries} entries); a fresh {DRIVE_LANE} tracker starts"
    )
    trail.log_operation(
        "tracker_set_aside",
        {"project_root": project_root, "lane": lane, "entries": entries, "set_aside": str(aside)},
    )
    return aside


def check_needs_upload(
    tracker: dict,
    local_file: Path,
    backup_root: Path,
) -> bool:
    """Check if a file needs upload (new or mtime/size changed); local only, no API calls.

    True when the path is foreign or unstatable: the upload names the failure, False would skip it silently.
    """
    try:
        rel_key = str(local_file.relative_to(backup_root))
    except ValueError:
        logger.info(f"File {local_file} not relative to {backup_root}")
        return True

    if rel_key not in tracker:
        return True

    entry = tracker[rel_key]
    try:
        stat = local_file.stat()
        if stat.st_size != entry.get("local_size"):
            return True
        if stat.st_mtime != entry.get("local_mtime"):
            return True
    except OSError as exc:
        logger.info(f"Failed to stat {local_file}: {exc}")
        return True

    return False


def update_entry(
    tracker: dict,
    local_file: Path,
    backup_root: Path,
    drive_file_id: str,
) -> None:
    """Update tracker entry (in place) after successful upload."""
    try:
        rel_key = str(local_file.relative_to(backup_root))
    except ValueError:
        logger.info(f"File {local_file} not relative to {backup_root}, using absolute")
        rel_key = str(local_file)

    try:
        stat = local_file.stat()
        tracker[rel_key] = {
            "local_size": stat.st_size,
            "local_mtime": stat.st_mtime,
            "drive_id": drive_file_id,
            "last_sync": datetime.now(timezone.utc).isoformat(),
        }
    except OSError as exc:
        logger.info(f"Failed to stat {local_file} for tracker update: {exc}")
        tracker[rel_key] = {
            "local_size": 0,
            "local_mtime": 0.0,
            "drive_id": drive_file_id,
            "last_sync": datetime.now(timezone.utc).isoformat(),
        }


def clean_tracker(tracker: dict, existing_files: set) -> list[str]:
    """Remove entries (in place) for files that no longer exist; return the removed keys."""
    stale = [k for k in tracker if k not in existing_files]
    for key in stale:
        del tracker[key]
    if stale:
        trail.log_operation(
            "clean_tracker",
            {"removed": len(stale)},
        )
    return stale


def get_stats(tracker: dict) -> dict:
    """Return tracker statistics: total count and sample entries."""
    total = len(tracker)
    sample = dict(list(tracker.items())[:5]) if tracker else {}
    return {
        "total": total,
        "sample": sample,
    }


def clear_all(project_root: str) -> bool:
    """Clear entire tracker file; True if cleared."""
    path = _tracker_path(project_root)
    if not json_handler.write_json(path, {}):
        logger.warning(f"Failed to clear tracker at {path}")
        return False
    trail.log_operation(
        "clear_tracker",
        {"project_root": project_root},
    )
    return True
