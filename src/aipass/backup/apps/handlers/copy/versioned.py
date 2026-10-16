# =================== AIPass ====================
# Name: versioned.py
# Description: Versioned copy — per-file baseline + diff engine
# Version: 2.1.0
# Created: 2026-04-16
# Modified: 2026-10-16
# =============================================

"""Versioned copy handler — per-file baseline + unified diff engine.

Each file gets a file-folder in the persistent store containing:
- <name> (current version, copy2 preserves mtime)
- <stem>-baseline-<YYYY-MM-DD>.<ext> (first-run full copy, never overwritten)
- <name>_diffs/<name>_v<YYYY-MM-DD_HH-MM-SS>.diff (old version's mtime timestamp)
"""

import datetime
import os
import shutil
import stat
from pathlib import Path

from aipass.prax import logger

from ..diff.generator import generate_diff_content, should_create_diff
from ..audit import trail
from ..path.builder import build_versioned_file_path
from ..state.stop_flag import stop_requested


def _make_baseline_name(target: Path) -> str:
    """Build the baseline filename: <stem>-baseline-<YYYY-MM-DD>.<ext>."""
    date_str = datetime.datetime.now().strftime("%Y-%m-%d")
    parts = target.name.rsplit(".", 1)
    if len(parts) == 2:
        return f"{parts[0]}-baseline-{date_str}.{parts[1]}"
    return f"{target.name}-baseline-{date_str}"


def _ensure_writable(path: Path) -> None:
    """Best-effort chmod to make a path writable."""
    try:
        path.chmod(stat.S_IWRITE | stat.S_IREAD)
    except OSError as e:
        logger.info(f"[versioned] Could not chmod {path}: {e}")


def _copy_new_file(source: Path, target: Path) -> bool:
    """Handle a new file: create baseline + current."""
    target.parent.mkdir(parents=True, exist_ok=True)

    # Current copy (mtime preserved via copy2)
    shutil.copy2(str(source), str(target))

    # Baseline copy (never overwritten after creation)
    baseline_name = _make_baseline_name(target)
    baseline_path = target.parent / baseline_name
    if not baseline_path.exists():
        shutil.copy2(str(source), str(baseline_path))

    return True


def _copy_changed_file(source: Path, target: Path) -> bool:
    """Handle a changed file: diff old current, then overwrite current."""
    # Generate diff before overwriting
    if should_create_diff(source):
        old_mtime = target.stat().st_mtime
        ts = datetime.datetime.fromtimestamp(old_mtime).strftime("%Y-%m-%d_%H-%M-%S")
        diff_dir = target.parent / f"{target.name}_diffs"
        diff_dir.mkdir(parents=True, exist_ok=True)
        diff_name = f"{target.name}_v{ts}.diff"
        diff_path = diff_dir / diff_name

        diff_content = generate_diff_content(target, source)
        if diff_content:
            diff_path.write_text(diff_content, encoding="utf-8")

    # Overwrite current with new version
    _ensure_writable(target)
    shutil.copy2(str(source), str(target))
    return True


def _copy_one(source: Path, target: Path, abs_path: str) -> int:
    """Copy one file into its file-folder; bytes copied, or -1 when unchanged.

    New: baseline + current. Changed (mtime differs): diff old->new, overwrite
    current. Unchanged: nothing.
    """
    if not target.exists():
        _copy_new_file(source, target)
        return os.path.getsize(abs_path)
    if source.stat().st_mtime != target.stat().st_mtime:
        _copy_changed_file(source, target)
        return os.path.getsize(abs_path)
    return -1


def copy_versioned(
    files: list[tuple[str, str]],
    project_root: str,
    on_progress=None,
    on_file=None,
) -> dict:
    """Copy files into the persistent versioned store.

    For each file:
    - New: create baseline + current (two copies)
    - Changed (mtime differs): diff old->new, overwrite current
    - Unchanged: skip

    The stop flag (handlers/state/stop_flag.py) is read before each file: a
    stop lets the file in flight finish and starts no other.

    Args:
        files: List of (absolute_path, relative_path) tuples.
        project_root: Project root (used to build store paths).
        on_progress: Optional no-argument callback after each file.
        on_file: Optional callback after each file with (relative_path,
            bytes_copied, ok); the running file's writer.

    Returns:
        Dict with files_copied, files_unchanged, bytes_copied, errors, and
        files_done (files gone through) and stopped (True when the stop flag
        ended the loop early).
    """
    files_copied = 0
    files_unchanged = 0
    bytes_copied = 0
    files_done = 0
    stopped = False
    errors: list[str] = []

    for abs_path, rel_path in files:
        if stop_requested():
            stopped = True
            break
        source = Path(abs_path)
        target = Path(build_versioned_file_path(project_root, rel_path))
        copied = -1
        ok = True

        if len(str(target)) > 260:
            # Long-path guard
            logger.warning(f"Path too long (>260), skipping: {rel_path}")
            errors.append(f"{rel_path}: path too long (>260 chars)")
            ok = False
        else:
            try:
                copied = _copy_one(source, target, abs_path)
            except OSError as e:
                logger.warning(f"Failed to process {rel_path}: {e}")
                errors.append(f"{rel_path}: {e}")
                ok = False
        if copied >= 0:
            bytes_copied += copied
            files_copied += 1
        elif ok:
            files_unchanged += 1
        files_done += 1

        if on_progress:
            on_progress()
        if on_file:
            on_file(rel_path, max(copied, 0), ok)

    result = {
        "files_copied": files_copied,
        "files_unchanged": files_unchanged,
        "bytes_copied": bytes_copied,
        "errors": errors,
        "files_done": files_done,
        "stopped": stopped,
    }
    trail.log_operation(
        "copy_versioned",
        {
            "project_root": project_root,
            "files_copied": files_copied,
            "files_unchanged": files_unchanged,
            "stopped": stopped,
        },
    )
    return result


# =============================================
