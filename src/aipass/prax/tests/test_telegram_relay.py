# =================== AIPass ====================
# Name: test_telegram_relay.py
# Description: Tests for the Telegram relay handler
# Version: 1.3.0
# Created: 2026-06-24
# Modified: 2026-10-17
# =============================================

"""Tests for apps/handlers/monitoring/telegram_relay.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(stdlib) — _flush_loop, a threading.Event.wait timer around the tested _flush_buffer
# seedgo: no-test-needed(json_structure) — init_relay's and stop_relay's log_operation records, covered by that row

import json
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest

from aipass.prax.apps.handlers.monitoring import telegram_relay
from aipass.prax.apps.modules import monitor


def _operator_control_file() -> Path:
    """The real operator's control file on this machine, the one no test may ever touch.

    Resolved when a test asks, never at import, so an unresolvable home fails only those tests."""
    return Path.home() / ".aipass" / "telegram_bots" / "prax_monitor_control.json"


@dataclass
class FakeEvent:
    """Minimal MonitoringEvent stand-in for tests."""

    priority: int = 3
    timestamp: datetime = field(default_factory=datetime.now)
    event_type: str = ""
    branch: str = ""
    action: str = ""
    message: str = ""
    level: str = "info"
    caller: Optional[str] = None
    pid: Optional[int] = None


# CONTROL_FILE defaults to the operator's LIVE pause state, and a paused flush discards
# the buffer, so every test re-points it; _import_relay refuses one aimed at home.


@pytest.fixture(autouse=True)
def isolate_control_file(tmp_path, monkeypatch):
    """A relay aimed at a throwaway control file, its state as a fresh import leaves it.

    Every name is set through monkeypatch, so the next test, and every other file
    in the session, gets the module back as it found it.
    """
    lock = MagicMock()
    lock.try_acquire = MagicMock(return_value=True)
    monkeypatch.setattr(telegram_relay, "CONTROL_FILE", tmp_path / "relay_control.json")
    monkeypatch.setattr(telegram_relay, "instance_lock", lock)
    monkeypatch.setattr(telegram_relay, "logger", MagicMock())
    monkeypatch.setattr(telegram_relay, "json_handler", MagicMock())
    monkeypatch.setattr(telegram_relay, "_buffer", [])
    monkeypatch.setattr(telegram_relay, "_stop_event", threading.Event())
    monkeypatch.setattr(telegram_relay, "_thread", None)
    monkeypatch.setattr(telegram_relay, "_bot_token", None)
    monkeypatch.setattr(telegram_relay, "_chat_id", None)
    monkeypatch.setattr(telegram_relay, "_RELAY_ACTIVE", False)
    monkeypatch.setattr(telegram_relay, "_control_mtime", 0.0)
    monkeypatch.setattr(telegram_relay, "_control_cache", {})
    monkeypatch.setattr(telegram_relay, "_OFFLINE", False)
    monkeypatch.setattr(telegram_relay, "_CURRENT_BACKOFF", telegram_relay._BACKOFF_INITIAL)
    monkeypatch.setattr(telegram_relay, "_NEXT_RETRY", 0.0)
    monkeypatch.setattr(telegram_relay, "_OFFLINE_SINCE", 0.0)
    monkeypatch.setattr(telegram_relay, "_SUPPRESSED_COUNT", 0)
    monkeypatch.setattr(telegram_relay, "_LAST_SUMMARY", 0.0)


def _import_relay():
    """The relay the fixture isolated; refuses one still aimed at the operator's file."""
    if telegram_relay.CONTROL_FILE == _operator_control_file():
        raise RuntimeError(
            "_import_relay() called outside the isolate_control_file fixture — "
            "the relay would read the operator's live control file"
        )
    return telegram_relay


def _log(relay) -> MagicMock:
    """The logger recorder the fixture put where the relay binds its logger."""
    assert isinstance(relay.logger, MagicMock), "the relay is logging for real"
    return relay.logger


def _formatted(relay, event) -> str:
    """The line _format_event makes; None (an event it drops) fails here, by name."""
    line = relay._format_event(event)
    assert line is not None, f"_format_event dropped {event!r}"
    return line


