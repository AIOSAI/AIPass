# =================== AIPass ====================
# Name: help_flags.py
# Description: Whole-sequence help-flag detection for ai_mail's CLI modules
# Version: 1.0.0
# Created: 2026-08-13
# Modified: 2026-10-17
# =============================================

"""Help-flag detection — a help flag anywhere means explain, never execute.

Dashed flags match exactly at any position (a quoted body "run --help" is one token, so mail stays intact);
bare ``help`` counts only at position 0, because a subject or body can legitimately be the word "help".
"""

from typing import Sequence

HELP_FLAGS_DASHED = ("--help", "-h")

HELP_BARE_WORD = "help"


def wants_help(args: Sequence[str], allow_bare_word: bool = True) -> bool:
    """Report whether help was requested anywhere in an argument list."""
    if not args:
        return False
    if any(token in HELP_FLAGS_DASHED for token in args):
        return True
    return bool(allow_bare_word and args[0] == HELP_BARE_WORD)
