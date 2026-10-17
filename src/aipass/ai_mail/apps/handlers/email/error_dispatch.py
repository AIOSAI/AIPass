# =================== AIPass ====================
# Name: error_dispatch.py
# Description: Email Error Dispatch Handler
# Version: 1.0.0
# Created: 2026-03-08
# Modified: 2026-10-17
# =============================================

"""
Email Error Dispatch Handler
"""

import os
from datetime import datetime
from typing import Dict, Any, Callable, Optional

from aipass.prax import logger
from aipass.ai_mail.apps.handlers.json import json_handler


def build_error_report(to_branch: str, subject: str, error_msg: str) -> Dict[str, Any]:
    """Build an error report email data dict for dispatch to @drone."""
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
        # reply.py routes to `reply_to or from`: an answer must reach the mailbox that raised it.
        "reply_to": "@ai_mail",
    }


def dispatch_send_error(
    to_branch: str,
    subject: str,
    error_msg: str,
    deliver_fn: Callable,
) -> bool:
    """Auto-dispatch error report to @drone when email delivery fails."""
    json_handler.log_operation("dispatch_send_error", {"to_branch": to_branch, "subject": subject})

    try:
        email_data = build_error_report(to_branch, subject, error_msg)
        deliver_fn("@drone", email_data)
        logger.info(f"[email] Error auto-dispatched to @drone for failed send to {to_branch}")
        return True
    except Exception as e:
        logger.warning(f"[email] Failed to dispatch send error to @drone: {e}")
        return False


def on_email_delivered(update_central_fn: Optional[Callable] = None) -> None:
    """Post-delivery callback: update central.

    update_central_fn takes no arguments; it rescans every branch inbox itself.
    """
    if update_central_fn:
        try:
            update_central_fn()
        except Exception as e:
            logger.warning("[error_dispatch] central update failed: %s", e)
