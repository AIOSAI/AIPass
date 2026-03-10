# =================== AIPass ====================
# Name: error_dispatch.py
# Description: Email Error Dispatch Handler
# Version: 1.0.0
# Created: 2026-03-08
# Modified: 2026-03-08
# =============================================

"""
Email Error Dispatch Handler

Handles auto-dispatch of error reports when email delivery fails.
Independent handler - no module or display dependencies.
"""

import os
from datetime import datetime
from typing import Dict, Any, Callable, Optional

from aipass.prax import logger


def build_error_report(to_branch: str, subject: str, error_msg: str) -> Dict[str, Any]:
    """
    Build an error report email data dict for dispatch to @drone.

    Args:
        to_branch: Intended recipient that failed
        subject: Original email subject
        error_msg: Error message from delivery failure

    Returns:
        Email data dict ready for delivery, or empty dict on failure.
    """
    sender = os.environ.get("AIPASS_CALLER_BRANCH", "ai_mail")
    sender = f"@{sender.lstrip('@')}"

    error_body = (
        f"Email delivery failed.\n\n"
        f"From: {sender}\n"
        f"To: {to_branch}\n"
        f"Subject: {subject}\n"
        f"Error: {error_msg}\n\n"
        f"This error was auto-dispatched for investigation."
    )

    return {
        "from": "@ai_mail",
        "from_name": "AI_MAIL",
        "to": "@drone",
        "subject": f"[ERROR] Send failed to {to_branch}: {error_msg[:50]}",
        "message": error_body,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "auto_execute": False,
        "priority": "normal",
        "reply_to": "@dev_central",
    }


def dispatch_send_error(
    to_branch: str,
    subject: str,
    error_msg: str,
    deliver_fn: Callable,
) -> bool:
    """
    Auto-dispatch error report to @drone when email delivery fails.

    Args:
        to_branch: Intended recipient that failed
        subject: Original email subject
        error_msg: Error message from delivery failure
        deliver_fn: Callable to deliver email (deliver_email_to_branch)

    Returns:
        True if error dispatched successfully, False otherwise.
    """
    try:
        email_data = build_error_report(to_branch, subject, error_msg)
        deliver_fn("@drone", email_data)
        logger.info(f"[email] Error auto-dispatched to @drone for failed send to {to_branch}")
        return True
    except Exception as e:
        logger.warning(f"[email] Failed to dispatch send error to @drone: {e}")
        return False


def on_email_delivered(
    branch_path,
    new_count: int,
    opened_count: int,
    total: int,
    push_dashboard_fn: Optional[Callable] = None,
    update_central_fn: Optional[Callable] = None,
) -> None:
    """
    Post-delivery callback: update dashboard and central.

    Args:
        branch_path: Path to the branch that received email
        new_count: Number of new (unread) messages
        opened_count: Number of opened messages
        total: Total message count
        push_dashboard_fn: Callable for push_dashboard_update
        update_central_fn: Callable for update_central
    """
    if push_dashboard_fn:
        try:
            push_dashboard_fn(branch_path)
        except Exception as e:
            logger.warning("[error_dispatch] dashboard update failed for %s: %s", branch_path, e)
    if update_central_fn:
        try:
            update_central_fn()
        except Exception as e:
            logger.warning("[error_dispatch] central update failed: %s", e)
