# =================== AIPass ====================
# Name: email.py
# Description: Email Orchestration Module
# Version: 3.0.0
# Created: 2025-12-02
# Modified: 2025-12-02
# =============================================

"""
Email Orchestration Module

Orchestrates email workflows for AI_Mail CLI system.
Handles: send, inbox, view, close, reply, sent, contacts commands.

Module Pattern:
- handle_command(command, args) -> bool entry point
- Imports handlers for business logic
- Logs operations via json_handler
- NO business logic in this file
"""

import sys
from pathlib import Path
from typing import List

# Infrastructure
_AI_MAIL_DIR = Path(__file__).resolve().parents[2]
_REPO_ROOT = _AI_MAIL_DIR.parents[2]

from aipass.prax import logger
from aipass.cli.apps.modules import console, error
from aipass.trigger.apps.modules.core import trigger

# Handlers - business logic providers
from aipass.ai_mail.apps.handlers.email.dashboard_sync import push_dashboard_update
from aipass.ai_mail.apps.handlers.email.delivery import deliver_email_to_branch
from aipass.ai_mail.apps.handlers.email.create import create_email_file, load_email_file
from aipass.ai_mail.apps.handlers.email.format import format_email_list_item, format_email_header
from aipass.ai_mail.apps.handlers.email.inbox_ops import load_inbox
from aipass.ai_mail.apps.handlers.email.inbox_cleanup import (
    mark_all_read_and_archive,
    mark_as_opened,
    mark_as_closed_and_archive,
)
from aipass.ai_mail.apps.handlers.email.reply import get_email_by_id, send_reply
from aipass.ai_mail.apps.handlers.email.header import prepend_dispatch_header
from aipass.ai_mail.apps.handlers.users.user import get_current_user
from aipass.ai_mail.apps.handlers.registry.read import get_all_branches, get_branch_by_email
from aipass.ai_mail.apps.handlers.json import json_handler
from aipass.ai_mail.apps.handlers.email.send import (
    resolve_sender_info,
    send_to_broadcast,
    send_to_single,
    collect_interactive_input,
)
from aipass.ai_mail.apps.handlers.email.error_dispatch import dispatch_send_error, on_email_delivered
from aipass.ai_mail.apps.handlers.email.send_args import parse_send_args, resolve_dispatch_target
from aipass.ai_mail.apps.handlers.email.close_ops import batch_close, batch_close_post_ops
from aipass.ai_mail.apps.handlers.email.inbox_resolve import resolve_inbox_target

try:
    from aipass.ai_mail.apps.handlers.central_writer import update_central
except ImportError as e:
    logger.warning("[email] central_writer import unavailable: %s", e)
    update_central = None


def _delivery_callback(branch_path, new_count, opened_count, total):
    """Post-delivery callback: delegates to error_dispatch handler."""
    on_email_delivered(
        branch_path,
        new_count,
        opened_count,
        total,
        push_dashboard_fn=push_dashboard_update,
        update_central_fn=update_central,
    )


def _resolve_branch_path() -> Path:
    """Resolve the branch path for inbox operations.

    Tries get_current_user() first (detects caller's branch).
    Falls back to this module's own branch path when caller detection fails
    (e.g., user calling from terminal outside any branch directory).
    """
    try:
        return Path(get_current_user()["mailbox_path"]).parent
    except RuntimeError as e:
        logger.warning("[email] caller detection failed, using own branch: %s", e)
        return _AI_MAIL_DIR


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
  ai_mail inbox | view <id> | reply <id> "msg" | close <id> | sent | contacts

