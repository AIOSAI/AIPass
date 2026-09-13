"""
Tests for multi-bot Telegram architecture (v2).

Covers:
1. tmux_manager.py (v1.1.0) - bot_id awareness via AIPASS_BOT_ID env var
2. telegram_response.py (v2.2.0) - v2 pending file matching with v1 fallback

All subprocess (tmux) and urllib (Telegram API) calls are mocked.
"""

import json
import time
import pytest
from unittest.mock import patch, MagicMock

from aipass.skills.lib.telegram.apps.handlers import tmux_manager as tg_tmux

try:
    from aipass.hooks.apps.handlers.notification import telegram_response as tg_hook
except ImportError:
    from unittest.mock import MagicMock

    tg_hook = MagicMock()


# ============================================================
# FIXTURES
# ============================================================


@pytest.fixture(autouse=True)
def _isolate_pending_dir(tmp_path, monkeypatch):
    """Redirect PENDING_DIR to tmp_path for every test."""
    pending = tmp_path / "telegram_pending"
    pending.mkdir()
    monkeypatch.setattr(tg_hook, "PENDING_DIR", pending)
    return pending


@pytest.fixture
def pending_dir(_isolate_pending_dir):
    """Convenience accessor for the isolated pending dir."""
    return _isolate_pending_dir


def _write_pending(pending_dir, filename, data):
    """Helper: write a pending JSON file."""
    path = pending_dir / filename
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _make_subprocess_result(returncode=0, stdout="", stderr=""):
    """Helper: build a mock subprocess.CompletedProcess."""
    result = MagicMock()
    result.returncode = returncode
    result.stdout = stdout
    result.stderr = stderr
    return result


# ============================================================
# TMUX MANAGER TESTS
# ============================================================


class TestTmuxSessionExists:
    """Tests for tmux_manager.session_exists."""

    @patch("aipass.skills.lib.telegram.apps.handlers.tmux_manager.subprocess.run")
    def test_session_exists_returns_true(self, mock_run):
        """session_exists returns True when tmux has-session succeeds."""
        mock_run.return_value = _make_subprocess_result(returncode=0)

        assert tg_tmux.session_exists("dev_central") is True
        mock_run.assert_called_once_with(
            ["tmux", "has-session", "-t", "telegram-dev_central"],
            capture_output=True,
        )

    @patch("aipass.skills.lib.telegram.apps.handlers.tmux_manager.subprocess.run")
    def test_session_exists_returns_false(self, mock_run):
        """session_exists returns False when tmux has-session fails."""
        mock_run.return_value = _make_subprocess_result(returncode=1)

        assert tg_tmux.session_exists("nonexistent") is False


class TestTmuxKillSession:
    """Tests for tmux_manager.kill_session."""

    @patch("aipass.skills.lib.telegram.apps.handlers.tmux_manager.subprocess.run")
    def test_kill_session_returns_true(self, mock_run):
        """kill_session returns True when session exists and is killed."""
        mock_run.side_effect = [
            _make_subprocess_result(returncode=0),  # has-session: exists
            _make_subprocess_result(returncode=0),  # kill-session: success
        ]

        assert tg_tmux.kill_session("dev_central") is True
        kill_call = mock_run.call_args_list[1]
        assert kill_call[0][0] == ["tmux", "kill-session", "-t", "telegram-dev_central"]

    @patch("aipass.skills.lib.telegram.apps.handlers.tmux_manager.subprocess.run")
    def test_kill_session_returns_true_when_not_exists(self, mock_run):
        """kill_session returns True when session doesn't exist (nothing to kill)."""
        mock_run.return_value = _make_subprocess_result(returncode=1)  # has-session: not found

        assert tg_tmux.kill_session("nonexistent") is True


