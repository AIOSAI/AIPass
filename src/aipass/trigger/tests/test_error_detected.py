# =================== META ====================
# Name: test_error_detected.py
# Description: Tests for error_detected event handler with Medic v2 dispatch gating
# Version: 1.5.0
# Created: 2026-04-25
# Modified: 2026-11-16
# =============================================

"""Tests for apps/handlers/events/error_detected.py and the dispatch gates it runs."""

# The declared pass — what is NOT tested here, and what covers it instead:
# sentry: no-test-needed(covered_elsewhere) — what should_dispatch and is_suppressed decide, in error_registry
# sentry: no-test-needed(covered_elsewhere) — the digest body and the aged lane, in test_escalation.py
# sentry: no-test-needed(covered_elsewhere) — the two producers of this event, log_watcher and the catch-up scan
# sentry: no-test-needed(external) — ai_mail delivery and wake_branch; AIPass tests only its own files
# sentry: no-test-needed(constant) — the fixed investigation-step prose _build_notification_message() wraps

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List
from unittest.mock import MagicMock

import pytest
import aipass.ai_mail as ai_mail
import aipass.trigger.apps.handlers as handlers_pkg
import aipass.trigger.apps.handlers.error_registry as error_registry
import aipass.trigger.apps.handlers.events.error_detected as error_detected
from aipass.prax import trail
from aipass.trigger.apps.handlers import escalation, medic_state

# wake_branch's home module, reached through the door (the handlers fence refuses a direct import).
# The door reads it there on every access, so a patch on it reaches error_detected's lazy import.
WAKE_HOME = sys.modules[ai_mail.wake_branch.__module__]


