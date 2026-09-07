# =================== AIPass ====================
# Name: test_multi_bot.py
# Description: Comprehensive tests for BaseBot and BranchPlugin
# Version: 1.0.0
# Created: 2026-06-15
# Modified: 2026-06-29
# =============================================

"""
Comprehensive pytest tests for BaseBot and BranchPlugin.

Tests cover:
  - BaseBot initialization and attribute assignment
  - Default hook methods (on_message, on_response)
  - Security: is_user_allowed (allowlist), check_rate_limit (sliding window)
  - BranchPlugin hook overrides (message prefixing, response tagging)
  - Pending file creation and JSON content
  - Heartbeat thread (elapsed-time edits via mocked edit_message)
  - verify_connection (mocked urllib success/failure)
  - send_message / edit_message API wrappers (mocked urllib)
  - ensure_tmux_session (mocked subprocess)
  - inject_message (mocked subprocess send-keys)

All network (urllib) and process (subprocess) calls are mocked.
No real Telegram API or tmux interaction occurs.
"""

from pathlib import Path

import json
import os
import time
import pytest
from unittest.mock import patch, MagicMock

from aipass.skills.lib.telegram.apps.handlers.base_bot import BaseBot
from aipass.skills.lib.telegram.apps.handlers.branch_plugin import BranchPlugin


# =============================================
# FIXTURES
# =============================================


@pytest.fixture
def base_bot(tmp_path):
    """Create a BaseBot instance with PENDING_DIR pointed at tmp_path."""
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    with patch("aipass.skills.lib.telegram.apps.handlers.base_bot.PENDING_DIR", tmp_path):
        bot = BaseBot(
            bot_id="test_bot",
            bot_token="123:FAKETOKEN",
            work_dir=workdir,
            bot_name="Test Bot",
            allowed_user_ids=[111, 222],
        )
        # Override pending_file to use the patched tmp_path directory
        bot.pending_file = tmp_path / "bot-test_bot.json"
    return bot


@pytest.fixture
def base_bot_open(tmp_path):
    """Create a BaseBot with an empty allowlist (allows everyone)."""
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    with patch("aipass.skills.lib.telegram.apps.handlers.base_bot.PENDING_DIR", tmp_path):
        bot = BaseBot(
            bot_id="open_bot",
            bot_token="456:FAKETOKEN",
            work_dir=workdir,
            bot_name="Open Bot",
            allowed_user_ids=[],
        )
        bot.pending_file = tmp_path / "bot-open_bot.json"
    return bot


@pytest.fixture
def branch_bot(tmp_path):
    """Create a BranchPlugin instance."""
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    with patch("aipass.skills.lib.telegram.apps.handlers.base_bot.PENDING_DIR", tmp_path):
        bot = BranchPlugin(
            branch_name="dev_central",
            bot_id="dev_central",
            bot_token="789:FAKETOKEN",
            work_dir=workdir,
            bot_name="AIPass Dev Central Bot",
            allowed_user_ids=[111],
        )
        bot.pending_file = tmp_path / "bot-dev_central.json"
    return bot


# =============================================
# 1. BaseBot INITIALIZATION
# =============================================


class TestBaseBotInit:
    """Test that BaseBot.__init__ sets all attributes correctly."""

    def test_bot_id(self, base_bot):
        assert base_bot.bot_id == "test_bot"

    def test_bot_token(self, base_bot):
        assert base_bot.bot_token == "123:FAKETOKEN"

    def test_work_dir_is_path(self, base_bot, tmp_path):
        assert base_bot.work_dir == tmp_path / "workdir"
        assert isinstance(base_bot.work_dir, Path)

    def test_bot_name(self, base_bot):
        assert base_bot.bot_name == "Test Bot"

    def test_allowed_user_ids(self, base_bot):
        assert base_bot.allowed_user_ids == [111, 222]

    def test_session_name(self, base_bot):
        assert base_bot.session_name == "telegram-test_bot"

    def test_state_defaults(self, base_bot):
        assert base_bot.state["running"] is True
        assert base_bot.state["message_count"] == 0
        assert isinstance(base_bot.state["start_time"], float)
        assert base_bot.state["last_message_time"] == 0.0

    def test_health_defaults(self, base_bot):
        assert base_bot._health["started_at"] is None
        assert base_bot._health["messages_received"] == 0
        assert base_bot._health["messages_failed"] == 0
        assert base_bot._health["errors"] == 0

    def test_rate_limit_tracker_empty(self, base_bot):
        assert base_bot._rate_limit_tracker == {}

    def test_custom_commands_default_empty(self, base_bot):
        assert base_bot.custom_commands == {}

    def test_custom_commands_set(self, tmp_path):
        with patch("aipass.skills.lib.telegram.apps.handlers.base_bot.PENDING_DIR", tmp_path):
            bot = BaseBot(
                bot_id="cmd_bot",
                bot_token="t",
                work_dir=tmp_path,
                custom_commands={"ping": "Pong!"},
            )
        assert bot.custom_commands == {"ping": "Pong!"}

    def test_allowed_user_ids_none_becomes_empty_list(self, tmp_path):
        with patch("aipass.skills.lib.telegram.apps.handlers.base_bot.PENDING_DIR", tmp_path):
            bot = BaseBot(
                bot_id="none_bot",
                bot_token="t",
                work_dir=tmp_path,
                allowed_user_ids=None,
            )
        assert bot.allowed_user_ids == []


# =============================================
# 2. BaseBot DEFAULT HOOKS
# =============================================


class TestBaseBotHooks:
    """Test default hook methods return values unchanged."""

    def test_on_message_returns_text_unchanged(self, base_bot):
        assert base_bot.on_message("hello world") == "hello world"

    def test_on_message_empty_string(self, base_bot):
        assert base_bot.on_message("") == ""

    def test_on_response_returns_text_unchanged(self, base_bot):
        assert base_bot.on_response("some response") == "some response"

    def test_on_response_empty_string(self, base_bot):
        assert base_bot.on_response("") == ""

    def test_get_custom_commands_returns_create_and_cancel(self, base_bot):
        commands = base_bot.get_custom_commands()
        assert "create" in commands
        assert "cancel" in commands


# =============================================
# 3. SECURITY: is_user_allowed
# =============================================


class TestIsUserAllowed:
    """Test allowlist logic: empty list allows all, populated list checks membership."""

    def test_allowed_user_passes(self, base_bot):
        assert base_bot.is_user_allowed(111) is True

    def test_allowed_user_second_id(self, base_bot):
        assert base_bot.is_user_allowed(222) is True

    def test_disallowed_user_blocked(self, base_bot):
        assert base_bot.is_user_allowed(999) is False

    def test_empty_allowlist_allows_all(self, base_bot_open):
        assert base_bot_open.is_user_allowed(999) is True
        assert base_bot_open.is_user_allowed(0) is True

    def test_zero_user_id_not_in_list(self, base_bot):
        assert base_bot.is_user_allowed(0) is False


# =============================================
# 4. SECURITY: check_rate_limit
# =============================================


class TestCheckRateLimit:
    """Test sliding-window rate limiting."""

    def test_first_message_allowed(self, base_bot):
        assert base_bot.check_rate_limit(111) is True

    def test_within_limit_allowed(self, base_bot):
        user_id = 111
        for _ in range(5):
            base_bot.check_rate_limit(user_id)
        # After 5 messages (RATE_LIMIT_MESSAGES=5), the 6th should be blocked
        # But first 5 should have returned True on every call
        # Reset and verify
        base_bot._rate_limit_tracker = {}
        results = [base_bot.check_rate_limit(user_id) for _ in range(5)]
        assert all(results)

    def test_exceeds_limit_blocked(self, base_bot):
        user_id = 111
        base_bot._rate_limit_tracker = {}
        # Send exactly RATE_LIMIT_MESSAGES (5)
        for _ in range(5):
            base_bot.check_rate_limit(user_id)
        # 6th message should be blocked
        assert base_bot.check_rate_limit(user_id) is False

    def test_rate_limit_stores_timestamps(self, base_bot):
        user_id = 333
        base_bot.check_rate_limit(user_id)
        assert user_id in base_bot._rate_limit_tracker
        assert len(base_bot._rate_limit_tracker[user_id]) == 1
        assert isinstance(base_bot._rate_limit_tracker[user_id][0], float)

    def test_old_timestamps_pruned(self, base_bot):
        user_id = 444
        # Inject timestamps from 120 seconds ago (outside RATE_LIMIT_WINDOW of 60s)
        old_time = time.time() - 120
        base_bot._rate_limit_tracker[user_id] = [old_time] * 5
        # Should be allowed because old timestamps are pruned
        assert base_bot.check_rate_limit(user_id) is True
        # Old timestamps should be gone, only the new one remains
        assert len(base_bot._rate_limit_tracker[user_id]) == 1

    def test_different_users_independent(self, base_bot):
        base_bot._rate_limit_tracker = {}
        # Fill up user 555
        for _ in range(5):
            base_bot.check_rate_limit(555)
        # User 555 is rate-limited
        assert base_bot.check_rate_limit(555) is False
        # User 666 is unaffected
        assert base_bot.check_rate_limit(666) is True


