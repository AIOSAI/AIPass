# =================== AIPass ====================
# Name: test_telegram_response_mirror.py
# Description: telegram_response's mirror lane: never-expired mirror files, turn extraction, handle() and cursor
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-08
# =============================================

"""Tests for apps/handlers/notification/telegram_response.py: its mirror lane."""

# Mirror sessions relay terminal turns to Telegram from a persistent mapping
# file. handle() for dispatched sessions is test_telegram_response.py; the
# delivery helpers are test_telegram_response_delivery.py.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that telegram_response.py parses and imports, ruff and collection cover it

import json
import time
from pathlib import Path
from unittest.mock import patch

from aipass.hooks.apps.handlers.notification.telegram_response import (
    _advance_pending,
    extract_mirror_turn,
    find_pending_file,
    handle,
)
from aipass.hooks.tests.support_telegram_response import (
    LOGGER_PATCH,
    MOD,
    _found,
    _jsonl_line,
    _kept_redirect,
    _ok_result,
    _record_waits,
)


def _mirrored_user(tmp_path: Path, content: object) -> str | None:
    """The user line extract_mirror_turn shows for a user entry holding content, None when it shows none."""
    transcript = tmp_path / "mirror.jsonl"
    user = json.dumps({"type": "user", "message": {"content": content}})
    transcript.write_text(f"{user}\n{_jsonl_line('assistant', 'Reply')}\n", encoding="utf-8")
    with patch(LOGGER_PATCH):
        turn = extract_mirror_turn(str(transcript))
    assert turn is not None and turn.endswith("Reply")
    head = turn.removesuffix("Reply").strip()
    return head.removeprefix("You: ") if head else None


# ===========================================================================
# _is_expired — mirror files
# ===========================================================================


class TestIsExpiredMirror:
    """Mirror files are never expired."""

    def test_mirror_file_never_expired(self, tmp_path):
        assert _found(tmp_path, {"timestamp": 0, "mirror": True}) is True

    def test_mirror_file_old_timestamp_not_expired(self, tmp_path):
        assert _found(tmp_path, {"timestamp": 1000, "mirror": True}) is True


# ===========================================================================
# _extract_user_text
# ===========================================================================


class TestExtractUserText:
    """User message text extraction, read as the "You:" line extract_mirror_turn shows."""

    def test_text_block(self, tmp_path):
        content = [{"type": "text", "text": "Hello world"}]
        assert _mirrored_user(tmp_path, content) == "Hello world"

    def test_tool_result_only_returns_none(self, tmp_path):
        content = [{"type": "tool_result", "content": "ok"}]
        assert _mirrored_user(tmp_path, content) is None

    def test_string_content(self, tmp_path):
        assert _mirrored_user(tmp_path, " Hello ") == "Hello"

    def test_empty_string_returns_none(self, tmp_path):
        assert _mirrored_user(tmp_path, "") is None

    def test_empty_list_returns_none(self, tmp_path):
        assert _mirrored_user(tmp_path, []) is None

    def test_non_list_non_string_returns_none(self, tmp_path):
        assert _mirrored_user(tmp_path, 42) is None

    def test_mixed_text_and_tool_result(self, tmp_path):
        content = [{"type": "text", "text": "Question"}, {"type": "tool_result", "content": "ok"}]
        assert _mirrored_user(tmp_path, content) == "Question"


# ===========================================================================
# extract_mirror_turn
# ===========================================================================


