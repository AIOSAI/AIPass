"""Tests for runaway_log_detected event handler."""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from aipass.trigger.apps.handlers.events import runaway_handler as mod


# ---------------------------------------------------------------------------
# Shared fixture: redirect file paths to tmp_path, mock _append_jsonl and
# wake_branch, clear cooldown state between tests.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):  # type: ignore[misc]
    """Reset module state and redirect file paths to tmp_path."""
    mod._file_cooldowns.clear()
    mod._send_email = None

    monkeypatch.setattr(mod, "MEDIC_STATE_FILE", tmp_path / "medic_state.json")
    monkeypatch.setattr(mod, "LEGACY_MEDIC_STATE_FILE", tmp_path / "trigger_config.json")
    monkeypatch.setattr(mod, "ALERTS_FILE", tmp_path / "alerts.json")
    monkeypatch.setattr(mod, "_append_jsonl", MagicMock())

    # Mock wake_branch import chain so the in-function import succeeds
    mock_wake_mod = MagicMock()
    mock_wake_mod.wake_branch = MagicMock()
    monkeypatch.setitem(sys.modules, "aipass.ai_mail", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.ai_mail.apps", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.ai_mail.apps.handlers", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.ai_mail.apps.handlers.dispatch", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.ai_mail.apps.handlers.dispatch.wake", mock_wake_mod)

    yield

    mod._file_cooldowns.clear()


def _setup_happy_path() -> MagicMock:
    """Set up a successful dispatch scenario and return the send_email mock."""
    send_mock = MagicMock(return_value=True)
    mod.set_send_email_callback(send_mock)
    return send_mock


# ---------------------------------------------------------------------------
# 1. Missing file_path — returns without dispatch
# ---------------------------------------------------------------------------


class TestMissingFilePath:
    """Handler returns early when file_path is missing."""

    def test_none_file_path_no_dispatch(self) -> None:
        """Returns without dispatch when file_path is None."""
        send = _setup_happy_path()
        mod.handle_runaway_log_detected(file_path=None, branch="flow")
        send.assert_not_called()

    def test_empty_file_path_no_dispatch(self) -> None:
        """Returns without dispatch when file_path is empty string."""
        send = _setup_happy_path()
        mod.handle_runaway_log_detected(file_path="", branch="flow")
        send.assert_not_called()


# ---------------------------------------------------------------------------
# 2. Per-file cooldown — second call within 30min is suppressed
# ---------------------------------------------------------------------------


class TestPerFileCooldown:
    """Second call for the same file within 30min cooldown is suppressed."""

    def test_second_call_within_cooldown_suppressed(self) -> None:
        """Second call for the same file is suppressed (no time mock needed)."""
        send = _setup_happy_path()

        mod.handle_runaway_log_detected(
            file_path="/var/log/test.log",
            branch="flow",
            rate_lines_per_min=5000,
            sustained_duration_sec=60,
            severity="critical",
        )
        assert send.call_count == 1

        # Second call — same file, should be suppressed
        mod.handle_runaway_log_detected(
            file_path="/var/log/test.log",
            branch="flow",
            rate_lines_per_min=5000,
            sustained_duration_sec=120,
            severity="critical",
        )
        assert send.call_count == 1


# ---------------------------------------------------------------------------
# 3. Cooldown expired — call after cooldown passes dispatches again
# ---------------------------------------------------------------------------


class TestCooldownExpired:
    """Call after cooldown window expires dispatches again."""

    @patch("aipass.trigger.apps.handlers.events.runaway_handler.time")
    def test_dispatches_again_after_cooldown_expires(self, mock_time: MagicMock) -> None:
        """Dispatch succeeds again once the 1800s cooldown has elapsed."""
        send = _setup_happy_path()

        mock_time.time.return_value = 1_000_000.0
        mod.handle_runaway_log_detected(
            file_path="/var/log/test.log",
            branch="flow",
            rate_lines_per_min=5000,
            sustained_duration_sec=60,
            severity="critical",
        )
        assert send.call_count == 1

        # Advance past 1800s cooldown
        mock_time.time.return_value = 1_000_000.0 + 1801
        mod.handle_runaway_log_detected(
            file_path="/var/log/test.log",
            branch="flow",
            rate_lines_per_min=5000,
            sustained_duration_sec=120,
            severity="critical",
        )
        assert send.call_count == 2


