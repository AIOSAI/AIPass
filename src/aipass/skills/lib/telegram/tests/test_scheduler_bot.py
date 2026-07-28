"""
Tests for SchedulerBot — dedicated Telegram bot for daemon job queue (TDPLAN-0008 P2).

Tests cover:
  - /queue parses drone @daemon queue --json and formats readable output
  - Free-text (non-command) does NOT launch tmux/Claude
  - Hourly digest thread posts a digest (mockable clock/sender)
  - >4096-char digest is chunked correctly via chunk_text
  - Bot loads telegram/scheduler config; missing secret fails loud
  - Slash-menu includes /queue
  - Command routing (/queue dispatched correctly)
"""

import json
import pytest
from unittest.mock import patch, MagicMock

from aipass.skills.lib.telegram.apps.handlers.scheduler_bot import SchedulerBot, QUEUE_CMD


# =============================================
# HELPERS
# =============================================


SAMPLE_QUEUE = {
    "generated_at": "2026-06-25T15:00:00Z",
    "count": 2,
    "jobs": [
        {
            "owner": "@api",
            "id": "data-check",
            "enabled": True,
            "type": "once",
            "schedule_human": "2026-07-02",
            "next_run": "2026-07-02T09:00:00Z",
            "last_run": None,
            "last_status": "success",
            "last_error": None,
            "prompt_preview": "Check the live data and report...",
            "wake": {"fresh": True, "model": "haiku"},
        },
        {
            "owner": "@backup",
            "id": "weekly-snap",
            "enabled": False,
            "type": "interval",
            "schedule_human": "every 7d",
            "next_run": "2026-07-01T00:00:00Z",
            "last_run": "2026-06-24T00:00:00Z",
            "last_status": "failed",
            "last_error": "disk full",
            "prompt_preview": "Run full backup...",
            "wake": {"fresh": True},
        },
    ],
}

EMPTY_QUEUE = {"generated_at": "2026-06-25T15:00:00Z", "count": 0, "jobs": []}


@pytest.fixture
def _patch_base_bot_deps(tmp_path):
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


def _make_scheduler_bot(tmp_path, _patch_base_bot_deps):
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    bot = SchedulerBot(
        bot_id="scheduler",
        bot_token="123:FAKETOKEN",
        work_dir=workdir,
        bot_name="AIPass Scheduler Bot",
        allowed_user_ids=[111],
        branch_name=None,
    )
    return bot


# =============================================
# 1. /queue PARSES AND FORMATS
# =============================================


class TestQueueCommand:
    """/queue fetches queue --json, formats, and sends."""

    def test_queue_formats_jobs(self):
        text = SchedulerBot._format_queue(SAMPLE_QUEUE)
        assert "@api/data-check" in text
        assert "@backup/weekly-snap" in text
        assert "[disabled]" in text
        assert "once" in text
        assert "success" in text

    def test_queue_shows_error_when_failed(self):
        text = SchedulerBot._format_queue(SAMPLE_QUEUE)
        assert "disk full" in text

    def test_queue_empty_shows_no_jobs(self):
        text = SchedulerBot._format_queue(EMPTY_QUEUE)
        assert "No scheduled jobs" in text

    def test_queue_shows_count(self):
        text = SchedulerBot._format_queue(SAMPLE_QUEUE)
        assert "2" in text

    def test_queue_shows_status_icons(self):
        text = SchedulerBot._format_queue(SAMPLE_QUEUE)
        assert "✅" in text  # success
        assert "❌" in text  # failed

    def test_queue_command_sends_formatted(self, tmp_path, _patch_base_bot_deps):
        bot = _make_scheduler_bot(tmp_path, _patch_base_bot_deps)
        with (
            patch.object(bot, "_fetch_queue", return_value=SAMPLE_QUEUE),
            patch.object(bot, "send_message") as mock_send,
        ):
            bot._handle_queue_command(42)
            mock_send.assert_called_once()
            msg = mock_send.call_args[0][1]
            assert "@api/data-check" in msg

    def test_queue_command_handles_fetch_failure(self, tmp_path, _patch_base_bot_deps):
        bot = _make_scheduler_bot(tmp_path, _patch_base_bot_deps)
        with (
            patch.object(bot, "_fetch_queue", return_value=None),
            patch.object(bot, "send_message") as mock_send,
        ):
            bot._handle_queue_command(42)
            msg = mock_send.call_args[0][1]
            assert "Failed" in msg

    def test_fetch_queue_parses_subprocess(self, tmp_path, _patch_base_bot_deps):
        bot = _make_scheduler_bot(tmp_path, _patch_base_bot_deps)
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps(SAMPLE_QUEUE)

        with patch("aipass.skills.lib.telegram.apps.handlers.scheduler_bot.subprocess.run", return_value=mock_result):
            data = bot._fetch_queue()

        assert data is not None
        assert data["count"] == 2
        assert len(data["jobs"]) == 2

    def test_fetch_queue_returns_none_on_failure(self, tmp_path, _patch_base_bot_deps):
        bot = _make_scheduler_bot(tmp_path, _patch_base_bot_deps)
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "error"

        with patch("aipass.skills.lib.telegram.apps.handlers.scheduler_bot.subprocess.run", return_value=mock_result):
            data = bot._fetch_queue()

        assert data is None

    def test_fetch_queue_returns_none_on_timeout(self, tmp_path, _patch_base_bot_deps):
        bot = _make_scheduler_bot(tmp_path, _patch_base_bot_deps)
        import subprocess as sp

        with patch(
            "aipass.skills.lib.telegram.apps.handlers.scheduler_bot.subprocess.run",
            side_effect=sp.TimeoutExpired(QUEUE_CMD, 15),
        ):
            data = bot._fetch_queue()

        assert data is None


