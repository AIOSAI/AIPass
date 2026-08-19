# =================== AIPass ====================
# Name: help_flag.py
# Description: Pure predicate — does this argv ask for help rather than act?
# Version: 1.0.0
# Created: 2026-08-13
# Modified: 2026-08-13
# =============================================

"""help_flag — decide whether an argument sequence is a help request.

Asking a question must never perform the action being asked about. A gate
that inspects only ``args[0]`` is not a gate: a help flag in any later
position falls through to the verb. That is not theoretical — before this
handler existed, ``aipass trust <dir> --help`` ran the enrollment write, and
running init_flow directly with ``agent --help`` would have created an agent
literally named ``--help`` (APLAN-0018, seedgo help_flag_safety).

Called from inside each module's ``handle_command()`` — AFTER the ownership
check, so a module never answers for a command it does not own — rather than
only at the router. The router is not enough on its own: modules with a
standalone ``__main__`` path hand raw ``sys.argv`` straight to
``handle_command()`` and never touch the router at all.

Deliberately pure: no I/O, no logging, no JSON. It runs on every command
dispatch, and a predicate that can fail is a predicate that can let a write
through.
"""

from __future__ import annotations

from typing import Sequence

# Exact matches only. Substring or prefix matching would swallow a real
# argument that merely starts with the same letters (a project named
# "-hotfix", a question containing "--help-me").
_HELP_FLAGS = frozenset({"--help", "-h"})

_HELP_WORD = "help"


def wants_help(args: Sequence[str], *, allow_bare_word: bool = True) -> bool:
    """True when `args` asks for help instead of requesting an action.

    A dashed flag (``--help`` / ``-h``) counts from ANY position — that is
    the whole point, and the shape every branch in the fleet round got wrong.

    The bare word ``help`` counts only at position 0, where it reads as a
    subcommand. Later on it is ordinary content: ``aipass new help-docs``
    names a project, it does not ask a question.

    Args:
        args: The argument sequence, without the command itself.
        allow_bare_word: Treat a leading bare ``help`` as a help request.
            Pass False from a module that OWNS a bare ``help`` verb — for
            `aipass help`, ``help`` is the command, so ``aipass help help``
            is a question to answer, not a request for usage text.
    """
    if not args:
        return False

    if any(arg in _HELP_FLAGS for arg in args):
        return True

    return allow_bare_word and args[0] == _HELP_WORD
