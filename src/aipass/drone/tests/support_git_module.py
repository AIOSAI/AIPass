# =================== AIPass ====================
# Name: support_git_module.py
# Description: Shared helpers for the git_module test files (split from test_git_module.py)
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-08
# =============================================

"""Shared helpers for the tests of apps/modules/git_module.py and its handlers (no test_ prefix: never collected)."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that the module parses and imports

from __future__ import annotations

from unittest.mock import MagicMock


def _done(stdout: str = "", returncode: int = 0, stderr: str = "") -> MagicMock:
    return MagicMock(stdout=stdout, stderr=stderr, returncode=returncode)
