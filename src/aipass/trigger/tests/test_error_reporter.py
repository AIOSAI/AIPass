# =================== META ====================
# Name: test_error_reporter.py
# Description: Unit tests for error_reporter handler
# Version: 1.1.0
# Created: 2026-04-03
# Modified: 2026-09-28
# =============================================

"""Tests for the error_reporter handler (apps/handlers/error_reporter.py)."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(covered_elsewhere) — how report() fingerprints and stores a row: tests/test_error_registry.py
# seedgo: no-test-needed(covered_elsewhere) — what error_detected does once fired: tests/test_error_detected.py

import pytest
from unittest.mock import MagicMock

from aipass.ai_mail.apps.modules import email_send
from aipass.trigger.apps.handlers import error_reporter
from aipass.trigger.apps.handlers.json import json_handler
from aipass.trigger.apps.modules import core


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


_RECORDERS: dict = {}


@pytest.fixture(autouse=True)
def _mock_infrastructure(monkeypatch):
    """Replace every edge error_reporter reaches, at the home of each name.

    The registry, the operation log, the event bus and ai_mail are all live:
    the registry writes trigger_json/error_registry.json, the bus's
    error_detected handler dispatches, and deliver_email_to_branch sends real
    mail. Each is a recorder here for every test, not only the ones that set
    their own. The two lazy imports inside the handler read core.trigger and
    email_send.deliver_email_to_branch at call time, so those homes are patched.
    """
    monkeypatch.setattr(error_reporter, "logger", MagicMock())

    # -- error_registry -----------------------------------------------------
    mock_registry_report = MagicMock(
        return_value={
            "id": "test-id-123",
            "fingerprint": "abc123def456",
            "is_new": True,
            "count": 1,
            "first_seen": "2026-04-03 10:00:00",
            "last_seen": "2026-04-03 10:00:00",
            "error_type": "ImportError",
            "message": "No module named foo",
            "component": "FLOW",
        }
    )
    monkeypatch.setattr(error_reporter, "_registry_report", mock_registry_report)
    _RECORDERS["registry_report"] = mock_registry_report

    # -- trigger json handler: the operation log is live, record instead -----
    json_recorder = MagicMock()
    json_recorder.log_operation.return_value = True
    monkeypatch.setattr(json_handler, "log_operation", json_recorder.log_operation)
    _RECORDERS["json_handler"] = json_recorder

    # -- the event bus and real mail: recorders unless a test sets its own ---
    monkeypatch.setattr(core, "trigger", MagicMock())
    monkeypatch.setattr(email_send, "deliver_email_to_branch", MagicMock(return_value=(True, "recorded")))


def _import_reporter():
    """The error_reporter module, imported once at the top of this file."""
    return error_reporter


def _get_registry_report():
    """Return the recorder standing in for the registry's report inside error_reporter."""
    return _RECORDERS["registry_report"]


def _get_json_handler():
    """Return the recorder whose log_operation stands in json_handler's at its home."""
    return _RECORDERS["json_handler"]


# ---------------------------------------------------------------------------
# Tests -- send_source_fix_email
# ---------------------------------------------------------------------------


