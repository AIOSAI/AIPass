# =================== AIPass ====================
# Name: compose.py
# Description: Compose operations — send feedback and reply to messages
# Version: 1.4.0
# Created: 2026-04-11
# Modified: 2026-10-22
# =============================================

"""
Feedback Compose — sending and replying to feedback messages.
"""

import os
from datetime import datetime, timezone
from pathlib import Path

from aipass.prax import logger
from aipass.devpulse.apps.handlers.feedback.storage import (
    inbox_lock,
    load_inbox,
    save_inbox,
    generate_id,
)

from aipass.cli.apps.modules import err_console, error, success, warning
from aipass.devpulse.apps.handlers.json import json_handler
from aipass.devpulse.apps.handlers.module_root import module_file
from aipass import ai_mail as _ai_mail

console = err_console

_AIPASS_ROOT = module_file(__file__).parents[4]

# Stamped as reply_path on delivered replies so external recipients can reply cross-project.
_DEVPULSE_INBOX = module_file(__file__).parents[3] / ".ai_mail.local" / "inbox.json"


def _resolve_sender() -> tuple[str, str]:
    """Resolve (branch, ai_mail path or "") from the AIPASS_CALLER_* vars drone sets when routing."""
    branch = os.environ.get("AIPASS_CALLER_BRANCH", "")
    caller_cwd = os.environ.get("AIPASS_CALLER_CWD", "")

    if not branch:
        return "unknown", ""

    if caller_cwd:
        cwd_path = Path(caller_cwd)
        ai_mail = cwd_path / ".ai_mail.local" / "inbox.json"
        if ai_mail.exists():
            return branch, str(ai_mail)
        for parent in cwd_path.parents:
            ai_mail = parent / ".ai_mail.local" / "inbox.json"
            if ai_mail.exists():
                return branch, str(ai_mail)

    internal_path = _AIPASS_ROOT / branch / ".ai_mail.local" / "inbox.json"
    if internal_path.exists():
        return branch, str(internal_path)

    return branch, ""


def send_feedback(from_branch: str, subject: str, body: str, ai_mail_path: str = "") -> str:
    """Add a new feedback message to devpulse's inbox and return its id."""
    json_handler.log_operation("send_feedback", {"from_branch": from_branch, "subject": subject})
    msg_id = generate_id()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

    message = {
        "id": msg_id,
        "from": from_branch,
        "subject": subject,
        "body": body,
        "timestamp": now,
        "read": False,
        "thread": [],
        "reply_path": ai_mail_path,
    }

    with inbox_lock():
        data = load_inbox()
        data["messages"].append(message)
        data["total_messages"] = len(data["messages"])
        data["unread_count"] = data.get("unread_count", 0) + 1
        save_inbox(data)

    logger.info(f"[FEEDBACK] Received feedback from {from_branch}: {subject}")
    console.print(f"[green]Feedback received (id: {msg_id}).[/green]")

    # No return address means no reply can arrive: tell the sender now, the one party who can fix it.
    # warning(), not error(): the feedback was stored, so the command must not be marked failed.
    if from_branch == "unknown" or not ai_mail_path:
        logger.warning(
            f"[FEEDBACK] Sender unresolved (branch={from_branch}, "
            f"reply_path={ai_mail_path or 'none'}) — replies cannot be delivered"
        )
        warning(
            "your identity could not be resolved — replies to this feedback CANNOT reach you",
            details="Run drone from inside your branch directory (where "
            ".trinity/passport.json lives) so replies have a return address.",
        )

    return msg_id


def reply_to(msg_id: str, body: str) -> bool:
    """Reply to a feedback message and deliver to sender's ai_mail; True once saved, whatever the delivery."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    reply = {
        "from": "devpulse",
        "body": body,
        "timestamp": now,
    }

    with inbox_lock():
        data = load_inbox()
        msg = next((m for m in data.get("messages", []) if m.get("id") == msg_id), None)
        if msg is None:
            error(f"Message {msg_id} not found.")
            return False
        msg.setdefault("thread", []).append(reply)
        save_inbox(data)

    console.print(f"[green]Reply added to thread {msg_id}.[/green]")

    # A reply the sender never sees is not a sent reply: a failed delivery is an error.
    sender = msg.get("from", "")
    reply_path = msg.get("reply_path", "")
    if sender:
        delivered, reason = _deliver_to_ai_mail(sender, msg.get("subject", ""), body, msg_id, reply_path)
        if delivered:
            success(f"Delivered to {sender}'s ai_mail inbox.")
        else:
            error(
                f"NOT delivered to {sender}: {reason}",
                suggestion="The reply is saved in the thread only — the sender will not see it.",
            )
    else:
        error("NOT delivered: message has no sender recorded.")

    return True


def _deliver_to_ai_mail(
    to_branch: str, subject: str, body: str, thread_id: str, reply_path: str = ""
) -> tuple[bool, str]:
    """Write a reply into the sender's .ai_mail.local/inbox.json through ai_mail's door: (delivered, reason).

    The door holds ai_mail's inbox lock and fires the feed event; a direct write here once raced the host's
    own delivery and left the phone deaf to the reply.
    """
    if reply_path:
        ai_mail_path = Path(reply_path)
    else:
        ai_mail_path = _AIPASS_ROOT / to_branch / ".ai_mail.local" / "inbox.json"

    # A guest in ai_mail's store writes the host's timestamp format: local wall-clock, space-separated.
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ai_mail v2 schema: its viewer reads 'message' and 'status'; 'body'/'read' render empty.
    # 'reply_to' must miss every registry email: a hit routes through delivery, which refuses cross-project
    # mail, and only a miss reaches the stored reply_path. '@devpulse:feedback' misses on purpose.
    mail_message = {
        "timestamp": now,
        "from": "@devpulse",
        "from_name": "devpulse",
        "to": f"@{to_branch.lstrip('@')}",
        "reply_to": "@devpulse:feedback",
        "subject": f"Re: {subject}",
        "message": body,
        "status": "new",
        "reply_path": str(_DEVPULSE_INBOX),
        "metadata": {
            "source": "feedback",
            "thread_id": thread_id,
        },
    }

    delivered, reason, _mail_id = _ai_mail.post_to_inbox_file(ai_mail_path, mail_message)
    if delivered:
        logger.info(f"[FEEDBACK] Reply delivered to {to_branch} ai_mail")
        return True, "delivered"
    logger.warning(f"[FEEDBACK] Reply to {to_branch} not delivered: {reason}")
    return False, reason
