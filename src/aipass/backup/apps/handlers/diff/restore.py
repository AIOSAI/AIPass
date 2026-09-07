# =================== AIPass ====================
# Name: restore.py
# Description: Version restore — reconstruct files from baseline + diffs
# Version: 1.0.0
# Created: 2026-06-12
# Modified: 2026-06-12
# =============================================

"""Restore handler — reconstruct file versions from baseline + diffs."""

import re
import shutil
from pathlib import Path

from aipass.prax import logger

from ..audit import trail


def list_versions(file_folder: Path) -> list[dict]:
    """List all versions available for a file-folder.

    Returns list of dicts with 'timestamp', 'path', 'type' (baseline/diff/current).
    """
    versions = []
    if not file_folder.is_dir():
        return versions

    name = file_folder.name

    # Find baseline
    for f in file_folder.iterdir():
        if f.is_file() and "-baseline-" in f.name:
            versions.append({"timestamp": "baseline", "path": f, "type": "baseline"})

    # Find current
    current = file_folder / name
    if current.is_file():
        versions.append({"timestamp": "current", "path": current, "type": "current"})

    # Find diffs
    diff_dir = file_folder / f"{name}_diffs"
    if diff_dir.is_dir():
        for diff_file in sorted(diff_dir.glob(f"{name}_v*.diff")):
            ts_match = re.search(r"_v(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})\.diff$", diff_file.name)
            if ts_match:
                versions.append(
                    {
                        "timestamp": ts_match.group(1),
                        "path": diff_file,
                        "type": "diff",
                    }
                )

    trail.log_operation("list_versions", {"folder": str(file_folder), "count": len(versions)})
    return versions


def restore_file(file_folder: Path, output_path: Path) -> bool:
    """Restore the current version of a file from the versioned store.

    Args:
        file_folder: The file-folder in the versioned store.
        output_path: Where to write the restored file.

    Returns:
        True if restoration succeeded.
    """
    name = file_folder.name
    current = file_folder / name

    if not current.is_file():
        logger.warning(f"[restore] No current version found in {file_folder}")
        return False

    output_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(current), str(output_path))
    trail.log_operation("restore_file", {"source": str(current), "output": str(output_path)})
    logger.info(f"[restore] Restored {name} to {output_path}")
    return True


# =============================================
