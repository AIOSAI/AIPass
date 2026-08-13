"""
Comprehensive pytest tests for LogStreamer.

Tests cover:
  - Initialization (logger setup, position tracking, empty state)
  - Position tracking (_read_new_lines): new content, rotation, discovery, pattern matching
  - Telegram delivery (_send_message): payloads, success/failure, logging
  - Batching (_send_batched): under limit, over limit splits, empty input
  - Start/Stop: daemon thread lifecycle, double-start safety, stop-before-start safety
  - Integration with BaseBot: streamer starts on first message, not for base bot, cleanup

All network (urllib) calls are mocked.
Fake log files are created in tmp_path - no real system_logs directory is touched.
"""

import io
import json
import threading
from email.message import Message
from urllib.error import HTTPError

import pytest
from unittest.mock import patch, MagicMock

from aipass.skills.lib.telegram.apps.handlers.log_streamer import (
    LogStreamer,
    TELEGRAM_MAX_LENGTH,
)


# =============================================
# HELPERS
# =============================================


def _make_streamer(logs_dir, tmp_path, branch_name: str = "api") -> LogStreamer:
    """Build a LogStreamer with SYSTEM_LOGS_DIR redirected to tmp_path."""
    with patch("aipass.skills.lib.telegram.apps.handlers.log_streamer.SYSTEM_LOGS_DIR", logs_dir):
        s = LogStreamer(
            bot_token="123:FAKETOKEN",
            chat_id=999888,
            branch_name=branch_name,
        )
    return s


# =============================================
# FIXTURES
# =============================================


@pytest.fixture
def logs_dir(tmp_path):
    """Create a temporary logs directory for test log files."""
    log_dir = tmp_path / "system_logs"
    log_dir.mkdir()
    return log_dir


@pytest.fixture
def streamer(logs_dir, tmp_path):
    """Create a LogStreamer with SYSTEM_LOGS_DIR and log handler redirected to tmp_path."""
    return _make_streamer(logs_dir, tmp_path)


@pytest.fixture
def streamer_with_files(logs_dir, tmp_path):
    """Create a LogStreamer after pre-populating matching and non-matching log files."""
    # Create matching log files with content. newline="" disables newline
    # translation so byte counts match len() on Windows too (\n stays 1 byte,
    # not \r\n) — real log files are LF-terminated.
    (logs_dir / "api_main.log").write_text("line1\nline2\n", encoding="utf-8", newline="")
    (logs_dir / "api_error.log").write_text("err1\n", encoding="utf-8", newline="")
    # Create a non-matching file (should be ignored)
    (logs_dir / "trigger_main.log").write_text("other\n", encoding="utf-8", newline="")

    return _make_streamer(logs_dir, tmp_path)


# =============================================
# 1. INITIALIZATION
# =============================================


class TestLogStreamerInit:
    """Test that LogStreamer.__init__ sets attributes and initializes positions."""

    def test_bot_token_stored(self, streamer):
        """Verify bot_token is stored on the instance."""
        assert streamer.bot_token == "123:FAKETOKEN"

    def test_chat_id_stored(self, streamer):
        """Verify chat_id is stored on the instance."""
        assert streamer.chat_id == 999888

    def test_branch_name_stored(self, streamer):
        """Verify branch_name is stored on the instance."""
        assert streamer.branch_name == "api"

    def test_running_false_initially(self, streamer):
        """Verify _running is False before start() is called."""
        assert streamer._running is False

    def test_thread_none_initially(self, streamer):
        """Verify _thread is None before start() is called."""
        assert streamer._thread is None

    def test_stop_event_exists(self, streamer):
        """Verify _stop_event is a threading.Event instance."""
        assert isinstance(streamer._stop_event, threading.Event)

    def test_branch_name_in_streamer(self, streamer):
        """Verify branch_name is accessible on the instance."""
        assert streamer.branch_name == "api"

    def test_positions_empty_when_no_matching_files(self, streamer):
        """When SYSTEM_LOGS_DIR has no matching files, positions should be empty."""
        assert streamer.log_positions == {}

    def test_positions_initialized_to_end_of_existing_files(self, streamer_with_files, logs_dir):
        """Positions should point to end of file so we only tail new lines."""
        api_main_path = str(logs_dir / "api_main.log")
        api_error_path = str(logs_dir / "api_error.log")

        assert api_main_path in streamer_with_files.log_positions
        assert api_error_path in streamer_with_files.log_positions
        # Position should equal file size (end of file)
        assert streamer_with_files.log_positions[api_main_path] == len("line1\nline2\n")
        assert streamer_with_files.log_positions[api_error_path] == len("err1\n")

    def test_positions_exclude_non_matching_files(self, streamer_with_files, logs_dir):
        """Files not matching '{branch_name}_*.log' pattern should be excluded."""
        trigger_path = str(logs_dir / "trigger_main.log")
        assert trigger_path not in streamer_with_files.log_positions

    def test_positions_only_two_matching_files(self, streamer_with_files):
        """Only the 2 matching api_*.log files should be tracked."""
        assert len(streamer_with_files.log_positions) == 2


