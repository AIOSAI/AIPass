# =================== AIPass ====================
# Name: test_telegram_relay.py
# Description: Tests for the Telegram relay handler
# Version: 1.2.0
# Created: 2026-06-24
# Modified: 2026-08-08
# =============================================

"""Tests for apps/handlers/monitoring/telegram_relay.py

Covers:
- Event formatting (log, command, hook types, PID labels)
- init_relay: disabled path, missing config, incomplete config, successful start
- Fail-silent-once: exactly one log line when config absent, zero sends
- stop_relay: final flush and thread join, no-op when inactive
- relay_event: buffering when active, no-op when inactive
- Batching: 4000-char split across messages
- Flood cap: truncation at 150 lines with suppression notice
- _render_event calls relay_event in monitor.py
- is_relay_enabled_by_env for env var detection
- Offline backoff: doubles+caps, resets on success, log-once, never blocks
- Control-file isolation: no test ever reads the operator's live pause state
"""

import importlib
import json
import ntpath
import os
import posixpath
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest

# Captured at import, before any fixture redirects the home directory: this is the
# real operator's file on this machine, and the one no test may ever touch.
_REAL_HOME = Path.home()
_OPERATOR_CONTROL_FILE = _REAL_HOME / ".aipass" / "telegram_bots" / "prax_monitor_control.json"


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


# ---------------------------------------------------------------------------
# Control-file isolation
# ---------------------------------------------------------------------------
#
# The module default CONTROL_FILE is ~/.aipass/telegram_bots/prax_monitor_control.json
# — LIVE operator state, written by the Telegram bot when the operator pauses or
# filters the feed. _flush_buffer discards the whole buffer when paused=true, so a
# test that flushes without re-pointing CONTROL_FILE inherits the operator's pause:
# red on a machine where the bot is paused, green on CI where no control file exists.
# Tests assert on relay behavior, never on operator state, so every import is aimed
# at a per-test tmp path and _import_relay refuses to return a module still aimed
# at the operator's home.
#
# Isolation is belt AND braces, because each covers a different failure:
#   braces — _import_relay re-points CONTROL_FILE after every reload (the module
#            default is recomputed by the reload, so a one-time patch would lapse).
#   belt   — the home directory itself is redirected while the reload runs, so even
#            the recomputed default lands in tmp. If someone deletes the re-point
#            line, the tests still cannot reach the operator's file.
#
# The belt must set HOME *and* USERPROFILE. Path.home() calls os.path.expanduser("~"),
# which reads HOME on POSIX but USERPROFILE on Windows (ntpath.expanduser checks
# USERPROFILE first, then HOMEDRIVE+HOMEPATH — HOME is never consulted). Setting only
# HOME would leave Windows resolving the real profile. Pinned by
# TestHomeRedirectIsPlatformHonest, which exercises both resolvers by name so the
# Windows branch is proven on any platform.

_ISOLATED_CONTROL_FILE: Optional[Path] = None
_ISOLATED_HOME: Optional[Path] = None
# CONTROL_FILE as the reload computed it, before _import_relay re-points it.
_LAST_RELOAD_DEFAULT: Optional[Path] = None


@pytest.fixture(autouse=True)
def isolate_control_file(tmp_path):
    """Point every relay import at a throwaway control file, never the operator's."""
    global _ISOLATED_CONTROL_FILE, _ISOLATED_HOME, _LAST_RELOAD_DEFAULT
    _ISOLATED_CONTROL_FILE = tmp_path / "relay_control.json"
    _ISOLATED_HOME = tmp_path / "home"
    yield
    _ISOLATED_CONTROL_FILE = None
    _ISOLATED_HOME = None
    _LAST_RELOAD_DEFAULT = None


def _isolated_home_env() -> dict:
    """Env overrides that move Path.home() into tmp on every platform."""
    return {"HOME": str(_ISOLATED_HOME), "USERPROFILE": str(_ISOLATED_HOME)}


