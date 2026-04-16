# =================== AIPass ====================
# Name: error_reporter.py
# Description: Error reporting handler for registry and source fix email
# Version: 1.0.0
# Created: 2026-03-08
# Modified: 2026-03-08
# =============================================

"""
Error Reporting Handler

Contains the core logic for reporting errors to the registry and
dispatching error_detected events. Also handles source fix email
pipeline for suppressed errors.

Purpose:
    Implementation logic for error reporting, separated from CLI/display
    layer to satisfy thin-module standard.
"""

from aipass.prax import logger

# logger imported from aipass.prax

from aipass.trigger.apps.handlers.error_registry import (
    report as _registry_report,
)
from aipass.trigger.apps.handlers.json import json_handler


def send_source_fix_email(entry: dict) -> bool:
    """Send recommendation email to source branch about fixing log level.

    When an error is suppressed, the source branch gets notified that
    their log level may be wrong. This closes the loop:
    error -> investigate -> suppress -> fix source -> error stops

    Args:
        entry: Error registry entry dict

    Returns:
        True if email sent successfully
    """
    try:
        from aipass.ai_mail.apps.modules.email import deliver_email_to_branch
    except ImportError:
        logger.info("[ERRORS] Could not import deliver_email_to_branch - ai_mail not available")
        return False

    try:
        component = entry.get("component", "").lower()
        if not component or component == "unknown":
            return False

        recipient = f"@{component}"
        fingerprint = entry.get("fingerprint", "")[:12]
        error_type = entry.get("error_type", "?")
        message = entry.get("message", "?")[:200]
        suppress_reason = entry.get("suppress_reason", "No reason")
        log_path = entry.get("log_path", "unknown")
        count = entry.get("count", 0)

        subject = f"[LOG FIX] {error_type} classified as non-critical"

        body = f"""Your code is generating an error that has been classified as non-critical.

Error fingerprint: {fingerprint}
Error type: {error_type}
Occurrences: {count}
Log file: {log_path}
Suppress reason: {suppress_reason}

Error message:
{message}

RECOMMENDATION:
This error is currently logged as ERROR but appears to be non-critical based on
investigation. Consider one of:
1. Change the log level from ERROR to WARNING or INFO
2. Add proper error handling to prevent this from being logged
3. If this is actually critical, reply to @trigger explaining why

This will prevent unnecessary error dispatch for this issue.

---
Automated recommendation from Medic v2 Error Registry.
Reply to @trigger with your fix status."""

        from datetime import datetime

        email_data = {
            "from": "@trigger",
            "from_name": "TRIGGER",
            "to": recipient,
            "subject": subject,
            "message": body,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        success, _ = deliver_email_to_branch(recipient, email_data)

        if success:
            logger.info(f"[ERRORS] Source fix email sent to {recipient} for {fingerprint}")
        return success
    except Exception as exc:
        logger.info(f"[ERRORS] Failed to send source fix email: {exc}")
        return False


def report_error(
    error_type: str, message: str, component: str, log_path: str = "", severity: str = "medium", fire_event: bool = True
) -> dict:
    """Report an error to the registry and optionally fire error_detected event.

    Public API for cross-branch push reporting. Drone and other branches
    call this instead of importing from handlers directly.

    Pipeline: report() -> registry stores -> fire event -> handler checks
    circuit breaker + rate limiting -> dispatch email if allowed.

    Args:
        error_type: Error class name (e.g., 'ImportError', 'TimeoutError')
        message: Original error message text
        component: Branch that generated the error (e.g., 'FLOW', 'API')
        log_path: Path to source log file (optional)
        severity: Error severity - low, medium, high, critical (default: medium)
        fire_event: Whether to fire error_detected event (default: True).
            Set False for silent registration without dispatch.

    Returns:
        Dict with error entry data + 'is_new' bool + 'dispatched' bool.
    """
    result = _registry_report(
        error_type=error_type,
        message=message,
        component=component,
        log_path=log_path,
        severity=severity,
    )
    result["dispatched"] = False

    # Fire event on every call — let the error_detected handler decide
    # when to dispatch via circuit breaker, backoff, and rate limiting.
    error_count = result.get("count", 1)
    if not fire_event:
        return result

    try:
        from aipass.trigger.apps.modules.core import trigger as _trigger_bus

        _trigger_bus.fire(
            "error_detected",
            branch=component,
            module=error_type,
            message=message,
            log_path=log_path,
            error_hash=result.get("id", ""),
            timestamp=result.get("last_seen", ""),
            fingerprint=result.get("fingerprint", ""),
            registry_id=result.get("id", ""),
            first_seen=result.get("first_seen", ""),
            last_seen=result.get("last_seen", ""),
            count=error_count,
        )
        result["dispatched"] = True
    except Exception as exc:
        logger.warning("Failed to fire error_detected event for '%s': %s", component, exc)

    json_handler.log_operation("error_reported", {"branch": component, "error_type": error_type})
    return result
