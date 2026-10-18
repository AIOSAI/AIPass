# =================== AIPass ====================
# Name: confirmation.py
# Description: Plan Confirmation Handler
# Version: 0.5.0
# Created: 2025-11-15
# Modified: 2026-10-17
# =============================================

"""Plan Confirmation Handler"""

import sys
from typing import Callable, Optional

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.flow.apps.handlers.json import json_handler

from aipass.flow.apps.handlers.repo_root import module_file

_PKG_ROOT = module_file(__file__).parents[4]


def confirm_plan_deletion(
    plan_key: str,
    ask: Callable[[str], str] = input,
    interactive: Optional[Callable[[], bool]] = None,
) -> Optional[bool]:
    """Prompt user to confirm plan deletion

    Without a TTY it auto-confirms, for autonomous workflows. ask/interactive are test seams.
    Returns None on EOF before an answer: never a yes, the caller treats it as cancelled.
    """
    is_tty = interactive() if interactive is not None else sys.stdin.isatty()
    if not is_tty:
        json_handler.log_operation("plan_deletion_confirmed", {"plan_key": plan_key, "method": "auto_non_interactive"})
        return True

    try:
        response = ask(f"Close FPLAN-{plan_key}? (yes/no): ").strip().lower()
        return response in ["yes", "y"]
    except EOFError as exc:
        logger.warning("[confirmation] Input ended before an answer for plan %s, not closing: %r", plan_key, exc)
        return None
