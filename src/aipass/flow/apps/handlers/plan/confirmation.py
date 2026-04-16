# =================== AIPass ====================
# Name: confirmation.py
# Description: Plan Confirmation Handler
# Version: 0.4.0
# Created: 2025-11-15
# Modified: 2025-11-15
# =============================================

"""
Plan Confirmation Handler

User interaction and confirmation prompts for plan operations.
"""

import sys
from pathlib import Path

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.flow.apps.handlers.json import json_handler

# Infrastructure
_PKG_ROOT = Path(__file__).resolve().parents[4]


def confirm_plan_deletion(plan_key: str) -> bool:
    """
    Prompt user to confirm plan deletion

    Displays interactive prompt asking user to confirm deletion.
    Accepts "yes" or "y" (case-insensitive) as confirmation.

    In non-interactive environments (no TTY), auto-confirms to support
    autonomous workflows and scripted operations.

    Args:
        plan_key: Normalized plan number (e.g., "0001")

    Returns:
        True if user confirmed deletion or non-interactive environment
        False if user cancelled

    Example:
        >>> if confirm_plan_deletion("0042"):
        ...     # User confirmed, proceed with deletion
        ...     pass
    """
    # Auto-confirm in non-interactive environments (autonomous workflows, CI/CD)
    if not sys.stdin.isatty():
        json_handler.log_operation("plan_deletion_confirmed", {"plan_key": plan_key, "method": "auto_non_interactive"})
        return True

    try:
        response = input(f"Close FPLAN-{plan_key}? (yes/no): ").strip().lower()
        return response in ["yes", "y"]
    except EOFError:
        # Fallback for edge cases where isatty() returns True but input fails
        logger.warning(f"[confirmation] EOFError reading input for plan {plan_key} deletion, auto-confirming")
        return True