def _import_relay():
    """Import (or reload) telegram_relay with mocked dependencies."""
    if _ISOLATED_CONTROL_FILE is None:
        raise RuntimeError(
            "_import_relay() called outside the isolate_control_file fixture — "
            "the relay would read the operator's live control file"
        )

    global _LAST_RELOAD_DEFAULT

    fresh_mocks = {
        "aipass.prax.apps.modules.logger": MagicMock(),
        "aipass.prax.apps.handlers.json": MagicMock(),
        "aipass.prax.apps.handlers.json.json_handler": MagicMock(),
    }
    # The home redirect wraps the reload because that is the only moment the module
    # default is computed — scoping it here keeps every other test's environment real.
    with patch.dict(os.environ, _isolated_home_env()), patch.dict(sys.modules, fresh_mocks):
        if "aipass.prax.apps.handlers.monitoring.telegram_relay" in sys.modules:
            mod = importlib.reload(sys.modules["aipass.prax.apps.handlers.monitoring.telegram_relay"])
        else:
            mod = importlib.import_module("aipass.prax.apps.handlers.monitoring.telegram_relay")

    _LAST_RELOAD_DEFAULT = mod.CONTROL_FILE
    setattr(mod, "CONTROL_FILE", _ISOLATED_CONTROL_FILE)

    lock_mock = MagicMock()
    lock_mock.try_acquire = MagicMock(return_value=True)
    lock_mock.release = MagicMock()
    setattr(mod, "instance_lock", lock_mock)

    setattr(mod, "_RELAY_ACTIVE", False)
    setattr(mod, "_bot_token", None)
    setattr(mod, "_chat_id", None)
    mod._buffer.clear()
    mod._stop_event.clear()
    setattr(mod, "_thread", None)
    setattr(mod, "_OFFLINE", False)
    setattr(mod, "_CURRENT_BACKOFF", mod._BACKOFF_INITIAL)
    setattr(mod, "_NEXT_RETRY", 0.0)
    setattr(mod, "_SUPPRESSED_COUNT", 0)
    return mod


# ---------------------------------------------------------------------------
# Event formatting
# ---------------------------------------------------------------------------


class TestFormatEvent:
    """Test _format_event produces correct plain-text lines."""

    def test_log_event_basic(self):
        """Log event includes uppercased branch and message."""
        relay = _import_relay()
        event = FakeEvent(event_type="log", branch="seedgo", message="Audit started")
        result = relay._format_event(event)
        assert "[SEEDGO]" in result
        assert "Audit started" in result

    def test_log_event_with_pid(self):
        """Log event with PID shows BRANCH:PID label."""
        relay = _import_relay()
        event = FakeEvent(event_type="log", branch="devpulse", message="Working", pid=12345)
        result = relay._format_event(event)
        assert "[DEVPULSE:12345]" in result

    def test_command_event(self):
        """Command event shows arrow prefix."""
        relay = _import_relay()
        event = FakeEvent(event_type="command", branch="drone", message="seedgo audit", action="")
        result = relay._format_event(event)
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
        result = relay._format_event(event)
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
        result = relay._format_event(event)
        assert "UNKNOWN" not in result

    def test_hook_event_fired(self):
        """Fired hook event uses lightning bolt symbol."""
        relay = _import_relay()
        event = FakeEvent(event_type="hook", branch="hooks", message="cadence:fired", action="fired")
        result = relay._format_event(event)
        assert result == "⚡ HOOK cadence:fired"

    def test_hook_event_skipped(self):
        """Skipped hook event uses dot symbol."""
        relay = _import_relay()
        event = FakeEvent(event_type="hook", branch="hooks", message="cadence:skipped", action="skipped")
        result = relay._format_event(event)
        assert result == "· HOOK cadence:skipped"

    def test_hook_event_unknown_action(self):
        """Unknown hook action uses question mark symbol."""
        relay = _import_relay()
        event = FakeEvent(event_type="hook", branch="hooks", message="something", action="other")
        result = relay._format_event(event)
        assert result.startswith("? HOOK")

    def test_file_event(self):
        """File event formats like a log event with branch and message."""
        relay = _import_relay()
        event = FakeEvent(event_type="file", branch="prax", message="monitor.py modified")
        result = relay._format_event(event)
        assert "[PRAX]" in result
        assert "monitor.py modified" in result


# ---------------------------------------------------------------------------
# init_relay
# ---------------------------------------------------------------------------


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
        calls = [c for c in relay.logger.info.call_args_list if "inactive" in str(c)]
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
        assert relay._thread.daemon is True
        assert relay._thread.name == "telegram-relay"
        relay.stop_relay()


# ---------------------------------------------------------------------------
# relay_event
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# stop_relay
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Batching
# ---------------------------------------------------------------------------


