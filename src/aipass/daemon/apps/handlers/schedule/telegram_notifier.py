# =================== AIPass ====================
# Name: telegram_notifier.py
# Description: Scheduler lifecycle notifications via Telegram
# Version: 3.0.0
# Created: 2026-02-15
# Modified: 2026-06-25
# =============================================

"""
Scheduler lifecycle notifications — emit running/complete/failed pings
via the @skills telegram notifier (secret slug: telegram/scheduler).

Fail-soft: if the secret is missing or the send fails, returns False
and never raises. The tick MUST keep firing jobs regardless.
"""

from aipass.prax import logger
from aipass.daemon.apps.handlers.json import json_handler


def _send(message: str) -> bool:
    """Send via skills notifier, fail-soft.

    Cross-branch import authorized by TDPLAN-0008 contract —
    daemon emits lifecycle pings through the skills telegram notifier.
    """
    try:
        from aipass.skills.lib.telegram.apps.handlers.notifier import (
            send_telegram_notification,
        )

        return send_telegram_notification(message)
    except Exception as e:
        logger.info("[telegram_notifier] Send failed (non-fatal): %s", e)
        return False


def notify_triggered(owner: str, job_id: str) -> bool:
    """Emit 'running' ping when a job fires."""
    json_handler.log_operation("notify_triggered", {"owner": owner, "job_id": job_id})
    return _send(f"\U0001f535 {owner}/{job_id} running")


def notify_complete(owner: str, job_id: str, summary: str) -> bool:
    """Emit 'complete' ping after successful dispatch."""
    json_handler.log_operation("notify_complete", {"owner": owner, "job_id": job_id})
    return _send(f"✅ {owner}/{job_id} dispatched\n{summary}")


def notify_error(owner: str, job_id: str, error: str) -> bool:
    """Emit 'failed' ping on dispatch failure."""
    json_handler.log_operation("notify_error", {"owner": owner, "job_id": job_id})
    return _send(f"❌ {owner}/{job_id} FAILED\n{error}")
