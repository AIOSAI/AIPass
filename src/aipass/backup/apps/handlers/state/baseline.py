# =================== AIPass ====================
# Name: baseline.py
# Description: The last good run's measured totals, the base the growth ceiling compares against
# Version: 1.0.0
# Created: 2026-11-26
# Modified: 2026-11-26
# =============================================

"""Run baseline: files and bytes of the last snapshot that completed, in <project>/.backup/last_good_run.json."""

import os
from datetime import datetime, timezone

from aipass.prax import logger

from ..audit import trail
from ..json import json_handler
from ..path import builder


def load_baseline(project_root: str) -> dict | None:
    """Answer {"files", "bytes", "recorded"} of the last good run, or None when there is none to trust."""
    path = builder.build_baseline_path(project_root)
    if not path.exists():
        logger.info(f"[backup] No run baseline for {project_root}: the growth ceiling waits, the walls hold")
        return None
    data = json_handler.read_json(path)
    valid = isinstance(data, dict) and all(isinstance(data.get(k), int) for k in ("files", "bytes"))
    if not valid:
        # Unreadable state is no reason to refuse a backup: the absolute walls still bound the run.
        logger.warning(f"[backup] Run baseline unreadable, growth ceiling skipped, walls hold: {path}")
        return None
    return data


def save_baseline(project_root: str, files: list[tuple[str, str]]) -> dict:
    """Measure a completed run's file set and record it as the baseline; raises WriteFailed or OSError."""
    total = 0
    for abs_path, _rel in files:
        try:
            total += os.path.getsize(abs_path)
        except FileNotFoundError as e:
            logger.warning(f"[backup] Baseline counts no bytes for a file gone since its copy: {e}")
            continue
    record = {"files": len(files), "bytes": total, "recorded": datetime.now(timezone.utc).isoformat()}
    path = builder.build_baseline_path(project_root)
    if not json_handler.write_json(path, record):
        raise json_handler.WriteFailed(f"Run baseline write failed: {path}")
    trail.log_operation("save_baseline", {"project_root": project_root, "files": len(files), "bytes": total})
    return record