class TestBatching:
    """Test _send_batched 4000-char splitting."""

    def test_single_message_under_limit(self):
        """Short content sends as one message."""
        relay = _import_relay()
        sent = []
        setattr(relay, "_send_message", lambda text: sent.append(text) or True)
        relay._send_batched(["short line"])
        assert len(sent) == 1
        assert sent[0] == "short line"

    def test_splits_at_4000_chars(self):
        """Lines exceeding 4000 chars are split across multiple messages."""
        relay = _import_relay()
        sent = []
        setattr(relay, "_send_message", lambda text: sent.append(text) or True)
        lines = [f"line-{i:04d}-" + "x" * 90 for i in range(50)]
        relay._send_batched(lines)
        assert len(sent) > 1
        for msg in sent:
            assert len(msg) <= relay.TELEGRAM_MAX_LENGTH + 200

    def test_empty_lines_sends_nothing(self):
        """Empty list sends no messages."""
        relay = _import_relay()
        sent = []
        setattr(relay, "_send_message", lambda text: sent.append(text) or True)
        relay._send_batched([])
        assert len(sent) == 0


# ---------------------------------------------------------------------------
# Flood cap
# ---------------------------------------------------------------------------


class TestFloodCap:
    """Test flood cap truncation."""

    def test_under_cap_sends_all(self):
        """Lines under FLOOD_CAP are all delivered."""
        relay = _import_relay()
        setattr(relay, "_bot_token", "t")
        setattr(relay, "_chat_id", 1)
        sent = []
        setattr(relay, "_send_batched", lambda lines: sent.extend(lines))
        relay._buffer.extend([f"line {i}" for i in range(100)])
        setattr(relay, "_RELAY_ACTIVE", True)
        relay._flush_buffer()
        assert len(sent) == 100

    def test_over_cap_truncates_with_notice(self):
        """Lines over FLOOD_CAP are truncated with a suppression notice."""
        relay = _import_relay()
        setattr(relay, "_bot_token", "t")
        setattr(relay, "_chat_id", 1)
        sent_lines = []
        setattr(relay, "_send_batched", lambda lines: sent_lines.extend(lines))
        relay._buffer.extend([f"line {i}" for i in range(200)])
        setattr(relay, "_RELAY_ACTIVE", True)
        relay._flush_buffer()
        assert len(sent_lines) == relay.FLOOD_CAP + 1
        assert "50 more suppressed" in sent_lines[-1]


# ---------------------------------------------------------------------------
# _render_event calls relay_event
# ---------------------------------------------------------------------------


class TestRenderEventCallsRelay:
    """Test that monitor._render_event calls relay_event."""

    def test_render_event_calls_relay(self):
        """_render_event in monitor.py calls relay_event after console render."""
        fresh_mocks = {
            "aipass.prax.apps.handlers.monitoring": MagicMock(),
            "aipass.prax.apps.handlers.monitoring.event_queue": MagicMock(),
            "aipass.prax.apps.handlers.monitoring.filesystem_handler": MagicMock(),
            "aipass.prax.apps.handlers.monitoring.log_watcher": MagicMock(),
            "aipass.prax.apps.handlers.monitoring.unified_stream": MagicMock(),
            "aipass.prax.apps.handlers.monitoring.module_tracker": MagicMock(),
            "aipass.prax.apps.handlers.monitoring.branch_detector": MagicMock(),
            "aipass.prax.apps.handlers.monitoring.interactive_filter": MagicMock(),
            "aipass.prax.apps.handlers.monitoring.monitoring_filters": MagicMock(),
            "aipass.prax.apps.handlers.monitoring.file_watcher_integration": MagicMock(),
            "aipass.prax.apps.handlers.monitoring.telegram_relay": MagicMock(),
            "aipass.prax.apps.handlers.monitoring.pid_cache": MagicMock(),
            "aipass.prax.apps.handlers.monitoring.instance_lock": MagicMock(),
        }
        with patch.dict(sys.modules, fresh_mocks):
            if "aipass.prax.apps.modules.monitor" in sys.modules:
                mod = importlib.reload(sys.modules["aipass.prax.apps.modules.monitor"])
            else:
                mod = importlib.import_module("aipass.prax.apps.modules.monitor")

        event = MagicMock()
        event.event_type = "log"
        event.branch = "TEST"
        event.message = "hello"
        event.level = "info"
        event.action = ""

        with patch.object(mod, "_get_pid_for_branch", return_value=None):
            mod._render_event(event)

        mod.relay_event.assert_called_once_with(event)