# ---------------------------------------------------------------------------
# 4. Mute classes — content mutes never gate runaways, volume mutes do
# ---------------------------------------------------------------------------


def _write_config(tmp_path: Path, config: dict) -> None:
    """Write a medic_state.json with the given config section."""
    (tmp_path / "medic_state.json").write_text(
        json.dumps({"config": config}),
        encoding="utf-8",
    )


class TestBranchMuted:
    """Volume mutes gate runaway alerts; medic content mutes do not."""

    def test_content_muted_branch_still_delivers(self, tmp_path: Path) -> None:
        """REGRESSION: a medic-muted branch still gets its runaway alert.

        Every dispatch checklist tells agents to medic-mute before build work,
        which is exactly when floods happen — gating runaways on the content
        mute made this channel dead in its own peak window.
        """
        send = _setup_happy_path()

        _write_config(tmp_path, {"muted_branches": ["flow"]})

        mod.handle_runaway_log_detected(
            file_path="/var/log/test.log",
            branch="flow",
            rate_lines_per_min=5000,
            sustained_duration_sec=60,
            severity="critical",
        )
        send.assert_called_once()
        assert send.call_args.kwargs["to_branch"] == "@flow"

    def test_volume_muted_branch_suppressed(self, tmp_path: Path) -> None:
        """Branch listed in volume_muted_branches is suppressed — no email sent."""
        send = _setup_happy_path()

        _write_config(tmp_path, {"volume_muted_branches": ["flow"]})

        mod.handle_runaway_log_detected(
            file_path="/var/log/test.log",
            branch="flow",
            rate_lines_per_min=500,
            sustained_duration_sec=60,
        )
        send.assert_not_called()

    def test_expired_volume_mute_delivers(self, tmp_path: Path) -> None:
        """An expired volume mute entry does not suppress."""
        send = _setup_happy_path()

        expired = (datetime.now() - timedelta(hours=1)).isoformat()
        _write_config(tmp_path, {"volume_muted_branches": [{"name": "flow", "expires_at": expired}]})

        mod.handle_runaway_log_detected(
            file_path="/var/log/test.log",
            branch="flow",
            rate_lines_per_min=5000,
            sustained_duration_sec=60,
            severity="critical",
        )
        send.assert_called_once()

    def test_critical_bypasses_volume_mute(self, tmp_path: Path) -> None:
        """CRITICAL runaways deliver even through an active volume mute."""
        send = _setup_happy_path()

        _write_config(tmp_path, {"volume_muted_branches": ["flow"]})

        mod.handle_runaway_log_detected(
            file_path="/var/log/test.log",
            branch="flow",
            rate_lines_per_min=5000,
            sustained_duration_sec=60,
            severity="critical",
        )
        send.assert_called_once()
        assert send.call_args.kwargs["to_branch"] == "@flow"

    def test_critical_bypass_is_case_insensitive(self, tmp_path: Path) -> None:
        """Severity matching tolerates 'CRITICAL' as well as 'critical'."""
        send = _setup_happy_path()

        _write_config(tmp_path, {"volume_muted_branches": ["flow"]})

        mod.handle_runaway_log_detected(
            file_path="/var/log/test.log",
            branch="flow",
            rate_lines_per_min=5000,
            sustained_duration_sec=60,
            severity="CRITICAL",
        )
        send.assert_called_once()

    def test_warning_still_respects_volume_mute(self, tmp_path: Path) -> None:
        """Non-critical runaways still honour an explicit volume mute.

        Observe-only made the no-email half of this trivially true, so the
        assertion that carries weight now is that a volume-muted WARNING is
        dropped entirely — it does not even reach the observe-only record.
        """
        send = _setup_happy_path()

        _write_config(tmp_path, {"volume_muted_branches": ["flow"]})

        mod.handle_runaway_log_detected(
            file_path="/var/log/test.log",
            branch="flow",
            rate_lines_per_min=500,
            sustained_duration_sec=60,
            severity="warning",
        )
        send.assert_not_called()
        assert not (tmp_path / "alerts.json").exists()


