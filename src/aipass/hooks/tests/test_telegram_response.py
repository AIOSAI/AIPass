# =================== AIPass ====================
# Name: test_telegram_response.py
# Version: 2.0.0
# Description: Tests for telegram_response notification handler
# Branch: hooks
# Layer: tests
# Created: 2026-06-15
# Modified: 2026-06-29
# =============================================

"""Tests for handlers/notification/telegram_response.py."""

import io
import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

# All tests use local imports per project convention.
# The prax logger is mocked at module level to avoid import-time dependency.
LOGGER_PATCH = "aipass.hooks.apps.handlers.notification.telegram_response.logger"
MOD = "aipass.hooks.apps.handlers.notification.telegram_response"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _jsonl_line(entry_type: str, text: str = "", *, sidechain: bool = False, tool_result: bool = False) -> str:
    """Build a single JSONL transcript line."""
    if tool_result and entry_type == "user":
        content = [{"type": "tool_result", "content": "ok"}]
    elif text:
        content = [{"type": "text", "text": text}]
    else:
        content = []

    entry: dict = {"type": entry_type, "message": {"content": content}}
    if sidechain:
        entry["isSidechain"] = True
    return json.dumps(entry)


def _make_pending(tmp_path: Path, name: str = "bot-123.json", **overrides) -> Path:
    """Create a pending file with sensible defaults."""
    data = {
        "chat_id": 999,
        "bot_token": "tok:ABC",
        "timestamp": time.time(),
        "work_dir": str(tmp_path),
        **overrides,
    }
    path = tmp_path / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _mock_urlopen_ok(message_id=100, text="mocked"):
    """Return a context-manager mock whose read() returns Telegram ok response."""
    resp = MagicMock()
    resp.read.return_value = json.dumps({"ok": True, "result": {"message_id": message_id, "text": text}}).encode()
    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=False)
    return resp


def _mock_urlopen_fail():
    """Return a context-manager mock whose read() returns Telegram not-ok response."""
    resp = MagicMock()
    resp.read.return_value = json.dumps({"ok": False, "description": "bad"}).encode()
    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=False)
    return resp


def _ok_result(message_id=100, text="mocked"):
    """Build a successful send/edit result dict."""
    return {"ok": True, "message_id": message_id, "text": text}


def _fail_result():
    """Build a failed send/edit result dict."""
    return {"ok": False}


# ===========================================================================
# Layer 1 defense — handle() early returns
# ===========================================================================


class TestHandleLayer1Defense:
    """Layer 1: gate-level filtering in handle()."""

    def test_subagent_stop_returns_early(self):
        from aipass.hooks.apps.handlers.notification.telegram_response import handle

        with patch(LOGGER_PATCH):
            result = handle({"hook_event_name": "SubagentStop", "session_id": "abc"})

        assert result == {"stdout": "", "exit_code": 0}

    def test_subagent_transcript_path_returns_early(self):
        from aipass.hooks.apps.handlers.notification.telegram_response import handle

        with patch(LOGGER_PATCH):
            result = handle(
                {
                    "hook_event_name": "Stop",
                    "session_id": "abc",
                    "transcript_path": str(Path.home() / ".claude/sessions/subagents/12345.jsonl"),
                }
            )

        assert result == {"stdout": "", "exit_code": 0}

    def test_no_session_id_returns_early(self):
        from aipass.hooks.apps.handlers.notification.telegram_response import handle

        with patch(LOGGER_PATCH):
            result = handle({"hook_event_name": "Stop"})

        assert result == {"stdout": "", "exit_code": 0}

    def test_no_pending_file_returns_early(self):
        from aipass.hooks.apps.handlers.notification.telegram_response import handle

        with patch(LOGGER_PATCH), patch(f"{MOD}.find_pending_file", return_value=None):
            result = handle({"hook_event_name": "Stop", "session_id": "abc123"})

        assert result == {"stdout": "", "exit_code": 0}


# ===========================================================================
# find_pending_file
# ===========================================================================


class TestFindPendingFile:
    """Multi-bot pending file resolution."""

    def test_env_bot_id_direct_match(self, tmp_path):
        from aipass.hooks.apps.handlers.notification.telegram_response import find_pending_file

        pending_dir = tmp_path / "telegram_pending"
        pending_dir.mkdir()
        data = {"timestamp": time.time(), "work_dir": str(tmp_path)}
        (pending_dir / "bot-42.json").write_text(json.dumps(data), encoding="utf-8")

        with (
            patch(LOGGER_PATCH),
            patch(f"{MOD}.PENDING_DIR", pending_dir),
            patch.dict("os.environ", {"AIPASS_BOT_ID": "42"}),
        ):
            result = find_pending_file("session-xyz")

        assert result is not None
        assert result.name == "bot-42.json"

    def test_cwd_relative_match(self, tmp_path):
        from aipass.hooks.apps.handlers.notification.telegram_response import find_pending_file

        pending_dir = tmp_path / "telegram_pending"
        pending_dir.mkdir()
        work = tmp_path / "project"
        work.mkdir()
        data = {"timestamp": time.time(), "work_dir": str(work)}
        (pending_dir / "bot-7.json").write_text(json.dumps(data), encoding="utf-8")

        with (
            patch(LOGGER_PATCH),
            patch(f"{MOD}.PENDING_DIR", pending_dir),
            patch.dict("os.environ", {}, clear=True),
            patch(f"{MOD}.Path.cwd", return_value=work / "subdir"),
        ):
            result = find_pending_file("session-abc")

        assert result is not None
        assert result.name == "bot-7.json"

    def test_no_pending_dir_returns_none(self, tmp_path):
        from aipass.hooks.apps.handlers.notification.telegram_response import find_pending_file

        missing = tmp_path / "nonexistent"

        with patch(LOGGER_PATCH), patch(f"{MOD}.PENDING_DIR", missing):
            result = find_pending_file("session-abc")

        assert result is None

    def test_expired_pending_skipped(self, tmp_path):
        from aipass.hooks.apps.handlers.notification.telegram_response import find_pending_file

        pending_dir = tmp_path / "telegram_pending"
        pending_dir.mkdir()
        old_ts = time.time() - 7200  # 2 hours ago
        data = {"timestamp": old_ts, "work_dir": str(tmp_path)}
        (pending_dir / "bot-9.json").write_text(json.dumps(data), encoding="utf-8")

        with (
            patch(LOGGER_PATCH),
            patch(f"{MOD}.PENDING_DIR", pending_dir),
            patch.dict("os.environ", {"AIPASS_BOT_ID": "9"}),
            patch(f"{MOD}.subprocess.run") as mock_tmux,
        ):
            mock_tmux.side_effect = OSError("no tmux")
            result = find_pending_file("session-xyz")

        assert result is None

    def test_non_expired_pending_returned(self, tmp_path):
        from aipass.hooks.apps.handlers.notification.telegram_response import find_pending_file

        pending_dir = tmp_path / "telegram_pending"
        pending_dir.mkdir()
        data = {"timestamp": time.time(), "work_dir": str(tmp_path)}
        (pending_dir / "bot-5.json").write_text(json.dumps(data), encoding="utf-8")

        with (
            patch(LOGGER_PATCH),
            patch(f"{MOD}.PENDING_DIR", pending_dir),
            patch.dict("os.environ", {"AIPASS_BOT_ID": "5"}),
        ):
            result = find_pending_file("session-abc")

        assert result is not None
        assert result.name == "bot-5.json"

    def test_no_work_dir_in_pending_skipped(self, tmp_path):
        """When CWD fallback is used and pending has no work_dir, skip it."""
        from aipass.hooks.apps.handlers.notification.telegram_response import find_pending_file

        pending_dir = tmp_path / "telegram_pending"
        pending_dir.mkdir()
        data = {"timestamp": time.time()}  # no work_dir
        (pending_dir / "bot-1.json").write_text(json.dumps(data), encoding="utf-8")

        with patch(LOGGER_PATCH), patch(f"{MOD}.PENDING_DIR", pending_dir), patch.dict("os.environ", {}, clear=True):
            result = find_pending_file("session-abc")

        assert result is None


# ===========================================================================
# _is_expired
# ===========================================================================


