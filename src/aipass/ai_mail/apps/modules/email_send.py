# =================== AIPass ====================
# Name: email_send.py
# Description: Email Send Orchestration (extracted from email.py)
# Version: 1.0.0
# Created: 2026-04-22
# Modified: 2026-04-22
# =============================================

"""
Email Send Orchestration

Handles the send/email command workflow: direct send, interactive send,
broadcast, and dispatch trigger. Extracted from email.py to keep modules
under the size threshold.
"""

from pathlib import Path
from typing import List

_AI_MAIL_DIR = Path(__file__).resolve().parents[2]
_REPO_ROOT = _AI_MAIL_DIR.parents[2]

from aipass.prax import logger
from aipass.cli.apps.modules import console, error
from aipass.trigger.apps.modules.core import trigger

from aipass.ai_mail.apps.handlers.email.dashboard_sync import push_dashboard_update
from aipass.ai_mail.apps.handlers.email.delivery import deliver_email_to_branch
from aipass.ai_mail.apps.handlers.email.create import create_email_file, load_email_file
from aipass.ai_mail.apps.handlers.email.header import prepend_dispatch_header
from aipass.ai_mail.apps.handlers.json import json_handler
from aipass.ai_mail.apps.handlers.registry.read import get_all_branches, get_branch_by_email
from aipass.ai_mail.apps.handlers.users.user import get_current_user
from aipass.ai_mail.apps.handlers.email.send import (
    resolve_sender_info,
    send_to_broadcast,
    send_to_single,
    collect_interactive_input,
)
from aipass.ai_mail.apps.handlers.email.error_dispatch import dispatch_send_error, on_email_delivered
from aipass.ai_mail.apps.handlers.email.send_args import parse_send_args, resolve_dispatch_target

try:
    from aipass.ai_mail.apps.handlers.central_writer import update_central
except ImportError as e:
    logger.warning("[email_send] central_writer import unavailable: %s", e)
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


def _get_branch_info_fn():
    """Return branch info lookup fn for dispatch target resolution, or None."""
    try:
        from aipass.ai_mail.apps.handlers.users.branch_detection import get_branch_info_from_registry

        return get_branch_info_from_registry
    except ImportError as e:
        logger.warning("[email_send] branch_detection import unavailable: %s", e)
        return None


COMMAND = "send"


def handle_command(command: str, args: List[str]) -> bool:
    """Module discovery entry point — routes to handle_send."""
    if not args:
        print_introspection()
        return True
    if args[0] in ("--help", "-h", "help"):
        print_introspection()
        return True
    return handle_send(args)


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
        logger.info("[email_send] Send: broken pipe (stdout closed early)")
        return True
    except Exception as e:
        logger.error(f"[email_send] Send failed: {e}")
        error(f"Error: {e}")
        dispatch_send_error(to_branch, subject, str(e), deliver_email_to_branch)
        return False


def _fire_dispatch_trigger(to_branch: str, subject: str) -> None:
    """Fire email_dispatched trigger event if auto_execute enabled."""
    try:
        trigger.fire("email_dispatched", to=to_branch, subject=subject)
    except Exception as e:
        logger.warning("[email_send] trigger fire for email_dispatched failed: %s", e)


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


def print_introspection():
    """Print module introspection for seedgo compliance."""
    console.print("\n" + "=" * 70)
    console.print("EMAIL SEND ORCHESTRATION")
    console.print("=" * 70)
    console.print("\nFunctions provided:")
    console.print("  - handle_send(args) -> bool")
    console.print("  - _send_direct(...) -> bool")
    console.print("  - _send_interactive() -> bool")
    console.print("  - _send_broadcast(...) -> bool")
    console.print("  - _fire_dispatch_trigger(to_branch, subject) -> None")
    console.print("  - _delivery_callback(branch_path, new_count, opened_count, total)")
    console.print()
    console.print("=" * 70 + "\n")


if __name__ == "__main__":
    print_introspection()
