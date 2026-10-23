# =================== AIPass ====================
# Name: outbound.py
# Description: CI red lane's doors out - mail, dispatch (mail plus wake), the notification feed, the awake count
# Version: 1.0.0
# Created: 2026-10-22
# Modified: 2026-10-22
# =============================================

"""
CI Outbound Handler - every message the lane sends leaves through here

Silent by contract: it runs on the event path, so it logs to a `.jsonl` trail, never through prax.
"""

from typing import Any, Callable, Dict, Optional

from aipass.trigger.apps.config import TRIGGER_ROOT, trail_logger
from aipass.trigger.apps.handlers.json import json_handler

logger = trail_logger(TRIGGER_ROOT / "logs" / "ci_lane.jsonl")

MANAGER = "@devpulse"
REVIEWER = "@seedgo"
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
    """One `system` event from source `ci` on the feed: answers written, refused, no_door or unavailable."""
    payload: Dict[str, str] = {
        key: str(extra.get(key, "") or "") for key in ("run_id", "workflow", "step", "owner", "url")
    }
    payload["state"] = state
    try:
        import aipass.ai_mail as ai_mail

        send = getattr(ai_mail, "send_notification", None)
    except (ImportError, OSError) as exc:
        logger.warning(f"feed not written, ai_mail unavailable: {exc}")
        return "unavailable"
    # ai_mail publishes no feed writer yet; the call is built to the contract and waits on that door.
    if send is None:
        logger.warning(f"feed not written, ai_mail publishes no send_notification: {state} {title}")
        return "no_door"
    written = bool(send(kind="system", source="ci", title=title.splitlines()[0][:120], body=body, extra=payload))
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
    """True when one more wake stays within the cap; an unreadable register answers no, so the wake queues."""
    try:
        count = awake_count()
    except Exception as exc:
        logger.warning(f"dispatch register unreadable, wake queued: {exc}")
        return False
    return count < AWAKE_CAP
