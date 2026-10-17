# =================== AIPass ====================
# Name: help_flags.py
# Description: Whole-sequence help detection — a help flag anywhere means explain, never execute
# Version: 1.0.0
# Created: 2026-08-13
# Modified: 2026-10-17
# =============================================

"""Whole-sequence help detection (DPLAN-0291 rule E).

A help flag ANYWHERE means explain, never execute: flow's verbs mutate plans, and a help probe must not.
"""

from __future__ import annotations

from typing import Sequence

DASHED_HELP_TOKENS = ("--help", "-h")

# Position 0 only: later slots carry free text ("help the user onboard" is a plan subject).
BARE_HELP_TOKEN = "help"


def wants_help(args: Sequence[str] | None, *, bare_help: bool = True) -> bool:
    """Whether this invocation is asking for help rather than asking to act.
    bare_help=False for call sites where ``help`` could be a legitimate first value.
    """
    tokens = [t for t in (args or []) if t is not None]
    if not tokens:
        return False

    if bare_help and tokens[0] == BARE_HELP_TOKEN:
        return True

    return any(token in DASHED_HELP_TOKENS for token in tokens)
