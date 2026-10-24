# =================== AIPass ====================
# Name: test_filesystem_handler_codex.py
# Description: Unit tests for filesystem_handler's Codex session lane
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-23
# =============================================

"""Tests for apps/handlers/monitoring/filesystem_handler.py, its Codex session lane."""

# Split from test_filesystem_handler.py (2026-10-08).
#
# Covers: _branch_from_cwd, _read_codex_cwd, _get_codex_branch,
# _extract_codex_action, _parse_codex_response_item, _extract_codex_model,
# _parse_codex_activity.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(through_the_command) — _emit_agent_event, covered by test_filesystem_handler_agent_activity.py

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from aipass.prax.tests.support_test_filesystem_handler import _import_filesystem_handler, _make_handler, _on_disk

pytestmark = pytest.mark.usefixtures("_filesystem_handler_doubled")


# =============================================
# BRANCH FROM CWD TESTS
# =============================================


class TestBranchFromCwd:
    """Tests for _branch_from_cwd static method."""

    def test_aipass_branch(self, tmp_path):
        """Should extract branch name after aipass in path."""
        mod, _, _, _, _ = _import_filesystem_handler()
        cls = mod.MonitoringFileHandler
        result = cls._branch_from_cwd(str(tmp_path / "Projects" / "AIPass" / "src" / "aipass" / "prax"))
        assert result == "PRAX"

    def test_empty_string(self):
        """Should return None for empty CWD."""
        mod, _, _, _, _ = _import_filesystem_handler()
        cls = mod.MonitoringFileHandler
        result = cls._branch_from_cwd("")
        assert result is None

    def test_src_fallback(self):
        """Should fall back to src/name for paths without aipass."""
        mod, _, _, _, _ = _import_filesystem_handler()
        cls = mod.MonitoringFileHandler
        with patch.object(mod, "detect_branch_from_path", return_value="UNKNOWN"):
            result = cls._branch_from_cwd("/opt/src/myproject/subdir")
        assert result == "MYPROJECT"

    def test_no_aipass_no_src(self, tmp_path):
        """Should return None when no recognizable pattern."""
        mod, _, _, _, _ = _import_filesystem_handler()
        cls = mod.MonitoringFileHandler
        result = cls._branch_from_cwd(str(tmp_path / "random" / "dir"))
        assert result is None

    def test_aipass_at_end_of_path(self, tmp_path):
        """Should return None when aipass is the last segment."""
        mod, _, _, _, _ = _import_filesystem_handler()
        cls = mod.MonitoringFileHandler
        result = cls._branch_from_cwd(str(tmp_path / "aipass"))
        assert result is None

    def test_projects_external_detected(self):
        """Should detect external projects under ~/Projects."""
        mod, _, _, _, _ = _import_filesystem_handler()
        cls = mod.MonitoringFileHandler
        home = str(Path.home())
        ext_path = f"{home}/Projects/AIPL/src/polyglot"
        with patch.object(mod, "detect_branch_from_path", return_value="AIPL/POLYGLOT"):
            result = cls._branch_from_cwd(ext_path)
        assert result == "AIPL/POLYGLOT"

    def test_projects_external_unknown_falls_through(self):
        """When detect returns UNKNOWN, should try src fallback."""
        mod, _, _, _, _ = _import_filesystem_handler()
        cls = mod.MonitoringFileHandler
        home = str(Path.home())
        ext_path = f"{home}/Projects/AIPL/src/polyglot"
        with patch.object(mod, "detect_branch_from_path", return_value="UNKNOWN"):
            result = cls._branch_from_cwd(ext_path)
        assert result == "POLYGLOT"


# =============================================
# READ CODEX CWD TESTS
# =============================================


class TestReadCodexCwd:
    """Tests for _read_codex_cwd."""

    def test_reads_cwd_from_session_meta(self, tmp_path):
        """Should read CWD from first line of Codex JSONL."""
        mod, _, _, _, _ = _import_filesystem_handler()
        handler = _make_handler(mod)
        cwd = str(tmp_path / "project")
        meta_line = json.dumps({"type": "session_meta", "payload": {"cwd": cwd}})
        result = handler._read_codex_cwd(str(_on_disk(tmp_path, meta_line + "\n")))
        assert result == cwd

    def test_empty_first_line(self, tmp_path):
        """Should return None for empty first line."""
        mod, _, _, _, _ = _import_filesystem_handler()
        handler = _make_handler(mod)
        result = handler._read_codex_cwd(str(_on_disk(tmp_path, "\n")))
        assert result is None

    def test_not_session_meta(self, tmp_path):
        """Should return None if first line is not session_meta type."""
        mod, _, _, _, _ = _import_filesystem_handler()
        handler = _make_handler(mod)
        meta_line = json.dumps({"type": "event_msg", "payload": {}})
        result = handler._read_codex_cwd(str(_on_disk(tmp_path, meta_line + "\n")))
        assert result is None

    def test_os_error(self, tmp_path):
        """Should return None when the session file cannot be opened: here, it is absent."""
        mod, _, _, _, _ = _import_filesystem_handler()
        handler = _make_handler(mod)
        result = handler._read_codex_cwd(str(tmp_path / "session.jsonl"))
        assert result is None

    def test_json_decode_error(self, tmp_path):
        """Should return None on JSONDecodeError."""
        mod, _, _, _, _ = _import_filesystem_handler()
        handler = _make_handler(mod)
        result = handler._read_codex_cwd(str(_on_disk(tmp_path, "not json\n")))
        assert result is None