# ---------------------------------------------------------------------------
# 5. UNKNOWN branch — dispatches to @prax instead
# ---------------------------------------------------------------------------


class TestUnknownBranch:
    """UNKNOWN branch falls back to @prax."""

    def test_unknown_branch_dispatches_to_prax(self) -> None:
        """Branch='UNKNOWN' dispatches email to @prax."""
        send = _setup_happy_path()

        mod.handle_runaway_log_detected(
            file_path="/var/log/test.log",
            branch="UNKNOWN",
            rate_lines_per_min=5000,
            sustained_duration_sec=60,
            severity="critical",
        )
        send.assert_called_once()
        assert send.call_args[1]["to_branch"] == "@prax"


# ---------------------------------------------------------------------------
# 6. None branch — dispatches to @prax instead
# ---------------------------------------------------------------------------


class TestNoneBranch:
    """None branch falls back to @prax."""

    def test_none_branch_dispatches_to_prax(self) -> None:
        """Branch=None dispatches email to @prax."""
        send = _setup_happy_path()

        mod.handle_runaway_log_detected(
            file_path="/var/log/test.log",
            branch=None,
            rate_lines_per_min=5000,
            sustained_duration_sec=60,
            severity="critical",
        )
        send.assert_called_once()
        assert send.call_args[1]["to_branch"] == "@prax"


# ---------------------------------------------------------------------------
# 7. No email callback — logs warning, no dispatch
# ---------------------------------------------------------------------------


class TestNoEmailCallback:
    """Handler logs warning and returns when _send_email is None.

    Only the CRITICAL path needs a callback — observe-only WARNINGs never
    reach this guard (see TestObserveOnlyWarning).
    """

    def test_logs_warning_no_dispatch(self) -> None:
        """Logs warning via _append_jsonl when no callback set."""
        # _send_email stays None (no set_send_email_callback call)
        mod.handle_runaway_log_detected(
            file_path="/var/log/test.log",
            branch="flow",
            rate_lines_per_min=5000,
            sustained_duration_sec=60,
            severity="critical",
        )

        calls = mod._append_jsonl.call_args_list  # type: ignore[union-attr]
        warning_calls = [c for c in calls if isinstance(c[0][1], dict) and c[0][1].get("level") == "WARNING"]
        assert len(warning_calls) >= 1
        assert "No email callback" in warning_calls[0][0][1]["msg"]


# ---------------------------------------------------------------------------
# 8. Successful dispatch — email sent, wake called, alert written,
#    cooldown recorded
# ---------------------------------------------------------------------------


class TestSuccessfulDispatch:
    """Full happy-path: email, wake, alert, cooldown."""

    def test_full_dispatch(self, tmp_path: Path) -> None:
        """Email sent with correct kwargs, alert file exists, cooldown recorded."""
        send = _setup_happy_path()
        file_path = "/var/log/test.log"

        mod.handle_runaway_log_detected(
            file_path=file_path,
            branch="flow",
            rate_lines_per_min=500,
            sustained_duration_sec=60,
            severity="critical",
        )

        # Email sent with expected kwargs
        send.assert_called_once()
        kwargs = send.call_args[1]
        assert kwargs["to_branch"] == "@flow"
        assert kwargs["auto_execute"] is True
        assert kwargs["reply_to"] == "@devpulse"
        assert kwargs["from_branch"] == "@trigger"
        assert "[RUNAWAY]" in kwargs["subject"]
        assert "CRITICAL" in kwargs["subject"]

        # wake_branch called (via mocked import)
        from aipass.ai_mail.apps.handlers.dispatch.wake import wake_branch

        wake_branch.assert_called_once_with("@flow", fresh=False, sender="@trigger")  # type: ignore[union-attr]

        # Alert file written
        alerts_file = tmp_path / "alerts.json"
        assert alerts_file.exists()

        # Cooldown recorded
        assert file_path in mod._file_cooldowns


