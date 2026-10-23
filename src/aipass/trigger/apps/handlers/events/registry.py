# =================== AIPass ====================
# Name: registry.py
# Description: Event handler registry for startup registration
# Version: 0.5.0
# Created: 2025-12-04
# Modified: 2026-10-22
# =============================================

"""Event Handler Registry - Setup all event handlers on startup"""

from aipass.trigger.apps.handlers.json import json_handler
from aipass.trigger.apps.config import TRIGGER_ROOT, trail_logger

# Not prax: a prax line would be watched and fired back here; watchers skip `.jsonl`.
logger = trail_logger(TRIGGER_ROOT / "logs" / "registry_handler.jsonl")


def setup_handlers():
    """Register all event handlers on startup"""
    from aipass.trigger.apps.modules.core import trigger
    from .startup import handle_startup
    from .error_detected import handle_error_detected, set_send_email_callback
    from .runaway_handler import handle_runaway_log_detected, set_send_email_callback as set_runaway_email_callback
    from aipass.trigger.apps.handlers.escalation import set_send_email_callback as set_escalation_email_callback
    from aipass.trigger.apps.handlers.ci.outbound import set_send_email_callback as set_ci_email_callback
    from .ci_red import handle_ci_red

    try:
        from aipass.ai_mail.apps.modules.email_send import deliver_email_to_branch
        from datetime import datetime

        def _send_email_adapter(
            to_branch,
            subject,
            message,
            auto_execute=False,
            reply_to="@trigger",
            from_branch="@trigger",
            upsert_key=None,
            upsert_result=None,
            **kwargs,
        ):
            """Adapt error_detected handler's call signature to deliver_email_to_branch.

            `upsert_key` stays explicit (in **kwargs it drops silently); `upsert_result` returns the upsert action.
            """
            email_data = {
                "from": from_branch,
                "from_name": "TRIGGER",
                "to": to_branch,
                "subject": subject,
                "message": message,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
            if auto_execute:
                email_data["message"] = f"⚡ DISPATCH TASK - READ THIS FIRST ⚡\n\n{message}"
            success, _ = deliver_email_to_branch(to_branch, email_data, upsert_key=upsert_key)
            if upsert_result is not None:
                upsert_result["upsert_action"] = email_data.get("upsert_action")
            return success

        set_send_email_callback(_send_email_adapter)
        set_runaway_email_callback(_send_email_adapter)
        # Escalation digests keep auto_execute=False: an email to a manager, never a wake.
        set_escalation_email_callback(_send_email_adapter)
        set_ci_email_callback(_send_email_adapter)
    # OSError too: an uncured peer's import guard raises FileNotFoundError.
    except (ImportError, OSError):
        logger.warning("ai_mail not available — error notifications won't send")
    from .warning_logged import handle_warning_logged
    from .memory_template_updated import handle_memory_template_updated
    from .memory_pool import handle_memory_pool_auto_processed

    trigger.on("startup", handle_startup)
    # Unwired on purpose: cli_header_displayed, plan_file_* and pr_* (handlers archived).
    trigger.on("error_detected", handle_error_detected)
    trigger.on("warning_logged", handle_warning_logged)
    trigger.on("memory_template_updated", handle_memory_template_updated)
    trigger.on("memory_pool_auto_processed", handle_memory_pool_auto_processed)
    trigger.on("runaway_log_detected", handle_runaway_log_detected)
    trigger.on("ci_red", handle_ci_red)

    json_handler.log_operation("handlers_registered", {"success": True})