class TestIsExpired:
    """TTL + tmux-alive expiry logic."""

    def test_fresh_not_expired(self):
        from aipass.hooks.apps.handlers.notification.telegram_response import _is_expired

        with patch(LOGGER_PATCH):
            assert _is_expired({"timestamp": time.time()}) is False

    def test_old_no_tmux_expired(self):
        from aipass.hooks.apps.handlers.notification.telegram_response import _is_expired

        with patch(LOGGER_PATCH), patch(f"{MOD}.subprocess.run") as mock_run:
            mock_run.side_effect = OSError("no tmux")
            assert _is_expired({"timestamp": time.time() - 7200}) is True

    def test_old_tmux_alive_not_expired(self):
        from aipass.hooks.apps.handlers.notification.telegram_response import _is_expired

        tmux_result = MagicMock()
        tmux_result.returncode = 0

        with patch(LOGGER_PATCH), patch(f"{MOD}.subprocess.run", return_value=tmux_result):
            result = _is_expired(
                {
                    "timestamp": time.time() - 7200,
                    "session_name": "my-session",
                }
            )

        assert result is False

    def test_old_tmux_dead_expired(self):
        from aipass.hooks.apps.handlers.notification.telegram_response import _is_expired

        tmux_result = MagicMock()
        tmux_result.returncode = 1

        with patch(LOGGER_PATCH), patch(f"{MOD}.subprocess.run", return_value=tmux_result):
            result = _is_expired(
                {
                    "timestamp": time.time() - 7200,
                    "session_name": "dead-session",
                }
            )

        assert result is True

    def test_string_timestamp_handling(self):
        from aipass.hooks.apps.handlers.notification.telegram_response import _is_expired

        with patch(LOGGER_PATCH):
            assert _is_expired({"timestamp": str(time.time())}) is False

    def test_invalid_string_timestamp_treated_as_zero(self):
        from aipass.hooks.apps.handlers.notification.telegram_response import _is_expired

        with patch(LOGGER_PATCH), patch(f"{MOD}.subprocess.run") as mock_run:
            mock_run.side_effect = OSError("no tmux")
            assert _is_expired({"timestamp": "not-a-number"}) is True

    def test_no_session_name_old_expired(self):
        """Old entry with no session_name -> expired (tmux check skipped)."""
        from aipass.hooks.apps.handlers.notification.telegram_response import _is_expired

        with patch(LOGGER_PATCH):
            assert _is_expired({"timestamp": time.time() - 7200}) is True


# ===========================================================================
# extract_assistant_response
# ===========================================================================


class TestExtractAssistantResponse:
    """JSONL transcript extraction with Layer 2 and Layer 3 defenses."""

    def test_normal_extraction(self, tmp_path):
        from aipass.hooks.apps.handlers.notification.telegram_response import extract_assistant_response

        transcript = tmp_path / "transcript.jsonl"
        lines = [
            _jsonl_line("user", "Hello"),
            _jsonl_line("assistant", "Hi there!"),
            _jsonl_line("assistant", "How can I help?"),
        ]
        transcript.write_text("\n".join(lines), encoding="utf-8")

        with patch(LOGGER_PATCH):
            result = extract_assistant_response(str(transcript))

        assert result == "Hi there!\n\nHow can I help?"

    def test_sidechain_entries_skipped(self, tmp_path):
        """Layer 2: isSidechain entries are filtered out."""
        from aipass.hooks.apps.handlers.notification.telegram_response import extract_assistant_response

        transcript = tmp_path / "transcript.jsonl"
        lines = [
            _jsonl_line("user", "Hello"),
            _jsonl_line("assistant", "Sidechain noise", sidechain=True),
            _jsonl_line("assistant", "Real response"),
        ]
        transcript.write_text("\n".join(lines), encoding="utf-8")

        with patch(LOGGER_PATCH):
            result = extract_assistant_response(str(transcript))

        assert result == "Real response"
        assert "Sidechain noise" not in result

    def test_sidechain_user_message_skipped(self, tmp_path):
        """Layer 2: sidechain user messages are not treated as the last user message."""
        from aipass.hooks.apps.handlers.notification.telegram_response import extract_assistant_response

        transcript = tmp_path / "transcript.jsonl"
        lines = [
            _jsonl_line("user", "First real question"),
            _jsonl_line("assistant", "First answer"),
            _jsonl_line("user", "Sidechain user msg", sidechain=True),
            _jsonl_line("assistant", "Sidechain assistant response", sidechain=True),
            _jsonl_line("assistant", "Continuation of first answer"),
        ]
        transcript.write_text("\n".join(lines), encoding="utf-8")

        with patch(LOGGER_PATCH):
            result = extract_assistant_response(str(transcript))

        # Last real user message is "First real question"; assistants after it (non-sidechain)
        assert result is not None
        assert "First answer" in result
        assert "Continuation of first answer" in result
        assert "Sidechain assistant response" not in result

    def test_start_line_offset(self, tmp_path):
        """Layer 3: transcript_line_after skips earlier entries."""
        from aipass.hooks.apps.handlers.notification.telegram_response import extract_assistant_response

        transcript = tmp_path / "transcript.jsonl"
        lines = [
            _jsonl_line("user", "Old question"),  # line 0
            _jsonl_line("assistant", "Old answer"),  # line 1
            _jsonl_line("user", "New question"),  # line 2
            _jsonl_line("assistant", "New answer"),  # line 3
        ]
        transcript.write_text("\n".join(lines), encoding="utf-8")

        with patch(LOGGER_PATCH):
            result = extract_assistant_response(str(transcript), start_line=2)

        assert result == "New answer"

    def test_tool_result_only_user_message_skipped(self, tmp_path):
        """User messages that contain only tool_result blocks are not real user messages."""
        from aipass.hooks.apps.handlers.notification.telegram_response import extract_assistant_response

        transcript = tmp_path / "transcript.jsonl"
        lines = [
            _jsonl_line("user", "Real question"),
            _jsonl_line("assistant", "Starting work..."),
            _jsonl_line("user", tool_result=True),  # tool_result only
            _jsonl_line("assistant", "Done with the work"),
        ]
        transcript.write_text("\n".join(lines), encoding="utf-8")

        with patch(LOGGER_PATCH):
            result = extract_assistant_response(str(transcript))

        # The last real user message is "Real question", so we get everything after it
        assert result is not None
        assert "Starting work..." in result
        assert "Done with the work" in result

    def test_no_user_message_returns_none(self, tmp_path):
        from aipass.hooks.apps.handlers.notification.telegram_response import extract_assistant_response

        transcript = tmp_path / "transcript.jsonl"
        lines = [
            _jsonl_line("assistant", "Hello"),
        ]
        transcript.write_text("\n".join(lines), encoding="utf-8")

        with patch(LOGGER_PATCH):
            result = extract_assistant_response(str(transcript))

        assert result is None

    def test_empty_transcript_returns_none(self, tmp_path):
        from aipass.hooks.apps.handlers.notification.telegram_response import extract_assistant_response

        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text("", encoding="utf-8")

        with patch(LOGGER_PATCH):
            result = extract_assistant_response(str(transcript))

        assert result is None

    def test_missing_transcript_returns_none(self):
        from aipass.hooks.apps.handlers.notification.telegram_response import extract_assistant_response

        with patch(LOGGER_PATCH):
            result = extract_assistant_response("/nonexistent/path.jsonl")

        assert result is None

    def test_corrupt_jsonl_lines_skipped(self, tmp_path):
        """Malformed JSON lines are gracefully skipped."""
        from aipass.hooks.apps.handlers.notification.telegram_response import extract_assistant_response

        transcript = tmp_path / "transcript.jsonl"
        lines = [
            _jsonl_line("user", "Question"),
            "this is not valid json {{{",
            _jsonl_line("assistant", "Answer"),
        ]
        transcript.write_text("\n".join(lines), encoding="utf-8")

        with patch(LOGGER_PATCH):
            result = extract_assistant_response(str(transcript))

        assert result == "Answer"

    def test_no_assistant_text_after_user_returns_none(self, tmp_path):
        from aipass.hooks.apps.handlers.notification.telegram_response import extract_assistant_response

        transcript = tmp_path / "transcript.jsonl"
        lines = [
            _jsonl_line("user", "Question"),
            # No assistant response follows
        ]
        transcript.write_text("\n".join(lines), encoding="utf-8")

        with patch(LOGGER_PATCH):
            result = extract_assistant_response(str(transcript))

        assert result is None


# ===========================================================================
# chunk_text
# ===========================================================================


