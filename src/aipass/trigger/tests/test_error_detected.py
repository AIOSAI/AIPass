# =================== META ====================
# Name: test_error_detected.py
# Description: Tests for error_detected event handler with Medic v2 dispatch gating
# Version: 1.3.0
# Created: 2026-04-25
# Modified: 2026-09-29
# =============================================

"""Tests for apps/handlers/events/error_detected.py and the dispatch gates it runs."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(covered_elsewhere) — what should_dispatch and is_suppressed decide, in error_registry
# seedgo: no-test-needed(covered_elsewhere) — the digest body and the aged lane, in test_escalation.py
# seedgo: no-test-needed(covered_elsewhere) — the two producers of this event, log_watcher and the catch-up scan
# seedgo: no-test-needed(external) — ai_mail delivery and wake_branch; AIPass tests only its own files
# seedgo: no-test-needed(constant) — the fixed investigation-step prose _build_notification_message() wraps

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest
import aipass.trigger.apps.handlers as handlers_pkg
import aipass.trigger.apps.handlers.error_registry as error_registry
import aipass.trigger.apps.handlers.events.error_detected as error_detected
from aipass.ai_mail.apps.handlers.dispatch import wake
from aipass.trigger.apps.config import trail_logger
from aipass.trigger.apps.handlers import escalation


# ---------------------------------------------------------------------------
# Shared fixture: the real module, with every edge that reaches outside
# patched, and a registry-available environment by default. Individual tests
# override module-level helpers after it.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _mock_infrastructure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Put the real error_detected module on tmp_path and recording stubs.

    Every edge that reaches outside is swapped with monkeypatch.setattr, so
    teardown restores it even when a test assigns over it directly:
    _send_email (mail), wake.wake_branch (the lazy import wakes a branch),
    the registry gates error_detected bound at import, json_handler's
    log_operation, the medic/branch-registry files and the logger. Escalation
    reaches error_registry.report (a registry write) by a lazy import, so
    report is a recording stub and the registry's files point at tmp_path.

    The registry's normalize_message stays REAL: escalation signatures are
    computed off it, and a mock returns the same object for every input, so
    any "these two share one signature" assertion would pass without it.
    """
    json_dir = tmp_path / "trigger_json"
    monkeypatch.setattr(error_registry, "REGISTRY_FILE", json_dir / "error_registry.json")
    monkeypatch.setattr(error_registry, "CB_STATE_FILE", json_dir / "trigger_cb_state.json")
    monkeypatch.setattr(error_registry, "report", MagicMock(return_value={"is_new": False}))
    monkeypatch.setattr(error_registry, "is_suppressed", MagicMock(return_value=False))
    monkeypatch.setattr(error_registry, "get_dispatch_count", MagicMock(return_value=0))
    monkeypatch.setattr(wake, "wake_branch", MagicMock())

    monkeypatch.setattr(error_detected, "_send_email", None)
    monkeypatch.setattr(error_detected, "circuit_breaker_allows", MagicMock(return_value=True))
    monkeypatch.setattr(error_detected, "circuit_breaker_record_error", MagicMock())
    monkeypatch.setattr(error_detected, "circuit_breaker_probe_succeeded", MagicMock())
    monkeypatch.setattr(error_detected, "registry_should_dispatch", MagicMock(return_value=True))
    monkeypatch.setattr(error_detected, "registry_record_dispatch", MagicMock())
    monkeypatch.setattr(error_detected, "registry_is_suppressed", MagicMock(return_value=False))
    monkeypatch.setattr(error_detected, "_REGISTRY_DISPATCH_AVAILABLE", True)
    monkeypatch.setattr(error_detected.json_handler, "log_operation", MagicMock(return_value=True))
    monkeypatch.setattr(error_detected, "MEDIC_STATE_FILE", json_dir / "medic_state.json")
    monkeypatch.setattr(error_detected, "LEGACY_MEDIC_STATE_FILE", json_dir / "trigger_config.json")
    monkeypatch.setattr(error_detected, "BRANCH_REGISTRY_FILE", tmp_path / "AIPASS_REGISTRY.json")
    monkeypatch.setattr(error_detected, "TRIGGER_ROOT", tmp_path)
    monkeypatch.setattr(error_detected, "logger", trail_logger(tmp_path / "error_detected_handler.jsonl"))
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
        """Medic off returns before the registry is consulted — an off switch that still
        burns backoff budget would silently re-arm the moment medic came back on."""
        mod = _import_module()
        send = _setup_happy_path(mod)
        breaker = MagicMock(return_value=True)
        recorded = MagicMock()
        mod._is_medic_enabled = MagicMock(return_value=False)  # type: ignore[attr-defined]
        mod.circuit_breaker_allows = breaker  # type: ignore[attr-defined]
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
        mod.circuit_breaker_allows = breaker  # type: ignore[attr-defined]
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

    def test_an_unreadable_branch_registry_is_reported_not_skipped(self, tmp_path: Path) -> None:
        """A registry that cannot be read names itself in the trail; nothing is skipped or sent.

        The real lookup runs over a tmp registry that is not JSON. Answering the
        empty set would log 'Unknown branch skipped' for a branch that has an
        owner. Mutants 2026-09-29: the raise put back to return set(), and the
        file's name taken out of the message, each redden this.
        """
        send = MagicMock(return_value=True)
        error_detected.set_send_email_callback(send)
        (tmp_path / "AIPASS_REGISTRY.json").write_text("{not json", encoding="utf-8")

        error_detected.handle_error_detected(branch="flow", module="cfg", message="err", error_hash="h1", count=2)

        send.assert_not_called()
        assert not (tmp_path / "logs" / "medic_suppressed.jsonl").exists()
        trail = (tmp_path / "error_detected_handler.jsonl").read_text(encoding="utf-8")
        assert "branch registry unreadable (AIPASS_REGISTRY.json)" in trail

    def test_an_unreadable_medic_state_dispatches_nothing(self, tmp_path: Path) -> None:
        """A medic state nobody can read may hold a person's 'off': no mail, the trail names it.

        Red first 2026-09-29: the unreadable state answered enabled and the error was sent.
        """
        send = MagicMock(return_value=True)
        error_detected.set_send_email_callback(send)
        registry = {"branches": [{"email": "@flow"}]}
        (tmp_path / "AIPASS_REGISTRY.json").write_text(json.dumps(registry), encoding="utf-8")
        (tmp_path / "trigger_json").mkdir()
        (tmp_path / "trigger_json" / "medic_state.json").write_text("{not json", encoding="utf-8")

        error_detected.handle_error_detected(branch="flow", module="cfg", message="err", error_hash="h1", count=2)

        send.assert_not_called()
        trail = (tmp_path / "error_detected_handler.jsonl").read_text(encoding="utf-8")
        assert "medic state unreadable (medic_state.json)" in trail

    def test_an_absent_branch_registry_is_a_registry_with_nobody_in_it(self, tmp_path: Path) -> None:
        """No registry file answers the empty set: the branch is skipped as unknown, no warning.

        Mutant 2026-09-29: an absent file made to raise reddens this.
        """
        send = MagicMock(return_value=True)
        error_detected.set_send_email_callback(send)

        error_detected.handle_error_detected(branch="flow", module="cfg", message="err", error_hash="h1", count=2)

        send.assert_not_called()
        assert not (tmp_path / "error_detected_handler.jsonl").exists()
        skipped = (tmp_path / "logs" / "medic_suppressed.jsonl").read_text(encoding="utf-8")
        assert "Unknown branch skipped: @flow" in skipped

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
        """A registry-suppressed fingerprint never dispatches (compass #219).

        KEPT against the DPLAN-0323 merge walk, which read this as a restatement
        of test_returns_early_should_dispatch_false. Measured 2026-09-07: move
        the shared `return` into the backoff arm only, so the suppressed arm
        falls through and dispatches, and the entire 1042-case suite stays
        GREEN — this is the only test that fails. The logging sibling asserts
        which trail the refusal is written to and never looks at the send, so
        it cannot see a suppressed error going out the door.
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

    def test_a_throwing_send_is_reported_and_stops_the_pipeline(self) -> None:
        """_send_email raising is caught, named in the log, and records nothing.

        The unit was the call and nothing else, so it passed on `except: pass`
        — which is the worst outcome available here. This handler is the last
        thing standing between an error and an operator: if a throwing send
        went unlogged, dispatch would be dead and the only symptom would be
        silence. And the exception must not be mistaken for a delivery, so
        nothing downstream of the send may run.
        """
        mod = _import_module()
        send = _setup_happy_path(mod)
        send.side_effect = RuntimeError("SMTP down")
        json_handler = mod.json_handler

        json_handler.log_operation.reset_mock()  # type: ignore[union-attr]

        with patch.object(mod, "logger") as mock_logger:
            mod.handle_error_detected(
                branch="flow",
                module="cfg",
                message="err",
                error_hash="h1",
                count=2,
                fingerprint="fpX",
            )

        reported = str(mock_logger.warning.call_args_list)
        assert "SMTP down" in reported, f"the cause must reach the log, got: {reported}"
        json_handler.log_operation.assert_not_called()  # type: ignore[union-attr]
        mod.registry_record_dispatch.assert_not_called()  # type: ignore[attr-defined]

    def test_does_not_record_dispatch_when_send_fails(self) -> None:
        """When _send_email returns False, dispatch is not recorded."""
        mod = _import_module()
        send = _setup_happy_path(mod)
        send.return_value = False
        json_handler = mod.json_handler

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

    @pytest.fixture
    def fallback_mod(self, monkeypatch: pytest.MonkeyPatch) -> Any:
        """A second copy of error_detected, imported while error_registry cannot be.

        HELD for import_site: these stubs exist only in the `except ImportError`
        arm, so the one way to reach them is an import that fails. No setattr on
        the real module can make its import-time `from ... import` fail again.
        monkeypatch restores both sys.modules entries at teardown.
        """
        monkeypatch.setitem(sys.modules, "aipass.trigger.apps.handlers.error_registry", None)
        monkeypatch.delitem(sys.modules, "aipass.trigger.apps.handlers.events.error_detected")
        import aipass.trigger.apps.handlers.events.error_detected as fresh

        return fresh

    def test_registry_should_dispatch_returns_true(self, fallback_mod: Any) -> None:
        """Fallback always allows dispatch for any fingerprint."""
        mod = fallback_mod
        assert mod.registry_should_dispatch("any-fingerprint") is True

    def test_registry_is_suppressed_returns_false(self, fallback_mod: Any) -> None:
        """Fallback suppresses nothing — no registry means no silencing."""
        mod = fallback_mod
        assert mod.registry_is_suppressed("any-fingerprint") is False

    def test_registry_record_dispatch_is_a_no_op_with_the_real_arity(self, fallback_mod: Any) -> None:
        """The fallback takes the same one argument and answers None like the real one.

        A stub stands in for a function the caller cannot see is missing, so
        the two things worth pinning are the shape of the call and the shape of
        the answer. "It did not raise" covers neither: a stub that took no
        argument, or returned a truthy sentinel a caller then branched on,
        would pass it. record_dispatch returns nothing, so the stub must too.
        """
        mod = fallback_mod

        assert mod.registry_record_dispatch("any-fingerprint") is None
        assert mod._REGISTRY_DISPATCH_AVAILABLE is False

    def test_circuit_breaker_record_error_takes_no_argument_and_answers_none(self, fallback_mod: Any) -> None:
        """The fallback breaker records nothing and says nothing.

        Same reasoning as the record_dispatch stub, with one addition that
        matters here: without a registry there is no breaker state, so this
        must not fabricate one. It counts nothing and returns None, and a
        caller cannot tell it apart from the real call by the answer.
        """
        mod = fallback_mod

        assert mod.circuit_breaker_record_error() is None
        assert mod.circuit_breaker_allows() is True


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

        config_file = mod.MEDIC_STATE_FILE
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

        config_file = mod.MEDIC_STATE_FILE
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

        config_file = mod.MEDIC_STATE_FILE
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

        config_file = mod.MEDIC_STATE_FILE
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

        config_file = mod.MEDIC_STATE_FILE
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

        config_file = mod.MEDIC_STATE_FILE
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


class TestNotificationNamesTheRegistryRow:
    """The responder must be able to look the error up and close it.

    @hooks, 2026-09-24: the mail said "Error ID: 5a2ac45a", which no registry
    verb accepts — the row was 6fd3636e — and nothing in the instructions named
    the closing verb, so three cured entries sat at status new and re-dispatched
    two days later.
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


# ---------------------------------------------------------------------------
# Escalation lane recording (DPLAN-0283 WS-A)
# ---------------------------------------------------------------------------


@pytest.fixture
def lane(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> SimpleNamespace:
    """The escalation lane on a tmp state file with known thresholds.

    handle_error_detected records into the real lane module, so the state file,
    the config and the digest callback are all pinned here — the operator's
    config never decides a test outcome, and no digest can leave the process.
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
    monkeypatch.setattr(escalation, "logger", trail_logger(tmp_path / "escalation.jsonl"))
    monkeypatch.setattr(escalation, "get_config", lambda: config)
    monkeypatch.setattr(escalation, "_send_email", _send)

    # medic_state is reached by a lazy `from ... import medic_state`, which
    # resolves off the package attribute — stubbing it there keeps the real
    # module (and the live medic_state.json behind it) out of this test.
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

    A mute, a medic toggle or a first occurrence stops the DISPATCH. None of
    them may stop the COUNT, or a repeating failure goes dark for the human
    exactly when medic has gone quiet about it (DPLAN-0283).
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
        mod.circuit_breaker_allows = MagicMock(return_value=False)

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
