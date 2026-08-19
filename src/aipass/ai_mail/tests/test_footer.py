# =================== AIPass ====================
# Name: test_footer.py
# Description: Tests for email footer handler
# Version: 1.0.0
# Created: 2026-04-25
# Modified: 2026-04-25
# =============================================

"""Tests for email footer handler -- get_footer, append_footer."""

import pytest
from unittest.mock import MagicMock

import aipass.ai_mail.apps.handlers.email.footer as mod


# --- Fixtures --------------------------------------------------------


@pytest.fixture(autouse=True)
def _suppress_log_operation(monkeypatch):
    """Prevent json_handler.log_operation from touching real files."""
    mock_jh = MagicMock()
    monkeypatch.setattr(mod, "json_handler", mock_jh)
    return mock_jh


# --- get_footer tests ------------------------------------------------


def test_get_footer_returns_string():
    """get_footer returns a string."""
    result = mod.get_footer()
    assert isinstance(result, str)


def test_get_footer_matches_constant():
    """get_footer returns the STANDARD_FOOTER constant."""
    result = mod.get_footer()
    assert result == mod.STANDARD_FOOTER


def test_get_footer_contains_checklist():
    """Footer contains the task checklist markers."""
    result = mod.get_footer()
    assert "TASK CHECKLIST" in result
    assert "SEEDGO CHECK" in result
    assert "UPDATE MEMORIES" in result
    assert "CLOSE YOUR PLAN" in result
    assert "EMAIL SENDER" in result


def test_close_your_plan_excludes_living_docs():
    """The close line must not tell an APLAN owner to close a standing record.

    This footer is appended to EVERY outgoing mail and has no plan context, so
    it cannot read a plan-type prefix — the wording itself has to carry the
    exception. Measured cost of leaving it implicit (DPLAN-0291 closeout):
    4 branches stopped to ask which rule won, and @api closed its living audit
    doc the day it was created, archiving the findings.
    """
    result = mod.get_footer()
    close_line = next(line for line in result.splitlines() if "CLOSE YOUR PLAN" in line)
    assert "APLAN" in close_line, "the close line must name the living-doc exception"


# --- append_footer tests ---------------------------------------------


def test_append_footer_appends_to_message():
    """append_footer adds the standard footer to the end of a message."""
    message = "Hello, this is the task body."
    result = mod.append_footer(message)
    assert result.startswith(message)
    assert result.endswith(mod.STANDARD_FOOTER)


def test_append_footer_preserves_original_message():
    """Original message text is intact in the result."""
    message = "Complete the integration for module X."
    result = mod.append_footer(message)
    assert message in result


def test_append_footer_logs_operation(_suppress_log_operation: MagicMock):
    """append_footer calls json_handler.log_operation with message length."""
    message = "Test message body"
    mod.append_footer(message)
    _suppress_log_operation.log_operation.assert_called_once_with("append_footer", {"message_length": len(message)})


def test_append_footer_empty_message():
    """append_footer works with an empty message string."""
    result = mod.append_footer("")
    assert result == mod.STANDARD_FOOTER


def test_append_footer_multiline_message():
    """append_footer handles multi-line messages correctly."""
    message = "Line 1\nLine 2\nLine 3"
    result = mod.append_footer(message)
    assert result == message + mod.STANDARD_FOOTER
