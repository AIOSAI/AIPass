# =================== AIPass ====================
# Name: arg_gate.py
# Description: Unknown-Argument Refusal Handler
# Version: 0.1.0
# Created: 2026-09-07
# Modified: 2026-09-07
# =============================================

"""
Unknown-Argument Refusal Handler

Single source of truth for "prax was handed a token it does not define".

Purpose:
    PATRICK'S STANDING RULING: an unknown command or argument FAILS — non-zero
    exit and a message naming the token. Never default, never silently ignore.

    @devpulse's 2026-09-07 fleet CLI sweep caught prax swallowing two of them:

        drone @prax --definitely-not-a-flag   -> self-map, exit 0
        drone @prax log-audit not_a_real_xyz  -> refusal printed, exit 0

    The first is the worse of the two: argparse's parse_known_args hands an
    unrecognised flag back instead of erroring, so the output was byte-identical
    to a clean no-args run and a caller's `&&` read the typo as success. The
    second told the truth on screen and lied in its exit code, which is the same
    failure wearing a friendlier face.

Independence:
    Pure argument inspection — no I/O, no state, no cli import. This handler
    DECIDES; `apps/prax.py` catches the refusal, renders it through cli and
    returns 1. Handlers that render their own errors fail seedgo's separation
    rule, and one refusal per module is exactly the drift a shared gate exists
    to prevent.
"""

from difflib import get_close_matches
from typing import NoReturn, Optional, Sequence

from aipass.prax.apps.handlers.json import json_handler


class UnknownArgument(Exception):
    """A command was handed a token it does not define.

    Carries the verb, the offending token and the cure line so the renderer can
    name all three without re-deriving any of them.
    """

    def __init__(self, verb: str, token: str, usage: str = "") -> None:
        super().__init__(f"{verb}: unknown argument '{token}'")
        self.verb = verb
        self.token = token
        self.usage = usage


# =============================================================================
# REFUSAL
# =============================================================================


def refuse(verb: str, token: str, usage: str = "") -> NoReturn:
    """
    Refuse one token by name — log it, then raise for the entry point to render.

    Logged before it is raised: a refused command leaves no other trace, and the
    operations log is where "why did that script stop" gets answered later.

    Args:
        verb: The command that was asked to accept the token
        token: The token prax does not define
        usage: The cure line to show the caller

    Raises:
        UnknownArgument: Always
    """
    json_handler.log_operation("unknown_argument_refused", {"verb": verb, "token": token})
    raise UnknownArgument(verb, token, usage)


# =============================================================================
# DETECTION
# =============================================================================


def unknown_option(args: Sequence[str], known: Sequence[str]) -> Optional[str]:
    """
    Return the first dashed token that is not a known option, or None.

    Only dashed tokens are judged here: a bare word in prax's top-level slot is
    a command, and commands are routed and refused by name elsewhere.

    Args:
        args: Tokens argparse could not place
        known: Options this level of the CLI defines, e.g. ('--help', '-h')

    Returns:
        The offending token, or None when every dashed token is recognised
    """
    for token in args:
        if token.startswith("-") and token not in known:
            return token
    return None


def did_you_mean(token: str, known: Sequence[str]) -> Optional[str]:
    """
    Return the closest known option to a rejected token, or None.

    A typo is the common case — `--verison` deserves a pointer, not a lecture.

    Args:
        token: The rejected token
        known: Options this level of the CLI defines

    Returns:
        The nearest match, or None when nothing is close enough
    """
    matches = get_close_matches(token, list(known), n=1, cutoff=0.6)
    return matches[0] if matches else None
