# =================== AIPass ====================
# Name: test_runaway_handler.py
# Description: Tests for the runaway_log_detected event handler
# Version: 1.0.2
# Created: 2026-08-09
# Modified: 2026-10-24
# =============================================

"""Tests for apps/handlers/events/runaway_handler.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(behaviour) — the detection in apps/handlers/log_watcher.py; the log watcher tests cover it
import json
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import cast
from unittest.mock import MagicMock, patch

import pytest

from aipass.ai_mail.apps.modules import door_wake as ai_mail_wake
from aipass.trigger.apps import config as trigger_config
from aipass.trigger.apps.handlers import medic_state
from aipass.trigger.apps.handlers.events import runaway_handler as mod

# The handler only keys cooldowns and names alerts by this path; it never opens it.
RUNAWAY_LOG = str(Path(tempfile.gettempdir()) / "test.log")


# Both sidecar writers funnel through config's one prax hook: patching it captures the trail.
_trail = MagicMock()


@pytest.fixture(autouse=True)
def _reset_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):  # type: ignore[misc]
    """Reset module state and redirect file paths to tmp_path."""
    monkeypatch.setattr(mod, "_file_cooldowns", {})
    mod._send_email = None

    monkeypatch.setattr(medic_state, "MEDIC_STATE_FILE", tmp_path / "medic_state.json")
    monkeypatch.setattr(medic_state, "LEGACY_MEDIC_STATE_FILE", tmp_path / "trigger_config.json")
    monkeypatch.setattr(medic_state, "logger", MagicMock())
    monkeypatch.setattr(mod, "ALERTS_FILE", tmp_path / "alerts.json")
    _trail.reset_mock()
    monkeypatch.setattr(trigger_config, "_append_jsonl", _trail)

    monkeypatch.setattr(ai_mail_wake, "wake_branch", MagicMock())

    yield


def _setup_happy_path() -> MagicMock:
    """Set up a successful dispatch scenario and return the send_email mock."""
    send_mock = MagicMock(return_value=True)
    mod.set_send_email_callback(send_mock)
    return send_mock


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


class TestPerFileCooldown:
    """Second call for the same file within 30min cooldown is suppressed."""

    def test_second_call_within_cooldown_suppressed(self) -> None:
        """Second call for the same file is suppressed; another file still dispatches."""
        send = _setup_happy_path()

        mod.handle_runaway_log_detected(
            file_path=RUNAWAY_LOG,
            branch="flow",
            rate_lines_per_min=5000,
            sustained_duration_sec=60,
            severity="critical",
        )
        assert send.call_count == 1

        mod.handle_runaway_log_detected(
            file_path=RUNAWAY_LOG,
            branch="flow",
            rate_lines_per_min=5000,
            sustained_duration_sec=120,
            severity="critical",
        )
        assert send.call_count == 1

        mod.handle_runaway_log_detected(
            file_path=str(Path(tempfile.gettempdir()) / "other.log"),
            branch="flow",
            rate_lines_per_min=5000,
            sustained_duration_sec=60,
            severity="critical",
        )
        subjects = [c.kwargs["subject"] for c in send.call_args_list]
        assert [subject.split()[1] for subject in subjects] == ["test.log", "other.log"]


class TestCooldownExpired:
    """Call after cooldown window expires dispatches again."""

    def test_dispatches_again_after_cooldown_expires(self) -> None:
        """Dispatch succeeds again once the 1800s cooldown has elapsed.

        The clock stub stands at the handler's own time binding; the process clock is never patched."""
        send = _setup_happy_path()

        mod.handle_runaway_log_detected(
            file_path=RUNAWAY_LOG,
            branch="flow",
            rate_lines_per_min=5000,
            sustained_duration_sec=60,
            severity="critical",
        )
        assert send.call_count == 1

        later = time.time() + mod.COOLDOWN_SECONDS + 1
        with patch.object(mod, "time", MagicMock(time=MagicMock(return_value=later))):
            mod.handle_runaway_log_detected(
                file_path=RUNAWAY_LOG,
                branch="flow",
                rate_lines_per_min=5000,
                sustained_duration_sec=120,
                severity="critical",
            )
        assert send.call_count == 2


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

        Agents medic-mute before build work, exactly when floods happen."""
        send = _setup_happy_path()

        _write_config(tmp_path, {"muted_branches": ["flow"]})

        mod.handle_runaway_log_detected(
            file_path=RUNAWAY_LOG,
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
            file_path=RUNAWAY_LOG,
            branch="flow",
            rate_lines_per_min=500,
            sustained_duration_sec=60,
        )
        send.assert_not_called()

    def test_a_mute_stored_with_an_at_reads_as_muted(self, tmp_path: Path) -> None:
        """A mute stored as "@flow" is the mute "flow", as medic status reads it.
        Red first: the handler compared the raw entry and let "@flow" through.
        """
        _write_config(tmp_path, {"volume_muted_branches": [{"name": "@flow", "expires_at": None}]})

        mod.handle_runaway_log_detected(file_path=RUNAWAY_LOG, branch="FLOW", rate_lines_per_min=500)

        assert [e["outcome"] for e in _decision_entries("volume_muted")] == ["suppressed"]

    def test_expired_volume_mute_delivers(self, tmp_path: Path) -> None:
        """An expired volume mute entry does not suppress."""
        send = _setup_happy_path()

        expired = (datetime.now() - timedelta(hours=1)).isoformat()
        _write_config(tmp_path, {"volume_muted_branches": [{"name": "flow", "expires_at": expired}]})

        mod.handle_runaway_log_detected(
            file_path=RUNAWAY_LOG,
            branch="flow",
            rate_lines_per_min=5000,
            sustained_duration_sec=60,
            severity="critical",
        )
        assert [c.kwargs["to_branch"] for c in send.call_args_list] == ["@flow"]

    def test_critical_bypasses_volume_mute(self, tmp_path: Path) -> None:
        """CRITICAL runaways deliver even through an active volume mute."""
        send = _setup_happy_path()

        _write_config(tmp_path, {"volume_muted_branches": ["flow"]})

        mod.handle_runaway_log_detected(
            file_path=RUNAWAY_LOG,
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
            file_path=RUNAWAY_LOG,
            branch="flow",
            rate_lines_per_min=5000,
            sustained_duration_sec=60,
            severity="CRITICAL",
        )
        assert [c.kwargs["to_branch"] for c in send.call_args_list] == ["@flow"]

    def test_warning_still_respects_volume_mute(self, tmp_path: Path) -> None:
        """Non-critical runaways still honour an explicit volume mute.

        Observe-only makes the no-email half trivial; a volume-muted WARNING must not even be recorded."""
        send = _setup_happy_path()

        _write_config(tmp_path, {"volume_muted_branches": ["flow"]})

        mod.handle_runaway_log_detected(
            file_path=RUNAWAY_LOG,
            branch="flow",
            rate_lines_per_min=500,
            sustained_duration_sec=60,
            severity="warning",
        )
        send.assert_not_called()
        assert not (tmp_path / "alerts.json").exists()

    def test_unreadable_mute_file_fails_open_and_says_so(self, tmp_path: Path) -> None:
        """An unreadable medic_state.json is not a mute, and the trail says it was unread.

        Failing open is kept (a runaway must reach someone); one event is one trail line."""
        (tmp_path / "medic_state.json").write_text("{not json", encoding="utf-8")

        mod.handle_runaway_log_detected(
            file_path=RUNAWAY_LOG,
            branch="flow",
            rate_lines_per_min=150,
            sustained_duration_sec=720,
            severity="warning",
        )

        entries = _decision_entries("mute_unreadable")
        assert [(e["outcome"], e["branch"]) for e in entries] == [("observed", "flow")]
        assert _decision_entries("observe_only") == []
        assert len(_read_alerts(tmp_path)) == 1


class TestUnknownBranch:
    """UNKNOWN branch falls back to @prax."""

    def test_unknown_branch_dispatches_to_prax(self) -> None:
        """Branch='UNKNOWN' dispatches email to @prax."""
        send = _setup_happy_path()

        mod.handle_runaway_log_detected(
            file_path=RUNAWAY_LOG,
            branch="UNKNOWN",
            rate_lines_per_min=5000,
            sustained_duration_sec=60,
            severity="critical",
        )
        send.assert_called_once()
        assert send.call_args[1]["to_branch"] == "@prax"


class TestNoneBranch:
    """None branch falls back to @prax."""

    def test_none_branch_dispatches_to_prax(self) -> None:
        """Branch=None dispatches email to @prax."""
        send = _setup_happy_path()

        mod.handle_runaway_log_detected(
            file_path=RUNAWAY_LOG,
            branch=None,
            rate_lines_per_min=5000,
            sustained_duration_sec=60,
            severity="critical",
        )
        send.assert_called_once()
        assert send.call_args[1]["to_branch"] == "@prax"


class TestNoEmailCallback:
    """Handler logs warning and returns when _send_email is None.

    Only the CRITICAL path needs a callback; observe-only WARNINGs never reach this guard."""

    def test_logs_warning_no_dispatch(self) -> None:
        """Logs a WARNING to the sidecar trail when no callback set."""
        mod.handle_runaway_log_detected(
            file_path=RUNAWAY_LOG,
            branch="flow",
            rate_lines_per_min=5000,
            sustained_duration_sec=60,
            severity="critical",
        )

        calls = _trail.call_args_list
        warning_calls = [c for c in calls if isinstance(c[0][1], dict) and c[0][1].get("level") == "WARNING"]
        assert len(warning_calls) >= 1
        assert "No email callback" in warning_calls[0][0][1]["msg"]


class TestSuccessfulDispatch:
    """Full happy-path: email, wake, alert, cooldown."""

    def test_full_dispatch(self, tmp_path: Path) -> None:
        """Email sent with correct kwargs, alert file exists, cooldown recorded."""
        send = _setup_happy_path()
        file_path = RUNAWAY_LOG

        mod.handle_runaway_log_detected(
            file_path=file_path,
            branch="flow",
            rate_lines_per_min=500,
            sustained_duration_sec=60,
            severity="critical",
        )

        send.assert_called_once()
        kwargs = send.call_args[1]
        assert kwargs["to_branch"] == "@flow"
        assert kwargs["auto_execute"] is True
        assert kwargs["reply_to"] == "@devpulse"
        assert kwargs["from_branch"] == "@trigger"
        assert "[RUNAWAY]" in kwargs["subject"]
        assert "CRITICAL" in kwargs["subject"]

        _wake_mock().assert_called_once_with("@flow", fresh=False, sender="@trigger")

        alerts_file = tmp_path / "alerts.json"
        assert alerts_file.exists()

        assert _gated_by_cooldown(file_path), "no cooldown was booked"


class TestAlertFileSchema:
    """Alert written to .aipass/alerts.json with correct schema."""

    def test_alert_has_required_fields(self, tmp_path: Path) -> None:
        """Schema: {alerts: [{id, source, severity, title, body, created_at, expires_at}]}."""
        _setup_happy_path()

        mod.handle_runaway_log_detected(
            file_path=RUNAWAY_LOG,
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
            file_path=RUNAWAY_LOG,
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
            file_path=RUNAWAY_LOG,
            branch="flow",
            rate_lines_per_min=500,
            sustained_duration_sec=60,
            forever=True,
        )

        alerts_file = tmp_path / "alerts.json"
        data = json.loads(alerts_file.read_text(encoding="utf-8"))
        assert data["alerts"][0]["expires_at"] is None


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
            file_path=RUNAWAY_LOG,
            branch="flow",
            rate_lines_per_min=500,
            sustained_duration_sec=60,
        )

        data = json.loads(alerts_file.read_text(encoding="utf-8"))
        assert len(data["alerts"]) == 2
        assert data["alerts"][0]["id"] == "existing-123"
        assert data["alerts"][1]["source"] == "prax"


class TestEmailSendFails:
    """When _send_email returns False, no alert or cooldown is recorded."""

    def test_returns_early_no_alert_no_cooldown(self, tmp_path: Path) -> None:
        """Failed email send means no alert file and no cooldown entry."""
        send = MagicMock(return_value=False)
        mod.set_send_email_callback(send)
        file_path = RUNAWAY_LOG

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
        assert not _gated_by_cooldown(file_path), "a failed dispatch booked a cooldown"


def _decision_entries(reason: str) -> list:
    """Collect decision-log entries written with the given reason."""
    calls = _trail.call_args_list
    return [c[0][1] for c in calls if isinstance(c[0][1], dict) and c[0][1].get("reason") == reason]


def _gated_by_cooldown(file_path: str) -> bool:
    """Detect the same file again at once; True when the handler's own trail says its cooldown gated it.

    _file_cooldowns is module state; a gated probe sends nothing."""
    before = len(_decision_entries("cooldown"))
    mod.handle_runaway_log_detected(
        file_path=file_path, branch="flow", rate_lines_per_min=5000, sustained_duration_sec=60, severity="critical"
    )
    return len(_decision_entries("cooldown")) == before + 1


def _trail_lines() -> list:
    """Collect every line written to the decision trail, in order."""
    return [c[0][1] for c in _trail.call_args_list if c[0][0] == mod.DECISION_LOG]


class TestSuppressionLog:
    """Cooldown and mute suppressions write to the decision log."""

    def test_cooldown_writes_suppression_log(self) -> None:
        """Cooldown suppression writes reason='cooldown' to the decision log."""
        _setup_happy_path()
        file_path = RUNAWAY_LOG

        mod.handle_runaway_log_detected(
            file_path=file_path,
            branch="flow",
            rate_lines_per_min=500,
            sustained_duration_sec=60,
        )

        _trail.reset_mock()

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
            file_path=RUNAWAY_LOG,
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
            file_path=RUNAWAY_LOG,
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

    def test_critical_bypass_that_fails_to_send_is_not_delivered(self, tmp_path: Path) -> None:
        """Delivered is written after the send returns, never before it.

        A refused send must not leave a trail saying delivered."""
        send = MagicMock(return_value=False)
        mod.set_send_email_callback(send)
        _write_config(tmp_path, {"volume_muted_branches": ["flow"]})

        mod.handle_runaway_log_detected(
            file_path=RUNAWAY_LOG,
            branch="flow",
            rate_lines_per_min=5000,
            sustained_duration_sec=60,
            severity="critical",
        )

        send.assert_called_once()
        assert _decision_entries("bypass_critical") == []

    def test_critical_over_an_unreadable_mute_is_delivered_once(self, tmp_path: Path) -> None:
        """A sent critical over a mute nobody could read leaves one line: delivered, mute_unreadable."""
        send = _setup_happy_path()
        (tmp_path / "medic_state.json").write_text("{not json", encoding="utf-8")

        mod.handle_runaway_log_detected(
            file_path=RUNAWAY_LOG,
            branch="flow",
            rate_lines_per_min=5000,
            sustained_duration_sec=60,
            severity="critical",
        )

        send.assert_called_once()
        assert [(e["outcome"], e["reason"]) for e in _trail_lines()] == [("delivered", "mute_unreadable")]

    def test_an_unmuted_critical_that_was_sent_is_delivered(self) -> None:
        """The trail records what happened to every event, the ones the gate passed included."""
        _setup_happy_path()

        mod.handle_runaway_log_detected(
            file_path=RUNAWAY_LOG,
            branch="flow",
            rate_lines_per_min=5000,
            sustained_duration_sec=60,
            severity="critical",
        )

        assert [(e["outcome"], e["reason"]) for e in _trail_lines()] == [("delivered", "critical")]

    def test_a_critical_whose_send_was_refused_is_failed(self) -> None:
        """A send that answers False is one line, failed, send_refused. Red first on 2026-09-29."""
        mod.set_send_email_callback(MagicMock(return_value=False))

        mod.handle_runaway_log_detected(
            file_path=RUNAWAY_LOG,
            branch="flow",
            rate_lines_per_min=5000,
            sustained_duration_sec=60,
            severity="critical",
        )

        assert [(e["outcome"], e["reason"]) for e in _trail_lines()] == [("failed", "send_refused")]

    def test_a_critical_with_no_mail_callback_is_failed(self) -> None:
        """No callback to send with is one line, failed, no_callback. Red first on 2026-09-29."""
        mod.handle_runaway_log_detected(
            file_path=RUNAWAY_LOG,
            branch="flow",
            rate_lines_per_min=5000,
            sustained_duration_sec=60,
            severity="critical",
        )

        assert [(e["outcome"], e["reason"]) for e in _trail_lines()] == [("failed", "no_callback")]

    def test_content_mute_writes_no_decision_entry(self, tmp_path: Path) -> None:
        """A content mute is not a runaway gate — it leaves no decision entry."""
        _setup_happy_path()
        _write_config(tmp_path, {"muted_branches": ["flow"]})

        mod.handle_runaway_log_detected(
            file_path=RUNAWAY_LOG,
            branch="flow",
            rate_lines_per_min=500,
            sustained_duration_sec=60,
        )

        assert not _decision_entries("volume_muted")
        assert not _decision_entries("bypass_critical")


class TestSetSendEmailCallback:
    """Tests for set_send_email_callback."""

    def test_sets_callback_correctly(self) -> None:
        """The callback set is the one a CRITICAL dispatch sends through."""
        callback = MagicMock(return_value=True)
        mod.set_send_email_callback(callback)

        mod.handle_runaway_log_detected(
            file_path=RUNAWAY_LOG,
            branch="flow",
            rate_lines_per_min=5000,
            sustained_duration_sec=60,
            severity="critical",
        )

        callback.assert_called_once()
        assert callback.call_args.kwargs["to_branch"] == "@flow"

    def test_overwrites_previous_callback(self) -> None:
        """Second call replaces the first callback: only the second one sends."""
        first = MagicMock(return_value=True)
        second = MagicMock(return_value=True)
        mod.set_send_email_callback(first)
        mod.set_send_email_callback(second)

        mod.handle_runaway_log_detected(
            file_path=RUNAWAY_LOG,
            branch="flow",
            rate_lines_per_min=5000,
            sustained_duration_sec=60,
            severity="critical",
        )

        second.assert_called_once()
        assert second.call_args.kwargs["to_branch"] == "@flow"
        first.assert_not_called()


def _wake_mock() -> MagicMock:
    """Return the mocked wake_branch installed by the autouse fixture."""
    return cast(MagicMock, ai_mail_wake.wake_branch)


def _read_alerts(tmp_path: Path) -> list:
    """Read the alert entries written to the redirected alerts.json."""
    alerts_file = tmp_path / "alerts.json"
    if not alerts_file.exists():
        return []
    return json.loads(alerts_file.read_text(encoding="utf-8")).get("alerts", [])


class TestObserveOnlyWarning:
    """WARNING tier is observe-only: full record, no email, no wake.

    The 100 lines/min threshold fires on healthy chatty logs, so a WARNING never wakes an agent."""

    def test_warning_never_emails_and_never_wakes(self) -> None:
        """A WARNING sends no email and wakes no branch."""
        send = _setup_happy_path()

        mod.handle_runaway_log_detected(
            file_path=RUNAWAY_LOG,
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
            file_path=RUNAWAY_LOG,
            branch="flow",
            rate_lines_per_min=150,
            sustained_duration_sec=720,
        )

        send.assert_not_called()
        _wake_mock().assert_not_called()

    def test_warning_writes_alert_with_full_fidelity(self, tmp_path: Path) -> None:
        """The durable record keeps file, severity, branch, rate and duration.

        Only the pair with the no-wake assert pins observe-only; writing the alert alone does not."""
        send = _setup_happy_path()

        mod.handle_runaway_log_detected(
            file_path=str(tmp_path / "chatty.log"),
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
        assert str(tmp_path / "chatty.log") in alert["body"]
        assert "150 lines/min" in alert["body"]
        assert "720s" in alert["body"]
        assert "flow" in alert["body"]

        send.assert_not_called()
        _wake_mock().assert_not_called()

    def test_warning_writes_observed_decision_entry(self) -> None:
        """Decision trail records outcome='observed', reason='observe_only'."""
        _setup_happy_path()

        mod.handle_runaway_log_detected(
            file_path=RUNAWAY_LOG,
            branch="flow",
            rate_lines_per_min=150,
            sustained_duration_sec=720,
            severity="warning",
        )

        entries = _decision_entries("observe_only")
        assert len(entries) == 1
        assert entries[0]["outcome"] == "observed"
        assert entries[0]["branch"] == "flow"
        assert entries[0]["file"] == RUNAWAY_LOG
        assert entries[0]["outcome"] not in {"suppressed", "delivered"}

    def test_warning_records_file_cooldown(self, tmp_path: Path) -> None:
        """Observe-only still books the cooldown — the record must not flood itself."""
        _setup_happy_path()
        file_path = RUNAWAY_LOG

        mod.handle_runaway_log_detected(
            file_path=file_path,
            branch="flow",
            rate_lines_per_min=150,
            sustained_duration_sec=720,
            severity="warning",
        )
        assert len(_read_alerts(tmp_path)) == 1

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

        A WARNING no longer sends, so the callback guard must not return before the record."""
        file_path = RUNAWAY_LOG

        mod.handle_runaway_log_detected(
            file_path=file_path,
            branch="flow",
            rate_lines_per_min=150,
            sustained_duration_sec=720,
            severity="warning",
        )

        assert len(_read_alerts(tmp_path)) == 1
        assert len(_decision_entries("observe_only")) == 1
        assert _gated_by_cooldown(file_path), "no cooldown was booked"
        _wake_mock().assert_not_called()


