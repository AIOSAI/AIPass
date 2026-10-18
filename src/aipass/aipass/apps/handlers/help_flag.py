# =================== AIPass ====================
# Name: help_flag.py
# Description: Pure predicate — does this argv ask for help rather than act?
# Version: 1.0.0
# Created: 2026-08-13
# Modified: 2026-10-17
# =============================================

"""help_flag — decide whether an argument sequence is a help request.

Call it inside each module's ``handle_command()``, after the ownership check: a
standalone ``__main__`` hands raw argv there and never touches the router.
"""

from __future__ import annotations

from typing import Sequence

# Exact matches only: prefix matching would swallow "-hotfix" or "--help-me".
_HELP_FLAGS = frozenset({"--help", "-h"})

_HELP_WORD = "help"


def wants_help(args: Sequence[str], *, allow_bare_word: bool = True) -> bool:
    """True when `args` asks for help instead of requesting an action.

    A dashed flag counts from any position, bare ``help`` only at position 0.
    Pass allow_bare_word=False from a module that owns a bare ``help`` verb.
    """
    if not args:
        return False

    if any(arg in _HELP_FLAGS for arg in args):
        return True

    return allow_bare_word and args[0] == _HELP_WORD
