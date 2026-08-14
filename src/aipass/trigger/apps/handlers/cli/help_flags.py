# =================== AIPass ====================
# Name: help_flags.py
# Description: Whole-sequence help-flag detection for trigger's CLI modules
# Version: 1.0.0
# Created: 2026-08-13
# Modified: 2026-08-13
# =============================================

"""Help-flag detection — a help flag anywhere means explain, never execute.

Every trigger module used to gate help at ``args[0]`` only. A flag one
position later was discarded and the subcommand ran instead, so
``drone @trigger medic mute @branch --help`` would have *muted the branch* it
was asked to describe — 24 hours of silenced error dispatch, with no unmute.
The fleet-wide version of this cost a 17-branch config reset and a real backup
run on 2026-08-13 (seedgo standard ``help_flag_safety``, DPLAN-0291).

Two token classes, deliberately treated differently:

``--help`` / ``-h``
    Unambiguous wherever they appear. Scanned across the whole sequence by
    exact match — exact so that ``fire evt message=--help`` stays a payload.

``help``
    A bare word that is also a legitimate operand. ``errors suppress <id>
    help`` is a suppression reason and ``fire evt message=help`` is event
    data; neither asks for the manual. It therefore only reads as help in the
    subcommand slot, position 0.

Independence: pure argument inspection. No I/O, no imports beyond typing, so
it can be called from any module's ``handle_command`` before anything else
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

    A dashed flag counts wherever it appears, so ``mute @branch --help`` and
    ``list --branch api -h`` both mean "describe this, do not do it". The bare
    word ``help`` counts only at position 0, where it is the subcommand rather
    than an operand.

    Args:
        args: The full argument sequence for this command
        allow_bare_word: Whether a leading bare ``help`` counts as a request

    Returns:
        True if the caller asked for help
    """
    if not args:
        return False
    if any(token in HELP_FLAGS_DASHED for token in args):
        return True
    return bool(allow_bare_word and args[0] == HELP_BARE_WORD)
