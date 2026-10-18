# =================== AIPass ====================
# Name: help_flags.py
# Version: 1.0.0
# Description: Help-Flag Detection Handler — did the caller ask, or instruct?
# Branch: hooks
# Layer: apps/handlers/cli
# Created: 2026-08-13
# Modified: 2026-10-17
# =============================================

"""
Help-Flag Detection Handler
"""

from typing import Sequence

# Dashed forms count anywhere: a question must never be executed as an instruction.
HELP_FLAGS_DASHED = ("--help", "-h")

# Bare `help` reads as help only in the subcommand slot: later it may be an alert id or branch.
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