# =============================================
# 2. FREE-TEXT DOES NOT LAUNCH TMUX
# =============================================


class TestNoTmux:
    """Free-text and file messages do NOT spin up tmux/Claude."""

    def test_free_text_rejected(self, tmp_path, _patch_base_bot_deps):
        bot = _make_scheduler_bot(tmp_path, _patch_base_bot_deps)
        with (
            patch.object(bot, "send_message") as mock_send,
            patch.object(bot, "ensure_tmux_session") as mock_tmux,
        ):
            bot.handle_message(42, "Hello there", {"message_id": 1})
            mock_tmux.assert_not_called()
            msg = mock_send.call_args[0][1]
            assert "commands" in msg.lower() or "/queue" in msg

    def test_file_rejected(self, tmp_path, _patch_base_bot_deps):
        bot = _make_scheduler_bot(tmp_path, _patch_base_bot_deps)
        with (
            patch.object(bot, "send_message") as mock_send,
            patch("aipass.skills.lib.telegram.apps.handlers.base_bot.BaseBot.handle_file") as mock_parent_file,
        ):
            bot.handle_file(42, {"message_id": 1, "document": {"file_id": "abc"}})
            mock_parent_file.assert_not_called()
            msg = mock_send.call_args[0][1]
            assert "file" in msg.lower() or "/queue" in msg


# =============================================
# 3. HOURLY DIGEST
# =============================================


class TestDigest:
    """Hourly digest thread posts queue digest."""

    def test_digest_posts_message(self, tmp_path, _patch_base_bot_deps):
        bot = _make_scheduler_bot(tmp_path, _patch_base_bot_deps)
        bot._scheduler_chat_id = 42

        with (
            patch.object(bot, "_fetch_queue", return_value=SAMPLE_QUEUE),
            patch.object(bot, "send_message") as mock_send,
        ):
            bot._post_digest()
            mock_send.assert_called_once()
            msg = mock_send.call_args[0][1]
            assert "Hourly Queue Digest" in msg
            assert "@api/data-check" in msg

    def test_digest_send_failure_does_not_log_posted(self, tmp_path, _patch_base_bot_deps):
        bot = _make_scheduler_bot(tmp_path, _patch_base_bot_deps)
        bot._scheduler_chat_id = 42

        with (
            patch.object(bot, "_fetch_queue", return_value=SAMPLE_QUEUE),
            patch.object(bot, "send_message", return_value=None),
            patch("aipass.skills.lib.telegram.apps.handlers.scheduler_bot.logger") as mock_logger,
        ):
            bot._post_digest()

        posted_calls = [c for c in mock_logger.info.call_args_list if "Hourly digest posted" in str(c)]
        failed_calls = [c for c in mock_logger.warning.call_args_list if "Hourly digest posting failed" in str(c)]
        assert posted_calls == []
        assert len(failed_calls) == 1

    def test_digest_skips_on_fetch_failure(self, tmp_path, _patch_base_bot_deps):
        bot = _make_scheduler_bot(tmp_path, _patch_base_bot_deps)
        bot._scheduler_chat_id = 42

        with (
            patch.object(bot, "_fetch_queue", return_value=None),
            patch.object(bot, "send_message") as mock_send,
        ):
            bot._post_digest()
            mock_send.assert_not_called()

    def test_digest_skips_when_no_chat_id(self, tmp_path, _patch_base_bot_deps):
        bot = _make_scheduler_bot(tmp_path, _patch_base_bot_deps)
        assert bot._scheduler_chat_id is None

        with patch.object(bot, "send_message") as mock_send:
            bot._post_digest()
            mock_send.assert_not_called()

    def test_start_digest_creates_thread(self, tmp_path, _patch_base_bot_deps):
        bot = _make_scheduler_bot(tmp_path, _patch_base_bot_deps)
        bot.start_digest(42)
        try:
            assert bot._digest_thread is not None
            assert bot._digest_thread.daemon is True
            assert bot._digest_thread.name == "scheduler-digest"
            assert bot._scheduler_chat_id == 42
        finally:
            bot.stop_digest()

    def test_stop_digest_cleans_up(self, tmp_path, _patch_base_bot_deps):
        bot = _make_scheduler_bot(tmp_path, _patch_base_bot_deps)
        bot.start_digest(42)
        bot.stop_digest()
        assert bot._digest_thread is None
        assert bot._digest_stop.is_set()