class TestTmuxListSessions:
    """Tests for tmux_manager.list_sessions."""

    @patch("aipass.skills.lib.telegram.apps.handlers.tmux_manager.subprocess.run")
    def test_list_sessions_filters_telegram_prefix(self, mock_run):
        """list_sessions returns only branch names from telegram-* sessions."""
        mock_run.return_value = _make_subprocess_result(
            returncode=0, stdout="telegram-dev_central\ntelegram-flow\nother-session\nrandom\n"
        )

        result = tg_tmux.list_sessions()

        assert result == ["dev_central", "flow"]

    @patch("aipass.skills.lib.telegram.apps.handlers.tmux_manager.subprocess.run")
    def test_list_sessions_returns_empty_on_failure(self, mock_run):
        """list_sessions returns [] when tmux command fails."""
        mock_run.return_value = _make_subprocess_result(returncode=1)

        assert tg_tmux.list_sessions() == []


# ============================================================
# TELEGRAM RESPONSE - FIND_PENDING_FILE TESTS
# ============================================================


class TestFindPendingFileV2:
    """Tests for v2 multi-bot matching in find_pending_file."""

    def test_v2_match_by_bot_id_env_var(self, pending_dir, monkeypatch):
        """v2 P1: AIPASS_BOT_ID env var matches bot-{bot_id}.json."""
        monkeypatch.setenv("AIPASS_BOT_ID", "mybot42")

        data = {
            "bot_id": "mybot42",
            "chat_id": 123,
            "bot_token": "tok",
            "timestamp": time.time(),
        }
        _write_pending(pending_dir, "bot-mybot42.json", data)

        with patch("aipass.hooks.apps.handlers.notification.telegram_response.subprocess.run"):
            result = tg_hook.find_pending_file("session-xyz")

        assert result is not None
        assert result.name == "bot-mybot42.json"

    def test_v2_match_by_cwd_relative_to(self, pending_dir, monkeypatch, tmp_path):
        """v2 P2: CWD relative_to work_dir matches bot-*.json."""
        monkeypatch.delenv("AIPASS_BOT_ID", raising=False)

        work_dir = tmp_path / "some" / "workspace"
        work_dir.mkdir(parents=True)
        cwd = work_dir / "subdir"
        cwd.mkdir()

        data = {
            "bot_id": "alpha",
            "work_dir": str(work_dir),
            "chat_id": 123,
            "bot_token": "tok",
            "timestamp": time.time(),
        }
        _write_pending(pending_dir, "bot-alpha.json", data)

        monkeypatch.chdir(cwd)

        with patch("aipass.hooks.apps.handlers.notification.telegram_response.subprocess.run"):
            result = tg_hook.find_pending_file("session-xyz")

        assert result is not None
        assert result.name == "bot-alpha.json"

    def test_returns_none_when_no_match(self, pending_dir, monkeypatch, tmp_path):
        """find_pending_file returns None when nothing matches."""
        monkeypatch.delenv("AIPASS_BOT_ID", raising=False)

        unrelated_dir = tmp_path / "nowhere"
        unrelated_dir.mkdir()
        monkeypatch.chdir(unrelated_dir)

        # Write a file that won't match by session_id either
        data = {
            "session_id": "different-session",
            "chat_id": 123,
            "bot_token": "tok",
            "timestamp": time.time(),
        }
        _write_pending(pending_dir, "telegram-something.json", data)

        result = tg_hook.find_pending_file("no-match-session")

        assert result is None

    def test_skips_expired_files(self, pending_dir, monkeypatch, tmp_path):
        """find_pending_file skips expired files (v1 10-min TTL)."""
        monkeypatch.delenv("AIPASS_BOT_ID", raising=False)

        branch_dir = tmp_path / "stale_branch"
        branch_dir.mkdir()
        monkeypatch.chdir(branch_dir)

        # Timestamp 20 minutes ago (expired for v1 10-min TTL)
        data = {
            "chat_id": 123,
            "bot_token": "tok",
            "timestamp": time.time() - 1200,
        }
        _write_pending(pending_dir, "telegram-stale_branch.json", data)

        result = tg_hook.find_pending_file("session-xyz")

        assert result is None


