# =================== AIPass ====================
# Name: branch_flag.py
# Description: Branch Flag Parsing Handler for rollover run/check and the todo verbs
# Version: 1.1.0
# Created: 2026-09-15
# Modified: 2026-10-17
# =============================================

"""
Branch Flag Parsing Handler

Anything else is refused, never ignored: a mistyped flag must not fall back to the caller's branch on a write.
"""

from typing import Sequence

from aipass.memory.apps.handlers.json import json_handler

MODULE_NAME = "branch_flag"
BRANCH_FLAG = "--branch"


def _refused(tokens: Sequence[str], problem: str) -> tuple[None, str]:
    """Record a refused flag and hand the refusal back."""
    json_handler.log_operation(
        "branch_flag_refused",
        {"tokens": list(tokens), "problem": problem},
        module_name=MODULE_NAME,
    )
    return None, problem


def read_branch_flag(tokens: Sequence[str]) -> tuple[str | None, str | None]:
    """Read ``--branch @name`` or ``--branch=@name``: ``(branch|None, None)`` or ``(None, problem)``."""
    if not tokens:
        return None, None

    token = tokens[0]
    if token == BRANCH_FLAG:
        value = tokens[1] if len(tokens) > 1 else ""
        rest = list(tokens[2:])
    elif token.startswith(BRANCH_FLAG + "="):
        value = token.split("=", 1)[1]
        rest = list(tokens[1:])
    else:
        return _refused(tokens, f"Unknown argument: '{token}'")

    if rest:
        return _refused(tokens, f"Unknown argument: '{rest[0]}'")
    if not value or value.startswith("-"):
        return _refused(tokens, f"{BRANCH_FLAG} needs a branch name")
    return value, None


def read_branch_arg(tokens: Sequence[str]) -> tuple[str | None, str | None]:
    """Read a bare ``@name``, or ``--branch @name``, for the ``todo`` verbs."""
    if tokens and tokens[0].startswith("@") and len(tokens[0]) > 1:
        if len(tokens) > 1:
            return _refused(tokens, f"Unknown argument: '{tokens[1]}'")
        return tokens[0], None
    return read_branch_flag(tokens)