# =============================================
# 5. BranchPlugin HOOKS
# =============================================


class TestBranchPluginHooks:
    """Test BranchPlugin hook overrides."""

    def test_branch_name_set(self, branch_bot):
        assert branch_bot.branch_name == "dev_central"

    def test_on_message_prefixes_text(self, branch_bot):
        result = branch_bot.on_message("deploy the fix")
        assert result == "User via Telegram: deploy the fix"

    def test_on_message_empty_text(self, branch_bot):
        result = branch_bot.on_message("")
        assert result == "User via Telegram: "

    def test_on_response_tags_with_branch(self, branch_bot):
        result = branch_bot.on_response("Done. Everything is deployed.")
        assert result == "@dev_central\nDone. Everything is deployed."

    def test_on_response_empty_text(self, branch_bot):
        result = branch_bot.on_response("")
        assert result == "@dev_central\n"

    def test_on_response_multiline(self, branch_bot):
        response = "Line 1\nLine 2\nLine 3"
        result = branch_bot.on_response(response)
        assert result == f"@dev_central\n{response}"

    def test_branch_plugin_inherits_base_bot(self, branch_bot):
        assert isinstance(branch_bot, BaseBot)
        assert branch_bot.bot_id == "dev_central"
        assert branch_bot.session_name == "telegram-dev_central"


# =============================================
# 6. PENDING FILE (write_pending_file)
# =============================================


class TestWritePendingFile:
    """Test pending file creation with correct JSON content."""

    def test_write_creates_file(self, base_bot, tmp_path):
        with patch("aipass.skills.lib.telegram.apps.handlers.base_bot.PENDING_DIR", tmp_path):
            with patch.object(base_bot, "_get_transcript_line_count", return_value=42):
                result = base_bot.write_pending_file(chat_id=12345, message_id=100, processing_message_id=101)
        assert result is True
        assert base_bot.pending_file.exists()

    def test_write_correct_json_content(self, base_bot, tmp_path):
        with patch("aipass.skills.lib.telegram.apps.handlers.base_bot.PENDING_DIR", tmp_path):
            with patch.object(base_bot, "_get_transcript_line_count", return_value=10):
                base_bot.write_pending_file(chat_id=12345, message_id=100, processing_message_id=101)
        data = json.loads(base_bot.pending_file.read_text())
        assert data["chat_id"] == 12345
        assert data["message_id"] == 100
        assert data["bot_token"] == "123:FAKETOKEN"
        assert data["bot_id"] == "test_bot"
        assert data["session_name"] == "telegram-test_bot"
        assert data["processing_message_id"] == 101
        assert data["transcript_line_after"] == 10
        assert isinstance(data["timestamp"], float)

    def test_write_with_none_processing_id(self, base_bot, tmp_path):
        with patch("aipass.skills.lib.telegram.apps.handlers.base_bot.PENDING_DIR", tmp_path):
            with patch.object(base_bot, "_get_transcript_line_count", return_value=0):
                base_bot.write_pending_file(chat_id=12345, message_id=100, processing_message_id=None)
        data = json.loads(base_bot.pending_file.read_text())
        assert data["processing_message_id"] is None

    def test_write_includes_work_dir(self, base_bot, tmp_path):
        with patch("aipass.skills.lib.telegram.apps.handlers.base_bot.PENDING_DIR", tmp_path):
            with patch.object(base_bot, "_get_transcript_line_count", return_value=0):
                base_bot.write_pending_file(chat_id=1, message_id=1)
        data = json.loads(base_bot.pending_file.read_text())
        assert data["work_dir"] == str(base_bot.work_dir)


# =============================================
# 7. HEARTBEAT THREAD
# =============================================


class TestHeartbeat:
    """Test heartbeat thread updates the processing message with elapsed time."""

    @patch("aipass.skills.lib.telegram.apps.handlers.base_bot.HEARTBEAT_INTERVAL", 0.1)
    def test_heartbeat_calls_edit_message(self, base_bot, tmp_path):
        """Verify heartbeat updates the message with elapsed time text."""
        # Create the pending file so heartbeat doesn't exit early
        base_bot.pending_file.write_text("{}")

        with patch.object(base_bot, "edit_message") as mock_edit:
            with patch.object(base_bot, "_tmux_session_exists", return_value=True):
                base_bot._start_heartbeat(chat_id=12345, processing_msg_id=101)

                # Wait enough for at least one heartbeat cycle
                time.sleep(0.35)

                base_bot._stop_heartbeat()

        # Should have been called at least once
        assert mock_edit.call_count >= 1
        # Check the call arguments: (chat_id, msg_id, text_with_elapsed)
        first_call = mock_edit.call_args_list[0]
        assert first_call[0][0] == 12345  # chat_id
        assert first_call[0][1] == 101  # message_id
        assert "Processing..." in first_call[0][2]

    def test_stop_heartbeat_without_start(self, base_bot):
        """Stopping heartbeat without starting should not raise."""
        base_bot._stop_heartbeat()  # Should be a no-op

    def test_format_elapsed_seconds(self):
        assert BaseBot._format_elapsed(30) == "30s"
        assert BaseBot._format_elapsed(0) == "0s"
        assert BaseBot._format_elapsed(59) == "59s"

    def test_format_elapsed_minutes(self):
        assert BaseBot._format_elapsed(60) == "1m 0s"
        assert BaseBot._format_elapsed(90) == "1m 30s"
        assert BaseBot._format_elapsed(150) == "2m 30s"


# =============================================
# 8. verify_connection (MOCKED URLLIB)
# =============================================


