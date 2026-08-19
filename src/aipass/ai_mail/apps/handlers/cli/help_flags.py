# =================== AIPass ====================
# Name: help_flags.py
# Description: Whole-sequence help-flag detection for ai_mail's CLI modules
# Version: 1.0.0
# Created: 2026-08-13
# Modified: 2026-08-13
# =============================================

"""Help-flag detection — a help flag anywhere means explain, never execute.

All three ai_mail modules gated help at ``args[0]`` only, so a flag one
position later was discarded and the command ran instead. On a messaging
branch the worst case is not a wasted keystroke:
``drone @ai_mail dispatch @target "Subject" "Body" --help`` reached
``_orchestrate_dispatch_send`` and would have **sent the mail and woken the
branch** it was asked to describe. Same class as @drone's ``rm`` shape, where
a trailing ``--help`` deleted the real target first (seedgo standard
``help_flag_safety``, DPLAN-0291 rule E).

Two token classes, deliberately treated differently:

``--help`` / ``-h``
    Unambiguous wherever they appear. Scanned across the whole sequence by
    **exact** match, which is what keeps real mail intact: a body reading
    "run --help for usage" arrives as one quoted argument and is not that
    token. A body that is *exactly* ``--help`` is nonsense input, and there
    the ruling is explain over execute.

``help``
    A legitimate operand. On this branch a subject or body can plausibly be
    the single word "help" — it is a message, not a typo — so the bare word
    only reads as a request in the subcommand slot, position 0. None of the
    three modules owns a genuine ``help`` verb, so that slot is free.

Independence: pure argument inspection. No I/O and no imports beyond typing,
so it can be called at the top of any ``handle_command`` before anything else
runs.
"""

from typing import Sequence

# Dashed forms are unambiguous at any position.
HELP_FLAGS_DASHED = ("--help", "-h")

# The bare word only reads as help in the subcommand slot.
HELP_BARE_WORD = "help"


# =============================================================================
# FLAG DETECTION
# =============================================================================


def wants_help(args: Sequence[str], allow_bare_word: bool = True) -> bool:
    """Report whether help was requested anywhere in an argument list.

    A dashed flag counts wherever it appears, so ``@target "Subject" --help``
    and ``wake @target -h`` both mean "describe this, do not do it". The bare
    word ``help`` counts only at position 0, where it is the subcommand rather
    than message content.

    Args:
        args: The full argument sequence for this command
        allow_bare_word: Whether a leading bare ``help`` counts as a request.
            Set False for a module that owns a genuine ``help`` verb.

    Returns:
        True if the caller asked for help
    """
    if not args:
        return False
    if any(token in HELP_FLAGS_DASHED for token in args):
        return True
    return bool(allow_bare_word and args[0] == HELP_BARE_WORD)