# =============================================
# GET CODEX BRANCH TESTS
# =============================================


class TestGetCodexBranch:
    """Tests for _get_codex_branch."""

    def test_cached_branch(self, tmp_path):
        """Should return cached branch if present."""
        mod, _, _, _, _ = _import_filesystem_handler()
        handler = _make_handler(mod)
        handler._session_branches["key1"] = "CACHED"
        result = handler._get_codex_branch(str(tmp_path / "file.jsonl"), "key1")
        assert result == "CACHED"

    def test_reads_cwd_and_detects_branch(self, tmp_path):
        """Should read CWD and detect branch from it."""
        mod, _, _, _, _ = _import_filesystem_handler()
        handler = _make_handler(mod)
        meta_line = json.dumps(
            {
                "type": "session_meta",
                "payload": {"cwd": str(tmp_path / "Projects" / "AIPass" / "src" / "aipass" / "prax")},
            }
        )
        result = handler._get_codex_branch(str(_on_disk(tmp_path, meta_line + "\n", "file.jsonl")), "key2")
        assert result == "PRAX"
        assert handler._session_branches["key2"] == "PRAX"

    def test_no_cwd_returns_codex(self, tmp_path):
        """Should return CODEX when CWD cannot be read."""
        mod, _, _, _, _ = _import_filesystem_handler()
        handler = _make_handler(mod)
        result = handler._get_codex_branch(str(_on_disk(tmp_path, "\n", "file.jsonl")), "key3")
        assert result == "CODEX"

    def test_cwd_but_no_branch_returns_codex(self, tmp_path):
        """Should return CODEX when CWD has no branch pattern."""
        mod, _, _, _, _ = _import_filesystem_handler()
        handler = _make_handler(mod)
        meta_line = json.dumps({"type": "session_meta", "payload": {"cwd": str(tmp_path / "nowhere")}})
        result = handler._get_codex_branch(str(_on_disk(tmp_path, meta_line + "\n", "file.jsonl")), "key4")
        assert result == "CODEX"


# =============================================
# EXTRACT CODEX ACTION TESTS
# =============================================


