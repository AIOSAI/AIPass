# =================== AIPass ====================
# Name: trail.py
# Description: Backup's own operation audit trail — JSONL append to logs/operations.jsonl
# Version: 1.0.0
# Created: 2026-09-03
# Modified: 2026-10-17
# =============================================

"""Backup's operation audit trail."""

# Not the fleet json log, and never in the byte-identical json shim: this record shape is backup's own.

import os
from datetime import datetime, timezone
from pathlib import Path

from aipass.prax import append_jsonl, logger

from ..path.module_paths import branch_root

BRANCH_NAME = "backup"
LOG_FILENAME = "operations.jsonl"


def log_path() -> Path:
    """The audit stream's path, computed on every call."""
    # Never captured at import: a test that sets AIPASS_TEST_LOG_DIR later must still redirect.
    test_dir = os.environ.get("AIPASS_TEST_LOG_DIR")
    if test_dir:
        return Path(test_dir) / BRANCH_NAME / "logs" / LOG_FILENAME
    return branch_root(__file__, 3) / "logs" / LOG_FILENAME


def log_operation(operation: str, data: dict) -> None:
    """Record an operation entry to the backup audit stream."""
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "operation": operation,
        **data,
    }
    try:
        append_jsonl(log_path(), entry)
    except OSError as e:
        logger.warning(f"Failed to write operation log: {e}")