class TestVerifyConnection:
    """Test verify_connection with mocked urllib responses."""

    def _make_mock_response(self, data_dict):
        """Create a mock urllib response that behaves as a context manager."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(data_dict).encode("utf-8")
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        return mock_resp

    @patch("aipass.skills.lib.telegram.apps.handlers.base_bot.urlopen")
    def test_verify_success(self, mock_urlopen, base_bot):
        mock_urlopen.return_value = self._make_mock_response({"ok": True, "result": {"username": "test_bot"}})
        assert base_bot.verify_connection() is True
        mock_urlopen.assert_called_once()

    @patch("aipass.skills.lib.telegram.apps.handlers.base_bot.urlopen")
    def test_verify_api_rejected(self, mock_urlopen, base_bot):
        mock_urlopen.return_value = self._make_mock_response({"ok": False, "description": "Unauthorized"})
        assert base_bot.verify_connection() is False

    @patch("aipass.skills.lib.telegram.apps.handlers.base_bot.urlopen")
    def test_verify_network_error(self, mock_urlopen, base_bot):
        from urllib.error import URLError

        mock_urlopen.side_effect = URLError("Connection refused")
        assert base_bot.verify_connection() is False

    @patch("aipass.skills.lib.telegram.apps.handlers.base_bot.urlopen")
    def test_verify_unexpected_exception(self, mock_urlopen, base_bot):
        mock_urlopen.side_effect = RuntimeError("unexpected")
        assert base_bot.verify_connection() is False

    @patch("aipass.skills.lib.telegram.apps.handlers.base_bot.urlopen")
    def test_verify_uses_correct_url(self, mock_urlopen, base_bot):
        mock_urlopen.return_value = self._make_mock_response({"ok": True, "result": {"username": "test_bot"}})
        base_bot.verify_connection()
        called_request = mock_urlopen.call_args[0][0]
        assert "123:FAKETOKEN" in called_request.full_url
        assert "getMe" in called_request.full_url


# =============================================
# 9. send_message / edit_message (MOCKED URLLIB)
# =============================================


class TestSendMessage:
    """Test send_message API wrapper."""

    def _make_mock_response(self, data_dict):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(data_dict).encode("utf-8")
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        return mock_resp

    @patch("aipass.skills.lib.telegram.apps.handlers.base_bot.urlopen")
    def test_send_success(self, mock_urlopen, base_bot):
        mock_urlopen.return_value = self._make_mock_response({"ok": True, "result": {"message_id": 42}})
        result = base_bot.send_message(12345, "Hello!")
        assert result == {"message_id": 42}

    @patch("aipass.skills.lib.telegram.apps.handlers.base_bot.urlopen")
    def test_send_returns_none_on_failure(self, mock_urlopen, base_bot):
        mock_urlopen.side_effect = RuntimeError("fail")
        result = base_bot.send_message(12345, "Hello!")
        assert result is None

    @patch("aipass.skills.lib.telegram.apps.handlers.base_bot.urlopen")
    def test_send_retries_on_failure(self, mock_urlopen, base_bot):
        """send_message retries up to 3 times."""
        mock_urlopen.side_effect = RuntimeError("fail")
        with patch("aipass.skills.lib.telegram.apps.handlers.base_bot.time.sleep"):
            base_bot.send_message(12345, "Hello!")
        assert mock_urlopen.call_count == 3

    @patch("aipass.skills.lib.telegram.apps.handlers.base_bot.urlopen")
    def test_send_with_reply_to(self, mock_urlopen, base_bot):
        mock_urlopen.return_value = self._make_mock_response({"ok": True, "result": {"message_id": 43}})
        result = base_bot.send_message(12345, "reply", reply_to=10)
        assert result == {"message_id": 43}
        # Verify the payload included reply_to_message_id
        sent_data = json.loads(mock_urlopen.call_args[0][0].data.decode("utf-8"))
        assert sent_data["reply_to_message_id"] == 10

    @patch("aipass.skills.lib.telegram.apps.handlers.base_bot.urlopen")
    def test_send_uses_correct_url(self, mock_urlopen, base_bot):
        mock_urlopen.return_value = self._make_mock_response({"ok": True, "result": {"message_id": 1}})
        base_bot.send_message(12345, "test")
        called_request = mock_urlopen.call_args[0][0]
        assert "sendMessage" in called_request.full_url
        assert "123:FAKETOKEN" in called_request.full_url


class TestEditMessage:
    """Test edit_message API wrapper."""

    def _make_mock_response(self, data_dict):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(data_dict).encode("utf-8")
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        return mock_resp

    @patch("aipass.skills.lib.telegram.apps.handlers.base_bot.urlopen")
    def test_edit_success(self, mock_urlopen, base_bot):
        mock_urlopen.return_value = self._make_mock_response({"ok": True})
        result = base_bot.edit_message(12345, 42, "Updated text")
        assert result is True

    @patch("aipass.skills.lib.telegram.apps.handlers.base_bot.urlopen")
    def test_edit_failure(self, mock_urlopen, base_bot):
        mock_urlopen.return_value = self._make_mock_response({"ok": False, "description": "Message not modified"})
        result = base_bot.edit_message(12345, 42, "Same text")
        assert result is False

    @patch("aipass.skills.lib.telegram.apps.handlers.base_bot.urlopen")
    def test_edit_exception(self, mock_urlopen, base_bot):
        mock_urlopen.side_effect = RuntimeError("network error")
        result = base_bot.edit_message(12345, 42, "text")
        assert result is False

    @patch("aipass.skills.lib.telegram.apps.handlers.base_bot.urlopen")
    def test_edit_sends_correct_payload(self, mock_urlopen, base_bot):
        mock_urlopen.return_value = self._make_mock_response({"ok": True})
        base_bot.edit_message(12345, 42, "new text")
        sent_data = json.loads(mock_urlopen.call_args[0][0].data.decode("utf-8"))
        assert sent_data["chat_id"] == 12345
        assert sent_data["message_id"] == 42
        assert sent_data["text"] == "new text"

    @patch("aipass.skills.lib.telegram.apps.handlers.base_bot.urlopen")
    def test_edit_uses_correct_url(self, mock_urlopen, base_bot):
        mock_urlopen.return_value = self._make_mock_response({"ok": True})
        base_bot.edit_message(12345, 42, "x")
        called_request = mock_urlopen.call_args[0][0]
        assert "editMessageText" in called_request.full_url


# =============================================
# 10. ensure_tmux_session (MOCKED SUBPROCESS)
# =============================================


class TestEnsureTmuxSession:
    """Test tmux session creation with mocked subprocess."""

    @patch("aipass.skills.lib.telegram.apps.handlers.base_bot.time.sleep")
    @patch("aipass.skills.lib.telegram.apps.handlers.base_bot.subprocess.run")
    def test_session_exists_returns_true(self, mock_run, mock_sleep, base_bot):
        """If tmux session already exists, return True without creating."""
        # has-session returns 0 (session exists)
        mock_run.return_value = MagicMock(returncode=0)
        result = base_bot.ensure_tmux_session()
        assert result is True
        # Only has-session should have been called
        mock_run.assert_called_once()
        assert "has-session" in mock_run.call_args[0][0]

    @patch("aipass.skills.lib.telegram.apps.handlers.base_bot.time.sleep")
    @patch("aipass.skills.lib.telegram.apps.handlers.base_bot.subprocess.run")
    def test_no_session_returns_false(self, mock_run, mock_sleep, base_bot):
        """When no session exists, bot returns False (never spawns own brain)."""
        mock_run.return_value = MagicMock(returncode=1)

        result = base_bot.ensure_tmux_session()
        assert result is False
        calls = [str(c) for c in mock_run.call_args_list]
        for call in calls:
            assert "new-session" not in call

    def test_session_refuses_nonexistent_work_dir(self, tmp_path):
        """When work_dir doesn't exist, ensure_tmux_session returns False."""
        bad_dir = tmp_path / "nonexistent"
        with patch("aipass.skills.lib.telegram.apps.handlers.base_bot.PENDING_DIR", tmp_path):
            bot = BaseBot(
                bot_id="bad_dir_bot",
                bot_token="t",
                work_dir=bad_dir,
            )
        result = bot.ensure_tmux_session()
        assert result is False

    def test_tmux_not_found_returns_false(self, base_bot):
        """FileNotFoundError (tmux not installed) returns False."""
        with patch(
            "aipass.skills.lib.telegram.apps.handlers.base_bot.subprocess.run", side_effect=FileNotFoundError("tmux")
        ):
            result = base_bot.ensure_tmux_session()
        assert result is False


# =============================================
# 11. inject_message (MOCKED SUBPROCESS)
# =============================================


class TestInjectMessage:
    """Test tmux send-keys injection with mocked subprocess."""

    @patch("aipass.skills.lib.telegram.apps.handlers.base_bot.time.sleep")
    @patch("aipass.skills.lib.telegram.apps.handlers.base_bot.subprocess.run")
    def test_inject_success(self, mock_run, mock_sleep, base_bot):
        mock_run.return_value = MagicMock(returncode=0)
        result = base_bot.inject_message("hello world")
        assert result is True

    @patch("aipass.skills.lib.telegram.apps.handlers.base_bot.time.sleep")
    @patch("aipass.skills.lib.telegram.apps.handlers.base_bot.subprocess.run")
    def test_inject_calls_send_keys_with_text_then_enter(self, mock_run, mock_sleep, base_bot):
        mock_run.return_value = MagicMock(returncode=0)
        base_bot.inject_message("test message")

        # Should be called twice: once for text (-l), once for Enter
        assert mock_run.call_count == 2

        # First call: send-keys with -l and text
        first_cmd = mock_run.call_args_list[0][0][0]
        assert "send-keys" in first_cmd
        assert "-l" in first_cmd
        assert "test message" in first_cmd

        # Second call: send-keys with Enter
        second_cmd = mock_run.call_args_list[1][0][0]
        assert "send-keys" in second_cmd
        assert "Enter" in second_cmd

    @patch("aipass.skills.lib.telegram.apps.handlers.base_bot.time.sleep")
    @patch("aipass.skills.lib.telegram.apps.handlers.base_bot.subprocess.run")
    def test_inject_uses_correct_session_name(self, mock_run, mock_sleep, base_bot):
        mock_run.return_value = MagicMock(returncode=0)
        base_bot.inject_message("x")
        first_cmd = mock_run.call_args_list[0][0][0]
        assert base_bot.session_name in first_cmd

    @patch("aipass.skills.lib.telegram.apps.handlers.base_bot.time.sleep")
    @patch("aipass.skills.lib.telegram.apps.handlers.base_bot.subprocess.run")
    def test_inject_failure(self, mock_run, mock_sleep, base_bot):
        import subprocess as sp

        mock_run.side_effect = sp.CalledProcessError(1, ["tmux"], stderr=b"error")
        result = base_bot.inject_message("hello")
        assert result is False

    @patch("aipass.skills.lib.telegram.apps.handlers.base_bot.time.sleep")
    @patch("aipass.skills.lib.telegram.apps.handlers.base_bot.subprocess.run")
    def test_inject_sleeps_between_commands(self, mock_run, mock_sleep, base_bot):
        """Verify there's a delay between sending text and pressing Enter."""
        mock_run.return_value = MagicMock(returncode=0)
        base_bot.inject_message("test")
        # sleep is called once with SEND_KEYS_DELAY between send-keys calls
        mock_sleep.assert_called()


# =============================================
# 12. poll_updates (MOCKED URLLIB)
# =============================================


