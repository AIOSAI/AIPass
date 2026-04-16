# =================== AIPass ====================
# Name: warning_logged.py
# Description: Warning logged event handler for monitoring hooks
# Version: 1.0.0
# Created: 2026-01-31
# Modified: 2026-01-31
# =============================================

"""
Warning Logged Event Handler

Handles warning_logged events fired by Trigger log watcher.
Logs warning for monitoring but does not send notifications
(warnings are informational, not actionable by default).

Event data expected:
    - branch: Branch where warning occurred
    - message: Warning message text
    - error_hash: Unique hash for deduplication
    - timestamp: When the warning occurred
    - log_file: Path to log file
    - module_name: Module that logged the warning
    - level: Log level (always 'warning' for this handler)
"""

from typing import Any
from aipass.trigger.apps.handlers.json import json_handler


def handle_warning_logged(
    branch: str | None = None,
    message: str | None = None,
    error_hash: str | None = None,
    timestamp: str | None = None,
    log_file: str | None = None,
    module_name: str | None = None,
    level: str | None = None,
    **kwargs: Any,
) -> None:
    """
    Handle warning_logged event.

    Warnings are logged for monitoring but do not trigger notifications.
    This handler exists as a hook point for future warning aggregation.

    Args:
        branch: Branch where warning occurred
        message: Warning message text
        error_hash: Unique hash for deduplication
        timestamp: When warning occurred
        log_file: Path to source log file
        module_name: Module that logged the warning
        level: Log level (for reference)
        **kwargs: Additional event data (ignored)

    Returns:
        None - handlers must not return values
    """
    # Warnings are informational - no action needed by default
    # This handler exists as a hook point for:
    # - Future warning aggregation
    # - Warning threshold alerts (e.g., 10+ warnings in 5 min)
    # - Warning pattern detection
    #
    # Suppress unused variable warnings - all params are part of event contract
    _ = (branch, message, error_hash, timestamp, log_file, module_name, level, kwargs)
    json_handler.log_operation("warning_logged_event", {"success": True})