class TestExtractCodexAction:
    """Tests for _extract_codex_action static method."""

    def test_agent_message_with_text(self):
        """Should format agent_message event."""
        mod, _, _, _, _ = _import_filesystem_handler()
        cls = mod.MonitoringFileHandler
        entry = {
            "type": "event_msg",
            "payload": {"type": "agent_message", "text": "Hello"},
        }
        result = cls._extract_codex_action(entry)
        assert "Hello" in result

    def test_agent_message_no_text(self):
        """Should return default for agent_message without text."""
        mod, _, _, _, _ = _import_filesystem_handler()
        cls = mod.MonitoringFileHandler
        entry = {
            "type": "event_msg",
            "payload": {"type": "agent_message"},
        }
        result = cls._extract_codex_action(entry)
        assert "Agent response" in result

    def test_user_message(self):
        """Should return user message for user_message event."""
        mod, _, _, _, _ = _import_filesystem_handler()
        cls = mod.MonitoringFileHandler
        entry = {
            "type": "event_msg",
            "payload": {"type": "user_message"},
        }
        result = cls._extract_codex_action(entry)
        assert "User message" in result

    def test_token_count(self):
        """Should return Thinking for token_count event."""
        mod, _, _, _, _ = _import_filesystem_handler()
        cls = mod.MonitoringFileHandler
        entry = {
            "type": "event_msg",
            "payload": {"type": "token_count"},
        }
        result = cls._extract_codex_action(entry)
        assert "Thinking" in result

    def test_task_started(self):
        """Should return Task started for task_started event."""
        mod, _, _, _, _ = _import_filesystem_handler()
        cls = mod.MonitoringFileHandler
        entry = {
            "type": "event_msg",
            "payload": {"type": "task_started"},
        }
        result = cls._extract_codex_action(entry)
        assert "Task started" in result

    def test_task_complete(self):
        """Should return Task complete for task_complete event."""
        mod, _, _, _, _ = _import_filesystem_handler()
        cls = mod.MonitoringFileHandler
        entry = {
            "type": "event_msg",
            "payload": {"type": "task_complete"},
        }
        result = cls._extract_codex_action(entry)
        assert "Task complete" in result

    def test_unknown_event_type(self):
        """Should return None for unknown event_msg types."""
        mod, _, _, _, _ = _import_filesystem_handler()
        cls = mod.MonitoringFileHandler
        entry = {
            "type": "event_msg",
            "payload": {"type": "something_else"},
        }
        result = cls._extract_codex_action(entry)
        assert result is None

    def test_response_item(self):
        """Should delegate to _parse_codex_response_item."""
        mod, _, _, _, _ = _import_filesystem_handler()
        cls = mod.MonitoringFileHandler
        entry = {
            "type": "response_item",
            "payload": {"item": {"type": "function_call", "name": "exec"}},
        }
        result = cls._extract_codex_action(entry)
        assert "exec" in result

    def test_session_meta_returns_none(self):
        """Session_meta entries should return None."""
        mod, _, _, _, _ = _import_filesystem_handler()
        cls = mod.MonitoringFileHandler
        result = cls._extract_codex_action({"type": "session_meta", "payload": {}})
        assert result is None

    def test_turn_context_returns_none(self):
        """Turn_context entries should return None."""
        mod, _, _, _, _ = _import_filesystem_handler()
        cls = mod.MonitoringFileHandler
        result = cls._extract_codex_action({"type": "turn_context", "payload": {}})
        assert result is None

    def test_unknown_top_level_type(self):
        """Unknown top-level entry types should return None."""
        mod, _, _, _, _ = _import_filesystem_handler()
        cls = mod.MonitoringFileHandler
        result = cls._extract_codex_action({"type": "random_type", "payload": {}})
        assert result is None

    def test_agent_message_with_message_fallback(self):
        """Should use message field when text is absent."""
        mod, _, _, _, _ = _import_filesystem_handler()
        cls = mod.MonitoringFileHandler
        entry = {
            "type": "event_msg",
            "payload": {"type": "agent_message", "message": "fallback"},
        }
        result = cls._extract_codex_action(entry)
        assert "fallback" in result


# =============================================
# PARSE CODEX RESPONSE ITEM TESTS
# =============================================


class TestParseCodexResponseItem:
    """Tests for _parse_codex_response_item static method."""

    def test_function_call(self):
        """Should format function_call item."""
        mod, _, _, _, _ = _import_filesystem_handler()
        cls = mod.MonitoringFileHandler
        result = cls._parse_codex_response_item({"item": {"type": "function_call", "name": "shell"}})
        assert "shell" in result

    def test_function_call_output_returns_none(self):
        """Function_call_output should return None."""
        mod, _, _, _, _ = _import_filesystem_handler()
        cls = mod.MonitoringFileHandler
        result = cls._parse_codex_response_item({"item": {"type": "function_call_output"}})
        assert result is None

    def test_message_with_text_content(self):
        """Message with text content should extract text."""
        mod, _, _, _, _ = _import_filesystem_handler()
        cls = mod.MonitoringFileHandler
        payload = {
            "item": {
                "type": "message",
                "content": [{"text": "hello there"}],
            }
        }
        result = cls._parse_codex_response_item(payload)
        assert "hello there" in result

    def test_message_without_list_content(self):
        """Message with non-list content should return default."""
        mod, _, _, _, _ = _import_filesystem_handler()
        cls = mod.MonitoringFileHandler
        payload = {"item": {"type": "message", "content": "just a string"}}
        result = cls._parse_codex_response_item(payload)
        assert "Agent response" in result

    def test_message_empty_text_parts(self):
        """Message with empty text parts should return default."""
        mod, _, _, _, _ = _import_filesystem_handler()
        cls = mod.MonitoringFileHandler
        payload = {"item": {"type": "message", "content": [{"text": ""}]}}
        result = cls._parse_codex_response_item(payload)
        assert "Agent response" in result

    def test_unknown_item_type(self):
        """Unknown item types should return None."""
        mod, _, _, _, _ = _import_filesystem_handler()
        cls = mod.MonitoringFileHandler
        result = cls._parse_codex_response_item({"item": {"type": "other"}})
        assert result is None

    def test_payload_without_item_key(self):
        """Payload without item key should use payload as item."""
        mod, _, _, _, _ = _import_filesystem_handler()
        cls = mod.MonitoringFileHandler
        result = cls._parse_codex_response_item({"type": "function_call", "name": "tool"})
        assert "tool" in result