class TestFormatEvent:
    """Test _format_event produces correct plain-text lines."""

    def test_log_event_basic(self):
        """Log event includes uppercased branch and message."""
        relay = _import_relay()
        event = FakeEvent(event_type="log", branch="seedgo", message="Audit started")
        result = _formatted(relay, event)
        assert "[SEEDGO]" in result
        assert "Audit started" in result

    def test_log_event_with_pid(self):
        """Log event with PID shows BRANCH:PID label."""
        relay = _import_relay()
        event = FakeEvent(event_type="log", branch="devpulse", message="Working", pid=12345)
        result = _formatted(relay, event)
        assert "[DEVPULSE:12345]" in result

    def test_command_event(self):
        """Command event shows arrow prefix."""
        relay = _import_relay()
        event = FakeEvent(event_type="command", branch="drone", message="seedgo audit", action="")
        result = _formatted(relay, event)
        assert "▶ seedgo audit" in result

    def test_command_event_with_caller_and_target(self):
        """Command event with caller and target shows attribution line."""
        relay = _import_relay()
        event = FakeEvent(
            event_type="command",
            branch="drone",
            message="seedgo audit",
            action="run:prax",
            caller="devpulse",
        )
        result = _formatted(relay, event)
        assert "devpulse → prax" in result
        assert "▶ seedgo audit" in result

    def test_command_event_unknown_caller_omitted(self):
        """Command event with UNKNOWN caller omits caller line."""
        relay = _import_relay()
        event = FakeEvent(
            event_type="command",
            branch="drone",
            message="test",
            caller="UNKNOWN",
        )
        result = _formatted(relay, event)
        assert "UNKNOWN" not in result

    def test_hook_event_fired(self):
        """Fired hook event uses lightning bolt symbol."""
        relay = _import_relay()
        event = FakeEvent(event_type="hook", branch="hooks", message="cadence:fired", action="fired")
        result = _formatted(relay, event)
        assert result == "⚡ HOOK cadence:fired"

    def test_hook_event_skipped(self):
        """Skipped hook event uses dot symbol."""
        relay = _import_relay()
        event = FakeEvent(event_type="hook", branch="hooks", message="cadence:skipped", action="skipped")
        result = _formatted(relay, event)
        assert result == "· HOOK cadence:skipped"

    def test_hook_event_unknown_action(self):
        """Unknown hook action uses question mark symbol."""
        relay = _import_relay()
        event = FakeEvent(event_type="hook", branch="hooks", message="something", action="other")
        result = _formatted(relay, event)
        assert result.startswith("? HOOK")

    def test_file_event(self):
        """File event formats like a log event with branch and message."""
        relay = _import_relay()
        event = FakeEvent(event_type="file", branch="prax", message="monitor.py modified")
        result = _formatted(relay, event)
        assert "[PRAX]" in result
        assert "monitor.py modified" in result


class TestInitRelay:
    """Test init_relay activation and fail-silent behavior."""

    def test_disabled_is_noop(self):
        """Disabled flag skips all initialization."""
        relay = _import_relay()
        relay.init_relay(enabled=False)
        assert relay._RELAY_ACTIVE is False
        assert relay._thread is None

    def test_no_config_stays_inactive(self):
        """None config keeps relay inactive."""
        relay = _import_relay()
        relay.init_relay(enabled=True, config=None)
        assert relay._RELAY_ACTIVE is False

    def test_no_config_logs_exactly_once(self):
        """Missing config produces exactly one info log, not per-cycle spam."""
        relay = _import_relay()
        relay.init_relay(enabled=True, config=None)
        calls = [c for c in _log(relay).info.call_args_list if "inactive" in str(c)]
        assert len(calls) == 1

    def test_incomplete_config_missing_chat_id(self):
        """Config without chat_id stays inactive."""
        relay = _import_relay()
        relay.init_relay(enabled=True, config={"bot_token": "tok123"})
        assert relay._RELAY_ACTIVE is False

    def test_incomplete_config_missing_token(self):
        """Config without bot_token stays inactive."""
        relay = _import_relay()
        relay.init_relay(enabled=True, config={"chat_id": 123})
        assert relay._RELAY_ACTIVE is False

    def test_valid_config_activates(self):
        """Valid config sets active flag and stores credentials."""
        relay = _import_relay()
        relay.init_relay(enabled=True, config={"bot_token": "tok123", "chat_id": 456})
        assert relay._RELAY_ACTIVE is True
        assert relay._bot_token == "tok123"
        assert relay._chat_id == 456
        assert relay._thread is not None
        relay.stop_relay()

    def test_valid_config_starts_daemon_thread(self):
        """Valid config starts a named daemon thread."""
        relay = _import_relay()
        relay.init_relay(enabled=True, config={"bot_token": "t", "chat_id": 1})
        thread = relay._thread
        assert thread is not None
        assert thread.daemon is True
        assert thread.name == "telegram-relay"
        relay.stop_relay()


