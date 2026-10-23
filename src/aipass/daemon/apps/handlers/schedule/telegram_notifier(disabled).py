# =================== AIPass ====================
# Name: telegram_notifier.py
# Description: Scheduler lifecycle notifications via Telegram
# Version: 3.0.1
# Created: 2026-02-15
# Modified: 2026-10-17
# =============================================

"""
Scheduler lifecycle notifications — emit running/complete/failed pings
via the @skills telegram notifier (secret slug: telegram/scheduler)."""

from aipass.prax import logger
from aipass.daemon.apps.handlers.json import json_handler


def _send(message: str) -> bool:
    """Send via skills notifier; False on any failure, never raises (the tick must keep firing jobs)."""
    try:
        from aipass.skills.apps.modules.door_notifier import send_telegram_notification

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
