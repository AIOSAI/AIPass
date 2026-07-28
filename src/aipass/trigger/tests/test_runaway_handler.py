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

    monkeypatch.setattr(mod, "TRIGGER_CONFIG_FILE", tmp_path / "trigger_config.json")
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
            rate_lines_per_min=500,
            sustained_duration_sec=60,
        )
        assert send.call_count == 1

        # Second call — same file, should be suppressed
        mod.handle_runaway_log_detected(
            file_path="/var/log/test.log",
            branch="flow",
            rate_lines_per_min=500,
            sustained_duration_sec=120,
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
            rate_lines_per_min=500,
            sustained_duration_sec=60,
        )
        assert send.call_count == 1

        # Advance past 1800s cooldown
        mock_time.time.return_value = 1_000_000.0 + 1801
        mod.handle_runaway_log_detected(
            file_path="/var/log/test.log",
            branch="flow",
            rate_lines_per_min=500,
            sustained_duration_sec=120,
        )
        assert send.call_count == 2


# ---------------------------------------------------------------------------
# 4. Branch muted — muted branch is suppressed
# ---------------------------------------------------------------------------


class TestBranchMuted:
    """Muted branch dispatch is suppressed."""

    def test_muted_branch_suppressed(self, tmp_path: Path) -> None:
        """Branch listed in muted_branches is suppressed — no email sent."""
        send = _setup_happy_path()

        config_file = tmp_path / "trigger_config.json"
        config_file.write_text(
            json.dumps({"config": {"muted_branches": ["flow"]}}),
            encoding="utf-8",
        )

        mod.handle_runaway_log_detected(
            file_path="/var/log/test.log",
            branch="flow",
            rate_lines_per_min=500,
            sustained_duration_sec=60,
        )
        send.assert_not_called()


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
            rate_lines_per_min=500,
            sustained_duration_sec=60,
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
            rate_lines_per_min=500,
            sustained_duration_sec=60,
        )
        send.assert_called_once()
        assert send.call_args[1]["to_branch"] == "@prax"


# ---------------------------------------------------------------------------
# 7. No email callback — logs warning, no dispatch
# ---------------------------------------------------------------------------


class TestNoEmailCallback:
    """Handler logs warning and returns when _send_email is None."""

    def test_logs_warning_no_dispatch(self) -> None:
        """Logs warning via _append_jsonl when no callback set."""
        # _send_email stays None (no set_send_email_callback call)
        mod.handle_runaway_log_detected(
            file_path="/var/log/test.log",
            branch="flow",
            rate_lines_per_min=500,
            sustained_duration_sec=60,
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
            rate_lines_per_min=500,
            sustained_duration_sec=60,
        )

        send.assert_called_once()
        alerts_file = tmp_path / "alerts.json"
        assert not alerts_file.exists()
        assert file_path not in mod._file_cooldowns


# ---------------------------------------------------------------------------
# 12. Suppression log written — cooldown and mute both write suppression log
# ---------------------------------------------------------------------------


class TestSuppressionLog:
    """Cooldown and mute suppressions write to the suppression log."""

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

        calls = mod._append_jsonl.call_args_list  # type: ignore[union-attr]
        suppression_calls = [c for c in calls if isinstance(c[0][1], dict) and c[0][1].get("reason") == "cooldown"]
        assert len(suppression_calls) == 1
        assert suppression_calls[0][0][1]["file"] == file_path

    def test_mute_writes_suppression_log(self, tmp_path: Path) -> None:
        """Branch mute suppression writes reason='branch_muted' via _append_jsonl."""
        _setup_happy_path()
        config_file = tmp_path / "trigger_config.json"
        config_file.write_text(
            json.dumps({"config": {"muted_branches": ["flow"]}}),
            encoding="utf-8",
        )

        mod.handle_runaway_log_detected(
            file_path="/var/log/test.log",
            branch="flow",
            rate_lines_per_min=500,
            sustained_duration_sec=60,
        )

        calls = mod._append_jsonl.call_args_list  # type: ignore[union-attr]
        suppression_calls = [c for c in calls if isinstance(c[0][1], dict) and c[0][1].get("reason") == "branch_muted"]
        assert len(suppression_calls) == 1
        assert suppression_calls[0][0][1]["branch"] == "flow"


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
