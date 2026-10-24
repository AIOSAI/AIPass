# =================== AIPass ====================
# Name: builder.py
# Description: Destination path builders for snapshot, versioned, and drive modes
# Version: 2.2.1
# Created: 2026-04-16
# Modified: 2026-10-24
# =============================================

"""Path builder handler."""

import hashlib
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


def build_versioned_store(project_root: str) -> Path:
    """Persistent versioned store: <project>/.backup/versioned/"""
    trail.log_operation("build_versioned_store", {"project_root": project_root})
    return backup_root(project_root) / "versioned"


#: Top-level files live under this folder; a project's own top-level ``root/`` is nested under it too.
VERSIONED_ROOT = "root"
_LONG_NAME = 50


def versioned_folder_name(name: str) -> str:
    """The file-folder name the versioned store gives a file called ``name``."""
    if len(name) > _LONG_NAME:
        return name[:30] + "_" + hashlib.md5(name.encode()).hexdigest()[:8]
    return name


def build_versioned_file_path(
    project_root: str,
    rel_path: str,
) -> Path:
    """Build the file-folder target path for a versioned file."""
    store = build_versioned_store(project_root)
    p = Path(rel_path)
    parent = p.parent
    # Prefixing a real root/ as well keeps "x.py" and "root/x.py" in different folders.
    if parent == Path(".") or p.parts[0] == VERSIONED_ROOT:
        parent = VERSIONED_ROOT / parent
    return store / parent / versioned_folder_name(p.name) / p.name


def versioned_rel_path(store_parent: str, name: str) -> str:
    """The project-relative path of the file stored under ``store_parent``; the inverse of the builder."""
    return f"{store_parent}/{name}".removeprefix(f"{VERSIONED_ROOT}/")
