# =================== AIPass ====================
# Name: registry.py
# Description: Event handler registry for startup registration
# Version: 0.3.0
# Created: 2025-12-04
# Modified: 2026-08-10
# =============================================

"""Event Handler Registry - Setup all event handlers on startup"""

from aipass.trigger.apps.handlers.json import json_handler
from aipass.trigger.apps.config import TRIGGER_ROOT, trail_logger

# Deliberately NOT prax: this wiring runs on the event path the log watchers
# read, so a prax line here would be detected, fired back as an event, and
# re-enter the handlers it just registered. The sidecar is `.jsonl`, which the
# watchers skip because they only read `*.log`.
logger = trail_logger(TRIGGER_ROOT / "logs" / "registry_handler.jsonl")


def setup_handlers():
    """Register all event handlers on startup"""
    from aipass.trigger.apps.modules.core import trigger
    from .startup import handle_startup
    from .cli import handle_cli_header_displayed
    from .plan_file import handle_plan_file_created, handle_plan_file_deleted, handle_plan_file_moved
    from .error_detected import handle_error_detected, set_send_email_callback
    from .runaway_handler import handle_runaway_log_detected, set_send_email_callback as set_runaway_email_callback
    from aipass.trigger.apps.handlers.escalation import set_send_email_callback as set_escalation_email_callback

    # Wire up email send callback for error_detected handler (avoids handler importing from modules)
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

            `upsert_key` is named EXPLICITLY, never left to **kwargs: a key that
            falls into kwargs is dropped silently — no error, no upsert, and the
            recipient's inbox keeps stacking. Callers that pass no key (medic,
            runaway) get the untouched one-message-per-send path.

            `upsert_result`, when a dict is passed, receives the delivery outcome
            ("created" | "updated") that ai_mail writes back onto email_data. The
            callback contract is `-> bool`, so this sink is the only way a caller
            can log what actually happened to the message.
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
        # Escalation digests go out through the same adapter with
        # auto_execute=False — an email to a manager, never a wake.
        set_escalation_email_callback(_send_email_adapter)
    except ImportError:
        logger.warning("ai_mail not available — error notifications won't send")
    from .warning_logged import handle_warning_logged
    from .memory_template_updated import handle_memory_template_updated

    # from .pr_status_sync import handle_pr_created, handle_pr_merged  # TDPLAN-0007: status-sync decommissioned
    from .memory_pool import handle_memory_pool_auto_processed

    trigger.on("startup", handle_startup)
    trigger.on("cli_header_displayed", handle_cli_header_displayed)
    trigger.on("plan_file_created", handle_plan_file_created)
    trigger.on("plan_file_deleted", handle_plan_file_deleted)
    trigger.on("plan_file_moved", handle_plan_file_moved)
    trigger.on("error_detected", handle_error_detected)
    trigger.on("warning_logged", handle_warning_logged)
    trigger.on("memory_template_updated", handle_memory_template_updated)
    # trigger.on("pr_created", handle_pr_created)  # TDPLAN-0007: status-sync decommissioned
    # trigger.on("pr_merged", handle_pr_merged)  # TDPLAN-0007: status-sync decommissioned
    trigger.on("memory_pool_auto_processed", handle_memory_pool_auto_processed)
    trigger.on("runaway_log_detected", handle_runaway_log_detected)

    json_handler.log_operation("handlers_registered", {"success": True})