# ---------------------------------------------------------------------------
# is_relay_enabled_by_env
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Control file: _read_control
# ---------------------------------------------------------------------------


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
        ctrl.write_text(json.dumps({"paused": True, "level": "errors"}))
        setattr(relay, "CONTROL_FILE", ctrl)
        result = relay._read_control()
        assert result["paused"] is True
        assert result["level"] == "errors"

    def test_mtime_cache_avoids_reread(self, tmp_path):
        """Same mtime returns cached result without re-reading the file."""
        relay = _import_relay()
        ctrl = tmp_path / "control.json"
        ctrl.write_text(json.dumps({"paused": False}))
        setattr(relay, "CONTROL_FILE", ctrl)
        first = relay._read_control()
        cached_mtime = ctrl.stat().st_mtime
        ctrl.write_text("INVALID JSON")
        os.utime(ctrl, (cached_mtime, cached_mtime))
        result = relay._read_control()
        assert result == first

    def test_mtime_change_triggers_reread(self, tmp_path):
        """Changed mtime causes re-read of the control file."""
        relay = _import_relay()
        ctrl = tmp_path / "control.json"
        ctrl.write_text(json.dumps({"paused": False, "level": "all"}))
        setattr(relay, "CONTROL_FILE", ctrl)
        relay._read_control()
        ctrl.write_text(json.dumps({"paused": True, "level": "errors"}))
        os.utime(ctrl, (ctrl.stat().st_mtime + 1, ctrl.stat().st_mtime + 1))
        result = relay._read_control()
        assert result["paused"] is True
        assert result["level"] == "errors"

    def test_invalid_json_returns_empty_and_warns(self, tmp_path):
        """Malformed JSON returns empty dict and logs a warning."""
        relay = _import_relay()
        ctrl = tmp_path / "control.json"
        ctrl.write_text("{bad json!!!")
        setattr(relay, "CONTROL_FILE", ctrl)
        result = relay._read_control()
        assert result == {}
        relay.logger.warning.assert_called_once()

    def test_non_dict_json_returns_empty_and_warns(self, tmp_path):
        """JSON that isn't a dict returns empty and logs warning."""
        relay = _import_relay()
        ctrl = tmp_path / "control.json"
        ctrl.write_text(json.dumps([1, 2, 3]))
        setattr(relay, "CONTROL_FILE", ctrl)
        result = relay._read_control()
        assert result == {}
        relay.logger.warning.assert_called_once()


# ---------------------------------------------------------------------------
# Control file: flush behavior with pause / level filter
# ---------------------------------------------------------------------------


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
            ctrl.write_text(json.dumps(control_data))
        setattr(relay, "CONTROL_FILE", ctrl)
        return relay

    def test_paused_discards_buffer(self, tmp_path):
        """Paused=true discards buffered lines, nothing sent."""
        relay = self._make_relay(tmp_path, {"paused": True, "level": "all"})
        relay._buffer.extend(["line 1", "line 2"])
        sent = []
        setattr(relay, "_send_batched", lambda lines: sent.extend(lines))
        relay._flush_buffer()
        assert sent == []
        assert len(relay._buffer) == 0

    def test_unpaused_sends_all(self, tmp_path):
        """Paused=false with level=all sends everything."""
        relay = self._make_relay(tmp_path, {"paused": False, "level": "all"})
        relay._buffer.extend(["info line", "WARNING alert"])
        sent = []
        setattr(relay, "_send_batched", lambda lines: sent.extend(lines))
        relay._flush_buffer()
        assert len(sent) == 2

    def test_level_errors_filters_info_lines(self, tmp_path):
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
        setattr(relay, "_send_batched", lambda lines: sent.extend(lines))
        relay._flush_buffer()
        assert len(sent) == 3
        assert all(any(m in ln for m in ("WARNING", "ERROR", "CRITICAL")) for ln in sent)

    def test_level_errors_all_filtered_sends_nothing(self, tmp_path):
        """Level=errors with no matching lines sends nothing."""
        relay = self._make_relay(tmp_path, {"paused": False, "level": "errors"})
        relay._buffer.extend(["info line 1", "info line 2"])
        sent = []
        setattr(relay, "_send_batched", lambda lines: sent.extend(lines))
        relay._flush_buffer()
        assert sent == []

    def test_missing_control_file_sends_all(self, tmp_path):
        """Missing control file = defaults (not paused, level=all)."""
        relay = self._make_relay(tmp_path)
        relay._buffer.extend(["line 1", "line 2"])
        sent = []
        setattr(relay, "_send_batched", lambda lines: sent.extend(lines))
        relay._flush_buffer()
        assert len(sent) == 2

    def test_missing_keys_use_defaults(self, tmp_path):
        """Control file with empty dict = not paused, level=all."""
        relay = self._make_relay(tmp_path, {})
        relay._buffer.extend(["line 1"])
        sent = []
        setattr(relay, "_send_batched", lambda lines: sent.extend(lines))
        relay._flush_buffer()
        assert len(sent) == 1

    def test_flood_cap_still_applies_after_filter(self, tmp_path):
        """FLOOD_CAP is enforced after level filtering."""
        relay = self._make_relay(tmp_path, {"paused": False, "level": "all"})
        relay._buffer.extend([f"line {i}" for i in range(200)])
        sent = []
        setattr(relay, "_send_batched", lambda lines: sent.extend(lines))
        relay._flush_buffer()
        assert len(sent) == relay.FLOOD_CAP + 1
        assert "suppressed" in sent[-1]