# =============================================
# 2. POSITION TRACKING (_read_new_lines)
# =============================================


class TestPositionTracking:
    """Test _read_new_lines: reading new content, rotation, discovery, pattern matching."""

    def test_reads_new_content_appended(self, streamer_with_files, logs_dir):
        """New lines appended after init should be returned by _read_new_lines."""
        log_file = logs_dir / "api_main.log"
        # Append new content
        with open(log_file, "a", encoding="utf-8") as f:
            f.write("new_line_3\nnew_line_4\n")

        with patch("aipass.skills.lib.telegram.apps.handlers.log_streamer.SYSTEM_LOGS_DIR", logs_dir):
            new_lines = streamer_with_files._read_new_lines()

        assert "new_line_3" in new_lines
        assert "new_line_4" in new_lines

    def test_no_new_content_returns_empty(self, streamer_with_files, logs_dir):
        """If nothing was appended, should return empty list."""
        with patch("aipass.skills.lib.telegram.apps.handlers.log_streamer.SYSTEM_LOGS_DIR", logs_dir):
            new_lines = streamer_with_files._read_new_lines()
        assert new_lines == []

    def test_detects_file_rotation(self, streamer_with_files, logs_dir):
        """When file size shrinks (rotation), should reset and read from beginning."""
        log_file = logs_dir / "api_main.log"
        # Simulate rotation: overwrite with smaller content
        log_file.write_text("rotated\n", encoding="utf-8")

        with patch("aipass.skills.lib.telegram.apps.handlers.log_streamer.SYSTEM_LOGS_DIR", logs_dir):
            new_lines = streamer_with_files._read_new_lines()

        assert "rotated" in new_lines

    def test_discovers_new_log_files(self, streamer_with_files, logs_dir):
        """New files appearing mid-run should be discovered and read from beginning."""
        new_file = logs_dir / "api_new_module.log"
        new_file.write_text("discovered_line\n", encoding="utf-8")

        with patch("aipass.skills.lib.telegram.apps.handlers.log_streamer.SYSTEM_LOGS_DIR", logs_dir):
            new_lines = streamer_with_files._read_new_lines()

        assert "discovered_line" in new_lines

    def test_ignores_non_matching_pattern(self, streamer_with_files, logs_dir):
        """Files not matching '{branch_name}_*.log' should never be read."""
        non_matching = logs_dir / "trigger_main.log"
        # Append to existing non-matching file
        with open(non_matching, "a", encoding="utf-8") as f:
            f.write("should_be_ignored\n")

        with patch("aipass.skills.lib.telegram.apps.handlers.log_streamer.SYSTEM_LOGS_DIR", logs_dir):
            new_lines = streamer_with_files._read_new_lines()

        assert "should_be_ignored" not in new_lines

    def test_handles_deleted_file_gracefully(self, streamer_with_files, logs_dir):
        """If a tracked file is deleted, _read_new_lines should not crash."""
        log_file = logs_dir / "api_main.log"
        log_file.unlink()

        with patch("aipass.skills.lib.telegram.apps.handlers.log_streamer.SYSTEM_LOGS_DIR", logs_dir):
            # Should not raise
            new_lines = streamer_with_files._read_new_lines()

        # It should still return lines from other files (or empty)
        assert isinstance(new_lines, list)

    def test_updates_position_after_read(self, streamer_with_files, logs_dir):
        """Position should advance after reading new content."""
        log_file = logs_dir / "api_main.log"
        file_path = str(log_file)
        initial_pos = streamer_with_files.log_positions[file_path]

        with open(log_file, "a", encoding="utf-8") as f:
            f.write("extra\n")

        with patch("aipass.skills.lib.telegram.apps.handlers.log_streamer.SYSTEM_LOGS_DIR", logs_dir):
            streamer_with_files._read_new_lines()

        assert streamer_with_files.log_positions[file_path] > initial_pos

    def test_system_logs_dir_missing_returns_empty(self, streamer, tmp_path):
        """If SYSTEM_LOGS_DIR does not exist, _get_log_files returns empty."""
        missing_dir = tmp_path / "does_not_exist"
        with patch("aipass.skills.lib.telegram.apps.handlers.log_streamer.SYSTEM_LOGS_DIR", missing_dir):
            new_lines = streamer._read_new_lines()
        assert new_lines == []


