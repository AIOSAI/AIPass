# =================== AIPass ====================
# Name: test_logs.py
# Description: Tests for /logs command — session log stream control
# Version: 1.0.0
# Created: 2026-07-12
# Modified: 2026-07-12
# =============================================

"""
Tests for /logs command — session log stream control.

Tests cover:
  - /logs on persists preference and starts streamer
  - /logs off stops streamer and persists "off"
  - /logs errors starts with level_filter="default"
  - /logs status shows correct state
  - /logs command routing (on, off, errors, status, bare, unknown)
  - Auto-start at handle_update honors saved preference
  - /logs unavailable on base bot (branch_name=None)
  - Persistence roundtrip (save + reload)
"""

import json
from pathlib import Path

import pytest
from unittest.mock import patch, MagicMock


# =============================================
# HELPERS
# =============================================


@pytest.fixture
def _patch_base_bot_deps(tmp_path):
    """Patch heavy BaseBot dependencies to allow lightweight instantiation."""
    pref_file = tmp_path / "logs_pref.json"
    patches = [
        patch("aipass.skills.lib.telegram.apps.handlers.base_bot.PENDING_DIR", tmp_path),
        patch("aipass.skills.lib.telegram.apps.handlers.base_bot.signal.signal"),
        patch("aipass.skills.lib.telegram.apps.handlers.base_bot.atexit.register"),
    ]
    for p in patches:
        p.start()
    yield pref_file
    for p in patches:
        p.stop()


def _make_bot(tmp_path, _patch_base_bot_deps, branch_name: str | None = "testbranch"):
    """Create a BaseBot with logs preference redirected to tmp_path."""
    from aipass.skills.lib.telegram.apps.handlers.base_bot import BaseBot

    workdir = tmp_path / "workdir"
    workdir.mkdir(exist_ok=True)
    bot = BaseBot(
        bot_id="logs_test",
        bot_token="123:FAKETOKEN",
        work_dir=workdir,
        bot_name="Logs Test Bot",
        allowed_user_ids=[111],
        branch_name=branch_name,
    )
    pref_file: Path = _patch_base_bot_deps
    bot._logs_preference_file = lambda: pref_file  # type: ignore[assignment]
    return bot


# =============================================
# 1. /LOGS ON — PERSIST + START STREAMER
# =============================================


