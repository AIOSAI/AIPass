# =================== AIPass ====================
# Name: test_error_detected.py
# Description: Tests for error_detected event handler with Medic v2 dispatch gating
# Version: 1.1.0
# Created: 2026-04-25
# Modified: 2026-08-07
# =============================================

"""Tests for error_detected event handler: set_send_email_callback, handle_error_detected, and fallback stubs."""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Shared fixture: mocks config + json_handler, provides a registry-available
# environment by default.  Individual tests override module-level helpers
# after importing.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _mock_infrastructure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Mock config, json_handler, error_registry, and wake_branch before import."""
    from aipass.trigger.apps.config import atomic_write_json

    mock_config = MagicMock()
    mock_config.TRIGGER_ROOT = tmp_path
    mock_config.atomic_write_json = atomic_write_json
    monkeypatch.setitem(sys.modules, "aipass.trigger.apps.config", mock_config)

    mock_json_handler = MagicMock()
    mock_json_handler.log_operation = MagicMock(return_value=True)
    json_pkg = MagicMock()
    json_pkg.json_handler = mock_json_handler
    monkeypatch.setitem(sys.modules, "aipass.trigger.apps.handlers.json", json_pkg)
    monkeypatch.setitem(
        sys.modules,
        "aipass.trigger.apps.handlers.json.json_handler",
        mock_json_handler,
    )

    # Provide a working error_registry mock so _REGISTRY_DISPATCH_AVAILABLE=True
    mock_registry = MagicMock()
    mock_registry.circuit_breaker_allows = MagicMock(return_value=True)
    mock_registry.circuit_breaker_record_error = MagicMock()
    mock_registry.should_dispatch = MagicMock(return_value=True)
    mock_registry.record_dispatch = MagicMock()
    monkeypatch.setitem(sys.modules, "aipass.trigger.apps.handlers.error_registry", mock_registry)

    # Mock wake_branch import chain to prevent real imports
    mock_wake = MagicMock()
    mock_wake.wake_branch = MagicMock()
    monkeypatch.setitem(sys.modules, "aipass.ai_mail", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.ai_mail.apps", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.ai_mail.apps.handlers", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.ai_mail.apps.handlers.dispatch", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.ai_mail.apps.handlers.dispatch.wake", mock_wake)

    monkeypatch.delitem(
        sys.modules,
        "aipass.trigger.apps.handlers.events.error_detected",
        raising=False,
    )


def _import_module():
    """Import error_detected module fresh after mocking."""
    import aipass.trigger.apps.handlers.events.error_detected as m

    return m


def _setup_happy_path(mod: object) -> MagicMock:
    """Patch module internals for a successful dispatch and return the send_email mock."""
    send_mock = MagicMock(return_value=True)
    mod._is_medic_enabled = MagicMock(return_value=True)  # type: ignore[attr-defined]
    mod._is_branch_muted = MagicMock(return_value=False)  # type: ignore[attr-defined]
    mod._get_registered_emails = MagicMock(return_value={"@flow", "@spawn"})  # type: ignore[attr-defined]
    mod._send_email = send_mock  # type: ignore[attr-defined]
    mod.circuit_breaker_allows = MagicMock(return_value=True)  # type: ignore[attr-defined]
    mod.registry_should_dispatch = MagicMock(return_value=True)  # type: ignore[attr-defined]
    mod.registry_is_suppressed = MagicMock(return_value=False)  # type: ignore[attr-defined]
    mod.registry_record_dispatch = MagicMock()  # type: ignore[attr-defined]
    mod.circuit_breaker_record_error = MagicMock()  # type: ignore[attr-defined]
    mod._REGISTRY_DISPATCH_AVAILABLE = True  # type: ignore[attr-defined]
    return send_mock


# ---------------------------------------------------------------------------
# set_send_email_callback
# ---------------------------------------------------------------------------


class TestSetSendEmailCallback:
    """Tests for set_send_email_callback."""

    def test_sets_callback(self) -> None:
        """Stores the callback as the module-level _send_email."""
        mod = _import_module()
        callback = MagicMock()
        mod.set_send_email_callback(callback)
        assert mod._send_email is callback

    def test_overwrites_previous_callback(self) -> None:
        """Second call replaces the first callback."""
        mod = _import_module()
        first = MagicMock()
        second = MagicMock()
        mod.set_send_email_callback(first)
        mod.set_send_email_callback(second)
        assert mod._send_email is second


