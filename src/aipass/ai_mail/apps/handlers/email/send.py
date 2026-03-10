# =================== AIPass ====================
# Name: send.py
# Description: Email Send Handler
# Version: 1.0.0
# Created: 2026-03-08
# Modified: 2026-03-08
# =============================================

"""
Email Send Handler

Core send logic for email delivery workflows.
Handles sender resolution, email creation, and delivery orchestration.
Independent handler - no module or display dependencies.
"""

from pathlib import Path
from typing import Optional, Tuple, List, Dict, Any

from aipass.prax import logger
# logger imported from aipass.prax


def resolve_sender_info(
    from_branch: Optional[str],
    repo_root: Path,
    ai_mail_dir: Path,
    get_branch_by_email_fn,
    get_current_user_fn,
) -> Dict[str, Any]:
    """
    Resolve sender user_info from explicit branch or PWD detection.

    Args:
        from_branch: Optional explicit sender branch (e.g., '@trigger').
        repo_root: Repository root path.
        ai_mail_dir: AI_Mail module directory.
        get_branch_by_email_fn: Callable to look up branch by email.
        get_current_user_fn: Callable to detect current user from PWD.

    Returns:
        Dict with email_address, display_name, mailbox_path, timestamp_format.
    """
    if from_branch:
        email_addr = f"@{from_branch.lstrip('@').lower()}"
        branch_info = get_branch_by_email_fn(email_addr)
        if branch_info:
            branch_path = Path(branch_info["path"])
            if not branch_path.is_absolute():
                branch_path = (repo_root / branch_path).resolve()
            return {
                "email_address": email_addr,
                "display_name": branch_info["name"],
                "mailbox_path": str(branch_path / ".ai_mail.local"),
                "timestamp_format": "%Y-%m-%d %H:%M:%S"
            }
        else:
            branch_name = from_branch.lstrip('@').upper()
            return {
                "email_address": email_addr,
                "display_name": branch_name,
                "mailbox_path": str(ai_mail_dir.parent / from_branch.lstrip('@').lower() / ".ai_mail.local"),
                "timestamp_format": "%Y-%m-%d %H:%M:%S"
            }
    else:
        return get_current_user_fn()


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
    on_delivered_callback,
    log_operation_fn,
    update_central_fn,
) -> Tuple[bool, int, int, Optional[str]]:
    """
    Execute broadcast send to all branches.

    Returns:
        Tuple of (success, success_count, total_count, error_msg).
        error_msg is set if the email file could not be loaded.
    """
    email_file = create_email_file_fn("all", subject, message, user_info, reply_to=reply_to, dispatched_to=dispatched_to)
    email_data = load_email_file_fn(email_file)

    if email_data is None:
        log_operation_fn("broadcast_failed", {"error": "Email file could not be loaded"})
        return False, 0, len(branches), "Email file could not be loaded"

    results = []  # List of (branch_name, success, error_msg)
    for branch in branches:
        delivery_data = email_data.copy()
        delivery_data['to'] = branch['email']
        delivery_data['auto_execute'] = auto_execute
        if no_memory_save:
            delivery_data['no_memory_save'] = True

        success, error_msg = deliver_email_to_branch_fn(branch['email'], delivery_data, on_delivered=on_delivered_callback)
        results.append((branch.get('name', branch['email']), success, error_msg))

    success_count = sum(1 for _, s, _ in results if s)
    log_operation_fn("broadcast_sent", {"recipients": len(branches), "successful": success_count})

    # Fire trigger event (best-effort)
    try:
        from aipass.trigger.apps.modules.core import trigger
        trigger.fire('email_broadcast_sent', recipients=len(branches), successful=success_count, subject=subject)
    except ImportError:
        pass

    # Update central (best-effort)
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
) -> Tuple[bool, Optional[str]]:
    """
    Execute single-recipient email send.

    Returns:
        Tuple of (success, error_msg). error_msg is None on success.
    """
    email_file = create_email_file_fn(to_branch, subject, message, user_info, reply_to=reply_to, dispatched_to=dispatched_to)
    email_data = load_email_file_fn(email_file)

    if email_data is None:
        log_operation_fn("email_failed", {"to": to_branch, "error": "Email file could not be loaded"})
        return False, "Email file could not be loaded"

    email_data['auto_execute'] = auto_execute
    if dispatched_to:
        email_data['dispatched_to'] = dispatched_to
    if no_memory_save:
        email_data['no_memory_save'] = True

    success, error_msg = deliver_email_to_branch_fn(to_branch, email_data, on_delivered=on_delivered_callback)

    if success:
        log_operation_fn("email_sent", {"to": to_branch, "subject": subject, "auto_execute": auto_execute})

        # Fire trigger event (best-effort)
        try:
            from aipass.trigger.apps.modules.core import trigger
            trigger.fire('email_sent', to=to_branch, subject=subject, auto_execute=auto_execute)
        except ImportError:
            pass

        # Update central (best-effort)
        try:
            if update_central_fn:
                update_central_fn()
        except Exception as e:
            logger.warning("[send] update_central_fn failed after send to %s: %s", to_branch, e)

        return True, None
    else:
        log_operation_fn("email_failed", {"to": to_branch, "error": error_msg})
        return False, error_msg


def collect_interactive_input(branches: List[Dict[str, Any]]) -> Optional[Dict[str, str]]:
    """
    Collect send parameters from interactive user input.

    Args:
        branches: List of available branch dicts with 'name' and 'email' keys.

    Returns:
        Dict with 'to', 'subject', 'message' keys, or None if cancelled.
    """
    try:
        selection = input(f"\nPick (1-{len(branches) + 1}): ").strip()
        idx = int(selection) - 1

        if idx == len(branches):
            selected_email = "all"
        elif idx < 0 or idx >= len(branches):
            return None
        else:
            selected_email = branches[idx]["email"]
    except (ValueError, KeyboardInterrupt, EOFError):
        return None

    try:
        subject = input("Subject: ").strip()
        if not subject:
            return None
    except (KeyboardInterrupt, EOFError):
        return None

    try:
        message_lines = []
        while True:
            try:
                line = input()
                message_lines.append(line)
            except EOFError:
                break
        message = "\n".join(message_lines).strip()
        if not message:
            return None
    except KeyboardInterrupt:
        return None

    try:
        confirm = input("\nSend? (y/n): ").strip().lower()
        if confirm != 'y':
            return None
    except (KeyboardInterrupt, EOFError):
        return None

    return {
        "to": selected_email,
        "subject": subject,
        "message": message,
    }
