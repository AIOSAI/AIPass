# =================== AIPass ====================
# Name: email.py
# Description: Email Orchestration Module
# Version: 3.5.0
# Created: 2025-12-02
# Modified: 2026-10-17
# =============================================

"""
Email Orchestration Module

Handles send, inbox, view, close, reply, sent, contacts; business logic lives in handlers.
"""

import os
import sys
from pathlib import Path
from typing import List

from rich.markup import escape

from aipass.prax import logger
from aipass.cli.apps.modules import console, error, warning
from aipass.ai_mail.apps.handlers.cli.help_flags import wants_help
from aipass.ai_mail.apps.handlers.email.create import load_email_file
from aipass.ai_mail.apps.handlers.email.format import format_email_list_item, format_email_header
from aipass.ai_mail.apps.handlers.email.inbox_ops import load_inbox
from aipass.ai_mail.apps.handlers.email.inbox_cleanup import (
    mark_all_read_and_archive,
    mark_as_opened,
    mark_as_closed_and_archive,
)
from aipass.ai_mail.apps.handlers.email.reply import get_email_by_id, send_reply
from aipass.ai_mail.apps.handlers.users.user import get_current_user
from aipass.ai_mail.apps.handlers.registry.read import get_all_branches, get_branch_by_email
from aipass.ai_mail.apps.handlers.json import json_handler
from aipass.ai_mail.apps.handlers.email.close_ops import batch_close, batch_close_post_ops
from aipass.ai_mail.apps.handlers.email.inbox_resolve import resolve_inbox_target
from aipass.ai_mail.apps.handlers.paths import find_repo_root

if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8", errors="replace")

_AI_MAIL_DIR = Path(__file__).resolve().parents[2]
_REPO_ROOT = find_repo_root()

# Max rows any bulk listing prints. Applied to the NEWEST end of the store.
LIST_LIMIT = 20

try:
    from aipass.ai_mail.apps.handlers.central_writer import update_central
except ImportError as e:
    logger.warning("[email] central_writer import unavailable: %s", e)
    update_central = None


def _print_row(row: str) -> None:
    """Print one listing row, never letting a render failure hide it.

    Rows carry sender text; a row that fails to render is reprinted raw, because an invisible message looks delivered.
    """
    try:
        console.print(row)
    except Exception as e:
        logger.warning("[email] row render failed, printing raw: %s", e)
        console.print(f"[!! RAW — markup render failed: {e} !!]", markup=False)
        console.print(row, markup=False)


def _resolve_branch_path() -> Path:
    """Resolve the branch path for inbox operations.

    Identity comes from get_current_user() only, never a fallback to @ai_mail's own mailbox; RuntimeError propagates.
    """
    return Path(get_current_user()["mailbox_path"]).parent


def caller_refusal() -> str:
    """Return a refusal message when the caller stands outside any branch, else "".

    Called once from the CLI entry point so every verb is gated; in-process importers do not pass through here.
    The text is get_current_user()'s own RuntimeError, never a second wording.
    """
    try:
        get_current_user()
        return ""
    except RuntimeError as e:
        logger.warning("[email] caller refused — no branch under the caller: %s", e)
        return str(e)


HELP_TEXT = """
Email Module - Send and manage branch-to-branch email (Lifecycle v2)

COMMANDS:
  email     - Send email to a branch (preferred)
  send      - Send email to a branch (alias for email)
  inbox     - View inbox messages (new + opened)
  view      - View email content and mark as opened
  reply     - Reply to email (auto-closes original)
  close     - Close email without reply (archives to deleted)
  sent      - View sent messages
  contacts  - Manage contacts

USAGE:
  ai_mail email @recipient "subject" "message" [--dispatch] [--reply-to @branch]
  ai_mail send @recipient "subject" "message"   (same as email)
  ai_mail inbox | view <id> | view latest | reply <id> "msg" | close <id> | sent | contacts

FLAGS:
  --dispatch        Mark as dispatch task (adds dispatch header)
  --from @branch    Send as a named sender — the explicit identity override
                    used when caller detection cannot see who is calling
  --reply-to        Redirect replies to a different branch
  --no-memory-save  Skip memory update requirement in dispatch header
  --upsert-key KEY  Repeat signature: rewrite the recipient's open message
                    carrying KEY (from you) instead of stacking a new one.
                    Bumps its update counter, keeps its id and read status,
                    never wakes anything. Closing it re-arms the signature.

NOTE: To send + wake in one step, use: drone @ai_mail dispatch @target "Subject" "Body"
"""


