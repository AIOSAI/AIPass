# =================== AIPass ====================
# Name: help_flags.py
# Description: Whole-sequence help detection — a help flag anywhere means explain, never execute
# Version: 1.0.0
# Created: 2026-08-13
# Modified: 2026-10-17
# =============================================

"""Whole-sequence help detection (DPLAN-0291 rule E).

A help flag anywhere in a command means explain, never execute: a gate at one fixed slot
let ``drone rm notes.md --help`` delete notes.md. One predicate serves every module.
"""

from __future__ import annotations

from typing import Sequence

# Unambiguous anywhere on a command line.
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

    ``bare_help=False`` for modules where ``help`` is itself a verb (discovery).
    """
    tokens = [t for t in [command, *(args or [])] if t is not None]
    if not tokens:
        return False

    if bare_help and tokens[0] == BARE_HELP_TOKEN:
        return True

    return any(token in DASHED_HELP_TOKENS for token in tokens)


def help_topic(
    command: str | None,
    args: Sequence[str] | None = None,
    *,
    bare_help: bool = True,
) -> str | None:
    """Which verb a help request is asking about, or None for the whole page."""
    tokens = [t for t in [command, *(args or [])] if t is not None]
    if bare_help and tokens and tokens[0] == BARE_HELP_TOKEN:
        tokens = tokens[1:]
    return next((token for token in tokens if token not in DASHED_HELP_TOKENS), None)
