# =================== AIPass ====================
# Name: test_telegram_response.py
# Version: 2.1.0
# Description: Tests for telegram_response notification handler
# Branch: hooks
# Layer: tests
# Created: 2026-06-15
# Modified: 2026-10-08
# =============================================

"""Tests for apps/handlers/notification/telegram_response.py."""

# handle() and the public senders, formatters and readers. The delivery
# helpers are test_telegram_response_delivery.py; mirror sessions are
# test_telegram_response_mirror.py.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that telegram_response.py parses and imports, ruff and collection cover it
# seedgo: no-test-needed(documentation) — handle()'s docstring, the documentation checker covers it
# seedgo: no-test-needed(constant) — PENDING_TTL's and TELEGRAM_CHAR_LIMIT's values, fixed literals
# seedgo: no-test-needed(stdlib) — urlopen()'s HTTP transport, the stdlib's own

import io
import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

from aipass.hooks.apps.handlers.notification.telegram_response import (
    chunk_text,
    edit_telegram_message,
    extract_assistant_response,
    extract_mirror_turn,
    find_pending_file,
    handle,
    markdown_to_telegram_html,
    send_to_telegram,
)
from aipass.hooks.tests.support_telegram_response import (
    LOGGER_PATCH,
    MOD,
    _found,
    _jsonl_line,
    _kept_redirect,
    _record_waits,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


# ===========================================================================
# Layer 1 defense — handle() early returns
# ===========================================================================


class TestHandleLayer1Defense:
    """Layer 1: gate-level filtering in handle()."""

    def test_subagent_stop_returns_early(self):
        with patch(LOGGER_PATCH):
            result = handle({"hook_event_name": "SubagentStop", "session_id": "abc"})

        assert result == {"stdout": "", "exit_code": 0}

    def test_subagent_transcript_path_returns_early(self):
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
        with patch(LOGGER_PATCH):
            result = handle({"hook_event_name": "Stop"})

        assert result == {"stdout": "", "exit_code": 0}

    def test_no_pending_file_returns_early(self):
        with patch(LOGGER_PATCH), patch(f"{MOD}.find_pending_file", return_value=None):
            result = handle({"hook_event_name": "Stop", "session_id": "abc123"})

        assert result == {"stdout": "", "exit_code": 0}


# ===========================================================================
# find_pending_file
# ===========================================================================


class TestFindPendingFile:
    """Multi-bot pending file resolution."""

    def test_env_bot_id_direct_match(self, tmp_path):
        pending_dir = tmp_path / "telegram_pending"
        pending_dir.mkdir()
        data = {"timestamp": time.time(), "work_dir": str(tmp_path)}
        (pending_dir / "bot-42.json").write_text(json.dumps(data), encoding="utf-8")

        with (
            patch(LOGGER_PATCH),
            patch(f"{MOD}.PENDING_DIR", pending_dir),
            patch.dict("os.environ", {"AIPASS_BOT_ID": "42"}),
        ):
            result = find_pending_file()

        assert result is not None
        assert result.name == "bot-42.json"

    def test_cwd_relative_match(self, tmp_path, monkeypatch):
        pending_dir = tmp_path / "telegram_pending"
        pending_dir.mkdir()
        work = tmp_path / "project"
        (work / "subdir").mkdir(parents=True)
        data = {"timestamp": time.time(), "work_dir": str(work)}
        (pending_dir / "bot-7.json").write_text(json.dumps(data), encoding="utf-8")
        monkeypatch.chdir(work / "subdir")

        with (
            patch(LOGGER_PATCH),
            patch(f"{MOD}.PENDING_DIR", pending_dir),
            patch.dict("os.environ", _kept_redirect(), clear=True),
        ):
            result = find_pending_file()

        assert result is not None
        assert result.name == "bot-7.json"

    def test_no_pending_dir_returns_none(self, tmp_path):
        missing = tmp_path / "nonexistent"

        with patch(LOGGER_PATCH), patch(f"{MOD}.PENDING_DIR", missing):
            result = find_pending_file()

        assert result is None

    def test_expired_pending_skipped(self, tmp_path):
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
            result = find_pending_file()

        assert result is None

    def test_non_expired_pending_returned(self, tmp_path):
        pending_dir = tmp_path / "telegram_pending"
        pending_dir.mkdir()
        data = {"timestamp": time.time(), "work_dir": str(tmp_path)}
        (pending_dir / "bot-5.json").write_text(json.dumps(data), encoding="utf-8")

        with (
            patch(LOGGER_PATCH),
            patch(f"{MOD}.PENDING_DIR", pending_dir),
            patch.dict("os.environ", {"AIPASS_BOT_ID": "5"}),
        ):
            result = find_pending_file()

        assert result is not None
        assert result.name == "bot-5.json"

    def test_no_work_dir_in_pending_skipped(self, tmp_path):
        """When CWD fallback is used and pending has no work_dir, skip it."""
        pending_dir = tmp_path / "telegram_pending"
        pending_dir.mkdir()
        data = {"timestamp": time.time()}  # no work_dir
        (pending_dir / "bot-1.json").write_text(json.dumps(data), encoding="utf-8")

        with (
            patch(LOGGER_PATCH),
            patch(f"{MOD}.PENDING_DIR", pending_dir),
            patch.dict("os.environ", _kept_redirect(), clear=True),
        ):
            result = find_pending_file()

        assert result is None

    def test_a_file_not_named_bot_star_is_never_matched(self, tmp_path, monkeypatch):
        """Absorbed from skills' test_multibot_integration: only bot-*.json is read; a telegram-*.json whose
        work_dir holds the cwd would match on everything but its name."""
        pending_dir = tmp_path / "telegram_pending"
        pending_dir.mkdir()
        work = tmp_path / "project"
        work.mkdir()
        data = {"timestamp": time.time(), "work_dir": str(work)}
        (pending_dir / "telegram-something.json").write_text(json.dumps(data), encoding="utf-8")
        monkeypatch.chdir(work)

        with (
            patch(LOGGER_PATCH),
            patch(f"{MOD}.PENDING_DIR", pending_dir),
            patch(f"{MOD}.MIRROR_DIR", tmp_path / "no_mirror"),
            patch.dict("os.environ", _kept_redirect(), clear=True),
        ):
            result = find_pending_file()

        assert result is None


# ===========================================================================
# _is_expired
# ===========================================================================


class TestIsExpired:
    """TTL + tmux-alive expiry logic, read as whether find_pending_file still hands the file back."""

    def test_fresh_not_expired(self, tmp_path):
        assert _found(tmp_path, {"timestamp": time.time()}) is True

    def test_half_an_hour_old_is_inside_the_one_hour_ttl(self, tmp_path):
        """Absorbed from skills' test_multibot_integration: the TTL is an hour, so 30 minutes old with no tmux
        session to ask about is still handed back."""
        assert _found(tmp_path, {"timestamp": time.time() - 1800}) is True

    def test_old_no_tmux_expired(self, tmp_path):
        with patch(f"{MOD}.subprocess.run") as mock_run:
            mock_run.side_effect = OSError("no tmux")
            assert _found(tmp_path, {"timestamp": time.time() - 7200, "session_name": "s"}) is False

    def test_old_tmux_alive_not_expired(self, tmp_path):
        tmux_result = MagicMock()
        tmux_result.returncode = 0

        with patch(f"{MOD}.subprocess.run", return_value=tmux_result):
            result = _found(tmp_path, {"timestamp": time.time() - 7200, "session_name": "my-session"})

        assert result is True

    def test_old_tmux_dead_expired(self, tmp_path):
        tmux_result = MagicMock()
        tmux_result.returncode = 1

        with patch(f"{MOD}.subprocess.run", return_value=tmux_result):
            result = _found(tmp_path, {"timestamp": time.time() - 7200, "session_name": "dead-session"})

        assert result is False

    def test_string_timestamp_handling(self, tmp_path):
        assert _found(tmp_path, {"timestamp": str(time.time())}) is True

    def test_invalid_string_timestamp_treated_as_zero(self, tmp_path):
        assert _found(tmp_path, {"timestamp": "not-a-number"}) is False

    def test_no_session_name_old_expired(self, tmp_path):
        """Old entry with no session_name -> expired (tmux check skipped)."""
        assert _found(tmp_path, {"timestamp": time.time() - 7200}) is False


# ===========================================================================
# extract_assistant_response
# ===========================================================================


class TestExtractAssistantResponse:
    """JSONL transcript extraction with Layer 2 and Layer 3 defenses."""

    def test_normal_extraction(self, tmp_path):
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
        assert result == "First answer\n\nContinuation of first answer"

    def test_start_line_offset(self, tmp_path):
        """Layer 3: transcript_line_after skips earlier entries."""
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
        assert result == "Starting work...\n\nDone with the work"

    def test_no_user_message_returns_none(self, tmp_path):
        transcript = tmp_path / "transcript.jsonl"
        lines = [
            _jsonl_line("assistant", "Hello"),
        ]
        transcript.write_text("\n".join(lines), encoding="utf-8")

        with patch(LOGGER_PATCH):
            result = extract_assistant_response(str(transcript))

        assert result is None

    def test_empty_transcript_returns_none(self, tmp_path):
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text("", encoding="utf-8")

        with patch(LOGGER_PATCH):
            result = extract_assistant_response(str(transcript))

        assert result is None

    def test_missing_transcript_returns_none(self, tmp_path):
        with patch(LOGGER_PATCH):
            result = extract_assistant_response(str(tmp_path / "nonexistent" / "path.jsonl"))

        assert result is None

    def test_corrupt_jsonl_lines_skipped(self, tmp_path):
        """Malformed JSON lines are gracefully skipped."""
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
# Cursor ahead of transcript (devpulse c361b355)
# ===========================================================================


class TestCursorAheadOfTranscript:
    """A cursor past the end of the transcript is a stuck delivery, not a quiet one.

    Live evidence, 2026-08-14: 117 'no user message found' WARNINGs in the current
    log, ALL from one session (ec388200), ALL at the identical start_line=10409,
    over ten hours - against a transcript 2544 lines long. The cursor sat 7865 lines
    past the end, so every Stop sliced an empty window and found no user message,
    forever. extract_mirror_turn already clamps this exact case; the non-mirror path
    did not.
    """

    def _transcript(self, tmp_path, extra_turns: int = 0):
        transcript = tmp_path / "transcript.jsonl"
        lines = [_jsonl_line("user", "Question"), _jsonl_line("assistant", "Answer")]
        for i in range(extra_turns):
            lines.append(_jsonl_line("user", f"Follow-up {i}"))
            lines.append(_jsonl_line("assistant", f"Reply {i}"))
        transcript.write_text("\n".join(lines), encoding="utf-8")
        return transcript

    def test_cursor_ahead_of_transcript_still_delivers(self, tmp_path):
        """The live failure: 4x-past-the-end cursor must not swallow the reply."""
        transcript = self._transcript(tmp_path)

        with patch(LOGGER_PATCH):
            result = extract_assistant_response(str(transcript), start_line=10409)

        assert result == "Answer"

    def test_the_clamp_delivers_the_latest_turn_not_the_whole_history(self, tmp_path):
        """Clamping to the last real user message, same rule the mirror path uses."""
        transcript = self._transcript(tmp_path, extra_turns=3)

        with patch(LOGGER_PATCH):
            result = extract_assistant_response(str(transcript), start_line=9999)

        assert result == "Reply 2"
        assert "Answer" not in result

    def test_the_clamp_names_both_numbers(self, tmp_path):
        """The log line has to carry the cursor AND the length — that pair is what
        turned 117 identical WARNINGs into a diagnosis."""
        transcript = self._transcript(tmp_path)

        with patch(LOGGER_PATCH) as mock_logger:
            extract_assistant_response(str(transcript), start_line=10409)

        warned = " ".join(str(call) for call in mock_logger.warning.call_args_list)
        assert "cursor ahead" in warned
        assert "10409" in warned
        assert "2" in warned

    def test_a_cursor_inside_the_transcript_is_untouched(self, tmp_path):
        """The clamp must only fire past the end — a normal cursor still slices."""
        transcript = self._transcript(tmp_path, extra_turns=1)

        with patch(LOGGER_PATCH) as mock_logger:
            result = extract_assistant_response(str(transcript), start_line=2)

        assert result == "Reply 0"
        warned = " ".join(str(call) for call in mock_logger.warning.call_args_list)
        assert "cursor ahead" not in warned

    def test_a_transcript_with_no_user_message_at_all_still_warns(self, tmp_path):
        """@devpulse asked for a guard: the genuinely-broken sub-case stays loud.

        Clamping cannot invent a user message. When one truly is not there, the
        WARNING is the only evidence a Telegram reply was dropped."""
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text(_jsonl_line("assistant", "Orphan"), encoding="utf-8")

        with patch(LOGGER_PATCH) as mock_logger:
            result = extract_assistant_response(str(transcript), start_line=500)

        assert result is None
        warned = " ".join(str(call) for call in mock_logger.warning.call_args_list)
        assert "no user message found" in warned

    def test_the_benign_sibling_stays_info(self, tmp_path):
        """Guard against a blanket reclass: 'no assistant text' is the quiet case and
        was already INFO. It fired 0 times in the live log while the -1 case fired 117."""
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text(_jsonl_line("user", "Question"), encoding="utf-8")

        with patch(LOGGER_PATCH) as mock_logger:
            result = extract_assistant_response(str(transcript))

        assert result is None
        mock_logger.warning.assert_not_called()
        info = " ".join(str(call) for call in mock_logger.info.call_args_list)
        assert "no assistant text after last user msg" in info

    def test_the_mirror_path_still_clamps(self, tmp_path):
        """Canary: the mirror clamp existed first and must survive being shared."""
        transcript = self._transcript(tmp_path)

        with patch(LOGGER_PATCH):
            result = extract_mirror_turn(str(transcript), start_line=10409)

        assert result == "You: Question\n\nAnswer"


# ===========================================================================
# chunk_text
# ===========================================================================


class TestChunkText:
    """Text splitting for Telegram's 4096-char limit."""

    def test_short_text_single_chunk(self):
        result = chunk_text("Hello world")
        assert result == ["Hello world"]

    def test_exact_limit_single_chunk(self):
        text = "x" * 4096
        result = chunk_text(text)
        assert len(result) == 1

    def test_long_text_multiple_chunks(self):
        text = "Hello world. " * 1000  # ~13000 chars
        result = chunk_text(text, limit=500)
        assert len(result) > 1
        # Reconstruct and verify nothing lost
        for chunk in result:
            assert len(chunk) <= 500

    def test_break_at_sentence_end(self):
        # Build text where a sentence ends near the limit boundary
        sentence = "A" * 480 + ". "
        text = sentence + "B" * 200
        result = chunk_text(text, limit=500)
        assert len(result) == 2
        assert result[0].endswith(".")

    def test_break_at_paragraph(self):
        para1 = "A" * 300
        para2 = "B" * 300
        text = para1 + "\n\n" + para2
        result = chunk_text(text, limit=400)
        assert len(result) == 2

    def test_break_at_newline(self):
        part1 = "A" * 300
        part2 = "B" * 300
        text = part1 + "\n" + part2
        result = chunk_text(text, limit=400)
        assert len(result) == 2

    def test_break_at_space(self):
        # Words with spaces — no sentence endings, no newlines in the break zone
        text = ("word " * 100).strip()  # ~499 chars
        result = chunk_text(text, limit=200)
        assert len(result) > 1
        for chunk in result:
            assert len(chunk) <= 200

    def test_empty_text(self):
        result = chunk_text("")
        assert result == [""]

    def test_text_with_no_boundary_is_cut_hard_at_the_limit(self):
        """Absorbed from skills' test_multibot_integration: no sentence, newline or space to break at."""
        assert chunk_text("a" * 200, limit=100) == ["a" * 100, "a" * 100]


# ===========================================================================
# markdown_to_telegram_html
# ===========================================================================


class TestMarkdownToTelegramHtml:
    """Markdown -> Telegram HTML conversion."""

    def test_code_blocks_preserved(self):
        text = "Before\n```python\nprint('hello')\n```\nAfter"
        result = markdown_to_telegram_html(text)
        assert '<pre><code class="language-python">' in result
        assert "print(" in result and "hello" in result

    def test_code_block_no_language(self):
        text = "Before\n```\nsome code\n```\nAfter"
        result = markdown_to_telegram_html(text)
        assert "<pre>" in result
        assert "some code" in result

    def test_inline_code_preserved(self):
        text = "Use `foo()` here"
        result = markdown_to_telegram_html(text)
        assert "<code>foo()</code>" in result

    def test_bold_converted(self):
        text = "This is **bold** text"
        result = markdown_to_telegram_html(text)
        assert "<b>bold</b>" in result

    def test_italic_converted(self):
        text = "This is *italic* text"
        result = markdown_to_telegram_html(text)
        assert "<i>italic</i>" in result

    def test_html_entities_escaped(self):
        text = "Use <div> & stuff > here"
        result = markdown_to_telegram_html(text)
        assert "&lt;div&gt;" in result
        assert "&amp;" in result

    def test_mixed_content(self):
        text = "**Bold** and *italic* with `code` and <tag>"
        result = markdown_to_telegram_html(text)
        assert "<b>Bold</b>" in result
        assert "<i>italic</i>" in result
        assert "<code>code</code>" in result
        assert "&lt;tag&gt;" in result

    def test_code_block_content_not_formatted(self):
        """Markdown inside code blocks should not be converted to HTML tags."""
        text = "```\n**not bold** *not italic*\n```"
        result = markdown_to_telegram_html(text)
        # Inside <pre>, the ** and * should be escaped, not converted
        assert "<b>" not in result.split("<pre>")[1].split("</pre>")[0]
        assert "<i>" not in result.split("<pre>")[1].split("</pre>")[0]

    def test_inline_code_content_not_formatted(self):
        """Markdown inside inline code should not be converted."""
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
        with patch(LOGGER_PATCH), patch(f"{MOD}.urlopen", return_value=_mock_urlopen_ok()):
            result = send_to_telegram("tok:ABC", 123, "Hello")

        assert result["ok"] is True
        assert result["message_id"] == 100

    def test_html_fails_plain_text_fallback_succeeds(self):
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
        with patch(LOGGER_PATCH), patch(f"{MOD}.urlopen", side_effect=Exception("network error")):
            result = send_to_telegram("tok:ABC", 123, "Hello")

        assert result["ok"] is False

    def test_http_error_handling(self):
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
        captured_requests = []

        def urlopen_capture(req, **kwargs):
            captured_requests.append(json.loads(req.data.decode()))
            return _mock_urlopen_ok()

        with patch(LOGGER_PATCH), patch(f"{MOD}.urlopen", side_effect=urlopen_capture):
            send_to_telegram("tok:ABC", 123, "Hello", message_id=456)

        assert captured_requests[0]["reply_to_message_id"] == 456

    def test_returns_message_text_from_api(self):
        with patch(LOGGER_PATCH), patch(f"{MOD}.urlopen", return_value=_mock_urlopen_ok(text="returned")):
            result = send_to_telegram("tok:ABC", 123, "Hello")

        assert result["text"] == "returned"


# ===========================================================================
# edit_telegram_message
# ===========================================================================


class TestEditTelegramMessage:
    """Telegram Bot API edit with HTML->plain text fallback."""

    def test_successful_html_edit(self):
        with patch(LOGGER_PATCH), patch(f"{MOD}.urlopen", return_value=_mock_urlopen_ok()):
            result = edit_telegram_message("tok:ABC", 123, 789, "Updated text")

        assert result["ok"] is True
        assert result["message_id"] == 100

    def test_html_edit_fails_plain_text_fallback(self):
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
        with patch(LOGGER_PATCH), patch(f"{MOD}.urlopen", side_effect=Exception("total failure")):
            result = edit_telegram_message("tok:ABC", 123, 789, "Text")

        assert result["ok"] is False

    def test_edit_url_uses_edit_message_text(self):
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

    def test_happy_path_send_and_advance(self, tmp_path, monkeypatch):
        """Full flow: pending exists -> extract -> send -> advance cursor."""
        monkeypatch.chdir(tmp_path)
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

    def test_send_fails_pending_kept(self, tmp_path, monkeypatch):
        """When delivery fails, pending file is kept for retry."""
        monkeypatch.chdir(tmp_path)
        waits = _record_waits(monkeypatch)
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
        assert waits == [1.0, 2.0]

    def test_no_response_text_pending_kept(self, tmp_path, monkeypatch):
        """When no response text is extracted, pending is kept."""
        monkeypatch.chdir(tmp_path)
        waits = _record_waits(monkeypatch)
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
        assert waits == [0.2, 0.5]

    def test_jsonl_retry_mechanism(self, tmp_path, monkeypatch):
        """JSONL extraction retries on flush-race (empty first attempt)."""
        monkeypatch.chdir(tmp_path)
        waits = _record_waits(monkeypatch)
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
        assert waits == [0.2]

    def test_fallback_to_last_assistant_message(self, tmp_path, monkeypatch):
        """When JSONL extraction fails, falls back to last_assistant_message from hook_data."""
        monkeypatch.chdir(tmp_path)
        waits = _record_waits(monkeypatch)
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
        assert waits == []

    def test_already_delivered_skips_fallback(self, tmp_path, monkeypatch):
        """After first delivery, last_assistant_message fallback is skipped."""
        monkeypatch.chdir(tmp_path)
        waits = _record_waits(monkeypatch)
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
        assert waits == [0.2, 0.5]

    def test_missing_chat_id_cleans_pending(self, tmp_path):
        """Pending with missing chat_id is cleaned up."""
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
