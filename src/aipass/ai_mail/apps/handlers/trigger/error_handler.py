# =================== AIPass ====================
# Name: error_handler.py
# Description: Error Detected Event Consumer
# Version: 1.0.0
# Created: 2026-02-02
# Modified: 2026-02-02
# =============================================

"""
Error Detected Event Consumer

Handles error_detected events fired by Trigger's log_watcher.
Delivers notifications to affected branches via AI_MAIL.

Event data from log_watcher.py:
    - branch: Target branch name (e.g., 'FLOW')
    - module: Module that logged the error
    - message: Error message text
    - log_path: Path to log file
    - error_hash: 8-char hash for deduplication
    - timestamp: When error occurred

Architecture:
    1. Trigger's log_watcher detects ERROR in branch logs
    2. log_watcher fires error_detected event
    3. This handler receives event, calls deliver_email_to_branch()
    4. Email delivered to affected branch inbox (auto_execute=True)
    5. Branch agent spawns and investigates
"""

from datetime import datetime
from pathlib import Path
from typing import Any

from aipass.prax.apps.modules.logger import system_logger as logger


def _build_notification_message(
    error_hash: str,
    module: str,
    message: str,
    timestamp: str,
    log_path: str
) -> str:
    """
    Build error notification message with investigation instructions.

    Args:
        error_hash: Unique error identifier (8-char)
        module: Module that logged the error
        message: Error message text
        timestamp: When error occurred
        log_path: Path to source log file

    Returns:
        Formatted message string with investigation instructions
    """
    return f"""Error detected - investigate and respond.

Error ID: {error_hash}
Module: {module}
Timestamp: {timestamp}
Log file: {log_path}

Error message:
{message}

---
INVESTIGATION STEPS:
1. Check the log file for context around this error
2. Identify root cause

DECISION TREE:
- SIMPLE FIX (typo, missing import, config issue):
  -> Fix it yourself, then report what you did to @dev_central
- COMPLEX/UNCLEAR (needs research, affects multiple files):
  -> Report findings only to @dev_central, recommend action, don't fix
- CRITICAL (data loss risk, security, system stability):
  -> STOP immediately, escalate to @dev_central with full context

REPORT TO @dev_central:
  ai_mail send @dev_central "ERROR {error_hash} - [STATUS]" "Findings..."

  Include: Error ID, severity (low/medium/high/critical), what you found, action taken or recommended.
"""


def handle_error_detected(
    branch: str | None = None,
    module: str | None = None,
    message: str | None = None,
    log_path: str | None = None,
    error_hash: str | None = None,
    timestamp: str | None = None,
    **kwargs: Any
) -> None:
    """
    Handle error_detected event - deliver notification to affected branch.

    Called by Trigger when log_watcher detects an ERROR in branch logs.
    Sends email to affected branch with auto_execute=True so an
    investigation agent spawns automatically.

    Args:
        branch: Target branch name (e.g., 'FLOW') - REQUIRED
        module: Module that logged the error - REQUIRED
        message: Error message text - REQUIRED
        log_path: Path to source log file
        error_hash: 8-char unique error identifier - REQUIRED
        timestamp: When error occurred (defaults to now)
        **kwargs: Additional event data (ignored)

    Returns:
        None - handlers must not return values

    Note:
        Handler follows silent failure pattern - all exceptions caught.
        NO logger imports (causes infinite recursion with trigger events).
        NO console.print() (handlers must be silent).
    """
    try:
        # Validate required fields
        if not branch or not module or not message or not error_hash:
            return

        # Import delivery handler here to avoid import-time failures
        try:
            from aipass.ai_mail.apps.handlers.email.delivery import deliver_email_to_branch
        except ImportError:
            return

        # Default timestamp to now if not provided
        if not timestamp:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Default log_path if not provided
        if not log_path:
            log_path = "unknown"

        # Convert branch name to email format (FLOW -> @flow)
        branch_email = f"@{branch.lower()}"

        # Build subject line
        subject = f"[ERROR] {module} - detected in logs"

        # Build notification message
        notification_message = _build_notification_message(
            error_hash=error_hash,
            module=module,
            message=message,
            timestamp=timestamp,
            log_path=log_path
        )

        # Build email data for delivery
        email_data = {
            'from': '@error_monitor',
            'from_name': 'Error Monitor',
            'to': branch_email,
            'subject': subject,
            'message': notification_message,
            'timestamp': timestamp,
            'auto_execute': True,
            'priority': 'normal',
            'reply_to': '@dev_central'
        }

        # Deliver via inbox.json
        deliver_email_to_branch(branch_email, email_data)

    except Exception as e:
        logger.warning("[error_handler] Failed to deliver error notification to %s: %s", branch_email, e)