class TestSendSourceFixEmail:
    """Tests for the send_source_fix_email function."""

    def test_successful_send(self, monkeypatch):
        """send_source_fix_email returns True when email delivery succeeds."""
        reporter = _import_reporter()

        mock_deliver = MagicMock(return_value=(True, "delivered"))
        monkeypatch.setattr(email_send, "deliver_email_to_branch", mock_deliver)

        entry = {
            "component": "flow",
            "fingerprint": "abc123def456789",
            "error_type": "ImportError",
            "message": "No module named foo",
            "suppress_reason": "Non-critical import",
            "log_path": "/var/log/test.log",
            "count": 5,
        }
        result = reporter.send_source_fix_email(entry)

        assert result is True
        mock_deliver.assert_called_once()
        # Check the recipient was @flow
        call_args = mock_deliver.call_args
        assert call_args[0][0] == "@flow"

    def test_empty_component_returns_false(self):
        """send_source_fix_email returns False when component is empty."""
        reporter = _import_reporter()

        entry = {"component": "", "error_type": "ImportError", "message": "test"}
        result = reporter.send_source_fix_email(entry)

        assert result is False

    def test_unknown_component_returns_false(self):
        """send_source_fix_email returns False when component is 'unknown'."""
        reporter = _import_reporter()

        entry = {"component": "unknown", "error_type": "ImportError", "message": "test"}
        result = reporter.send_source_fix_email(entry)

        assert result is False

    def test_unknown_component_case_insensitive(self):
        """send_source_fix_email returns False for 'UNKNOWN' (case insensitive)."""
        reporter = _import_reporter()

        entry = {"component": "UNKNOWN", "error_type": "ImportError", "message": "test"}
        result = reporter.send_source_fix_email(entry)

        assert result is False

    def test_ai_mail_unavailable_returns_none(self, monkeypatch):
        """send_source_fix_email returns None, the failed-send answer, when ai_mail import fails.

        False is "nothing to send" (no branch named); a send that could not be
        attempted must not read the same. Red first 2026-09-27 against the
        handler's `return False`.
        """
        reporter = _import_reporter()

        # The name gone from its home makes the handler's lazy
        # 'from aipass.ai_mail.apps.modules.email_send import ...' raise ImportError.
        monkeypatch.delattr(email_send, "deliver_email_to_branch")

        entry = {
            "component": "flow",
            "fingerprint": "abc123",
            "error_type": "ImportError",
            "message": "test",
        }
        result = reporter.send_source_fix_email(entry)

        assert result is None

    def test_deliver_failure_returns_none(self, monkeypatch):
        """send_source_fix_email returns None when deliver_email_to_branch refuses the mail.

        Red first 2026-09-27 against `return success` handing back the refusal's False.
        """
        reporter = _import_reporter()

        mock_deliver = MagicMock(return_value=(False, "delivery failed"))
        monkeypatch.setattr(email_send, "deliver_email_to_branch", mock_deliver)

        entry = {
            "component": "flow",
            "fingerprint": "abc123def456789",
            "error_type": "ImportError",
            "message": "No module named foo",
        }
        result = reporter.send_source_fix_email(entry)

        assert result is None

    def test_deliver_exception_returns_none(self, monkeypatch):
        """send_source_fix_email returns None when deliver raises an exception.

        Red first 2026-09-27 against the handler's `return False`.
        """
        reporter = _import_reporter()

        mock_deliver = MagicMock(side_effect=RuntimeError("connection refused"))
        monkeypatch.setattr(email_send, "deliver_email_to_branch", mock_deliver)

        entry = {
            "component": "flow",
            "fingerprint": "abc123",
            "error_type": "ImportError",
            "message": "test",
        }
        result = reporter.send_source_fix_email(entry)

        assert result is None

    def test_missing_component_key_returns_false(self):
        """send_source_fix_email returns False when entry has no component key."""
        reporter = _import_reporter()

        entry = {"error_type": "ImportError", "message": "test"}
        result = reporter.send_source_fix_email(entry)

        assert result is False

    def test_email_contains_correct_subject(self, monkeypatch):
        """The email data contains the correct subject line format."""
        reporter = _import_reporter()

        mock_deliver = MagicMock(return_value=(True, "ok"))
        monkeypatch.setattr(email_send, "deliver_email_to_branch", mock_deliver)

        entry = {
            "component": "api",
            "fingerprint": "abc123def456",
            "error_type": "TimeoutError",
            "message": "Connection timed out",
        }
        reporter.send_source_fix_email(entry)

        call_args = mock_deliver.call_args
        email_data = call_args[0][1]
        assert email_data["subject"] == "[LOG FIX] TimeoutError classified as non-critical"
        assert email_data["from"] == "@trigger"
        assert email_data["to"] == "@api"


# ---------------------------------------------------------------------------
# Tests -- report_error
# ---------------------------------------------------------------------------


