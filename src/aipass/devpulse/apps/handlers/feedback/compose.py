# =================== AIPass ====================
# Name: compose.py
# Description: Compose operations — send feedback and reply to messages
# Version: 1.3.0
# Created: 2026-04-11
# Modified: 2026-08-07
# =============================================

"""
Feedback Compose — sending and replying to feedback messages.

Handles inbound feedback from any agent and devpulse replies.
Replies are also delivered to the sender's ai_mail inbox.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from aipass.prax import logger
from aipass.devpulse.apps.handlers.feedback.storage import (
    load_inbox,
    save_inbox,
    generate_id,
)

from aipass.cli.apps.modules import err_console, error, success, warning
from aipass.devpulse.apps.handlers.json import json_handler

console = err_console

# AIPass src/aipass/ directory (four levels up from compose.py)
_AIPASS_ROOT = Path(__file__).resolve().parents[4]

# Devpulse's own ai_mail inbox — stamped as reply_path on delivered replies so
# external recipients can reply cross-project via ai_mail's stored-path route.
_DEVPULSE_INBOX = Path(__file__).resolve().parents[3] / ".ai_mail.local" / "inbox.json"


def _resolve_sender() -> tuple[str, str]:
    """Resolve the sender's identity and ai_mail path from drone env vars.

    Drone sets AIPASS_CALLER_BRANCH and AIPASS_CALLER_CWD when routing.
    Uses these to identify who sent the feedback and where to reply.

    Returns:
        tuple: (branch_name, ai_mail_path_or_empty_string)
    """
    branch = os.environ.get("AIPASS_CALLER_BRANCH", "")
    caller_cwd = os.environ.get("AIPASS_CALLER_CWD", "")

    if not branch:
        return "unknown", ""

    # Try to find sender's ai_mail inbox
    # First: check if caller_cwd points to a branch with ai_mail
    if caller_cwd:
        cwd_path = Path(caller_cwd)
        ai_mail = cwd_path / ".ai_mail.local" / "inbox.json"
        if ai_mail.exists():
            return branch, str(ai_mail)
        # Walk up from CWD to find the branch directory
        for parent in cwd_path.parents:
            ai_mail = parent / ".ai_mail.local" / "inbox.json"
            if ai_mail.exists():
                return branch, str(ai_mail)

    # Fallback: check AIPass internal path
    internal_path = _AIPASS_ROOT / branch / ".ai_mail.local" / "inbox.json"
    if internal_path.exists():
        return branch, str(internal_path)

    return branch, ""


def send_feedback(from_branch: str, subject: str, body: str, ai_mail_path: str = "") -> str:
    """Add a new feedback message to devpulse's inbox.

    Args:
        from_branch: Name of the sending branch/agent.
        subject: Message subject line.
        body: Message body text.
        ai_mail_path: Full path to sender's ai_mail inbox for replies.

    Returns:
        str: The generated message ID.
    """
    json_handler.log_operation("send_feedback", {"from_branch": from_branch, "subject": subject})
    data = load_inbox()
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

    data["messages"].append(message)
    data["total_messages"] = len(data["messages"])
    data["unread_count"] = data.get("unread_count", 0) + 1

    save_inbox(data)

    logger.info(f"[FEEDBACK] Received feedback from {from_branch}: {subject}")
    console.print(f"[green]Feedback received (id: {msg_id}).[/green]")

    # Anonymous sender = no return address. Say so NOW, at send time, to the
    # one party who can fix it — a reply to 'unknown' can never be delivered
    # (live failure 2026-08-04: 6 messages arrived anonymous, 3 replies
    # silently stranded for 5 hours).
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
    """Reply to a feedback message and deliver to sender's ai_mail.

    Adds the reply to the local thread and attempts to deliver
    a copy to the sender's ai_mail inbox.

    Args:
        msg_id: The message ID to reply to.
        body: The reply body text.

    Returns:
        bool: True if reply was saved (regardless of ai_mail delivery).
    """
    data = load_inbox()
    messages = data.get("messages", [])

    msg = None
    for m in messages:
        if m.get("id") == msg_id:
            msg = m
            break

    if msg is None:
        error(f"Message {msg_id} not found.")
        return False

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

    reply = {
        "from": "devpulse",
        "body": body,
        "timestamp": now,
    }

    msg.setdefault("thread", []).append(reply)
    save_inbox(data)

    console.print(f"[green]Reply added to thread {msg_id}.[/green]")

    # Deliver to sender's ai_mail using stored reply path — and report the
    # outcome honestly. A reply the sender never sees is not a sent reply
    # (live failure 2026-08-04: 3 replies to 'unknown' silently stranded).
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
    """Deliver a reply to the sender's ai_mail inbox.

    Writes directly to the sender's .ai_mail.local/inbox.json.

    Args:
        to_branch: Target branch name.
        subject: Original message subject (prefixed with Re:).
        body: Reply body text.
        thread_id: Original feedback message ID for reference.
        reply_path: Sender inbox path captured at send time.

    Returns:
        tuple: (delivered, reason) — reason explains a failed delivery.
    """
    # Use stored reply_path (works for external projects), fall back to AIPass internal
    if reply_path:
        ai_mail_path = Path(reply_path)
    else:
        ai_mail_path = _AIPASS_ROOT / to_branch / ".ai_mail.local" / "inbox.json"

    if not ai_mail_path.exists():
        reason = f"ai_mail inbox not found at {ai_mail_path}"
        logger.warning(f"[FEEDBACK] {reason} for {to_branch} — skipping delivery")
        return False, reason

    try:
        with open(ai_mail_path, encoding="utf-8") as f:
            inbox = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        reason = f"failed to read inbox: {e}"
        logger.warning(f"[FEEDBACK] Failed to read {to_branch} ai_mail inbox: {e}")
        return False, reason

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    mail_id = generate_id()

    # ai_mail v2 message schema (see ai_mail email/delivery.py) — the viewer
    # reads 'message' and 'status'. Writing 'body'/'read' here left delivered
    # replies rendering as EMPTY under view while the data sat intact in
    # inbox.json (VERA field report 2026-08-05).
    # 'from' must be the @-prefixed email and 'reply_path' must point back at
    # our inbox: ai_mail's reply verb resolves the destination by matching
    # 'from' against branch emails, then falls back to the stored reply_path
    # for cross-project delivery (reply.py). An @-less from with no reply_path
    # made every delivered reply a dead end (@ai_mail wall-2 report 2026-08-07).
    # 'reply_to' takes precedence over 'from' in that resolution and must NOT
    # match any registry branch email: a match on '@devpulse' routes the reply
    # through normal delivery, which refuses cross-project mail (#134) — the
    # stored reply_path is only consulted on a registry MISS. The feedback loop
    # is cross-project BY DESIGN and owns its whole round trip (Patrick ruling
    # 2026-08-07); '@devpulse:feedback' steers replies past the registry onto
    # the reply_path route.
    mail_message = {
        "id": mail_id,
        "timestamp": now,
        "from": "@devpulse",
        "from_name": "devpulse",
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

    inbox.setdefault("messages", []).insert(0, mail_message)
    inbox["total_messages"] = len(inbox["messages"])
    inbox["unread_count"] = sum(
        1
        for m in inbox["messages"]
        if m.get("status") == "new" or (m.get("status") is None and not m.get("read", False))
    )

    try:
        with open(ai_mail_path, "w", encoding="utf-8") as f:
            json.dump(inbox, f, indent=2)
            f.write("\n")
        logger.info(f"[FEEDBACK] Reply delivered to {to_branch} ai_mail")
        return True, "delivered"
    except OSError as e:
        reason = f"failed to write inbox: {e}"
        logger.warning(f"[FEEDBACK] Failed to write to {to_branch} ai_mail: {e}")
        return False, reason
