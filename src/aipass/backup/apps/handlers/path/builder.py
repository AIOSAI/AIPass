# =================== AIPass ====================
# Name: builder.py
# Description: Destination path builders for the snapshot store and its config files
# Version: 3.1.0
# Created: 2026-04-16
# Modified: 2026-11-26
# =============================================

"""Path builder handler."""

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


def build_baseline_path(project_root: str) -> Path:
    """Run baseline: <project>/.backup/last_good_run.json"""
    return backup_root(project_root) / "last_good_run.json"


def build_changelog_path(project_root: str) -> Path:
    """Changelog file: <project>/.backup/changelog.json"""
    return backup_root(project_root) / "changelog.json"
