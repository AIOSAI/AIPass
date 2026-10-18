# =================== AIPass ====================
# Name: builder.py
# Description: Destination path builders for snapshot, versioned, and drive modes
# Version: 2.2.0
# Created: 2026-04-16
# Modified: 2026-10-17
# =============================================

"""Path builder handler."""

import os
from pathlib import Path

from ..audit import trail

BACKUP_DIR = ".backup"

#: Windows' MAX_PATH only: on POSIX an over-long path is the OS's OSError, which each lane records,
#: and a 260 guard there only kept real files out of the store.
_MAX_PATH = 260 if os.name == "nt" else None


def exceeds_max_path(target: str) -> bool:
    """True when a store path is longer than this platform lets the lane write."""
    return _MAX_PATH is not None and len(target) > _MAX_PATH


def backup_root(project_root: str) -> Path:
    """Return the .backup/ path for a project."""
    return Path(project_root) / BACKUP_DIR


def build_snapshot_path(project_root: str) -> Path:
    """Snapshot destination: <project>/.backup/snapshots/"""
    trail.log_operation("build_snapshot_path", {"project_root": project_root})
    return backup_root(project_root) / "snapshots"


def build_config_path(project_root: str) -> Path:
    """Config file: <project>/.backup/config.json"""
    return backup_root(project_root) / "config.json"


def build_ignore_path(project_root: str) -> Path:
    """Ignore file: <project>/.backupignore"""
    return Path(project_root) / ".backupignore"


def build_timestamps_path(project_root: str) -> Path:
    """Timestamps file: <project>/.backup/timestamps.json"""
    return backup_root(project_root) / "timestamps.json"


def build_changelog_path(project_root: str) -> Path:
    """Changelog file: <project>/.backup/changelog.json"""
    return backup_root(project_root) / "changelog.json"


def build_log_dir(project_root: str) -> Path:
    """Log directory: <project>/.backup/logs/"""
    return backup_root(project_root) / "logs"


def build_versioned_store(project_root: str) -> Path:
    """Persistent versioned store: <project>/.backup/versioned/"""
    trail.log_operation("build_versioned_store", {"project_root": project_root})
    return backup_root(project_root) / "versioned"


def build_versioned_file_path(
    project_root: str,
    rel_path: str,
) -> Path:
    """Build the file-folder target path for a versioned file."""
    import hashlib

    store = build_versioned_store(project_root)
    p = Path(rel_path)
    name = p.name
    parent = str(p.parent)

    if len(name) > 50:
        name_hash = hashlib.md5(name.encode()).hexdigest()[:8]
        folder_name = name[:30] + f"_{name_hash}"
    else:
        folder_name = name

    if parent == ".":
        return store / "root" / folder_name / name
    return store / parent / folder_name / name


def build_drive_path(project_root: str, file: str) -> Path:
    """Drive destination for one snapshot-store-relative file, as a single path."""
    # REMOTE: mirrors the folders drive/client.py and drive/upload.py create; no name shortening on Drive.
    from ..drive.client import BACKUP_FOLDER_NAME
    from ..drive.tracker import DRIVE_LANE

    return Path(BACKUP_FOLDER_NAME) / Path(project_root).name / DRIVE_LANE / file