class TestChunkText:
    """Text splitting for Telegram's 4096-char limit."""

    def test_short_text_single_chunk(self):
        from aipass.hooks.apps.handlers.notification.telegram_response import chunk_text

        result = chunk_text("Hello world")
        assert result == ["Hello world"]

    def test_exact_limit_single_chunk(self):
        from aipass.hooks.apps.handlers.notification.telegram_response import chunk_text

        text = "x" * 4096
        result = chunk_text(text)
        assert len(result) == 1

    def test_long_text_multiple_chunks(self):
        from aipass.hooks.apps.handlers.notification.telegram_response import chunk_text

        text = "Hello world. " * 1000  # ~13000 chars
        result = chunk_text(text, limit=500)
        assert len(result) > 1
        # Reconstruct and verify nothing lost
        for chunk in result:
            assert len(chunk) <= 500

    def test_break_at_sentence_end(self):
        from aipass.hooks.apps.handlers.notification.telegram_response import chunk_text

        # Build text where a sentence ends near the limit boundary
        sentence = "A" * 480 + ". "
        text = sentence + "B" * 200
        result = chunk_text(text, limit=500)
        assert len(result) == 2
        assert result[0].endswith(".")

    def test_break_at_paragraph(self):
        from aipass.hooks.apps.handlers.notification.telegram_response import chunk_text

        para1 = "A" * 300
        para2 = "B" * 300
        text = para1 + "\n\n" + para2
        result = chunk_text(text, limit=400)
        assert len(result) == 2

    def test_break_at_newline(self):
        from aipass.hooks.apps.handlers.notification.telegram_response import chunk_text

        part1 = "A" * 300
        part2 = "B" * 300
        text = part1 + "\n" + part2
        result = chunk_text(text, limit=400)
        assert len(result) == 2

    def test_break_at_space(self):
        from aipass.hooks.apps.handlers.notification.telegram_response import chunk_text

        # Words with spaces — no sentence endings, no newlines in the break zone
        text = ("word " * 100).strip()  # ~499 chars
        result = chunk_text(text, limit=200)
        assert len(result) > 1
        for chunk in result:
            assert len(chunk) <= 200

    def test_empty_text(self):
        from aipass.hooks.apps.handlers.notification.telegram_response import chunk_text

        result = chunk_text("")
        assert result == [""]


# ===========================================================================
# markdown_to_telegram_html
# ===========================================================================


class TestMarkdownToTelegramHtml:
    """Markdown -> Telegram HTML conversion."""

    def test_code_blocks_preserved(self):
        from aipass.hooks.apps.handlers.notification.telegram_response import markdown_to_telegram_html

        text = "Before\n```python\nprint('hello')\n```\nAfter"
        result = markdown_to_telegram_html(text)
        assert '<pre><code class="language-python">' in result
        assert "print(" in result and "hello" in result

    def test_code_block_no_language(self):
        from aipass.hooks.apps.handlers.notification.telegram_response import markdown_to_telegram_html

        text = "Before\n```\nsome code\n```\nAfter"
        result = markdown_to_telegram_html(text)
        assert "<pre>" in result
        assert "some code" in result

    def test_inline_code_preserved(self):
        from aipass.hooks.apps.handlers.notification.telegram_response import markdown_to_telegram_html

        text = "Use `foo()` here"
        result = markdown_to_telegram_html(text)
        assert "<code>foo()</code>" in result

    def test_bold_converted(self):
        from aipass.hooks.apps.handlers.notification.telegram_response import markdown_to_telegram_html

        text = "This is **bold** text"
        result = markdown_to_telegram_html(text)
        assert "<b>bold</b>" in result

    def test_italic_converted(self):
        from aipass.hooks.apps.handlers.notification.telegram_response import markdown_to_telegram_html

        text = "This is *italic* text"
        result = markdown_to_telegram_html(text)
        assert "<i>italic</i>" in result

    def test_html_entities_escaped(self):
        from aipass.hooks.apps.handlers.notification.telegram_response import markdown_to_telegram_html

        text = "Use <div> & stuff > here"
        result = markdown_to_telegram_html(text)
        assert "&lt;div&gt;" in result
        assert "&amp;" in result

    def test_mixed_content(self):
        from aipass.hooks.apps.handlers.notification.telegram_response import markdown_to_telegram_html

        text = "**Bold** and *italic* with `code` and <tag>"
        result = markdown_to_telegram_html(text)
        assert "<b>Bold</b>" in result
        assert "<i>italic</i>" in result
        assert "<code>code</code>" in result
        assert "&lt;tag&gt;" in result

    def test_code_block_content_not_formatted(self):
        """Markdown inside code blocks should not be converted to HTML tags."""
        from aipass.hooks.apps.handlers.notification.telegram_response import markdown_to_telegram_html

        text = "```\n**not bold** *not italic*\n```"
        result = markdown_to_telegram_html(text)
        # Inside <pre>, the ** and * should be escaped, not converted
        assert "<b>" not in result.split("<pre>")[1].split("</pre>")[0]
        assert "<i>" not in result.split("<pre>")[1].split("</pre>")[0]

    def test_inline_code_content_not_formatted(self):
        """Markdown inside inline code should not be converted."""
        from aipass.hooks.apps.handlers.notification.telegram_response import markdown_to_telegram_html

        text = "Use `**not bold**` here"
        result = markdown_to_telegram_html(text)
        # The ** should be present as literal text inside <code>
        code_content = result.split("<code>")[1].split("</code>")[0]
        assert "<b>" not in code_content


# ===========================================================================
# send_to_telegram
# ===========================================================================


class TestSendToTelegram:
    """Telegram Bot API send with HTML->plain text fallback."""

    def test_successful_html_send(self):
        from aipass.hooks.apps.handlers.notification.telegram_response import send_to_telegram

        with patch(LOGGER_PATCH), patch(f"{MOD}.urlopen", return_value=_mock_urlopen_ok()):
            result = send_to_telegram("tok:ABC", 123, "Hello")

        assert result["ok"] is True
        assert result["message_id"] == 100

    def test_html_fails_plain_text_fallback_succeeds(self):
        from aipass.hooks.apps.handlers.notification.telegram_response import send_to_telegram

        call_count = 0

        def urlopen_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("HTML parse error")
            return _mock_urlopen_ok()

        with patch(LOGGER_PATCH), patch(f"{MOD}.urlopen", side_effect=urlopen_side_effect):
            result = send_to_telegram("tok:ABC", 123, "Hello **bold**")

        assert result["ok"] is True
        assert call_count == 2

    def test_html_fails_plain_text_also_fails(self):
        from aipass.hooks.apps.handlers.notification.telegram_response import send_to_telegram

        with patch(LOGGER_PATCH), patch(f"{MOD}.urlopen", side_effect=Exception("network error")):
            result = send_to_telegram("tok:ABC", 123, "Hello")

        assert result["ok"] is False

    def test_http_error_handling(self):
        from aipass.hooks.apps.handlers.notification.telegram_response import send_to_telegram
        from urllib.error import HTTPError

        call_count = 0

        def urlopen_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("HTML error")
            err = HTTPError(
                url="https://api.telegram.org/bot/sendMessage",
                code=400,
                msg="Bad Request",
                hdrs=MagicMock(),  # type: ignore[arg-type]
                fp=io.BytesIO(json.dumps({"description": "bad request"}).encode()),
            )
            raise err

        with patch(LOGGER_PATCH), patch(f"{MOD}.urlopen", side_effect=urlopen_side_effect):
            result = send_to_telegram("tok:ABC", 123, "Hello")

        assert result["ok"] is False

    def test_url_error_handling(self):
        from aipass.hooks.apps.handlers.notification.telegram_response import send_to_telegram
        from urllib.error import URLError

        call_count = 0

        def urlopen_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("HTML error")
            raise URLError("DNS failure")

        with patch(LOGGER_PATCH), patch(f"{MOD}.urlopen", side_effect=urlopen_side_effect):
            result = send_to_telegram("tok:ABC", 123, "Hello")

        assert result["ok"] is False

    def test_reply_to_message_id_included(self):
        from aipass.hooks.apps.handlers.notification.telegram_response import send_to_telegram

        captured_requests = []

        def urlopen_capture(req, **kwargs):
            captured_requests.append(json.loads(req.data.decode()))
            return _mock_urlopen_ok()

        with patch(LOGGER_PATCH), patch(f"{MOD}.urlopen", side_effect=urlopen_capture):
            send_to_telegram("tok:ABC", 123, "Hello", message_id=456)

        assert captured_requests[0]["reply_to_message_id"] == 456

    def test_returns_message_text_from_api(self):
        from aipass.hooks.apps.handlers.notification.telegram_response import send_to_telegram

        with patch(LOGGER_PATCH), patch(f"{MOD}.urlopen", return_value=_mock_urlopen_ok(text="returned")):
            result = send_to_telegram("tok:ABC", 123, "Hello")

        assert result["text"] == "returned"