# ---------------------------------------------------------------------------
# 9. Alert file written — verify alerts.json schema
# ---------------------------------------------------------------------------


class TestAlertFileSchema:
    """Alert written to .aipass/alerts.json with correct schema."""

    def test_alert_has_required_fields(self, tmp_path: Path) -> None:
        """Schema: {alerts: [{id, source, severity, title, body, created_at, expires_at}]}."""
        _setup_happy_path()

        mod.handle_runaway_log_detected(
            file_path="/var/log/test.log",
            branch="flow",
            rate_lines_per_min=500,
            sustained_duration_sec=60,
            severity="warning",
        )

        alerts_file = tmp_path / "alerts.json"
        data = json.loads(alerts_file.read_text(encoding="utf-8"))

        assert "alerts" in data
        assert len(data["alerts"]) == 1

        alert = data["alerts"][0]
        required_keys = {"id", "source", "severity", "title", "body", "created_at", "expires_at"}
        assert required_keys == set(alert.keys())
        assert alert["source"] == "prax"
        assert alert["severity"] == "warning"
        assert "test.log" in alert["title"]
        assert alert["body"]
        assert alert["created_at"]

    def test_alert_defaults_to_24h_ttl(self, tmp_path: Path) -> None:
        """expires_at defaults to ~24h from now, not None."""
        _setup_happy_path()

        mod.handle_runaway_log_detected(
            file_path="/var/log/test.log",
            branch="flow",
            rate_lines_per_min=500,
            sustained_duration_sec=60,
        )

        alerts_file = tmp_path / "alerts.json"
        data = json.loads(alerts_file.read_text(encoding="utf-8"))
        expires_at = data["alerts"][0]["expires_at"]

        assert expires_at is not None
        expires_dt = datetime.fromisoformat(expires_at)
        delta = expires_dt - datetime.now()
        assert timedelta(hours=23) < delta <= timedelta(hours=24, minutes=1)

    def test_alert_forever_true_sets_no_expiry(self, tmp_path: Path) -> None:
        """forever=True writes expires_at=None (permanent alert)."""
        _setup_happy_path()

        mod.handle_runaway_log_detected(
            file_path="/var/log/test.log",
            branch="flow",
            rate_lines_per_min=500,
            sustained_duration_sec=60,
            forever=True,
        )

        alerts_file = tmp_path / "alerts.json"
        data = json.loads(alerts_file.read_text(encoding="utf-8"))
        assert data["alerts"][0]["expires_at"] is None


# ---------------------------------------------------------------------------
# 10. Alert appends — existing alerts preserved when new one appended
# ---------------------------------------------------------------------------


class TestAlertAppends:
    """Existing alerts are preserved when a new alert is appended."""

    def test_existing_alerts_preserved(self, tmp_path: Path) -> None:
        """Pre-populated alerts.json keeps existing entries after append."""
        alerts_file = tmp_path / "alerts.json"
        existing_alert = {
            "id": "existing-123",
            "source": "medic",
            "severity": "critical",
            "title": "Existing alert",
            "body": "Some body",
            "created_at": "2026-01-01T00:00:00",
            "expires_at": None,
        }
        alerts_file.write_text(
            json.dumps({"alerts": [existing_alert]}),
            encoding="utf-8",
        )

        _setup_happy_path()
        mod.handle_runaway_log_detected(
            file_path="/var/log/test.log",
            branch="flow",
            rate_lines_per_min=500,
            sustained_duration_sec=60,
        )

        data = json.loads(alerts_file.read_text(encoding="utf-8"))
        assert len(data["alerts"]) == 2
        assert data["alerts"][0]["id"] == "existing-123"
        assert data["alerts"][1]["source"] == "prax"


# ---------------------------------------------------------------------------
# 11. Email send fails — returns early, no alert written, no cooldown
# ---------------------------------------------------------------------------


