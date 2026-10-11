# =================== AIPass ====================
# Name: support_checkers_batch7.py
# Description: Shared helper for the checkers_batch7 test files (split from test_checkers_batch7.py)
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-08
# =============================================

"""Shared helper for the tests of apps/handlers/aipass_standards/ checkers (not test_: never collected)."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that the module parses and imports

from typing import List


def _lines(text: str) -> List[str]:
    """Split text into lines, widening LiteralString to str for pyright."""
    return text.split("\n")