def print_help():
    """Display help text for the email module."""
    console.print(HELP_TEXT)


def handle_command(command: str, args: List[str]) -> bool:
    """Handle email commands - main orchestration entry point."""
    if command in ("--help", "-h"):
        print_help()
        return True
    # send/email belong to email_send.py alone: two claimants would be settled by directory listing order.
    valid = ["inbox", "view", "close", "reply", "sent", "contacts", "read", "register"]
    if command not in valid:
        return False
    # Whole-sequence: a later --help must not reach close/reply and mutate a mailbox.
    if wants_help(args):
        print_help()
        return True

    dispatch = {
        "inbox": handle_inbox,
        "view": handle_view,
        "close": handle_close,
        "reply": handle_reply,
        "read": handle_view,
        "sent": handle_sent,
        "contacts": handle_contacts,
        "register": handle_register,
    }
    return dispatch[command](args)


def handle_inbox(args: List[str]) -> bool:
    """Orchestrate inbox viewing."""
    json_handler.log_operation("inbox_viewed")
    try:
        first_arg = args[0] if args else None

        # get_current_user passed directly, no substitute: an unresolvable caller must not see @ai_mail's inbox.
        ok, info = resolve_inbox_target(first_arg, _REPO_ROOT, get_branch_by_email, get_current_user)
        if not ok:
            error(info["error"])
            return True

        inbox_file = info["inbox_file"]
        target = info["target_branch"]
        label = f" for {target} ({info['display_name']})" if target else ""

        if not inbox_file.exists():
            console.print(f"Inbox{label} is empty")
            return True

        inbox_data = load_inbox(inbox_file)
        messages = inbox_data.get("messages", [])
        if not messages:
            console.print(f"Inbox{label} is empty")
            return True

        # delivery.py inserts new mail at index 0: slice the newest first, then reverse for reading order.
        newest = messages[:LIST_LIMIT]
        display = list(reversed(newest))
        console.print(f"\nInbox{label}\n" + "=" * 70)
        for i, msg in enumerate(display, 1):
            _print_row(format_email_list_item(i, msg, show_unread=True))
        console.print("\n" + "=" * 70)
        if len(messages) > len(display):
            console.print(f"Showing {len(display)} most recent of {len(messages)} messages")
        else:
            console.print(f"Showing {len(display)} of {len(messages)} messages")
        return True
    except BrokenPipeError as e:
        logger.warning("[email] inbox view broken pipe: %s", e)
        return True
    except Exception as e:
        logger.error(f"[email] Inbox view failed: {e}")
        error(f"Error: {e}")
        return True


def handle_view(args: List[str]) -> bool:
    """View email content and mark as opened."""
    json_handler.log_operation("view_email_initiated", {"args": args})
    if not args:
        error("Usage: drone @ai_mail view <message_id> | drone @ai_mail view latest")
        return True
    try:
        branch_path = _resolve_branch_path()
        message_id = args[0]

        if message_id.lower() == "latest":
            inbox_file = branch_path / ".ai_mail.local" / "inbox.json"
            inbox_data = load_inbox(inbox_file)
            if not inbox_data or not inbox_data.get("messages"):
                error("Inbox is empty")
                return True
            # delivery.py inserts at index 0, so the most recent message is the FIRST entry.
            message_id = inbox_data["messages"][0].get("id")
            if not message_id:
                error("Could not find latest message")
                return True

        success, message, email_data = mark_as_opened(branch_path, message_id)
        if not success or email_data is None:
            error(message)
            return True
        header = format_email_header(email_data)
        console.print(f"\n{header}")
        # Raw sender text renders with markup off: markup=False cannot raise MarkupError on any content.
        console.print(f"\n{email_data.get('message', '')}", markup=False)
        console.print("=" * 70)
        # Echo the message's OWN id, never args[0] ("latest", or a sender's sent_id).
        resolved_id = email_data.get("id", message_id)
        sent_id = email_data.get("sent_id")
        origin = f" | sender's id: {sent_id}" if sent_id else ""
        console.print(f"[dim]Status: opened | ID: {resolved_id}{origin}[/dim]")
        console.print(f'[dim]To reply: drone @ai_mail reply {resolved_id} "your message"[/dim]')
        console.print(f"[dim]To close: drone @ai_mail close {resolved_id}[/dim]")
        json_handler.log_operation("email_viewed", {"message_id": resolved_id})
        return True
    except BrokenPipeError as e:
        logger.warning("[email] view broken pipe: %s", e)
        return True
    except Exception as e:
        logger.error(f"[email] View failed: {e}")
        error(f"Error: {e}")
        return True


