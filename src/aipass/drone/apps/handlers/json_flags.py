# =================== AIPass ====================
# Name: json_flags.py
# Description: Whole-sequence machine-output detection — --json in any slot asks for a document, not prose
# Version: 1.0.0
# Created: 2026-08-18
# Modified: 2026-10-17
# =============================================

"""Whole-sequence machine-output detection for drone's read verbs.

Strip before positional parsing: unstripped, ``--json`` reaches ``_handle_log``'s int().
Help outranks json; callers evaluate ``wants_help`` first.
"""

from __future__ import annotations

from typing import Sequence

# Dashed only: a bare ``json`` is plausible free text (a path, a branch) and would swallow it.
JSON_FLAG = "--json"


def wants_json(args: Sequence[str] | None) -> bool:
    """Whether the caller asked for a machine document instead of prose."""
    return JSON_FLAG in (args or ())


def strip_json_flag(args: Sequence[str] | None) -> list[str]:
    """Return *args* with every ``--json`` token removed."""
    return [token for token in (args or ()) if token != JSON_FLAG]
