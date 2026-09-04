# =================== AIPass ====================
# Name: timestamps.py
# Description: Per-project last-backup timestamp persistence
# Version: 1.1.0
# Created: 2026-04-16
# Modified: 2026-09-03
# =============================================

"""Timestamp state handler.

Persists per-file modification timestamps recorded at the last backup so the
versioned copy strategy can detect changes.
"""

from ..audit import trail
from ..json import json_handler
from ..path import builder


def load_timestamps(project_root: str) -> dict:
    """Load the timestamp map for a project.

    Args:
        project_root: Absolute path to the project root.

    Returns:
        Mapping of relative_path to last recorded mtime (float seconds).

    Raises:
        InvalidDocument: The map exists but cannot be read as a JSON object.
            Answering an empty map would make every file look changed AND let
            the next save_timestamps overwrite the unreadable document.
    """
    ts_path = builder.build_timestamps_path(project_root)
    data = json_handler.read_json(ts_path)
    if data is None:
        if ts_path.exists():
            raise json_handler.InvalidDocument(f"Timestamp map unreadable: {ts_path}")
        data = {}
    if not isinstance(data, dict):
        raise json_handler.InvalidDocument(f"Timestamp map is not a JSON object: {ts_path}")
    trail.log_operation("load_timestamps", {"project_root": project_root, "count": len(data)})
    return data


def save_timestamps(project_root: str, data: dict) -> None:
    """Persist the timestamp map for a project.

    Args:
        project_root: Absolute path to the project root.
        data: Mapping of relative_path to mtime (float seconds).

    Raises:
        WriteFailed: The map could not be written. A versioned run whose
            timestamps never landed copies everything again next time, so the
            failure is surfaced rather than counted as a success.
    """
    ts_path = builder.build_timestamps_path(project_root)
    if not json_handler.write_json(ts_path, data):
        raise json_handler.WriteFailed(f"Timestamp map write failed: {ts_path}")
    trail.log_operation("save_timestamps", {"project_root": project_root, "count": len(data)})


# =============================================