def handle_close(args: List[str]) -> bool:
    """Close email(s) and archive to deleted."""
    json_handler.log_operation("close_email_initiated", {"args": args})
    if not args:
        error("Usage: drone @ai_mail close <id> [id2 ...] | close all")
        return True
    try:
        branch_path = _resolve_branch_path()
        if args[0].lower() == "all":
            success, message, count = mark_all_read_and_archive(branch_path)
            if success:
                console.print(f"[green]{escape(message)}[/green]")
                json_handler.log_operation("email_closed_all", {"count": count})
            else:
                error(message)
            return True

        results, closed, failed = batch_close(branch_path, args, mark_as_closed_and_archive)
        for msg_id, success, message in results:
            if success:
                console.print(f"[green]{escape(message)}[/green]")
            else:
                error(message)
            if success:
                json_handler.log_operation("email_closed", {"message_id": msg_id})

        if len(args) > 1 and closed > 0:
            try:
                from aipass.ai_mail.apps.handlers.email.purge import run_purge
            except ImportError as e:
                logger.warning("[email] purge import unavailable: %s", e)
                run_purge = None
            batch_close_post_ops(branch_path, update_central, run_purge)
            console.print(f"\nClosed {closed}, failed {failed}")
        return True
    except Exception as e:
        logger.error(f"[email] Close failed: {e}")
        error(f"Error: {e}")
        return True


def handle_reply(args: List[str]) -> bool:
    """Reply to an email."""
    json_handler.log_operation("reply_email_initiated", {"args": args})
    if len(args) < 2:
        error('Usage: drone @ai_mail reply <message_id> "your message"')
        return True
    try:
        branch_path = _resolve_branch_path()
        inbox_file = branch_path / ".ai_mail.local" / "inbox.json"
        original = get_email_by_id(inbox_file, args[0])
        if not original:
            error(f"Message not found: {args[0]}")
            return True
        reply_message = " ".join(args[1:])
        flag_like = [a for a in args[1:] if a.startswith("--")]
        if flag_like:
            # reply has no flag parsing: args[1:] is the body verbatim, so an unknown flag ships as literal text.
            warning(
                f"reply takes no flags — {', '.join(flag_like)} sent as literal message text.",
            )
        success, message, reply_id = send_reply(branch_path, original, reply_message)
        if success:
            console.print(f"[green]{escape(message)}[/green]")
        else:
            error(message)
        if success:
            json_handler.log_operation("email_replied", {"message_id": args[0], "reply_id": reply_id})
        return True
    except Exception as e:
        logger.error(f"[email] Reply failed: {e}")
        error(f"Error: {e}")
        return True


def handle_sent(args: List[str]) -> bool:
    """View sent messages."""
    json_handler.log_operation("sent_viewed")
    try:
        sent_folder = _resolve_branch_path() / ".ai_mail.local" / "sent"
        if not sent_folder.exists():
            console.print("No sent messages")
            return True
        # Sort by mtime, not filename: create.py and reply.py use two naming schemes, and hex ids outsort dates.
        files = sorted(sent_folder.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True)[:LIST_LIMIT]
        if not files:
            console.print("No sent messages")
            return True
        console.print("\nSent Messages\n" + "=" * 70)
        for i, f in enumerate(files, 1):
            data = load_email_file(f)
            if data:
                _print_row(format_email_list_item(i, data, show_unread=False))
            else:
                # An unreadable sent file still gets a row, so nothing sent is silently under-reported.
                logger.warning("[email] sent file unreadable, listing as placeholder: %s", f.name)
                console.print(f"\n{i}. [UNREADABLE FILE] {f.name}", markup=False)
        console.print("\n" + "=" * 70 + f"\nShowing {len(files)} sent messages")
        return True
    except Exception as e:
        logger.error(f"[email] Sent view failed: {e}")
        error(f"Error: {e}")
        return True


