# =================== AIPass ====================
# Name: warning_logged.py
# Description: Warning logged event handler — feeds the escalation digest lane
# Version: 2.0.0
# Created: 2026-01-31
# Modified: 2026-08-08
# =============================================

"""
Warning Logged Event Handler

Handles warning_logged events fired by Trigger's log watchers.

A single warning is still informational — nobody is notified about it. But a
warning signature that REPEATS is the one failure mode nothing in medic ever
covered: warnings have no dispatch path at all, so a loop of them was
invisible to humans forever (DPLAN-0283). This handler feeds every warning
into the escalation lane, which counts by signature and emails the operator
only once a signature crosses its threshold.

Event data expected:
    - branch: Branch where warning occurred
    - message: Warning message text
    - error_hash: Unique hash for deduplication
    - timestamp: When the warning occurred
    - log_file: Path to log file
    - module_name: Module that logged the warning
    - level: Log level (always 'warning' for this handler)
    - raw_line: Full log line, carried into the digest as a sample
"""

from typing import Any
from aipass.trigger.apps.handlers.json import json_handler
from aipass.trigger.apps.handlers import escalation


def handle_warning_logged(
    branch: str | None = None,
    message: str | None = None,
    error_hash: str | None = None,
    timestamp: str | None = None,
    log_file: str | None = None,
    module_name: str | None = None,
    level: str | None = None,
    raw_line: str | None = None,
    **kwargs: Any,
) -> None:
    """
    Handle warning_logged event.

    One warning notifies nobody. A REPEATING warning signature is escalated:
    the occurrence is counted, and when the signature crosses its threshold
    inside the window the escalation lane emails the operator once.

    Args:
        branch: Branch where warning occurred
        message: Warning message text
        error_hash: Unique hash for deduplication
        timestamp: When warning occurred
        log_file: Path to source log file
        module_name: Module that logged the warning
        level: Log level (for reference)
        raw_line: Full log line, kept as a digest sample
        **kwargs: Additional event data (ignored)

    Returns:
        None - handlers must not return values
    """
    # Suppress unused variable warnings - all params are part of event contract
    _ = (error_hash, timestamp, level, kwargs)

    if branch and message:
        # Silent-failure contract: record() never raises.
        escalation.record_warning(
            branch=branch,
            module=module_name or "unknown",
            message=message,
            log_file=log_file or "",
            raw_line=raw_line or "",
        )

    json_handler.log_operation("warning_logged_event", {"success": True})
