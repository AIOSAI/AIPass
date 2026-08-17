# =================== AIPass ====================
# Name: json_flag.py
# Description: Machine-Output Flag Detection Handler
# Version: 0.1.0
# Created: 2026-08-16
# Modified: 2026-08-16
# =============================================

"""
Machine-Output Flag Detection Handler

Single source of truth for "did the caller ask for machine output?" across
memory's command routing.

Purpose:
    @api execs these verbs to serve BAUD's memory-settings screens and had
    no machine surface, so it read the RENDERED human output — every
    wording change was a silent breakage waiting to happen. `--json` is
    that surface.

    The flag is position-agnostic exactly like the help flag, and is
    STRIPPED before positional parsing so
    `config set @memory sessions 25 --json` parses identically to the same
    line without it.

Precedence:
    Help still beats JSON. Callers must evaluate `wants_help` FIRST — a
    question must never be executed as an instruction (APLAN-0010), and
    `... --help --json` is still a question.

Independence:
    Pure argument inspection — no I/O, no imports beyond typing.
"""

from typing import Sequence

# Dashed only. There is deliberately no bare `json` form: unlike `help`, it
# is a plausible piece of free text and the bare word would swallow it.
JSON_FLAG = "--json"


# =============================================================================
# FLAG DETECTION
# =============================================================================


def wants_json(args: Sequence[str]) -> bool:
    """
    Report whether machine-readable output was requested.

    Args:
        args: Argument tokens after the command name

    Returns:
        True if `--json` appears in any slot
    """
    return JSON_FLAG in args


def strip_json_flag(args: Sequence[str]) -> list[str]:
    """
    Return *args* with every `--json` token removed.

    Positional parsing runs on the stripped list, so the flag can ride in
    any slot without shifting `@branch <type> <count>` out from under it.

    Args:
        args: Argument tokens after the command name

    Returns:
        A new list containing every token that is not the JSON flag
    """
    return [token for token in args if token != JSON_FLAG]
