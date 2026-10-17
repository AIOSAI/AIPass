# =================== AIPass ====================
# Name: snapshot.py
# Description: Snapshot copy strategy — mirror destination tree with cleanup
# Version: 3.2.1
# Created: 2026-04-16
# Modified: 2026-10-16
# =============================================

"""Snapshot copy handler — mirror destination tree with cleanup."""

import os
import shutil
import stat
from pathlib import Path

from aipass.prax import logger

from ..cleanup.mirror import cleanup_deleted_files
from ..path.builder import exceeds_max_path
from ..audit import trail
from ..report.result import BackupResult
from ..state.stop_flag import stop_requested


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

    # Long-path guard: Windows' MAX_PATH only (path/builder.py)
    if exceeds_max_path(target):
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


def _run_mirror_cleanup(dest_path: Path, project_root: str) -> int:
    """Run mirror-delete cleanup on an existing snapshot destination."""
    cleanup_result = BackupResult(mode="snapshot", project_root=project_root)
    cleanup_deleted_files(
        dest_path,
        Path(project_root),
        cleanup_result,
    )
    return cleanup_result.files_deleted


def copy_snapshot(
    files: list[tuple[str, str]],
    dest: str,
    project_root: str,
    on_progress=None,
    on_file=None,
) -> dict:
    """Copy files into a snapshot destination with mirror-delete.

    The stop flag (handlers/state/stop_flag.py) is read before each file: a
    stop lets the file in flight finish and starts no other.

    Args:
        files: List of (absolute_path, relative_path) tuples.
        dest: Absolute destination directory path.
        project_root: Project root for cleanup source reference.
        on_progress: Optional no-argument callback after each file.
        on_file: Optional callback after each file with (relative_path,
            bytes_copied, ok); the running file's writer.

    Returns:
        Dict with files_copied, bytes_copied, errors, files_deleted, and
        files_done (files gone through) and stopped (True when the stop flag
        ended the loop early).
    """
    dest_path = Path(os.path.realpath(dest))

    # Mirror-delete: remove snapshot files whose source is gone
    files_deleted = 0
    if dest_path.exists():
        files_deleted = _run_mirror_cleanup(dest_path, project_root)

    dest_path.mkdir(parents=True, exist_ok=True)

    files_copied = 0
    bytes_copied = 0
    files_done = 0
    stopped = False
    errors: list[str] = []

    for abs_path, rel_path in files:
        if stop_requested():
            stopped = True
            break
        result_bytes = -1
        failures_before = len(errors)
        try:
            result_bytes = _copy_single_file(abs_path, rel_path, dest_path, errors)
            if result_bytes >= 0:
                bytes_copied += result_bytes
                files_copied += 1
        except OSError as e:
            logger.warning(f"Failed to copy {rel_path}: {e}")
            errors.append(f"{rel_path}: {e}")
        ok = len(errors) == failures_before
        files_done += 1

        if on_progress:
            on_progress()
        if on_file:
            on_file(rel_path, max(result_bytes, 0), ok)

    result = {
        "files_copied": files_copied,
        "bytes_copied": bytes_copied,
        "errors": errors,
        "files_deleted": files_deleted,
        "files_done": files_done,
        "stopped": stopped,
    }
    trail.log_operation(
        "copy_snapshot",
        {
            "project_root": project_root,
            "files_copied": files_copied,
            "bytes_copied": bytes_copied,
            "files_deleted": files_deleted,
            "stopped": stopped,
        },
    )
    return result


# =============================================