class TestRelayEvent:
    """Test relay_event buffering."""

    def test_noop_when_inactive(self):
        """Inactive relay does not buffer events."""
        relay = _import_relay()
        event = FakeEvent(event_type="log", branch="test", message="hello")
        relay.relay_event(event)
        assert len(relay._buffer) == 0

    def test_buffers_when_active(self):
        """Active relay appends formatted line to buffer."""
        relay = _import_relay()
        setattr(relay, "_RELAY_ACTIVE", True)
        event = FakeEvent(event_type="log", branch="test", message="hello")
        relay.relay_event(event)
        assert len(relay._buffer) == 1
        assert "hello" in relay._buffer[0]


class TestStopRelay:
    """Test stop_relay cleanup."""

    def test_noop_when_inactive(self):
        """Stopping an inactive relay is a safe no-op."""
        relay = _import_relay()
        relay.stop_relay()
        assert relay._RELAY_ACTIVE is False

    def test_flushes_and_joins(self):
        """Stopping an active relay clears state and joins thread."""
        relay = _import_relay()
        relay.init_relay(enabled=True, config={"bot_token": "t", "chat_id": 1})
        assert relay._RELAY_ACTIVE is True
        relay.stop_relay()
        assert relay._RELAY_ACTIVE is False
        assert relay._thread is None


class TestBatching:
    """Test _send_batched 4000-char splitting."""

    def test_single_message_under_limit(self, monkeypatch):
        """Short content sends as one message."""
        relay = _import_relay()
        sent = []
        monkeypatch.setattr(relay, "_send_message", lambda text: sent.append(text) or True)
        relay._send_batched(["short line"])
        assert len(sent) == 1
        assert sent[0] == "short line"

    def test_splits_at_4000_chars(self, monkeypatch):
        """Lines exceeding 4000 chars are split across multiple messages."""
        relay = _import_relay()
        sent = []
        monkeypatch.setattr(relay, "_send_message", lambda text: sent.append(text) or True)
        lines = [f"line-{i:04d}-" + "x" * 90 for i in range(50)]
        relay._send_batched(lines)
        assert len(sent) > 1
        for msg in sent:
            assert len(msg) <= relay.TELEGRAM_MAX_LENGTH + 200

    def test_empty_lines_sends_nothing(self, monkeypatch):
        """Empty list sends no messages."""
        relay = _import_relay()
        sent = []
        monkeypatch.setattr(relay, "_send_message", lambda text: sent.append(text) or True)
        relay._send_batched([])
        assert len(sent) == 0


class TestFloodCap:
    """Test flood cap truncation."""

    def test_under_cap_sends_all(self, monkeypatch):
        """Lines under FLOOD_CAP are all delivered."""
        relay = _import_relay()
        setattr(relay, "_bot_token", "t")
        setattr(relay, "_chat_id", 1)
        sent = []
        monkeypatch.setattr(relay, "_send_batched", lambda lines: sent.extend(lines))
        relay._buffer.extend([f"line {i}" for i in range(100)])
        setattr(relay, "_RELAY_ACTIVE", True)
        relay._flush_buffer()
        assert len(sent) == 100

    def test_over_cap_truncates_with_notice(self, monkeypatch):
        """Lines over FLOOD_CAP are truncated with a suppression notice."""
        relay = _import_relay()
        setattr(relay, "_bot_token", "t")
        setattr(relay, "_chat_id", 1)
        sent_lines = []
        monkeypatch.setattr(relay, "_send_batched", lambda lines: sent_lines.extend(lines))
        relay._buffer.extend([f"line {i}" for i in range(200)])
        setattr(relay, "_RELAY_ACTIVE", True)
        relay._flush_buffer()
        assert len(sent_lines) == relay.FLOOD_CAP + 1
        assert "50 more suppressed" in sent_lines[-1]


