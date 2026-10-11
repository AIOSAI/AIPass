# =================== AIPass ====================
# Name: test_checkers_batch7_unused_function.py
# Description: unused_function_check ruling: the message says what was measured (split from test_checkers_batch7.py)
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-08
# =============================================

"""Tests for apps/handlers/aipass_standards/unused_function_check.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that each checker in handlers/aipass_standards/ parses and imports

import pytest

from aipass.seedgo.apps.handlers.aipass_standards import unused_function_check

pytestmark = pytest.mark.usefixtures("_pin_bypass_log")


class TestUnusedFunctionSaysWhatItActuallyMeasured:
    """The check measures "no caller in THIS branch" and said "unused".

    @memory 2026-08-31: `entry_limits.changed_entries()` was reported unused. It
    is called by @hooks at security/edit_gate.py:496 through a dynamic
    importlib import — a cross-branch consumer a same-branch AST scan cannot see
    in principle. Deleting it would disable the entry-cap half of the write gate
    for the whole fleet.

    The danger is precisely that the check is USEFUL: @memory had already acted
    on it correctly once the same night and dropped a genuinely dead helper. An
    agent that trusts it will eventually delete a real cross-branch entry point
    to get a green audit, and the audit will go green.

    They asked for the cheapest of three options and were right about which:
    the measurement is sound, only the WORD overclaims. Same species as this
    pack's AIPASS_ROOT substring bug — the checker stating more than it measured.
    """

    def _report(self, tmp_path, monkeypatch):
        # The REAL ignore handler runs here: it reads only this tmp branch. A
        # MagicMock stand-in makes is_seedgo_ignored() return a TRUTHY Mock and the
        # collector silently skips every file — the report then reads "No .py files
        # found in branch" and any assertion about the message passes or fails for
        # reasons unrelated to the message. A stand-in more generous than the real
        # function is the exact trap @memory described on 2026-08-30.

        # A neutral branch root INSIDE tmp_path: pytest names tmp_path after the
        # test, and the collector's skip set is matched against every path part.
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
        # NOT an `or` over synonyms: the first cut accepted either phrase, so a
        # mutant deleting the cross-branch clause kept passing on "this branch"
        # alone. Both halves of the disclosure are pinned.
        assert "cross-branch" in blob
        assert "importlib" in blob
        assert "confirm before deleting" in blob