class TestPollUpdates:
    """Test long-polling getUpdates."""

    def _make_mock_response(self, data_dict):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(data_dict).encode("utf-8")
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        return mock_resp

    @patch("aipass.skills.lib.telegram.apps.handlers.base_bot.urlopen")
    def test_poll_returns_updates(self, mock_urlopen, base_bot):
        updates = [{"update_id": 1, "message": {"text": "hi"}}]
        mock_urlopen.return_value = self._make_mock_response({"ok": True, "result": updates})
        result = base_bot.poll_updates(0)
        assert result == updates

    @patch("aipass.skills.lib.telegram.apps.handlers.base_bot.urlopen")
    def test_poll_returns_empty_on_error(self, mock_urlopen, base_bot):
        mock_urlopen.return_value = self._make_mock_response({"ok": False, "description": "Bad Request"})
        result = base_bot.poll_updates(0)
        assert result == []

    @patch("aipass.skills.lib.telegram.apps.handlers.base_bot.urlopen")
    def test_poll_returns_empty_on_exception(self, mock_urlopen, base_bot):
        from urllib.error import URLError

        mock_urlopen.side_effect = URLError("timeout")
        result = base_bot.poll_updates(0)
        assert result == []

    @patch("aipass.skills.lib.telegram.apps.handlers.base_bot.urlopen")
    def test_poll_includes_offset_in_url(self, mock_urlopen, base_bot):
        mock_urlopen.return_value = self._make_mock_response({"ok": True, "result": []})
        base_bot.poll_updates(42)
        called_request = mock_urlopen.call_args[0][0]
        assert "offset=42" in called_request.full_url


# =============================================
# 13. TEXT CHUNKING
# =============================================


class TestChunkText:
    """Test text chunking for Telegram's 4096 char limit."""

    def test_short_text_single_chunk(self, base_bot):
        result = base_bot.chunk_text("Hello world")
        assert result == ["Hello world"]

    def test_exactly_at_limit(self, base_bot):
        text = "a" * 4096
        result = base_bot.chunk_text(text)
        assert len(result) == 1

    def test_over_limit_splits(self, base_bot):
        text = "a" * 5000
        result = base_bot.chunk_text(text)
        assert len(result) >= 2
        # Reassembled should cover all characters
        total_len = sum(len(c) for c in result)
        assert total_len == 5000

    def test_custom_limit(self, base_bot):
        text = "hello world this is a test"
        result = base_bot.chunk_text(text, limit=10)
        assert len(result) >= 2
        for chunk in result:
            assert len(chunk) <= 10


# =============================================
# 14. process_update ROUTING
# =============================================


class TestProcessUpdate:
    """Test update routing in process_update."""

    def test_no_message_key_returns_early(self, base_bot):
        """Updates without a 'message' key are silently ignored."""
        base_bot.process_update({"update_id": 1})
        # No error raised

    def test_blocked_user_not_processed(self, base_bot):
        """Messages from unauthorized users are dropped."""
        update = {
            "update_id": 1,
            "message": {
                "text": "hello",
                "chat": {"id": 1},
                "from": {"id": 999, "username": "hacker"},
                "message_id": 1,
            },
        }
        with patch.object(base_bot, "handle_message") as mock_handle:
            base_bot.process_update(update)
            mock_handle.assert_not_called()

    def test_allowed_user_message_handled(self, base_bot):
        """Messages from allowed users are routed to handle_message."""
        update = {
            "update_id": 1,
            "message": {
                "text": "do something",
                "chat": {"id": 1},
                "from": {"id": 111, "username": "testuser"},
                "message_id": 1,
            },
        }
        with patch.object(base_bot, "handle_message") as mock_handle:
            with patch("aipass.skills.lib.telegram.apps.handlers.base_bot.parse_command", return_value=None):
                base_bot.process_update(update)
                mock_handle.assert_called_once()

    def test_rate_limited_user_gets_rejection(self, base_bot):
        """Rate-limited users get a rejection message."""
        with patch.object(base_bot, "check_rate_limit", return_value=False):
            with patch.object(base_bot, "send_message") as mock_send:
                update = {
                    "update_id": 1,
                    "message": {
                        "text": "hello",
                        "chat": {"id": 1},
                        "from": {"id": 111, "username": "testuser"},
                        "message_id": 1,
                    },
                }
                base_bot.process_update(update)
                mock_send.assert_called_once()
                assert "Rate limit" in mock_send.call_args[0][1]


# =============================================
# 15. LOCK FILE MANAGEMENT
# =============================================


class TestLockFile:
    """Test lock file creation, checking, and removal."""

    def test_create_lock_writes_file(self, base_bot, tmp_path):
        base_bot._lock_file = tmp_path / ".test_bot.lock"
        base_bot._create_lock()
        assert base_bot._lock_file.exists()
        data = json.loads(base_bot._lock_file.read_text())
        assert "pid" in data
        assert data["bot_id"] == "test_bot"

    def test_remove_lock_deletes_file(self, base_bot, tmp_path):
        base_bot._lock_file = tmp_path / ".test_bot.lock"
        base_bot._lock_file.write_text("{}")
        base_bot._remove_lock()
        assert not base_bot._lock_file.exists()

    def test_check_lock_no_file_returns_false(self, base_bot, tmp_path):
        base_bot._lock_file = tmp_path / ".nonexistent.lock"
        assert base_bot._check_lock() is False

    def test_check_lock_stale_pid_returns_false(self, base_bot, tmp_path):
        """A lock with a dead PID should be treated as stale."""
        base_bot._lock_file = tmp_path / ".test_bot.lock"
        base_bot._lock_file.write_text(json.dumps({"pid": 99999999}))
        # PID 99999999 almost certainly doesn't exist
        assert base_bot._check_lock() is False


# =============================================
# 16. OFFSET PERSISTENCE
# =============================================


class TestOffsetPersistence:
    """Test offset load and save."""

    def test_load_offset_no_file(self, base_bot, tmp_path):
        base_bot._offset_file = tmp_path / "nonexistent_offset.json"
        assert base_bot._load_offset() == 0

    def test_save_and_load_offset(self, base_bot, tmp_path):
        base_bot._offset_file = tmp_path / "offset.json"
        base_bot._save_offset(42)
        assert base_bot._load_offset() == 42

    def test_load_corrupt_offset_returns_zero(self, base_bot, tmp_path):
        base_bot._offset_file = tmp_path / "offset.json"
        base_bot._offset_file.write_text("not json!!!")
        assert base_bot._load_offset() == 0


# =============================================
# 17. SHUTDOWN HANDLER
# =============================================


class TestShutdown:
    """Test signal handling and cleanup."""

    def test_shutdown_handler_sets_running_false(self, base_bot):
        import signal

        base_bot._shutdown_handler(signal.SIGTERM, None)
        assert base_bot.state["running"] is False

    def test_cleanup_removes_lock_and_stops_heartbeat(self, base_bot, tmp_path):
        base_bot._lock_file = tmp_path / ".test_bot.lock"
        base_bot._lock_file.write_text("{}")
        base_bot._cleanup()
        assert not base_bot._lock_file.exists()


# =============================================
# 18. /create COMMAND (Step 1: branch validation)
# =============================================


class TestCreateCommand:
    """Test _handle_create_command: branch validation, state setup, error handling."""

    @pytest.fixture(autouse=True)
    def setup_bot(self, tmp_path):
        with patch("aipass.skills.lib.telegram.apps.handlers.base_bot.PENDING_DIR", tmp_path):
            self.bot = BaseBot(
                bot_id="test",
                bot_token="123:FAKE",
                work_dir=tmp_path,
                bot_name="Test Bot",
                allowed_user_ids=[],
            )
        self.bot.send_message = MagicMock(return_value={"message_id": 42})
        self.chat_id = 12345

    @patch(
        "aipass.skills.lib.telegram.apps.handlers.base_bot.check_telethon_setup", return_value=(False, "not configured")
    )
    @patch("aipass.skills.lib.telegram.apps.handlers.base_bot.get_bot_by_branch", return_value=None)
    @patch("aipass.skills.lib.telegram.apps.handlers.base_bot.validate_branch")
    def test_create_valid_branch(self, mock_validate, mock_get_bot, mock_telethon):
        mock_validate.return_value = {"name": "dev_central", "path": "/home/aipass/dev_central"}
        self.bot._handle_create_command(self.chat_id, "chat dev_central")
        assert self.chat_id in self.bot._create_state
        self.bot.send_message.assert_called_once()  # type: ignore[union-attr]
        msg = self.bot.send_message.call_args[0][1]  # type: ignore[union-attr]
        assert "dev_central" in msg
        assert "token" in msg.lower()

    def test_create_missing_args(self):
        self.bot._handle_create_command(self.chat_id, "")
        self.bot.send_message.assert_called_once()  # type: ignore[union-attr]
        msg = self.bot.send_message.call_args[0][1]  # type: ignore[union-attr]
        assert "Usage" in msg

    def test_create_invalid_format(self):
        self.bot._handle_create_command(self.chat_id, "foo bar")
        self.bot.send_message.assert_called_once()  # type: ignore[union-attr]
        msg = self.bot.send_message.call_args[0][1]  # type: ignore[union-attr]
        assert "Usage" in msg

    @patch("aipass.skills.lib.telegram.apps.handlers.base_bot.validate_branch", return_value=None)
    def test_create_branch_not_found(self, mock_validate):
        self.bot._handle_create_command(self.chat_id, "chat nonexistent")
        self.bot.send_message.assert_called_once()  # type: ignore[union-attr]
        msg = self.bot.send_message.call_args[0][1]  # type: ignore[union-attr]
        assert "not found" in msg

    @patch("aipass.skills.lib.telegram.apps.handlers.base_bot.get_bot_by_branch")
    @patch("aipass.skills.lib.telegram.apps.handlers.base_bot.validate_branch")
    def test_create_branch_already_has_bot(self, mock_validate, mock_get_bot):
        mock_validate.return_value = {"name": "dev_central", "path": "/tmp"}
        mock_get_bot.return_value = {"bot_id": "dev_central", "username": "dc_bot"}
        self.bot._handle_create_command(self.chat_id, "chat dev_central")
        self.bot.send_message.assert_called_once()  # type: ignore[union-attr]
        msg = self.bot.send_message.call_args[0][1]  # type: ignore[union-attr]
        assert "already has a bot" in msg

    @patch("aipass.skills.lib.telegram.apps.handlers.base_bot.get_bot_by_branch", return_value=None)
    @patch("aipass.skills.lib.telegram.apps.handlers.base_bot.validate_branch")
    def test_create_sets_state_with_branch_info(self, mock_validate, mock_get_bot):
        mock_validate.return_value = {"name": "flow", "path": "/home/aipass/flow"}
        self.bot._handle_create_command(self.chat_id, "chat @flow")
        state = self.bot._create_state[self.chat_id]
        assert state["branch_name"] == "flow"
        assert state["branch_path"] == "/home/aipass/flow"
        assert "started_at" in state
        assert isinstance(state["started_at"], float)

    def test_create_single_arg_no_branch(self):
        """Calling /create with only 'chat' and no branch name shows usage."""
        self.bot._handle_create_command(self.chat_id, "chat")  # type: ignore[union-attr]
        self.bot.send_message.assert_called_once()  # type: ignore[union-attr]
        msg = self.bot.send_message.call_args[0][1]
        assert "Usage" in msg

    @patch("aipass.skills.lib.telegram.apps.handlers.base_bot.get_bot_by_branch", return_value=None)
    @patch("aipass.skills.lib.telegram.apps.handlers.base_bot.validate_branch")
    def test_create_strips_at_symbol(self, mock_validate, mock_get_bot):
        """Branch name should have @ stripped before lookup."""
        mock_validate.return_value = {"name": "seed", "path": "/home/aipass/seed"}
        self.bot._handle_create_command(self.chat_id, "chat @seed")
        mock_validate.assert_called_once_with("seed")


