# =================== AIPass ====================
# Name: send.py
# Description: Email Send Handler
# Version: 1.3.1
# Created: 2026-03-08
# Modified: 2026-10-17
# =============================================

"""
Email Send Handler
"""

import sys
from pathlib import Path
from typing import Optional, Tuple, List, Dict, Any

from aipass.prax import logger
from aipass.ai_mail.apps.handlers.json import json_handler
from aipass.ai_mail.apps.handlers.email.create import mark_sent_record_refused


def _log_resolved_sender(user_info: Dict[str, Any], from_branch: Optional[str], strategy: str) -> Dict[str, Any]:
    """Record WHO the sender resolved to, alongside the input that produced it.

    Logging only the input leaves a misattributed message with no trace of who it became or why.
    """
    json_handler.log_operation(
        "resolved_sender",
        {
            "strategy": strategy,
            "in_from_branch": from_branch,
            "resolved_email": user_info.get("email_address", ""),
            "resolved_name": user_info.get("display_name", ""),
            "mailbox_path": user_info.get("mailbox_path", ""),
        },
    )
    logger.info(
        "[identity] sender resolved %s (%s) via %s -> mailbox %s",
        user_info.get("email_address", "?"),
        user_info.get("display_name", "?"),
        strategy,
        user_info.get("mailbox_path", "?"),
    )
    return user_info


def resolve_sender_info(
    from_branch: Optional[str],
    repo_root: Path,
    ai_mail_dir: Path,
    get_branch_by_email_fn,
    get_current_user_fn,
) -> Dict[str, Any]:
    """Resolve sender user_info from explicit branch or PWD detection."""
    json_handler.log_operation("resolve_sender", {"from_branch": from_branch})
    if from_branch:
        email_addr = f"@{from_branch.lstrip('@').lower()}"
        branch_info = get_branch_by_email_fn(email_addr)
        if branch_info:
            branch_path = Path(branch_info["path"])
            if not branch_path.is_absolute():
                branch_path = (repo_root / branch_path).resolve()
            return _log_resolved_sender(
                {
                    "email_address": email_addr,
                    "display_name": branch_info["name"],
                    "mailbox_path": str(branch_path / ".ai_mail.local"),
                    "timestamp_format": "%Y-%m-%d %H:%M:%S",
                },
                from_branch,
                "explicit_from:registry",
            )
        else:
            branch_name = from_branch.lstrip("@").upper()
            return _log_resolved_sender(
                {
                    "email_address": email_addr,
                    "display_name": branch_name,
                    "mailbox_path": str(ai_mail_dir.parent / from_branch.lstrip("@").lower() / ".ai_mail.local"),
                    "timestamp_format": "%Y-%m-%d %H:%M:%S",
                },
                from_branch,
                "explicit_from:assumed_path",
            )
    else:
        return _log_resolved_sender(get_current_user_fn(), from_branch, "detected_from_caller_env")


def send_to_broadcast(
    subject: str,
    message: str,
    user_info: Dict[str, Any],
    auto_execute: bool,
    no_memory_save: bool,
    reply_to: Optional[str],
    dispatched_to: Optional[str],
    branches: List[Dict[str, Any]],
    create_email_file_fn,
    load_email_file_fn,
    deliver_email_to_branch_fn,
    log_operation_fn,
    update_central_fn,
) -> Tuple[bool, int, int, Any]:
    """Execute broadcast send to all branches.

    No per-recipient on_delivered: update_central rescans every inbox, so N calls blow drone's 60s cap.
    """
    email_file = create_email_file_fn(
        "all", subject, message, user_info, reply_to=reply_to, dispatched_to=dispatched_to
    )
    email_data = load_email_file_fn(email_file)

    if email_data is None:
        log_operation_fn("broadcast_failed", {"error": "Email file could not be loaded"})
        return False, 0, len(branches), "Email file could not be loaded"

    results = []  # List of (branch_name, success, error_msg)
    for branch in branches:
        delivery_data = email_data.copy()
        delivery_data["to"] = branch["email"]
        delivery_data["auto_execute"] = auto_execute
        if no_memory_save:
            delivery_data["no_memory_save"] = True

        success, error_msg = deliver_email_to_branch_fn(branch["email"], delivery_data)
        results.append((branch.get("name", branch["email"]), success, error_msg))

    success_count = sum(1 for _, s, _ in results if s)
    if success_count == 0:
        # The one sent record covers every recipient; left "sent" it claims a delivery that never happened.
        first_error = next((err for _, s, err in results if not s and err), "no recipient accepted delivery")
        mark_sent_record_refused(email_file, first_error)
    log_operation_fn("broadcast_sent", {"recipients": len(branches), "successful": success_count})

    if success_count > 0:
        try:
            from aipass.trigger.apps.modules.core import trigger

            trigger.fire("email_broadcast_sent", recipients=len(branches), successful=success_count, subject=subject)
        except ImportError as e:
            logger.warning("[send] trigger import unavailable for broadcast event: %s", e)

    try:
        if update_central_fn:
            update_central_fn()
    except Exception as e:
        logger.warning("[send] update_central_fn failed after broadcast: %s", e)

    return success_count > 0, success_count, len(branches), results


