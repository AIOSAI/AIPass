# =================== AIPass ====================
# Name: registry.py
# Description: Event handler registry for startup registration
# Version: 0.1.0
# Created: 2025-12-04
# Modified: 2025-12-04
# =============================================

"""Event Handler Registry - Setup all event handlers on startup"""

from aipass.trigger.apps.handlers.json import json_handler
from aipass.trigger.apps.config import TRIGGER_ROOT

try:
    from aipass.prax import append_jsonl as _append_jsonl
except Exception:
    _append_jsonl = None

_HANDLER_LOG = TRIGGER_ROOT / "logs" / "registry_handler.jsonl"


def _log_warning(message: str) -> None:
    """Log warning to file (recursion-safe prax path)."""
    if _append_jsonl is None:
        return
    try:
        _append_jsonl(_HANDLER_LOG, {"level": "WARNING", "msg": message})
    except Exception:
        pass  # seedgo:bypass meta-logging


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
            to_branch, subject, message, auto_execute=False, reply_to="@trigger", from_branch="@trigger", **kwargs
        ):
            """Adapt error_detected handler's call signature to deliver_email_to_branch."""
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
            success, _ = deliver_email_to_branch(to_branch, email_data)
            return success

        set_send_email_callback(_send_email_adapter)
        set_runaway_email_callback(_send_email_adapter)
        # Escalation digests go out through the same adapter with
        # auto_execute=False — an email to a manager, never a wake.
        set_escalation_email_callback(_send_email_adapter)
    except ImportError:
        _log_warning("ai_mail not available — error notifications won't send")
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