# =============================================
# 19. /create TOKEN (Step 2: token paste)
# =============================================


class TestCreateToken:
    """Test _handle_create_token: token validation, bot creation, state cleanup."""

    @pytest.fixture(autouse=True)
    def setup_bot(self, tmp_path):
        with patch("aipass.skills.lib.telegram.apps.handlers.base_bot.PENDING_DIR", tmp_path):
            self.bot = BaseBot(
                bot_id="test",
                bot_token="123:FAKE",
                work_dir=tmp_path,
                bot_name="Test Bot",
                allowed_user_ids=[111],
            )
        self.bot.send_message = MagicMock(return_value={"message_id": 42})
        self.chat_id = 12345

    def _set_create_state(self, branch_name="dev_central", branch_path="/tmp/dc", started_at=None):
        """Helper to set up _create_state for this chat."""
        self.bot._create_state[self.chat_id] = {
            "branch_name": branch_name,
            "branch_path": branch_path,
            "started_at": started_at or time.time(),
        }

    @patch("aipass.skills.lib.telegram.apps.handlers.base_bot.create_bot")
    @patch("aipass.skills.lib.telegram.apps.handlers.base_bot.validate_token")
    def test_valid_token_creates_bot(self, mock_validate_token, mock_create_bot):
        self._set_create_state()
        mock_validate_token.return_value = {"username": "my_new_bot"}
        mock_create_bot.return_value = {"bot_id": "dev_central", "status": "created"}
        self.bot._handle_create_token(self.chat_id, "123456789:ABCdefGHIjklMNOpqr")
        # Should have been called
        mock_create_bot.assert_called_once()
        # Last send_message should contain success info # type: ignore[union-attr]
        last_msg = self.bot.send_message.call_args[0][1]
        assert "my_new_bot" in last_msg

    def test_invalid_token_format_no_colon(self):
        self._set_create_state()
        self.bot._handle_create_token(self.chat_id, "shorttoken")  # type: ignore[union-attr]
        msg = self.bot.send_message.call_args[0][1]
        assert "doesn't look like a valid" in msg
        # State should still be present (user can retry)
        assert self.chat_id in self.bot._create_state

    def test_invalid_token_format_too_short(self):
        self._set_create_state()
        self.bot._handle_create_token(self.chat_id, "1:A")  # type: ignore[union-attr]
        msg = self.bot.send_message.call_args[0][1]
        assert "doesn't look like a valid" in msg

    @patch("aipass.skills.lib.telegram.apps.handlers.base_bot.validate_token", return_value=None)
    def test_token_validation_fails(self, mock_validate_token):
        self._set_create_state()
        self.bot._handle_create_token(self.chat_id, "123456789:ABCdefGHIjklMNOpqr")
        mock_validate_token.assert_called_once()  # type: ignore[union-attr]
        msg = self.bot.send_message.call_args[0][1]
        assert "validation failed" in msg.lower()

    @patch("aipass.skills.lib.telegram.apps.handlers.base_bot.create_bot", return_value=None)
    @patch("aipass.skills.lib.telegram.apps.handlers.base_bot.validate_token")
    def test_bot_creation_fails(self, mock_validate_token, mock_create_bot):
        self._set_create_state()
        mock_validate_token.return_value = {"username": "test_bot"}
        self.bot._handle_create_token(self.chat_id, "123456789:ABCdefGHIjklMNOpqr")  # type: ignore[union-attr]
        msg = self.bot.send_message.call_args[0][1]
        assert "failed" in msg.lower()

    def test_state_expires(self):
        """State older than _create_state_ttl should be rejected."""
        old_time = time.time() - 600  # 10 minutes ago, TTL is 300s
        self._set_create_state(started_at=old_time)
        self.bot._handle_create_token(self.chat_id, "123456789:ABCdefGHIjklMNOpqr")  # type: ignore[union-attr]
        msg = self.bot.send_message.call_args[0][1]
        assert "expired" in msg.lower()
        assert self.chat_id not in self.bot._create_state

    @patch("aipass.skills.lib.telegram.apps.handlers.base_bot.create_bot")
    @patch("aipass.skills.lib.telegram.apps.handlers.base_bot.validate_token")
    def test_state_cleared_after_success(self, mock_validate_token, mock_create_bot):
        self._set_create_state()
        mock_validate_token.return_value = {"username": "new_bot"}
        mock_create_bot.return_value = {"bot_id": "dev_central"}
        self.bot._handle_create_token(self.chat_id, "123456789:ABCdefGHIjklMNOpqr")
        assert self.chat_id not in self.bot._create_state

    @patch("aipass.skills.lib.telegram.apps.handlers.base_bot.create_bot", return_value=None)
    @patch("aipass.skills.lib.telegram.apps.handlers.base_bot.validate_token")
    def test_state_cleared_after_failure(self, mock_validate_token, mock_create_bot):
        """State should be cleared even when bot creation fails (after token validated)."""
        self._set_create_state()
        mock_validate_token.return_value = {"username": "test_bot"}
        self.bot._handle_create_token(self.chat_id, "123456789:ABCdefGHIjklMNOpqr")
        # State is cleared before API calls
        assert self.chat_id not in self.bot._create_state


# =============================================
# 20. /cancel COMMAND
# =============================================


class TestCancelCommand:
    """Test /cancel command — cancels active /create flow."""

    @pytest.fixture(autouse=True)
    def setup_bot(self, tmp_path):
        with patch("aipass.skills.lib.telegram.apps.handlers.base_bot.PENDING_DIR", tmp_path):
            self.bot = BaseBot(
                bot_id="test",
                bot_token="123:FAKE",
                work_dir=tmp_path,
                bot_name="Test Bot",
                allowed_user_ids=[],
            )
        self.bot.send_message = MagicMock(return_value={"message_id": 42})
        self.chat_id = 12345

    def test_cancel_active_flow(self):
        self.bot._create_state[self.chat_id] = {
            "branch_name": "flow",
            "branch_path": "/tmp",
            "started_at": time.time(),
        }
        # Simulate process_update handling /cancel
        update = {
            "update_id": 1,
            "message": {
                "text": "/cancel",
                "chat": {"id": self.chat_id},
                "from": {"id": 999, "username": "test"},
                "message_id": 1,
            },
        }
        with patch("aipass.skills.lib.telegram.apps.handlers.base_bot.parse_command", return_value=("cancel", "")):
            self.bot.process_update(update)
        assert self.chat_id not in self.bot._create_state  # type: ignore[union-attr]
        msg = self.bot.send_message.call_args[0][1]
        assert "cancelled" in msg.lower()

    def test_cancel_no_active_flow(self):
        update = {
            "update_id": 1,
            "message": {
                "text": "/cancel",
                "chat": {"id": self.chat_id},
                "from": {"id": 999, "username": "test"},
                "message_id": 1,
            },
        }
        with patch("aipass.skills.lib.telegram.apps.handlers.base_bot.parse_command", return_value=("cancel", "")):
            self.bot.process_update(update)  # type: ignore[union-attr]
        msg = self.bot.send_message.call_args[0][1]
        assert "Nothing to cancel" in msg

    def test_cancel_preserves_other_chat_state(self):
        """Cancelling one chat's flow should not affect another chat."""
        other_chat = 99999
        self.bot._create_state[self.chat_id] = {
            "branch_name": "flow",
            "branch_path": "/tmp",
            "started_at": time.time(),
        }
        self.bot._create_state[other_chat] = {
            "branch_name": "seed",
            "branch_path": "/tmp2",
            "started_at": time.time(),
        }
        update = {
            "update_id": 1,
            "message": {
                "text": "/cancel",
                "chat": {"id": self.chat_id},
                "from": {"id": 999, "username": "test"},
                "message_id": 1,
            },
        }
        with patch("aipass.skills.lib.telegram.apps.handlers.base_bot.parse_command", return_value=("cancel", "")):
            self.bot.process_update(update)
        assert self.chat_id not in self.bot._create_state
        assert other_chat in self.bot._create_state


