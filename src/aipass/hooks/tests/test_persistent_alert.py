# =================== AIPass ====================
# Name: test_persistent_alert.py
# Version: 1.1.0
# Description: Tests for persistent_alert handler and alert_dismiss module (cadence-gated since 1.1.0)
# Branch: hooks
# Created: 2026-07-14
# Modified: 2026-09-15
# =============================================

"""Tests for handlers/prompt/persistent_alert.py and modules/alert_dismiss.py.

A banner announces on arrival and then repeats only on the cadence beat, so the
gate is held open for every test here and TestAlertCadence pins the gate itself.
The announce guards are redirected into tmp for the same reason: they are keyed
by the LIVE session id, so on a real seat the suite read guard files written by
the session running it.
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

_MODULE = "aipass.hooks.apps.handlers.prompt.persistent_alert"
_CADENCE_MODULE = "aipass.hooks.apps.modules.cadence"


@pytest.fixture(autouse=True)
def _isolated_guards_and_open_beat(tmp_path, monkeypatch):
    """Per-test announce guards, and the repeat beat held open."""
    guards = tmp_path / "alert-guards"
    guards.mkdir()
    monkeypatch.setattr(f"{_MODULE}._GUARD_DIR", guards)
    monkeypatch.setattr(f"{_CADENCE_MODULE}.should_fire", lambda *_a, **_k: True)


def _make_alert(
    alert_id="test-001",
    source="prax",
    severity="warning",
    title="Test alert",
    body="Something happened",
    expires_at=None,
):
    alert = {
        "id": alert_id,
        "source": source,
        "severity": severity,
        "title": title,
        "body": body,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "expires_at": expires_at,
    }
    return alert


def _write_alerts(aipass_dir: Path, alerts: list[dict]):
    alerts_path = aipass_dir / "alerts.json"
    alerts_path.write_text(
        json.dumps({"alerts": alerts}, indent=2) + "\n",
        encoding="utf-8",
    )


class TestPersistentAlertHandler:
    """Banner injection behavior."""

    def test_banner_injected_when_alerts_exist(self, tmp_path):
        from aipass.hooks.apps.handlers.prompt.persistent_alert import handle

        aipass_dir = tmp_path / ".aipass"
        aipass_dir.mkdir()
        _write_alerts(aipass_dir, [_make_alert()])

        with patch(
            "aipass.hooks.apps.handlers.prompt.persistent_alert._find_aipass_dir",
            return_value=aipass_dir,
        ):
            result = handle({})

        assert result["exit_code"] == 0
        assert "# Active Alerts" in result["stdout"]
        assert "[WARNING] Test alert" in result["stdout"]
        assert "drone @hooks dismiss" in result["stdout"]

    def test_no_banner_when_no_alerts_file(self, tmp_path):
        from aipass.hooks.apps.handlers.prompt.persistent_alert import handle

        aipass_dir = tmp_path / ".aipass"
        aipass_dir.mkdir()

        with patch(
            "aipass.hooks.apps.handlers.prompt.persistent_alert._find_aipass_dir",
            return_value=aipass_dir,
        ):
            result = handle({})

        assert result["stdout"] == ""
        assert result["exit_code"] == 0

    def test_no_banner_when_empty_alerts(self, tmp_path):
        from aipass.hooks.apps.handlers.prompt.persistent_alert import handle

        aipass_dir = tmp_path / ".aipass"
        aipass_dir.mkdir()
        _write_alerts(aipass_dir, [])

        with patch(
            "aipass.hooks.apps.handlers.prompt.persistent_alert._find_aipass_dir",
            return_value=aipass_dir,
        ):
            result = handle({})

        assert result["stdout"] == ""

    def test_no_banner_when_no_aipass_dir(self):
        from aipass.hooks.apps.handlers.prompt.persistent_alert import handle

        with patch(
            "aipass.hooks.apps.handlers.prompt.persistent_alert._find_aipass_dir",
            return_value=None,
        ):
            result = handle({})

        assert result["stdout"] == ""
        assert result["exit_code"] == 0

    def test_multiple_alerts_all_shown(self, tmp_path):
        from aipass.hooks.apps.handlers.prompt.persistent_alert import handle

        aipass_dir = tmp_path / ".aipass"
        aipass_dir.mkdir()
        _write_alerts(
            aipass_dir,
            [
                _make_alert(alert_id="a1", title="First"),
                _make_alert(alert_id="a2", title="Second", severity="critical"),
            ],
        )

        with patch(
            "aipass.hooks.apps.handlers.prompt.persistent_alert._find_aipass_dir",
            return_value=aipass_dir,
        ):
            result = handle({})

        assert "[WARNING] First" in result["stdout"]
        assert "[CRITICAL] Second" in result["stdout"]

    def test_source_and_id_in_banner(self, tmp_path):
        from aipass.hooks.apps.handlers.prompt.persistent_alert import handle

        aipass_dir = tmp_path / ".aipass"
        aipass_dir.mkdir()
        _write_alerts(aipass_dir, [_make_alert(alert_id="abc-123", source="trigger")])

        with patch(
            "aipass.hooks.apps.handlers.prompt.persistent_alert._find_aipass_dir",
            return_value=aipass_dir,
        ):
            result = handle({})

        assert "@trigger" in result["stdout"]
        assert "abc-123" in result["stdout"]

    def test_body_included_in_banner(self, tmp_path):
        from aipass.hooks.apps.handlers.prompt.persistent_alert import handle

        aipass_dir = tmp_path / ".aipass"
        aipass_dir.mkdir()
        _write_alerts(aipass_dir, [_make_alert(body="Log rate exceeds 50/s")])

        with patch(
            "aipass.hooks.apps.handlers.prompt.persistent_alert._find_aipass_dir",
            return_value=aipass_dir,
        ):
            result = handle({})

        assert "Log rate exceeds 50/s" in result["stdout"]

    def test_no_body_line_when_body_empty(self, tmp_path):
        from aipass.hooks.apps.handlers.prompt.persistent_alert import handle

        aipass_dir = tmp_path / ".aipass"
        aipass_dir.mkdir()
        _write_alerts(aipass_dir, [_make_alert(body="")])

        with patch(
            "aipass.hooks.apps.handlers.prompt.persistent_alert._find_aipass_dir",
            return_value=aipass_dir,
        ):
            result = handle({})

        lines = result["stdout"].split("\n")
        body_lines = [line for line in lines if line.startswith("  ")]
        assert len(body_lines) == 0


class TestExpiredAlertCleanup:
    """Auto-cleaning of expired alerts."""

    def test_expired_alerts_removed(self, tmp_path):
        from aipass.hooks.apps.handlers.prompt.persistent_alert import handle

        aipass_dir = tmp_path / ".aipass"
        aipass_dir.mkdir()
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        _write_alerts(
            aipass_dir,
            [
                _make_alert(alert_id="expired", expires_at=past),
                _make_alert(alert_id="active", expires_at=None),
            ],
        )

        with patch(
            "aipass.hooks.apps.handlers.prompt.persistent_alert._find_aipass_dir",
            return_value=aipass_dir,
        ):
            result = handle({})

        assert "active" in result["stdout"]
        assert "expired" not in result["stdout"]

        saved = json.loads((aipass_dir / "alerts.json").read_text())
        assert len(saved["alerts"]) == 1
        assert saved["alerts"][0]["id"] == "active"

    def test_all_expired_returns_empty(self, tmp_path):
        from aipass.hooks.apps.handlers.prompt.persistent_alert import handle

        aipass_dir = tmp_path / ".aipass"
        aipass_dir.mkdir()
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        _write_alerts(aipass_dir, [_make_alert(expires_at=past)])

        with patch(
            "aipass.hooks.apps.handlers.prompt.persistent_alert._find_aipass_dir",
            return_value=aipass_dir,
        ):
            result = handle({})

        assert result["stdout"] == ""

    def test_future_expiry_kept(self, tmp_path):
        from aipass.hooks.apps.handlers.prompt.persistent_alert import handle

        aipass_dir = tmp_path / ".aipass"
        aipass_dir.mkdir()
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        _write_alerts(aipass_dir, [_make_alert(alert_id="still-valid", expires_at=future)])

        with patch(
            "aipass.hooks.apps.handlers.prompt.persistent_alert._find_aipass_dir",
            return_value=aipass_dir,
        ):
            result = handle({})

        assert "still-valid" in result["stdout"]

    def test_corrupt_json_returns_empty(self, tmp_path):
        from aipass.hooks.apps.handlers.prompt.persistent_alert import handle

        aipass_dir = tmp_path / ".aipass"
        aipass_dir.mkdir()
        (aipass_dir / "alerts.json").write_text("{bad json", encoding="utf-8")

        with patch(
            "aipass.hooks.apps.handlers.prompt.persistent_alert._find_aipass_dir",
            return_value=aipass_dir,
        ):
            result = handle({})

        assert result["stdout"] == ""
        assert result["exit_code"] == 0


class TestAlertSound:
    """Sound fires once per alert per session (session-keyed tempdir guard)."""

    def test_sound_on_first_injection(self, tmp_path):
        from aipass.hooks.apps.handlers.prompt import persistent_alert

        aipass_dir = tmp_path / ".aipass"
        aipass_dir.mkdir()
        _write_alerts(aipass_dir, [_make_alert(alert_id="snd-001")])

        with (
            patch.object(persistent_alert, "_find_aipass_dir", return_value=aipass_dir),
            patch.object(persistent_alert, "_GUARD_DIR", tmp_path),
        ):
            result = persistent_alert.handle({"session_id": "s-snd-001"})

        assert "sound" in result
        assert "1 active alert" in result["sound"]

    def test_no_sound_on_repeat_injection(self, tmp_path):
        from aipass.hooks.apps.handlers.prompt import persistent_alert

        aipass_dir = tmp_path / ".aipass"
        aipass_dir.mkdir()
        _write_alerts(aipass_dir, [_make_alert(alert_id="snd-002")])

        with (
            patch.object(persistent_alert, "_find_aipass_dir", return_value=aipass_dir),
            patch.object(persistent_alert, "_GUARD_DIR", tmp_path),
        ):
            persistent_alert.handle({"session_id": "s-snd-002"})
            result = persistent_alert.handle({"session_id": "s-snd-002"})

        assert "sound" not in result

    def test_fresh_process_same_session_still_dedupes(self, tmp_path):
        """Regression: module-global set used to reset every process (real bridge calls
        are fresh processes each time) so sound fired on every prompt. Guard file persists
        across separate handle() calls even after re-importing the module fresh."""
        import importlib

        from aipass.hooks.apps.handlers.prompt import persistent_alert

        aipass_dir = tmp_path / ".aipass"
        aipass_dir.mkdir()
        _write_alerts(aipass_dir, [_make_alert(alert_id="snd-fresh")])

        with (
            patch.object(persistent_alert, "_find_aipass_dir", return_value=aipass_dir),
            patch.object(persistent_alert, "_GUARD_DIR", tmp_path),
        ):
            persistent_alert.handle({"session_id": "s-fresh"})

        fresh_module = importlib.reload(persistent_alert)
        with (
            patch.object(fresh_module, "_find_aipass_dir", return_value=aipass_dir),
            patch.object(fresh_module, "_GUARD_DIR", tmp_path),
        ):
            result = fresh_module.handle({"session_id": "s-fresh"})

        assert "sound" not in result
        importlib.reload(persistent_alert)

    def test_sound_on_new_alert_added(self, tmp_path):
        from aipass.hooks.apps.handlers.prompt import persistent_alert

        aipass_dir = tmp_path / ".aipass"
        aipass_dir.mkdir()
        _write_alerts(aipass_dir, [_make_alert(alert_id="snd-003")])

        with (
            patch.object(persistent_alert, "_find_aipass_dir", return_value=aipass_dir),
            patch.object(persistent_alert, "_GUARD_DIR", tmp_path),
        ):
            persistent_alert.handle({"session_id": "s-snd-003"})

        _write_alerts(
            aipass_dir,
            [
                _make_alert(alert_id="snd-003"),
                _make_alert(alert_id="snd-004"),
            ],
        )

        with (
            patch.object(persistent_alert, "_find_aipass_dir", return_value=aipass_dir),
            patch.object(persistent_alert, "_GUARD_DIR", tmp_path),
        ):
            result = persistent_alert.handle({"session_id": "s-snd-003"})

        assert "sound" in result
        assert "2 active alerts" in result["sound"]

    def test_different_sessions_both_hear_sound(self, tmp_path):
        from aipass.hooks.apps.handlers.prompt import persistent_alert

        aipass_dir = tmp_path / ".aipass"
        aipass_dir.mkdir()
        _write_alerts(aipass_dir, [_make_alert(alert_id="snd-indep")])

        with (
            patch.object(persistent_alert, "_find_aipass_dir", return_value=aipass_dir),
            patch.object(persistent_alert, "_GUARD_DIR", tmp_path),
        ):
            first = persistent_alert.handle({"session_id": "s-a"})
            second = persistent_alert.handle({"session_id": "s-b"})

        assert "sound" in first
        assert "sound" in second

    def test_no_sound_when_no_alerts(self, tmp_path):
        from aipass.hooks.apps.handlers.prompt import persistent_alert

        aipass_dir = tmp_path / ".aipass"
        aipass_dir.mkdir()
        _write_alerts(aipass_dir, [])

        with (
            patch.object(persistent_alert, "_find_aipass_dir", return_value=aipass_dir),
            patch.object(persistent_alert, "_GUARD_DIR", tmp_path),
        ):
            result = persistent_alert.handle({"session_id": "s-none"})

        assert "sound" not in result


class TestAlertBannerCap:
    """Banner truncates at _MAX_ALERTS_SHOWN with a hidden-count note."""

    def test_cap_truncates_and_notes_hidden_count(self, tmp_path):
        from aipass.hooks.apps.handlers.prompt import persistent_alert

        aipass_dir = tmp_path / ".aipass"
        aipass_dir.mkdir()
        alerts = [_make_alert(alert_id=f"cap-{i}", title=f"Alert {i}") for i in range(13)]
        _write_alerts(aipass_dir, alerts)

        with (
            patch.object(persistent_alert, "_find_aipass_dir", return_value=aipass_dir),
            patch.object(persistent_alert, "_GUARD_DIR", tmp_path),
        ):
            result = persistent_alert.handle({"session_id": "s-cap"})

        assert "Alert 0" in result["stdout"]
        assert "Alert 9" in result["stdout"]
        assert "Alert 10" not in result["stdout"]
        assert "...and 3 more" in result["stdout"]

    def test_under_cap_no_hidden_note(self, tmp_path):
        from aipass.hooks.apps.handlers.prompt import persistent_alert

        aipass_dir = tmp_path / ".aipass"
        aipass_dir.mkdir()
        _write_alerts(aipass_dir, [_make_alert(alert_id="under-cap")])

        with (
            patch.object(persistent_alert, "_find_aipass_dir", return_value=aipass_dir),
            patch.object(persistent_alert, "_GUARD_DIR", tmp_path),
        ):
            result = persistent_alert.handle({"session_id": "s-under-cap"})

        assert "more (dismiss some" not in result["stdout"]


class TestAlertBodyCap:
    """DPLAN-0347 row 3: a body is cut at 300 chars, and the cut says where the full text lives."""

    def _banner(self, tmp_path, body):
        from aipass.hooks.apps.handlers.prompt import persistent_alert

        aipass_dir = tmp_path / ".aipass"
        aipass_dir.mkdir()
        _write_alerts(aipass_dir, [_make_alert(alert_id="body-cap", body=body)])
        with patch.object(persistent_alert, "_find_aipass_dir", return_value=aipass_dir):
            return persistent_alert.handle({"session_id": "s-body"})["stdout"]

    def test_a_long_body_is_cut_and_points_at_the_full_text(self, tmp_path):
        banner = self._banner(tmp_path, "b" * 900)
        body_line = next(line for line in banner.splitlines() if line.startswith("  b"))
        assert len(body_line.strip()) == 300, body_line
        assert "drone @hooks alerts" in body_line

    def test_a_body_at_the_cap_is_untouched(self, tmp_path):
        """The cap is a ceiling, not a target: 300 chars renders whole, marker included nowhere."""
        banner = self._banner(tmp_path, "b" * 300)
        assert "b" * 300 in banner
        assert "cut at 300 chars" not in banner


class TestAlertCadence:
    """DPLAN-0347 row 3: announce on arrival, then only on the beat.

    The old guard file silenced the SOUND alone — the banner itself re-injected
    in full on every turn for as long as the alert stayed active, up to ten
    alerts with uncapped bodies. Arrival stays ungated: a notification that waits
    four turns for a beat is not a notification.
    """

    def _seat(self, tmp_path, alert_id="beat-1"):
        aipass_dir = tmp_path / ".aipass"
        aipass_dir.mkdir()
        _write_alerts(aipass_dir, [_make_alert(alert_id=alert_id)])
        return aipass_dir

    def test_arrival_announces_even_when_the_beat_says_skip(self, tmp_path, monkeypatch):
        from aipass.hooks.apps.handlers.prompt import persistent_alert

        aipass_dir = self._seat(tmp_path)
        monkeypatch.setattr(f"{_CADENCE_MODULE}.should_fire", lambda *_a, **_k: False)
        with patch.object(persistent_alert, "_find_aipass_dir", return_value=aipass_dir):
            result = persistent_alert.handle({"session_id": "s-arrival"})

        assert "Test alert" in result["stdout"]
        assert "sound" in result

    def test_an_announced_alert_is_held_until_the_beat(self, tmp_path, monkeypatch):
        from aipass.hooks.apps.handlers.prompt import persistent_alert

        aipass_dir = self._seat(tmp_path, alert_id="beat-2")
        seen: list[str] = []

        def _skip(loader_name, _hook_data=None):
            seen.append(loader_name)
            return False

        with patch.object(persistent_alert, "_find_aipass_dir", return_value=aipass_dir):
            persistent_alert.handle({"session_id": "s-held"})
            monkeypatch.setattr(f"{_CADENCE_MODULE}.should_fire", _skip)
            result = persistent_alert.handle({"session_id": "s-held"})

        assert seen == ["alert"]
        assert result == {"stdout": "", "exit_code": 0}

    def test_the_beat_re_injects_the_standing_alert(self, tmp_path):
        from aipass.hooks.apps.handlers.prompt import persistent_alert

        aipass_dir = self._seat(tmp_path, alert_id="beat-3")
        with patch.object(persistent_alert, "_find_aipass_dir", return_value=aipass_dir):
            persistent_alert.handle({"session_id": "s-beat"})
            result = persistent_alert.handle({"session_id": "s-beat"})

        assert "Test alert" in result["stdout"], "a standing alert still reminds, on the beat"
        assert "sound" not in result, "the sound stays a first-sighting signal"

    def test_a_cadence_failure_keeps_the_banner_and_warns(self, tmp_path, monkeypatch, caplog):
        """Fail-open, loudly: an alert nobody sees is worse than one seen too often."""
        from aipass.hooks.apps.handlers.prompt import persistent_alert

        aipass_dir = self._seat(tmp_path, alert_id="beat-4")

        def _boom(*_args, **_kwargs):
            raise RuntimeError("no cadence state")

        with patch.object(persistent_alert, "_find_aipass_dir", return_value=aipass_dir):
            persistent_alert.handle({"session_id": "s-fail"})
            monkeypatch.setattr(f"{_CADENCE_MODULE}.should_fire", _boom)
            result = persistent_alert.handle({"session_id": "s-fail"})

        assert "Test alert" in result["stdout"]
        assert "FAIL-OPEN loader=alert" in caplog.text


class TestAlertDismiss:
    """drone @hooks dismiss behavior."""

    def test_dismiss_removes_by_id(self, tmp_path):
        from aipass.hooks.apps.modules.alert_dismiss import _dismiss_alert

        aipass_dir = tmp_path / ".aipass"
        aipass_dir.mkdir()
        _write_alerts(
            aipass_dir,
            [
                _make_alert(alert_id="keep"),
                _make_alert(alert_id="remove"),
            ],
        )

        with patch(
            "aipass.hooks.apps.modules.alert_dismiss._find_aipass_dir",
            return_value=aipass_dir,
        ):
            result = _dismiss_alert("remove")

        assert result is True
        saved = json.loads((aipass_dir / "alerts.json").read_text())
        assert len(saved["alerts"]) == 1
        assert saved["alerts"][0]["id"] == "keep"

    def test_dismiss_nonexistent_returns_false(self, tmp_path):
        from aipass.hooks.apps.modules.alert_dismiss import _dismiss_alert

        aipass_dir = tmp_path / ".aipass"
        aipass_dir.mkdir()
        _write_alerts(aipass_dir, [_make_alert(alert_id="exists")])

        with patch(
            "aipass.hooks.apps.modules.alert_dismiss._find_aipass_dir",
            return_value=aipass_dir,
        ):
            result = _dismiss_alert("nope")

        assert result is False

    def test_dismiss_no_alerts_file(self, tmp_path):
        from aipass.hooks.apps.modules.alert_dismiss import _dismiss_alert

        aipass_dir = tmp_path / ".aipass"
        aipass_dir.mkdir()

        with patch(
            "aipass.hooks.apps.modules.alert_dismiss._find_aipass_dir",
            return_value=aipass_dir,
        ):
            result = _dismiss_alert("any")

        assert result is False

    def test_dismiss_no_aipass_dir(self):
        from aipass.hooks.apps.modules.alert_dismiss import _dismiss_alert

        with patch(
            "aipass.hooks.apps.modules.alert_dismiss._find_aipass_dir",
            return_value=None,
        ):
            result = _dismiss_alert("any")

        assert result is False

    def test_handle_command_routes_dismiss(self, tmp_path):
        from aipass.hooks.apps.modules.alert_dismiss import handle_command

        aipass_dir = tmp_path / ".aipass"
        aipass_dir.mkdir()
        _write_alerts(aipass_dir, [_make_alert(alert_id="cmd-test")])

        with patch(
            "aipass.hooks.apps.modules.alert_dismiss._find_aipass_dir",
            return_value=aipass_dir,
        ):
            result = handle_command("dismiss", ["cmd-test"])

        assert result is True
        saved = json.loads((aipass_dir / "alerts.json").read_text())
        assert len(saved["alerts"]) == 0

    def test_handle_command_ignores_other_commands(self):
        from aipass.hooks.apps.modules.alert_dismiss import handle_command

        assert handle_command("status", []) is False

    def test_handle_command_help(self):
        from aipass.hooks.apps.modules.alert_dismiss import handle_command

        assert handle_command("dismiss", ["--help"]) is True
