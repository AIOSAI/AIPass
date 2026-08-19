# =================== AIPass ====================
# Name: help_flags.py
# Description: Whole-sequence help detection — a help flag anywhere means explain, never execute
# Version: 1.0.0
# Created: 2026-08-13
# Modified: 2026-08-13
# =============================================

"""Whole-sequence help detection for seedgo's own command surface.

THE RULE (help_flag_safety, the standard this branch publishes): a help flag
ANYWHERE in the arguments means EXPLAIN, never EXECUTE.

seedgo audited ten branches into this fix while carrying the same defect. Every
seedgo module gated help at one fixed slot — ``args[0]`` — so a flag typed later
was invisible and the verb ran: ``drone @seedgo checklist <file> --help`` ran a
full per-file audit instead of describing one, and ``drone @seedgo audit
inbox-ids --help`` walked every inbox in the repo. The auditor is not exempt
from the audit.

One predicate, nine call sites. The gate lived in nine copies of the same two
lines, which is how nine modules drifted into the same bug at once; a rule worth
enforcing in every module is worth defining once.

Bare ``help`` counts only at position 0, because later positions may be
legitimate values — a pack name, a file path, a branch. Modules that own
``help`` as a real subcommand pass ``bare_help=False``; for them the word is a
value in every position, dashed forms still catch.

Pure predicate: no I/O, no state, no logging. It answers a question about a list
of strings and returns a bool. It runs before EVERY seedgo command, which is why
it carries a json_structure bypass — logging here would write "a help flag was
looked for" on every invocation and bury the operation log it is meant to serve.
"""

from __future__ import annotations

from typing import Sequence

# The two spellings unambiguous ANYWHERE on a command line. A user typing
# either has asked a question, wherever it lands.
DASHED_HELP_TOKENS = ("--help", "-h")

# Legitimate content in any later slot — a pack called `help`, a file called
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
            being judged (seedgo modules receive their own name in ``command``,
            so they pass None and let ``args`` supply position 0).
        args: Everything after it.
        bare_help: Whether a bare ``help`` at position 0 requests help. False
            for modules where ``help`` is itself a verb, so their own
            subcommand keeps working.

    Returns:
        True if help should be printed and nothing else should happen.
    """
    tokens = [token for token in [command, *(args or [])] if token is not None]
    if not tokens:
        return False

    if bare_help and tokens[0] == BARE_HELP_TOKEN:
        return True

    return any(token in DASHED_HELP_TOKENS for token in tokens)
