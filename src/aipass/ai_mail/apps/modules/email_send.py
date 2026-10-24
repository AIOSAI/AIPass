# =================== AIPass ====================
# Name: email_send.py
# Description: Email Send Orchestration (extracted from email.py)
# Version: 1.3.0
# Created: 2026-04-22
# Modified: 2026-10-23
# =============================================

"""
Email Send Orchestration

Direct, interactive and broadcast send, plus the dispatch trigger.
"""

import os
import sys
from pathlib import Path
from typing import List

from aipass.prax import logger
from aipass.cli.apps.modules import console, error
from aipass.trigger.apps.modules.core import trigger

from aipass.ai_mail.apps.handlers.cli.help_flags import wants_help
from aipass.ai_mail.apps.handlers.email.delivery import deliver_email_to_branch
from aipass.ai_mail.apps.handlers.email.create import create_email_file, load_email_file
from aipass.ai_mail.apps.handlers.email.header import prepend_dispatch_header
from aipass.ai_mail.apps.handlers.json import json_handler
from aipass.ai_mail.apps.handlers.registry.read import (
    get_all_branches,
    get_branch_by_email,
    get_resident_branches,
)
from aipass.ai_mail.apps.handlers.users import verified_caller
from aipass.ai_mail.apps.handlers.users.user import get_current_user
from aipass.ai_mail.apps.handlers.email.send import (
    resolve_sender_info,
    send_to_broadcast,
    send_to_single,
    collect_interactive_input,
)
from aipass.ai_mail.apps.handlers.email.error_dispatch import dispatch_send_error, on_email_delivered
from aipass.ai_mail.apps.handlers.email.send_args import parse_send_args, resolve_dispatch_target
from aipass.ai_mail.apps.handlers.paths import find_repo_root

if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8", errors="replace")

_AI_MAIL_DIR = Path(__file__).resolve().parents[2]
_REPO_ROOT = find_repo_root()

try:
    from aipass.ai_mail.apps.handlers.central_writer import update_central
except ImportError as e:
    logger.warning("[email_send] central_writer import unavailable: %s", e)
    update_central = None


def _delivery_callback(branch_path, new_count, opened_count, total):
    """Post-delivery callback: delegates to error_dispatch handler."""
    on_email_delivered(update_central_fn=update_central)


def _get_branch_info_fn():
    """Return branch info lookup fn for dispatch target resolution, or None."""
    try:
        from aipass.ai_mail.apps.handlers.users.branch_detection import get_branch_info_from_registry

        return get_branch_info_from_registry
    except ImportError as e:
        logger.warning("[email_send] branch_detection import unavailable: %s", e)
        return None


COMMAND = "send"

# The only commands this module answers to; answering any other would re-run sends another module declined.
COMMANDS = ("send", "email")


def handle_command(command: str, args: List[str]) -> bool:
    """Module discovery entry point — routes send/email to handle_send."""
    if command not in COMMANDS:
        return False
    if not args:
        print_introspection()
        return True
    # Whole-sequence: a later --help must not reach handle_send and deliver the mail.
    if wants_help(args):
        print_introspection()
        return True
    return handle_send(args)


def handle_send(args: List[str]) -> bool:
    """Orchestrate email sending workflow.

    True means recognised and run, not "it worked": failures go through error(). False on failure re-runs the send.
    """
    json_handler.log_operation("send_email_initiated", {"args_count": len(args)})
    parsed = parse_send_args(args)

    if parsed["mode"] == "error":
        error(parsed["error"])
        console.print('   Multiple: send @branch1 @branch2 "Subject" "Message"')
        return True

    if parsed["mode"] == "interactive":
        # A cancelled or failed interactive send is still a handled command.
        _send_interactive()
        return True

    recipients = parsed["recipients"]
    from_branch = parsed.get("from_branch")
    if len(recipients) == 1:
        target = resolve_dispatch_target(recipients[0], parsed["auto_execute"], _get_branch_info_fn())
        _send_direct(
            recipients[0],
            parsed["subject"],
            parsed["message"],
            parsed["auto_execute"],
            parsed["reply_to"],
            target,
            parsed["no_memory_save"],
            from_branch=from_branch,
            upsert_key=parsed.get("upsert_key"),
        )
        return True

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
            upsert_key=parsed.get("upsert_key"),
        ):
            ok += 1
    console.print(f"\nGroup send complete: {ok}/{len(recipients)} delivered")
    return True


