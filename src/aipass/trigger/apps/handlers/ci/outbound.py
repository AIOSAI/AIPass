# =================== AIPass ====================
# Name: outbound.py
# Description: CI red lane's doors out - mail, dispatch (mail plus wake), the notification feed, the awake count
# Version: 1.1.0
# Created: 2026-10-22
# Modified: 2026-11-16
# =============================================

"""
CI Outbound Handler - every message the lane sends leaves through here
"""

from typing import Any, Callable, Dict, Optional

from aipass.prax import logger
from aipass.trigger.apps.handlers.json import json_handler

MANAGER = "@devpulse"
REVIEWER = "@sentry"
AWAKE_CAP = 2
FEED_STATES = ("red", "dispatched", "pushed", "green", "held", "unowned")

# Set by registry.setup_handlers, the same adapter medic and escalation send through.
_send_email: Optional[Callable[..., bool]] = None


def set_send_email_callback(callback: Callable[..., bool]) -> None:
    """Wire the ai_mail delivery adapter."""
    global _send_email
    _send_email = callback


def mail(to_branch: str, subject: str, body: str, auto_execute: bool = False) -> bool:
    """Deliver one mail from @trigger; False, logged, when nothing is wired or delivery failed."""
    if _send_email is None:
        logger.warning(f"mail not sent, no ai_mail callback wired: {to_branch} {subject}")
        return False
    sent = bool(
        _send_email(
            to_branch=to_branch, subject=subject, message=body, auto_execute=auto_execute, from_branch="@trigger"
        )
    )
    if not sent:
        logger.warning(f"mail delivery failed: {to_branch} {subject}")
    json_handler.log_operation("ci_mail", {"to": to_branch, "sent": sent})
    return sent


def wake(to_branch: str, subject: str) -> bool:
    """Wake *to_branch* with @trigger as sender, so its exit wakes @trigger back to read the reply."""
    try:
        # ai_mail's published door, never its handlers.
        from aipass.ai_mail.apps.modules.door_wake import wake_branch

        _status, woke = wake_branch(to_branch, fresh=False, sender="@trigger", subject=subject)
        return bool(woke)
    except Exception as exc:
        # The mail already waits in the inbox; the missed wake is recorded, not raised.
        logger.warning(f"wake failed for {to_branch}: {exc}")
        return False


def dispatch(to_branch: str, subject: str, body: str) -> bool:
    """Mail as a dispatch task, then wake; a manager is mailed and never woken."""
    if not mail(to_branch, subject, body, auto_execute=True):
        return False
    if to_branch == MANAGER:
        return True
    if not wake(to_branch, subject):
        logger.warning(f"dispatch mailed but not woken: {to_branch} {subject}")
    return True


def feed(state: str, title: str, body: str, /, **extra: Any) -> str:
    """One `system` event from source `ci` on the feed: answers written or refused."""
    payload: Dict[str, str] = {
        key: str(extra.get(key, "") or "") for key in ("run_id", "workflow", "step", "owner", "url")
    }
    payload["state"] = state
    from aipass.ai_mail import send_notification

    written = bool(
        send_notification(kind="system", source="ci", title=title.splitlines()[0][:120], body=body, extra=payload)
    )
    json_handler.log_operation("ci_feed", {"state": state, "written": written})
    return "written" if written else "refused"


def awake_count() -> int:
    """Citizens awake now: distinct targets of dispatches still open whose monitor is not known dead."""
    from aipass.ai_mail import outstanding_dispatches

    targets = {
        str(row.get("target", ""))
        for row in outstanding_dispatches()
        if row.get("monitor_alive") is not False and not row.get("overdue")
    }
    return len(targets - {""})


def cap_allows() -> bool:
    """True when one more wake stays within the cap; an unreadable register raises."""
    return awake_count() < AWAKE_CAP