FLAGS:
  --dispatch        Mark as dispatch task (adds dispatch header)
  --reply-to        Redirect replies to a different branch
  --no-memory-save  Skip memory update requirement in dispatch header

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
    valid = ["send", "email", "inbox", "view", "close", "reply", "sent", "contacts", "read", "register"]
    if command not in valid:
        return False
    if args and args[0] in ["--help", "-h", "help"]:
        print_help()
        return True

    dispatch = {
        "send": handle_send,
        "email": handle_send,
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


def handle_send(args: List[str]) -> bool:
    """Orchestrate email sending workflow."""
    json_handler.log_operation("send_email_initiated", {"args_count": len(args)})
    parsed = parse_send_args(args)

    if parsed["mode"] == "error":
        error(parsed["error"])
        console.print('   Multiple: send @branch1 @branch2 "Subject" "Message"')
        return False

    if parsed["mode"] == "interactive":
        return _send_interactive()

    # Direct send
    recipients = parsed["recipients"]
    from_branch = parsed.get("from_branch")
    if len(recipients) == 1:
        target = resolve_dispatch_target(recipients[0], parsed["auto_execute"], _get_branch_info_fn())
        return _send_direct(
            recipients[0],
            parsed["subject"],
            parsed["message"],
            parsed["auto_execute"],
            parsed["reply_to"],
            target,
            parsed["no_memory_save"],
            from_branch=from_branch,
        )

    console.print(f"\n[bold]Group send to {len(recipients)} recipients...[/bold]")
    ok = 0
    for r in recipients:
        target = resolve_dispatch_target(r, parsed["auto_execute"], _get_branch_info_fn())
        if _send_direct(
            r,
            parsed["subject"],
            parsed["message"],
            parsed["auto_execute"],
            parsed["reply_to"],
            target,
            parsed["no_memory_save"],
            from_branch=from_branch,
        ):
            ok += 1
    console.print(f"\nGroup send complete: {ok}/{len(recipients)} delivered")
    return ok > 0


def _get_branch_info_fn():
    """Return branch info lookup fn for dispatch target resolution, or None."""
    try:
        from aipass.ai_mail.apps.handlers.users.branch_detection import get_branch_info_from_registry

        return get_branch_info_from_registry
    except ImportError as e:
        logger.warning("[email] branch_detection import unavailable: %s", e)
        return None


def _send_interactive() -> bool:
    """Interactive email sending with prompts."""
    branches = get_all_branches()
    console.print("\nAI_Mail - Send Email\n" + "=" * 50)
    console.print("\nSelect recipient:")
    for i, b in enumerate(branches, 1):
        console.print(f"  {i}. {b['name']} ({b['email']})")
    console.print(f"  {len(branches) + 1}. ALL BRANCHES (broadcast)")
    console.print("Message (press Ctrl+D when done, Ctrl+C to cancel):")

    result = collect_interactive_input(branches)
    if result is None:
        console.print("\nCancelled")
        return False

    console.print("\n" + "=" * 50)
    console.print(f"To: {result['to']}\nSubject: {result['subject']}\nMessage:\n{result['message']}")
    console.print("=" * 50)
    return _send_direct(result["to"], result["subject"], result["message"])


def _send_direct(
    to_branch,
    subject,
    message,
    auto_execute=False,
    reply_to=None,
    dispatched_to=None,
    no_memory_save=False,
    from_branch=None,
) -> bool:
    """Direct email send - thin wrapper over send handlers."""
    try:
        user_info = resolve_sender_info(from_branch, _REPO_ROOT, _AI_MAIL_DIR, get_branch_by_email, get_current_user)
        if auto_execute:
            message = prepend_dispatch_header(message, no_memory_save=no_memory_save)

        if to_branch.lower() in ["all", "@all"]:
            return _send_broadcast(subject, message, user_info, auto_execute, no_memory_save, reply_to, dispatched_to)

        success, error_msg = send_to_single(
            to_branch,
            subject,
            message,
            user_info,
            auto_execute,
            no_memory_save,
            reply_to,
            dispatched_to,
            create_email_file,
            load_email_file,
            deliver_email_to_branch,
            _delivery_callback,
            json_handler.log_operation,
            update_central,
        )

        if success:
            label = "\\[dispatch: queued for daemon]" if auto_execute else ""
            console.print(f"[green]Email sent to {to_branch} {label}[/green]")
            if auto_execute:
                _fire_dispatch_trigger(to_branch, subject)
            return True
        else:
            error(f"Failed to deliver: {error_msg}")
            dispatch_send_error(to_branch, subject, error_msg or "", deliver_email_to_branch)
            return False
    except BrokenPipeError:
        logger.info("[email] Send: broken pipe (stdout closed early)")
        return True
    except Exception as e:
        logger.error(f"[email] Send failed: {e}")
        error(f"Error: {e}")
        dispatch_send_error(to_branch, subject, str(e), deliver_email_to_branch)
        return False


def _fire_dispatch_trigger(to_branch: str, subject: str) -> None:
    """Fire email_dispatched trigger event if auto_execute enabled."""
    try:
        trigger.fire("email_dispatched", to=to_branch, subject=subject)
    except Exception as e:
        logger.warning("[email] trigger fire for email_dispatched failed: %s", e)


def _send_broadcast(subject, message, user_info, auto_execute, no_memory_save, reply_to, dispatched_to) -> bool:
    """Broadcast send to all branches - display wrapper."""
    branches = get_all_branches()
    console.print(f"\nBroadcasting to {len(branches)} branches...")
    ok, success_count, total, results = send_to_broadcast(
        subject,
        message,
        user_info,
        auto_execute,
        no_memory_save,
        reply_to,
        dispatched_to,
        branches,
        create_email_file,
        load_email_file,
        deliver_email_to_branch,
        _delivery_callback,
        json_handler.log_operation,
        update_central,
    )
    if isinstance(results, str) or results is None:
        error("Failed to load email file for broadcast")
        return False
    for name, ok, err in results:  # type: ignore[union-attr]
        if ok:
            console.print(f"  [green]OK[/green] {name}")
        else:
            error(f"FAIL {name} ({err})")
    console.print(f"\nBroadcast complete: {success_count}/{total} delivered")
    return ok


def handle_inbox(args: List[str]) -> bool:
    """Orchestrate inbox viewing."""
    json_handler.log_operation("inbox_viewed")
    try:
        first_arg = args[0] if args else None

        def _get_user_with_fallback():
            try:
                return get_current_user()
            except RuntimeError as e:
                logger.warning("[email] caller detection failed for inbox, using own branch: %s", e)
                return {
                    "mailbox_path": str(_AI_MAIL_DIR / ".ai_mail.local"),
                    "display_name": "AI_MAIL",
                }

        ok, info = resolve_inbox_target(first_arg, _REPO_ROOT, get_branch_by_email, _get_user_with_fallback)
        if not ok:
            error(info["error"])
            return False

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

        display = list(reversed(messages))[:20]
        console.print(f"\nInbox{label}\n" + "=" * 70)
        for i, msg in enumerate(display, 1):
            console.print(format_email_list_item(i, msg, show_unread=True))
        console.print("\n" + "=" * 70)
        console.print(f"Showing {len(display)} of {len(messages)} messages")
        return True
    except BrokenPipeError as e:
        logger.warning("[email] inbox view broken pipe: %s", e)
        return True
    except Exception as e:
        logger.error(f"[email] Inbox view failed: {e}")
        error(f"Error: {e}")
        return False


def handle_view(args: List[str]) -> bool:
    """View email content and mark as opened."""
    json_handler.log_operation("view_email_initiated", {"args": args})
    if not args:
        error("Usage: drone @ai_mail view <message_id> | drone @ai_mail view latest")
        return True
    try:
        branch_path = _resolve_branch_path()
        message_id = args[0]

        # Handle "latest" shortcut — get the most recent message ID
        if message_id.lower() == "latest":
            inbox_file = branch_path / ".ai_mail.local" / "inbox.json"
            inbox_data = load_inbox(inbox_file)
            if not inbox_data or not inbox_data.get("messages"):
                error("Inbox is empty")
                return True
            # Get the most recent message (last in the list)
            message_id = inbox_data["messages"][-1].get("id")
            if not message_id:
                error("Could not find latest message")
                return True

        success, message, email_data = mark_as_opened(branch_path, message_id)
        if not success or email_data is None:
            error(message)
            return True
        header = format_email_header(email_data)
        console.print(f"\n{header}")
        console.print(f"\n{email_data.get('message', '')}\n{'=' * 70}")
        console.print(f"[dim]Status: opened | ID: {args[0]}[/dim]")
        console.print(f'[dim]To reply: drone @ai_mail reply {args[0]} "your message"[/dim]')
        console.print(f"[dim]To close: drone @ai_mail close {args[0]}[/dim]")
        json_handler.log_operation("email_viewed", {"message_id": args[0]})
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
                console.print(f"[green]{message}[/green]")
                json_handler.log_operation("email_closed_all", {"count": count})
            else:
                error(message)
            return True

        results, closed, failed = batch_close(branch_path, args, mark_as_closed_and_archive)
        for msg_id, success, message in results:
            if success:
                console.print(f"[green]{message}[/green]")
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
            batch_close_post_ops(branch_path, push_dashboard_update, update_central, run_purge)
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
        success, message, reply_id = send_reply(branch_path, original, args[1])
        if success:
            console.print(f"[green]{message}[/green]")
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
        files = sorted(sent_folder.glob("*.json"), reverse=True)[:20]
        if not files:
            console.print("No sent messages")
            return True
        console.print("\nSent Messages\n" + "=" * 70)
        for i, f in enumerate(files, 1):
            data = load_email_file(f)
            if data:
                console.print(format_email_list_item(i, data, show_unread=False))
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
    console.print("    - inbox_cleanup.py (mark_read_and_archive — mark email read and archive)")
    console.print("    - inbox_cleanup.py (mark_all_read_and_archive — mark all emails read and archive)")
    console.print("    - inbox_cleanup.py (mark_as_opened — mark email as opened)")
    console.print("    - inbox_cleanup.py (mark_as_closed_and_archive — close and archive email)")
    console.print("    - inbox_resolve.py (resolve_inbox_target — resolve inbox target from args)")
    console.print("    - close_ops.py (batch_close — close multiple emails in batch)")
    console.print("    - close_ops.py (batch_close_post_ops — post-close cleanup operations)")
    console.print("    - reply.py (get_email_by_id — retrieve email by message ID)")
    console.print("    - reply.py (send_reply — send reply to an email)")
    console.print("    - header.py (prepend_dispatch_header — prepend dispatch header to message)")
    console.print("    - dashboard_sync.py (push_dashboard_update — push email stats to dashboard)")
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
