# =================== AIPass ====================
# Name: json_flag.py
# Description: Machine-Output Flag Detection Handler
# Version: 0.1.0
# Created: 2026-08-16
# Modified: 2026-10-17
# =============================================

"""
Machine-Output Flag Detection Handler

Help beats JSON: callers check `wants_help` first, so `... --help --json` stays a question.
"""

from typing import Sequence

# Dashed only. There is deliberately no bare `json` form: unlike `help`, it
# is a plausible piece of free text and the bare word would swallow it.
JSON_FLAG = "--json"


def wants_json(args: Sequence[str]) -> bool:
    """Report whether machine-readable output was requested."""
    return JSON_FLAG in args


def strip_json_flag(args: Sequence[str]) -> list[str]:
    """Return *args* with every `--json` token removed.

    Positional parsing runs on the stripped list, so the flag never shifts `@branch <type> <count>`.
    """
    return [token for token in args if token != JSON_FLAG]