class TestRenderEventCallsRelay:
    """Test that monitor._render_event calls relay_event."""

    def test_render_event_calls_relay(self, monkeypatch):
        """_render_event hands the event to the relay, then to the console.

        monitor is imported once at the top; both sinks are doubled where monitor
        binds them, so no reload and no stubbed package (prax, leg 10).
        """
        sinks: list[tuple[str, object]] = []
        monkeypatch.setattr(monitor, "relay_event", lambda e: sinks.append(("relay", e)))
        monkeypatch.setattr(monitor, "_print_event_to_console", lambda e: sinks.append(("console", e)))

        event = MagicMock()
        monitor._render_event(event)

        assert sinks == [("relay", event), ("console", event)]


class TestRelayEnabledByEnv:
    """Test environment variable detection."""

    def test_not_set(self):
        """Unset env var returns False."""
        relay = _import_relay()
        with patch.dict("os.environ", {}, clear=True):
            assert relay.is_relay_enabled_by_env() is False

    def test_set_to_1(self):
        """AIPASS_PRAX_MONITOR_RELAY=1 returns True."""
        relay = _import_relay()
        with patch.dict("os.environ", {"AIPASS_PRAX_MONITOR_RELAY": "1"}):
            assert relay.is_relay_enabled_by_env() is True

    def test_set_to_true(self):
        """AIPASS_PRAX_MONITOR_RELAY=true returns True."""
        relay = _import_relay()
        with patch.dict("os.environ", {"AIPASS_PRAX_MONITOR_RELAY": "true"}):
            assert relay.is_relay_enabled_by_env() is True

    def test_set_to_yes(self):
        """AIPASS_PRAX_MONITOR_RELAY=yes returns True."""
        relay = _import_relay()
        with patch.dict("os.environ", {"AIPASS_PRAX_MONITOR_RELAY": "yes"}):
            assert relay.is_relay_enabled_by_env() is True

    def test_set_to_0(self):
        """AIPASS_PRAX_MONITOR_RELAY=0 returns False."""
        relay = _import_relay()
        with patch.dict("os.environ", {"AIPASS_PRAX_MONITOR_RELAY": "0"}):
            assert relay.is_relay_enabled_by_env() is False


class TestReadControl:
    """Test _read_control reads, caches, and handles errors."""

    def test_missing_file_returns_empty(self, tmp_path):
        """Missing control file returns empty dict (defaults)."""
        relay = _import_relay()
        setattr(relay, "CONTROL_FILE", tmp_path / "nonexistent.json")
        assert relay._read_control() == {}

    def test_valid_file_returns_content(self, tmp_path):
        """Valid JSON control file is read and returned."""
        relay = _import_relay()
        ctrl = tmp_path / "control.json"
        ctrl.write_text(json.dumps({"paused": True, "level": "errors"}), encoding="utf-8")
        setattr(relay, "CONTROL_FILE", ctrl)
        result = relay._read_control()
        assert result["paused"] is True
        assert result["level"] == "errors"

    def test_mtime_cache_avoids_reread(self, tmp_path):
        """Same mtime returns cached result without re-reading the file."""
        relay = _import_relay()
        ctrl = tmp_path / "control.json"
        ctrl.write_text(json.dumps({"paused": False}), encoding="utf-8")
        setattr(relay, "CONTROL_FILE", ctrl)
        first = relay._read_control()
        cached_mtime = ctrl.stat().st_mtime
        ctrl.write_text("INVALID JSON", encoding="utf-8")
        os.utime(ctrl, (cached_mtime, cached_mtime))
        result = relay._read_control()
        assert result == first

    def test_mtime_change_triggers_reread(self, tmp_path):
        """Changed mtime causes re-read of the control file."""
        relay = _import_relay()
        ctrl = tmp_path / "control.json"
        ctrl.write_text(json.dumps({"paused": False, "level": "all"}), encoding="utf-8")
        setattr(relay, "CONTROL_FILE", ctrl)
        relay._read_control()
        ctrl.write_text(json.dumps({"paused": True, "level": "errors"}), encoding="utf-8")
        os.utime(ctrl, (ctrl.stat().st_mtime + 1, ctrl.stat().st_mtime + 1))
        result = relay._read_control()
        assert result["paused"] is True
        assert result["level"] == "errors"

    def test_invalid_json_returns_empty_and_warns(self, tmp_path):
        """Malformed JSON returns empty dict and logs a warning."""
        relay = _import_relay()
        ctrl = tmp_path / "control.json"
        ctrl.write_text("{bad json!!!", encoding="utf-8")
        setattr(relay, "CONTROL_FILE", ctrl)
        result = relay._read_control()
        assert result == {}
        assert _log(relay).warning.call_count == 1
        assert (
            _log(relay)
            .warning.call_args.args[0]
            .startswith("[telegram_relay] The Telegram relay could not read its control file (%s)")
        )

    def test_non_dict_json_returns_empty_and_warns(self, tmp_path):
        """JSON that isn't a dict returns empty and logs warning."""
        relay = _import_relay()
        ctrl = tmp_path / "control.json"
        ctrl.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
        setattr(relay, "CONTROL_FILE", ctrl)
        result = relay._read_control()
        assert result == {}
        assert _log(relay).warning.call_count == 1
        assert (
            _log(relay)
            .warning.call_args.args[0]
            .startswith("[telegram_relay] The Telegram relay could not read its control file (%s)")
        )