@pytest.fixture(autouse=True)
def _mock_infrastructure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Put the real error_detected module on tmp_path and recording stubs.
    Every outside edge is swapped with monkeypatch.setattr, so teardown restores direct assignments.
    normalize_message stays real: a mock returns one object for every input,
    so a shared-signature assertion passes vacuously.
    """
    json_dir = tmp_path / "trigger_json"
    monkeypatch.setattr(error_registry, "REGISTRY_FILE", json_dir / "error_registry.json")
    monkeypatch.setattr(error_registry, "CB_STATE_FILE", json_dir / "trigger_cb_state.json")
    monkeypatch.setattr(error_registry, "report", MagicMock(return_value={"is_new": False}))
    monkeypatch.setattr(error_registry, "is_suppressed", MagicMock(return_value=False))
    monkeypatch.setattr(error_registry, "get_dispatch_count", MagicMock(return_value=0))
    monkeypatch.setattr(WAKE_HOME, "wake_branch", MagicMock())

    monkeypatch.setattr(error_detected, "_send_email", None)
    monkeypatch.setattr(error_detected, "breaker_gate", MagicMock(return_value=""))
    monkeypatch.setattr(error_detected, "circuit_breaker_delivered", MagicMock())
    monkeypatch.setattr(error_detected, "circuit_breaker_send_failed", MagicMock())
    monkeypatch.setattr(error_detected, "circuit_breaker_held", MagicMock(return_value={}))
    monkeypatch.setattr(error_detected, "registry_should_dispatch", MagicMock(return_value=True))
    monkeypatch.setattr(error_detected, "registry_record_dispatch", MagicMock())
    monkeypatch.setattr(error_detected, "registry_is_suppressed", MagicMock(return_value=False))
    monkeypatch.setattr(error_detected.json_handler, "log_operation", MagicMock(return_value=True))
    monkeypatch.setattr(medic_state, "MEDIC_STATE_FILE", json_dir / "medic_state.json")
    monkeypatch.setattr(medic_state, "LEGACY_MEDIC_STATE_FILE", json_dir / "trigger_config.json")
    monkeypatch.setattr(medic_state, "logger", MagicMock())
    monkeypatch.setattr(error_detected, "BRANCH_REGISTRY_FILE", tmp_path / "AIPASS_REGISTRY.json")
    monkeypatch.setattr(error_detected, "TRIGGER_ROOT", tmp_path)
    monkeypatch.setattr(error_detected, "logger", MagicMock())
    monkeypatch.setattr(error_detected, "_dispatch_timestamps", {})
    # Tests assign over these directly; setattr them first so teardown undoes it.
    for name in (
        "_is_medic_enabled",
        "_is_branch_muted",
        "_get_registered_emails",
        "_write_suppression_log",
        "_write_rate_log",
    ):
        monkeypatch.setattr(error_detected, name, getattr(error_detected, name))


def _import_module():
    """Return the error_detected module; the autouse fixture has already patched its edges."""
    return error_detected


def _setup_happy_path(mod: object) -> MagicMock:
    """Patch module internals for a successful dispatch and return the send_email mock."""
    send_mock = MagicMock(return_value=True)
    mod._is_medic_enabled = MagicMock(return_value=True)  # type: ignore[attr-defined]
    mod._is_branch_muted = MagicMock(return_value=False)  # type: ignore[attr-defined]
    mod._get_registered_emails = MagicMock(return_value={"@flow", "@spawn"})  # type: ignore[attr-defined]
    mod._send_email = send_mock  # type: ignore[attr-defined]
    mod.breaker_gate = MagicMock(return_value="")  # type: ignore[attr-defined]
    mod.registry_should_dispatch = MagicMock(return_value=True)  # type: ignore[attr-defined]
    mod.registry_is_suppressed = MagicMock(return_value=False)  # type: ignore[attr-defined]
    mod.registry_record_dispatch = MagicMock()  # type: ignore[attr-defined]
    return send_mock


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
        """Medic off returns before the registry is consulted — an off switch that still
        burns backoff budget would silently re-arm the moment medic came back on."""
        mod = _import_module()
        send = _setup_happy_path(mod)
        breaker = MagicMock(return_value=True)
        recorded = MagicMock()
        mod._is_medic_enabled = MagicMock(return_value=False)  # type: ignore[attr-defined]
        mod.breaker_gate = breaker  # type: ignore[attr-defined]
        mod.registry_record_dispatch = recorded  # type: ignore[attr-defined]

        mod.handle_error_detected(branch="flow", module="cfg", message="err", error_hash="h1", count=2)

        send.assert_not_called()
        breaker.assert_not_called()
        recorded.assert_not_called()

    def test_returns_early_branch_muted(self) -> None:
        """Does not dispatch when branch is muted."""
        mod = _import_module()
        send = _setup_happy_path(mod)
        mod._is_branch_muted = MagicMock(return_value=True)  # type: ignore[attr-defined]

        mod.handle_error_detected(branch="flow", module="cfg", message="err", error_hash="h1", count=2)

        send.assert_not_called()

    def test_returns_early_count_below_threshold(self) -> None:
        """A first occurrence returns before the registry is consulted — a one-off that
        spent the fingerprint's backoff would mute the real repeat that follows it."""
        mod = _import_module()
        send = _setup_happy_path(mod)
        breaker = MagicMock(return_value=True)
        recorded = MagicMock()
        mod.breaker_gate = breaker  # type: ignore[attr-defined]
        mod.registry_record_dispatch = recorded  # type: ignore[attr-defined]

        mod.handle_error_detected(
            branch="flow", module="cfg", message="err", error_hash="h1", count=1, fingerprint="fp1"
        )

        send.assert_not_called()
        breaker.assert_not_called()
        recorded.assert_not_called()

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

    def test_an_unreadable_registry_tells_its_owner_once_and_records_each_held_dispatch(self, tmp_path: Path) -> None:
        """Pins the deaf medic: each event failed into an unread trail and nobody was told."""
        send = MagicMock(return_value=True)
        error_detected.set_send_email_callback(send)
        (tmp_path / "AIPASS_REGISTRY.json").write_text("{not json", encoding="utf-8")

        for _ in range(3):
            error_detected.handle_error_detected(branch="flow", module="cfg", message="err", error_hash="h1", count=2)

        assert [c.kwargs["to_branch"] for c in send.call_args_list] == ["@spawn"]
        assert "branch registry unreadable (AIPASS_REGISTRY.json)" in send.call_args.kwargs["message"]
        held = (tmp_path / "logs" / "medic_suppressed.jsonl").read_text(encoding="utf-8").splitlines()
        assert len(held) == 3
        assert all("registry unreadable" in line and "flow" in line for line in held)

    def test_a_registry_that_recovers_dispatches_again_and_a_new_failure_is_told_again(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Told once per failure, not once per process: a second outage after a recovery mails the owner again."""
        monkeypatch.setattr(error_detected, "REGISTERED_TTL_SECONDS", 0.0)
        send = MagicMock(return_value=True)
        error_detected.set_send_email_callback(send)
        registry_file = tmp_path / "AIPASS_REGISTRY.json"
        registry = {"branches": [{"email": "@flow", "status": "active", "path": "src/aipass/flow"}]}

        registry_file.write_text("{not json", encoding="utf-8")
        error_detected.handle_error_detected(branch="flow", module="cfg", message="err", error_hash="h1", count=2)
        registry_file.write_text(json.dumps(registry), encoding="utf-8")
        error_detected.handle_error_detected(branch="flow", module="cfg", message="err", error_hash="h1", count=2)
        registry_file.write_text("{not json", encoding="utf-8")
        error_detected.handle_error_detected(branch="flow", module="cfg", message="err", error_hash="h1", count=2)

        assert [c.kwargs["to_branch"] for c in send.call_args_list] == ["@spawn", "@flow", "@spawn"]

    def test_an_unreadable_medic_state_raises_to_the_bus_and_dispatches_nothing(self, tmp_path: Path) -> None:
        """A medic state nobody can read may hold a person's 'off': no mail, and the bus is told, not a trail."""
        send = MagicMock(return_value=True)
        error_detected.set_send_email_callback(send)
        registry = {"branches": [{"email": "@flow", "status": "active", "path": "src/aipass/flow"}]}
        (tmp_path / "AIPASS_REGISTRY.json").write_text(json.dumps(registry), encoding="utf-8")
        medic_state.MEDIC_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        medic_state.MEDIC_STATE_FILE.write_text("{not json", encoding="utf-8")

        with pytest.raises(RuntimeError, match=r"medic state unreadable \(medic_state.json\)"):
            error_detected.handle_error_detected(branch="flow", module="cfg", message="err", error_hash="h1", count=2)

        send.assert_not_called()

    def test_an_unreadable_mute_list_raises_never_answers_unmuted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Pins the default: an unreadable mute list read as 'unmuted' and woke a branch a person had muted."""
        mod = _import_module()
        real_is_branch_muted = mod._is_branch_muted
        send = _setup_happy_path(mod)
        mod._is_branch_muted = real_is_branch_muted  # type: ignore[attr-defined]
        monkeypatch.setattr(medic_state, "get_muted_branches", MagicMock(side_effect=OSError("disk gone")))

        with pytest.raises(RuntimeError, match="mute list unreadable.*disk gone"):
            mod.handle_error_detected(branch="flow", module="cfg", message="err", error_hash="h1", count=2)

        send.assert_not_called()

    def test_a_wake_failure_after_delivery_raises_once_the_dispatch_is_recorded(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Pins the warning-only wake: a delivered mail that never woke its branch reached only a log line."""
        mod = _import_module()
        send = _setup_happy_path(mod)
        monkeypatch.setattr(WAKE_HOME, "wake_branch", MagicMock(side_effect=RuntimeError("no session")))
        record = MagicMock()
        monkeypatch.setattr(mod, "registry_record_dispatch", record)

        with pytest.raises(RuntimeError, match="mail delivered to @flow but wake failed.*no session"):
            mod.handle_error_detected(
                branch="flow", module="cfg", message="err", error_hash="h1", count=2, fingerprint="fp1"
            )

        send.assert_called_once()
        record.assert_called_once_with("fp1")

    def test_a_registry_owner_wake_failure_raises_after_the_hold_is_recorded(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Pins the warning-only wake on the census alert: spawn's mail sat unread and nobody knew."""
        send = MagicMock(return_value=True)
        error_detected.set_send_email_callback(send)
        wake_mock = MagicMock(side_effect=RuntimeError("no session"))
        monkeypatch.setattr(WAKE_HOME, "wake_branch", wake_mock)

        with pytest.raises(RuntimeError, match="mail delivered to @spawn but wake failed.*no session"):
            error_detected.handle_error_detected(branch="flow", module="cfg", message="err", error_hash="h1", count=2)

        assert "registry unreadable" in (tmp_path / "logs" / "medic_suppressed.jsonl").read_text(encoding="utf-8")
        wake_mock.side_effect = None
        error_detected.handle_error_detected(branch="flow", module="cfg", message="err", error_hash="h1", count=2)
        assert [c.kwargs["to_branch"] for c in send.call_args_list] == ["@spawn"], "the alert was not marked sent"

    def test_an_unreadable_log_context_is_named_in_the_mail(self, tmp_path: Path) -> None:
        """Pins the empty default: an unreadable log sent the mail with no context and no word why."""
        mod = _import_module()
        send = _setup_happy_path(mod)
        unreadable = tmp_path / "flow.log"
        unreadable.mkdir()

        mod.handle_error_detected(
            branch="flow", module="cfg", message="err", error_hash="h1", count=2, log_path=str(unreadable)
        )

        assert "context unavailable" in send.call_args.kwargs["message"]
        assert "Is a directory" in send.call_args.kwargs["message"]

    def test_an_absent_branch_registry_is_told_to_its_owner_not_read_as_empty(self, tmp_path: Path) -> None:
        """Pins the silent default census: no file answered the empty set and every branch was skipped as unknown."""
        send = MagicMock(return_value=True)
        error_detected.set_send_email_callback(send)

        error_detected.handle_error_detected(branch="flow", module="cfg", message="err", error_hash="h1", count=2)

        assert [c.kwargs["to_branch"] for c in send.call_args_list] == ["@spawn"]
        held = (tmp_path / "logs" / "medic_suppressed.jsonl").read_text(encoding="utf-8")
        assert "Unknown branch skipped" not in held
        assert "registry unreadable" in held

    def test_returns_early_circuit_breaker_open(self) -> None:
        """Does not dispatch when circuit breaker is open."""
        mod = _import_module()
        send = _setup_happy_path(mod)
        mod.breaker_gate = MagicMock(return_value="Circuit breaker OPEN - held for")  # type: ignore[attr-defined]

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
        """A registry-suppressed fingerprint never dispatches (compass #219).
        A suppressed arm falling through to dispatch fails only this test; the logging sibling
        asserts which trail the refusal is written to and never looks at the send.
        """
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
        json_handler = mod.json_handler

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

    def test_a_throwing_send_reaches_the_bus_and_records_nothing(self) -> None:
        """Pins the swallowed send: a raise ended in an unread trail and the error was never delivered or told."""
        mod = _import_module()
        send = _setup_happy_path(mod)
        send.side_effect = RuntimeError("SMTP down")
        mod.json_handler.log_operation.reset_mock()  # type: ignore[union-attr]

        with pytest.raises(RuntimeError, match="SMTP down"):
            mod.handle_error_detected(
                branch="flow", module="cfg", message="err", error_hash="h1", count=2, fingerprint="fpX"
            )

        mod.json_handler.log_operation.assert_not_called()  # type: ignore[union-attr]
        mod.registry_record_dispatch.assert_not_called()  # type: ignore[attr-defined]

    def test_a_refused_send_raises_and_records_no_dispatch(self) -> None:
        """A False from the mail adapter is a failed delivery: the bus is told, and backoff is not started."""
        mod = _import_module()
        send = _setup_happy_path(mod)
        send.return_value = False
        mod.json_handler.log_operation.reset_mock()  # type: ignore[union-attr]

        with pytest.raises(RuntimeError, match="delivery failed for @flow"):
            mod.handle_error_detected(
                branch="flow", module="cfg", message="err", error_hash="h1", count=2, fingerprint="fp_fail"
            )

        send.assert_called_once()
        mod.json_handler.log_operation.assert_not_called()  # type: ignore[union-attr]
        mod.registry_record_dispatch.assert_not_called()  # type: ignore[attr-defined]

    def test_no_mail_adapter_wired_raises_instead_of_returning_quietly(self) -> None:
        """Pins the quiet return: with ai_mail unwired, every error past the gates vanished."""
        mod = _import_module()
        _setup_happy_path(mod)
        mod._send_email = None  # type: ignore[attr-defined]

        with pytest.raises(RuntimeError, match="no ai_mail adapter"):
            mod.handle_error_detected(branch="flow", module="cfg", message="err", error_hash="h1", count=2)


class TestMedicEnabledTTL:
    """Tests for _is_medic_enabled TTL expiry behavior."""

    def test_medic_enabled_ttl_expired(self) -> None:
        """medic_enabled=False with expired TTL -> treated as enabled, dispatch proceeds."""
        mod = _import_module()
        real_is_medic_enabled = mod._is_medic_enabled
        send = _setup_happy_path(mod)
        mod._is_medic_enabled = real_is_medic_enabled  # type: ignore[attr-defined]

        config_file = medic_state.MEDIC_STATE_FILE
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
        assert send.call_args.kwargs["to_branch"] == "@flow"

    def test_medic_enabled_ttl_active(self) -> None:
        """medic_enabled=False with future TTL -> medic still disabled, dispatch suppressed."""
        mod = _import_module()
        real_is_medic_enabled = mod._is_medic_enabled
        send = _setup_happy_path(mod)
        mod._is_medic_enabled = real_is_medic_enabled  # type: ignore[attr-defined]

        config_file = medic_state.MEDIC_STATE_FILE
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


class TestBranchMutedFormats:
    """Tests for _is_branch_muted dict and string format support."""

    def test_branch_muted_dict_format_active(self) -> None:
        """Dict entry with future expires_at -> branch IS muted, dispatch suppressed."""
        mod = _import_module()
        real_is_branch_muted = mod._is_branch_muted
        send = _setup_happy_path(mod)
        mod._is_branch_muted = real_is_branch_muted  # type: ignore[attr-defined]
        mod._get_registered_emails = MagicMock(return_value={"@api", "@flow"})  # type: ignore[attr-defined]

        config_file = medic_state.MEDIC_STATE_FILE
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

        config_file = medic_state.MEDIC_STATE_FILE
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
        assert send.call_args.kwargs["to_branch"] == "@api"

    def test_branch_muted_plain_string_backcompat(self) -> None:
        """Plain string entry in muted_branches -> branch IS muted (permanent)."""
        mod = _import_module()
        real_is_branch_muted = mod._is_branch_muted
        send = _setup_happy_path(mod)
        mod._is_branch_muted = real_is_branch_muted  # type: ignore[attr-defined]
        mod._get_registered_emails = MagicMock(return_value={"@api", "@flow"})  # type: ignore[attr-defined]

        config_file = medic_state.MEDIC_STATE_FILE
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

        config_file = medic_state.MEDIC_STATE_FILE
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


class TestDeliveredIsReported:
    """A delivered mail is reported to the breaker, which closes a spent probe and clears what rode in it."""

    def test_a_delivered_mail_reports_its_fingerprint_to_the_breaker(self) -> None:
        mod = _import_module()
        send = _setup_happy_path(mod)
        mod.circuit_breaker_delivered = MagicMock()  # type: ignore[attr-defined]

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
        mod.circuit_breaker_delivered.assert_called_once_with("@flow", ["fp_probe"])  # type: ignore[attr-defined]


class TestOccurrencesReportsTrueCount:
    """The dispatched notification must report the registry count, not a literal 1.
    The call site hardcoded occurrences=1, so every dispatch called a recurring error a one-off.
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
        'Occurrences: 1' against a month-long window means two sources fed one payload.
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


class TestNotificationNamesTheRegistryRow:
    """The responder must be able to look the error up and close it.
    A mail naming an id no registry verb accepts, and no closing verb, leaves cured entries re-dispatching.
    """

    def test_registry_id_is_the_id_the_verbs_take(self) -> None:
        """The ID printed at the top is the one errors detail/resolve accept."""
        mod = _import_module()
        send = _setup_happy_path(mod)

        mod.handle_error_detected(
            branch="flow",
            module="cfg",
            message="err",
            error_hash="legacy01",
            count=2,
            fingerprint="67b396e47ba3616ad99178b2216a54cc",
            registry_id="6fd3636e",
        )

        body = send.call_args.kwargs["message"]
        assert "Error ID: 6fd3636e" in body
        assert "Error ID: legacy01" not in body

    def test_a_dispatch_with_no_registry_row_says_so(self) -> None:
        """Never print a hash as if a verb would take it — say it is not tracked."""
        mod = _import_module()
        send = _setup_happy_path(mod)

        mod.handle_error_detected(branch="flow", module="cfg", message="err", error_hash="legacy01", count=2)

        body = send.call_args.kwargs["message"]
        assert "not tracked in the registry" in body
        assert "Error ID: legacy01" not in body

    def test_the_closing_verb_is_in_the_instructions(self) -> None:
        """A dispatch that never names its closing verb is a loop nobody closes."""
        mod = _import_module()
        send = _setup_happy_path(mod)

        mod.handle_error_detected(
            branch="flow", module="cfg", message="err", error_hash="x", count=2, registry_id="6fd3636e"
        )

        body = send.call_args.kwargs["message"]
        assert "drone @trigger errors resolve 6fd3636e" in body
        assert "drone @trigger errors suppress 6fd3636e" in body


@pytest.fixture
def lane(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> SimpleNamespace:
    """The escalation lane on a tmp state file with known thresholds.
    State file, config and digest callback are pinned: operator config never decides an outcome, no digest leaves.
    """
    config: Dict[str, Any] = {
        "enabled": True,
        "digest_recipient": "@digest-inbox",
        "warning_threshold": 2,
        "error_threshold": 2,
        "window_minutes": 60,
        "cooldown_minutes": 60,
        "sample_lines": 3,
        "max_signatures": 500,
        "escalate_suppressed": False,
        "ignore_branches": [],
    }
    digests: List[Dict[str, Any]] = []

    def _send(**kwargs: Any) -> bool:
        digests.append(kwargs)
        return True

    monkeypatch.setattr(escalation, "STATE_FILE", tmp_path / "escalation_state.json")
    monkeypatch.setattr(escalation, "logger", trail(tmp_path / "logs" / "escalation.jsonl"))
    monkeypatch.setattr(escalation, "get_config", lambda: config)
    monkeypatch.setattr(escalation, "_send_email", _send)

    # Stubbed on the package attribute the lazy import resolves, keeping the live medic_state.json out.
    medic = MagicMock()
    medic.is_enabled.return_value = True
    medic.get_muted_branches.return_value = []
    monkeypatch.setattr(handlers_pkg, "medic_state", medic, raising=False)

    # The lane's lazy is_suppressed / get_dispatch_count reads: not suppressed,
    # never dispatched (the autouse fixture sets them on the real registry).
    escalation._config_cache = (0.0, None)
    escalation._branch_names_cache = (0.0, None)
    return SimpleNamespace(mod=escalation, config=config, digests=digests, medic=medic, registry=error_registry)


class TestEscalationRecording:
    """The occurrence is counted BEFORE every dispatch gate.
    A mute, medic toggle or first occurrence stops the dispatch, never the count, or a repeat goes dark.
    """

    def test_dispatched_error_is_recorded(self, lane) -> None:
        """Positive control: the ordinary dispatch path records too."""
        mod = _import_module()
        send = _setup_happy_path(mod)

        mod.handle_error_detected(branch="flow", module="cfg", message="err", error_hash="h1", count=2)

        send.assert_called_once()
        rows = lane.mod.get_signatures()
        assert len(rows) == 1
        assert rows[0]["total_count"] == 1

    def test_medic_off_still_records(self, lane) -> None:
        """Medic off suppresses the dispatch; the count carries on."""
        mod = _import_module()
        send = _setup_happy_path(mod)
        mod._is_medic_enabled = MagicMock(return_value=False)

        mod.handle_error_detected(branch="flow", module="cfg", message="err", error_hash="h1", count=2)

        send.assert_not_called()
        assert lane.mod.get_signatures()[0]["total_count"] == 1

    def test_muted_branch_still_records(self, lane) -> None:
        """THE MUTE RULE: a mute is 'do not wake me', never 'stop counting'."""
        mod = _import_module()
        send = _setup_happy_path(mod)
        mod._is_branch_muted = MagicMock(return_value=True)

        mod.handle_error_detected(branch="flow", module="cfg", message="err", error_hash="h1", count=5)

        send.assert_not_called()
        assert lane.mod.get_signatures()[0]["total_count"] == 1

    def test_muted_branch_repeat_escalates_without_any_dispatch(self, lane) -> None:
        """The whole point: medic stays silent for a muted branch, the human does not."""
        mod = _import_module()
        send = _setup_happy_path(mod)
        mod._is_branch_muted = MagicMock(return_value=True)
        lane.medic.get_muted_branches.return_value = ["flow"]

        for _ in range(2):
            mod.handle_error_detected(branch="flow", module="cfg", message="err", error_hash="h1", count=5)

        send.assert_not_called()
        assert len(lane.digests) == 1
        assert lane.digests[0]["to_branch"] == "@digest-inbox"
        assert lane.digests[0]["auto_execute"] is False

    def test_first_occurrence_still_records(self, lane) -> None:
        """count=1 never dispatches, so without the lane a one-per-minute error is invisible."""
        mod = _import_module()
        send = _setup_happy_path(mod)

        mod.handle_error_detected(branch="flow", module="cfg", message="err", error_hash="h1", count=1)

        send.assert_not_called()
        assert lane.mod.get_signatures()[0]["total_count"] == 1

    def test_open_circuit_breaker_still_records(self, lane) -> None:
        """An error storm opens the breaker — the storm still has to be countable."""
        mod = _import_module()
        send = _setup_happy_path(mod)
        mod.breaker_gate = MagicMock(return_value="Circuit breaker OPEN - held for")

        mod.handle_error_detected(
            branch="flow", module="cfg", message="err", error_hash="h1", count=3, fingerprint="fp1"
        )

        send.assert_not_called()
        assert lane.mod.get_signatures()[0]["total_count"] == 1

    def test_backoff_suppressed_dispatch_still_records(self, lane) -> None:
        """Per-fingerprint backoff is exactly the silence this lane exists to cover."""
        mod = _import_module()
        send = _setup_happy_path(mod)
        mod.registry_should_dispatch = MagicMock(return_value=False)

        mod.handle_error_detected(
            branch="flow", module="cfg", message="err", error_hash="h1", count=3, fingerprint="fp1"
        )

        send.assert_not_called()
        assert lane.mod.get_signatures()[0]["total_count"] == 1

    def test_unknown_branch_still_records(self, lane) -> None:
        """An error from a branch medic cannot mail is still counted."""
        mod = _import_module()
        send = _setup_happy_path(mod)
        mod._get_registered_emails = MagicMock(return_value={"@spawn"})

        mod.handle_error_detected(branch="flow", module="cfg", message="err", error_hash="h1", count=2)

        send.assert_not_called()
        assert lane.mod.get_signatures()[0]["total_count"] == 1

    def test_invalid_event_records_nothing(self, lane) -> None:
        """Validation runs first — an event with no message counts as nothing."""
        mod = _import_module()
        _setup_happy_path(mod)

        mod.handle_error_detected(branch="flow", module="cfg", message="", error_hash="h1", count=2)

        assert lane.mod.get_signatures() == []

    def test_repeats_with_variable_paths_share_one_signature(self, lane) -> None:
        """Two dispatches of the same failure against different paths are one signature."""
        mod = _import_module()
        _setup_happy_path(mod)

        mod.handle_error_detected(
            branch="flow", module="cfg", message="cannot open /home/a/x.json", error_hash="h1", count=2
        )
        mod.handle_error_detected(
            branch="flow", module="cfg", message="cannot open /srv/b/y.json", error_hash="h2", count=3
        )

        rows = lane.mod.get_signatures()
        assert len(rows) == 1
        assert rows[0]["total_count"] == 2

    def test_recorded_entry_carries_the_event_context(self, lane, tmp_path: Path) -> None:
        """Log path, fingerprint and raw line travel into the lane for the digest."""
        mod = _import_module()
        _setup_happy_path(mod)
        log_path = tmp_path / "logs" / "flow.log"

        mod.handle_error_detected(
            branch="flow",
            module="cfg",
            message="err",
            error_hash="h1",
            count=2,
            fingerprint="fp-abc",
            log_path=str(log_path),
            raw_line="2026-08-08 | cfg | ERROR | err",
        )

        row = lane.mod.get_signatures()[0]
        assert row["level"] == "ERROR"
        assert row["log_file"] == str(log_path)
        assert row["fingerprint"] == "fp-abc"
        assert row["samples"] == ["2026-08-08 | cfg | ERROR | err"]

    def test_disabled_lane_records_nothing_but_dispatch_survives(self, lane) -> None:
        """Switching the lane off must not take medic's dispatch down with it."""
        mod = _import_module()
        send = _setup_happy_path(mod)
        lane.config["enabled"] = False

        mod.handle_error_detected(branch="flow", module="cfg", message="err", error_hash="h1", count=2)

        send.assert_called_once()
        assert lane.mod.get_signatures() == []


class TestOneMuteRule:
    """A mute reads the same in every gate, however it was stored."""

    def test_a_mute_stored_with_an_at_suppresses_dispatch(self) -> None:
        """medic status reads "@sentry" as sentry muted; the dispatch gate must agree.
        Red first: the gate compared the raw entry and dispatched to a muted branch.
        """
        mod = _import_module()
        real_is_branch_muted = mod._is_branch_muted
        send = _setup_happy_path(mod)
        mod._is_branch_muted = real_is_branch_muted  # type: ignore[attr-defined]
        mod._get_registered_emails = MagicMock(return_value={"@sentry"})  # type: ignore[attr-defined]
        medic_state.MEDIC_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        medic_state.MEDIC_STATE_FILE.write_text(
            json.dumps({"config": {"muted_branches": [{"name": "@sentry", "expires_at": None}]}}), encoding="utf-8"
        )

        mod.handle_error_detected(
            branch="SENTRY", module="cfg", message="err", error_hash="h1", count=2, fingerprint="fp_at"
        )

        send.assert_not_called()


_REAL_GATES = {
    name: getattr(error_detected, name)
    for name in (
        "breaker_gate",
        "circuit_breaker_delivered",
        "circuit_breaker_send_failed",
        "circuit_breaker_held",
        "registry_should_dispatch",
        "registry_record_dispatch",
        "registry_is_suppressed",
    )
}
_REAL_REPORT, _REAL_IS_SUPPRESSED = error_registry.report, error_registry.is_suppressed


@pytest.fixture
def medic_line(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Real registry, backoff and breaker on tmp files, fed the way the watcher feeds them; the clock is pinned."""
    for name, real in _REAL_GATES.items():
        monkeypatch.setattr(error_detected, name, real)
    monkeypatch.setattr(error_registry, "report", _REAL_REPORT)
    monkeypatch.setattr(error_registry, "is_suppressed", _REAL_IS_SUPPRESSED)
    monkeypatch.setattr(error_registry, "logger", MagicMock())
    clock = [1_000_000.0]
    monkeypatch.setattr(error_registry, "time", SimpleNamespace(time=lambda: clock[0]))
    mails: List[Dict[str, Any]] = []
    held: List[str] = []
    monkeypatch.setattr(error_detected, "_send_email", lambda **kwargs: mails.append(kwargs) or True)
    monkeypatch.setattr(error_detected, "_get_registered_emails", lambda: {"@hooks", "@memory", "@seed", "@flow"})
    monkeypatch.setattr(error_detected, "_wake", lambda *args: None)
    monkeypatch.setattr(error_detected, "_write_suppression_log", lambda reason, *rest: held.append(reason))

    def feed(branch: str, message: str, times: int = 1) -> None:
        for _ in range(times):
            row = error_registry.report(error_type="ERROR", message=message, component=branch)
            error_detected.handle_error_detected(
                branch=branch,
                module="m",
                message=message,
                error_hash=row["id"],
                fingerprint=row["fingerprint"],
                registry_id=row["id"],
                count=row["count"],
            )

    def trip() -> None:
        """Ten distinct faults from two branches, each seen twice: the fleet trip."""
        for branch in ("hooks", "memory"):
            for n in range(5):
                feed(branch, f"{branch} fault {chr(97 + n)}", times=2)

    def to(branch: str) -> List[Dict[str, Any]]:
        return [m for m in mails if m["to_branch"] == branch]

    return SimpleNamespace(feed=feed, trip=trip, to=to, mails=mails, held=held, clock=clock)


class TestTheBreakerCountsMailsNotLines:
    """One fleet breaker, fed only where a mail would go: a storm from one branch never holds another's mail."""

    def test_a_storm_from_one_branch_never_holds_another_branchs_mail(self, medic_line) -> None:
        medic_line.feed("hooks", "handler error navmap KeyError 'x'", times=12)
        medic_line.feed("memory", "vector store write failed", times=2)

        assert [m["to_branch"] for m in medic_line.mails] == ["@hooks", "@memory"]
        assert error_registry.get_circuit_breaker_status()["state"] == "closed"

    def test_faults_from_unregistered_branches_never_count_toward_the_trip(self, medic_line) -> None:
        for ghost in ("ghost1", "ghost2"):
            for n in range(5):
                medic_line.feed(ghost, f"fault {n}", times=2)
        medic_line.feed("memory", "vector store write failed", times=2)

        assert [m["to_branch"] for m in medic_line.mails] == ["@memory"]

    def test_one_branch_gets_five_faults_and_the_rest_ride_in_its_next_mail(self, medic_line) -> None:
        for n in range(7):
            medic_line.feed("hooks", f"fault {chr(97 + n)}", times=2)

        assert len(medic_line.to("@hooks")) == 5
        holds = [reason for reason in medic_line.held if reason.startswith("Held")]
        assert holds == ["Held, @hooks had 5 faults mailed in 10 min - held for"] * 2
        assert error_registry.get_circuit_breaker_status()["state"] == "closed"

        medic_line.clock[0] += 601
        medic_line.feed("hooks", "fault h", times=2)

        late = medic_line.to("@hooks")[-1]["message"]
        assert "m: fault f" in late and "m: fault g" in late
        assert error_registry.circuit_breaker_held("@hooks") == {}

    def test_an_open_breaker_mails_devpulse_one_summary_and_never_wakes_it(self, medic_line) -> None:
        medic_line.trip()
        medic_line.feed("seed", "seed fault", times=2)

        summaries = medic_line.to("@devpulse")
        assert len(summaries) == 1
        assert summaries[0]["auto_execute"] is False
        assert "@hooks" in summaries[0]["message"] and "@memory" in summaries[0]["message"]
        assert len(medic_line.mails) == 10
        assert error_registry.get_circuit_breaker_status()["summary_sent"] is True

    def test_holds_while_open_never_postpone_recovery(self, medic_line) -> None:
        medic_line.trip()
        opened_at = error_registry.get_circuit_breaker_status()["opened_at"]
        for n in range(49):
            medic_line.clock[0] += 6
            medic_line.feed("seed", f"trickle {n}", times=2)

        assert error_registry.get_circuit_breaker_status()["opened_at"] == opened_at
        medic_line.clock[0] += 7
        medic_line.feed("flow", "fresh fault", times=2)

        assert len(medic_line.to("@flow")) == 1
        assert error_registry.get_circuit_breaker_status()["state"] == "closed"

    def test_a_status_read_after_cooldown_moves_nothing_and_the_next_mail_probes(self, medic_line) -> None:
        medic_line.trip()
        medic_line.clock[0] += 301
        before = error_registry.CB_STATE_FILE.read_text(encoding="utf-8")

        assert error_registry.get_circuit_breaker_status()["state"] == "open"
        assert error_registry.CB_STATE_FILE.read_text(encoding="utf-8") == before

        medic_line.feed("seed", "seed fault", times=2)
        medic_line.feed("flow", "flow fault", times=2)

        assert len(medic_line.to("@seed")) == 1
        assert len(medic_line.to("@flow")) == 1

    def test_a_backoff_fingerprint_leaves_the_probe_for_a_fresh_one(self, medic_line) -> None:
        medic_line.feed("flow", "noisy", times=2)
        medic_line.clock[0] += 300
        medic_line.feed("flow", "noisy")  # its second mail: backoff is now 900 s
        medic_line.trip()
        medic_line.clock[0] += 301
        medic_line.feed("flow", "noisy")
        medic_line.feed("flow", "fresh", times=2)

        assert "fresh" in medic_line.to("@flow")[-1]["message"]
        assert error_registry.get_circuit_breaker_status()["state"] == "closed"

    def test_a_failed_probe_reopens_with_double_cooldown(self, medic_line, monkeypatch) -> None:
        medic_line.trip()
        medic_line.clock[0] += 301
        monkeypatch.setattr(error_detected, "_send_email", lambda **kwargs: kwargs["to_branch"] == "@devpulse")

        with pytest.raises(RuntimeError, match="Email delivery failed"):
            medic_line.feed("flow", "flow fault", times=2)

        status = error_registry.get_circuit_breaker_status()
        assert (status["state"], status["cooldown_seconds"]) == ("open", 600)


class TestTheRegisteredGateReadsTheDeclaredFleet:
    """A citizen at a declared root is registered: its errors dispatch, they are never 'Unknown branch'."""

    def test_an_external_citizens_error_is_dispatched_to_it(self, fleet, monkeypatch) -> None:
        send = MagicMock(return_value=True)
        error_detected.set_send_email_callback(send)
        monkeypatch.setattr(error_detected, "BRANCH_REGISTRY_FILE", fleet.registry)

        error_detected.handle_error_detected(branch="GROW", module="bed", message="dry", error_hash="h1", count=2)

        assert send.call_args.kwargs["to_branch"] == "@grow"

    def test_the_gate_reads_the_door_once_per_ttl_not_once_per_error(self, fleet, monkeypatch) -> None:
        """The door logs refusals at ERROR into a watched log: a read per error event would feed itself."""
        reads = []

        def counting_door(**kwargs):
            reads.append(kwargs)
            return [{"email": "@grow"}]

        send = MagicMock(return_value=True)
        error_detected.set_send_email_callback(send)
        monkeypatch.setattr(error_detected, "fleet_branches", counting_door)
        monkeypatch.setattr(error_detected, "BRANCH_REGISTRY_FILE", fleet.registry)

        for error_hash in ("h1", "h2"):
            error_detected.handle_error_detected(
                branch="GROW", module="bed", message=error_hash, error_hash=error_hash, count=2
            )

        assert send.call_count == 2
        assert len(reads) == 1
