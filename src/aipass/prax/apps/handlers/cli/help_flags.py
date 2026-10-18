# =================== AIPass ====================
# Name: help_flags.py
# Description: Help-Flag Detection Handler
# Version: 0.1.0
# Created: 2026-08-13
# Modified: 2026-10-17
# =============================================

"""
Help-Flag Detection Handler

Reference: docs/architecture.md
"""

from typing import Sequence

HELP_FLAGS_DASHED = ("--help", "-h")

# Bare `help` is help only in the subcommand slot: later it is free text (a branch, a grep).
HELP_FLAGS = HELP_FLAGS_DASHED + ("help",)


def is_help_flag(token: str) -> bool:
    """Report whether a single token is a help flag in any form."""
    return token in HELP_FLAGS


def wants_help(args: Sequence[str], allow_bare_word: bool = False) -> bool:
    """Report whether help was requested in an argument list."""
    if not args:
        return False

    if is_help_flag(args[0]):
        return True

    tail = HELP_FLAGS if allow_bare_word else HELP_FLAGS_DASHED
    return any(token in tail for token in args[1:])