class TestFlushControl:
    """Test _flush_buffer honors control file pause and level filtering."""

    def _make_relay(self, tmp_path, control_data=None):
        """Helper: import relay, wire credentials, point control file at tmp_path."""
        relay = _import_relay()
        setattr(relay, "_bot_token", "t")
        setattr(relay, "_chat_id", 1)
        setattr(relay, "_RELAY_ACTIVE", True)
        ctrl = tmp_path / "control.json"
        if control_data is not None:
            ctrl.write_text(json.dumps(control_data), encoding="utf-8")
        setattr(relay, "CONTROL_FILE", ctrl)
        return relay

    def test_paused_discards_buffer(self, tmp_path, monkeypatch):
        """Paused=true discards buffered lines, nothing sent."""
        relay = self._make_relay(tmp_path, {"paused": True, "level": "all"})
        relay._buffer.extend(["line 1", "line 2"])
        sent = []
        monkeypatch.setattr(relay, "_send_batched", lambda lines: sent.extend(lines))
        relay._flush_buffer()
        assert sent == []
        assert len(relay._buffer) == 0

    def test_unpaused_sends_all(self, tmp_path, monkeypatch):
        """Paused=false with level=all sends everything."""
        relay = self._make_relay(tmp_path, {"paused": False, "level": "all"})
        relay._buffer.extend(["info line", "WARNING alert"])
        sent = []
        monkeypatch.setattr(relay, "_send_batched", lambda lines: sent.extend(lines))
        relay._flush_buffer()
        assert len(sent) == 2

    def test_level_errors_filters_info_lines(self, tmp_path, monkeypatch):
        """Level=errors drops lines without WARNING/ERROR/CRITICAL markers."""
        relay = self._make_relay(tmp_path, {"paused": False, "level": "errors"})
        relay._buffer.extend(
            [
                "normal info line",
                "[10:00:00] [PRAX] WARNING disk full",
                "just a log",
                "[10:00:01] [FLOW] ERROR crash",
                "[10:00:02] [CLI] CRITICAL meltdown",
            ]
        )
        sent = []
        monkeypatch.setattr(relay, "_send_batched", lambda lines: sent.extend(lines))
        relay._flush_buffer()
        assert len(sent) == 3
        assert all(any(m in ln for m in ("WARNING", "ERROR", "CRITICAL")) for ln in sent)

    def test_level_errors_all_filtered_sends_nothing(self, tmp_path, monkeypatch):
        """Level=errors with no matching lines sends nothing."""
        relay = self._make_relay(tmp_path, {"paused": False, "level": "errors"})
        relay._buffer.extend(["info line 1", "info line 2"])
        sent = []
        monkeypatch.setattr(relay, "_send_batched", lambda lines: sent.extend(lines))
        relay._flush_buffer()
        assert sent == []

    def test_missing_control_file_sends_all(self, tmp_path, monkeypatch):
        """Missing control file = defaults (not paused, level=all)."""
        relay = self._make_relay(tmp_path)
        relay._buffer.extend(["line 1", "line 2"])
        sent = []
        monkeypatch.setattr(relay, "_send_batched", lambda lines: sent.extend(lines))
        relay._flush_buffer()
        assert len(sent) == 2

    def test_missing_keys_use_defaults(self, tmp_path, monkeypatch):
        """Control file with empty dict = not paused, level=all."""
        relay = self._make_relay(tmp_path, {})
        relay._buffer.extend(["line 1"])
        sent = []
        monkeypatch.setattr(relay, "_send_batched", lambda lines: sent.extend(lines))
        relay._flush_buffer()
        assert len(sent) == 1

    def test_flood_cap_still_applies_after_filter(self, tmp_path, monkeypatch):
        """FLOOD_CAP is enforced after level filtering."""
        relay = self._make_relay(tmp_path, {"paused": False, "level": "all"})
        relay._buffer.extend([f"line {i}" for i in range(200)])
        sent = []
        monkeypatch.setattr(relay, "_send_batched", lambda lines: sent.extend(lines))
        relay._flush_buffer()
        assert len(sent) == relay.FLOOD_CAP + 1
        assert "suppressed" in sent[-1]