# ---------------------------------------------------------------------------
# handle_error_detected -- early-return gates
# ---------------------------------------------------------------------------


class TestHandleErrorDetectedGates:
    """Tests for early-return gates in handle_error_detected."""

    def test_returns_early_missing_branch(self) -> None:
        """Does not dispatch when branch is None."""
        mod = _import_module()
        send = _setup_happy_path(mod)

        mod.handle_error_detected(branch=None, module="cfg", message="err", error_hash="h1", count=2)

        send.assert_not_called()

    def test_returns_early_missing_module(self) -> None:
        """Does not dispatch when module is None."""
        mod = _import_module()
        send = _setup_happy_path(mod)

        mod.handle_error_detected(branch="flow", module=None, message="err", error_hash="h1", count=2)

        send.assert_not_called()

    def test_returns_early_missing_message(self) -> None:
        """Does not dispatch when message is None."""
        mod = _import_module()
        send = _setup_happy_path(mod)

        mod.handle_error_detected(branch="flow", module="cfg", message=None, error_hash="h1", count=2)

        send.assert_not_called()

    def test_returns_early_missing_error_hash(self) -> None:
        """Does not dispatch when error_hash is None."""
        mod = _import_module()
        send = _setup_happy_path(mod)

        mod.handle_error_detected(branch="flow", module="cfg", message="err", error_hash=None, count=2)

        send.assert_not_called()

    def test_returns_early_medic_disabled(self) -> None:
        """Does not dispatch when medic is disabled."""
        mod = _import_module()
        send = _setup_happy_path(mod)
        mod._is_medic_enabled = MagicMock(return_value=False)  # type: ignore[attr-defined]

        mod.handle_error_detected(branch="flow", module="cfg", message="err", error_hash="h1", count=2)

        send.assert_not_called()

    def test_returns_early_branch_muted(self) -> None:
        """Does not dispatch when branch is muted."""
        mod = _import_module()
        send = _setup_happy_path(mod)
        mod._is_branch_muted = MagicMock(return_value=True)  # type: ignore[attr-defined]

        mod.handle_error_detected(branch="flow", module="cfg", message="err", error_hash="h1", count=2)

        send.assert_not_called()

    def test_returns_early_count_below_threshold(self) -> None:
        """Does not dispatch on first occurrence (count=1)."""
        mod = _import_module()
        send = _setup_happy_path(mod)

        mod.handle_error_detected(branch="flow", module="cfg", message="err", error_hash="h1", count=1)

        send.assert_not_called()

    def test_returns_early_send_email_is_none(self) -> None:
        """Does not dispatch when _send_email callback was never set."""
        mod = _import_module()
        _setup_happy_path(mod)
        mod._send_email = None  # type: ignore[attr-defined]

        mod.handle_error_detected(branch="flow", module="cfg", message="err", error_hash="h1", count=2)

    def test_returns_early_devpulse_recipient(self) -> None:
        """Does not dispatch to @devpulse (protected branch)."""
        mod = _import_module()
        send = _setup_happy_path(mod)
        mod._get_registered_emails = MagicMock(return_value={"@devpulse"})  # type: ignore[attr-defined]

        mod.handle_error_detected(branch="devpulse", module="cfg", message="err", error_hash="h1", count=2)

        send.assert_not_called()

    def test_returns_early_branch_not_in_registry(self) -> None:
        """Does not dispatch when branch email is not in the registry."""
        mod = _import_module()
        send = _setup_happy_path(mod)
        mod._get_registered_emails = MagicMock(return_value={"@api", "@drone"})  # type: ignore[attr-defined]

        mod.handle_error_detected(branch="flow", module="cfg", message="err", error_hash="h1", count=2)

        send.assert_not_called()

    def test_returns_early_circuit_breaker_open(self) -> None:
        """Does not dispatch when circuit breaker is open."""
        mod = _import_module()
        send = _setup_happy_path(mod)
        mod.circuit_breaker_allows = MagicMock(return_value=False)  # type: ignore[attr-defined]

        mod.handle_error_detected(
            branch="flow",
            module="cfg",
            message="err",
            error_hash="h1",
            count=2,
            fingerprint="abc123",
        )

        send.assert_not_called()

    def test_returns_early_should_dispatch_false(self) -> None:
        """Does not dispatch when per-fingerprint backoff rejects."""
        mod = _import_module()
        send = _setup_happy_path(mod)
        mod.registry_should_dispatch = MagicMock(return_value=False)  # type: ignore[attr-defined]

        mod.handle_error_detected(
            branch="flow",
            module="cfg",
            message="err",
            error_hash="h1",
            count=2,
            fingerprint="abc123",
        )

        send.assert_not_called()

    def test_backoff_refusal_logs_as_rate_limit(self) -> None:
        """A backoff refusal is logged to the rate log, not as a suppression."""
        mod = _import_module()
        _setup_happy_path(mod)
        mod.registry_should_dispatch = MagicMock(return_value=False)  # type: ignore[attr-defined]
        rate_log = MagicMock()
        suppression_log = MagicMock()
        mod._write_rate_log = rate_log  # type: ignore[attr-defined]
        mod._write_suppression_log = suppression_log  # type: ignore[attr-defined]

        mod.handle_error_detected(
            branch="flow", module="cfg", message="err", error_hash="h1", count=2, fingerprint="abc123"
        )

        rate_log.assert_called_once()
        suppression_log.assert_not_called()
        assert "Backoff active" in str(rate_log.call_args)

    def test_suppressed_fingerprint_does_not_dispatch(self) -> None:
        """A registry-suppressed fingerprint never dispatches (compass #219)."""
        mod = _import_module()
        send = _setup_happy_path(mod)
        mod.registry_should_dispatch = MagicMock(return_value=False)  # type: ignore[attr-defined]
        mod.registry_is_suppressed = MagicMock(return_value=True)  # type: ignore[attr-defined]

        mod.handle_error_detected(
            branch="flow", module="cfg", message="err", error_hash="h1", count=2, fingerprint="abc123"
        )

        send.assert_not_called()

    def test_suppressed_fingerprint_logs_as_suppression(self) -> None:
        """A suppressed refusal is logged as suppression, not mislabelled as a timing wait."""
        mod = _import_module()
        _setup_happy_path(mod)
        mod.registry_should_dispatch = MagicMock(return_value=False)  # type: ignore[attr-defined]
        mod.registry_is_suppressed = MagicMock(return_value=True)  # type: ignore[attr-defined]
        rate_log = MagicMock()
        suppression_log = MagicMock()
        mod._write_rate_log = rate_log  # type: ignore[attr-defined]
        mod._write_suppression_log = suppression_log  # type: ignore[attr-defined]

        mod.handle_error_detected(
            branch="flow", module="cfg", message="err", error_hash="h1", count=2, fingerprint="abc123"
        )

        suppression_log.assert_called_once()
        rate_log.assert_not_called()
        assert "Suppressed fingerprint" in str(suppression_log.call_args)