# =============================================
# EXTRACT CODEX MODEL TESTS
# =============================================


class TestExtractCodexModel:
    """Tests for _extract_codex_model."""

    def test_extracts_model_from_turn_context(self):
        """Should extract model from turn_context entry."""
        mod, _, _, _, _ = _import_filesystem_handler()
        handler = _make_handler(mod)
        entry = {
            "type": "turn_context",
            "payload": {"model": "gpt-4o"},
        }
        handler._extract_codex_model(entry, "pk")
        assert handler._session_models["pk"] == "gpt-4o"

    def test_ignores_non_turn_context(self):
        """Should not extract model from non-turn_context entries."""
        mod, _, _, _, _ = _import_filesystem_handler()
        handler = _make_handler(mod)
        entry = {
            "type": "event_msg",
            "payload": {"model": "gpt-4o"},
        }
        handler._extract_codex_model(entry, "pk")
        assert "pk" not in handler._session_models

    def test_ignores_empty_model(self):
        """Should not store empty model string."""
        mod, _, _, _, _ = _import_filesystem_handler()
        handler = _make_handler(mod)
        entry = {"type": "turn_context", "payload": {"model": ""}}
        handler._extract_codex_model(entry, "pk")
        assert "pk" not in handler._session_models


# =============================================
# PARSE CODEX ACTIVITY TESTS
# =============================================


class TestParseCodexActivity:
    """Tests for _parse_codex_activity."""

    def test_parses_lines_and_emits(self, tmp_path):
        """Should parse new JSONL lines and emit agent event."""
        mod, _, _, _, queue = _import_filesystem_handler()
        handler = _make_handler(mod, queue=queue)
        line = json.dumps(
            {
                "type": "event_msg",
                "payload": {"type": "user_message"},
            }
        )
        result = handler._parse_codex_activity(_on_disk(tmp_path, line + "\n", "codex.jsonl"), "CODEX")
        assert result is True
        queue.enqueue.assert_called()

    def test_no_new_lines(self, tmp_path):
        """Should return True when no new lines."""
        mod, _, _, _, queue = _import_filesystem_handler()
        handler = _make_handler(mod, queue=queue)
        path = _on_disk(tmp_path, '{"type": "old"}\n', "codex.jsonl")
        handler._jsonl_positions[str(path)] = path.stat().st_size
        result = handler._parse_codex_activity(path, "CODEX")
        assert result is True
        queue.enqueue.assert_not_called()

    def test_malformed_json_skipped(self, tmp_path):
        """Should skip malformed JSON lines."""
        mod, _, _, _, queue = _import_filesystem_handler()
        handler = _make_handler(mod, queue=queue)
        result = handler._parse_codex_activity(_on_disk(tmp_path, "not json\n", "codex.jsonl"), "CODEX")
        assert result is True

    def test_exception_returns_false(self):
        """Should return False on unexpected exception."""
        mod, _, _, _, queue = _import_filesystem_handler()
        handler = _make_handler(mod, queue=queue)
        mock_path = MagicMock()
        mock_path.stat.side_effect = Exception("boom")
        mock_path.__str__ = MagicMock(return_value="/fake/codex.jsonl")
        mock_path.name = "codex.jsonl"
        result = handler._parse_codex_activity(mock_path, "CODEX")
        assert result is False

    def test_extracts_model_from_turn_context(self, tmp_path):
        """Should extract model from turn_context entries."""
        mod, _, _, _, queue = _import_filesystem_handler()
        handler = _make_handler(mod, queue=queue)
        lines = "\n".join(
            [
                json.dumps(
                    {
                        "type": "event_msg",
                        "payload": {"type": "user_message"},
                    }
                ),
                json.dumps(
                    {
                        "type": "turn_context",
                        "payload": {"model": "o4-mini"},
                    }
                ),
            ]
        )
        path = _on_disk(tmp_path, lines + "\n", "codex.jsonl")
        handler._parse_codex_activity(path, "CODEX")
        assert handler._session_models.get(str(path)) == "o4-mini"

    def test_no_actionable_lines(self, tmp_path):
        """Should return True when all lines produce no action."""
        mod, _, _, _, queue = _import_filesystem_handler()
        handler = _make_handler(mod, queue=queue)
        line = json.dumps({"type": "session_meta", "payload": {}})
        result = handler._parse_codex_activity(_on_disk(tmp_path, line + "\n", "codex.jsonl"), "CODEX")
        assert result is True
        queue.enqueue.assert_not_called()
