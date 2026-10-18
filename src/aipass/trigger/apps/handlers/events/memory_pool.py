# =================== AIPass ====================
# Name: memory_pool.py
# Description: Memory pool auto-process event handler — observability for pool processing
# Version: 1.1.0
# Created: 2026-06-06
# Modified: 2026-10-17
# =============================================

"""
Memory Pool Auto-Processed Event Handler
status vocabulary: ok/skipped/failed/unknown; an absent section derives to "unknown", never "ok".
branch must be a registered citizen, never "__global__": error_detected's gate drops it.
"""

from typing import Any

from aipass.trigger.apps.config import TRIGGER_ROOT, trail_logger
from aipass.trigger.apps.handlers.json import json_handler

# Not prax: watchers read *.log and would fire this line back here; the .jsonl sidecar is skipped.
logger = trail_logger(TRIGGER_ROOT / "logs" / "memory_pool_handler.jsonl")


def handle_memory_pool_auto_processed(
    success: bool | None = None,
    branch: str | None = None,
    pool: dict | None = None,
    rollover: dict | None = None,
    error: str | None = None,
    **kwargs: Any,
) -> None:
    """Handle memory_pool_auto_processed event."""
    pool = pool or {}
    rollover = rollover or {}
    files_processed = pool.get("files_processed", 0)
    total_chunks = pool.get("total_chunks", 0)

    if success:
        json_handler.log_operation(
            "memory_pool_auto_processed",
            {
                "success": True,
                "files_processed": files_processed,
                "total_chunks": total_chunks,
                "pool_status": pool.get("status", "unknown"),
                "rollover_status": rollover.get("status", "unknown"),
            },
        )
        return

    error_msg = error or "memory pool auto-process failed (no detail)"
    logger.warning(f"auto-process failure: {error_msg}")

    json_handler.log_operation(
        "memory_pool_auto_processed",
        {
            "success": False,
            "error": error_msg,
        },
    )

    fire_event = kwargs.get("fire_event")
    if fire_event is not None:
        fire_event(
            "error_detected",
            branch=branch or "memory",
            error_type="MemoryPoolAutoProcessError",
            message=error_msg,
            source_file="auto_process.py",
        )
