# =================== AIPass ====================
# Name: warning_logged.py
# Description: Warning logged event handler — feeds the escalation digest lane
# Version: 2.0.0
# Created: 2026-01-31
# Modified: 2026-10-17
# =============================================

"""
Warning Logged Event Handler
Warnings have no dispatch path, so repeats are counted by signature and escalated past a threshold."""

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
    """Handle warning_logged event."""
    _ = (error_hash, timestamp, level, kwargs)

    if branch and message:
        escalation.record_warning(
            branch=branch,
            module=module_name or "unknown",
            message=message,
            log_file=log_file or "",
            raw_line=raw_line or "",
        )

    json_handler.log_operation("warning_logged_event", {"success": True})