# =============================================
# 21. /status WITH REGISTRY INFO
# =============================================


class TestStatusWithRegistry:
    """Test /status enhancement with _build_registry_status."""

    @pytest.fixture(autouse=True)
    def setup_bot(self, tmp_path):
        with patch("aipass.skills.lib.telegram.apps.handlers.base_bot.PENDING_DIR", tmp_path):
            self.bot = BaseBot(
                bot_id="test",
                bot_token="123:FAKE",
                work_dir=tmp_path,
                bot_name="Test Bot",
                allowed_user_ids=[],
            )
        self.bot.send_message = MagicMock(return_value={"message_id": 42})
        self.chat_id = 12345

    @patch("aipass.skills.lib.telegram.apps.handlers.base_bot.registry_list_bots")
    def test_status_includes_registry(self, mock_list_bots):
        mock_list_bots.return_value = [
            {"bot_id": "dev_central", "username": "dc_bot", "status": "running", "branch_name": "dev_central"},
            {"bot_id": "flow", "username": "flow_bot", "status": "stopped", "branch_name": "flow"},
        ]
        update = {
            "update_id": 1,
            "message": {
                "text": "/status",
                "chat": {"id": self.chat_id},
                "from": {"id": 999, "username": "test"},
                "message_id": 1,
            },
        }
        with patch("aipass.skills.lib.telegram.apps.handlers.base_bot.parse_command", return_value=("status", "")):
            with patch(
                "aipass.skills.lib.telegram.apps.handlers.base_bot.build_status_text", return_value="Bot Status"
            ):
                self.bot.process_update(update)
        msg = self.bot.send_message.call_args[0][1]
        assert "Registered Bots" in msg
        assert "dc_bot" in msg

    @patch("aipass.skills.lib.telegram.apps.handlers.base_bot.registry_list_bots", return_value=[])
    def test_status_empty_registry(self, mock_list_bots):
        update = {
            "update_id": 1,
            "message": {
                "text": "/status",
                "chat": {"id": self.chat_id},
                "from": {"id": 999, "username": "test"},
                "message_id": 1,
            },
        }
        with patch("aipass.skills.lib.telegram.apps.handlers.base_bot.parse_command", return_value=("status", "")):
            with patch(
                "aipass.skills.lib.telegram.apps.handlers.base_bot.build_status_text", return_value="Bot Status"
            ):
                self.bot.process_update(update)
        msg = self.bot.send_message.call_args[0][1]
        assert "none" in msg.lower()

    @patch("aipass.skills.lib.telegram.apps.handlers.base_bot.registry_list_bots")
    def test_build_registry_status_with_bots(self, mock_list_bots):
        mock_list_bots.return_value = [
            {"bot_id": "seed", "username": "seed_bot", "status": "running", "branch_name": "seed"},
        ]
        result = self.bot._build_registry_status()
        assert "Registered Bots: 1" in result
        assert "seed" in result
        assert "seed_bot" in result
        assert "running" in result

    @patch("aipass.skills.lib.telegram.apps.handlers.base_bot.registry_list_bots")
    def test_build_registry_status_exception(self, mock_list_bots):
        mock_list_bots.side_effect = RuntimeError("DB error")
        result = self.bot._build_registry_status()
        assert result == ""

    @patch("aipass.skills.lib.telegram.apps.handlers.base_bot.registry_list_bots", return_value=[])
    def test_build_registry_status_empty(self, mock_list_bots):
        result = self.bot._build_registry_status()
        assert result == "Registered Bots: none"


# =============================================
# 22. get_custom_commands HOOK
# =============================================


class TestGetCustomCommands:
    """Test that get_custom_commands returns /create and /cancel."""

    @pytest.fixture(autouse=True)
    def setup_bot(self, tmp_path):
        with patch("aipass.skills.lib.telegram.apps.handlers.base_bot.PENDING_DIR", tmp_path):
            self.bot = BaseBot(
                bot_id="test",
                bot_token="123:FAKE",
                work_dir=tmp_path,
                bot_name="Test Bot",
                allowed_user_ids=[],
            )

    def test_custom_commands_include_create(self):
        commands = self.bot.get_custom_commands()
        assert "create" in commands
        assert "description" in commands["create"]

    def test_custom_commands_include_cancel(self):
        commands = self.bot.get_custom_commands()
        assert "cancel" in commands
        assert "description" in commands["cancel"]


# =============================================
# 23. /create FLOW IN process_update ROUTING
# =============================================


class TestCreateFlowInProcessUpdate:
    """Test process_update routing for /create flow, token paste, and /cancel."""

    @pytest.fixture(autouse=True)
    def setup_bot(self, tmp_path):
        with patch("aipass.skills.lib.telegram.apps.handlers.base_bot.PENDING_DIR", tmp_path):
            self.bot = BaseBot(
                bot_id="test",
                bot_token="123:FAKE",
                work_dir=tmp_path,
                bot_name="Test Bot",
                allowed_user_ids=[],
            )
        self.bot.send_message = MagicMock(return_value={"message_id": 42})
        self.chat_id = 12345

    def _make_update(self, text):
        return {
            "update_id": 1,
            "message": {
                "text": text,
                "chat": {"id": self.chat_id},
                "from": {"id": 999, "username": "test"},
                "message_id": 1,
            },
        }

    @patch("aipass.skills.lib.telegram.apps.handlers.base_bot.get_bot_by_branch", return_value=None)
    @patch("aipass.skills.lib.telegram.apps.handlers.base_bot.validate_branch")
    @patch(
        "aipass.skills.lib.telegram.apps.handlers.base_bot.parse_command", return_value=("create", "chat test_branch")
    )
    def test_process_update_create_command_routed(self, mock_parse, mock_validate, mock_get_bot):
        """Sending /create chat test_branch should call _handle_create_command."""
        mock_validate.return_value = {"name": "test_branch", "path": "/tmp"}
        with patch.object(self.bot, "_handle_create_command", wraps=self.bot._handle_create_command) as mock_method:
            self.bot.process_update(self._make_update("/create chat test_branch"))
            mock_method.assert_called_once_with(self.chat_id, "chat test_branch")

    @patch("aipass.skills.lib.telegram.apps.handlers.base_bot.create_bot")
    @patch("aipass.skills.lib.telegram.apps.handlers.base_bot.validate_token")
    def test_process_update_token_paste_during_create_flow(self, mock_validate_token, mock_create_bot):
        """When _create_state is active, non-command text routes to _handle_create_token."""
        self.bot._create_state[self.chat_id] = {
            "branch_name": "dev_central",
            "branch_path": "/tmp",
            "started_at": time.time(),
        }
        mock_validate_token.return_value = {"username": "new_bot"}
        mock_create_bot.return_value = {"bot_id": "dev_central"}
        with patch.object(self.bot, "_handle_create_token", wraps=self.bot._handle_create_token) as mock_method:
            self.bot.process_update(self._make_update("123456789:ABCdefGHIjklMNOpqr"))
            mock_method.assert_called_once_with(self.chat_id, "123456789:ABCdefGHIjklMNOpqr")

    def test_process_update_no_token_paste_without_state(self):
        """Without _create_state, non-command text routes to handle_message."""
        with patch.object(self.bot, "handle_message") as mock_handle:
            with patch("aipass.skills.lib.telegram.apps.handlers.base_bot.parse_command", return_value=None):
                self.bot.process_update(self._make_update("just regular text"))
                mock_handle.assert_called_once()

    def test_cancel_via_process_update(self):
        """Sending /cancel through process_update clears _create_state."""
        self.bot._create_state[self.chat_id] = {
            "branch_name": "flow",
            "branch_path": "/tmp",
            "started_at": time.time(),
        }
        with patch("aipass.skills.lib.telegram.apps.handlers.base_bot.parse_command", return_value=("cancel", "")):
            self.bot.process_update(self._make_update("/cancel"))
        assert self.chat_id not in self.bot._create_state

    @patch("aipass.skills.lib.telegram.apps.handlers.base_bot.create_bot")
    @patch("aipass.skills.lib.telegram.apps.handlers.base_bot.validate_token")
    def test_command_during_create_flow_not_treated_as_token(self, mock_validate_token, mock_create_bot):
        """Even with _create_state active, /commands should not be routed to _handle_create_token."""
        self.bot._create_state[self.chat_id] = {
            "branch_name": "dev_central",
            "branch_path": "/tmp",
            "started_at": time.time(),
        }
        with patch("aipass.skills.lib.telegram.apps.handlers.base_bot.parse_command", return_value=("cancel", "")):
            with patch.object(self.bot, "_handle_create_token") as mock_token:
                self.bot.process_update(self._make_update("/cancel"))
                mock_token.assert_not_called()