# ---------------------------------------------------------------------------
# Offline backoff
# ---------------------------------------------------------------------------


class TestOfflineBackoff:
    """Network-failure backoff: doubles+caps, resets on success, log-once."""

    def _make_relay(self):
        relay = _import_relay()
        setattr(relay, "_bot_token", "t")
        setattr(relay, "_chat_id", 1)
        setattr(relay, "_RELAY_ACTIVE", True)
        return relay

    def test_network_error_enters_offline(self):
        """First URLError sets _offline=True."""
        from urllib.error import URLError

        relay = self._make_relay()
        setattr(relay, "_send_message", relay._send_message)
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

    def test_flush_suppresses_during_backoff(self):
        """_flush_buffer skips _send_batched while offline and before next retry."""
        import time

        relay = self._make_relay()
        setattr(relay, "_OFFLINE", True)
        setattr(relay, "_NEXT_RETRY", time.monotonic() + 9999)
        relay._buffer.extend(["line 1", "line 2", "line 3"])
        sent = []
        setattr(relay, "_send_batched", lambda lines: sent.extend(lines))
        relay._flush_buffer()
        assert sent == []
        assert relay._SUPPRESSED_COUNT == 3

    def test_flush_retries_after_backoff_expires(self):
        """_flush_buffer attempts send when backoff period has elapsed."""
        import time

        relay = self._make_relay()
        setattr(relay, "_OFFLINE", True)
        setattr(relay, "_NEXT_RETRY", time.monotonic() - 1)
        relay._buffer.extend(["retry line"])
        sent = []
        setattr(relay, "_send_batched", lambda lines: sent.extend(lines))
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
        warning_calls = relay.logger.warning.call_args_list
        offline_warnings = [c for c in warning_calls if "offline" in str(c).lower()]
        assert len(offline_warnings) == 1

    def test_summary_logged_after_interval(self):
        """Suppression summary logged after _SUMMARY_INTERVAL elapses."""
        import time

        relay = self._make_relay()
        setattr(relay, "_OFFLINE", True)
        setattr(relay, "_NEXT_RETRY", time.monotonic() + 9999)
        setattr(relay, "_LAST_SUMMARY", time.monotonic() - relay._SUMMARY_INTERVAL - 1)
        relay._buffer.extend(["line"])
        setattr(relay, "_send_batched", lambda lines: None)
        relay._flush_buffer()
        info_calls = relay.logger.info.call_args_list
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
        info_calls = relay.logger.info.call_args_list
        recovery_calls = [c for c in info_calls if "recovered" in str(c).lower()]
        assert len(recovery_calls) == 1
        assert "42" in str(recovery_calls[0])


# ---------------------------------------------------------------------------
# Control-file isolation
# ---------------------------------------------------------------------------