# ===========================================================================
# edit_telegram_message
# ===========================================================================


class TestEditTelegramMessage:
    """Telegram Bot API edit with HTML->plain text fallback."""

    def test_successful_html_edit(self):
        from aipass.hooks.apps.handlers.notification.telegram_response import edit_telegram_message

        with patch(LOGGER_PATCH), patch(f"{MOD}.urlopen", return_value=_mock_urlopen_ok()):
            result = edit_telegram_message("tok:ABC", 123, 789, "Updated text")

        assert result["ok"] is True
        assert result["message_id"] == 100

    def test_html_edit_fails_plain_text_fallback(self):
        from aipass.hooks.apps.handlers.notification.telegram_response import edit_telegram_message

        call_count = 0

        def urlopen_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("HTML edit error")
            return _mock_urlopen_ok()

        with patch(LOGGER_PATCH), patch(f"{MOD}.urlopen", side_effect=urlopen_side_effect):
            result = edit_telegram_message("tok:ABC", 123, 789, "Updated")

        assert result["ok"] is True

    def test_both_fail_returns_false(self):
        from aipass.hooks.apps.handlers.notification.telegram_response import edit_telegram_message

        with patch(LOGGER_PATCH), patch(f"{MOD}.urlopen", side_effect=Exception("total failure")):
            result = edit_telegram_message("tok:ABC", 123, 789, "Text")

        assert result["ok"] is False

    def test_edit_url_uses_editMessageText(self):
        from aipass.hooks.apps.handlers.notification.telegram_response import edit_telegram_message

        captured_urls = []

        def urlopen_capture(req, **kwargs):
            captured_urls.append(req.full_url)
            return _mock_urlopen_ok()

        with patch(LOGGER_PATCH), patch(f"{MOD}.urlopen", side_effect=urlopen_capture):
            edit_telegram_message("tok:ABC", 123, 789, "Text")

        assert "editMessageText" in captured_urls[0]


# ===========================================================================
# handle — integration tests
# ===========================================================================