class TestEmailSendFails:
    """When _send_email returns False, no alert or cooldown is recorded."""

    def test_returns_early_no_alert_no_cooldown(self, tmp_path: Path) -> None:
        """Failed email send means no alert file and no cooldown entry."""
        send = MagicMock(return_value=False)
        mod.set_send_email_callback(send)
        file_path = "/var/log/test.log"

        mod.handle_runaway_log_detected(
            file_path=file_path,
            branch="flow",
            rate_lines_per_min=5000,
            sustained_duration_sec=60,
            severity="critical",
        )

        send.assert_called_once()
        alerts_file = tmp_path / "alerts.json"
        assert not alerts_file.exists()
        assert file_path not in mod._file_cooldowns


# ---------------------------------------------------------------------------
# 12. Decision log — every gating decision is recorded with an outcome
# ---------------------------------------------------------------------------


def _decision_entries(reason: str) -> list:
    """Collect decision-log entries written with the given reason."""
    calls = mod._append_jsonl.call_args_list  # type: ignore[union-attr]
    return [c[0][1] for c in calls if isinstance(c[0][1], dict) and c[0][1].get("reason") == reason]


class TestSuppressionLog:
    """Cooldown and mute suppressions write to the decision log."""

    def test_cooldown_writes_suppression_log(self) -> None:
        """Cooldown suppression writes reason='cooldown' via _append_jsonl."""
        _setup_happy_path()
        file_path = "/var/log/test.log"

        # First call dispatches normally
        mod.handle_runaway_log_detected(
            file_path=file_path,
            branch="flow",
            rate_lines_per_min=500,
            sustained_duration_sec=60,
        )

        # Reset mock to isolate suppression log call
        mod._append_jsonl.reset_mock()  # type: ignore[union-attr]

        # Second call is on cooldown — should write suppression log
        mod.handle_runaway_log_detected(
            file_path=file_path,
            branch="flow",
            rate_lines_per_min=500,
            sustained_duration_sec=120,
        )

        entries = _decision_entries("cooldown")
        assert len(entries) == 1
        assert entries[0]["file"] == file_path
        assert entries[0]["outcome"] == "suppressed"

    def test_volume_mute_writes_suppression_entry(self, tmp_path: Path) -> None:
        """Volume mute suppression writes outcome='suppressed', reason='volume_muted'."""
        _setup_happy_path()
        _write_config(tmp_path, {"volume_muted_branches": ["flow"]})

        mod.handle_runaway_log_detected(
            file_path="/var/log/test.log",
            branch="flow",
            rate_lines_per_min=500,
            sustained_duration_sec=60,
        )

        entries = _decision_entries("volume_muted")
        assert len(entries) == 1
        assert entries[0]["branch"] == "flow"
        assert entries[0]["outcome"] == "suppressed"

    def test_critical_bypass_writes_delivered_entry(self, tmp_path: Path) -> None:
        """A critical bypass is logged as delivered, not suppressed."""
        _setup_happy_path()
        _write_config(tmp_path, {"volume_muted_branches": ["flow"]})

        mod.handle_runaway_log_detected(
            file_path="/var/log/test.log",
            branch="flow",
            rate_lines_per_min=5000,
            sustained_duration_sec=60,
            severity="critical",
        )

        entries = _decision_entries("bypass_critical")
        assert len(entries) == 1
        assert entries[0]["outcome"] == "delivered"
        assert entries[0]["branch"] == "flow"
        assert not _decision_entries("volume_muted")

    def test_content_mute_writes_no_decision_entry(self, tmp_path: Path) -> None:
        """A content mute is not a runaway gate — it leaves no decision entry."""
        _setup_happy_path()
        _write_config(tmp_path, {"muted_branches": ["flow"]})

        mod.handle_runaway_log_detected(
            file_path="/var/log/test.log",
            branch="flow",
            rate_lines_per_min=500,
            sustained_duration_sec=60,
        )

        assert not _decision_entries("volume_muted")
        assert not _decision_entries("bypass_critical")