class TestControlFileIsolation:
    """Tests must never inherit the operator's live pause state from HOME."""

    def test_import_never_points_at_operator_file(self, tmp_path):
        """A freshly imported relay reads a tmp control file, not the operator's."""
        relay = _import_relay()
        assert relay.CONTROL_FILE != _OPERATOR_CONTROL_FILE
        assert relay.CONTROL_FILE == tmp_path / "relay_control.json"

    def test_reimport_re_isolates(self):
        """Reload recomputes the default, so every import must re-point after it.

        Asserted by path identity, never by ancestry. "not under home" was the
        original check and it is a POSIX-only proxy: on Windows pytest's tmp_path
        lives *inside* the user profile (…/AppData/Local/Temp/pytest-of-…), so the
        home directory is an ancestor of the isolated file too. That check cannot
        tell working isolation from lapsed isolation there, and it failed CI on
        2026-08-08 while isolation was in fact holding.
        """
        _import_relay()
        relay = _import_relay()
        assert relay.CONTROL_FILE == _ISOLATED_CONTROL_FILE
        assert relay.CONTROL_FILE != _OPERATOR_CONTROL_FILE

    def test_reload_default_is_recomputed_not_inherited(self):
        """The re-point is load-bearing: the reload really does rebuild the default."""
        relay = _import_relay()
        assert _LAST_RELOAD_DEFAULT is not None
        assert _LAST_RELOAD_DEFAULT != _ISOLATED_CONTROL_FILE, "re-point would be decorative"
        assert relay.CONTROL_FILE == _ISOLATED_CONTROL_FILE

    def test_reload_default_lands_in_tmp_without_the_re_point(self):
        """Belt alone holds: even the recomputed default is inside the isolated home."""
        _import_relay()
        assert _LAST_RELOAD_DEFAULT is not None
        assert _ISOLATED_HOME is not None
        assert _LAST_RELOAD_DEFAULT.is_relative_to(_ISOLATED_HOME)
        assert _LAST_RELOAD_DEFAULT != _OPERATOR_CONTROL_FILE

    def test_flush_ignores_a_paused_operator_file(self, tmp_path):
        """paused=true in the isolated file suppresses; the real file is never consulted."""
        relay = _import_relay()
        setattr(relay, "_bot_token", "t")
        setattr(relay, "_chat_id", 1)
        setattr(relay, "_RELAY_ACTIVE", True)
        sent = []
        setattr(relay, "_send_batched", lambda lines: sent.extend(lines))

        relay._buffer.extend(["line 1", "line 2"])
        relay._flush_buffer()
        assert len(sent) == 2, "no control file must mean 'not paused', whatever HOME says"

        relay.CONTROL_FILE.write_text(json.dumps({"paused": True}))
        relay._buffer.extend(["line 3"])
        relay._flush_buffer()
        assert len(sent) == 2

    def test_helper_refuses_without_isolation(self, monkeypatch):
        """The helper fails loud rather than silently reading operator state."""
        monkeypatch.setattr(sys.modules[__name__], "_ISOLATED_CONTROL_FILE", None)
        with pytest.raises(RuntimeError, match="operator's live control file"):
            _import_relay()


class TestHomeRedirectIsPlatformHonest:
    """The home redirect must hold on Windows, which nobody here can run locally.

    Path.home() delegates to os.path.expanduser("~"), which is posixpath.expanduser
    on Linux/macOS and ntpath.expanduser on Windows — two functions reading two
    different environment variables. Calling both by name proves the Windows branch
    from any platform, so this stays honest without a Windows box.
    """

    def test_both_resolvers_land_in_the_isolated_home(self):
        """HOME covers POSIX, USERPROFILE covers Windows — the redirect sets both."""
        with patch.dict(os.environ, _isolated_home_env()):
            assert posixpath.expanduser("~") == str(_ISOLATED_HOME)
            assert ntpath.expanduser("~") == str(_ISOLATED_HOME)

    def test_home_alone_lapses_on_windows(self):
        """The CI failure class, reproduced on any platform: HOME is not enough.

        Setting only HOME leaves ntpath.expanduser reading the real USERPROFILE, so
        a reload on Windows would rebuild CONTROL_FILE from the operator's profile.
        This is why _isolated_home_env sets both.
        """
        operator_profile = r"C:\Users\runneradmin"
        with patch.dict(os.environ, {"HOME": str(_ISOLATED_HOME), "USERPROFILE": operator_profile}):
            assert posixpath.expanduser("~") == str(_ISOLATED_HOME)
            assert ntpath.expanduser("~") == operator_profile

    def test_import_relay_redirects_home_for_both_resolvers(self):
        """The env the helper actually applies, not a hand-built copy."""
        env = _isolated_home_env()
        assert env["HOME"] == env["USERPROFILE"] == str(_ISOLATED_HOME)
        assert not Path(env["HOME"]).is_relative_to(_REAL_HOME / ".aipass")