# ---------------------------------------------------------------------------
# handle_error_detected -- happy path
# ---------------------------------------------------------------------------


class TestHandleErrorDetectedHappyPath:
    """Tests for successful dispatch through handle_error_detected."""

    def test_sends_email_with_correct_args(self) -> None:
        """Dispatches email to the correct recipient with auto_execute."""
        mod = _import_module()
        send = _setup_happy_path(mod)

        mod.handle_error_detected(
            branch="flow",
            module="config",
            message="NullPointerError",
            error_hash="h1",
            count=2,
            fingerprint="fp123",
            timestamp="2026-04-25 10:00:00",
        )

        send.assert_called_once()
        kwargs = send.call_args[1]
        assert kwargs["to_branch"] == "@flow"
        assert kwargs["auto_execute"] is True
        assert kwargs["reply_to"] == "@devpulse"
        assert kwargs["from_branch"] == "@trigger"

    def test_records_dispatch_after_send(self) -> None:
        """Calls registry_record_dispatch with the fingerprint after sending."""
        mod = _import_module()
        _setup_happy_path(mod)

        mod.handle_error_detected(
            branch="flow",
            module="cfg",
            message="err",
            error_hash="h1",
            count=2,
            fingerprint="fp456",
        )

        mod.registry_record_dispatch.assert_called_once_with("fp456")  # type: ignore[attr-defined]

    def test_logs_dispatch_sent(self) -> None:
        """Logs dispatch_sent via json_handler after successful send."""
        mod = _import_module()
        _setup_happy_path(mod)
        from aipass.trigger.apps.handlers.json import json_handler

        json_handler.log_operation.reset_mock()  # type: ignore[union-attr]

        mod.handle_error_detected(
            branch="flow",
            module="cfg",
            message="err",
            error_hash="h1",
            count=2,
            fingerprint="fp789",
        )

        json_handler.log_operation.assert_called_once_with(  # type: ignore[union-attr]
            "dispatch_sent", {"recipient": "@flow"}
        )

    def test_handles_send_exception_gracefully(self) -> None:
        """Does not raise when _send_email throws."""
        mod = _import_module()
        send = _setup_happy_path(mod)
        send.side_effect = RuntimeError("SMTP down")

        mod.handle_error_detected(
            branch="flow",
            module="cfg",
            message="err",
            error_hash="h1",
            count=2,
            fingerprint="fpX",
        )

    def test_does_not_record_dispatch_when_send_fails(self) -> None:
        """When _send_email returns False, dispatch is not recorded."""
        mod = _import_module()
        send = _setup_happy_path(mod)
        send.return_value = False
        from aipass.trigger.apps.handlers.json import json_handler

        json_handler.log_operation.reset_mock()  # type: ignore[union-attr]

        mod.handle_error_detected(
            branch="flow",
            module="cfg",
            message="err",
            error_hash="h1",
            count=2,
            fingerprint="fp_fail",
        )

        # Email was attempted
        send.assert_called_once()
        # But nothing after it should have run
        json_handler.log_operation.assert_not_called()  # type: ignore[union-attr]
        mod.registry_record_dispatch.assert_not_called()  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Fallback stubs (when error_registry import fails)
