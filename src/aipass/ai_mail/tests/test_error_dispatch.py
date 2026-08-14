"""Tests for email error dispatch handler -- error report building, dispatch, and delivery callbacks."""

import pytest
from unittest.mock import patch, MagicMock

from aipass.ai_mail.apps.handlers.email.error_dispatch import (
    build_error_report,
    dispatch_send_error,
    on_email_delivered,
)


# ---- Fixtures ------------------------------------------------


@pytest.fixture(autouse=True)
def _silence_json_handler():
    """Prevent log_operation from writing real JSON files during tests."""
    with patch("aipass.ai_mail.apps.handlers.email.error_dispatch.json_handler") as mock_jh:
        mock_jh.log_operation.return_value = True
        yield mock_jh


# ---- build_error_report tests --------------------------------


def test_build_error_report_basic_structure(monkeypatch):
    """Error report contains all required email fields."""
    monkeypatch.setenv("AIPASS_CALLER_BRANCH", "trigger")

    result = build_error_report("@backup", "Deploy task", "Connection refused")

    assert isinstance(result, dict)
    assert result["from"] == "@ai_mail"
    assert result["from_name"] == "AI_MAIL"
    assert result["to"] == "@drone"
    assert result["auto_execute"] is False
    assert result["priority"] == "normal"
    assert result["reply_to"] == "@ai_mail"
    assert "timestamp" in result
    assert len(result["timestamp"]) == 19  # "YYYY-MM-DD HH:MM:SS"


def test_build_error_report_reply_lands_on_the_mailbox_in_the_from_line(monkeypatch):
    """A reply to an error report reaches the sender it names, not a third party.

    reply.py routes a reply to `reply_to or from`, so these two fields together
    decide where an answer lands. @drone replied to one of these reports and it
    arrived at @devpulse -- the dispatcher -- while the message read From: ai_mail
    (reported 2026-08-12, APLAN-0006). Named after the contract, not the value:
    whatever the From line claims is who must receive the answer.
    """
    monkeypatch.setenv("AIPASS_CALLER_BRANCH", "trigger")

    result = build_error_report("@backup", "Deploy task", "Connection refused")

    assert result["reply_to"] == result["from"]


def test_build_error_report_reply_route_ignores_the_failing_sender(monkeypatch):
    """The caller that failed to send is named in the body, never in the reply route.

    The report is about ai_mail's delivery, so the investigation reply belongs to
    ai_mail. The original sender stays evidence in the body.
    """
    monkeypatch.setenv("AIPASS_CALLER_BRANCH", "devpulse")

    result = build_error_report("@backup", "Deploy task", "Connection refused")

    assert result["reply_to"] == "@ai_mail"
    assert "@devpulse" in result["message"]


def test_build_error_report_subject_includes_recipient_and_error(monkeypatch):
    """Subject line contains the failed recipient and truncated error message."""
    monkeypatch.setenv("AIPASS_CALLER_BRANCH", "trigger")

    result = build_error_report("@backup", "Deploy task", "Connection refused")

    assert "@backup" in result["subject"]
    assert "Connection refused" in result["subject"]
    assert result["subject"].startswith("[ERROR]")


def test_build_error_report_message_body_content(monkeypatch):
    """Message body contains sender, recipient, subject, and error details."""
    monkeypatch.setenv("AIPASS_CALLER_BRANCH", "flow")

    result = build_error_report("@memory", "Vectorize data", "Timeout after 120s")

    body = result["message"]
    assert "@flow" in body
    assert "@memory" in body
    assert "Vectorize data" in body
    assert "Timeout after 120s" in body
    assert "auto-dispatched" in body


def test_build_error_report_with_env_var_set(monkeypatch):
    """Uses AIPASS_CALLER_BRANCH env var for sender in the body."""
    monkeypatch.setenv("AIPASS_CALLER_BRANCH", "devpulse")

    result = build_error_report("@flow", "Status check", "Not found")

    assert "@devpulse" in result["message"]


def test_build_error_report_without_env_var(monkeypatch):
    """Defaults to @ai_mail sender in the body when env var is unset."""
    monkeypatch.delenv("AIPASS_CALLER_BRANCH", raising=False)

    result = build_error_report("@flow", "Status check", "Not found")

    assert "@ai_mail" in result["message"]


def test_build_error_report_env_var_with_at_prefix(monkeypatch):
    """Handles AIPASS_CALLER_BRANCH that already has @ prefix."""
    monkeypatch.setenv("AIPASS_CALLER_BRANCH", "@trigger")

    result = build_error_report("@backup", "task", "error")

    # Should normalize to @trigger (not @@trigger)
    assert "@@" not in result["message"]
    assert "@trigger" in result["message"]


def test_build_error_report_long_error_truncated_in_subject(monkeypatch):
    """Error message in subject is truncated to 50 chars."""
    monkeypatch.setenv("AIPASS_CALLER_BRANCH", "trigger")
    long_error = "A" * 100

    result = build_error_report("@backup", "task", long_error)

    # The subject uses error_msg[:50]
    assert len(result["subject"]) < 200  # reasonable length
    assert "A" * 50 in result["subject"]


# ---- dispatch_send_error tests --------------------------------


def test_dispatch_send_error_success(monkeypatch):
    """Returns True when deliver_fn succeeds."""
    monkeypatch.setenv("AIPASS_CALLER_BRANCH", "trigger")
    mock_deliver = MagicMock()

    result = dispatch_send_error("@backup", "task", "error msg", mock_deliver)

    assert result is True
    mock_deliver.assert_called_once()
    args = mock_deliver.call_args[0]
    assert args[0] == "@drone"
    assert isinstance(args[1], dict)
    assert args[1]["to"] == "@drone"


def test_dispatch_send_error_failure_returns_false(monkeypatch):
    """Returns False when deliver_fn raises an exception."""
    monkeypatch.setenv("AIPASS_CALLER_BRANCH", "trigger")
    mock_deliver = MagicMock(side_effect=RuntimeError("network error"))

    result = dispatch_send_error("@backup", "task", "error msg", mock_deliver)

    assert result is False
    mock_deliver.assert_called_once()


def test_dispatch_send_error_passes_correct_email_data(monkeypatch):
    """Verify the email_data dict passed to deliver_fn has expected keys."""
    monkeypatch.setenv("AIPASS_CALLER_BRANCH", "flow")
    captured = {}

    def capture_deliver(target, data):
        """Capture deliver_fn arguments for assertion."""
        captured.update(data)

    dispatch_send_error("@memory", "Vectorize", "Timeout", capture_deliver)

    assert captured["from"] == "@ai_mail"
    assert captured["to"] == "@drone"
    assert "@memory" in captured["subject"]


# ---- on_email_delivered tests --------------------------------


def test_on_email_delivered_with_central_callback():
    """Central callback is invoked when provided."""
    update_fn = MagicMock()

    on_email_delivered(update_central_fn=update_fn)

    update_fn.assert_called_once_with()


def test_on_email_delivered_with_none_callbacks():
    """No error when callback is None."""
    on_email_delivered(None)


def test_on_email_delivered_central_failure_does_not_raise():
    """Central update failure is caught silently."""
    update_fn = MagicMock(side_effect=RuntimeError("central broken"))

    on_email_delivered(update_central_fn=update_fn)

    update_fn.assert_called_once()


def test_on_email_delivered_central_fail_no_exception():
    """Central callback failing does not raise any exception."""
    update_fn = MagicMock(side_effect=RuntimeError("update fail"))

    on_email_delivered(update_central_fn=update_fn)

    update_fn.assert_called_once()
