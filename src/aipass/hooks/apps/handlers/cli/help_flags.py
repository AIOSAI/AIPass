# =================== AIPass ====================
# Name: help_flags.py
# Version: 1.0.0
# Description: Help-Flag Detection Handler — did the caller ask, or instruct?
# Branch: hooks
# Layer: apps/handlers/cli
# Created: 2026-08-13
# Modified: 2026-08-13
# =============================================

"""
Help-Flag Detection Handler

Single source of truth for "did the caller ask for help?" across every
hooks module's command routing.

Purpose:
    Modules read help flags at args[0] only. A flag anywhere later in the
    line was silently discarded and the subcommand ran instead:

        drone @hooks dismiss <alert-id> --help   -> dismissed the alert
        drone @hooks test --verbose --help       -> fired every hook
        drone @hooks sessions reclaim --help     -> stopped live sessions,
                                                    filtered on "-help"

    A question must never be executed as an instruction.

Independence:
    Pure argument inspection — no I/O, no imports beyond typing. Nothing
    here can block, log, or touch disk, so any module can gate on it.
"""

from typing import Sequence

# Dashed forms are unambiguous anywhere on the line.
HELP_FLAGS_DASHED = ("--help", "-h")

# The bare word is also a subcommand name, so it only reads as help in the
# subcommand slot — a later `help` may be someone's alert id or branch name.
HELP_FLAGS = HELP_FLAGS_DASHED + ("help",)


# =============================================================================
# FLAG DETECTION
# =============================================================================


def is_help_flag(token: str) -> bool:
    """
    Report whether a single token is a help flag in any form.

    Args:
        token: One command-line token

    Returns:
        True if the token asks for help
    """
    return token in HELP_FLAGS


def wants_help(args: Sequence[str], allow_bare_word: bool = False) -> bool:
    """
    Report whether help was requested in an argument list.

    A dashed flag counts wherever it appears, so `reclaim --help` and
    `test --verbose --help` both mean "describe this, do not do it". The
    bare word `help` counts only in the first slot unless the caller opts
    in, because modules that take free text legitimately receive it as
    content.

    Args:
        args: Argument tokens after the command name
        allow_bare_word: Treat a bare `help` in any slot as a help request.
            Safe for modules whose subcommands take no free-text arguments.

    Returns:
        True if help was requested
    """
    if not args:
        return False

    if is_help_flag(args[0]):
        return True

    tail = HELP_FLAGS if allow_bare_word else HELP_FLAGS_DASHED
    return any(token in tail for token in args[1:])
