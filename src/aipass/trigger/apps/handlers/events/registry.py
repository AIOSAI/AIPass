# =================== AIPass ====================
# Name: registry.py
# Description: Event handler registry for startup registration
# Version: 0.1.0
# Created: 2025-12-04
# Modified: 2025-12-04
# =============================================

"""Event Handler Registry - Setup all event handlers on startup"""

from datetime import datetime, timezone

from aipass.trigger.apps.handlers.json import json_handler
from aipass.trigger.apps.config import TRIGGER_ROOT

_HANDLER_LOG = TRIGGER_ROOT / "logs" / "registry_handler.log"


def _log_warning(message: str) -> None:
    """Log warning to file (event handlers cannot import Prax logger — causes recursion)."""
    try:
        _HANDLER_LOG.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        with open(_HANDLER_LOG, "a", encoding="utf-8") as f:
            f.write(f"{ts} | WARNING | {message}\n")
    except Exception:
        pass  # Meta-logging: cannot log a failure to log


def setup_handlers():
    """Register all event handlers on startup"""
    from aipass.trigger.apps.modules.core import trigger
    from .startup import handle_startup
    from .memory import handle_memory_saved
    from .cli import handle_cli_header_displayed
    from .plan_file import handle_plan_file_created, handle_plan_file_deleted, handle_plan_file_moved
    from .error_detected import handle_error_detected, set_send_email_callback
    from .error_logged import handle_error_logged

    # Wire up email send callback for error_detected handler (avoids handler importing from modules)
    try:
        from aipass.ai_mail.apps.modules.email import deliver_email_to_branch
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
    except ImportError:
        _log_warning("ai_mail not available — error notifications won't send")
    from .warning_logged import handle_warning_logged
    from .bulletin_created import handle_bulletin_created
    from .memory_threshold_exceeded import handle_memory_threshold_exceeded
    from .memory_template_updated import handle_memory_template_updated
    from .pr_status_sync import handle_pr_created, handle_pr_merged

    trigger.on("startup", handle_startup)
    trigger.on("memory_saved", handle_memory_saved)
    trigger.on("cli_header_displayed", handle_cli_header_displayed)
    trigger.on("plan_file_created", handle_plan_file_created)
    trigger.on("plan_file_deleted", handle_plan_file_deleted)
    trigger.on("plan_file_moved", handle_plan_file_moved)
    trigger.on("error_detected", handle_error_detected)
    trigger.on("error_logged", handle_error_logged)
    trigger.on("warning_logged", handle_warning_logged)
    trigger.on("bulletin_created", handle_bulletin_created)
    trigger.on("memory_threshold_exceeded", handle_memory_threshold_exceeded)
    trigger.on("memory_template_updated", handle_memory_template_updated)
    trigger.on("pr_created", handle_pr_created)
    trigger.on("pr_merged", handle_pr_merged)

    json_handler.log_operation("handlers_registered", {"success": True})
