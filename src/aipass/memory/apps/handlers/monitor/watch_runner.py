# =================== AIPass ====================
# Name: watch_runner.py
# Description: Watch Mode Runner Handler
# Version: 0.2.0
# Created: 2026-08-13
# Modified: 2026-10-17
# =============================================

"""
Watch Mode Runner Handler

wait_forever() is split out so the startup path is testable without hanging.
"""

import time
from typing import Any, Dict

from aipass.prax import logger
from aipass.memory.apps.handlers.json import json_handler
from aipass.memory.apps.handlers.monitor.memory_watcher import (
    start_memory_watcher,
    stop_memory_watcher,
)
from aipass.memory.apps.handlers.monitor.detector import get_rollover_stats


def start_watching() -> Dict[str, Any]:
    """Start the file watcher over every registered branch."""
    result = start_memory_watcher()

    if not result.get("success"):
        logger.error(f"[watch_runner] Watcher failed to start: {result.get('error')}")
        json_handler.log_operation("watch_start", {"success": False, "error": result.get("error")})
        return result

    json_handler.log_operation("watch_start", {"success": True, "branches": result.get("count", 0)})
    return result


def current_stats() -> Dict[str, Any]:
    """Sample how many watched files are currently over their limits."""
    return get_rollover_stats()


def stop_watching() -> None:
    """Stop the file watcher (called from the caller's signal handler)."""
    stop_memory_watcher()
    json_handler.log_operation("watch_stop", {"success": True})


def wait_forever() -> None:
    """Block until the caller's SIGINT handler exits the process."""
    while True:
        time.sleep(1)
