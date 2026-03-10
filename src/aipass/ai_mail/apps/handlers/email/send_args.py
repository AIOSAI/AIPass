# =================== AIPass ====================
# Name: send_args.py
# Description: Email Send Argument Parsing Handler
# Version: 1.0.0
# Created: 2026-03-08
# Modified: 2026-03-08
# =============================================

"""
Email Send Argument Parsing Handler

Parses send command arguments into structured data.
Independent handler - no module or display dependencies.
"""

from pathlib import Path
from typing import List, Dict, Optional, Any


def parse_send_args(args: List[str]) -> Dict[str, Any]:
    """
    Parse send command arguments into structured result.

    Args:
        args: Raw argument list from CLI

    Returns:
        Dict with keys:
            auto_execute: bool
            no_memory_save: bool
            reply_to: str | None
            recipients: List[str]
            subject: str | None
            message: str | None
            mode: 'direct' | 'interactive' | 'error'
            error: str | None (set when mode=='error')
    """
    working_args = list(args)

    # Extract --dispatch / --auto-execute
    auto_execute = '--dispatch' in working_args or '--auto-execute' in working_args
    working_args = [a for a in working_args if a not in ('--dispatch', '--auto-execute')]

    # Extract --no-memory-save
    no_memory_save = '--no-memory-save' in working_args
    working_args = [a for a in working_args if a != '--no-memory-save']

    # Extract --from (explicit sender identity override)
    from_branch = None
    if '--from' in working_args:
        idx = working_args.index('--from')
        if idx + 1 < len(working_args):
            from_branch = working_args[idx + 1]
            working_args = working_args[:idx] + working_args[idx + 2:]
        else:
            return {
                "auto_execute": auto_execute,
                "no_memory_save": no_memory_save,
                "reply_to": None,
                "from_branch": None,
                "recipients": [],
                "subject": None,
                "message": None,
                "mode": "error",
                "error": "--from requires a branch address (e.g., --from @spawn)",
            }

    # Extract --reply-to
    reply_to = None
    if '--reply-to' in working_args:
        idx = working_args.index('--reply-to')
        if idx + 1 < len(working_args):
            reply_to = working_args[idx + 1]
            working_args = working_args[:idx] + working_args[idx + 2:]
        else:
            return {
                "auto_execute": auto_execute,
                "no_memory_save": no_memory_save,
                "reply_to": None,
                "from_branch": from_branch,
                "recipients": [],
                "subject": None,
                "message": None,
                "mode": "error",
                "error": "--reply-to requires a branch address (e.g., --reply-to @dev_central)",
            }

    # Separate recipients from subject/message
    recipients = []
    rest = []
    for a in working_args:
        if a.startswith('@') and not rest:
            recipients.append(a)
        elif a.startswith('/') and not rest:
            recipients.append(a)
        else:
            rest.append(a)

    # Determine mode
    if recipients and len(rest) >= 2:
        mode = "direct"
        subject = rest[0]
        message = rest[1]
    elif not recipients and not rest:
        mode = "interactive"
        subject = None
        message = None
    else:
        mode = "error"
        subject = rest[0] if rest else None
        message = rest[1] if len(rest) >= 2 else None

    return {
        "auto_execute": auto_execute,
        "no_memory_save": no_memory_save,
        "reply_to": reply_to,
        "from_branch": from_branch,
        "recipients": recipients,
        "subject": subject,
        "message": message,
        "mode": mode,
        "error": None if mode != "error" else "Usage: send @recipient [subject] [message]",
    }


def resolve_dispatch_target(
    branch: str,
    auto_execute: bool,
    get_branch_info_fn=None,
) -> Optional[str]:
    """
    Resolve dispatch target address for a recipient.

    Args:
        branch: Recipient address (e.g., '@flow' or '/path/to/branch')
        auto_execute: Whether dispatch was requested
        get_branch_info_fn: Callable to look up branch info from registry by path

    Returns:
        Dispatch target address string, or None if no dispatch.
    """
    if not auto_execute:
        return None

    if branch.startswith('/') or branch.startswith('~'):
        if get_branch_info_fn:
            branch_info = get_branch_info_fn(Path(branch))
            if branch_info:
                return branch_info.get("email", f"@{Path(branch).name.lower()}")
        return f"@{Path(branch).name.lower()}"

    return branch
