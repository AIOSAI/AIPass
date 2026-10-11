# =================== AIPass ====================
# Name: test_daemon_guards.py
# Description: Tests for the dispatch daemon's protected-branch guard and the AIPASS-TEST token auto-ack
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-08
# =============================================

"""Tests for apps/handlers/dispatch/test_token.py and daemon.py's guard -- protected branches, the test-token ack."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(shared) — check_inbox_for_dispatch(), the scan beside these acks: tests/test_daemon_inbox.py

import json
import pytest
from unittest.mock import patch

from aipass.ai_mail.apps.handlers.dispatch.daemon import is_protected_branch
from aipass.ai_mail.apps.handlers.dispatch.test_token import (
    has_test_token as _has_test_token,
    auto_ack_test_email as _auto_ack_test_email,
    scan_and_ack_test_emails,
    TEST_TOKEN,
)

pytestmark = pytest.mark.usefixtures("daemon_json_silenced", "daemon_paths_in_tmp")


# ---- is_protected_branch tests ---------------------------------


def test_is_protected_branch_devpulse():
    """@devpulse is protected."""
    assert is_protected_branch("@devpulse") is True


def test_is_protected_branch_other():
    """Other branches are not protected."""
    assert is_protected_branch("@flow") is False
    assert is_protected_branch("@backup") is False
    assert is_protected_branch("@memory") is False


def test_is_protected_branch_empty_string():
    """Empty string is not protected."""
    assert is_protected_branch("") is False


# ---- _has_test_token tests -----------------------------------


def test_has_test_token_plain_body():
    """Token on its own line is detected."""
    body = f"Some text\n{TEST_TOKEN}\nMore text"
    assert _has_test_token(body) is True


def test_has_test_token_only_token():
    """Body containing only the token is detected."""
    assert _has_test_token(TEST_TOKEN) is True


def test_has_test_token_absent():
    """Body without token returns False."""
    assert _has_test_token("Hello, please process inbox.") is False


def test_has_test_token_inside_code_fence_ignored():
    """Token inside a code fence is not detected."""
    body = f"Example:\n```\n{TEST_TOKEN}\n```\nEnd"
    assert _has_test_token(body) is False


def test_has_test_token_after_code_fence():
    """Token after a closing fence is still detected."""
    body = f"```\nsome code\n```\n{TEST_TOKEN}"
    assert _has_test_token(body) is True


def test_has_test_token_whitespace_stripped():
    """Leading/trailing whitespace is stripped before comparison."""
    body = f"  {TEST_TOKEN}  "
    assert _has_test_token(body) is True


def test_has_test_token_partial_match_not_detected():
    """A partial token string does not match."""
    assert _has_test_token("[AIPASS-TEST]") is False


# ---- _auto_ack_test_email tests ------------------------------


def test_auto_ack_test_email_success(tmp_path):
    """Successful reply + close returns True."""
    branch_path = tmp_path / "testbranch"
    branch_path.mkdir()
    message = {"id": "abc123", "from_email": "@devpulse", "subject": "Ping"}

    with patch("aipass.ai_mail.apps.handlers.dispatch.daemon.subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        result = _auto_ack_test_email(branch_path, "@testbranch", message)

    assert result is True
    assert mock_run.call_count == 2


def test_auto_ack_test_email_reply_failure(tmp_path):
    """Failed reply returns False without attempting close."""
    branch_path = tmp_path / "testbranch"
    branch_path.mkdir()
    message = {"id": "abc123", "from_email": "@devpulse", "subject": "Ping"}

    with patch("aipass.ai_mail.apps.handlers.dispatch.daemon.subprocess.run") as mock_run:
        mock_run.return_value.returncode = 1
        mock_run.return_value.stderr = "error"
        result = _auto_ack_test_email(branch_path, "@testbranch", message)

    assert result is False
    assert mock_run.call_count == 1


def test_auto_ack_test_email_missing_id(tmp_path):
    """Message without id returns False immediately."""
    message = {"from_email": "@devpulse", "subject": "Ping"}
    result = _auto_ack_test_email(tmp_path, "@testbranch", message)
    assert result is False


def test_auto_ack_test_email_missing_sender(tmp_path):
    """Message without from_email or from returns False immediately."""
    message = {"id": "abc123", "subject": "Ping"}
    result = _auto_ack_test_email(tmp_path, "@testbranch", message)
    assert result is False


# ---- scan_and_ack_test_emails tests -------------------------


def test_scan_and_ack_test_emails_acks_matching(tmp_path):
    """Returns count of acked test emails."""
    branch_path = tmp_path / "testbranch"
    ai_mail_local = branch_path / ".ai_mail.local"
    ai_mail_local.mkdir(parents=True)
    inbox = {
        "messages": [
            {"id": "t1", "status": "new", "from_email": "@devpulse", "subject": "test", "body": TEST_TOKEN},
            {"id": "n1", "status": "new", "from_email": "@devpulse", "subject": "work", "body": "do something"},
        ]
    }
    (ai_mail_local / "inbox.json").write_text(json.dumps(inbox), encoding="utf-8")

    with patch("aipass.ai_mail.apps.handlers.dispatch.test_token.auto_ack_test_email", return_value=True) as mock_ack:
        count = scan_and_ack_test_emails(branch_path, "@testbranch")

    assert count == 1
    mock_ack.assert_called_once()


def test_scan_and_ack_test_emails_skips_closed(tmp_path):
    """Closed messages are not scanned."""
    branch_path = tmp_path / "testbranch"
    ai_mail_local = branch_path / ".ai_mail.local"
    ai_mail_local.mkdir(parents=True)
    inbox = {
        "messages": [
            {"id": "t1", "status": "closed", "from_email": "@devpulse", "subject": "test", "body": TEST_TOKEN},
        ]
    }
    (ai_mail_local / "inbox.json").write_text(json.dumps(inbox), encoding="utf-8")

    with patch("aipass.ai_mail.apps.handlers.dispatch.test_token.auto_ack_test_email") as mock_ack:
        count = scan_and_ack_test_emails(branch_path, "@testbranch")

    assert count == 0
    mock_ack.assert_not_called()


def test_scan_and_ack_test_emails_no_inbox(tmp_path):
    """Missing inbox returns 0."""
    branch_path = tmp_path / "testbranch"
    branch_path.mkdir()
    count = scan_and_ack_test_emails(branch_path, "@testbranch")
    assert count == 0