# ---------------------------------------------------------------------------


class TestFallbackStubs:
    """Tests for fallback functions defined when error_registry is unavailable."""

    @pytest.fixture(autouse=True)
    def _force_registry_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Set error_registry to None so the ImportError fallback triggers."""
        monkeypatch.setitem(sys.modules, "aipass.trigger.apps.handlers.error_registry", None)
        monkeypatch.delitem(
            sys.modules,
            "aipass.trigger.apps.handlers.events.error_detected",
            raising=False,
        )

    def test_registry_should_dispatch_returns_true(self) -> None:
        """Fallback always allows dispatch for any fingerprint."""
        mod = _import_module()
        assert mod.registry_should_dispatch("any-fingerprint") is True

    def test_registry_is_suppressed_returns_false(self) -> None:
        """Fallback suppresses nothing — no registry means no silencing."""
        mod = _import_module()
        assert mod.registry_is_suppressed("any-fingerprint") is False

    def test_registry_record_dispatch_does_not_raise(self) -> None:
        """Fallback record_dispatch is a no-op."""
        mod = _import_module()
        mod.registry_record_dispatch("any-fingerprint")

    def test_circuit_breaker_allows_returns_true(self) -> None:
        """Fallback circuit breaker always allows."""
        mod = _import_module()
        assert mod.circuit_breaker_allows() is True

    def test_circuit_breaker_record_error_does_not_raise(self) -> None:
        """Fallback circuit_breaker_record_error is a no-op."""
        mod = _import_module()
        mod.circuit_breaker_record_error()

    def test_registry_dispatch_available_is_false(self) -> None:
        """Module reports registry dispatch as unavailable."""
        mod = _import_module()
        assert mod._REGISTRY_DISPATCH_AVAILABLE is False


# ---------------------------------------------------------------------------
# TTL-aware medic enable/disable
# ---------------------------------------------------------------------------


class TestMedicEnabledTTL:
    """Tests for _is_medic_enabled TTL expiry behavior."""

    def test_medic_enabled_ttl_expired(self) -> None:
        """medic_enabled=False with expired TTL -> treated as enabled, dispatch proceeds."""
        mod = _import_module()
        real_is_medic_enabled = mod._is_medic_enabled
        send = _setup_happy_path(mod)
        mod._is_medic_enabled = real_is_medic_enabled  # type: ignore[attr-defined]

        config_file = mod.TRIGGER_CONFIG_FILE
        config_file.parent.mkdir(parents=True, exist_ok=True)
        past = (datetime.now() - timedelta(hours=1)).isoformat()
        config_file.write_text(
            json.dumps(
                {
                    "config": {
                        "medic_enabled": False,
                        "medic_disabled_until": past,
                    }
                }
            ),
            encoding="utf-8",
        )

        mod.handle_error_detected(
            branch="flow",
            module="cfg",
            message="err",
            error_hash="h1",
            count=2,
            fingerprint="fp_ttl_exp",
        )

        send.assert_called_once()

    def test_medic_enabled_ttl_active(self) -> None:
        """medic_enabled=False with future TTL -> medic still disabled, dispatch suppressed."""
        mod = _import_module()
        real_is_medic_enabled = mod._is_medic_enabled
        send = _setup_happy_path(mod)
        mod._is_medic_enabled = real_is_medic_enabled  # type: ignore[attr-defined]

        config_file = mod.TRIGGER_CONFIG_FILE
        config_file.parent.mkdir(parents=True, exist_ok=True)
        future = (datetime.now() + timedelta(hours=1)).isoformat()
        config_file.write_text(
            json.dumps(
                {
                    "config": {
                        "medic_enabled": False,
                        "medic_disabled_until": future,
                    }
                }
            ),
            encoding="utf-8",
        )

        mod.handle_error_detected(
            branch="flow",
            module="cfg",
            message="err",
            error_hash="h1",
            count=2,
            fingerprint="fp_ttl_act",
        )

        send.assert_not_called()


# ---------------------------------------------------------------------------
# Branch mute dict/string format support
# ---------------------------------------------------------------------------


class TestBranchMutedFormats:
    """Tests for _is_branch_muted dict and string format support."""

    def test_branch_muted_dict_format_active(self) -> None:
        """Dict entry with future expires_at -> branch IS muted, dispatch suppressed."""
        mod = _import_module()
        real_is_branch_muted = mod._is_branch_muted
        send = _setup_happy_path(mod)
        mod._is_branch_muted = real_is_branch_muted  # type: ignore[attr-defined]
        mod._get_registered_emails = MagicMock(return_value={"@api", "@flow"})  # type: ignore[attr-defined]

        config_file = mod.TRIGGER_CONFIG_FILE
        config_file.parent.mkdir(parents=True, exist_ok=True)
        future = (datetime.now() + timedelta(hours=1)).isoformat()
        config_file.write_text(
            json.dumps(
                {
                    "config": {
                        "medic_enabled": True,
                        "muted_branches": [{"name": "api", "expires_at": future}],
                    }
                }
            ),
            encoding="utf-8",
        )

        mod.handle_error_detected(
            branch="api",
            module="cfg",
            message="err",
            error_hash="h1",
            count=2,
            fingerprint="fp_mute_act",
        )

        send.assert_not_called()

    def test_branch_muted_dict_format_expired(self) -> None:
        """Dict entry with past expires_at -> branch NOT muted, dispatch proceeds."""
        mod = _import_module()
        real_is_branch_muted = mod._is_branch_muted
        send = _setup_happy_path(mod)
        mod._is_branch_muted = real_is_branch_muted  # type: ignore[attr-defined]
        mod._get_registered_emails = MagicMock(return_value={"@api", "@flow"})  # type: ignore[attr-defined]

        config_file = mod.TRIGGER_CONFIG_FILE
        config_file.parent.mkdir(parents=True, exist_ok=True)
        past = (datetime.now() - timedelta(hours=1)).isoformat()
        config_file.write_text(
            json.dumps(
                {
                    "config": {
                        "medic_enabled": True,
                        "muted_branches": [{"name": "api", "expires_at": past}],
                    }
                }
            ),
            encoding="utf-8",
        )

        mod.handle_error_detected(
            branch="api",
            module="cfg",
            message="err",
            error_hash="h1",
            count=2,
            fingerprint="fp_mute_exp",
        )

        send.assert_called_once()

    def test_branch_muted_plain_string_backcompat(self) -> None:
        """Plain string entry in muted_branches -> branch IS muted (permanent)."""
        mod = _import_module()
        real_is_branch_muted = mod._is_branch_muted
        send = _setup_happy_path(mod)
        mod._is_branch_muted = real_is_branch_muted  # type: ignore[attr-defined]
        mod._get_registered_emails = MagicMock(return_value={"@api", "@flow"})  # type: ignore[attr-defined]

        config_file = mod.TRIGGER_CONFIG_FILE
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_file.write_text(
            json.dumps(
                {
                    "config": {
                        "medic_enabled": True,
                        "muted_branches": ["api"],
                    }
                }
            ),
            encoding="utf-8",
        )

        mod.handle_error_detected(
            branch="api",
            module="cfg",
            message="err",
            error_hash="h1",
            count=2,
            fingerprint="fp_str_perm",
        )

        send.assert_not_called()

    def test_branch_muted_dict_permanent(self) -> None:
        """Dict entry with expires_at=null -> branch IS muted (permanent)."""
        mod = _import_module()
        real_is_branch_muted = mod._is_branch_muted
        send = _setup_happy_path(mod)
        mod._is_branch_muted = real_is_branch_muted  # type: ignore[attr-defined]
        mod._get_registered_emails = MagicMock(return_value={"@api", "@flow"})  # type: ignore[attr-defined]

        config_file = mod.TRIGGER_CONFIG_FILE
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_file.write_text(
            json.dumps(
                {
                    "config": {
                        "medic_enabled": True,
                        "muted_branches": [{"name": "api", "expires_at": None}],
                    }
                }
            ),
            encoding="utf-8",
        )

        mod.handle_error_detected(
            branch="api",
            module="cfg",
            message="err",
            error_hash="h1",
            count=2,
            fingerprint="fp_dict_perm",
        )

        send.assert_not_called()


# ---------------------------------------------------------------------------
# circuit_breaker_probe_succeeded after dispatch
# ---------------------------------------------------------------------------


class TestProbeSucceeded:
    """Tests for circuit_breaker_probe_succeeded called after dispatch."""

    def test_probe_succeeded_called_after_dispatch(self) -> None:
        """circuit_breaker_probe_succeeded is called after successful dispatch with fingerprint."""
        mod = _import_module()
        send = _setup_happy_path(mod)
        mod.circuit_breaker_probe_succeeded = MagicMock()  # type: ignore[attr-defined]

        mod.handle_error_detected(
            branch="flow",
            module="cfg",
            message="err",
            error_hash="h1",
            count=2,
            fingerprint="fp_probe",
        )

        send.assert_called_once()
        mod.registry_record_dispatch.assert_called_once_with("fp_probe")  # type: ignore[attr-defined]
        mod.circuit_breaker_probe_succeeded.assert_called_once()  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Occurrences field fidelity (reported by @drone 2026-08-04)
# ---------------------------------------------------------------------------


class TestOccurrencesReportsTrueCount:
    """The dispatched notification must report the registry count, not a literal 1.

    The call site hardcoded occurrences=1 while threading every other field
    through, so every dispatch told its reader a recurring error was a one-off.
    """

    def test_occurrences_matches_count(self) -> None:
        """Notification body reports the count it was dispatched with."""
        mod = _import_module()
        send = _setup_happy_path(mod)

        mod.handle_error_detected(branch="flow", module="cfg", message="err", error_hash="h1", count=9)

        body = send.call_args.kwargs["message"]
        assert "Occurrences: 9" in body

    def test_occurrences_never_reports_one(self) -> None:
        """Gate 3 requires count >= 2, so a dispatched mail can never truthfully say 1."""
        mod = _import_module()
        send = _setup_happy_path(mod)

        mod.handle_error_detected(branch="flow", module="cfg", message="err", error_hash="h1", count=2)

        body = send.call_args.kwargs["message"]
        assert "Occurrences: 1" not in body
        assert "Occurrences: 2" in body

    def test_occurrences_consistent_with_seen_window(self) -> None:
        """A count spanning a first/last-seen window stays internally consistent.

        The inconsistency @drone spotted -- 'Occurrences: 1' against a month-long
        window -- was the tell that two different sources fed one payload.
        """
        mod = _import_module()
        send = _setup_happy_path(mod)

        mod.handle_error_detected(
            branch="flow",
            module="cfg",
            message="err",
            error_hash="h1",
            count=9,
            first_seen="2026-07-06T08:13:26",
            last_seen="2026-08-04T18:27:38",
        )

        body = send.call_args.kwargs["message"]
        assert "Occurrences: 9" in body
        assert "First seen: 2026-07-06T08:13:26" in body
        assert "Last seen: 2026-08-04T18:27:38" in body