class TestExtractMirrorTurn:
    """Mirror transcript extraction — user input + assistant response."""

    def test_single_turn_user_and_assistant(self, tmp_path):
        transcript = tmp_path / "transcript.jsonl"
        lines = [
            _jsonl_line("user", "What is AIPass?"),
            _jsonl_line("assistant", "AIPass is a multi-agent framework."),
        ]
        transcript.write_text("\n".join(lines), encoding="utf-8")

        with patch(LOGGER_PATCH):
            result = extract_mirror_turn(str(transcript))

        assert result == "You: What is AIPass?\n\nAIPass is a multi-agent framework."

    def test_multiple_turns_separated_by_divider(self, tmp_path):
        transcript = tmp_path / "transcript.jsonl"
        lines = [
            _jsonl_line("user", "First question"),
            _jsonl_line("assistant", "First answer"),
            _jsonl_line("user", "Second question"),
            _jsonl_line("assistant", "Second answer"),
        ]
        transcript.write_text("\n".join(lines), encoding="utf-8")

        with patch(LOGGER_PATCH):
            result = extract_mirror_turn(str(transcript))

        assert result == "You: First question\n\nFirst answer\n\n---\n\nYou: Second question\n\nSecond answer"

    def test_sidechain_entries_skipped(self, tmp_path):
        transcript = tmp_path / "transcript.jsonl"
        lines = [
            _jsonl_line("user", "Real question"),
            _jsonl_line("assistant", "Sidechain noise", sidechain=True),
            _jsonl_line("assistant", "Real answer"),
        ]
        transcript.write_text("\n".join(lines), encoding="utf-8")

        with patch(LOGGER_PATCH):
            result = extract_mirror_turn(str(transcript))

        assert result == "You: Real question\n\nReal answer"

    def test_tool_result_user_messages_skipped(self, tmp_path):
        transcript = tmp_path / "transcript.jsonl"
        lines = [
            _jsonl_line("user", "Real question"),
            _jsonl_line("assistant", "Working on it..."),
            _jsonl_line("user", tool_result=True),
            _jsonl_line("assistant", "Done with the work"),
        ]
        transcript.write_text("\n".join(lines), encoding="utf-8")

        with patch(LOGGER_PATCH):
            result = extract_mirror_turn(str(transcript))

        # tool_result should not create a second turn
        assert result == "You: Real question\n\nWorking on it...\n\nDone with the work"

    def test_start_line_skips_old_entries(self, tmp_path):
        transcript = tmp_path / "transcript.jsonl"
        lines = [
            _jsonl_line("user", "Old question"),
            _jsonl_line("assistant", "Old answer"),
            _jsonl_line("user", "New question"),
            _jsonl_line("assistant", "New answer"),
        ]
        transcript.write_text("\n".join(lines), encoding="utf-8")

        with patch(LOGGER_PATCH):
            result = extract_mirror_turn(str(transcript), start_line=2)

        assert result == "You: New question\n\nNew answer"

    def test_no_new_entries_returns_none(self, tmp_path):
        transcript = tmp_path / "transcript.jsonl"
        lines = [
            _jsonl_line("user", "Question"),
            _jsonl_line("assistant", "Answer"),
        ]
        transcript.write_text("\n".join(lines), encoding="utf-8")

        with patch(LOGGER_PATCH):
            result = extract_mirror_turn(str(transcript), start_line=2)

        assert result is None

    def test_missing_transcript_returns_none(self, tmp_path):
        with patch(LOGGER_PATCH):
            result = extract_mirror_turn(str(tmp_path / "nonexistent" / "path.jsonl"))

        assert result is None

    def test_corrupt_lines_skipped(self, tmp_path):
        transcript = tmp_path / "transcript.jsonl"
        lines = [
            _jsonl_line("user", "Question"),
            "this is {{{ not json",
            _jsonl_line("assistant", "Answer"),
        ]
        transcript.write_text("\n".join(lines), encoding="utf-8")

        with patch(LOGGER_PATCH):
            result = extract_mirror_turn(str(transcript))

        assert result == "You: Question\n\nAnswer"

    def test_assistant_only_no_user_text(self, tmp_path):
        """Assistant text after cursor with no user message — still delivered."""
        transcript = tmp_path / "transcript.jsonl"
        lines = [
            _jsonl_line("assistant", "Continuation text"),
        ]
        transcript.write_text("\n".join(lines), encoding="utf-8")

        with patch(LOGGER_PATCH):
            result = extract_mirror_turn(str(transcript))

        assert result == "Continuation text"

    def test_stale_cursor_clamps_to_latest_turn(self, tmp_path):
        """Cursor ahead of transcript self-heals by clamping to latest turn."""
        transcript = tmp_path / "transcript.jsonl"
        lines = [
            _jsonl_line("user", "Old question"),
            _jsonl_line("assistant", "Old answer"),
            _jsonl_line("user", "Latest question"),
            _jsonl_line("assistant", "Latest answer"),
        ]
        transcript.write_text("\n".join(lines), encoding="utf-8")

        with patch(LOGGER_PATCH):
            result = extract_mirror_turn(str(transcript), start_line=50)

        assert result == "You: Latest question\n\nLatest answer"

    def test_stale_cursor_no_user_msg_delivers_all(self, tmp_path):
        """Stale cursor with no user messages — delivers all assistant text."""
        transcript = tmp_path / "transcript.jsonl"
        lines = [
            _jsonl_line("assistant", "Some output"),
        ]
        transcript.write_text("\n".join(lines), encoding="utf-8")

        with patch(LOGGER_PATCH):
            result = extract_mirror_turn(str(transcript), start_line=99)

        assert result == "Some output"


