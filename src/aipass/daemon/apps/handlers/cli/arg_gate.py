# =================== AIPass ====================
# Name: arg_gate.py
# Description: The one unknown-argument refusal every daemon verb shares
# Version: 1.1.0
# Created: 2026-09-07
# Modified: 2026-10-17
# =============================================

"""
Unknown-argument gate — one refusal, decided once, for every daemon verb.

Decides only: raises UnknownArgument; apps/daemon.py renders it and exits 1 (handlers may not import cli).
"""

from typing import Iterable, NoReturn, Optional, Sequence

from aipass.daemon.apps.handlers.json import json_handler

# Verbs resolve help BEFORE the gate runs: help is never an unknown argument.
HELP_FLAGS = ("--help", "-h", "help")


class UnknownArgument(Exception):
    """A verb was handed an argument it does not define (carries verb, token, usage)."""

    def __init__(self, verb: str, token: str, usage: str = "") -> None:
        super().__init__(f"{verb}: unknown argument '{token}'")
        self.verb = verb
        self.token = token
        self.usage = usage


def unknown_argument(
    args: Sequence[str],
    flags: Iterable[str] = (),
    value_flags: Iterable[str] = (),
) -> Optional[str]:
    """Return the first argument this verb does not define, or None if all are known."""
    known_flags = set(flags)
    known_value_flags = set(value_flags)

    index = 0
    while index < len(args):
        token = args[index]
        if token in known_value_flags:
            # Skip the value too, or `--hours 48` refuses on "48".
            index += 2
            continue
        if token in known_flags:
            index += 1
            continue
        return token
    return None


def refuse(verb: str, token: str, usage: str = "") -> NoReturn:
    """Record the refusal (its only trace) and raise it. Never returns."""
    json_handler.log_operation("unknown_argument_refused", {"verb": verb, "token": token})
    raise UnknownArgument(verb, token, usage)


def gate(
    verb: str,
    args: Sequence[str],
    flags: Iterable[str] = (),
    value_flags: Iterable[str] = (),
    usage: str = "",
) -> None:
    """Refuse the first unrecognised argument, or return so the verb can run."""
    token = unknown_argument(args, flags=flags, value_flags=value_flags)
    if token is not None:
        refuse(verb, token, usage)