# ---------------------------------------------------------------------------
# 13. set_send_email_callback — sets the callback correctly
# ---------------------------------------------------------------------------


class TestSetSendEmailCallback:
    """Tests for set_send_email_callback."""

    def test_sets_callback_correctly(self) -> None:
        """Stores the callback as module-level _send_email."""
        callback = MagicMock()
        mod.set_send_email_callback(callback)
        assert mod._send_email is callback

    def test_overwrites_previous_callback(self) -> None:
        """Second call replaces the first callback."""
        first = MagicMock()
        second = MagicMock()
        mod.set_send_email_callback(first)
        mod.set_send_email_callback(second)
        assert mod._send_email is second


# ---------------------------------------------------------------------------
# 14. Observe-only WARNING — records with full fidelity, wakes nobody
# ---------------------------------------------------------------------------


def _wake_mock() -> MagicMock:
    """Return the mocked wake_branch installed by the autouse fixture."""
    from aipass.ai_mail.apps.handlers.dispatch.wake import wake_branch

    return wake_branch  # type: ignore[return-value]


def _read_alerts(tmp_path: Path) -> list:
    """Read the alert entries written to the redirected alerts.json."""
    alerts_file = tmp_path / "alerts.json"
    if not alerts_file.exists():
        return []
    return json.loads(alerts_file.read_text(encoding="utf-8")).get("alerts", [])


class TestObserveOnlyWarning:
    """WARNING tier is observe-only: full record, no email, no wake.

    The 100 lines/min threshold predates routine multi-agent fleets and fires
    on healthy chatty logs, so a WARNING must never pull an agent out of sleep.
    """

    def test_warning_never_emails_and_never_wakes(self) -> None:
        """A WARNING sends no email and wakes no branch."""
        send = _setup_happy_path()

        mod.handle_runaway_log_detected(
            file_path="/var/log/test.log",
            branch="flow",
            rate_lines_per_min=150,
            sustained_duration_sec=720,
            severity="warning",
        )

        send.assert_not_called()
        _wake_mock().assert_not_called()

    def test_warning_default_severity_never_wakes(self) -> None:
        """Severity defaults to 'warning' — the default path wakes nobody either."""
        send = _setup_happy_path()

        mod.handle_runaway_log_detected(
            file_path="/var/log/test.log",
            branch="flow",
            rate_lines_per_min=150,
            sustained_duration_sec=720,
        )

        send.assert_not_called()
        _wake_mock().assert_not_called()

    def test_warning_writes_alert_with_full_fidelity(self, tmp_path: Path) -> None:
        """The durable record keeps file, severity, branch, rate and duration.

        Asserts the no-wake half too: writing the alert alone is what the old
        dispatch path did as well, so only the pair pins observe-only.
        """
        send = _setup_happy_path()

        mod.handle_runaway_log_detected(
            file_path="/var/log/chatty.log",
            branch="flow",
            rate_lines_per_min=150,
            sustained_duration_sec=720,
            severity="warning",
        )

        alerts = _read_alerts(tmp_path)
        assert len(alerts) == 1
        alert = alerts[0]
        assert alert["severity"] == "warning"
        assert alert["source"] == "prax"
        assert "chatty.log" in alert["title"]
        assert "/var/log/chatty.log" in alert["body"]
        assert "150 lines/min" in alert["body"]
        assert "720s" in alert["body"]
        assert "flow" in alert["body"]

        send.assert_not_called()
        _wake_mock().assert_not_called()

    def test_warning_writes_observed_decision_entry(self) -> None:
        """Decision trail records outcome='observed', reason='observe_only'."""
        _setup_happy_path()

        mod.handle_runaway_log_detected(
            file_path="/var/log/test.log",
            branch="flow",
            rate_lines_per_min=150,
            sustained_duration_sec=720,
            severity="warning",
        )

        entries = _decision_entries("observe_only")
        assert len(entries) == 1
        assert entries[0]["outcome"] == "observed"
        assert entries[0]["branch"] == "flow"
        assert entries[0]["file"] == "/var/log/test.log"
        # Not a suppression (we recorded it) and not a delivery (nobody was told)
        assert entries[0]["outcome"] not in {"suppressed", "delivered"}

    def test_warning_records_file_cooldown(self, tmp_path: Path) -> None:
        """Observe-only still books the cooldown — the record must not flood itself."""
        _setup_happy_path()
        file_path = "/var/log/test.log"

        mod.handle_runaway_log_detected(
            file_path=file_path,
            branch="flow",
            rate_lines_per_min=150,
            sustained_duration_sec=720,
            severity="warning",
        )
        assert file_path in mod._file_cooldowns
        assert len(_read_alerts(tmp_path)) == 1

        # Second detection interval for the same file is gated by the cooldown
        mod.handle_runaway_log_detected(
            file_path=file_path,
            branch="flow",
            rate_lines_per_min=150,
            sustained_duration_sec=780,
            severity="warning",
        )
        assert len(_read_alerts(tmp_path)) == 1
        assert len(_decision_entries("cooldown")) == 1
        assert len(_decision_entries("observe_only")) == 1

    def test_warning_records_fully_without_email_callback(self, tmp_path: Path) -> None:
        """REGRESSION: no email callback must not silence the observe-only record.

        The callback guard predates the split and used to return before any
        record was written; a WARNING no longer sends, so it must not care.
        """
        # _send_email stays None (no set_send_email_callback call)
        file_path = "/var/log/test.log"

        mod.handle_runaway_log_detected(
            file_path=file_path,
            branch="flow",
            rate_lines_per_min=150,
            sustained_duration_sec=720,
            severity="warning",
        )

        assert len(_read_alerts(tmp_path)) == 1
        assert len(_decision_entries("observe_only")) == 1
        assert file_path in mod._file_cooldowns
        _wake_mock().assert_not_called()