# ===========================================================================
# find_pending_file — mirror directory
# ===========================================================================


class TestFindPendingFileMirror:
    """Mirror directory search for persistent mapping files."""

    def test_mirror_dir_env_bot_id_match(self, tmp_path):
        mirror_dir = tmp_path / "telegram_bots"
        mirror_dir.mkdir()
        data = {"timestamp": time.time(), "work_dir": str(tmp_path), "mirror": True}
        (mirror_dir / "bot-42.json").write_text(json.dumps(data), encoding="utf-8")

        with (
            patch(LOGGER_PATCH),
            patch(f"{MOD}.MIRROR_DIR", mirror_dir),
            patch(f"{MOD}.PENDING_DIR", tmp_path / "nonexistent"),
            patch.dict("os.environ", {"AIPASS_BOT_ID": "42"}),
        ):
            result = find_pending_file()

        assert result is not None
        assert result.name == "bot-42.json"

    def test_mirror_dir_preferred_over_pending_for_env(self, tmp_path):
        """Mirror dir is checked before pending dir for AIPASS_BOT_ID match."""
        mirror_dir = tmp_path / "telegram_bots"
        mirror_dir.mkdir()
        pending_dir = tmp_path / "telegram_pending"
        pending_dir.mkdir()
        mirror_data = {"timestamp": time.time(), "work_dir": str(tmp_path), "mirror": True}
        pending_data = {"timestamp": time.time(), "work_dir": str(tmp_path)}
        (mirror_dir / "bot-42.json").write_text(json.dumps(mirror_data), encoding="utf-8")
        (pending_dir / "bot-42.json").write_text(json.dumps(pending_data), encoding="utf-8")

        with (
            patch(LOGGER_PATCH),
            patch(f"{MOD}.MIRROR_DIR", mirror_dir),
            patch(f"{MOD}.PENDING_DIR", pending_dir),
            patch.dict("os.environ", {"AIPASS_BOT_ID": "42"}),
        ):
            result = find_pending_file()

        assert result == mirror_dir / "bot-42.json"

    def test_mirror_dir_cwd_match(self, tmp_path, monkeypatch):
        mirror_dir = tmp_path / "telegram_bots"
        mirror_dir.mkdir()
        work = tmp_path / "project"
        (work / "subdir").mkdir(parents=True)
        data = {"timestamp": time.time(), "work_dir": str(work), "mirror": True}
        (mirror_dir / "bot-7.json").write_text(json.dumps(data), encoding="utf-8")
        monkeypatch.chdir(work / "subdir")

        with (
            patch(LOGGER_PATCH),
            patch(f"{MOD}.MIRROR_DIR", mirror_dir),
            patch(f"{MOD}.PENDING_DIR", tmp_path / "nonexistent"),
            patch.dict("os.environ", _kept_redirect(), clear=True),
        ):
            result = find_pending_file()

        assert result is not None
        assert result.name == "bot-7.json"


# ===========================================================================
# handle — mirror integration tests
# ===========================================================================


