# =================== AIPass ====================
# Name: snapshot.py
# Description: Snapshot copy strategy — mirror destination tree with cleanup
# Version: 3.0.0
# Created: 2026-04-16
# Modified: 2026-06-12
# =============================================

"""Snapshot copy handler — mirror destination tree with cleanup."""

import os
import shutil
import stat
from pathlib import Path

import pathspec

from aipass.prax import logger

from ..cleanup.mirror import cleanup_deleted_files
from ..ignore.patterns import is_ignored
from ..audit import trail
from ..report.result import BackupResult


def _should_skip_mtime(abs_path: str, target: str) -> bool:
    """Return True if source and target have identical mtime."""
    try:
        src_mtime = os.path.getmtime(abs_path)
        dst_mtime = os.path.getmtime(target)
        return src_mtime == dst_mtime
    except OSError as e:
        logger.info(f"[snapshot] mtime check failed, will recopy: {e}")
        return False


def _make_target_writable(target_path: Path) -> None:
    """Best-effort chmod to make an existing target writable before overwrite."""
    try:
        target_path.chmod(stat.S_IWRITE | stat.S_IREAD)
    except OSError as e:
        logger.warning(f"[snapshot] Could not chmod {target_path}: {e}")


def _should_ignore_for_cleanup(path: Path, project_root: str, spec: pathspec.PathSpec) -> bool:
    """Check whether a path matches the ignore spec."""
    try:
        rel = str(path.relative_to(project_root)).replace("\\", "/")
    except ValueError as e:
        logger.info(f"[snapshot] Path not relative to project root: {path}: {e}")
        return False
    return is_ignored(rel, spec)


def _copy_single_file(
    abs_path: str,
    rel_path: str,
    dest_path: Path,
    errors: list[str],
) -> int:
    """Copy a single file to the snapshot destination, returning bytes copied.

    Skips unchanged files (same mtime), handles read-only targets.
    Returns bytes copied (0 if skipped or errored).
    """
    target = str(dest_path / rel_path)

    # Long-path guard
    if len(target) > 260:
        logger.warning(f"Path too long (>260 chars), skipping: {rel_path}")
        errors.append(f"{rel_path}: path too long (>260 chars)")
        return -1  # signal: skipped due to error

    target_path = Path(target)
    target_path.parent.mkdir(parents=True, exist_ok=True)

    # Skip if target exists and has same mtime
    if target_path.exists():
        if _should_skip_mtime(abs_path, target):
            return -1  # signal: skipped, unchanged
        _make_target_writable(target_path)

    shutil.copy2(abs_path, target)
    return os.path.getsize(abs_path)


def _run_mirror_cleanup(dest_path: Path, project_root: str, spec: pathspec.PathSpec) -> int:
    """Run mirror-delete cleanup on an existing snapshot destination."""
    cleanup_result = BackupResult(mode="snapshot", project_root=project_root)
    cleanup_deleted_files(
        dest_path,
        Path(project_root),
        lambda p: _should_ignore_for_cleanup(p, project_root, spec),
        cleanup_result,
    )
    return cleanup_result.files_deleted


def copy_snapshot(
    files: list[tuple[str, str]],
    dest: str,
    project_root: str,
    spec: pathspec.PathSpec,
    on_progress=None,
) -> dict:
    """Copy files into a snapshot destination with mirror-delete.

    Args:
        files: List of (absolute_path, relative_path) tuples.
        dest: Absolute destination directory path.
        project_root: Project root for cleanup source reference.
        spec: Compiled PathSpec for ignore matching during cleanup.
        on_progress: Optional callback after each file.

    Returns:
        Dict with files_copied, bytes_copied, errors, files_deleted.
    """
    dest_path = Path(os.path.realpath(dest))

    # Mirror-delete: remove snapshot files whose source is gone
    files_deleted = 0
    if dest_path.exists():
        files_deleted = _run_mirror_cleanup(dest_path, project_root, spec)

    dest_path.mkdir(parents=True, exist_ok=True)

    files_copied = 0
    bytes_copied = 0
    errors: list[str] = []

    for abs_path, rel_path in files:
        try:
            result_bytes = _copy_single_file(abs_path, rel_path, dest_path, errors)
            if result_bytes >= 0:
                bytes_copied += result_bytes
                files_copied += 1
        except OSError as e:
            logger.warning(f"Failed to copy {rel_path}: {e}")
            errors.append(f"{rel_path}: {e}")

        if on_progress:
            on_progress()

    result = {
        "files_copied": files_copied,
        "bytes_copied": bytes_copied,
        "errors": errors,
        "files_deleted": files_deleted,
    }
    trail.log_operation(
        "copy_snapshot",
        {
            "project_root": project_root,
            "files_copied": files_copied,
            "bytes_copied": bytes_copied,
            "files_deleted": files_deleted,
        },
    )
    return result


# =============================================