class TestOfflineBackoff:
    """Network-failure backoff: doubles+caps, resets on success, log-once."""

    def _make_relay(self):
        relay = _import_relay()
        setattr(relay, "_bot_token", "t")
        setattr(relay, "_chat_id", 1)
        setattr(relay, "_RELAY_ACTIVE", True)
        return relay

    def test_network_error_enters_offline(self, monkeypatch):
        """First URLError sets _offline=True."""
        from urllib.error import URLError

        relay = self._make_relay()
        monkeypatch.setattr(relay, "_send_message", relay._send_message)
        with patch.object(relay, "_http_fetch", side_effect=URLError("DNS failed")):
            result = relay._send_message("hello")
        assert result is False
        assert relay._OFFLINE is True

    def test_backoff_doubles_on_repeated_failure(self):
        """Backoff doubles: 1 → 2 → 4."""
        from urllib.error import URLError

        relay = self._make_relay()
        with patch.object(relay, "_http_fetch", side_effect=URLError("offline")):
            relay._send_message("a")
            assert relay._CURRENT_BACKOFF == relay._BACKOFF_INITIAL
            relay._send_message("b")
            assert relay._CURRENT_BACKOFF == 2.0
            relay._send_message("c")
            assert relay._CURRENT_BACKOFF == 4.0

    def test_backoff_caps_at_60s(self):
        """Backoff never exceeds _BACKOFF_CAP (60s)."""
        from urllib.error import URLError

        relay = self._make_relay()
        with patch.object(relay, "_http_fetch", side_effect=URLError("offline")):
            for _ in range(20):
                relay._send_message("x")
        assert relay._CURRENT_BACKOFF == relay._BACKOFF_CAP

    def test_success_resets_offline(self):
        """Successful send after offline resets state."""
        from urllib.error import URLError

        relay = self._make_relay()
        with patch.object(relay, "_http_fetch", side_effect=URLError("offline")):
            relay._send_message("a")
        assert relay._OFFLINE is True

        ok_response = MagicMock()
        ok_response.read.return_value = b'{"ok": true}'
        ok_response.__enter__ = MagicMock(return_value=ok_response)
        ok_response.__exit__ = MagicMock(return_value=False)
        with patch.object(relay, "_http_fetch", return_value=ok_response):
            result = relay._send_message("b")
        assert result is True
        assert relay._OFFLINE is False
        assert relay._CURRENT_BACKOFF == relay._BACKOFF_INITIAL
        assert relay._SUPPRESSED_COUNT == 0

    def test_flush_suppresses_during_backoff(self, monkeypatch):
        """_flush_buffer skips _send_batched while offline and before next retry."""
        import time

        relay = self._make_relay()
        setattr(relay, "_OFFLINE", True)
        setattr(relay, "_NEXT_RETRY", time.monotonic() + 9999)
        relay._buffer.extend(["line 1", "line 2", "line 3"])
        sent = []
        monkeypatch.setattr(relay, "_send_batched", lambda lines: sent.extend(lines))
        relay._flush_buffer()
        assert sent == []
        assert relay._SUPPRESSED_COUNT == 3

    def test_flush_retries_after_backoff_expires(self, monkeypatch):
        """_flush_buffer attempts send when backoff period has elapsed."""
        import time

        relay = self._make_relay()
        setattr(relay, "_OFFLINE", True)
        setattr(relay, "_NEXT_RETRY", time.monotonic() - 1)
        relay._buffer.extend(["retry line"])
        sent = []
        monkeypatch.setattr(relay, "_send_batched", lambda lines: sent.extend(lines))
        relay._flush_buffer()
        assert len(sent) == 1

    def test_log_once_on_entering_offline(self):
        """Only one warning logged on first network failure."""
        from urllib.error import URLError

        relay = self._make_relay()
        with patch.object(relay, "_http_fetch", side_effect=URLError("offline")):
            relay._send_message("a")
            relay._send_message("b")
            relay._send_message("c")
        warning_calls = _log(relay).warning.call_args_list
        offline_warnings = [c for c in warning_calls if "offline" in str(c).lower()]
        assert len(offline_warnings) == 1

    def test_summary_logged_after_interval(self, monkeypatch):
        """Suppression summary logged after _SUMMARY_INTERVAL elapses."""
        import time

        relay = self._make_relay()
        setattr(relay, "_OFFLINE", True)
        setattr(relay, "_NEXT_RETRY", time.monotonic() + 9999)
        setattr(relay, "_LAST_SUMMARY", time.monotonic() - relay._SUMMARY_INTERVAL - 1)
        relay._buffer.extend(["line"])
        monkeypatch.setattr(relay, "_send_batched", lambda lines: None)
        relay._flush_buffer()
        info_calls = _log(relay).info.call_args_list
        summary_calls = [c for c in info_calls if "suppressed" in str(c).lower()]
        assert len(summary_calls) >= 1

    def test_recovery_log_includes_drop_count(self):
        """Recovery log line includes the number of dropped events."""
        from urllib.error import URLError

        relay = self._make_relay()
        with patch.object(relay, "_http_fetch", side_effect=URLError("offline")):
            relay._send_message("a")
        setattr(relay, "_SUPPRESSED_COUNT", 42)

        ok_response = MagicMock()
        ok_response.read.return_value = b'{"ok": true}'
        ok_response.__enter__ = MagicMock(return_value=ok_response)
        ok_response.__exit__ = MagicMock(return_value=False)
        with patch.object(relay, "_http_fetch", return_value=ok_response):
            relay._send_message("b")
        info_calls = _log(relay).info.call_args_list
        recovery_calls = [c for c in info_calls if "recovered" in str(c).lower()]
        assert len(recovery_calls) == 1
        assert "42" in str(recovery_calls[0])


