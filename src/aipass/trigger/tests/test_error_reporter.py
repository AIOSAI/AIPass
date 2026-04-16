"""Tests for the error_reporter handler (apps/handlers/error_reporter.py)."""

# =================== META ====================
# Name: test_error_reporter.py
# Description: Unit tests for error_reporter handler
# Version: 1.0.0
# Created: 2026-04-03
# Modified: 2026-04-03
# =============================================

import sys
import pytest
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _mock_infrastructure(monkeypatch):
    """Mock heavy infrastructure imports before error_reporter module loads."""

    mock_logger = MagicMock()
    mock_logger.info = MagicMock()
    mock_logger.warning = MagicMock()

    # -- prax logger --------------------------------------------------------
    prax_mod = MagicMock()
    prax_mod.logger = mock_logger
    monkeypatch.setitem(sys.modules, "aipass.prax", prax_mod)
    monkeypatch.setitem(sys.modules, "aipass.prax.apps", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.prax.apps.modules", MagicMock())
    prax_logger_mod = MagicMock()
    prax_logger_mod.get_direct_logger = MagicMock(return_value=mock_logger)
    prax_logger_mod.system_logger = mock_logger
    monkeypatch.setitem(sys.modules, "aipass.prax.apps.modules.logger", prax_logger_mod)

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
    registry_mod = MagicMock()
    registry_mod.report = mock_registry_report
    monkeypatch.setitem(sys.modules, "aipass.trigger.apps.handlers.error_registry", registry_mod)

    # -- trigger json handler -----------------------------------------------
    mock_json_handler = MagicMock()
    mock_json_handler.log_operation = MagicMock(return_value=True)
    json_pkg = MagicMock()
    json_pkg.json_handler = mock_json_handler
    monkeypatch.setitem(sys.modules, "aipass.trigger.apps.handlers.json", json_pkg)
    json_mod = MagicMock()
    json_mod.log_operation = mock_json_handler.log_operation
    monkeypatch.setitem(sys.modules, "aipass.trigger.apps.handlers.json.json_handler", json_mod)

    # -- trigger config (needed by error_registry import chain) -------------
    from aipass.trigger.apps.config import atomic_write_json

    config_mock = MagicMock()
    config_mock.atomic_write_json = atomic_write_json
    monkeypatch.setitem(sys.modules, "aipass.trigger.apps.config", config_mock)

    # -- Force re-import so mocks take effect -------------------------------
    monkeypatch.delitem(sys.modules, "aipass.trigger.apps.handlers.error_reporter", raising=False)


def _import_reporter():
    """Import error_reporter module fresh (after mocks are in place)."""
    import aipass.trigger.apps.handlers.error_reporter as mod

    return mod


def _get_registry_report():
    """Return the mocked registry report function."""
    return sys.modules["aipass.trigger.apps.handlers.error_registry"].report


def _get_json_handler():
    """Return the mocked json_handler."""
    return sys.modules["aipass.trigger.apps.handlers.json"].json_handler


# ---------------------------------------------------------------------------
# Tests -- send_source_fix_email
# ---------------------------------------------------------------------------


class TestSendSourceFixEmail:
    """Tests for the send_source_fix_email function."""

    def test_successful_send(self, monkeypatch):
        """send_source_fix_email returns True when email delivery succeeds."""
        reporter = _import_reporter()

        mock_deliver = MagicMock(return_value=(True, "delivered"))
        email_mod = MagicMock()
        email_mod.deliver_email_to_branch = mock_deliver
        monkeypatch.setitem(sys.modules, "aipass.ai_mail", MagicMock())
        monkeypatch.setitem(sys.modules, "aipass.ai_mail.apps", MagicMock())
        monkeypatch.setitem(sys.modules, "aipass.ai_mail.apps.modules", MagicMock())
        monkeypatch.setitem(sys.modules, "aipass.ai_mail.apps.modules.email", email_mod)

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

    def test_ai_mail_unavailable_returns_false(self, monkeypatch):
        """send_source_fix_email returns False when ai_mail import fails."""
        reporter = _import_reporter()

        # Setting a sys.modules entry to None tells Python the import failed,
        # causing ImportError on 'from aipass.ai_mail.apps.modules.email import ...'
        monkeypatch.setitem(sys.modules, "aipass.ai_mail.apps.modules.email", None)

        entry = {
            "component": "flow",
            "fingerprint": "abc123",
            "error_type": "ImportError",
            "message": "test",
        }
        result = reporter.send_source_fix_email(entry)

        assert result is False

    def test_deliver_failure_returns_false(self, monkeypatch):
        """send_source_fix_email returns False when deliver_email_to_branch fails."""
        reporter = _import_reporter()

        mock_deliver = MagicMock(return_value=(False, "delivery failed"))
        email_mod = MagicMock()
        email_mod.deliver_email_to_branch = mock_deliver
        monkeypatch.setitem(sys.modules, "aipass.ai_mail", MagicMock())
        monkeypatch.setitem(sys.modules, "aipass.ai_mail.apps", MagicMock())
        monkeypatch.setitem(sys.modules, "aipass.ai_mail.apps.modules", MagicMock())
        monkeypatch.setitem(sys.modules, "aipass.ai_mail.apps.modules.email", email_mod)

        entry = {
            "component": "flow",
            "fingerprint": "abc123def456789",
            "error_type": "ImportError",
            "message": "No module named foo",
        }
        result = reporter.send_source_fix_email(entry)

        assert result is False

    def test_deliver_exception_returns_false(self, monkeypatch):
        """send_source_fix_email returns False when deliver raises an exception."""
        reporter = _import_reporter()

        mock_deliver = MagicMock(side_effect=RuntimeError("connection refused"))
        email_mod = MagicMock()
        email_mod.deliver_email_to_branch = mock_deliver
        monkeypatch.setitem(sys.modules, "aipass.ai_mail", MagicMock())
        monkeypatch.setitem(sys.modules, "aipass.ai_mail.apps", MagicMock())
        monkeypatch.setitem(sys.modules, "aipass.ai_mail.apps.modules", MagicMock())
        monkeypatch.setitem(sys.modules, "aipass.ai_mail.apps.modules.email", email_mod)

        entry = {
            "component": "flow",
            "fingerprint": "abc123",
            "error_type": "ImportError",
            "message": "test",
        }
        result = reporter.send_source_fix_email(entry)

        assert result is False

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
        email_mod = MagicMock()
        email_mod.deliver_email_to_branch = mock_deliver
        monkeypatch.setitem(sys.modules, "aipass.ai_mail", MagicMock())
        monkeypatch.setitem(sys.modules, "aipass.ai_mail.apps", MagicMock())
        monkeypatch.setitem(sys.modules, "aipass.ai_mail.apps.modules", MagicMock())
        monkeypatch.setitem(sys.modules, "aipass.ai_mail.apps.modules.email", email_mod)

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
        trigger_mod = MagicMock()
        trigger_mod.trigger = mock_trigger
        monkeypatch.setitem(sys.modules, "aipass.trigger.apps.modules.core", trigger_mod)

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
        trigger_mod = MagicMock()
        trigger_mod.trigger = mock_trigger
        monkeypatch.setitem(sys.modules, "aipass.trigger.apps.modules.core", trigger_mod)

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
        trigger_mod = MagicMock()
        trigger_mod.trigger = mock_trigger
        monkeypatch.setitem(sys.modules, "aipass.trigger.apps.modules.core", trigger_mod)

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
        trigger_mod = MagicMock()
        trigger_mod.trigger = mock_trigger
        monkeypatch.setitem(sys.modules, "aipass.trigger.apps.modules.core", trigger_mod)

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
        trigger_mod = MagicMock()
        trigger_mod.trigger = mock_trigger
        monkeypatch.setitem(sys.modules, "aipass.trigger.apps.modules.core", trigger_mod)

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
        trigger_mod = MagicMock()
        trigger_mod.trigger = mock_trigger
        monkeypatch.setitem(sys.modules, "aipass.trigger.apps.modules.core", trigger_mod)

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
        trigger_mod = MagicMock()
        trigger_mod.trigger = mock_trigger
        monkeypatch.setitem(sys.modules, "aipass.trigger.apps.modules.core", trigger_mod)

        result = reporter.report_error("ImportError", "No module foo", "FLOW")

        assert result["dispatched"] is False

    def test_calls_registry_report_with_correct_args(self):
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
            log_path="/var/log/api.log",
            severity="high",
            fire_event=False,
        )

        registry_report.assert_called_once_with(
            error_type="TimeoutError",
            message="Connection timed out",
            component="API",
            log_path="/var/log/api.log",
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
        trigger_mod = MagicMock()
        trigger_mod.trigger = mock_trigger
        monkeypatch.setitem(sys.modules, "aipass.trigger.apps.modules.core", trigger_mod)

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

    def test_fire_event_passes_all_kwargs(self, monkeypatch):
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
        trigger_mod = MagicMock()
        trigger_mod.trigger = mock_trigger
        monkeypatch.setitem(sys.modules, "aipass.trigger.apps.modules.core", trigger_mod)

        reporter.report_error("ValueError", "bad value", "DRONE", log_path="/logs/drone.log")

        fire_call = mock_trigger.fire.call_args
        assert fire_call[0][0] == "error_detected"
        assert fire_call[1]["branch"] == "DRONE"
        assert fire_call[1]["module"] == "ValueError"
        assert fire_call[1]["message"] == "bad value"
        assert fire_call[1]["log_path"] == "/logs/drone.log"
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
        """Even when trigger.fire fails, json_handler.log_operation is still called."""
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
        trigger_mod = MagicMock()
        trigger_mod.trigger = mock_trigger
        monkeypatch.setitem(sys.modules, "aipass.trigger.apps.modules.core", trigger_mod)

        reporter.report_error("ImportError", "No module foo", "FLOW")

        jh = _get_json_handler()
        jh.log_operation.assert_called_once()