# =============================================
# 24. /create AUTOMATED FLOW (BotFather + Telethon)
# =============================================


class TestCreateAutomated:
    """Test _handle_create_automated and automated path in _handle_create_command."""

    @pytest.fixture(autouse=True)
    def setup_bot(self, tmp_path):
        with patch("aipass.skills.lib.telegram.apps.handlers.base_bot.PENDING_DIR", tmp_path):
            self.bot = BaseBot(
                bot_id="test",
                bot_token="123:FAKE",
                work_dir=tmp_path,
                bot_name="Test Bot",
                allowed_user_ids=[111],
            )
        self.bot.send_message = MagicMock(return_value={"message_id": 42})
        self.chat_id = 12345

    @patch("aipass.skills.lib.telegram.apps.handlers.base_bot.create_bot")
    @patch("aipass.skills.lib.telegram.apps.handlers.base_bot.create_bot_via_botfather")
    def test_automated_flow_succeeds(self, mock_bf_create, mock_create_bot):
        """Automated flow: sends progress, calls BotFather, registers, sends success."""
        mock_bf_create.return_value = {
            "token": "111:AAA_bbb",
            "username": "aipass_dev_central_bot",
            "display_name": "AIPass Dev Central",
        }
        mock_create_bot.return_value = {"bot_id": "dev_central", "status": "created"}

        self.bot._handle_create_automated(self.chat_id, "dev_central", "/home/aipass/dev_central")

        # Should have sent a progress message first, then a success message
        assert self.bot.send_message.call_count == 2
        progress_msg = self.bot.send_message.call_args_list[0][0][1]
        assert "Creating bot" in progress_msg
        success_msg = self.bot.send_message.call_args_list[1][0][1]
        assert "aipass_dev_central_bot" in success_msg
        assert "dev_central" in success_msg

        # Verify create_bot was called with correct args
        mock_create_bot.assert_called_once_with(
            bot_id="dev_central",
            bot_token="111:AAA_bbb",
            branch_name="dev_central",
            work_dir="/home/aipass/dev_central",
            bot_name="AIPass Dev Central",
            allowed_user_ids=[111],
        )

    @patch("aipass.skills.lib.telegram.apps.handlers.base_bot.create_bot_via_botfather")
    def test_automated_flow_botfather_fails_falls_back_to_manual(self, mock_bf_create):
        """When BotFather automation fails, falls back to manual mode (sets _create_state)."""
        mock_bf_create.return_value = None

        self.bot._handle_create_automated(self.chat_id, "flow", "/home/aipass/flow")

        # Should have sent progress message + failure message
        assert self.bot.send_message.call_count == 2
        failure_msg = self.bot.send_message.call_args_list[1][0][1]
        assert "failed" in failure_msg.lower() or "automation" in failure_msg.lower()

        # Should fall back to manual mode by setting _create_state
        assert self.chat_id in self.bot._create_state
        state = self.bot._create_state[self.chat_id]
        assert state["branch_name"] == "flow"
        assert state["branch_path"] == "/home/aipass/flow"

    @patch("aipass.skills.lib.telegram.apps.handlers.base_bot.create_bot", return_value=None)
    @patch("aipass.skills.lib.telegram.apps.handlers.base_bot.create_bot_via_botfather")
    def test_automated_flow_registration_fails(self, mock_bf_create, mock_create_bot):
        """When BotFather succeeds but bot_factory.create_bot fails, sends error."""
        mock_bf_create.return_value = {
            "token": "111:AAA_bbb",
            "username": "aipass_seed_bot",
            "display_name": "AIPass Seed",
        }

        self.bot._handle_create_automated(self.chat_id, "seed", "/home/aipass/seed")

        # Progress message + error message
        assert self.bot.send_message.call_count == 2
        error_msg = self.bot.send_message.call_args_list[1][0][1]
        assert "failed" in error_msg.lower() or "registration" in error_msg.lower()
        # Should NOT set _create_state (no manual fallback after registration failure)
        assert self.chat_id not in self.bot._create_state

    @patch("aipass.skills.lib.telegram.apps.handlers.base_bot.get_bot_by_branch", return_value=None)
    @patch("aipass.skills.lib.telegram.apps.handlers.base_bot.validate_branch")
    @patch("aipass.skills.lib.telegram.apps.handlers.base_bot.check_telethon_setup")
    def test_create_command_uses_automated_when_telethon_ready(self, mock_check, mock_validate, mock_get_bot):
        """_handle_create_command uses automated path when Telethon is ready."""
        mock_check.return_value = (True, "ready")
        mock_validate.return_value = {"name": "dev_central", "path": "/home/aipass/dev_central"}

        with patch.object(self.bot, "_handle_create_automated") as mock_automated:
            self.bot._handle_create_command(self.chat_id, "chat dev_central")
            mock_automated.assert_called_once_with(self.chat_id, "dev_central", "/home/aipass/dev_central")

    @patch("aipass.skills.lib.telegram.apps.handlers.base_bot.get_bot_by_branch", return_value=None)
    @patch("aipass.skills.lib.telegram.apps.handlers.base_bot.validate_branch")
    @patch("aipass.skills.lib.telegram.apps.handlers.base_bot.check_telethon_setup")
    def test_create_command_uses_manual_when_telethon_not_ready(self, mock_check, mock_validate, mock_get_bot):
        """_handle_create_command uses manual path when Telethon is not ready."""
        mock_check.return_value = (False, "Telethon not installed")
        mock_validate.return_value = {"name": "flow", "path": "/home/aipass/flow"}

        with patch.object(self.bot, "_handle_create_automated") as mock_automated:
            self.bot._handle_create_command(self.chat_id, "chat flow")
            mock_automated.assert_not_called()

        # Manual path: _create_state should be set
        assert self.chat_id in self.bot._create_state
        state = self.bot._create_state[self.chat_id]
        assert state["branch_name"] == "flow"

    @patch("aipass.skills.lib.telegram.apps.handlers.base_bot.get_bot_by_branch", return_value=None)
    @patch("aipass.skills.lib.telegram.apps.handlers.base_bot.validate_branch")
    @patch("aipass.skills.lib.telegram.apps.handlers.base_bot.check_telethon_setup")
    def test_manual_fallback_message_shows_reason(self, mock_check, mock_validate, mock_get_bot):
        """Manual fallback message includes the reason automation is unavailable."""
        mock_check.return_value = (False, "Telethon library not installed. Run: pip install telethon")
        mock_validate.return_value = {"name": "flow", "path": "/home/aipass/flow"}

        self.bot._handle_create_command(self.chat_id, "chat flow")

        msg = self.bot.send_message.call_args[0][1]
        assert "Telethon library not installed" in msg
        assert "Falling back to manual token flow" in msg

    @patch("aipass.skills.lib.telegram.apps.handlers.base_bot.create_bot")
    @patch("aipass.skills.lib.telegram.apps.handlers.base_bot.create_bot_via_botfather")
    def test_automated_success_message_contains_service_info(self, mock_bf_create, mock_create_bot):
        """Success message includes systemd service name and start command."""
        mock_bf_create.return_value = {
            "token": "111:AAA_bbb",
            "username": "aipass_memory_bank_bot",
            "display_name": "AIPass Memory Bank",
        }
        mock_create_bot.return_value = {"bot_id": "memory_bank", "status": "created"}

        self.bot._handle_create_automated(self.chat_id, "memory_bank", "/home/aipass/memory_bank")

        success_msg = self.bot.send_message.call_args_list[1][0][1]
        assert "telegram-bot@memory_bank" in success_msg
        assert "systemctl" in success_msg

    @patch("aipass.skills.lib.telegram.apps.handlers.base_bot.create_bot")
    @patch("aipass.skills.lib.telegram.apps.handlers.base_bot.create_bot_via_botfather")
    def test_automated_flow_passes_allowed_user_ids(self, mock_bf_create, mock_create_bot):
        """Automated flow passes the base bot's allowed_user_ids to create_bot."""
        mock_bf_create.return_value = {
            "token": "111:AAA_bbb",
            "username": "aipass_flow_bot",
            "display_name": "AIPass Flow",
        }
        mock_create_bot.return_value = {"bot_id": "flow"}

        self.bot._handle_create_automated(self.chat_id, "flow", "/home/aipass/flow")

        call_kwargs = mock_create_bot.call_args[1]
        assert call_kwargs["allowed_user_ids"] == [111]