# ============================================================
# TELEGRAM RESPONSE - _IS_EXPIRED TESTS
# ============================================================


class TestIsExpired:
    """Tests for _is_expired TTL logic."""

    def test_v2_uses_1hr_ttl(self):
        """v2 files (with bot_id) use 1-hour TTL."""
        # 30 minutes old — should NOT be expired under 1hr TTL
        data = {
            "bot_id": "mybot",
            "timestamp": time.time() - 1800,
        }
        with patch("aipass.hooks.apps.handlers.notification.telegram_response.subprocess.run"):
            assert tg_hook._is_expired(data) is False

    def test_within_ttl_not_expired(self):
        """File within 1-hour TTL is not expired."""
        data = {
            "timestamp": time.time() - 300,  # 5 minutes
        }
        assert tg_hook._is_expired(data) is False

    def test_v2_expired_past_1hr(self):
        """v2 file past 1-hour TTL is expired when tmux is dead."""
        data = {
            "bot_id": "mybot",
            "timestamp": time.time() - 7200,  # 2 hours
        }
        with patch("aipass.hooks.apps.handlers.notification.telegram_response.subprocess.run") as mock_sub:
            mock_sub.return_value = _make_subprocess_result(returncode=1)
            assert tg_hook._is_expired(data) is True

    def test_not_expired_when_tmux_alive(self):
        """Even past TTL, not expired when tmux session is still alive."""
        data = {
            "bot_id": "mybot",
            "session_name": "telegram-dev_central",
            "timestamp": time.time() - 7200,  # 2 hours ago (past 1hr TTL)
        }
        with patch("aipass.hooks.apps.handlers.notification.telegram_response.subprocess.run") as mock_sub:
            # tmux has-session -> success (session alive)
            mock_sub.return_value = _make_subprocess_result(returncode=0)
            assert tg_hook._is_expired(data) is False


# ============================================================
# TELEGRAM RESPONSE - EXTRACT_ASSISTANT_RESPONSE TESTS
# ============================================================


class TestExtractAssistantResponse:
    """Tests for extract_assistant_response JSONL parsing."""

    def _make_jsonl(self, tmp_path, entries):
        """Helper: write entries as JSONL and return the path."""
        path = tmp_path / "transcript.jsonl"
        lines = [json.dumps(e) for e in entries]
        path.write_text("\n".join(lines), encoding="utf-8")
        return str(path)

    def test_skips_sidechain_entries(self, tmp_path):
        """extract_assistant_response skips isSidechain entries."""
        entries = [
            {
                "type": "user",
                "message": {"content": [{"type": "text", "text": "hello"}]},
            },
            {
                "type": "assistant",
                "isSidechain": True,
                "message": {"content": [{"type": "text", "text": "sidechain noise"}]},
            },
            {
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": "real response"}]},
            },
        ]
        path = self._make_jsonl(tmp_path, entries)
        result = tg_hook.extract_assistant_response(path)

        assert result == "real response"
        assert "sidechain" not in result

    def test_uses_start_line_for_position_tracking(self, tmp_path):
        """extract_assistant_response uses start_line to skip earlier content."""
        entries = [
            # Line 0: old user message
            {
                "type": "user",
                "message": {"content": [{"type": "text", "text": "old question"}]},
            },
            # Line 1: old assistant response
            {
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": "old answer"}]},
            },
            # Line 2: new user message (injected via bridge)
            {
                "type": "user",
                "message": {"content": [{"type": "text", "text": "new question"}]},
            },
            # Line 3: new assistant response
            {
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": "new answer"}]},
            },
        ]
        path = self._make_jsonl(tmp_path, entries)

        # start_line=2 means only look from line 2 onward
        result = tg_hook.extract_assistant_response(path, start_line=2)

        assert result == "new answer"

    def test_returns_none_for_missing_file(self, tmp_path):
        """extract_assistant_response returns None when file doesn't exist."""
        result = tg_hook.extract_assistant_response(str(tmp_path / "nope.jsonl"))
        assert result is None

    def test_returns_none_for_empty_transcript(self, tmp_path):
        """extract_assistant_response returns None for empty file."""
        path = tmp_path / "empty.jsonl"
        path.write_text("", encoding="utf-8")
        result = tg_hook.extract_assistant_response(str(path))
        assert result is None


