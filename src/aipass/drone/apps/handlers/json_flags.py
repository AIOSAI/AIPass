# =================== AIPass ====================
# Name: json_flags.py
# Description: Whole-sequence machine-output detection — --json in any slot asks for a document, not prose
# Version: 1.0.0
# Created: 2026-08-18
# Modified: 2026-08-18
# =============================================

"""Whole-sequence machine-output detection for drone's read verbs.

Drone's git read doors answered only in rendered prose, so every consumer that
needed a fact had to scrape a sentence. @api's host lane carried ~385 lines of
parsing keyed on the *shape* of drone's output — a header, an indented row, a
footer — and said so in its own docstrings. A reworded footer was a phantom
changed file waiting to happen. ``--json`` is the answer those callers were
asking for (FPLAN-0438 round 4a, @devpulse).

Position-agnostic and STRIPPED before positional parsing, exactly like the help
flag: ``log --json 20`` and ``log 20 --json`` parse identically to ``log 20``.
Without the strip, ``--json`` reaches ``_handle_log``'s int() and logs a bogus
"Invalid log count" warning, and reaches ``_handle_show`` as the ref itself.

Help OUTRANKS json. ``status --help --json`` is still a question, and a question
must never be executed as an instruction (DPLAN-0291 rule E — the rule written
after ``drone rm notes.md --help`` deleted notes.md). Callers evaluate
``wants_help`` first; this module never sees that invocation.

Mirrors @memory's json_flag.py, which shipped the same surface the day @api
deleted their memory-config screen scraper. One spelling across the fleet.
"""

from __future__ import annotations

from typing import Sequence

# Dashed only, deliberately. Unlike ``help`` there is no bare ``json`` form: it
# is plausible free text — a path, a branch, a commit subject — and the bare
# word would swallow a real value.
JSON_FLAG = "--json"


def wants_json(args: Sequence[str] | None) -> bool:
    """Whether the caller asked for a machine document instead of prose.

    Args:
        args: Every token after the subcommand.

    Returns:
        True if ``--json`` appears in any slot.
    """
    return JSON_FLAG in (args or ())


def strip_json_flag(args: Sequence[str] | None) -> list[str]:
    """Return *args* with every ``--json`` token removed.

    Positional parsing runs on the stripped list, so the flag rides in any slot
    without shifting the real arguments out from under it.

    Args:
        args: Every token after the subcommand.

    Returns:
        A new list of every token that is not the JSON flag.
    """
    return [token for token in (args or ()) if token != JSON_FLAG]
