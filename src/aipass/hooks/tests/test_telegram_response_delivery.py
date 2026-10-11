# =================== AIPass ====================
# Name: test_telegram_response_delivery.py
# Description: telegram_response's delivery lane: retry, branch prefix, chunk delivery, cursor advance, delivery log
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-08
# =============================================

"""Tests for apps/handlers/notification/telegram_response.py: its delivery lane."""

# How a response reaches Telegram once handle() has it. handle() itself is
# test_telegram_response.py; mirror sessions are test_telegram_response_mirror.py.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that telegram_response.py parses and imports, ruff and collection cover it
# seedgo: no-test-needed(stdlib) — urlopen()'s HTTP transport, the stdlib's own

import json
from pathlib import Path
from unittest.mock import patch

from aipass.hooks.apps.handlers.notification.telegram_response import (
    _advance_pending,
    _deliver_chunks,
    _prepend_branch_prefix,
    _send_with_retry,
    _write_delivery_log,
)
from aipass.hooks.tests.support_telegram_response import LOGGER_PATCH, MOD, _ok_result, _record_waits


def _fail_result():
    """Build a failed send/edit result dict."""
    return {"ok": False}


# ===========================================================================
# _send_with_retry
# ===========================================================================


class TestSendWithRetry:
    """Retry mechanism with exponential backoff."""

    def test_success_on_first_try(self):
        with patch(LOGGER_PATCH), patch(f"{MOD}.send_to_telegram", return_value=_ok_result()) as mock_send:
            result = _send_with_retry("tok:ABC", 123, "Hello")

        assert result["ok"] is True
        assert mock_send.call_count == 1

    def test_success_on_retry(self, monkeypatch):
        waits = _record_waits(monkeypatch)
        with (
            patch(LOGGER_PATCH),
            patch(f"{MOD}.send_to_telegram", side_effect=[_fail_result(), _ok_result()]) as mock_send,
        ):
            result = _send_with_retry("tok:ABC", 123, "Hello")

        assert result["ok"] is True
        assert mock_send.call_count == 2
        assert waits == [1.0]

    def test_all_retries_fail(self, monkeypatch):
        waits = _record_waits(monkeypatch)
        with (
            patch(LOGGER_PATCH),
            patch(f"{MOD}.send_to_telegram", return_value=_fail_result()) as mock_send,
        ):
            result = _send_with_retry("tok:ABC", 123, "Hello", retries=3)

        assert result["ok"] is False
        assert mock_send.call_count == 3
        assert waits == [1.0, 2.0]


# ===========================================================================
# _prepend_branch_prefix
# ===========================================================================


class TestPrependBranchPrefix:
    """Branch prefix added to response text."""

    def test_adds_branch_prefix(self, tmp_path, monkeypatch):
        (tmp_path / "flow").mkdir()
        monkeypatch.chdir(tmp_path / "flow")
        with patch(LOGGER_PATCH):
            result = _prepend_branch_prefix("Hello")

        assert result == "@flow\n\nHello"

    def test_cwd_failure_returns_original(self):
        def unreadable() -> Path:
            raise OSError("no cwd")

        with patch(LOGGER_PATCH) as log:
            result = _prepend_branch_prefix("Hello", cwd=unreadable)

        assert result == "Hello"
        log.info.assert_called_once_with("[HOOKS] telegram: could not resolve CWD for branch prefix")


# ===========================================================================
# _deliver_chunks
# ===========================================================================


