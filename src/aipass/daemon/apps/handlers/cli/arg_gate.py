# =================== AIPass ====================
# Name: arg_gate.py
# Description: The one unknown-argument refusal every daemon verb shares
# Version: 1.1.0
# Created: 2026-09-07
# Modified: 2026-09-07
# =============================================

"""
Unknown-argument gate — one refusal, decided once, for every daemon verb.

PATRICK'S STANDING RULING: an unknown command or argument FAILS with a non-zero
exit and a message naming the token. Never default, never silently ignore.

WHY THIS EXISTS. @devpulse's 2026-09-07 fleet CLI sweep caught `branch-health`
printing "not found" and exiting 0 (EXIT-0-ON-FAILURE, row 21). Cured in wave 1.
The wave-1 reply then reported the quieter half of the same violation: ten more
verbs ACCEPTED a trailing argument and silently ignored it, so
`drone @daemon queue not_a_real_subarg_xyz` rendered the queue and exited 0 —
the caller's `&&` reads that as the queue it asked for, and a typo'd flag
(`--jsonn`) reads as success while doing something else entirely.

TWO KINDS OF FLAG, because they consume different amounts of the argv. A boolean
flag stands alone (`--json`); a value flag swallows the token after it
(`--hours 48`), and that token must NOT then be judged a stray positional. Any
argument that is neither, and every positional on a verb that defines none, is
refused BY NAME — the caller has to be told which token was rejected, or a long
command line is a guessing game.

THIS HANDLER DECIDES, IT DOES NOT DISPLAY. It raises :class:`UnknownArgument`
carrying everything a renderer needs; ``apps/daemon.py`` catches it once, prints
through cli, and exits 1. Handlers that import cli services fail seedgo's
separation rule, and eleven verbs each rendering their own refusal is exactly
the drift one shared gate exists to prevent — so the decision is centralised
here and the rendering is centralised there.
"""

from typing import Iterable, NoReturn, Optional, Sequence

from aipass.daemon.apps.handlers.json import json_handler

# Help is resolved by each verb BEFORE the gate runs — a help request is never an
# unknown argument, and it must never exit non-zero. Named here so the vocabulary
# is stated once even though the gate itself never sees it.
HELP_FLAGS = ("--help", "-h", "help")


class UnknownArgument(Exception):
    """A verb was handed an argument it does not define.

    Carries the verb, the offending token and the cure line, so the renderer can
    name all three without re-deriving any of them.
    """

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
    """Return the first argument this verb does not define, or None if all are known.

    Args:
        args: The verb's argument list, exactly as the router handed it over.
        flags: Boolean flags the verb accepts, e.g. ``("--json",)``.
        value_flags: Flags that consume the token after them, e.g. ``("--hours",)``.

    Returns:
        The offending token, or None when every argument is recognised.
    """
    known_flags = set(flags)
    known_value_flags = set(value_flags)

    index = 0
    while index < len(args):
        token = args[index]
        if token in known_value_flags:
            # Skip the flag AND its value. Without this the value reads as a
            # stray positional and `--hours 48` refuses on "48".
            index += 2
            continue
        if token in known_flags:
            index += 1
            continue
        return token
    return None


def refuse(verb: str, token: str, usage: str = "") -> NoReturn:
    """Record the refusal and raise it. Never returns.

    Logged before it is raised: a refused command leaves no other trace, and the
    operations log is where "why did that script stop" gets answered later.
    """
    json_handler.log_operation("unknown_argument_refused", {"verb": verb, "token": token})
    raise UnknownArgument(verb, token, usage)


def gate(
    verb: str,
    args: Sequence[str],
    flags: Iterable[str] = (),
    value_flags: Iterable[str] = (),
    usage: str = "",
) -> None:
    """Refuse the first unrecognised argument, or return so the verb can run.

    The whole gate in one call, because a two-step form (detect here, refuse
    there) is what lets one verb out of eleven forget the second step.
    """
    token = unknown_argument(args, flags=flags, value_flags=value_flags)
    if token is not None:
        refuse(verb, token, usage)
