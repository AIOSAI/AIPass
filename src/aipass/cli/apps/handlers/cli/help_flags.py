# =================== AIPass ====================
# Name: help_flags.py
# Description: Whole-sequence help detection — a help flag anywhere means explain, never execute
# Version: 1.0.0
# Created: 2026-08-13
# Modified: 2026-10-17
# =============================================

"""Whole-sequence help detection for the CLI branch's command surface."""

# Runs before every command, so it must not log (and cli cannot import prax).

from __future__ import annotations

from typing import Sequence

DASHED_HELP_TOKENS = ("--help", "-h")

# A later `help` may be a real value (a module or file named help): position 0 only.
BARE_HELP_TOKEN = "help"


def wants_help(
    command: str | None,
    args: Sequence[str] | None = None,
    *,
    bare_help: bool = True,
) -> bool:
    """Whether this invocation is asking for help rather than asking to act."""
    tokens = [token for token in [command, *(args or [])] if token is not None]
    if not tokens:
        return False

    if bare_help and tokens[0] == BARE_HELP_TOKEN:
        return True

    return any(token in DASHED_HELP_TOKENS for token in tokens)