# =============================================
# SHARED-SESSION MODE
# =============================================


class TestSharedSession:
    """Tests for shared-session mode (FPLAN-0406)."""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        """Create a BaseBot with shared_session configured."""
        self.workdir = tmp_path / "workdir"
        self.workdir.mkdir()
        self.tmp_path = tmp_path
        with patch("aipass.skills.lib.telegram.apps.handlers.base_bot.PENDING_DIR", tmp_path):
            self.bot = BaseBot(
                bot_id="dev_central",
                bot_token="123:FAKETOKEN",
                work_dir=self.workdir,
                bot_name="Test Bot",
                allowed_user_ids=[111],
                shared_session="pc",
            )
            self.bot.pending_file = tmp_path / "bot-dev_central.json"

    def test_init_stores_shared_session_name(self):
        """shared_session parameter is stored correctly."""
        assert self.bot._shared_session_name == "pc"
        assert self.bot._using_shared_session is False

    def test_init_default_session_name_unchanged(self):
        """Default session_name is still telegram-{bot_id} until shared session found."""
        assert self.bot.session_name == "telegram-dev_central"

    @patch("aipass.skills.lib.telegram.apps.handlers.base_bot.time.sleep")
    @patch("aipass.skills.lib.telegram.apps.handlers.base_bot.subprocess.run")
    def test_ensure_attaches_to_shared_session(self, mock_run, mock_sleep):
        """When shared session exists, bot attaches to it."""
        mock_run.return_value = MagicMock(returncode=0)
        result = self.bot.ensure_tmux_session()
        assert result is True
        assert self.bot.session_name == "pc"
        assert self.bot._using_shared_session is True
        # Should only call has-session for "pc", nothing else
        mock_run.assert_called_once()
        assert mock_run.call_args[0][0] == ["tmux", "has-session", "-t", "pc"]

    @patch("aipass.skills.lib.telegram.apps.handlers.base_bot.time.sleep")
    @patch("aipass.skills.lib.telegram.apps.handlers.base_bot.subprocess.run")
    def test_ensure_returns_false_when_shared_missing(self, mock_run, mock_sleep):
        """When shared session doesn't exist and no presence, returns False (no spawn)."""
        mock_run.return_value = MagicMock(returncode=1)
        result = self.bot.ensure_tmux_session()
        assert result is False
        assert self.bot._using_shared_session is False
        calls = [str(c) for c in mock_run.call_args_list]
        for call in calls:
            assert "new-session" not in call

    @patch("aipass.skills.lib.telegram.apps.handlers.base_bot.subprocess.run")
    def test_inject_uses_shared_session_name(self, mock_run):
        """After attaching, inject_message sends to the shared session."""
        self.bot.session_name = "pc"
        self.bot._using_shared_session = True
        mock_run.return_value = MagicMock(returncode=0)
        result = self.bot.inject_message("test message")
        assert result is True
        # First call should target the shared session "pc"
        first_call = mock_run.call_args_list[0][0][0]
        assert first_call == ["tmux", "send-keys", "-t", "pc", "-l", "test message"]

    def test_kill_protects_shared_session(self):
        """_kill_tmux_session detaches instead of killing shared sessions."""
        self.bot.session_name = "pc"
        self.bot._using_shared_session = True
        result = self.bot._kill_tmux_session()
        assert result is True
        # Should have reset to own session
        assert self.bot._using_shared_session is False
        assert self.bot.session_name == "telegram-dev_central"

    @patch("aipass.skills.lib.telegram.apps.handlers.base_bot.time.sleep")
    @patch("aipass.skills.lib.telegram.apps.handlers.base_bot.subprocess.run")
    def test_pending_file_has_shared_session_name(self, mock_run, mock_sleep):
        """Pending file session_name reflects the shared session."""
        self.bot.session_name = "pc"
        self.bot._using_shared_session = True
        with patch.object(self.bot, "_get_transcript_line_count", return_value=42):
            self.bot.write_pending_file(chat_id=123, message_id=99, processing_message_id=100)
        data = json.loads(self.bot.pending_file.read_text())
        assert data["session_name"] == "pc"
        assert data["bot_id"] == "dev_central"
        assert data["work_dir"] == str(self.workdir)

    def test_no_shared_session_default_behavior(self, tmp_path):
        """Bot without shared_session behaves exactly as before."""
        workdir = tmp_path / "normal"
        workdir.mkdir()
        with patch("aipass.skills.lib.telegram.apps.handlers.base_bot.PENDING_DIR", tmp_path):
            bot = BaseBot(
                bot_id="flow",
                bot_token="456:FAKE",
                work_dir=workdir,
            )
        assert bot._shared_session_name is None
        assert bot._using_shared_session is False
        assert bot.session_name == "telegram-flow"

    @patch("aipass.skills.lib.telegram.apps.handlers.base_bot.time.sleep")
    @patch("aipass.skills.lib.telegram.apps.handlers.base_bot.subprocess.run")
    def test_reattaches_after_new_command(self, mock_run, mock_sleep):
        """After /new detaches, next ensure_tmux_session reattaches to shared session."""
        # Simulate attached to shared session
        self.bot.session_name = "pc"
        self.bot._using_shared_session = True

        # /new triggers kill which detaches
        self.bot._kill_tmux_session()
        assert self.bot._using_shared_session is False

        # Next ensure should try shared session again
        mock_run.return_value = MagicMock(returncode=0)
        result = self.bot.ensure_tmux_session()
        assert result is True
        assert self.bot.session_name == "pc"
        assert self.bot._using_shared_session is True


# =============================================
# LOCK FILE PID REUSE FIX
# =============================================


class TestLockPidReuse:
    """Tests for lock file PID reuse detection."""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        """Create a BaseBot with lock file in tmp_path."""
        self.workdir = tmp_path / "workdir"
        self.workdir.mkdir()
        self.tmp_path = tmp_path
        with patch("aipass.skills.lib.telegram.apps.handlers.base_bot.PENDING_DIR", tmp_path):
            self.bot = BaseBot(
                bot_id="vera",
                bot_token="123:FAKETOKEN",
                work_dir=self.workdir,
                bot_name="Test Bot",
            )
        self.bot._lock_file = tmp_path / ".vera.lock"

    def test_no_lock_file_returns_false(self):
        """No lock file means no conflict."""
        assert self.bot._check_lock() is False

    def test_dead_pid_cleans_stale_lock(self):
        """Dead PID in lock file is cleaned as stale."""
        self.bot._lock_file.write_text(
            json.dumps({"pid": 999999999, "bot_id": "vera"}),
            encoding="utf-8",
        )
        assert self.bot._check_lock() is False
        assert not self.bot._lock_file.exists()

    @patch("sys.platform", "linux")
    @patch("aipass.skills.lib.telegram.apps.handlers.base_bot.os.kill")
    def test_alive_pid_same_bot_returns_true(self, mock_kill):
        """Live PID running this bot returns True (lock held)."""
        mock_kill.return_value = None  # PID alive
        pid = os.getpid()
        self.bot._lock_file.write_text(
            json.dumps({"pid": pid, "bot_id": "vera"}),
            encoding="utf-8",
        )
        # Mock /proc read to return matching cmdline
        with patch("pathlib.Path.read_bytes") as mock_read:
            mock_read.return_value = b"python3\x00base_bot.py\x00--bot-id\x00vera"
            assert self.bot._check_lock() is True
        assert self.bot._lock_file.exists()  # Lock preserved

    @patch("sys.platform", "linux")
    @patch("aipass.skills.lib.telegram.apps.handlers.base_bot.os.kill")
    def test_alive_pid_different_bot_cleans_lock(self, mock_kill):
        """Live PID running a DIFFERENT bot cleans stale lock (PID reuse)."""
        mock_kill.return_value = None  # PID alive
        pid = os.getpid()
        self.bot._lock_file.write_text(
            json.dumps({"pid": pid, "bot_id": "vera"}),
            encoding="utf-8",
        )
        # Mock /proc read to return different bot's cmdline
        with patch("pathlib.Path.read_bytes") as mock_read:
            mock_read.return_value = b"python3\x00base_bot.py\x00--bot-id\x00other_bot"
            assert self.bot._check_lock() is False
        assert not self.bot._lock_file.exists()  # Stale lock cleaned

    def test_corrupt_lock_file_cleaned(self):
        """Corrupt lock file is cleaned."""
        self.bot._lock_file.write_text("not json", encoding="utf-8")
        assert self.bot._check_lock() is False
        assert not self.bot._lock_file.exists()
