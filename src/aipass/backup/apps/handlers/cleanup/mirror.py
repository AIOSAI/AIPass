# =================== AIPass ====================
# Name: mirror.py
# Description: Mirror cleanup handler — removes snapshot files whose source no longer exists
# Version: 2.0.0
# Created: 2026-06-12
# Modified: 2026-06-12
# =============================================

"""Mirror cleanup handler — removes snapshot files whose source no longer exists."""

import stat
from pathlib import Path

from aipass.prax import logger

from ..audit import trail
from ..report.result import BackupResult


def _make_writable(path: Path) -> None:
    """Best-effort chmod to make a file writable before deletion."""
    try:
        path.chmod(stat.S_IWRITE | stat.S_IREAD)
    except OSError as e:
        logger.info(f"[cleanup] Could not chmod {path}: {e}")


def _should_delete(backup_file: Path, backup_path: Path, source_dir: Path) -> str | None:
    """Return the relative path string if the file should be deleted, else None."""
    rel = backup_file.relative_to(backup_path)
    source_file = source_dir / rel

    if source_file.exists():
        return None

    return str(rel).replace("\\", "/")


def _delete_stale_files(
    backup_path: Path,
    source_dir: Path,
    result: BackupResult,
    dry_run: bool,
) -> None:
    """Pass 1: delete files whose source is gone."""
    for backup_file in list(backup_path.rglob("*")):
        if not backup_file.is_file():
            continue
        try:
            rel_str = _should_delete(backup_file, backup_path, source_dir)
            if rel_str is None:
                continue

            if dry_run:
                result.files_deleted += 1
                continue

            _make_writable(backup_file)
            backup_file.unlink()
            result.files_deleted += 1
        except PermissionError as e:
            result.add_error(f"Permission denied deleting {backup_file}: {e}")
            logger.warning(f"[cleanup] Permission denied: {backup_file}: {e}")
        except Exception as e:
            result.add_warning(f"Error deleting {backup_file}: {e}")
            logger.warning(f"[cleanup] Error: {backup_file}: {e}")


def _remove_empty_dirs(
    backup_path: Path,
    source_dir: Path,
    dry_run: bool,
) -> None:
    """Pass 2: remove empty directories bottom-up."""
    all_dirs = sorted(
        [d for d in backup_path.rglob("*") if d.is_dir()],
        key=lambda p: len(p.parts),
        reverse=True,
    )
    for d in all_dirs:
        try:
            if any(d.iterdir()):
                continue
            rel = d.relative_to(backup_path)
            source_d = source_dir / rel
            if not source_d.exists() and not dry_run:
                d.rmdir()
        except OSError as e:
            logger.info(f"[cleanup] Could not remove dir {d}: {e}")


def cleanup_deleted_files(
    backup_path: Path,
    source_dir: Path,
    should_ignore,
    result: BackupResult,
    dry_run: bool = False,
) -> None:
    """Remove snapshot files whose source no longer exists.

    Args:
        backup_path: Snapshot destination directory.
        source_dir: Original project root.
        should_ignore: Callable(Path) -> bool for ignore check.
        result: BackupResult to track deletions.
        dry_run: If True, only count what would be deleted.
    """
    trail.log_operation("cleanup_started", {"backup_path": str(backup_path)})

    if not backup_path.exists():
        return

    try:
        _delete_stale_files(backup_path, source_dir, result, dry_run)
        _remove_empty_dirs(backup_path, source_dir, dry_run)
    except Exception as e:
        result.add_warning(f"Cleanup scan error: {e}")
        logger.warning(f"[cleanup] Scan error: {e}")

    trail.log_operation(
        "cleanup_complete",
        {"files_deleted": result.files_deleted, "dry_run": dry_run},
    )
    logger.info(f"[cleanup] Deleted {result.files_deleted} files (dry_run={dry_run})")


# =============================================
