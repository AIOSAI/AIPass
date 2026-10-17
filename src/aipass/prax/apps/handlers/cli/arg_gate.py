# =================== AIPass ====================
# Name: arg_gate.py
# Description: Unknown-Argument Refusal Handler
# Version: 0.1.0
# Created: 2026-09-07
# Modified: 2026-10-17
# =============================================

"""
Unknown-Argument Refusal Handler

Reference: docs/architecture.md
"""

from difflib import get_close_matches
from typing import NoReturn, Optional, Sequence

from aipass.prax.apps.handlers.json import json_handler


class UnknownArgument(Exception):
    """A command was handed a token it does not define."""

    def __init__(self, verb: str, token: str, usage: str = "") -> None:
        super().__init__(f"{verb}: unknown argument '{token}'")
        self.verb = verb
        self.token = token
        self.usage = usage


def refuse(verb: str, token: str, usage: str = "") -> NoReturn:
    """Refuse one token by name — log it, then raise for the entry point to render."""
    json_handler.log_operation("unknown_argument_refused", {"verb": verb, "token": token})
    raise UnknownArgument(verb, token, usage)


def unknown_option(args: Sequence[str], known: Sequence[str]) -> Optional[str]:
    """Return the first dashed token that is not a known option, or None."""
    for token in args:
        if token.startswith("-") and token not in known:
            return token
    return None


def did_you_mean(token: str, known: Sequence[str]) -> Optional[str]:
    """Return the closest known option to a rejected token, or None."""
    matches = get_close_matches(token, list(known), n=1, cutoff=0.6)
    return matches[0] if matches else None
