# =================== AIPass ====================
# Name: send_args.py
# Description: Email Send Argument Parsing Handler
# Version: 1.3.1
# Created: 2026-03-08
# Modified: 2026-11-21
# =============================================

"""
Email Send Argument Parsing Handler
"""

from pathlib import Path
from typing import List, Dict, Optional, Any

from aipass.ai_mail.apps.handlers.json import json_handler
from aipass.ai_mail.apps.handlers.email.mail_kind import MAIL_KINDS


def _flag_error(error: str, **parsed: Any) -> Dict[str, Any]:
    """The refused-parse result: every key present, the flags parsed so far carried over."""
    result: Dict[str, Any] = {
        "auto_execute": False,
        "no_memory_save": False,
        "reply_to": None,
        "from_branch": None,
        "recipients": [],
        "subject": None,
        "message": None,
        "upsert_key": None,
        "kind": None,
        "mode": "error",
        "error": error,
    }
    result.update(parsed)
    return result


def parse_send_args(args: List[str]) -> Dict[str, Any]:
    """Parse send command arguments into structured result."""
    json_handler.log_operation("parse_send_args", {"arg_count": len(args)})
    working_args = list(args)

    auto_execute = "--dispatch" in working_args or "--auto-execute" in working_args
    working_args = [a for a in working_args if a not in ("--dispatch", "--auto-execute")]

    no_memory_save = "--no-memory-save" in working_args
    working_args = [a for a in working_args if a != "--no-memory-save"]

    from_branch = None
    if "--from" in working_args:
        idx = working_args.index("--from")
        if idx + 1 < len(working_args):
            from_branch = working_args[idx + 1]
            working_args = working_args[:idx] + working_args[idx + 2 :]
        else:
            return _flag_error(
                "--from requires a branch address (e.g., --from @spawn)",
                auto_execute=auto_execute,
                no_memory_save=no_memory_save,
            )

    reply_to = None
    if "--reply-to" in working_args:
        idx = working_args.index("--reply-to")
        if idx + 1 < len(working_args):
            reply_to = working_args[idx + 1]
            working_args = working_args[:idx] + working_args[idx + 2 :]
        else:
            return _flag_error(
                "--reply-to requires a branch address (e.g., --reply-to @devpulse)",
                auto_execute=auto_execute,
                no_memory_save=no_memory_save,
                from_branch=from_branch,
            )

    # --upsert-key: a repeat signature updates one message instead of stacking.
    upsert_key = None
    if "--upsert-key" in working_args:
        idx = working_args.index("--upsert-key")
        if idx + 1 < len(working_args):
            upsert_key = working_args[idx + 1]
            working_args = working_args[:idx] + working_args[idx + 2 :]
        else:
            return _flag_error(
                "--upsert-key requires a signature (e.g., --upsert-key trigger:warn:disk)",
                auto_execute=auto_execute,
                no_memory_save=no_memory_save,
                reply_to=reply_to,
                from_branch=from_branch,
            )

    kind = None
    if "--kind" in working_args:
        idx = working_args.index("--kind")
        kind = working_args[idx + 1] if idx + 1 < len(working_args) else None
        if kind not in MAIL_KINDS:
            return _flag_error(
                f"--kind needs one of {', '.join(MAIL_KINDS)} (got {kind!r})",
                auto_execute=auto_execute,
                no_memory_save=no_memory_save,
                reply_to=reply_to,
                from_branch=from_branch,
                upsert_key=upsert_key,
            )
        working_args = working_args[:idx] + working_args[idx + 2 :]

    recipients = []
    rest = []
    for a in working_args:
        if a.startswith("@") and not rest:
            recipients.append(a)
        elif a.startswith("/") and not rest:
            recipients.append(a)
        else:
            rest.append(a)

    refusal = None
    if recipients and len(rest) >= 2:
        usage = 'Usage: send @recipient "subject" "message"'
        # Known flags are gone by now: a flag in the subject slot is a typo, never a subject.
        if rest[0].startswith("--"):
            refusal = f"Unknown flag {rest[0]!r} — {usage}"
        elif not rest[0].strip():
            refusal = f"Empty subject refused — give the mail a subject. {usage}"
    if refusal:
        return _flag_error(
            refusal,
            auto_execute=auto_execute,
            no_memory_save=no_memory_save,
            reply_to=reply_to,
            from_branch=from_branch,
            upsert_key=upsert_key,
            kind=kind,
        )

    if recipients and len(rest) >= 2:
        mode = "direct"
        subject = rest[0]
        message = " ".join(rest[1:])
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
        "upsert_key": upsert_key,
        "kind": kind,
        "mode": mode,
        "error": None if mode != "error" else "Usage: send @recipient [subject] [message]",
    }


def resolve_dispatch_target(
    branch: str,
    auto_execute: bool,
    get_branch_info_fn=None,
) -> Optional[str]:
    """Resolve dispatch target address for a recipient."""
    if not auto_execute:
        return None

    if branch.startswith("/") or branch.startswith("~"):
        name = Path(branch).name.lower()
        if get_branch_info_fn:
            branch_info = get_branch_info_fn(Path(branch))
            if branch_info:
                return branch_info.get("email", f"@{name}")
        return f"@{name}"

    return branch
