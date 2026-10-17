# =================== AIPass ====================
# Name: test_checkers_batch7_unused_function.py
# Description: unused_function_check ruling: the message says what was measured (split from test_checkers_batch7.py)
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-17
# =============================================

"""Tests for apps/handlers/aipass_standards/unused_function_check.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that each checker in handlers/aipass_standards/ parses and imports

import pytest

from aipass.seedgo.apps.handlers.aipass_standards import unused_function_check

pytestmark = pytest.mark.usefixtures("_pin_bypass_log")


class TestUnusedFunctionSaysWhatItActuallyMeasured:
    """The check measures "no caller in THIS branch" and said "unused"."""

    def _report(self, tmp_path, monkeypatch):
        # The REAL ignore handler: a MagicMock returns a truthy Mock and the collector skips every file.

        # A neutral root inside tmp_path: the collector's skip set matches every path part, and tmp_path names the test.
        root = tmp_path / "branchroot"
        pkg = root / "apps" / "handlers"
        pkg.mkdir(parents=True)
        (pkg / "mod.py").write_text("def never_called_here():\n    return 1\n", encoding="utf-8")
        return unused_function_check.check_branch(str(root))

    def test_the_message_does_not_claim_the_function_is_unused(self, tmp_path, monkeypatch):
        report = self._report(tmp_path, monkeypatch)
        blob = str(report).lower()
        assert "no caller in this branch" in blob, report

    def test_the_message_names_the_limit_of_the_scan(self, tmp_path, monkeypatch):
        """A reader must be able to tell that cross-branch callers were not checked."""
        blob = str(self._report(tmp_path, monkeypatch)).lower()
        # Not an `or` over synonyms: both halves of the disclosure are pinned.
        assert "cross-branch" in blob
        assert "importlib" in blob
        assert "confirm before deleting" in blob