# ============================================================
# TELEGRAM RESPONSE - CHUNK_TEXT TESTS
# ============================================================


class TestChunkText:
    """Tests for chunk_text splitting logic."""

    def test_splits_at_sentence_boundaries(self):
        """chunk_text splits at sentence boundaries when possible."""
        # Build text that exceeds the limit
        sentence_a = "First sentence. " * 30  # ~480 chars
        sentence_b = "Second sentence. " * 30  # ~510 chars
        text = sentence_a.strip() + " " + sentence_b.strip()

        chunks = tg_hook.chunk_text(text, limit=500)

        assert len(chunks) >= 2
        # First chunk should end at a sentence boundary (ends with '.')
        assert chunks[0].rstrip().endswith(".")

    def test_returns_single_chunk_for_short_text(self):
        """chunk_text returns single chunk when text is within limit."""
        text = "Short message."
        chunks = tg_hook.chunk_text(text, limit=4096)

        assert chunks == ["Short message."]

    def test_handles_exact_limit(self):
        """chunk_text returns single chunk when text equals limit exactly."""
        text = "x" * 100
        chunks = tg_hook.chunk_text(text, limit=100)

        assert chunks == [text]

    def test_hard_break_when_no_boundaries(self):
        """chunk_text does a hard break when no natural boundaries exist."""
        # No spaces, no newlines, no sentence punctuation
        text = "a" * 200
        chunks = tg_hook.chunk_text(text, limit=100)

        assert len(chunks) == 2
        assert len(chunks[0]) == 100
        assert len(chunks[1]) == 100


# ============================================================
# A HOST WITHOUT TMUX (FPLAN-0554 round three)
# ============================================================


class TestTmuxManagerWithoutTmux:
    """session_exists is called BEFORE the try in send_message, kill_session and
    get_session_pane, so a raise there escaped all three."""

    @patch(
        "aipass.skills.lib.telegram.apps.handlers.tmux_manager.subprocess.run",
        side_effect=FileNotFoundError("tmux"),
    )
    def test_session_exists_is_false(self, mock_run):
        assert tg_tmux.session_exists("dev_central") is False
        assert mock_run.call_count == 1

    @patch(
        "aipass.skills.lib.telegram.apps.handlers.tmux_manager.subprocess.run",
        side_effect=FileNotFoundError("tmux"),
    )
    def test_kill_session_has_nothing_to_kill(self, mock_run):
        assert tg_tmux.kill_session("dev_central") is True
        assert mock_run.call_count == 1

    @patch(
        "aipass.skills.lib.telegram.apps.handlers.tmux_manager.subprocess.run",
        side_effect=FileNotFoundError("tmux"),
    )
    def test_get_session_pane_is_none(self, mock_run):
        assert tg_tmux.get_session_pane("dev_central") is None
        assert mock_run.call_count == 1

    @patch(
        "aipass.skills.lib.telegram.apps.handlers.tmux_manager.subprocess.run",
        side_effect=FileNotFoundError("tmux"),
    )
    def test_send_message_is_false(self, mock_run):
        import asyncio

        assert asyncio.run(tg_tmux.send_message("dev_central", "hello")) is False
        assert mock_run.call_count == 1

    def test_send_rename_reaches_exec_and_does_not_raise(self, monkeypatch):
        monkeypatch.setattr(tg_tmux, "RENAME_DELAY", 0)
        with patch(
            "aipass.skills.lib.telegram.apps.handlers.tmux_manager.subprocess.run",
            side_effect=FileNotFoundError("tmux"),
        ) as mock_run:
            tg_tmux._send_rename("telegram-dev_central", "dev_central")
        assert mock_run.call_count == 1
