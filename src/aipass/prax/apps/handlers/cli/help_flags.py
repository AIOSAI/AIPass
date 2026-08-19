# =================== AIPass ====================
# Name: help_flags.py
# Description: Help-Flag Detection Handler
# Version: 0.1.0
# Created: 2026-08-13
# Modified: 2026-08-13
# =============================================

"""
Help-Flag Detection Handler

Single source of truth for "did the caller ask for help?" across every prax
module's command routing.

Purpose:
    Modules read help flags at args[0] only, so a flag later in the line was
    discarded and the subcommand ran instead. prax's standalone `__main__`
    paths screened `--help` but not `-h`, and `-h` survives a `--`-prefix
    filter because it carries a single dash. Run as a file, not through drone —
    the router was never the vulnerable path:

        modules/log_audit.py enforce -h   -> TRUNCATED THE LOGS
        modules/monitor.py   run -h       -> STARTED A MONITOR

    A question must never be executed as an instruction. Reported by @seedgo
    (help_flag_safety, 2026-08-13); prax's own `dashboard.py` was the clean
    reference that distinguished a real fix from a half fix.

Independence:
    Pure argument inspection — no I/O, no state, no branch imports.
"""

from typing import Sequence

# Dashed forms are unambiguous anywhere on the line.
HELP_FLAGS_DASHED = ("--help", "-h")

# The bare word is a subcommand name, so it only reads as help in the
# subcommand slot — `monitor run help` names a branch, and a grep pattern or
# log filename containing "help" is legitimate free text.
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

    A dashed flag counts wherever it appears, so `enforce --help` and
    `run seedgo -h` both mean "describe this, do not do it". The bare word
    `help` counts only in the first slot unless the caller opts in, because
    prax modules take free text — branch names, log filenames, grep patterns —
    where "help" is content rather than a request.

    Matching is exact: `--help-me` and `-hx` are not help flags.

    Args:
        args: Argument tokens after the command name
        allow_bare_word: Treat a bare `help` in any slot as a help request.
            Safe only for modules whose subcommands take no free text.

    Returns:
        True if help was requested
    """
    if not args:
        return False

    if is_help_flag(args[0]):
        return True

    tail = HELP_FLAGS if allow_bare_word else HELP_FLAGS_DASHED
    return any(token in tail for token in args[1:])
