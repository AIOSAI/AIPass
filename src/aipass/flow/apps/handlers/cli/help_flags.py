# =================== AIPass ====================
# Name: help_flags.py
# Description: Whole-sequence help detection — a help flag anywhere means explain, never execute
# Version: 1.0.0
# Created: 2026-08-13
# Modified: 2026-08-13
# =============================================

"""Whole-sequence help detection (DPLAN-0291 rule E).

A help flag ANYWHERE in a command means explain, never execute. Every flow
module gated help at ``args[0]`` only, so a flag typed later was invisible and
the verb ran. `drone @flow close FPLAN-0042 --help` did not print help -- it
CLOSED FPLAN-0042.

That is the sharp edge here: flow's verbs close, create and restore plans.
A help question must never mutate a plan.

Bare ``help`` counts only at position 0, because flow's later slots carry
FREE TEXT -- a plan subject is whatever the caller typed. Matching the word
anywhere would make `drone @flow create . "help the user onboard"` print help
instead of creating that plan. Dashed forms are exact-match, so a subject only
collides when it is *exactly* ``--help`` or ``-h``.

One predicate, nine call sites. The gate lived in five copies of the same two
lines, which is how five modules drifted into the same bug at once -- the
copy-paste was the defect (@drone and @trigger landed the same conclusion
today).
"""

from __future__ import annotations

from typing import Sequence

# The two spellings unambiguous ANYWHERE on a command line. A user typing
# either has asked a question, wherever it lands.
DASHED_HELP_TOKENS = ("--help", "-h")

# Legitimate content in any later slot (plan subjects are free text), so it is
# honoured at position 0 only.
BARE_HELP_TOKEN = "help"


def wants_help(args: Sequence[str] | None, *, bare_help: bool = True) -> bool:
    """Whether this invocation is asking for help rather than asking to act.

    Args:
        args: The argument sequence following the module's own verb.
        bare_help: Whether a bare ``help`` at position 0 requests help. False
            for call sites where ``help`` could be a legitimate first value.

    Returns:
        True if help should be printed and nothing else should happen.
    """
    tokens = [t for t in (args or []) if t is not None]
    if not tokens:
        return False

    if bare_help and tokens[0] == BARE_HELP_TOKEN:
        return True

    return any(token in DASHED_HELP_TOKENS for token in tokens)