class TestHandleIntegration:
    """Full handle() flow integration tests."""

    def test_happy_path_send_and_advance(self, tmp_path):
        """Full flow: pending exists -> extract -> send -> advance cursor."""
        from aipass.hooks.apps.handlers.notification.telegram_response import handle

        transcript = tmp_path / "transcript.jsonl"
        lines = [
            _jsonl_line("user", "Hello"),
            _jsonl_line("assistant", "Hi there!"),
        ]
        transcript.write_text("\n".join(lines), encoding="utf-8")

        pending_dir = tmp_path / "telegram_pending"
        pending_dir.mkdir()
        pending_data = {
            "chat_id": 999,
            "bot_token": "tok:ABC",
            "timestamp": time.time(),
            "work_dir": str(tmp_path),
        }
        pending_file = pending_dir / "bot-1.json"
        pending_file.write_text(json.dumps(pending_data), encoding="utf-8")

        with (
            patch(LOGGER_PATCH),
            patch(f"{MOD}.find_pending_file", return_value=pending_file),
            patch(f"{MOD}.urlopen", return_value=_mock_urlopen_ok()),
            patch(f"{MOD}._check_log_streamer_active", return_value=False),
            patch(f"{MOD}.Path.cwd", return_value=tmp_path),
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
        assert pending_file.exists()
        updated = json.loads(pending_file.read_text(encoding="utf-8"))
        assert updated["delivered"] is True
        assert updated["transcript_line_after"] == 2

    def test_send_fails_pending_kept(self, tmp_path):
        """When delivery fails, pending file is kept for retry."""
        from aipass.hooks.apps.handlers.notification.telegram_response import handle

        transcript = tmp_path / "transcript.jsonl"
        lines = [
            _jsonl_line("user", "Hello"),
            _jsonl_line("assistant", "Response"),
        ]
        transcript.write_text("\n".join(lines), encoding="utf-8")

        pending_dir = tmp_path / "telegram_pending"
        pending_dir.mkdir()
        pending_data = {
            "chat_id": 999,
            "bot_token": "tok:ABC",
            "timestamp": time.time(),
            "work_dir": str(tmp_path),
        }
        pending_file = pending_dir / "bot-1.json"
        pending_file.write_text(json.dumps(pending_data), encoding="utf-8")

        with (
            patch(LOGGER_PATCH),
            patch(f"{MOD}.find_pending_file", return_value=pending_file),
            patch(f"{MOD}.urlopen", side_effect=Exception("network down")),
            patch(f"{MOD}._check_log_streamer_active", return_value=False),
            patch(f"{MOD}.time.sleep"),
            patch(f"{MOD}.Path.cwd", return_value=tmp_path),
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
        assert pending_file.exists()
        updated = json.loads(pending_file.read_text(encoding="utf-8"))
        assert "delivered" not in updated

    def test_no_response_text_pending_kept(self, tmp_path):
        """When no response text is extracted, pending is kept."""
        from aipass.hooks.apps.handlers.notification.telegram_response import handle

        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text("", encoding="utf-8")  # empty transcript

        pending_dir = tmp_path / "telegram_pending"
        pending_dir.mkdir()
        pending_data = {
            "chat_id": 999,
            "bot_token": "tok:ABC",
            "timestamp": time.time(),
            "work_dir": str(tmp_path),
        }
        pending_file = pending_dir / "bot-1.json"
        pending_file.write_text(json.dumps(pending_data), encoding="utf-8")

        with (
            patch(LOGGER_PATCH),
            patch(f"{MOD}.find_pending_file", return_value=pending_file),
            patch(f"{MOD}._check_log_streamer_active", return_value=False),
            patch(f"{MOD}.time.sleep"),
            patch(f"{MOD}.Path.cwd", return_value=tmp_path),
        ):
            result = handle(
                {
                    "hook_event_name": "Stop",
                    "session_id": "session-abc",
                    "transcript_path": str(transcript),
                    "last_assistant_message": "",
                }
            )

        assert result == {"stdout": "", "exit_code": 0}
        assert pending_file.exists()

    def test_jsonl_retry_mechanism(self, tmp_path):
        """JSONL extraction retries on flush-race (empty first attempt)."""
        from aipass.hooks.apps.handlers.notification.telegram_response import handle

        transcript = tmp_path / "transcript.jsonl"
        lines = [
            _jsonl_line("user", "Hello"),
            _jsonl_line("assistant", "Answer"),
        ]
        transcript.write_text("\n".join(lines), encoding="utf-8")

        pending_dir = tmp_path / "telegram_pending"
        pending_dir.mkdir()
        pending_data = {
            "chat_id": 999,
            "bot_token": "tok:ABC",
            "timestamp": time.time(),
            "work_dir": str(tmp_path),
        }
        pending_file = pending_dir / "bot-1.json"
        pending_file.write_text(json.dumps(pending_data), encoding="utf-8")

        from aipass.hooks.apps.handlers.notification.telegram_response import extract_assistant_response

        extract_call_count = 0
        original_extract = extract_assistant_response

        def mock_extract(tp: str, start_line: int = 0) -> str | None:
            nonlocal extract_call_count
            extract_call_count += 1
            if extract_call_count == 1:
                return None  # Simulate flush-race
            return original_extract(tp, start_line=start_line)

        with (
            patch(LOGGER_PATCH),
            patch(f"{MOD}.find_pending_file", return_value=pending_file),
            patch(f"{MOD}.extract_assistant_response", side_effect=mock_extract),
            patch(f"{MOD}.urlopen", return_value=_mock_urlopen_ok()),
            patch(f"{MOD}._check_log_streamer_active", return_value=False),
            patch(f"{MOD}.time.sleep"),
            patch(f"{MOD}.Path.cwd", return_value=tmp_path),
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
        assert extract_call_count >= 2
        assert pending_file.exists()
        updated = json.loads(pending_file.read_text(encoding="utf-8"))
        assert updated["delivered"] is True

    def test_fallback_to_last_assistant_message(self, tmp_path):
        """When JSONL extraction fails, falls back to last_assistant_message from hook_data."""
        from aipass.hooks.apps.handlers.notification.telegram_response import handle

        pending_dir = tmp_path / "telegram_pending"
        pending_dir.mkdir()
        pending_data = {
            "chat_id": 999,
            "bot_token": "tok:ABC",
            "timestamp": time.time(),
            "work_dir": str(tmp_path),
        }
        pending_file = pending_dir / "bot-1.json"
        pending_file.write_text(json.dumps(pending_data), encoding="utf-8")

        with (
            patch(LOGGER_PATCH),
            patch(f"{MOD}.find_pending_file", return_value=pending_file),
            patch(f"{MOD}.urlopen", return_value=_mock_urlopen_ok()),
            patch(f"{MOD}._check_log_streamer_active", return_value=False),
            patch(f"{MOD}.time.sleep"),
            patch(f"{MOD}.Path.cwd", return_value=tmp_path),
            patch(f"{MOD}._write_delivery_log"),
        ):
            result = handle(
                {
                    "hook_event_name": "Stop",
                    "session_id": "session-abc",
                    "transcript_path": "",
                    "last_assistant_message": "Fallback text",
                }
            )

        assert result == {"stdout": "", "exit_code": 0, "sound": "telegram response"}
        assert not pending_file.exists()

    def test_already_delivered_skips_fallback(self, tmp_path):
        """After first delivery, last_assistant_message fallback is skipped."""
        from aipass.hooks.apps.handlers.notification.telegram_response import handle

        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text("", encoding="utf-8")

        pending_dir = tmp_path / "telegram_pending"
        pending_dir.mkdir()
        pending_data = {
            "chat_id": 999,
            "bot_token": "tok:ABC",
            "timestamp": time.time(),
            "work_dir": str(tmp_path),
            "delivered": True,
            "transcript_line_after": 5,
        }
        pending_file = pending_dir / "bot-1.json"
        pending_file.write_text(json.dumps(pending_data), encoding="utf-8")

        with (
            patch(LOGGER_PATCH),
            patch(f"{MOD}.find_pending_file", return_value=pending_file),
            patch(f"{MOD}._check_log_streamer_active", return_value=False),
            patch(f"{MOD}.time.sleep"),
            patch(f"{MOD}.Path.cwd", return_value=tmp_path),
        ):
            result = handle(
                {
                    "hook_event_name": "Stop",
                    "session_id": "session-abc",
                    "transcript_path": str(transcript),
                    "last_assistant_message": "Would be a duplicate",
                }
            )

        assert result == {"stdout": "", "exit_code": 0}
        assert pending_file.exists()

    def test_missing_chat_id_cleans_pending(self, tmp_path):
        """Pending with missing chat_id is cleaned up."""
        from aipass.hooks.apps.handlers.notification.telegram_response import handle

        pending_dir = tmp_path / "telegram_pending"
        pending_dir.mkdir()
        pending_data = {
            "bot_token": "tok:ABC",
            "timestamp": time.time(),
            # no chat_id
        }
        pending_file = pending_dir / "bot-1.json"
        pending_file.write_text(json.dumps(pending_data), encoding="utf-8")

        with patch(LOGGER_PATCH), patch(f"{MOD}.find_pending_file", return_value=pending_file):
            result = handle(
                {
                    "hook_event_name": "Stop",
                    "session_id": "session-abc",
                }
            )

        assert result == {"stdout": "", "exit_code": 0}
        assert not pending_file.exists()

    def test_corrupt_pending_file_cleaned(self, tmp_path):
        """Corrupt pending JSON is handled gracefully and cleaned up."""
        from aipass.hooks.apps.handlers.notification.telegram_response import handle

        pending_dir = tmp_path / "telegram_pending"
        pending_dir.mkdir()
        pending_file = pending_dir / "bot-1.json"
        pending_file.write_text("this is not json{{{", encoding="utf-8")

        with patch(LOGGER_PATCH), patch(f"{MOD}.find_pending_file", return_value=pending_file):
            result = handle(
                {
                    "hook_event_name": "Stop",
                    "session_id": "session-abc",
                }
            )

        assert result == {"stdout": "", "exit_code": 0}
        assert not pending_file.exists()


# ===========================================================================
# _send_with_retry
# ===========================================================================


class TestSendWithRetry:
    """Retry mechanism with exponential backoff."""

    def test_success_on_first_try(self):
        from aipass.hooks.apps.handlers.notification.telegram_response import _send_with_retry

        with patch(LOGGER_PATCH), patch(f"{MOD}.send_to_telegram", return_value=_ok_result()) as mock_send:
            result = _send_with_retry("tok:ABC", 123, "Hello")

        assert result["ok"] is True
        assert mock_send.call_count == 1

    def test_success_on_retry(self):
        from aipass.hooks.apps.handlers.notification.telegram_response import _send_with_retry

        with (
            patch(LOGGER_PATCH),
            patch(f"{MOD}.send_to_telegram", side_effect=[_fail_result(), _ok_result()]) as mock_send,
            patch(f"{MOD}.time.sleep"),
        ):
            result = _send_with_retry("tok:ABC", 123, "Hello")

        assert result["ok"] is True
        assert mock_send.call_count == 2

    def test_all_retries_fail(self):
        from aipass.hooks.apps.handlers.notification.telegram_response import _send_with_retry

        with (
            patch(LOGGER_PATCH),
            patch(f"{MOD}.send_to_telegram", return_value=_fail_result()) as mock_send,
            patch(f"{MOD}.time.sleep"),
        ):
            result = _send_with_retry("tok:ABC", 123, "Hello", retries=3)

        assert result["ok"] is False
        assert mock_send.call_count == 3


# ===========================================================================
# _prepend_branch_prefix
# ===========================================================================


class TestPrependBranchPrefix:
    """Branch prefix added to response text."""

    def test_adds_branch_prefix(self, tmp_path):
        from aipass.hooks.apps.handlers.notification.telegram_response import _prepend_branch_prefix

        with patch(LOGGER_PATCH), patch(f"{MOD}.Path.cwd", return_value=tmp_path / "hooks"):
            result = _prepend_branch_prefix("Hello")

        assert result == "@hooks\n\nHello"

    def test_cwd_failure_returns_original(self):
        from aipass.hooks.apps.handlers.notification.telegram_response import _prepend_branch_prefix

        with patch(LOGGER_PATCH), patch(f"{MOD}.Path.cwd", side_effect=OSError("no cwd")):
            result = _prepend_branch_prefix("Hello")

        assert result == "Hello"


# ===========================================================================
# _deliver_chunks
# ===========================================================================


class TestDeliverChunks:
    """Chunk delivery with edit/send logic."""

    def test_single_chunk_no_processing_msg(self):
        from aipass.hooks.apps.handlers.notification.telegram_response import _deliver_chunks

        with patch(LOGGER_PATCH), patch(f"{MOD}._send_with_retry", return_value=_ok_result()) as mock_send:
            all_sent, chunk_results = _deliver_chunks(["Hello"], "tok", 123, None, False)

        assert all_sent is True
        assert len(chunk_results) == 1
        assert chunk_results[0]["method"] == "send"
        mock_send.assert_called_once_with("tok", 123, "Hello")

    def test_single_chunk_with_processing_msg_edits(self):
        from aipass.hooks.apps.handlers.notification.telegram_response import _deliver_chunks

        with patch(LOGGER_PATCH), patch(f"{MOD}.edit_telegram_message", return_value=_ok_result()) as mock_edit:
            all_sent, chunk_results = _deliver_chunks(["Hello"], "tok", 123, 789, False)

        assert all_sent is True
        assert chunk_results[0]["method"] == "edit"
        mock_edit.assert_called_once_with("tok", 123, 789, "Hello")

    def test_single_chunk_edit_fails_falls_back_to_send(self):
        from aipass.hooks.apps.handlers.notification.telegram_response import _deliver_chunks

        with (
            patch(LOGGER_PATCH),
            patch(f"{MOD}.edit_telegram_message", return_value=_fail_result()),
            patch(f"{MOD}._send_with_retry", return_value=_ok_result()) as mock_send,
        ):
            all_sent, chunk_results = _deliver_chunks(["Hello"], "tok", 123, 789, False)

        assert all_sent is True
        assert chunk_results[0]["method"] == "send"
        mock_send.assert_called_once()

    def test_logs_active_sends_done_then_sends_new(self):
        """When logs were active, edit processing msg to 'Done.' then send new."""
        from aipass.hooks.apps.handlers.notification.telegram_response import _deliver_chunks

        with (
            patch(LOGGER_PATCH),
            patch(f"{MOD}.edit_telegram_message", return_value=_ok_result()) as mock_edit,
            patch(f"{MOD}._send_with_retry", return_value=_ok_result()) as mock_send,
        ):
            all_sent, chunk_results = _deliver_chunks(["Hello"], "tok", 123, 789, True)

        assert all_sent is True
        mock_edit.assert_called_once_with("tok", 123, 789, "Done.")
        mock_send.assert_called_once()

    def test_multiple_chunks_clears_placeholder_sends_all_fresh(self):
        """Multi-chunk: clears placeholder and sends ALL chunks as fresh messages."""
        from aipass.hooks.apps.handlers.notification.telegram_response import _deliver_chunks

        sent_texts = []

        def capture_send(bot_token, chat_id, text):
            sent_texts.append(text)
            return _ok_result()

        with (
            patch(LOGGER_PATCH),
            patch(f"{MOD}.edit_telegram_message", return_value=_ok_result()) as mock_edit,
            patch(f"{MOD}._send_with_retry", side_effect=capture_send),
        ):
            all_sent, chunk_results = _deliver_chunks(["Part A", "Part B", "Part C"], "tok", 123, 789, False)

        assert all_sent is True
        mock_edit.assert_called_once_with("tok", 123, 789, "Done.")
        assert len(sent_texts) == 3
        assert "[1/3]" in sent_texts[0]
        assert "[2/3]" in sent_texts[1]
        assert "[3/3]" in sent_texts[2]

    def test_multiple_chunks_no_processing_msg(self):
        from aipass.hooks.apps.handlers.notification.telegram_response import _deliver_chunks

        sent_texts = []

        def capture_send(bot_token, chat_id, text):
            sent_texts.append(text)
            return _ok_result()

        with patch(LOGGER_PATCH), patch(f"{MOD}._send_with_retry", side_effect=capture_send):
            all_sent, chunk_results = _deliver_chunks(["Part A", "Part B", "Part C"], "tok", 123, None, False)

        assert all_sent is True
        assert "[1/3]" in sent_texts[0]
        assert "[2/3]" in sent_texts[1]
        assert "[3/3]" in sent_texts[2]

    def test_chunk_results_contain_message_ids(self):
        from aipass.hooks.apps.handlers.notification.telegram_response import _deliver_chunks

        call_idx = 0

        def mock_send_with_ids(bot_token, chat_id, text):
            nonlocal call_idx
            call_idx += 1
            return _ok_result(message_id=200 + call_idx)

        with patch(LOGGER_PATCH), patch(f"{MOD}._send_with_retry", side_effect=mock_send_with_ids):
            _, chunk_results = _deliver_chunks(["A", "B"], "tok", 123, None, False)

        assert chunk_results[0]["message_id"] == 201
        assert chunk_results[1]["message_id"] == 202


# ===========================================================================
# _deliver_chunks streaming mode
# ===========================================================================


class TestDeliverChunksStreaming:
    """Streaming flag changes reconcile behavior — batch unchanged."""

    def test_streaming_logs_active_reconciles_instead_of_done(self):
        """Streaming + logs_active: edit processing msg with response, not 'Done.'."""
        from aipass.hooks.apps.handlers.notification.telegram_response import _deliver_chunks

        with (
            patch(LOGGER_PATCH),
            patch(f"{MOD}.edit_telegram_message", return_value=_ok_result()) as mock_edit,
        ):
            all_sent, chunk_results = _deliver_chunks(["Hello"], "tok", 123, 789, True, streaming=True)

        assert all_sent is True
        assert chunk_results[0]["method"] == "edit"
        mock_edit.assert_called_once_with("tok", 123, 789, "Hello")

    def test_streaming_multi_chunk_edits_first_sends_rest(self):
        """Streaming + multi-chunk: edit chunk 1 into processing msg, send rest."""
        from aipass.hooks.apps.handlers.notification.telegram_response import _deliver_chunks

        sent_texts = []

        def capture_send(bot_token, chat_id, text):
            sent_texts.append(text)
            return _ok_result()

        with (
            patch(LOGGER_PATCH),
            patch(f"{MOD}.edit_telegram_message", return_value=_ok_result()) as mock_edit,
            patch(f"{MOD}._send_with_retry", side_effect=capture_send),
        ):
            all_sent, chunk_results = _deliver_chunks(
                ["Part A", "Part B", "Part C"], "tok", 123, 789, False, streaming=True
            )

        assert all_sent is True
        mock_edit.assert_called_once_with("tok", 123, 789, "Part A")
        assert chunk_results[0]["method"] == "edit"
        assert len(sent_texts) == 2
        assert "[2/3]" in sent_texts[0]
        assert "[3/3]" in sent_texts[1]

    def test_streaming_multi_chunk_edit_fails_sends_all(self):
        """Streaming + multi-chunk: if edit fails, fall back to send for chunk 1."""
        from aipass.hooks.apps.handlers.notification.telegram_response import _deliver_chunks

        sent_texts = []

        def capture_send(bot_token, chat_id, text):
            sent_texts.append(text)
            return _ok_result()

        with (
            patch(LOGGER_PATCH),
            patch(f"{MOD}.edit_telegram_message", return_value=_fail_result()),
            patch(f"{MOD}._send_with_retry", side_effect=capture_send),
        ):
            all_sent, chunk_results = _deliver_chunks(["Part A", "Part B"], "tok", 123, 789, False, streaming=True)

        assert all_sent is True
        assert chunk_results[0]["method"] == "send"
        assert len(sent_texts) == 2

    def test_batch_logs_active_still_sends_done(self):
        """Batch mode (no streaming): logs_active still sends 'Done.' — zero regression."""
        from aipass.hooks.apps.handlers.notification.telegram_response import _deliver_chunks

        with (
            patch(LOGGER_PATCH),
            patch(f"{MOD}.edit_telegram_message", return_value=_ok_result()) as mock_edit,
            patch(f"{MOD}._send_with_retry", return_value=_ok_result()),
        ):
            all_sent, chunk_results = _deliver_chunks(["Hello"], "tok", 123, 789, True, streaming=False)

        assert all_sent is True
        mock_edit.assert_called_once_with("tok", 123, 789, "Done.")

    def test_batch_multi_chunk_still_sends_done(self):
        """Batch mode (no streaming): multi-chunk still sends 'Done.' — zero regression."""
        from aipass.hooks.apps.handlers.notification.telegram_response import _deliver_chunks

        with (
            patch(LOGGER_PATCH),
            patch(f"{MOD}.edit_telegram_message", return_value=_ok_result()) as mock_edit,
            patch(f"{MOD}._send_with_retry", return_value=_ok_result()),
        ):
            _deliver_chunks(["Part A", "Part B"], "tok", 123, 789, False, streaming=False)

        mock_edit.assert_called_once_with("tok", 123, 789, "Done.")

    def test_streaming_single_no_logs_still_edits(self):
        """Streaming + single chunk + no logs: same as batch — reconcile-edit."""
        from aipass.hooks.apps.handlers.notification.telegram_response import _deliver_chunks

        with (
            patch(LOGGER_PATCH),
            patch(f"{MOD}.edit_telegram_message", return_value=_ok_result()) as mock_edit,
        ):
            all_sent, chunk_results = _deliver_chunks(["Hello"], "tok", 123, 789, False, streaming=True)

        assert all_sent is True
        mock_edit.assert_called_once_with("tok", 123, 789, "Hello")
        assert chunk_results[0]["method"] == "edit"


# ===========================================================================
# _advance_pending
# ===========================================================================


class TestAdvancePending:
    """Pending file cursor advancement."""

    def test_advances_cursor(self, tmp_path):
        from aipass.hooks.apps.handlers.notification.telegram_response import _advance_pending

        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text("line1\nline2\nline3\n", encoding="utf-8")

        pending_file = tmp_path / "pending.json"
        pending_data = {"chat_id": 1, "bot_token": "tok"}
        pending_file.write_text(json.dumps(pending_data), encoding="utf-8")

        with patch(LOGGER_PATCH):
            _advance_pending(pending_file, pending_data, str(transcript))

        assert pending_file.exists()
        updated = json.loads(pending_file.read_text(encoding="utf-8"))
        assert updated["transcript_line_after"] == 3
        assert updated["delivered"] is True

    def test_no_transcript_removes_pending(self, tmp_path):
        from aipass.hooks.apps.handlers.notification.telegram_response import _advance_pending

        pending_file = tmp_path / "pending.json"
        pending_data = {"chat_id": 1}
        pending_file.write_text(json.dumps(pending_data), encoding="utf-8")

        with patch(LOGGER_PATCH):
            _advance_pending(pending_file, pending_data, "")

        assert not pending_file.exists()

    def test_transcript_read_failure_removes_pending(self, tmp_path):
        from aipass.hooks.apps.handlers.notification.telegram_response import _advance_pending

        pending_file = tmp_path / "pending.json"
        pending_data = {"chat_id": 1}
        pending_file.write_text(json.dumps(pending_data), encoding="utf-8")

        with patch(LOGGER_PATCH):
            _advance_pending(pending_file, pending_data, "/nonexistent/transcript.jsonl")

        assert not pending_file.exists()

    def test_clears_processing_message_id_after_advance(self, tmp_path):
        """After advance, processing_message_id is None so next Stop sends new msg, not edit."""
        from aipass.hooks.apps.handlers.notification.telegram_response import _advance_pending

        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text("line1\nline2\n", encoding="utf-8")

        pending_file = tmp_path / "pending.json"
        pending_data = {"chat_id": 1, "bot_token": "tok", "processing_message_id": 42}
        pending_file.write_text(json.dumps(pending_data), encoding="utf-8")

        with patch(LOGGER_PATCH):
            _advance_pending(pending_file, pending_data, str(transcript))

        updated = json.loads(pending_file.read_text(encoding="utf-8"))
        assert updated["processing_message_id"] is None

    def test_second_delivery_sends_new_message_after_advance(self, tmp_path):
        """Two consecutive deliver->advance cycles: 2nd must send, not edit."""
        from aipass.hooks.apps.handlers.notification.telegram_response import _advance_pending

        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text("line1\nline2\n", encoding="utf-8")

        pending_file = tmp_path / "pending.json"
        pending_data = {
            "chat_id": 1,
            "bot_token": "tok",
            "processing_message_id": 42,
        }
        pending_file.write_text(json.dumps(pending_data), encoding="utf-8")

        with patch(LOGGER_PATCH):
            _advance_pending(pending_file, pending_data, str(transcript))

        after_first = json.loads(pending_file.read_text(encoding="utf-8"))
        assert after_first["processing_message_id"] is None
        assert after_first["delivered"] is True

        transcript.write_text("line1\nline2\nline3\nline4\n", encoding="utf-8")
        after_first["delivered"] = False

        with patch(LOGGER_PATCH):
            _advance_pending(pending_file, after_first, str(transcript))

        after_second = json.loads(pending_file.read_text(encoding="utf-8"))
        assert after_second["processing_message_id"] is None
        assert after_second["transcript_line_after"] == 4


# ===========================================================================
# _write_delivery_log
# ===========================================================================


class TestWriteDeliveryLog:
    """Delivery match log JSONL output."""

    def test_writes_jsonl_record(self, tmp_path):
        from aipass.hooks.apps.handlers.notification.telegram_response import _write_delivery_log

        log_path = tmp_path / "delivery.jsonl"

        with patch(LOGGER_PATCH), patch(f"{MOD}._get_delivery_log", return_value=log_path):
            _write_delivery_log(
                "hello",
                ["hello"],
                [{"idx": 0, "method": "send", "ok": True, "message_id": 1, "text": "hello"}],
                "session123",
            )

        assert log_path.exists()
        record = json.loads(log_path.read_text(encoding="utf-8").strip())
        assert record["intended_len"] == 5
        assert record["match"] is True
        assert record["session"] == "session1"
        assert len(record["chunks"]) == 1

    def test_mismatch_reports_culprit(self, tmp_path):
        from aipass.hooks.apps.handlers.notification.telegram_response import _write_delivery_log

        log_path = tmp_path / "delivery.jsonl"

        with patch(LOGGER_PATCH), patch(f"{MOD}._get_delivery_log", return_value=log_path):
            _write_delivery_log(
                "**bold text**",
                ["**bold text**"],
                [{"idx": 0, "method": "send", "ok": True, "message_id": 1, "text": "bold text"}],
                "session123",
            )

        record = json.loads(log_path.read_text(encoding="utf-8").strip())
        assert record["match"] is False
        assert "culprit" in record

    def test_failed_chunk_culprit(self, tmp_path):
        from aipass.hooks.apps.handlers.notification.telegram_response import _write_delivery_log

        log_path = tmp_path / "delivery.jsonl"

        with patch(LOGGER_PATCH), patch(f"{MOD}._get_delivery_log", return_value=log_path):
            _write_delivery_log(
                "hello",
                ["hello"],
                [{"idx": 0, "method": "send", "ok": False, "text": ""}],
                "sess",
            )

        record = json.loads(log_path.read_text(encoding="utf-8").strip())
        assert record["match"] is False
        assert "delivery_failed" in record["culprit"]

    def test_log_write_failure_does_not_raise(self):
        from aipass.hooks.apps.handlers.notification.telegram_response import _write_delivery_log

        impossible = Path("/dev/null/impossible/log.jsonl")
        with patch(LOGGER_PATCH), patch(f"{MOD}._get_delivery_log", return_value=impossible):
            _write_delivery_log("hi", ["hi"], [{"idx": 0, "ok": True, "text": "hi"}], "s")


# ===========================================================================
# _is_expired — mirror files
# ===========================================================================


class TestIsExpiredMirror:
    """Mirror files are never expired."""

    def test_mirror_file_never_expired(self):
        from aipass.hooks.apps.handlers.notification.telegram_response import _is_expired

        with patch(LOGGER_PATCH):
            assert _is_expired({"timestamp": 0, "mirror": True}) is False

    def test_mirror_file_old_timestamp_not_expired(self):
        from aipass.hooks.apps.handlers.notification.telegram_response import _is_expired

        with patch(LOGGER_PATCH):
            assert _is_expired({"timestamp": 1000, "mirror": True}) is False


# ===========================================================================
# _extract_user_text
# ===========================================================================


class TestExtractUserText:
    """User message text extraction."""

    def test_text_block(self):
        from aipass.hooks.apps.handlers.notification.telegram_response import _extract_user_text

        content = [{"type": "text", "text": "Hello world"}]
        assert _extract_user_text(content) == "Hello world"

    def test_tool_result_only_returns_none(self):
        from aipass.hooks.apps.handlers.notification.telegram_response import _extract_user_text

        content = [{"type": "tool_result", "content": "ok"}]
        assert _extract_user_text(content) is None

    def test_string_content(self):
        from aipass.hooks.apps.handlers.notification.telegram_response import _extract_user_text

        assert _extract_user_text("Hello") == "Hello"

    def test_empty_string_returns_none(self):
        from aipass.hooks.apps.handlers.notification.telegram_response import _extract_user_text

        assert _extract_user_text("") is None

    def test_empty_list_returns_none(self):
        from aipass.hooks.apps.handlers.notification.telegram_response import _extract_user_text

        assert _extract_user_text([]) is None

    def test_non_list_non_string_returns_none(self):
        from aipass.hooks.apps.handlers.notification.telegram_response import _extract_user_text

        assert _extract_user_text(42) is None  # type: ignore[arg-type]

    def test_mixed_text_and_tool_result(self):
        from aipass.hooks.apps.handlers.notification.telegram_response import _extract_user_text

        content = [{"type": "text", "text": "Question"}, {"type": "tool_result", "content": "ok"}]
        assert _extract_user_text(content) == "Question"


# ===========================================================================
# extract_mirror_turn
# ===========================================================================


class TestExtractMirrorTurn:
    """Mirror transcript extraction — user input + assistant response."""

    def test_single_turn_user_and_assistant(self, tmp_path):
        from aipass.hooks.apps.handlers.notification.telegram_response import extract_mirror_turn

        transcript = tmp_path / "transcript.jsonl"
        lines = [
            _jsonl_line("user", "What is AIPass?"),
            _jsonl_line("assistant", "AIPass is a multi-agent framework."),
        ]
        transcript.write_text("\n".join(lines), encoding="utf-8")

        with patch(LOGGER_PATCH):
            result = extract_mirror_turn(str(transcript))

        assert result is not None
        assert "You: What is AIPass?" in result
        assert "AIPass is a multi-agent framework." in result

    def test_multiple_turns_separated_by_divider(self, tmp_path):
        from aipass.hooks.apps.handlers.notification.telegram_response import extract_mirror_turn

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

        assert result is not None
        assert "You: First question" in result
        assert "First answer" in result
        assert "---" in result
        assert "You: Second question" in result
        assert "Second answer" in result

    def test_sidechain_entries_skipped(self, tmp_path):
        from aipass.hooks.apps.handlers.notification.telegram_response import extract_mirror_turn

        transcript = tmp_path / "transcript.jsonl"
        lines = [
            _jsonl_line("user", "Real question"),
            _jsonl_line("assistant", "Sidechain noise", sidechain=True),
            _jsonl_line("assistant", "Real answer"),
        ]
        transcript.write_text("\n".join(lines), encoding="utf-8")

        with patch(LOGGER_PATCH):
            result = extract_mirror_turn(str(transcript))

        assert result is not None
        assert "Sidechain noise" not in result
        assert "Real answer" in result

    def test_tool_result_user_messages_skipped(self, tmp_path):
        from aipass.hooks.apps.handlers.notification.telegram_response import extract_mirror_turn

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

        assert result is not None
        assert "You: Real question" in result
        assert "Working on it..." in result
        assert "Done with the work" in result
        # tool_result should not create a second turn
        assert "---" not in result

    def test_start_line_skips_old_entries(self, tmp_path):
        from aipass.hooks.apps.handlers.notification.telegram_response import extract_mirror_turn

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

        assert result is not None
        assert "Old question" not in result
        assert "New question" in result
        assert "New answer" in result

    def test_no_new_entries_returns_none(self, tmp_path):
        from aipass.hooks.apps.handlers.notification.telegram_response import extract_mirror_turn

        transcript = tmp_path / "transcript.jsonl"
        lines = [
            _jsonl_line("user", "Question"),
            _jsonl_line("assistant", "Answer"),
        ]
        transcript.write_text("\n".join(lines), encoding="utf-8")

        with patch(LOGGER_PATCH):
            result = extract_mirror_turn(str(transcript), start_line=2)

        assert result is None

    def test_missing_transcript_returns_none(self):
        from aipass.hooks.apps.handlers.notification.telegram_response import extract_mirror_turn

        with patch(LOGGER_PATCH):
            result = extract_mirror_turn("/nonexistent/path.jsonl")

        assert result is None

    def test_corrupt_lines_skipped(self, tmp_path):
        from aipass.hooks.apps.handlers.notification.telegram_response import extract_mirror_turn

        transcript = tmp_path / "transcript.jsonl"
        lines = [
            _jsonl_line("user", "Question"),
            "this is {{{ not json",
            _jsonl_line("assistant", "Answer"),
        ]
        transcript.write_text("\n".join(lines), encoding="utf-8")

        with patch(LOGGER_PATCH):
            result = extract_mirror_turn(str(transcript))

        assert result is not None
        assert "You: Question" in result
        assert "Answer" in result

    def test_assistant_only_no_user_text(self, tmp_path):
        """Assistant text after cursor with no user message — still delivered."""
        from aipass.hooks.apps.handlers.notification.telegram_response import extract_mirror_turn

        transcript = tmp_path / "transcript.jsonl"
        lines = [
            _jsonl_line("assistant", "Continuation text"),
        ]
        transcript.write_text("\n".join(lines), encoding="utf-8")

        with patch(LOGGER_PATCH):
            result = extract_mirror_turn(str(transcript))

        assert result is not None
        assert "Continuation text" in result
        assert "You:" not in result

    def test_stale_cursor_clamps_to_latest_turn(self, tmp_path):
        """Cursor ahead of transcript self-heals by clamping to latest turn."""
        from aipass.hooks.apps.handlers.notification.telegram_response import extract_mirror_turn

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

        assert result is not None
        assert "You: Latest question" in result
        assert "Latest answer" in result

    def test_stale_cursor_no_user_msg_delivers_all(self, tmp_path):
        """Stale cursor with no user messages — delivers all assistant text."""
        from aipass.hooks.apps.handlers.notification.telegram_response import extract_mirror_turn

        transcript = tmp_path / "transcript.jsonl"
        lines = [
            _jsonl_line("assistant", "Some output"),
        ]
        transcript.write_text("\n".join(lines), encoding="utf-8")

        with patch(LOGGER_PATCH):
            result = extract_mirror_turn(str(transcript), start_line=99)

        assert result is not None
        assert "Some output" in result


# ===========================================================================
# find_pending_file — mirror directory
# ===========================================================================


class TestFindPendingFileMirror:
    """Mirror directory search for persistent mapping files."""

    def test_mirror_dir_env_bot_id_match(self, tmp_path):
        from aipass.hooks.apps.handlers.notification.telegram_response import find_pending_file

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
            result = find_pending_file("session-xyz")

        assert result is not None
        assert result.name == "bot-42.json"

    def test_mirror_dir_preferred_over_pending_for_env(self, tmp_path):
        """Mirror dir is checked before pending dir for AIPASS_BOT_ID match."""
        from aipass.hooks.apps.handlers.notification.telegram_response import find_pending_file

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
            result = find_pending_file("session-xyz")

        assert result is not None
        assert str(mirror_dir) in str(result)

    def test_mirror_dir_cwd_match(self, tmp_path):
        from aipass.hooks.apps.handlers.notification.telegram_response import find_pending_file

        mirror_dir = tmp_path / "telegram_bots"
        mirror_dir.mkdir()
        work = tmp_path / "project"
        work.mkdir()
        data = {"timestamp": time.time(), "work_dir": str(work), "mirror": True}
        (mirror_dir / "bot-7.json").write_text(json.dumps(data), encoding="utf-8")

        with (
            patch(LOGGER_PATCH),
            patch(f"{MOD}.MIRROR_DIR", mirror_dir),
            patch(f"{MOD}.PENDING_DIR", tmp_path / "nonexistent"),
            patch.dict("os.environ", {}, clear=True),
            patch(f"{MOD}.Path.cwd", return_value=work / "subdir"),
        ):
            result = find_pending_file("session-abc")

        assert result is not None
        assert result.name == "bot-7.json"


# ===========================================================================
# handle — mirror integration tests
# ===========================================================================


class TestHandleMirrorIntegration:
    """Full handle() flow for mirror sessions."""

    def test_mirror_user_typed_directly_delivered(self, tmp_path):
        """User types directly in terminal — mirror delivers to TG."""
        from aipass.hooks.apps.handlers.notification.telegram_response import handle

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
            patch(f"{MOD}.Path.cwd", return_value=tmp_path),
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

    def test_mirror_tg_injected_no_double_send(self, tmp_path):
        """TG-injected turn — cursor advancement prevents re-delivery."""
        from aipass.hooks.apps.handlers.notification.telegram_response import handle

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
            patch(f"{MOD}.time.sleep"),
            patch(f"{MOD}.Path.cwd", return_value=tmp_path),
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

    def test_mirror_cursor_advances_no_redelivery(self, tmp_path):
        """Cursor advances after mirror delivery — old turns not re-sent."""
        from aipass.hooks.apps.handlers.notification.telegram_response import handle

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
            patch(f"{MOD}.Path.cwd", return_value=tmp_path),
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
        from aipass.hooks.apps.handlers.notification.telegram_response import handle

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

    def test_mirror_no_processing_message_sends_fresh(self, tmp_path):
        """Mirror sessions have no processing_message_id — always send fresh."""
        from aipass.hooks.apps.handlers.notification.telegram_response import handle

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
            patch(f"{MOD}.Path.cwd", return_value=tmp_path),
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
        from aipass.hooks.apps.handlers.notification.telegram_response import _advance_pending

        pending_file = tmp_path / "pending.json"
        pending_data = {"chat_id": 1, "mirror": True}
        pending_file.write_text(json.dumps(pending_data), encoding="utf-8")

        with patch(LOGGER_PATCH):
            _advance_pending(pending_file, pending_data, "")

        assert pending_file.exists()

    def test_mirror_transcript_failure_kept(self, tmp_path):
        from aipass.hooks.apps.handlers.notification.telegram_response import _advance_pending

        pending_file = tmp_path / "pending.json"
        pending_data = {"chat_id": 1, "mirror": True}
        pending_file.write_text(json.dumps(pending_data), encoding="utf-8")

        with patch(LOGGER_PATCH):
            _advance_pending(pending_file, pending_data, "/nonexistent/transcript.jsonl")

        assert pending_file.exists()
