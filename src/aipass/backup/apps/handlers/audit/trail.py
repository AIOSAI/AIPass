# =================== AIPass ====================
# Name: trail.py
# Description: Backup's own operation audit trail — JSONL append to logs/operations.jsonl
# Version: 1.0.0
# Created: 2026-09-03
# Modified: 2026-09-03
# =============================================

"""Backup's operation audit trail.

This is NOT the fleet's per-module json log. The fleet's json service
(``aipass.prax``, DPLAN-0325) writes typed ``<module>_log.json`` documents
inside a branch's ``<branch>_json`` directory, capped and rotated. Backup keeps
something different and older: one append-only JSONL stream at
``logs/operations.jsonl``, one line per operation, the operation's own fields
flattened into the record.

It is backup's audit trail, so backup owns it. The shim
(``apps/handlers/json/json_handler.py``) is byte-identical in every branch and
nothing branch-specific goes into it — the record shape below is exactly that.

Built on ``aipass.prax.append_jsonl``, which rotates the stream and serialises
with ``default=str``, so a Path or a datetime in a payload records as its text
rather than killing the call.
"""

import os
from datetime import datetime, timezone
from pathlib import Path

from aipass.prax import append_jsonl, logger

from ..path.module_paths import branch_root

BRANCH_NAME = "backup"
LOG_FILENAME = "operations.jsonl"


def log_path() -> Path:
    """The audit stream's path, computed on every call.

    Never captured at import, for the same reason the json service recomputes
    its json dir: a test that sets ``AIPASS_TEST_LOG_DIR`` after this module is
    imported must still be redirected. An EMPTY value is absence, not a
    redirect.

    Returns:
        Path to the JSONL stream this process should append to.
    """
    test_dir = os.environ.get("AIPASS_TEST_LOG_DIR")
    if test_dir:
        return Path(test_dir) / BRANCH_NAME / "logs" / LOG_FILENAME
    return branch_root(__file__, 3) / "logs" / LOG_FILENAME


def log_operation(operation: str, data: dict) -> None:
    """Record an operation entry to the backup audit stream.

    Args:
        operation: What happened, e.g. ``"snapshot_complete"``.
        data: The operation's own fields, flattened into the record beside
            ``timestamp`` and ``operation``.

    Note:
        Best-effort by design: this is a record of work, not the work. A
        failed append warns and returns; it never takes a backup down with it.
    """
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "operation": operation,
        **data,
    }
    try:
        append_jsonl(log_path(), entry)
    except OSError as e:
        logger.warning(f"Failed to write operation log: {e}")


# =============================================
