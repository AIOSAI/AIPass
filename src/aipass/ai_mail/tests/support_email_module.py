# =================== AIPass ====================
# Name: support_email_module.py
# Description: Shared helper for test_email_module.py and test_email_module_send.py - the stdout line reader
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-08
# =============================================

"""Helper for the tests of apps/modules/email.py and email_send.py (no test_ prefix: never collected)."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that the module parses and imports

import pytest


class _StdoutLines:
    """The lines the product's real console has written to stdout, read through capsys.

    Each read drains capsys and keeps what it drained, so a test may iterate
    more than once and still see every line printed so far. Leg 5 put this
    where a MagicMock console used to record the call args (mock_console).
    """

    def __init__(self, capsys: pytest.CaptureFixture[str]) -> None:
        self._capsys = capsys
        self._lines: list[str] = []

    def __iter__(self):
        self._lines.extend(self._capsys.readouterr().out.splitlines())
        return iter(list(self._lines))
