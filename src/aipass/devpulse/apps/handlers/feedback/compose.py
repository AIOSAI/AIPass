# META
# module: devpulse.feedback
# description: Compose operations — send feedback and reply to messages
# END META

"""
Feedback Compose — sending and replying to feedback messages.

Handles inbound feedback from any agent and devpulse replies.
Replies are also delivered to the sender's ai_mail inbox.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console

from aipass.prax import logger
from aipass.devpulse.apps.handlers.feedback.storage import (
    load_inbox,
    save_inbox,
    generate_id,
)

console = Console(stderr=True)

# AIPass src/aipass/ directory (four levels up from compose.py)
_AIPASS_ROOT = Path(__file__).resolve().parents[4]


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
        console.print(f"[red]Message {msg_id} not found.[/red]")
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

    # Deliver to sender's ai_mail using stored reply path
    sender = msg.get("from", "")
    reply_path = msg.get("reply_path", "")
    if sender:
        _deliver_to_ai_mail(sender, msg.get("subject", ""), body, msg_id, reply_path)

    return True


def _deliver_to_ai_mail(to_branch: str, subject: str, body: str, thread_id: str, reply_path: str = "") -> None:
    """Deliver a reply to the sender's ai_mail inbox.

    Writes directly to the sender's .ai_mail.local/inbox.json.
    If the path does not exist or delivery fails, logs a warning
    and skips silently.

    Args:
        to_branch: Target branch name.
        subject: Original message subject (prefixed with Re:).
        body: Reply body text.
        thread_id: Original feedback message ID for reference.
    """
    # Use stored reply_path (works for external projects), fall back to AIPass internal
    if reply_path:
        ai_mail_path = Path(reply_path)
    else:
        ai_mail_path = _AIPASS_ROOT / to_branch / ".ai_mail.local" / "inbox.json"

    if not ai_mail_path.exists():
        logger.warning(f"[FEEDBACK] ai_mail inbox not found for {to_branch} at {ai_mail_path} — skipping delivery")
        return

    try:
        with open(ai_mail_path, encoding="utf-8") as f:
            inbox = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"[FEEDBACK] Failed to read {to_branch} ai_mail inbox: {e}")
        return

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    mail_id = generate_id()

    mail_message = {
        "id": mail_id,
        "from": "devpulse",
        "to": to_branch,
        "subject": f"Re: {subject}",
        "body": body,
        "timestamp": now,
        "read": False,
        "metadata": {
            "source": "feedback",
            "thread_id": thread_id,
        },
    }

    inbox.setdefault("messages", []).append(mail_message)
    inbox["total_messages"] = len(inbox["messages"])
    inbox["unread_count"] = inbox.get("unread_count", 0) + 1

    try:
        with open(ai_mail_path, "w", encoding="utf-8") as f:
            json.dump(inbox, f, indent=2)
            f.write("\n")
        logger.info(f"[FEEDBACK] Reply delivered to {to_branch} ai_mail")
    except OSError as e:
        logger.warning(f"[FEEDBACK] Failed to write to {to_branch} ai_mail: {e}")