def send_to_single(
    to_branch: str,
    subject: str,
    message: str,
    user_info: Dict[str, Any],
    auto_execute: bool,
    no_memory_save: bool,
    reply_to: Optional[str],
    dispatched_to: Optional[str],
    create_email_file_fn,
    load_email_file_fn,
    deliver_email_to_branch_fn,
    on_delivered_callback,
    log_operation_fn,
    update_central_fn,
    upsert_key: Optional[str] = None,
) -> Tuple[bool, Optional[str]]:
    """Execute single-recipient email send.

    upsert_key: delivery rewrites this sender's open message with the same key instead of stacking.
    """
    email_file = create_email_file_fn(
        to_branch, subject, message, user_info, reply_to=reply_to, dispatched_to=dispatched_to
    )
    email_data = load_email_file_fn(email_file)

    if email_data is None:
        log_operation_fn("email_failed", {"to": to_branch, "error": "Email file could not be loaded"})
        return False, "Email file could not be loaded"

    email_data["auto_execute"] = auto_execute
    if dispatched_to:
        email_data["dispatched_to"] = dispatched_to
    if no_memory_save:
        email_data["no_memory_save"] = True
    # On email_data, not a kwarg: the delivery function here is injected.
    if upsert_key:
        email_data["upsert_key"] = upsert_key

    success, error_msg = deliver_email_to_branch_fn(to_branch, email_data, on_delivered=on_delivered_callback)

    if success:
        payload = {"to": to_branch, "subject": subject, "auto_execute": auto_execute}
        if email_data.get("upsert_action"):
            payload["upsert_action"] = email_data["upsert_action"]
        log_operation_fn("email_sent", payload)

        try:
            from aipass.trigger.apps.modules.core import trigger

            trigger.fire("email_sent", to=to_branch, subject=subject, auto_execute=auto_execute)
        except ImportError as e:
            logger.warning("[send] trigger import unavailable for send event: %s", e)

        try:
            if update_central_fn:
                update_central_fn()
        except Exception as e:
            logger.warning("[send] update_central_fn failed after send to %s: %s", to_branch, e)

        return True, None
    else:
        # The sent record predates delivery: a refused one must never read as delivered.
        mark_sent_record_refused(email_file, error_msg or "delivery refused")
        log_operation_fn("email_failed", {"to": to_branch, "error": error_msg})
        return False, error_msg


def collect_interactive_input(branches: List[Dict[str, Any]]) -> Optional[Dict[str, str]]:
    """Collect send parameters from interactive user input.

    Returns None if cancelled.
    """
    # Under drone stdin is an open, silent pipe: input() blocks until the 30s timeout, never EOFError.
    if not sys.stdin.isatty():
        logger.warning("[send] interactive send needs a terminal — no TTY on stdin")
        return None

    try:
        selection = input(f"\nPick (1-{len(branches) + 1}): ").strip()
        idx = int(selection) - 1

        if idx == len(branches):
            selected_email = "all"
        elif idx < 0 or idx >= len(branches):
            return None
        else:
            selected_email = branches[idx]["email"]
    except (ValueError, KeyboardInterrupt, EOFError) as e:
        logger.warning("[send] recipient selection cancelled or invalid: %s", e)
        return None

    try:
        subject = input("Subject: ").strip()
        if not subject:
            return None
    except (KeyboardInterrupt, EOFError) as e:
        logger.warning("[send] subject input cancelled: %s", e)
        return None

    try:
        message_lines = []
        while True:
            try:
                line = input()
                message_lines.append(line)
            except EOFError as e:
                logger.warning("[send] message input ended: %s", e)
                break
        message = "\n".join(message_lines).strip()
        if not message:
            return None
    except KeyboardInterrupt as e:
        logger.warning("[send] message input cancelled: %s", e)
        return None

    try:
        confirm = input("\nSend? (y/n): ").strip().lower()
        if confirm != "y":
            return None
    except (KeyboardInterrupt, EOFError) as e:
        logger.warning("[send] confirmation cancelled: %s", e)
        return None

    return {
        "to": selected_email,
        "subject": subject,
        "message": message,
    }