class TestDeliverChunks:
    """Chunk delivery with edit/send logic."""

    def test_single_chunk_no_processing_msg(self):
        with patch(LOGGER_PATCH), patch(f"{MOD}._send_with_retry", return_value=_ok_result()) as mock_send:
            all_sent, chunk_results = _deliver_chunks(["Hello"], "tok", 123, None, False)

        assert all_sent is True
        assert len(chunk_results) == 1
        assert chunk_results[0]["method"] == "send"
        mock_send.assert_called_once_with("tok", 123, "Hello")

    def test_single_chunk_with_processing_msg_edits(self):
        with patch(LOGGER_PATCH), patch(f"{MOD}.edit_telegram_message", return_value=_ok_result()) as mock_edit:
            all_sent, chunk_results = _deliver_chunks(["Hello"], "tok", 123, 789, False)

        assert all_sent is True
        assert chunk_results[0]["method"] == "edit"
        mock_edit.assert_called_once_with("tok", 123, 789, "Hello")

    def test_single_chunk_edit_fails_falls_back_to_send(self):
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
        with (
            patch(LOGGER_PATCH),
            patch(f"{MOD}.edit_telegram_message", return_value=_ok_result()) as mock_edit,
            patch(f"{MOD}._send_with_retry", return_value=_ok_result()),
        ):
            _deliver_chunks(["Part A", "Part B"], "tok", 123, 789, False, streaming=False)

        mock_edit.assert_called_once_with("tok", 123, 789, "Done.")

    def test_streaming_single_no_logs_still_edits(self):
        """Streaming + single chunk + no logs: same as batch — reconcile-edit."""
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
        pending_file = tmp_path / "pending.json"
        pending_data = {"chat_id": 1}
        pending_file.write_text(json.dumps(pending_data), encoding="utf-8")

        with patch(LOGGER_PATCH):
            _advance_pending(pending_file, pending_data, "")

        assert not pending_file.exists()

    def test_transcript_read_failure_removes_pending(self, tmp_path):
        pending_file = tmp_path / "pending.json"
        pending_data = {"chat_id": 1}
        pending_file.write_text(json.dumps(pending_data), encoding="utf-8")

        with patch(LOGGER_PATCH):
            _advance_pending(pending_file, pending_data, str(tmp_path / "nonexistent" / "transcript.jsonl"))

        assert not pending_file.exists()

    def test_clears_processing_message_id_after_advance(self, tmp_path):
        """After advance, processing_message_id is None so next Stop sends new msg, not edit."""
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
        log_path = tmp_path / "delivery.jsonl"

        with patch(LOGGER_PATCH), patch(f"{MOD}._get_delivery_log", return_value=log_path):
            _write_delivery_log(
                "hello",
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
        log_path = tmp_path / "delivery.jsonl"

        with patch(LOGGER_PATCH), patch(f"{MOD}._get_delivery_log", return_value=log_path):
            _write_delivery_log(
                "**bold text**",
                [{"idx": 0, "method": "send", "ok": True, "message_id": 1, "text": "bold text"}],
                "session123",
            )

        record = json.loads(log_path.read_text(encoding="utf-8").strip())
        assert record["match"] is False
        assert "culprit" in record

    def test_failed_chunk_culprit(self, tmp_path):
        log_path = tmp_path / "delivery.jsonl"

        with patch(LOGGER_PATCH), patch(f"{MOD}._get_delivery_log", return_value=log_path):
            _write_delivery_log(
                "hello",
                [{"idx": 0, "method": "send", "ok": False, "text": ""}],
                "sess",
            )

        record = json.loads(log_path.read_text(encoding="utf-8").strip())
        assert record["match"] is False
        assert "delivery_failed" in record["culprit"]

    def test_log_write_failure_does_not_raise(self, tmp_path):
        """An unwritable delivery log is reported, not swallowed and not raised.

        Had no oracle: it called _write_delivery_log inside a mocked logger and
        asserted nothing. A version that caught the OSError and dropped it on
        the floor passed identically to one that reported it - and "the record
        silently stopped being written" is the failure this whole file exists
        to make impossible.

        The failure is injected at the seam the function itself calls
        (``append_jsonl``), not through the filesystem's mood: a POSIX-only
        path like `/dev/null/impossible/...` or a chmod'd directory never
        raises on Windows, which ignores owner mode bits, so the write would
        silently succeed there and the "must warn" assertion would never fire.
        """
        log_path = tmp_path / "delivery.jsonl"
        with (
            patch(LOGGER_PATCH) as mock_logger,
            patch(f"{MOD}._get_delivery_log", return_value=log_path),
            patch(f"{MOD}.append_jsonl", side_effect=OSError("disk full")),
        ):
            _write_delivery_log("hi", [{"idx": 0, "ok": True, "text": "hi"}], "s")

        assert mock_logger.warning.call_count == 1
        assert "delivery log write failed" in mock_logger.warning.call_args[0][0]
        assert not log_path.exists()
