# =================== AIPass ====================
# Name: memory_pool.py
# Description: Memory pool auto-process event handler — observability for pool processing
# Version: 1.3.1
# Created: 2026-06-06
# Modified: 2026-11-22
# =============================================

"""
Memory Pool Auto-Processed Event Handler
status vocabulary: ok/skipped/failed/unknown; an absent section derives to "unknown", never "ok".
branch must be a registered citizen, never "__global__": error_detected's gate drops it.
"""

from typing import Any

from aipass.prax import logger
from aipass.trigger.apps.handlers.error_reporter import report_error
from aipass.trigger.apps.handlers.json import json_handler


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

    report_error(
        error_type="MemoryPoolAutoProcessError",
        message=error_msg,
        component=(branch or "memory").lower(),
        fire_event=kwargs.get("fire_event") is not None,
    )
