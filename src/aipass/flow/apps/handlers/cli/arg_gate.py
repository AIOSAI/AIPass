# =================== AIPass ====================
# Name: arg_gate.py
# Description: One refusal for an unknown argument — decided here, rendered once by flow.py
# Version: 1.0.0
# Created: 2026-09-07
# Modified: 2026-09-07
# =============================================

"""The unknown-argument gate (Patrick's standing ruling, fleet sweep 2026-09-07).

An unknown command or argument FAILS: non-zero exit, a message naming the token,
a did-you-mean when one is close. It never proceeds as if a default were meant.

Flow's verbs and flags were already clean; its SUB-arguments were not, and the
sweep put flow in the worst class it defines. ``drone @flow list not_a_filter``
warned and then printed the open plans with exit 0: the caller gets an answer to
a question they did not ask, and a script reads success. Measured 2026-09-07,
six doors ran real work on an unread argument — ``aggregate`` performed a
cross-branch write — and two named the token but still exited 0.

ONE decision, every door. The refusal lived nowhere and nine doors each guessed,
which is how they drifted apart; the same lesson ``help_flags.py`` records one
file over.

THIS HANDLER DECIDES, IT DOES NOT DISPLAY. Handlers that import cli services
fail seedgo's separation rule, so the gate raises :class:`UnknownArgument`
carrying everything a renderer needs and ``apps/flow.py`` catches it once,
prints through cli and returns 1. Centralising the decision here and the
rendering there is what keeps nine doors saying the same thing.
"""

from __future__ import annotations

import difflib
from typing import NoReturn, Sequence

from aipass.flow.apps.handlers.json import json_handler

MODULE_NAME = "arg_gate"

# How close a typo must be before naming what the caller probably meant.
_SUGGESTION_CUTOFF = 0.6


class UnknownArgument(Exception):
    """A door was handed an argument it does not define.

    Carries the door, the offending token and the cure line so the renderer can
    name all three without re-deriving any of them.
    """

    def __init__(self, door: str, token: str, message: str, usage: str) -> None:
        super().__init__(message)
        self.door = door
        self.token = token
        self.message = message
        self.usage = usage


def _did_you_mean(token: str, valid: Sequence[str]) -> str | None:
    """The single closest valid value, when one is close enough to name.

    Args:
        token: What the caller typed.
        valid: The values this door accepts.

    Returns:
        The closest match, or None when nothing is near enough.
    """
    lowered = [value.lower() for value in valid]
    matches = difflib.get_close_matches(token.lower(), lowered, n=1, cutoff=_SUGGESTION_CUTOFF)
    return matches[0] if matches else None


def refuse_unknown(token: str, *, door: str, valid: Sequence[str] = (), noun: str = "argument") -> NoReturn:
    """Refuse an unrecognised token by name. Never returns.

    Args:
        token: The unrecognised token, exactly as the caller typed it.
        door: The command it was typed at, e.g. ``"flow list"``.
        valid: The accepted values, listed back to the caller when known.
        noun: What the token was in this position — "filter", "subcommand".

    Raises:
        UnknownArgument: Always. Rendered and exited non-zero by ``flow.py``.
    """
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
    """Refuse trailing arguments a door does not read. Never returns.

    Separate from :func:`refuse_unknown` because there is no valid-value list to
    offer: the door takes nothing in that position, so the cure is to drop the
    token, not to spell it differently. Silently ignoring it was the defect —
    ``drone @flow aggregate <typo>`` ran a real cross-branch write and reported
    success.

    Args:
        tokens: The unread trailing arguments.
        door: The command they were typed at, e.g. ``"templates"``.

    Raises:
        UnknownArgument: Always. Rendered and exited non-zero by ``flow.py``.
    """
    named = " ".join(repr(token) for token in tokens)
    message = f"{door}: takes no arguments here, got {named}"
    json_handler.log_operation(
        "unknown_argument_refused",
        {"door": door, "token": named, "noun": "trailing argument", "valid": []},
        module_name=MODULE_NAME,
    )
    raise UnknownArgument(door, named, message, f"drone @flow {door}")