class TestControlFileIsolation:
    """Tests must never inherit the operator's live pause state from HOME."""

    def test_import_never_points_at_operator_file(self, tmp_path):
        """A freshly imported relay reads a tmp control file, not the operator's."""
        relay = _import_relay()
        assert relay.CONTROL_FILE != _operator_control_file()
        assert relay.CONTROL_FILE == tmp_path / "relay_control.json"

    def test_flush_ignores_a_paused_operator_file(self, tmp_path, monkeypatch):
        """paused=true in the isolated file suppresses; the real file is never consulted."""
        relay = _import_relay()
        setattr(relay, "_bot_token", "t")
        setattr(relay, "_chat_id", 1)
        setattr(relay, "_RELAY_ACTIVE", True)
        sent = []
        monkeypatch.setattr(relay, "_send_batched", lambda lines: sent.extend(lines))

        relay._buffer.extend(["line 1", "line 2"])
        relay._flush_buffer()
        assert len(sent) == 2, "no control file must mean 'not paused', whatever HOME says"

        relay.CONTROL_FILE.write_text(json.dumps({"paused": True}), encoding="utf-8")
        relay._buffer.extend(["line 3"])
        relay._flush_buffer()
        assert len(sent) == 2

    def test_helper_refuses_without_isolation(self, monkeypatch):
        """The helper fails loud rather than silently reading operator state."""
        monkeypatch.setattr(telegram_relay, "CONTROL_FILE", _operator_control_file())
        with pytest.raises(RuntimeError, match="operator's live control file"):
            _import_relay()
