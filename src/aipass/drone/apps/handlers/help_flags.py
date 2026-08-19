# =================== AIPass ====================
# Name: help_flags.py
# Description: Whole-sequence help detection — a help flag anywhere means explain, never execute
# Version: 1.0.0
# Created: 2026-08-13
# Modified: 2026-08-13
# =============================================

"""Whole-sequence help detection (DPLAN-0291 rule E).

A help flag ANYWHERE in a command means explain, never execute. Every drone
module gated help at one fixed slot — ``command`` or ``args[0]`` — so a flag
typed later was invisible and the verb ran. `drone rm notes.md --help` deleted
notes.md and then tried to delete a file called ``--help``.

One predicate, ten call sites. The gate lived in ten copies of the same two
lines, which is how ten modules drifted into the same bug at once; a rule worth
enforcing in every module is worth defining once (S39 — duplicated precedence
lies, one resolver serves both sites).

Bare ``help`` counts only at position 0, because later positions may be
legitimate values — a path to delete, a branch to look up. Modules that own
``help`` as a real subcommand pass ``bare_help=False``; for them the word is a
value in every position, dashed forms still catch.
"""

from __future__ import annotations

from typing import Sequence

# The two spellings unambiguous ANYWHERE on a command line. A user typing
# either has asked a question, wherever it lands.
DASHED_HELP_TOKENS = ("--help", "-h")

# Legitimate content in any later slot, so it is honoured at position 0 only.
BARE_HELP_TOKEN = "help"


def wants_help(
    command: str | None,
    args: Sequence[str] | None = None,
    *,
    bare_help: bool = True,
) -> bool:
    """Whether this invocation is asking for help rather than asking to act.

    Args:
        command: The subcommand slot, or None.
        args: Everything after it.
        bare_help: Whether a bare ``help`` at position 0 requests help. False
            for modules where ``help`` is itself a verb (discovery), so their
            own subcommand keeps working.

    Returns:
        True if help should be printed and nothing else should happen.
    """
    tokens = [t for t in [command, *(args or [])] if t is not None]
    if not tokens:
        return False

    if bare_help and tokens[0] == BARE_HELP_TOKEN:
        return True

    return any(token in DASHED_HELP_TOKENS for token in tokens)