class TestCriticalUnchanged:
    """NO-OVERREACH: CRITICAL keeps email + wake exactly as before the split."""

    def test_critical_emails_and_wakes(self, tmp_path: Path) -> None:
        """NO-OVERREACH: CRITICAL sends the email and wakes the branch."""
        send = _setup_happy_path()

        mod.handle_runaway_log_detected(
            file_path=RUNAWAY_LOG,
            branch="flow",
            rate_lines_per_min=5000,
            sustained_duration_sec=60,
            severity="critical",
        )

        send.assert_called_once()
        assert send.call_args.kwargs["to_branch"] == "@flow"
        _wake_mock().assert_called_once_with("@flow", fresh=False, sender="@trigger")
        assert len(_read_alerts(tmp_path)) == 1
        assert _gated_by_cooldown(RUNAWAY_LOG), "no cooldown was booked"

    def test_critical_bypasses_volume_mute_and_still_wakes(self, tmp_path: Path) -> None:
        """NO-OVERREACH: a volume mute still does not stop a CRITICAL wake."""
        send = _setup_happy_path()
        _write_config(tmp_path, {"volume_muted_branches": ["flow"]})

        mod.handle_runaway_log_detected(
            file_path=RUNAWAY_LOG,
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
        file_path = RUNAWAY_LOG

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
        assert not _decision_entries("observe_only")
        assert not _gated_by_cooldown(file_path), "a failed dispatch booked a cooldown"

        calls = _trail.call_args_list
        warnings = [c[0][1] for c in calls if isinstance(c[0][1], dict) and c[0][1].get("level") == "WARNING"]
        assert any("Email delivery failed" in w["msg"] for w in warnings)

    def test_critical_unknown_branch_still_wakes_prax(self) -> None:
        """NO-OVERREACH: the @prax fallback recipient still gets woken."""
        send = _setup_happy_path()

        mod.handle_runaway_log_detected(
            file_path=RUNAWAY_LOG,
            branch="UNKNOWN",
            rate_lines_per_min=5000,
            sustained_duration_sec=60,
            severity="critical",
        )

        assert send.call_args.kwargs["to_branch"] == "@prax"
        _wake_mock().assert_called_once_with("@prax", fresh=False, sender="@trigger")


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
                file_path=RUNAWAY_LOG,
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
                file_path=RUNAWAY_LOG,
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
                file_path=str(Path(tempfile.gettempdir()) / "warn.log"),
                branch="flow",
                rate_lines_per_min=150,
                sustained_duration_sec=720,
                severity="warning",
            )
            mod.handle_runaway_log_detected(
                file_path=str(Path(tempfile.gettempdir()) / "crit.log"),
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
        medic_state.LEGACY_MEDIC_STATE_FILE.write_text(
            json.dumps({"config": {"volume_muted_branches": [{"name": "hooks", "expires_at": None}]}}),
            encoding="utf-8",
        )

        mod.handle_runaway_log_detected(file_path=RUNAWAY_LOG, branch="hooks", severity="warning")

        assert [e["outcome"] for e in _decision_entries("volume_muted")] == ["suppressed"]
        assert medic_state.MEDIC_STATE_FILE.exists()
        assert not medic_state.LEGACY_MEDIC_STATE_FILE.exists()
