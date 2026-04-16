# =================== AIPass ====================
# Name: error_logged.py
# Description: Legacy error logged event handler — monitor-only (no dispatch)
# Version: 3.0.0
# Created: 2026-01-31
# Modified: 2026-04-10
# =============================================

"""
Error Logged Event Handler (Monitor-Only)

Legacy handler for error_logged events. All dispatch now goes through
error_detected.py (Medic v2) which provides circuit breaker, per-fingerprint
backoff, and registry-based deduplication.

This handler logs event metadata for monitoring. No email, no wake_branch.
"""

from datetime import datetime, timezone
from typing import Any
from aipass.trigger.apps.config import TRIGGER_ROOT
from aipass.trigger.apps.handlers.json import json_handler

_HANDLER_LOG = TRIGGER_ROOT / "logs" / "error_logged_handler.log"


def _log_warning(message: str) -> None:
    """Log warning to file (event handlers cannot import Prax logger - causes recursion)."""
    try:
        _HANDLER_LOG.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        with open(_HANDLER_LOG, "a", encoding="utf-8") as f:
            f.write(f"{ts} | WARNING | {message}\n")
    except Exception:
        pass


def handle_error_logged(
    branch: str | None = None,
    message: str | None = None,
    error_hash: str | None = None,
    source_module: str | None = None,
    module_name: str | None = None,
    **_kwargs: Any,
) -> None:
    """Handle error_logged event — monitor-only, no dispatch.

    All dispatch now goes through error_detected.py (Medic v2).
    This handler logs event metadata for monitoring only.

    Args:
        branch: Branch where error occurred
        message: Error message text
        error_hash: Unique error identifier
        source_module: Module that logged the error
        module_name: Deprecated alias for source_module
        **_kwargs: Additional event data (ignored)
    """
    try:
        if not branch or not message or not error_hash:
            return

        effective_module = source_module or module_name or "unknown"

        json_handler.log_operation(
            "error_logged_event",
            {
                "branch": branch,
                "module": effective_module,
                "error_hash": error_hash,
            },
        )

    except Exception as exc:
        _log_warning(f"handle_error_logged failed: {exc}")
        return