class TestLogsOn:
    """Verify /logs on persists preference and starts streamer."""

    def test_on_writes_preference(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        pref_file: Path = _patch_base_bot_deps
        with (
            patch.object(bot, "send_message"),
            patch("aipass.skills.lib.telegram.apps.handlers.base_bot.LogStreamer") as MockStreamer,
        ):
            MockStreamer.return_value = MagicMock()
            bot._logs_start(42, "all")

            data = json.loads(pref_file.read_text(encoding="utf-8"))
            assert data == {"chat_id": 42, "mode": "all"}

    def test_on_starts_streamer(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        with (
            patch.object(bot, "send_message"),
            patch("aipass.skills.lib.telegram.apps.handlers.base_bot.LogStreamer") as MockStreamer,
        ):
            mock_instance = MagicMock()
            MockStreamer.return_value = mock_instance

            bot._logs_start(42, "all")

            MockStreamer.assert_called_once_with(
                "123:FAKETOKEN",
                42,
                "testbranch",
                level_filter="all",
            )
            mock_instance.start.assert_called_once()
            assert bot._log_streamer is mock_instance

    def test_on_sends_confirmation(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        with (
            patch.object(bot, "send_message") as mock_send,
            patch("aipass.skills.lib.telegram.apps.handlers.base_bot.LogStreamer", return_value=MagicMock()),
        ):
            bot._logs_start(42, "all")
            mock_send.assert_called_once()
            msg = mock_send.call_args[0][1]
            assert "all levels" in msg

    def test_on_stops_existing_streamer(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        old_streamer = MagicMock()
        bot._log_streamer = old_streamer

        with (
            patch.object(bot, "send_message"),
            patch("aipass.skills.lib.telegram.apps.handlers.base_bot.LogStreamer", return_value=MagicMock()),
        ):
            bot._logs_start(42, "all")
            old_streamer.stop.assert_called_once()

    def test_on_aborts_on_save_failure(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        with (
            patch.object(bot, "_save_logs_preference", return_value=False),
            patch.object(bot, "send_message") as mock_send,
        ):
            bot._logs_start(42, "all")
            msg = mock_send.call_args[0][1]
            assert "Failed" in msg
            assert bot._log_streamer is None


# =============================================
# 2. /LOGS ERRORS — FILTERED MODE
# =============================================


class TestLogsErrors:
    """Verify /logs errors starts with level_filter="default"."""

    def test_errors_starts_with_default_filter(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        with (
            patch.object(bot, "send_message"),
            patch("aipass.skills.lib.telegram.apps.handlers.base_bot.LogStreamer") as MockStreamer,
        ):
            MockStreamer.return_value = MagicMock()
            bot._logs_start(42, "default")

            MockStreamer.assert_called_once_with(
                "123:FAKETOKEN",
                42,
                "testbranch",
                level_filter="default",
            )

    def test_errors_confirmation_message(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        with (
            patch.object(bot, "send_message") as mock_send,
            patch("aipass.skills.lib.telegram.apps.handlers.base_bot.LogStreamer", return_value=MagicMock()),
        ):
            bot._logs_start(42, "default")
            msg = mock_send.call_args[0][1]
            assert "errors & warnings" in msg

    def test_errors_persists_mode(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        pref_file: Path = _patch_base_bot_deps
        with (
            patch.object(bot, "send_message"),
            patch("aipass.skills.lib.telegram.apps.handlers.base_bot.LogStreamer", return_value=MagicMock()),
        ):
            bot._logs_start(42, "default")
            data = json.loads(pref_file.read_text(encoding="utf-8"))
            assert data["mode"] == "default"


# =============================================
# 3. /LOGS OFF — STOP + PERSIST
# =============================================


class TestLogsOff:
    """Verify /logs off stops streamer and persists 'off'."""

    def test_off_stops_streamer(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        mock_streamer = MagicMock()
        bot._log_streamer = mock_streamer

        with patch.object(bot, "send_message"):
            bot._logs_stop(42)

        mock_streamer.stop.assert_called_once()
        assert bot._log_streamer is None

    def test_off_persists_off(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        pref_file: Path = _patch_base_bot_deps

        with patch.object(bot, "send_message"):
            bot._logs_stop(42)

        data = json.loads(pref_file.read_text(encoding="utf-8"))
        assert data["mode"] == "off"

    def test_off_sends_confirmation(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        with patch.object(bot, "send_message") as mock_send:
            bot._logs_stop(42)

        mock_send.assert_called_once()
        assert "stopped" in mock_send.call_args[0][1].lower()

    def test_off_safe_when_no_streamer(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        assert bot._log_streamer is None

        with patch.object(bot, "send_message"):
            bot._logs_stop(42)

        assert bot._log_streamer is None


# =============================================
# 4. /LOGS STATUS
# =============================================


class TestLogsStatus:
    """Verify /logs status shows correct state."""

    def test_status_when_stopped(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        with patch.object(bot, "send_message") as mock_send:
            bot._logs_status(42)
            msg = mock_send.call_args[0][1]
            assert "stopped" in msg

    def test_status_when_disabled(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        pref_file: Path = _patch_base_bot_deps
        pref_file.write_text(json.dumps({"chat_id": 42, "mode": "off"}), encoding="utf-8")

        with patch.object(bot, "send_message") as mock_send:
            bot._logs_status(42)
            msg = mock_send.call_args[0][1]
            assert "disabled" in msg

    def test_status_when_active(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        pref_file: Path = _patch_base_bot_deps
        pref_file.write_text(json.dumps({"chat_id": 42, "mode": "all"}), encoding="utf-8")
        bot._log_streamer = MagicMock(_running=True)

        with patch.object(bot, "send_message") as mock_send:
            bot._logs_status(42)
            msg = mock_send.call_args[0][1]
            assert "active" in msg
            assert "all levels" in msg

    def test_status_shows_errors_mode(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        pref_file: Path = _patch_base_bot_deps
        pref_file.write_text(json.dumps({"chat_id": 42, "mode": "default"}), encoding="utf-8")
        bot._log_streamer = MagicMock(_running=True)

        with patch.object(bot, "send_message") as mock_send:
            bot._logs_status(42)
            msg = mock_send.call_args[0][1]
            assert "errors & warnings" in msg

    def test_status_shows_branch_name(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        pref_file: Path = _patch_base_bot_deps
        pref_file.write_text(json.dumps({"chat_id": 42, "mode": "all"}), encoding="utf-8")
        bot._log_streamer = MagicMock(_running=True)

        with patch.object(bot, "send_message") as mock_send:
            bot._logs_status(42)
            msg = mock_send.call_args[0][1]
            assert "testbranch" in msg


# =============================================
# 5. COMMAND ROUTING
# =============================================


class TestLogsCommandRouting:
    """Verify _handle_logs_command routes subcommands correctly."""

    def test_on_routes_to_start_all(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        with patch.object(bot, "_logs_start") as mock_start:
            bot._handle_logs_command(42, "on")
            mock_start.assert_called_once_with(42, mode="all")

    def test_errors_routes_to_start_default(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        with patch.object(bot, "_logs_start") as mock_start:
            bot._handle_logs_command(42, "errors")
            mock_start.assert_called_once_with(42, mode="default")

    def test_off_routes_to_stop(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        with patch.object(bot, "_logs_stop") as mock_stop:
            bot._handle_logs_command(42, "off")
            mock_stop.assert_called_once_with(42)

    def test_status_routes_to_status(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        with patch.object(bot, "_logs_status") as mock_stat:
            bot._handle_logs_command(42, "status")
            mock_stat.assert_called_once_with(42)

    def test_bare_logs_shows_help(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        with patch.object(bot, "send_message") as mock_send:
            bot._handle_logs_command(42, "")
            msg = mock_send.call_args[0][1]
            assert "/logs on" in msg
            assert "/logs off" in msg
            assert "/logs errors" in msg

    def test_unknown_subcommand_shows_help(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        with patch.object(bot, "send_message") as mock_send:
            bot._handle_logs_command(42, "banana")
            msg = mock_send.call_args[0][1]
            assert "/logs on" in msg


# =============================================
# 6. BASE BOT GUARD (branch_name=None)
# =============================================


class TestLogsBaseBotGuard:
    """Verify /logs is unavailable on the base bot."""

    def test_no_branch_shows_unavailable(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps, branch_name=None)
        with patch.object(bot, "send_message") as mock_send:
            bot._handle_logs_command(42, "on")
            msg = mock_send.call_args[0][1]
            assert "not available" in msg.lower()

    def test_no_branch_does_not_start_streamer(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps, branch_name=None)
        with patch.object(bot, "send_message"):
            bot._handle_logs_command(42, "on")
        assert bot._log_streamer is None

    def test_logs_in_custom_commands_only_for_branch_bots(self, tmp_path, _patch_base_bot_deps):
        branch_bot = _make_bot(tmp_path, _patch_base_bot_deps, branch_name="mybranch")
        assert "logs" in branch_bot.get_custom_commands()

        base_bot = _make_bot(tmp_path, _patch_base_bot_deps, branch_name=None)
        assert "logs" not in base_bot.get_custom_commands()


# =============================================
# 7. PERSISTENCE ROUNDTRIP
# =============================================


class TestLogsPersistence:
    """Verify save + load roundtrip."""

    def test_save_and_load(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        bot._save_logs_preference(42, "default")

        result = bot._load_logs_preference()
        assert result == {"chat_id": 42, "mode": "default"}

    def test_load_returns_none_when_no_file(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        assert bot._load_logs_preference() is None

    def test_load_returns_none_on_corrupt_json(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        pref_file: Path = _patch_base_bot_deps
        pref_file.write_text("not json{{{", encoding="utf-8")

        assert bot._load_logs_preference() is None

    def test_load_returns_none_on_non_dict(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        pref_file: Path = _patch_base_bot_deps
        pref_file.write_text('"just a string"', encoding="utf-8")

        assert bot._load_logs_preference() is None


# =============================================
# 8. AUTO-START HONORS PREFERENCE
# =============================================


class TestAutoStartPreference:
    """Verify handle_update auto-start respects saved preference."""

    def test_autostart_defaults_to_all(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        bot._active_chat_id = None

        with (
            patch.object(bot, "_write_mirror_mapping"),
            patch.object(bot, "is_user_allowed", return_value=True),
            patch.object(bot, "check_rate_limit", return_value=True),
            patch.object(bot, "handle_message"),
            patch("aipass.skills.lib.telegram.apps.handlers.base_bot.LogStreamer") as MockStreamer,
        ):
            MockStreamer.return_value = MagicMock()
            bot.process_update({"message": {"text": "hi", "chat": {"id": 42}, "from": {"id": 111, "username": "u"}}})
            MockStreamer.assert_called_once_with("123:FAKETOKEN", 42, "testbranch", level_filter="all")

    def test_autostart_honors_errors_preference(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        bot._active_chat_id = None
        pref_file: Path = _patch_base_bot_deps
        pref_file.write_text(json.dumps({"chat_id": 42, "mode": "default"}), encoding="utf-8")

        with (
            patch.object(bot, "_write_mirror_mapping"),
            patch.object(bot, "is_user_allowed", return_value=True),
            patch.object(bot, "check_rate_limit", return_value=True),
            patch.object(bot, "handle_message"),
            patch("aipass.skills.lib.telegram.apps.handlers.base_bot.LogStreamer") as MockStreamer,
        ):
            MockStreamer.return_value = MagicMock()
            bot.process_update({"message": {"text": "hi", "chat": {"id": 42}, "from": {"id": 111, "username": "u"}}})
            MockStreamer.assert_called_once_with("123:FAKETOKEN", 42, "testbranch", level_filter="default")

    def test_autostart_skips_when_off(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        bot._active_chat_id = None
        pref_file: Path = _patch_base_bot_deps
        pref_file.write_text(json.dumps({"chat_id": 42, "mode": "off"}), encoding="utf-8")

        with (
            patch.object(bot, "_write_mirror_mapping"),
            patch.object(bot, "is_user_allowed", return_value=True),
            patch.object(bot, "check_rate_limit", return_value=True),
            patch.object(bot, "handle_message"),
            patch("aipass.skills.lib.telegram.apps.handlers.base_bot.LogStreamer") as MockStreamer,
        ):
            bot.process_update({"message": {"text": "hi", "chat": {"id": 42}, "from": {"id": 111, "username": "u"}}})
            MockStreamer.assert_not_called()
            assert bot._log_streamer is None