class TestReportError:
    """Tests for the report_error function."""

    def test_new_error_fires_event(self, monkeypatch):
        """report_error fires error_detected event when is_new=True."""
        reporter = _import_reporter()
        registry_report = _get_registry_report()
        registry_report.return_value = {
            "id": "new-id",
            "fingerprint": "fp123",
            "is_new": True,
            "count": 1,
            "first_seen": "2026-04-03 10:00:00",
            "last_seen": "2026-04-03 10:00:00",
        }

        mock_trigger = MagicMock()
        monkeypatch.setattr(core, "trigger", mock_trigger)

        result = reporter.report_error("ImportError", "No module foo", "FLOW")

        mock_trigger.fire.assert_called_once()
        assert result["dispatched"] is True

    def test_count_2_fires_event(self, monkeypatch):
        """report_error fires event when count==2 (second occurrence)."""
        reporter = _import_reporter()
        registry_report = _get_registry_report()
        registry_report.return_value = {
            "id": "existing-id",
            "fingerprint": "fp456",
            "is_new": False,
            "count": 2,
            "first_seen": "2026-04-03 09:00:00",
            "last_seen": "2026-04-03 10:00:00",
        }

        mock_trigger = MagicMock()
        monkeypatch.setattr(core, "trigger", mock_trigger)

        result = reporter.report_error("ImportError", "No module foo", "FLOW")

        mock_trigger.fire.assert_called_once()
        assert result["dispatched"] is True

    def test_count_3_fires_event(self, monkeypatch):
        """report_error fires event at count=3 — handler decides dispatch via backoff."""
        reporter = _import_reporter()
        registry_report = _get_registry_report()
        registry_report.return_value = {
            "id": "existing-id",
            "fingerprint": "fp789",
            "is_new": False,
            "count": 3,
            "first_seen": "2026-04-03 09:00:00",
            "last_seen": "2026-04-03 10:00:00",
        }

        mock_trigger = MagicMock()
        monkeypatch.setattr(core, "trigger", mock_trigger)

        result = reporter.report_error("ImportError", "No module foo", "FLOW")

        mock_trigger.fire.assert_called_once()
        assert result["dispatched"] is True

    def test_count_5_fires_event(self, monkeypatch):
        """report_error fires event at count=5 — handler decides dispatch via backoff."""
        reporter = _import_reporter()
        registry_report = _get_registry_report()
        registry_report.return_value = {
            "id": "existing-id",
            "fingerprint": "fp999",
            "is_new": False,
            "count": 5,
            "first_seen": "2026-04-03 09:00:00",
            "last_seen": "2026-04-03 10:00:00",
        }

        mock_trigger = MagicMock()
        monkeypatch.setattr(core, "trigger", mock_trigger)

        result = reporter.report_error("ImportError", "No module foo", "FLOW")

        mock_trigger.fire.assert_called_once()
        assert result["dispatched"] is True

    def test_fire_event_false_never_fires(self, monkeypatch):
        """report_error with fire_event=False never fires an event."""
        reporter = _import_reporter()
        registry_report = _get_registry_report()
        registry_report.return_value = {
            "id": "new-id",
            "fingerprint": "fp000",
            "is_new": True,
            "count": 1,
            "first_seen": "2026-04-03 10:00:00",
            "last_seen": "2026-04-03 10:00:00",
        }

        mock_trigger = MagicMock()
        monkeypatch.setattr(core, "trigger", mock_trigger)

        result = reporter.report_error("ImportError", "No module foo", "FLOW", fire_event=False)

        mock_trigger.fire.assert_not_called()
        assert result["dispatched"] is False

    def test_returns_correct_dict_shape(self, monkeypatch):
        """report_error returns dict with is_new, count, and dispatched keys."""
        reporter = _import_reporter()
        registry_report = _get_registry_report()
        registry_report.return_value = {
            "id": "test-id",
            "fingerprint": "fp111",
            "is_new": True,
            "count": 1,
            "first_seen": "2026-04-03 10:00:00",
            "last_seen": "2026-04-03 10:00:00",
        }

        mock_trigger = MagicMock()
        monkeypatch.setattr(core, "trigger", mock_trigger)

        result = reporter.report_error("ImportError", "No module foo", "FLOW")

        assert "is_new" in result
        assert "count" in result
        assert "dispatched" in result
        assert result["is_new"] is True
        assert result["count"] == 1
        assert result["dispatched"] is True

    def test_fire_event_exception_sets_dispatched_false(self, monkeypatch):
        """report_error sets dispatched=False when trigger.fire raises an exception."""
        reporter = _import_reporter()
        registry_report = _get_registry_report()
        registry_report.return_value = {
            "id": "test-id",
            "fingerprint": "fp222",
            "is_new": True,
            "count": 1,
            "first_seen": "2026-04-03 10:00:00",
            "last_seen": "2026-04-03 10:00:00",
        }

        mock_trigger = MagicMock()
        mock_trigger.fire.side_effect = RuntimeError("event bus failure")
        monkeypatch.setattr(core, "trigger", mock_trigger)

        result = reporter.report_error("ImportError", "No module foo", "FLOW")

        assert result["dispatched"] is False

    def test_calls_registry_report_with_correct_args(self, tmp_path):
        """report_error calls _registry_report with the correct arguments."""
        reporter = _import_reporter()
        registry_report = _get_registry_report()
        registry_report.return_value = {
            "id": "test-id",
            "fingerprint": "fp333",
            "is_new": False,
            "count": 10,
        }

        reporter.report_error(
            error_type="TimeoutError",
            message="Connection timed out",
            component="API",
            log_path=str(tmp_path / "api.log"),
            severity="high",
            fire_event=False,
        )

        registry_report.assert_called_once_with(
            error_type="TimeoutError",
            message="Connection timed out",
            component="API",
            log_path=str(tmp_path / "api.log"),
            severity="high",
        )

    def test_logs_operation_on_successful_dispatch(self, monkeypatch):
        """report_error logs the error_reported operation after successful dispatch."""
        reporter = _import_reporter()
        registry_report = _get_registry_report()
        registry_report.return_value = {
            "id": "test-id",
            "fingerprint": "fp444",
            "is_new": True,
            "count": 1,
            "first_seen": "2026-04-03 10:00:00",
            "last_seen": "2026-04-03 10:00:00",
        }

        mock_trigger = MagicMock()
        monkeypatch.setattr(core, "trigger", mock_trigger)

        reporter.report_error("ImportError", "No module foo", "FLOW")

        jh = _get_json_handler()
        jh.log_operation.assert_called_with("error_reported", {"branch": "FLOW", "error_type": "ImportError"})

    def test_does_not_log_operation_when_no_dispatch(self):
        """report_error does NOT log operation when fire_event=False (early return)."""
        reporter = _import_reporter()
        registry_report = _get_registry_report()
        registry_report.return_value = {
            "id": "test-id",
            "fingerprint": "fp555",
            "is_new": False,
            "count": 10,
        }

        reporter.report_error("ImportError", "No module foo", "FLOW", fire_event=False)

        jh = _get_json_handler()
        jh.log_operation.assert_not_called()

    def test_fire_event_passes_all_kwargs(self, monkeypatch, tmp_path):
        """report_error passes correct kwargs to trigger.fire."""
        reporter = _import_reporter()
        registry_report = _get_registry_report()
        registry_report.return_value = {
            "id": "unique-id-42",
            "fingerprint": "fp666aabbcc",
            "is_new": True,
            "count": 1,
            "first_seen": "2026-04-03 09:00:00",
            "last_seen": "2026-04-03 09:30:00",
        }

        mock_trigger = MagicMock()
        monkeypatch.setattr(core, "trigger", mock_trigger)

        reporter.report_error("ValueError", "bad value", "DRONE", log_path=str(tmp_path / "drone.log"))

        fire_call = mock_trigger.fire.call_args
        assert fire_call[0][0] == "error_detected"
        assert fire_call[1]["branch"] == "DRONE"
        assert fire_call[1]["module"] == "ValueError"
        assert fire_call[1]["message"] == "bad value"
        assert fire_call[1]["log_path"] == str(tmp_path / "drone.log")
        assert fire_call[1]["error_hash"] == "unique-id-42"
        assert fire_call[1]["fingerprint"] == "fp666aabbcc"
        assert fire_call[1]["registry_id"] == "unique-id-42"
        assert fire_call[1]["first_seen"] == "2026-04-03 09:00:00"
        assert fire_call[1]["last_seen"] == "2026-04-03 09:30:00"
        assert fire_call[1]["count"] == 1

    def test_default_severity_is_medium(self):
        """report_error passes severity='medium' by default."""
        reporter = _import_reporter()
        registry_report = _get_registry_report()
        registry_report.return_value = {
            "id": "test-id",
            "fingerprint": "fp777",
            "is_new": False,
            "count": 10,
        }

        reporter.report_error("ImportError", "No module foo", "FLOW", fire_event=False)

        registry_report.assert_called_once_with(
            error_type="ImportError",
            message="No module foo",
            component="FLOW",
            log_path="",
            severity="medium",
        )

    def test_report_error_returns_registry_data(self):
        """report_error passes through all registry data in return dict."""
        reporter = _import_reporter()
        registry_report = _get_registry_report()
        registry_report.return_value = {
            "id": "special-id",
            "fingerprint": "fp888",
            "is_new": False,
            "count": 7,
            "custom_field": "preserved",
        }

        result = reporter.report_error("RuntimeError", "something broke", "BACKUP", fire_event=False)

        assert result["id"] == "special-id"
        assert result["fingerprint"] == "fp888"
        assert result["count"] == 7
        assert result["custom_field"] == "preserved"
        assert result["dispatched"] is False

    def test_fire_event_failure_still_logs_operation(self, monkeypatch):
        """Even when trigger.fire fails, json_handler.log_operation is still called.

        Mutant run 2026-09-27: log_operation logs branch=error_type -> red.
        """
        reporter = _import_reporter()
        registry_report = _get_registry_report()
        registry_report.return_value = {
            "id": "test-id",
            "fingerprint": "fp999",
            "is_new": True,
            "count": 1,
            "first_seen": "2026-04-03 10:00:00",
            "last_seen": "2026-04-03 10:00:00",
        }

        mock_trigger = MagicMock()
        mock_trigger.fire.side_effect = RuntimeError("bus down")
        monkeypatch.setattr(core, "trigger", mock_trigger)

        reporter.report_error("ImportError", "No module foo", "FLOW")

        jh = _get_json_handler()
        jh.log_operation.assert_called_once_with("error_reported", {"branch": "FLOW", "error_type": "ImportError"})
