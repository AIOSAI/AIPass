# =================== AIPass ====================
# Name: tracker.py
# Description: Drive upload tracker — mtime+size dedup for file sync
# Version: 1.1.0
# Created: 2026-04-16
# Modified: 2026-09-03
# =============================================

"""Drive upload tracker.

Maintains a persistent mapping of local file paths to Drive metadata
(file ID, mtime, size) so repeat syncs can skip unchanged files.
Tracker is stored at ``<project>/.backup/drive_tracker.json``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from aipass.prax import logger

from ..audit import trail
from ..json import json_handler

TRACKER_FILENAME = "drive_tracker.json"


def _tracker_path(project_root: str) -> Path:
    """Return the tracker file path for a project."""
    from ..path.builder import backup_root

    return backup_root(project_root) / TRACKER_FILENAME


def load_tracker(project_root: str) -> dict:
    """Load tracker from .backup/drive_tracker.json.

    Returns:
        Dict keyed by relative file path with metadata values.

    Raises:
        InvalidDocument: The tracker exists but cannot be read as a JSON
            object. An empty tracker would re-upload the whole store AND let
            the next save_tracker overwrite the unreadable document.
    """
    path = _tracker_path(project_root)
    data = json_handler.read_json(path)
    if data is None:
        if path.exists():
            raise json_handler.InvalidDocument(f"Drive tracker unreadable: {path}")
        data = {}
    if not isinstance(data, dict):
        raise json_handler.InvalidDocument(f"Drive tracker is not a JSON object: {path}")
    trail.log_operation(
        "load_tracker",
        {"project_root": project_root, "entries": len(data)},
    )
    return data


def save_tracker(project_root: str, tracker: dict) -> None:
    """Save tracker to .backup/drive_tracker.json.

    Raises:
        WriteFailed: The tracker could not be written. A sync whose tracker
            never landed re-uploads every file next run, so it is surfaced
            rather than counted as a success.
    """
    path = _tracker_path(project_root)
    if not json_handler.write_json(path, tracker):
        raise json_handler.WriteFailed(f"Drive tracker write failed: {path}")
    trail.log_operation(
        "save_tracker",
        {"project_root": project_root, "entries": len(tracker)},
    )


def check_needs_upload(
    tracker: dict,
    local_file: Path,
    backup_root: Path,
) -> bool:
    """Check if a file needs upload (new or mtime/size changed).

    Pure local check -- no API calls.

    Args:
        tracker: Current tracker dict.
        local_file: Absolute path to the local file.
        backup_root: Root directory for computing relative paths.

    Returns:
        True if the file is new or has changed since last sync.
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
    """Update tracker entry after successful upload.

    Args:
        tracker: Tracker dict (mutated in place).
        local_file: Absolute path to the uploaded file.
        backup_root: Root directory for computing relative paths.
        drive_file_id: Drive file ID assigned to the uploaded resource.
    """
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
    """Remove entries for files that no longer exist.

    Args:
        tracker: Tracker dict (mutated in place).
        existing_files: Set of relative file paths that still exist.

    Returns:
        List of removed keys.
    """
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
    """Return tracker statistics.

    Returns:
        Dict with total count and sample entries.
    """
    total = len(tracker)
    sample = dict(list(tracker.items())[:5]) if tracker else {}
    return {
        "total": total,
        "sample": sample,
    }


def clear_all(project_root: str) -> bool:
    """Clear entire tracker file.

    Returns:
        True if cleared successfully.
    """
    path = _tracker_path(project_root)
    if not json_handler.write_json(path, {}):
        logger.warning(f"Failed to clear tracker at {path}")
        return False
    trail.log_operation(
        "clear_tracker",
        {"project_root": project_root},
    )
    return True


# =============================================
