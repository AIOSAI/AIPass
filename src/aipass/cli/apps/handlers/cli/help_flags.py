# =================== AIPass ====================
# Name: help_flags.py
# Description: Whole-sequence help detection — a help flag anywhere means explain, never execute
# Version: 1.0.0
# Created: 2026-08-13
# Modified: 2026-08-13
# =============================================

"""Whole-sequence help detection for the CLI branch's command surface.

THE RULE (help_flag_safety, published by @seedgo): a help flag ANYWHERE in the
arguments means EXPLAIN, never EXECUTE.

Both cli modules gated help at one fixed slot — ``args[0]`` — so a flag typed
after a subcommand was invisible and the verb ran anyway::

    drone @cli display demo --help    ->  args = ['demo', '--help']
                                          args[0] == 'demo', gate misses
                                          run_demo() fires, flag never read

The user asked a question and got a demo. Cheap here — ``run_demo()`` only
prints, nothing is written, deleted or sent — but the rule does not bend for
cheap cases, and the shape is the same one that cost @hooks live sessions and
@flow a registry write on the same day.

One predicate, four call sites. The gate lived in copies of the same two lines
in display.py and templates.py, which is how both drifted into the same bug at
once.

Bare ``help`` counts only at position 0, because later positions may be
legitimate values. Modules that own ``help`` as a real subcommand pass
``bare_help=False``; for them the word is a value in every position, dashed
forms still catch.

Pure predicate: no I/O, no state, no logging. It answers a question about a list
of strings and returns a bool. That is also what lets it live here at all —
this branch cannot import prax (prax depends on cli), and a helper that runs
before every command must not log.
"""

from __future__ import annotations

from typing import Sequence

# The two spellings unambiguous ANYWHERE on a command line. A user typing
# either has asked a question, wherever it lands.
DASHED_HELP_TOKENS = ("--help", "-h")

# Legitimate content in any later slot — a module called `help`, a file called
# `help` — so it is honoured at position 0 only.
BARE_HELP_TOKEN = "help"


def wants_help(
    command: str | None,
    args: Sequence[str] | None = None,
    *,
    bare_help: bool = True,
) -> bool:
    """Whether this invocation is asking for help rather than asking to act.

    Args:
        command: The subcommand slot, or None when only the argument list is
            being judged. cli modules receive their own name in ``command``
            (``display``, ``templates``, ``demo``), so they pass None and let
            ``args`` supply position 0.
        args: Everything after it.
        bare_help: Whether a bare ``help`` at position 0 requests help. False
            for modules where ``help`` is itself a verb.

    Returns:
        True if help should be printed and nothing else should happen.
    """
    tokens = [token for token in [command, *(args or [])] if token is not None]
    if not tokens:
        return False

    if bare_help and tokens[0] == BARE_HELP_TOKEN:
        return True

    return any(token in DASHED_HELP_TOKENS for token in tokens)
