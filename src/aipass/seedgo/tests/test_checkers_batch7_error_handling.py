# =================== AIPass ====================
# Name: test_checkers_batch7_error_handling.py
# Description: error_handling_check ruling: the shared diagnostic guard clause (split from test_checkers_batch7.py)
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-08
# =============================================

"""Tests for apps/handlers/aipass_standards/error_handling_check.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that each checker in handlers/aipass_standards/ parses and imports

import pytest

from aipass.seedgo.apps.handlers.aipass_standards import error_handling_check

pytestmark = pytest.mark.usefixtures("_pin_bypass_log")


class TestErrorHandlingSharesTheDiagnosticGuardClause:
    """Two checkers, one question, one implementation — @canary's point that a
    single discriminator clears both findings. Shared rather than copied so the
    two cannot drift into disagreeing about the same handler.
    """

    def _passed(self, tmp_path, source):
        target = tmp_path / "probe.py"
        target.write_text(source, encoding="utf-8")
        return error_handling_check.check_module(str(target))["checks"][0]["passed"]

    def test_a_pass_guarding_a_report_is_not_a_silent_failure(self, tmp_path):
        source = "def f(logger, exc):\n    try:\n        logger.debug('x', exc)\n    except Exception:\n        pass\n"
        assert self._passed(tmp_path, source) is True

    def test_a_pass_over_real_work_is_still_a_silent_failure(self, tmp_path):
        """error_handling's own finding names the file and the handler's line.

        It was the same body as silent_catch's
        test_a_pass_guarding_real_work_keeps_its_finding; the property this
        checker adds is where it points (seedgo, fleet green leg 8).
        """
        source = "def f(path):\n    try:\n        path.unlink()\n    except OSError:\n        pass\n"
        target = tmp_path / "probe.py"
        target.write_text(source, encoding="utf-8")
        check = error_handling_check.check_module(str(target))["checks"][0]
        assert check["passed"] is False
        assert check["message"] == (
            f"Silent failure detected (except: pass) in {target.name} at line 4 - errors should log/return"
        )