# ---------------------------------------------------------------------------
# 15. CRITICAL tier — NO-OVERREACH GUARDS (pass before and after the split)
#
# These deliberately pass against both the old and new handler: their whole
# job is to prove the observe-only split did not touch the CRITICAL path.
# ---------------------------------------------------------------------------


class TestCriticalUnchanged:
    """NO-OVERREACH: CRITICAL keeps email + wake exactly as before the split."""

    def test_critical_emails_and_wakes(self, tmp_path: Path) -> None:
        """NO-OVERREACH: CRITICAL sends the email and wakes the branch."""
        send = _setup_happy_path()

        mod.handle_runaway_log_detected(
            file_path="/var/log/test.log",
            branch="flow",
            rate_lines_per_min=5000,
            sustained_duration_sec=60,
            severity="critical",
        )

        send.assert_called_once()
        assert send.call_args.kwargs["to_branch"] == "@flow"
        _wake_mock().assert_called_once_with("@flow", fresh=False, sender="@trigger")
        assert len(_read_alerts(tmp_path)) == 1
        assert "/var/log/test.log" in mod._file_cooldowns

    def test_critical_bypasses_volume_mute_and_still_wakes(self, tmp_path: Path) -> None:
        """NO-OVERREACH: a volume mute still does not stop a CRITICAL wake."""
        send = _setup_happy_path()
        _write_config(tmp_path, {"volume_muted_branches": ["flow"]})

        mod.handle_runaway_log_detected(
            file_path="/var/log/test.log",
            branch="flow",
            rate_lines_per_min=5000,
            sustained_duration_sec=60,
            severity="critical",
        )

        send.assert_called_once()
        _wake_mock().assert_called_once_with("@flow", fresh=False, sender="@trigger")
        assert _decision_entries("bypass_critical")[0]["outcome"] == "delivered"

    def test_critical_send_failure_logs_and_records_nothing(self, tmp_path: Path) -> None:
        """NO-OVERREACH: sent=False still logs, returns, and records no dispatch."""
        send = MagicMock(return_value=False)
        mod.set_send_email_callback(send)
        file_path = "/var/log/test.log"

        mod.handle_runaway_log_detected(
            file_path=file_path,
            branch="flow",
            rate_lines_per_min=5000,
            sustained_duration_sec=60,
            severity="critical",
        )

        send.assert_called_once()
        _wake_mock().assert_not_called()
        assert not _read_alerts(tmp_path)
        assert file_path not in mod._file_cooldowns
        assert not _decision_entries("observe_only")

        calls = mod._append_jsonl.call_args_list  # type: ignore[union-attr]
        warnings = [c[0][1] for c in calls if isinstance(c[0][1], dict) and c[0][1].get("level") == "WARNING"]
        assert any("Email delivery failed" in w["msg"] for w in warnings)

    def test_critical_unknown_branch_still_wakes_prax(self) -> None:
        """NO-OVERREACH: the @prax fallback recipient still gets woken."""
        send = _setup_happy_path()

        mod.handle_runaway_log_detected(
            file_path="/var/log/test.log",
            branch="UNKNOWN",
            rate_lines_per_min=5000,
            sustained_duration_sec=60,
            severity="critical",
        )

        assert send.call_args.kwargs["to_branch"] == "@prax"
        _wake_mock().assert_called_once_with("@prax", fresh=False, sender="@trigger")