# =============================================
# 3. TELEGRAM DELIVERY (_send_message)
# =============================================


class TestSendMessage:
    """Test _send_message: payload, success, failure, logging."""

    def _make_mock_response(self, body_dict):
        """Build a mock urllib response that works as a context manager."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(body_dict).encode("utf-8")
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        return mock_resp

    def test_sends_correct_payload(self, streamer):
        """Payload should include chat_id, text, and disable_notification."""
        mock_resp = self._make_mock_response({"ok": True})

        with patch(
            "aipass.skills.lib.telegram.apps.handlers.log_streamer.urlopen", return_value=mock_resp
        ) as mock_urlopen:
            streamer._send_message("hello world")

        # Verify the request was made
        args, _kwargs = mock_urlopen.call_args
        req = args[0]
        assert req.full_url == "https://api.telegram.org/bot123:FAKETOKEN/sendMessage"
        payload = json.loads(req.data.decode("utf-8"))
        assert payload["chat_id"] == 999888
        assert payload["text"] == "hello world"
        assert payload["disable_notification"] is True

    def test_returns_true_on_success(self, streamer):
        """Should return True when Telegram responds with ok=True."""
        mock_resp = self._make_mock_response({"ok": True})

        with patch("aipass.skills.lib.telegram.apps.handlers.log_streamer.urlopen", return_value=mock_resp):
            result = streamer._send_message("test")

        assert result is True

    def test_returns_false_on_url_error(self, streamer):
        """Should return False and not crash on URLError."""
        from urllib.error import URLError

        with patch("aipass.skills.lib.telegram.apps.handlers.log_streamer.urlopen", side_effect=URLError("fail")):
            result = streamer._send_message("test")

        assert result is False

    def test_returns_false_on_generic_exception(self, streamer):
        """Should return False on any unexpected exception."""
        with patch("aipass.skills.lib.telegram.apps.handlers.log_streamer.urlopen", side_effect=RuntimeError("boom")):
            result = streamer._send_message("test")

        assert result is False

    def test_logs_warning_on_failure(self, streamer):
        """Should log a warning when send fails."""
        from urllib.error import URLError

        with (
            patch("aipass.skills.lib.telegram.apps.handlers.log_streamer.urlopen", side_effect=URLError("network")),
            patch("aipass.skills.lib.telegram.apps.handlers.log_streamer.logger") as mock_logger,
        ):
            streamer._send_message("test")

        mock_logger.warning.assert_called_once()
        assert "Telegram send failed" in mock_logger.warning.call_args[0][0]

    def test_returns_false_when_ok_is_false(self, streamer):
        """Should return False when Telegram responds with ok=False."""
        mock_resp = self._make_mock_response({"ok": False})

        with patch("aipass.skills.lib.telegram.apps.handlers.log_streamer.urlopen", return_value=mock_resp):
            result = streamer._send_message("test")

        assert result is False

    def test_content_type_header(self, streamer):
        """Request should have Content-Type: application/json header."""
        mock_resp = self._make_mock_response({"ok": True})

        with patch(
            "aipass.skills.lib.telegram.apps.handlers.log_streamer.urlopen", return_value=mock_resp
        ) as mock_urlopen:
            streamer._send_message("test")

        req = mock_urlopen.call_args[0][0]
        assert req.get_header("Content-type") == "application/json"


# =============================================
# 4. BATCHING (_send_batched)
# =============================================


class TestSendBatched:
    """Test _send_batched: single message, splitting, empty input."""

    def test_single_message_under_limit(self, streamer):
        """Lines fitting within TELEGRAM_MAX_LENGTH should be sent as one message."""
        lines = ["line1", "line2", "line3"]
        with patch.object(streamer, "_send_message") as mock_send:
            streamer._send_batched(lines)

        mock_send.assert_called_once_with("line1\nline2\nline3")

    def test_empty_input_sends_nothing(self, streamer):
        """Empty list should not trigger any sends."""
        with patch.object(streamer, "_send_message") as mock_send:
            streamer._send_batched([])

        mock_send.assert_not_called()

    def test_splits_at_line_boundaries_when_over_limit(self, streamer):
        """Messages exceeding TELEGRAM_MAX_LENGTH should be split across multiple sends."""
        # Each line ~100 chars, 50 lines = ~5000 total (exceeds 4000 limit)
        long_line = "A" * 99
        lines = [long_line] * 50

        with patch.object(streamer, "_send_message") as mock_send:
            streamer._send_batched(lines)

        # Should have been called more than once
        assert mock_send.call_count >= 2

        # Verify each message is under the limit
        for call_args in mock_send.call_args_list:
            message = call_args[0][0]
            assert len(message) <= TELEGRAM_MAX_LENGTH

    def test_all_lines_delivered_when_split(self, streamer):
        """All original lines should appear across the split messages."""
        long_line = "X" * 99
        lines = [f"{long_line}_{i}" for i in range(50)]

        sent_messages: list[str] = []
        with patch.object(streamer, "_send_message", side_effect=lambda m: sent_messages.append(m)):
            streamer._send_batched(lines)

        # Reconstruct all lines from sent messages
        all_sent_lines: list[str] = []
        for msg in sent_messages:
            all_sent_lines.extend(msg.split("\n"))

        for line in lines:
            assert line in all_sent_lines

    def test_single_line_sent_as_single_message(self, streamer):
        """A single line should result in exactly one send."""
        with patch.object(streamer, "_send_message") as mock_send:
            streamer._send_batched(["single line"])

        mock_send.assert_called_once_with("single line")


# =============================================
# 5. START / STOP
# =============================================


class TestStartStop:
    """Test start() and stop() lifecycle management."""

    def test_start_creates_daemon_thread(self, streamer):
        """Verify start() creates and starts a daemon thread."""
        # Patch _run to avoid real loop execution
        with patch.object(streamer, "_run"):
            streamer.start()
            try:
                assert streamer._thread is not None
                assert streamer._thread.daemon is True
                assert streamer._thread.name == "log-streamer-api"
                assert streamer._running is True
            finally:
                streamer.stop()

    def test_stop_sets_flag_and_joins(self, streamer):
        """Verify stop() sets _running to False, signals the event, and joins thread."""
        with patch.object(streamer, "_run"):
            streamer.start()
            assert streamer._running is True

            streamer.stop()
            assert streamer._running is False
            assert streamer._thread is None

    def test_double_start_is_safe(self, streamer):
        """Calling start() twice should log a warning and not create a second thread."""
        with patch.object(streamer, "_run"):
            streamer.start()
            first_thread = streamer._thread

            with patch("aipass.skills.lib.telegram.apps.handlers.log_streamer.logger") as mock_logger:
                streamer.start()

            mock_logger.warning.assert_called_once()
            assert "already running" in mock_logger.warning.call_args[0][0]
            assert streamer._thread is first_thread

            streamer.stop()

    def test_stop_on_not_started_is_safe(self, streamer):
        """Calling stop() before start() should not raise any exception."""
        assert streamer._running is False
        # Should not raise any exception
        streamer.stop()
        assert streamer._running is False

    def test_stop_event_is_set_on_stop(self, streamer):
        """Verify the _stop_event is set when stop() is called."""
        with patch.object(streamer, "_run"):
            streamer.start()
            assert not streamer._stop_event.is_set()

            streamer.stop()
            assert streamer._stop_event.is_set()

    def test_start_clears_stop_event(self, streamer):
        """Verify start() clears any previously set stop event."""
        streamer._stop_event.set()
        with patch.object(streamer, "_run"):
            streamer.start()
            assert not streamer._stop_event.is_set()
            streamer.stop()


# =============================================
# 6. INTEGRATION WITH base_bot.py
# =============================================


class TestBaseBotIntegration:
    """Test LogStreamer integration points in BaseBot."""

    @pytest.fixture
    def _patch_base_bot_deps(self, tmp_path):
        """Patch heavy BaseBot dependencies to allow lightweight instantiation."""
        patches = [
            patch("aipass.skills.lib.telegram.apps.handlers.base_bot.PENDING_DIR", tmp_path),
            patch("aipass.skills.lib.telegram.apps.handlers.base_bot.signal.signal"),
            patch("aipass.skills.lib.telegram.apps.handlers.base_bot.atexit.register"),
        ]
        for p in patches:
            p.start()
        yield
        for p in patches:
            p.stop()

    def test_streamer_starts_on_first_message_with_branch_name(self, tmp_path, _patch_base_bot_deps):
        """When branch_name is set, LogStreamer should start on first message."""
        from aipass.skills.lib.telegram.apps.handlers.base_bot import BaseBot

        workdir = tmp_path / "workdir"
        workdir.mkdir()
        bot = BaseBot(
            bot_id="test_branch",
            bot_token="123:FAKETOKEN",
            work_dir=workdir,
            bot_name="Test Branch Bot",
            allowed_user_ids=[111],
            branch_name="api",
        )

        assert bot._log_streamer is None

        # Wrap message in a Telegram update dict (process_update extracts .message)
        fake_update = {
            "message": {
                "chat": {"id": 42},
                "from": {"id": 111},
                "text": "/start",
                "message_id": 1,
            }
        }

        # Patch LogStreamer at the import location in base_bot
        with (
            patch.object(bot, "send_message"),
            patch("aipass.skills.lib.telegram.apps.handlers.base_bot.LogStreamer") as MockStreamer,
        ):
            mock_instance = MagicMock()
            MockStreamer.return_value = mock_instance

            bot.process_update(fake_update)

            MockStreamer.assert_called_once_with("123:FAKETOKEN", 42, "api", level_filter="all")
            mock_instance.start.assert_called_once()

    def test_streamer_not_started_when_branch_name_is_none(self, tmp_path, _patch_base_bot_deps):
        """When branch_name is None (base bot), LogStreamer should NOT be created."""
        from aipass.skills.lib.telegram.apps.handlers.base_bot import BaseBot

        workdir = tmp_path / "workdir"
        workdir.mkdir()
        bot = BaseBot(
            bot_id="base_only",
            bot_token="123:FAKETOKEN",
            work_dir=workdir,
            bot_name="Base Bot",
            allowed_user_ids=[111],
            branch_name=None,
        )

        fake_update = {
            "message": {
                "chat": {"id": 42},
                "from": {"id": 111},
                "text": "/start",
                "message_id": 1,
            }
        }

        with (
            patch.object(bot, "send_message"),
            patch("aipass.skills.lib.telegram.apps.handlers.base_bot.LogStreamer") as MockStreamer,
        ):
            bot.process_update(fake_update)
            MockStreamer.assert_not_called()

    def test_cleanup_stops_streamer(self, tmp_path, _patch_base_bot_deps):
        """BaseBot._cleanup should call stop() on the LogStreamer if it exists."""
        from aipass.skills.lib.telegram.apps.handlers.base_bot import BaseBot

        workdir = tmp_path / "workdir"
        workdir.mkdir()
        bot = BaseBot(
            bot_id="cleanup_test",
            bot_token="123:FAKETOKEN",
            work_dir=workdir,
            bot_name="Cleanup Bot",
            allowed_user_ids=[111],
            branch_name="api",
        )

        mock_streamer = MagicMock()
        bot._log_streamer = mock_streamer

        bot._cleanup()

        mock_streamer.stop.assert_called_once()
        assert bot._log_streamer is None

    def test_cleanup_safe_when_no_streamer(self, tmp_path, _patch_base_bot_deps):
        """BaseBot._cleanup should work fine when _log_streamer is None."""
        from aipass.skills.lib.telegram.apps.handlers.base_bot import BaseBot

        workdir = tmp_path / "workdir"
        workdir.mkdir()
        bot = BaseBot(
            bot_id="no_streamer",
            bot_token="123:FAKETOKEN",
            work_dir=workdir,
            bot_name="No Streamer Bot",
            allowed_user_ids=[111],
        )

        assert bot._log_streamer is None
        # Should not raise
        bot._cleanup()
        assert bot._log_streamer is None


# =============================================
# 7. PAYLOADS TELEGRAM REJECTS WITH 400
# =============================================


class TestRejectedPayloads:
    """Regression cover for the HTTP 400 burst on bot_prax_monitor.

    Measured against the live API on 2026-08-11, sendMessage answers 400 with:
      - 'Bad Request: message is too long'    for text over ~4096 chars
      - 'Bad Request: message text is empty'  for ''
      - 'Bad Request: text must be non-empty' for whitespace-only text
    Brackets, dashes and underscores are NOT an offense on this path — it sends
    no parse_mode — and a 4000-char line of them was accepted live.
    """

    def test_single_oversized_line_is_split(self, streamer):
        """THE root cause: batching splits between lines, so one long line went whole."""
        # 5,167 chars — the exact length of the drone_router line that preceded
        # the 12:39:19 rejection.
        lines = ["2026-08-11 12:39:14 | captured_router | INFO | " + "x" * 5120]

        sent: list[str] = []
        with patch.object(streamer, "_send_message", side_effect=lambda m: sent.append(m) or True):
            streamer._send_batched(lines)

        assert len(sent) >= 2, "oversized line was not split"
        for message in sent:
            assert len(message) <= TELEGRAM_MAX_LENGTH

    def test_no_payload_ever_exceeds_the_cap(self, streamer):
        """Whatever the input shape, nothing over the cap may reach the API."""
        lines = [
            "short",
            "y" * 12000,  # far over
            "also short",
            "z" * (TELEGRAM_MAX_LENGTH + 1),  # one char over the edge
        ]

        sent: list[str] = []
        with patch.object(streamer, "_send_message", side_effect=lambda m: sent.append(m) or True):
            streamer._send_batched(lines)

        assert sent
        for message in sent:
            assert len(message) <= TELEGRAM_MAX_LENGTH

    def test_split_chunks_are_marked_and_lossless(self, streamer):
        """A split line must stay readable and must not lose characters."""
        payload = "q" * 9000

        sent: list[str] = []
        with patch.object(streamer, "_send_message", side_effect=lambda m: sent.append(m) or True):
            streamer._send_batched([payload])

        joined = "\n".join(sent)
        assert "[1/" in joined and "[3/3]" in joined
        recovered = "".join(part.rsplit(" [", 1)[0] for part in joined.split("\n"))
        assert recovered == payload

    def test_monitor_line_with_brackets_and_underscores_passes_intact(self, streamer):
        """Devpulse's markdown suspect: this path sets no parse_mode, so it must pass unchanged."""
        line = (
            "2026-08-11 12:39:14 | captured_router | INFO | "
            "Routing @ai_mail [CALLER:SEEDGO] -> snake_case *stars* _under_"
        )

        sent: list[str] = []
        with patch.object(streamer, "_send_message", side_effect=lambda m: sent.append(m) or True):
            streamer._send_batched([line])

        assert sent == [line]

    def test_send_message_refuses_empty_text(self, streamer):
        """'' is a 400 ('message text is empty') — refuse it before the network."""
        with patch("aipass.skills.lib.telegram.apps.handlers.log_streamer.urlopen") as mock_open:
            assert streamer._send_message("") is False
            mock_open.assert_not_called()

    def test_send_message_refuses_whitespace_only_text(self, streamer):
        """'\\n\\n' is a 400 ('text must be non-empty') — same guard."""
        with patch("aipass.skills.lib.telegram.apps.handlers.log_streamer.urlopen") as mock_open:
            assert streamer._send_message("\n\n") is False
            mock_open.assert_not_called()

    def test_blank_lines_are_dropped_by_the_filter(self, streamer):
        """Blank log lines carry nothing; a batch of only blanks is a rejected payload."""
        lines = ["", "   ", "2026-08-11 | captured_x | WARNING | real content", ""]
        assert streamer._filter_lines(lines) == ["2026-08-11 | captured_x | WARNING | real content"]

    def test_batch_of_only_blank_lines_sends_nothing(self, streamer):
        with patch.object(streamer, "_send_message") as mock_send:
            streamer._send_batched(streamer._filter_lines(["", "  ", ""]))
        mock_send.assert_not_called()

    def test_http_error_body_is_logged_not_discarded(self, streamer):
        """The 400 body names the offense; a bare status line names nothing."""
        body = json.dumps({"ok": False, "error_code": 400, "description": "Bad Request: message is too long"})
        err = HTTPError("url", 400, "Bad Request", Message(), io.BytesIO(body.encode()))

        with patch("aipass.skills.lib.telegram.apps.handlers.log_streamer.urlopen", side_effect=err):
            with patch("aipass.skills.lib.telegram.apps.handlers.log_streamer.logger") as mock_logger:
                assert streamer._send_message("anything") is False

        logged = " ".join(str(c) for c in mock_logger.warning.call_args_list)
        assert "message is too long" in logged
        assert "400" in logged

    def test_http_error_without_body_still_logs(self, streamer):
        """An unreadable body must not turn the rejection into a crash or a silence."""
        err = HTTPError("url", 400, "Bad Request", Message(), io.BytesIO(b"not json"))

        with patch("aipass.skills.lib.telegram.apps.handlers.log_streamer.urlopen", side_effect=err):
            with patch("aipass.skills.lib.telegram.apps.handlers.log_streamer.logger") as mock_logger:
                assert streamer._send_message("anything") is False

        assert mock_logger.warning.called