def _send_interactive() -> bool:
    """Interactive email sending with prompts."""
    # No terminal: refuse with usage (exit 2) before printing the branch list, which would read as progress.
    if not sys.stdin.isatty():
        error('Interactive send needs a terminal. Use: email @recipient "Subject" "Message"')
        return False

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
    # Echoed user text renders with markup off, so "[/rc]" in a subject cannot break confirmation.
    console.print(
        f"To: {result['to']}\nSubject: {result['subject']}\nMessage:\n{result['message']}",
        markup=False,
    )
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
    upsert_key=None,
    user_info=None,
) -> bool:
    """Direct email send - thin wrapper over send handlers.

    upsert_key rewrites the recipient's open message with that key in place (bumped counter) instead of adding one.
    user_info, when given, is the sender already resolved; from_branch is then not read.
    """
    try:
        if user_info is None:
            user_info = resolve_sender_info(from_branch, _REPO_ROOT, _AI_MAIL_DIR, get_branch_by_email, get_current_user)
        if auto_execute:
            message = prepend_dispatch_header(message, no_memory_save=no_memory_save)

        if to_branch.lower() in ["all", "@all"]:
            # Broadcast has no single message to update: refuse rather than silently drop the key.
            if upsert_key:
                error("--upsert-key is not supported for broadcast (@all) sends")
                return False
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
            upsert_key=upsert_key,
        )

        if success:
            label = "\\[dispatch]" if auto_execute else ""
            if upsert_key:
                label = f"\\[upsert: {upsert_key}]"
            console.print(f"[green]Email sent to {to_branch} {label}[/green]")
            # An upsert may have landed on an existing message; do not wake work off a repeat.
            if auto_execute and not upsert_key:
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


def resolve_broadcast_targets() -> list:
    """Who @all reaches: the fleet, plus the residents for a verified admin.

    Widening rides the five-leg admin check and fails closed (a raising verifier widens nothing).
    Residents already in the core registry are not added twice.
    """
    branches = get_all_branches()
    try:
        if not verified_caller.is_verified_admin_caller():
            return branches
    except Exception as e:
        logger.warning("[email_send] admin verification failed, broadcast stays fleet-only: %s", e)
        return branches

    known = {b.get("email", "").lower() for b in branches}
    for email, path in get_resident_branches().items():
        if email.lower() in known:
            continue
        known.add(email.lower())
        branches.append({"email": email, "path": path, "name": email.lstrip("@").upper()})
    return branches


def _send_broadcast(subject, message, user_info, auto_execute, no_memory_save, reply_to, dispatched_to) -> bool:
    """Broadcast send to all branches - display wrapper."""
    branches = resolve_broadcast_targets()
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
    console.print()
    console.print("[bold cyan]email_send Module[/bold cyan]")
    console.print("[dim]Send orchestration — direct, interactive, and broadcast email delivery.[/dim]")
    console.print()
    console.print("[yellow]Functions provided:[/yellow]")
    console.print("  - [cyan]handle_send[/cyan][dim](args) -> bool[/dim]")
    console.print("  - [cyan]_send_direct[/cyan][dim](...) -> bool[/dim]")
    console.print("  - [cyan]_send_interactive[/cyan][dim]() -> bool[/dim]")
    console.print("  - [cyan]_send_broadcast[/cyan][dim](...) -> bool[/dim]")
    console.print("  - [cyan]_fire_dispatch_trigger[/cyan][dim](to_branch, subject) -> None[/dim]")
    console.print("  - [cyan]_delivery_callback[/cyan][dim](branch_path, new_count, opened_count, total)[/dim]")
    console.print()


if __name__ == "__main__":
    print_introspection()