def handle_contacts(args: List[str]) -> bool:
    """View contacts."""
    json_handler.log_operation("contacts_viewed")
    try:
        branches = get_all_branches()
        if not branches:
            error("No contacts found")
            return True
        console.print(f"\nTotal: {len(branches)} branches\n")
        console.print(f"{'EMAIL':<20} {'BRANCH NAME':<25} {'PATH':<35}")
        console.print("-" * 80)
        for b in sorted(branches, key=lambda x: x["email"]):
            console.print(f"{b['email']:<20} {b['name']:<25} {b['path']:<35}")
        return True
    except Exception as e:
        logger.error(f"[email] Contacts view failed: {e}")
        error(f"Error: {e}")
        return True


def handle_register(args: List[str]) -> bool:
    """Register a branch in the contacts address book.

    Usage: drone @ai_mail register @branch /path/to/inbox [project]
    """
    json_handler.log_operation("register_contact_initiated", {"args": args})
    if len(args) < 2:
        error("Usage: register @branch /path/to/inbox [project]")
        return True
    branch_name = args[0].lstrip("@")
    inbox_path = args[1]
    project = args[2] if len(args) > 2 else ""
    from aipass.ai_mail.apps.handlers.email.contacts import register_contact

    ok = register_contact(branch_name, project, inbox_path)
    if ok:
        console.print(f"[green]Registered @{branch_name} -> {inbox_path}[/green]")
    else:
        error(f"Failed to register @{branch_name}")
    return True


def print_introspection():
    """Display module introspection info."""
    console.print()
    console.print("email Module")
    console.print("Orchestrates email workflows: send, inbox, view, close, reply, sent, and contacts.")
    console.print()
    console.print("Connected Handlers:")
    console.print("  handlers/email/")
    console.print("    - send.py (resolve_sender_info — resolve sender identity for outgoing email)")
    console.print("    - send.py (send_to_single — deliver email to a single branch)")
    console.print("    - send.py (send_to_broadcast — broadcast email to all branches)")
    console.print("    - send.py (collect_interactive_input — gather interactive send inputs)")
    console.print("    - send_args.py (parse_send_args — parse CLI send arguments)")
    console.print("    - send_args.py (resolve_dispatch_target — resolve dispatch target branch)")
    console.print("    - create.py (create_email_file — create email JSON file on disk)")
    console.print("    - create.py (load_email_file — load email data from JSON file)")
    console.print("    - delivery.py (deliver_email_to_branch — deliver email into branch inbox)")
    console.print("    - format.py (format_email_list_item — format email for list display)")
    console.print("    - inbox_ops.py (load_inbox — load inbox JSON data)")
    console.print("    - inbox_cleanup.py (mark_all_read_and_archive — mark all emails read and archive)")
    console.print("    - inbox_cleanup.py (mark_as_opened — mark email as opened)")
    console.print("    - inbox_cleanup.py (mark_as_closed_and_archive — close and archive email)")
    console.print("    - inbox_resolve.py (resolve_inbox_target — resolve inbox target from args)")
    console.print("    - close_ops.py (batch_close — close multiple emails in batch)")
    console.print("    - close_ops.py (batch_close_post_ops — post-close cleanup operations)")
    console.print("    - reply.py (get_email_by_id — retrieve email by message ID)")
    console.print("    - reply.py (send_reply — send reply to an email)")
    console.print("    - header.py (prepend_dispatch_header — prepend dispatch header to message)")
    console.print("    - error_dispatch.py (dispatch_send_error — handle and report send errors)")
    console.print("    - error_dispatch.py (on_email_delivered — post-delivery callback handler)")
    console.print("  handlers/users/")
    console.print("    - user.py (get_current_user — get current branch user info)")
    console.print("    - branch_detection.py (get_branch_info_from_registry — look up branch info)")
    console.print("  handlers/registry/")
    console.print("    - read.py (get_all_branches — list all registered branches)")
    console.print("    - read.py (get_branch_by_email — look up branch by email address)")
    console.print("  handlers/json_utils/")
    console.print("    - json_handler.py (log_operation — log structured operation to JSON)")
    console.print("  handlers/")
    console.print("    - central_writer.py (update_central — update central dashboard data)")
    console.print()


if __name__ == "__main__":
    if len(sys.argv) == 1 or sys.argv[1] in ["--help", "-h", "help"]:
        print_help()
        sys.exit(0)
    command = sys.argv[1]
    remaining = sys.argv[2:] if len(sys.argv) > 2 else []
    if not handle_command(command, remaining):
        error(f"Unknown command: {command}")
        console.print("[dim]Run 'drone @ai_mail --help' for available commands[/dim]\n")
        sys.exit(1)