# ---------------------------------------------------------------------------
# 16. Operation log naming — never log a dispatch that did not happen
# ---------------------------------------------------------------------------


class TestOperationLogNaming:
    """The two tiers log distinct operation names."""

    def _operations(self, log_mock: MagicMock) -> list[str]:
        """Extract operation names from a patched log_operation mock."""
        return [c[0][0] for c in log_mock.call_args_list]

    def test_warning_logs_runaway_observed(self) -> None:
        """A WARNING logs 'runaway_observed' — never a dispatch that did not happen."""
        _setup_happy_path()

        with patch.object(mod.json_handler, "log_operation") as log_op:
            mod.handle_runaway_log_detected(
                file_path="/var/log/test.log",
                branch="flow",
                rate_lines_per_min=150,
                sustained_duration_sec=720,
                severity="warning",
            )

        ops = self._operations(log_op)
        assert ops == ["runaway_observed"]
        assert "runaway_dispatch_sent" not in ops

    def test_critical_logs_runaway_dispatch_sent(self) -> None:
        """NO-OVERREACH: a CRITICAL still logs 'runaway_dispatch_sent'."""
        _setup_happy_path()

        with patch.object(mod.json_handler, "log_operation") as log_op:
            mod.handle_runaway_log_detected(
                file_path="/var/log/test.log",
                branch="flow",
                rate_lines_per_min=5000,
                sustained_duration_sec=60,
                severity="critical",
            )

        ops = self._operations(log_op)
        assert ops == ["runaway_dispatch_sent"]
        assert "runaway_observed" not in ops

    def test_tier_operation_names_differ(self) -> None:
        """The same file across both tiers produces two different operation names."""
        _setup_happy_path()

        with patch.object(mod.json_handler, "log_operation") as log_op:
            mod.handle_runaway_log_detected(
                file_path="/var/log/warn.log",
                branch="flow",
                rate_lines_per_min=150,
                sustained_duration_sec=720,
                severity="warning",
            )
            mod.handle_runaway_log_detected(
                file_path="/var/log/crit.log",
                branch="flow",
                rate_lines_per_min=5000,
                sustained_duration_sec=60,
                severity="critical",
            )

        ops = self._operations(log_op)
        assert len(set(ops)) == 2
        assert ops == ["runaway_observed", "runaway_dispatch_sent"]


class TestVolumeMuteMigration:
    """Volume mutes are read through the legacy-path migration."""

    def test_volume_mute_survives_migration(self, tmp_path: Path) -> None:
        """A volume mute written under the old filename still silences the alert."""
        mod.LEGACY_MEDIC_STATE_FILE.write_text(
            json.dumps({"config": {"volume_muted_branches": [{"name": "hooks", "expires_at": None}]}}),
            encoding="utf-8",
        )

        assert mod._is_branch_volume_muted("hooks") is True
        assert mod.MEDIC_STATE_FILE.exists()
        assert not mod.LEGACY_MEDIC_STATE_FILE.exists()
