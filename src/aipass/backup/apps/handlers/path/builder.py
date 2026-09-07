# =================== AIPass ====================
# Name: builder.py
# Description: Destination path builders for snapshot, versioned, and drive modes
# Version: 2.0.0
# Created: 2026-04-16
# Modified: 2026-06-12
# =============================================

"""Path builder handler.

Computes destination paths for backup modes. All paths are relative to the
target project's .backup/ directory.
"""

from pathlib import Path

from ..audit import trail

BACKUP_DIR = ".backup"


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
    """Build the file-folder target path for a versioned file.

    Layout:
        root-level file: <store>/root/<name>/<name>
        nested file: <store>/<parent>/<name>/<name>
        name >50 chars: <parent>/<name[:30]_md5[:8]>/<name>
    """
    import hashlib

    store = build_versioned_store(project_root)
    p = Path(rel_path)
    name = p.name
    parent = str(p.parent)

    if len(name) > 50:
        name_hash = hashlib.md5(name.encode()).hexdigest()[:8]  # noqa: S324
        folder_name = name[:30] + f"_{name_hash}"
    else:
        folder_name = name

    if parent == ".":
        return store / "root" / folder_name / name
    return store / parent / folder_name / name


def build_drive_path(project_root: str, file: str) -> Path:
    """Drive-sync path for a single file (deferred to DPLAN-003)."""
    return Path()


# =============================================