class TestHandleMirrorIntegration:
    """Full handle() flow for mirror sessions."""

    def test_mirror_user_typed_directly_delivered(self, tmp_path, monkeypatch):
        """User types directly in terminal — mirror delivers to TG."""
        monkeypatch.chdir(tmp_path)
        transcript = tmp_path / "transcript.jsonl"
        lines = [
            _jsonl_line("user", "Old question"),
            _jsonl_line("assistant", "Old answer"),
            _jsonl_line("user", "What is this?"),
            _jsonl_line("assistant", "This is the answer."),
        ]
        transcript.write_text("\n".join(lines), encoding="utf-8")

        mirror_dir = tmp_path / "telegram_bots"
        mirror_dir.mkdir()
        mirror_data = {
            "chat_id": 999,
            "bot_token": "tok:ABC",
            "session_name": "devpulse",
            "work_dir": str(tmp_path),
            "mirror": True,
            "transcript_line_after": 2,
        }
        mirror_file = mirror_dir / "bot-1.json"
        mirror_file.write_text(json.dumps(mirror_data), encoding="utf-8")

        sent_texts = []

        def capture_send(bot_token, chat_id, text):
            sent_texts.append(text)
            return _ok_result()

        with (
            patch(LOGGER_PATCH),
            patch(f"{MOD}.find_pending_file", return_value=mirror_file),
            patch(f"{MOD}._send_with_retry", side_effect=capture_send),
            patch(f"{MOD}._check_log_streamer_active", return_value=False),
            patch(f"{MOD}._write_delivery_log"),
        ):
            result = handle(
                {
                    "hook_event_name": "Stop",
                    "session_id": "session-abc",
                    "transcript_path": str(transcript),
                }
            )

        assert result == {"stdout": "", "exit_code": 0, "sound": "telegram response"}
        assert len(sent_texts) == 1
        assert "You: What is this?" in sent_texts[0]
        assert "This is the answer." in sent_texts[0]

    def test_mirror_tg_injected_no_double_send(self, tmp_path, monkeypatch):
        """TG-injected turn — cursor advancement prevents re-delivery."""
        monkeypatch.chdir(tmp_path)
        waits = _record_waits(monkeypatch)
        transcript = tmp_path / "transcript.jsonl"
        lines = [
            _jsonl_line("user", "Injected from TG"),
            _jsonl_line("assistant", "Response to TG"),
        ]
        transcript.write_text("\n".join(lines), encoding="utf-8")

        mirror_dir = tmp_path / "telegram_bots"
        mirror_dir.mkdir()
        mirror_data = {
            "chat_id": 999,
            "bot_token": "tok:ABC",
            "session_name": "devpulse",
            "work_dir": str(tmp_path),
            "mirror": True,
            "transcript_line_after": 2,
            "delivered": True,
        }
        mirror_file = mirror_dir / "bot-1.json"
        mirror_file.write_text(json.dumps(mirror_data), encoding="utf-8")

        with (
            patch(LOGGER_PATCH),
            patch(f"{MOD}.find_pending_file", return_value=mirror_file),
            patch(f"{MOD}._check_log_streamer_active", return_value=False),
        ):
            result = handle(
                {
                    "hook_event_name": "Stop",
                    "session_id": "session-abc",
                    "transcript_path": str(transcript),
                }
            )

        assert result == {"stdout": "", "exit_code": 0}
        assert mirror_file.exists()
        assert waits == [0.2, 0.5]

    def test_mirror_cursor_advances_no_redelivery(self, tmp_path, monkeypatch):
        """Cursor advances after mirror delivery — old turns not re-sent."""
        monkeypatch.chdir(tmp_path)
        transcript = tmp_path / "transcript.jsonl"
        lines = [
            _jsonl_line("user", "Question"),
            _jsonl_line("assistant", "Answer"),
        ]
        transcript.write_text("\n".join(lines), encoding="utf-8")

        mirror_dir = tmp_path / "telegram_bots"
        mirror_dir.mkdir()
        mirror_data = {
            "chat_id": 999,
            "bot_token": "tok:ABC",
            "session_name": "devpulse",
            "work_dir": str(tmp_path),
            "mirror": True,
            "transcript_line_after": 0,
        }
        mirror_file = mirror_dir / "bot-1.json"
        mirror_file.write_text(json.dumps(mirror_data), encoding="utf-8")

        with (
            patch(LOGGER_PATCH),
            patch(f"{MOD}.find_pending_file", return_value=mirror_file),
            patch(f"{MOD}._send_with_retry", return_value=_ok_result()),
            patch(f"{MOD}._check_log_streamer_active", return_value=False),
            patch(f"{MOD}._write_delivery_log"),
        ):
            handle(
                {
                    "hook_event_name": "Stop",
                    "session_id": "session-abc",
                    "transcript_path": str(transcript),
                }
            )

        updated = json.loads(mirror_file.read_text(encoding="utf-8"))
        assert updated["transcript_line_after"] == 2
        assert updated["delivered"] is True
        assert mirror_file.exists()

    def test_mirror_file_never_deleted_on_error(self, tmp_path):
        """Mirror mapping files are never deleted, even on validation errors."""
        mirror_dir = tmp_path / "telegram_bots"
        mirror_dir.mkdir()
        mirror_data = {
            "mirror": True,
            "session_name": "devpulse",
            "work_dir": str(tmp_path),
        }
        mirror_file = mirror_dir / "bot-1.json"
        mirror_file.write_text(json.dumps(mirror_data), encoding="utf-8")

        with patch(LOGGER_PATCH), patch(f"{MOD}.find_pending_file", return_value=mirror_file):
            handle(
                {
                    "hook_event_name": "Stop",
                    "session_id": "session-abc",
                }
            )

        assert mirror_file.exists()

    def test_mirror_no_processing_message_sends_fresh(self, tmp_path, monkeypatch):
        """Mirror sessions have no processing_message_id — always send fresh."""
        monkeypatch.chdir(tmp_path)
        transcript = tmp_path / "transcript.jsonl"
        lines = [
            _jsonl_line("user", "Hello"),
            _jsonl_line("assistant", "Hi there"),
        ]
        transcript.write_text("\n".join(lines), encoding="utf-8")

        mirror_dir = tmp_path / "telegram_bots"
        mirror_dir.mkdir()
        mirror_data = {
            "chat_id": 999,
            "bot_token": "tok:ABC",
            "session_name": "devpulse",
            "work_dir": str(tmp_path),
            "mirror": True,
            "transcript_line_after": 0,
        }
        mirror_file = mirror_dir / "bot-1.json"
        mirror_file.write_text(json.dumps(mirror_data), encoding="utf-8")

        with (
            patch(LOGGER_PATCH),
            patch(f"{MOD}.find_pending_file", return_value=mirror_file),
            patch(f"{MOD}._send_with_retry", return_value=_ok_result()) as mock_send,
            patch(f"{MOD}.edit_telegram_message") as mock_edit,
            patch(f"{MOD}._check_log_streamer_active", return_value=False),
            patch(f"{MOD}._write_delivery_log"),
        ):
            handle(
                {
                    "hook_event_name": "Stop",
                    "session_id": "session-abc",
                    "transcript_path": str(transcript),
                }
            )

        mock_send.assert_called_once()
        mock_edit.assert_not_called()


# ===========================================================================
# _advance_pending — mirror protection
# ===========================================================================


class TestAdvancePendingMirror:
    """Mirror files are never deleted by _advance_pending."""

    def test_mirror_no_transcript_kept(self, tmp_path):
        pending_file = tmp_path / "pending.json"
        pending_data = {"chat_id": 1, "mirror": True}
        pending_file.write_text(json.dumps(pending_data), encoding="utf-8")

        with patch(LOGGER_PATCH):
            _advance_pending(pending_file, pending_data, "")

        assert pending_file.exists()

    def test_mirror_transcript_failure_kept(self, tmp_path):
        pending_file = tmp_path / "pending.json"
        pending_data = {"chat_id": 1, "mirror": True}
        pending_file.write_text(json.dumps(pending_data), encoding="utf-8")

        with patch(LOGGER_PATCH):
            _advance_pending(pending_file, pending_data, str(tmp_path / "nonexistent" / "transcript.jsonl"))

        assert pending_file.exists()
