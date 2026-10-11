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
        name_hash = hashlib.md5(name.encode()).hexdigest()[:8]
        folder_name = name[:30] + f"_{name_hash}"
    else:
        folder_name = name

    if parent == ".":
        return store / "root" / folder_name / name
    return store / parent / folder_name / name


def build_drive_path(project_root: str, file: str) -> Path:
    """Drive destination for one store-relative file, as a single path.

    This is a REMOTE path, not a local one: it names the folder hierarchy the
    Drive lane creates, which the lane itself only ever holds as folder ids.
    Read off the shipped sync (DPLAN-003 is closed), in the order the ids are
    resolved:

        drive/client.py:150-227   the root folder, BACKUP_FOLDER_NAME
        drive/upload.py:67        the project folder, named by the caller;
                                  drive_sync.py:139-140 defaults that name to
                                  the project directory's own name
        drive/upload.py:78-83     rel_path.parent, one nested folder a segment
        drive/upload.py:122-125   the create body's "name", the file's leaf

    Layout:
        <BACKUP_FOLDER_NAME>/<project dir name>/<rel_path>

    Args:
        project_root: Absolute path to the project.
        file: Path of the file relative to the versioned store -- the same
            key drive/tracker.py records it under.

    Returns:
        The Drive-side path of the file.
    """
    # No name shortening here, unlike build_versioned_file_path above: the
    # store already applied it on the way in, so rel_path arrives carrying the
    # hashed folder. Nothing under handlers/drive/ hashes a name.
    from ..drive.client import BACKUP_FOLDER_NAME

    return Path(BACKUP_FOLDER_NAME) / Path(project_root).name / file


# =============================================
