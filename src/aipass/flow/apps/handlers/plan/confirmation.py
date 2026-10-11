# =================== AIPass ====================
# Name: confirmation.py
# Description: Plan Confirmation Handler
# Version: 0.5.0
# Created: 2025-11-15
# Modified: 2026-10-03
# =============================================

"""
Plan Confirmation Handler

User interaction and confirmation prompts for plan operations.
"""

import sys
from typing import Callable, Optional

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.flow.apps.handlers.json import json_handler

# Infrastructure
from aipass.flow.apps.handlers.repo_root import module_file

_PKG_ROOT = module_file(__file__).parents[4]


def confirm_plan_deletion(
    plan_key: str,
    ask: Callable[[str], str] = input,
    interactive: Optional[Callable[[], bool]] = None,
) -> Optional[bool]:
    """
    Prompt user to confirm plan deletion

    Displays interactive prompt asking user to confirm deletion.
    Accepts "yes" or "y" (case-insensitive) as confirmation.

    In non-interactive environments (no TTY), auto-confirms to support
    autonomous workflows and scripted operations.

    Args:
        plan_key: Normalized plan number (e.g., "0001")
        ask: The prompt call, input by default. A seam: the tests hand in a
            stand-in so no test replaces builtins.input for the whole process.
        interactive: The TTY question, sys.stdin.isatty at call time when
            None. A seam for the same reason: pytest's stdin is never a TTY.

    Returns:
        True if user confirmed deletion or non-interactive environment
        False if user cancelled
        None if input ended (EOF) before any answer. Never a yes: the user
        asked to be asked, so close_plan_impl treats it as cancelled. It
        returned True until leg 5 of fleet green and closed the plan.

    Example:
        >>> if confirm_plan_deletion("0042"):
        ...     # User confirmed, proceed with deletion
        ...     pass
    """
    is_tty = interactive() if interactive is not None else sys.stdin.isatty()
    # Auto-confirm in non-interactive environments (autonomous workflows, CI/CD)
    if not is_tty:
        json_handler.log_operation("plan_deletion_confirmed", {"plan_key": plan_key, "method": "auto_non_interactive"})
        return True

    try:
        response = ask(f"Close FPLAN-{plan_key}? (yes/no): ").strip().lower()
        return response in ["yes", "y"]
    except EOFError as exc:
        logger.warning("[confirmation] Input ended before an answer for plan %s, not closing: %r", plan_key, exc)
        return None
