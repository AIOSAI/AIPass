# =================== AIPass ====================
# Name: watch_runner.py
# Description: Watch Mode Runner Handler
# Version: 0.2.0
# Created: 2026-08-13
# Modified: 2026-08-13
# =============================================

"""
Watch Mode Runner Handler

Lifecycle for the auto-rollover watcher session: start, sample, block, stop.

Purpose:
    Implementation half of the `watch` command. Wraps the two monitor handlers
    the session spans -- memory_watcher (the observer) and detector (the
    over-cap count) -- so the module stays thin CLI routing.

Design:
    - Returns data, never prints: display belongs to the module (cli standard)
    - wait_forever() is isolated so the startup path can be tested without
      hanging a test run
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
    """
    Start the file watcher over every registered branch.

    Returns:
        Dict with success, count (branch directories watched), and error on failure.
    """
    result = start_memory_watcher()

    if not result.get("success"):
        logger.error(f"[watch_runner] Watcher failed to start: {result.get('error')}")
        json_handler.log_operation("watch_start", {"success": False, "error": result.get("error")})
        return result

    json_handler.log_operation("watch_start", {"success": True, "branches": result.get("count", 0)})
    return result


def current_stats() -> Dict[str, Any]:
    """
    Sample how many watched files are currently over their limits.

    Returns:
        Dict with success, files_checked, files_ready.
    """
    return get_rollover_stats()


def stop_watching() -> None:
    """Stop the file watcher (called from the caller's signal handler)."""
    stop_memory_watcher()
    json_handler.log_operation("watch_stop", {"success": True})


def wait_forever() -> None:
    """Block until the caller's SIGINT handler exits the process."""
    while True:
        time.sleep(1)