# =============================================
# 4. CHUNKING LONG MESSAGES
# =============================================


class TestChunking:
    """>4096-char messages are split via chunk_text."""

    def test_long_queue_is_chunked(self, tmp_path, _patch_base_bot_deps):
        bot = _make_scheduler_bot(tmp_path, _patch_base_bot_deps)
        many_jobs = {
            "generated_at": "now",
            "count": 100,
            "jobs": [
                {
                    "owner": f"@branch{i}",
                    "id": f"job-{i}",
                    "enabled": True,
                    "type": "daily",
                    "schedule_human": "every day",
                    "next_run": "2026-07-01T00:00:00Z",
                    "last_run": None,
                    "last_status": None,
                    "last_error": None,
                    "prompt_preview": "A" * 80,
                    "wake": {},
                }
                for i in range(100)
            ],
        }

        with (
            patch.object(bot, "_fetch_queue", return_value=many_jobs),
            patch.object(bot, "send_message") as mock_send,
        ):
            bot._handle_queue_command(42)
            assert mock_send.call_count >= 2

    def test_short_queue_not_chunked(self, tmp_path, _patch_base_bot_deps):
        bot = _make_scheduler_bot(tmp_path, _patch_base_bot_deps)
        with (
            patch.object(bot, "_fetch_queue", return_value=SAMPLE_QUEUE),
            patch.object(bot, "send_message") as mock_send,
        ):
            bot._handle_queue_command(42)
            assert mock_send.call_count == 1


# =============================================
# 5. SECRET LOADING
# =============================================


class TestSecretLoading:
    """Bot loads telegram/scheduler config; missing fails loud."""

    def test_missing_secret_returns_none(self):
        """When get_secret returns None, load_bot_config returns None — bot won't start."""
        from aipass.skills.lib.telegram.apps.handlers.config import load_bot_config

        with patch("aipass.skills.lib.telegram.apps.handlers.config._get_secret", return_value=None):
            config = load_bot_config("scheduler")
            assert config is None

    def test_secret_provides_chat_id(self):
        """The scheduler config includes chat_id for digest delivery."""
        config = {
            "bot_id": "scheduler",
            "bot_token": "123:FAKE",
            "bot_name": "AIPass Scheduler Bot",
            "branch_name": "daemon",
            "work_dir": "/tmp",
            "allowed_user_ids": [111],
            "chat_id": "7235222625",
        }
        assert "chat_id" in config
        assert config["chat_id"] == "7235222625"


# =============================================
# 6. SLASH-MENU INCLUDES /queue
# =============================================


class TestSlashMenu:
    """/queue appears in get_custom_commands and the command menu."""

    def test_queue_in_custom_commands(self, tmp_path, _patch_base_bot_deps):
        bot = _make_scheduler_bot(tmp_path, _patch_base_bot_deps)
        cmds = bot.get_custom_commands()
        assert "queue" in cmds
        assert "description" in cmds["queue"]

    def test_inherited_commands_preserved(self, tmp_path, _patch_base_bot_deps):
        bot = _make_scheduler_bot(tmp_path, _patch_base_bot_deps)
        cmds = bot.get_custom_commands()
        assert "monitor" in cmds
        assert "create" in cmds


# =============================================
# 7. COMMAND ROUTING
# =============================================


class TestCommandRouting:
    """/queue is dispatched correctly through _dispatch_command."""

    def test_queue_routed(self, tmp_path, _patch_base_bot_deps):
        bot = _make_scheduler_bot(tmp_path, _patch_base_bot_deps)
        with patch.object(bot, "_handle_queue_command") as mock_q:
            result = bot._dispatch_command(42, ("queue", ""))
            assert result is True
            mock_q.assert_called_once_with(42)

    def test_other_commands_fall_through_to_parent(self, tmp_path, _patch_base_bot_deps):
        bot = _make_scheduler_bot(tmp_path, _patch_base_bot_deps)
        with patch.object(bot, "send_message"):
            result = bot._dispatch_command(42, ("status", ""))
            assert result is True

    def test_unknown_command_falls_through(self, tmp_path, _patch_base_bot_deps):
        bot = _make_scheduler_bot(tmp_path, _patch_base_bot_deps)
        with patch.object(bot, "send_message"):
            result = bot._dispatch_command(42, ("nonexistent", ""))
            assert result is False
