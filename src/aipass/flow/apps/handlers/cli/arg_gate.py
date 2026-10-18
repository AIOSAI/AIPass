# =================== AIPass ====================
# Name: arg_gate.py
# Description: One refusal for an unknown argument — decided here, rendered once by flow.py
# Version: 1.0.0
# Created: 2026-09-07
# Modified: 2026-10-17
# =============================================

"""The unknown-argument gate (the owner's standing ruling, fleet sweep 2026-09-07).

An unknown argument fails with a non-zero exit, never a silent default. Handlers may not import
cli services, so the gate raises UnknownArgument and ``apps/flow.py`` renders it once for every door.
"""

from __future__ import annotations

import difflib
from typing import NoReturn, Sequence

from aipass.flow.apps.handlers.json import json_handler

MODULE_NAME = "arg_gate"

_SUGGESTION_CUTOFF = 0.6


class UnknownArgument(Exception):
    """A door was handed an argument it does not define."""

    def __init__(self, door: str, token: str, message: str, usage: str) -> None:
        super().__init__(message)
        self.door = door
        self.token = token
        self.message = message
        self.usage = usage


def _did_you_mean(token: str, valid: Sequence[str]) -> str | None:
    """The single closest valid value, when one is close enough to name."""
    lowered = [value.lower() for value in valid]
    matches = difflib.get_close_matches(token.lower(), lowered, n=1, cutoff=_SUGGESTION_CUTOFF)
    return matches[0] if matches else None


def refuse_unknown(token: str, *, door: str, valid: Sequence[str] = (), noun: str = "argument") -> NoReturn:
    """Refuse an unrecognised token by name. Never returns."""
    suggestion = _did_you_mean(token, valid) if valid else None
    if suggestion:
        usage = f"drone @flow {door} {suggestion}"
    elif valid:
        usage = f"drone @flow {door} <{'|'.join(valid)}>"
    else:
        usage = f"drone @flow {door} --help"

    message = f"{door}: unknown {noun} '{token}'"
    json_handler.log_operation(
        "unknown_argument_refused",
        {"door": door, "token": token, "noun": noun, "valid": list(valid)},
        module_name=MODULE_NAME,
    )
    raise UnknownArgument(door, token, message, usage)


def refuse_extra(tokens: Sequence[str], *, door: str) -> NoReturn:
    """Refuse trailing arguments a door does not read. Never returns."""
    named = " ".join(repr(token) for token in tokens)
    message = f"{door}: takes no arguments here, got {named}"
    json_handler.log_operation(
        "unknown_argument_refused",
        {"door": door, "token": named, "noun": "trailing argument", "valid": []},
        module_name=MODULE_NAME,
    )
    raise UnknownArgument(door, named, message, f"drone @flow {door}")
