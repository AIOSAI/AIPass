# =================== AIPass ====================
# Name: test_filesystem_handler_tool_action.py
# Description: Unit tests for filesystem_handler's tool action and model extraction
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-08
# =============================================

"""Tests for apps/handlers/monitoring/filesystem_handler.py, its tool action and model extraction."""

# Split from test_filesystem_handler.py (2026-10-08).
#
# Covers: _format_tool_action, _extract_model_from_entry,
# _extract_action_from_entry, _shorten_model, _tag_branch_with_model.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(through_the_command) — _emit_agent_event, covered by test_filesystem_handler_agent_activity.py

import pytest

from aipass.prax.tests.support_test_filesystem_handler import _import_filesystem_handler, _make_handler

pytestmark = pytest.mark.usefixtures("_filesystem_handler_doubled")


# =============================================
# FORMAT TOOL ACTION TESTS
# =============================================


class TestFormatToolAction:
    """Tests for _format_tool_action static method."""

    def test_read_tool(self, tmp_path):
        """Should format Read tool with short filename."""
        mod, _, _, _, _ = _import_filesystem_handler()
        cls = mod.MonitoringFileHandler
        result = cls._format_tool_action({"name": "Read", "input": {"file_path": str(tmp_path / "src" / "file.py")}})
        assert "Read" in result
        assert "file.py" in result

    def test_edit_tool(self):
        """Should format Edit tool with short filename."""
        mod, _, _, _, _ = _import_filesystem_handler()
        cls = mod.MonitoringFileHandler
        result = cls._format_tool_action({"name": "Edit", "input": {"file_path": "/a/b/c.py"}})
        assert "Edit" in result
        assert "c.py" in result

    def test_write_tool(self):
        """Should format Write tool with short filename."""
        mod, _, _, _, _ = _import_filesystem_handler()
        cls = mod.MonitoringFileHandler
        result = cls._format_tool_action({"name": "Write", "input": {"file_path": "/x/y.txt"}})
        assert "Write" in result
        assert "y.txt" in result

    def test_bash_tool_with_description(self):
        """Should format Bash tool with description."""
        mod, _, _, _, _ = _import_filesystem_handler()
        cls = mod.MonitoringFileHandler
        result = cls._format_tool_action({"name": "Bash", "input": {"description": "run tests"}})
        assert "Bash" in result
        assert "run tests" in result

    def test_bash_tool_with_command_fallback(self):
        """Should format Bash tool with command when no description."""
        mod, _, _, _, _ = _import_filesystem_handler()
        cls = mod.MonitoringFileHandler
        result = cls._format_tool_action({"name": "Bash", "input": {"command": "ls -la"}})
        assert "Bash" in result
        assert "ls -la" in result

    def test_grep_tool(self):
        """Should format Grep tool with pattern."""
        mod, _, _, _, _ = _import_filesystem_handler()
        cls = mod.MonitoringFileHandler
        result = cls._format_tool_action({"name": "Grep", "input": {"pattern": "TODO"}})
        assert "Grep" in result
        assert "TODO" in result

    def test_glob_tool(self):
        """Should format Glob tool with pattern."""
        mod, _, _, _, _ = _import_filesystem_handler()
        cls = mod.MonitoringFileHandler
        result = cls._format_tool_action({"name": "Glob", "input": {"pattern": "**/*.py"}})
        assert "Glob" in result
        assert "**/*.py" in result

    def test_task_tool(self):
        """Should format Task tool with description."""
        mod, _, _, _, _ = _import_filesystem_handler()
        cls = mod.MonitoringFileHandler
        result = cls._format_tool_action({"name": "Task", "input": {"description": "do stuff"}})
        assert "Agent" in result
        assert "do stuff" in result

    def test_unknown_tool(self):
        """Should return tool name for unknown tools."""
        mod, _, _, _, _ = _import_filesystem_handler()
        cls = mod.MonitoringFileHandler
        result = cls._format_tool_action({"name": "CustomTool", "input": {}})
        assert "CustomTool" in result

    def test_read_no_slash_in_path(self):
        """Should handle file_path without slashes."""
        mod, _, _, _, _ = _import_filesystem_handler()
        cls = mod.MonitoringFileHandler
        result = cls._format_tool_action({"name": "Read", "input": {"file_path": "file.py"}})
        assert "file.py" in result


# =============================================
# EXTRACT MODEL FROM ENTRY TESTS
# =============================================


class TestExtractModelFromEntry:
    """Tests for _extract_model_from_entry static method."""

    def test_extracts_model(self):
        """Should extract model from message dict."""
        mod, _, _, _, _ = _import_filesystem_handler()
        cls = mod.MonitoringFileHandler
        entry = {"message": {"model": "claude-sonnet-4-20250514"}}
        result = cls._extract_model_from_entry(entry)
        assert result == "claude-sonnet-4-20250514"

    def test_no_message_key(self):
        """Should return None when no message key."""
        mod, _, _, _, _ = _import_filesystem_handler()
        cls = mod.MonitoringFileHandler
        result = cls._extract_model_from_entry({})
        assert result is None

    def test_message_not_dict(self):
        """Should return None when message is not a dict."""
        mod, _, _, _, _ = _import_filesystem_handler()
        cls = mod.MonitoringFileHandler
        result = cls._extract_model_from_entry({"message": "string"})
        assert result is None


# =============================================
# EXTRACT ACTION FROM ENTRY TESTS
# =============================================


class TestExtractActionFromEntry:
    """Tests for _extract_action_from_entry static method."""

    def test_progress_type_returns_none(self):
        """Progress entries should return None."""
        mod, _, _, _, _ = _import_filesystem_handler()
        cls = mod.MonitoringFileHandler
        assert cls._extract_action_from_entry({"type": "progress"}) is None

    def test_system_type_returns_none(self):
        """System entries should return None."""
        mod, _, _, _, _ = _import_filesystem_handler()
        cls = mod.MonitoringFileHandler
        assert cls._extract_action_from_entry({"type": "system"}) is None

    def test_file_history_snapshot_returns_none(self):
        """File-history-snapshot entries should return None."""
        mod, _, _, _, _ = _import_filesystem_handler()
        cls = mod.MonitoringFileHandler
        assert cls._extract_action_from_entry({"type": "file-history-snapshot"}) is None

    def test_queue_operation_returns_none(self):
        """Queue-operation entries should return None."""
        mod, _, _, _, _ = _import_filesystem_handler()
        cls = mod.MonitoringFileHandler
        assert cls._extract_action_from_entry({"type": "queue-operation"}) is None

    def test_assistant_thinking(self):
        """Assistant entry with thinking item should return thinking."""
        mod, _, _, _, _ = _import_filesystem_handler()
        cls = mod.MonitoringFileHandler
        entry = {
            "type": "assistant",
            "message": {"content": [{"type": "thinking", "text": "hmm"}]},
        }
        result = cls._extract_action_from_entry(entry)
        assert "Thinking" in result

    def test_assistant_tool_use(self):
        """Assistant entry with tool_use item should return tool action."""
        mod, _, _, _, _ = _import_filesystem_handler()
        cls = mod.MonitoringFileHandler
        entry = {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "name": "Read",
                        "input": {"file_path": "/a/b.py"},
                    }
                ]
            },
        }
        result = cls._extract_action_from_entry(entry)
        assert "Read" in result

    def test_assistant_text(self):
        """Assistant entry with text item should return text snippet."""
        mod, _, _, _, _ = _import_filesystem_handler()
        cls = mod.MonitoringFileHandler
        entry = {
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": "Hello world"}]},
        }
        result = cls._extract_action_from_entry(entry)
        assert "Hello world" in result

    def test_assistant_text_empty(self):
        """Assistant entry with empty text should return None."""
        mod, _, _, _, _ = _import_filesystem_handler()
        cls = mod.MonitoringFileHandler
        entry = {
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": ""}]},
        }
        result = cls._extract_action_from_entry(entry)
        assert result is None

    def test_assistant_content_item_not_dict(self):
        """Assistant entry with non-dict content items should skip them."""
        mod, _, _, _, _ = _import_filesystem_handler()
        cls = mod.MonitoringFileHandler
        entry = {
            "type": "assistant",
            "message": {"content": ["just a string", {"type": "thinking"}]},
        }
        result = cls._extract_action_from_entry(entry)
        assert "Thinking" in result

    def test_user_message(self):
        """User entry should return user message."""
        mod, _, _, _, _ = _import_filesystem_handler()
        cls = mod.MonitoringFileHandler
        entry = {"type": "user", "message": {"content": "hello"}}
        result = cls._extract_action_from_entry(entry)
        assert "User message" in result

    def test_user_tool_result(self):
        """User entry with tool_result content should return None."""
        mod, _, _, _, _ = _import_filesystem_handler()
        cls = mod.MonitoringFileHandler
        entry = {
            "type": "user",
            "message": {"content": [{"type": "tool_result", "content": "ok"}]},
        }
        result = cls._extract_action_from_entry(entry)
        assert result is None

    def test_unknown_type_returns_none(self):
        """Unknown entry types should return None."""
        mod, _, _, _, _ = _import_filesystem_handler()
        cls = mod.MonitoringFileHandler
        result = cls._extract_action_from_entry({"type": "unknown_type"})
        assert result is None

    def test_message_not_dict_in_entry(self):
        """Should handle non-dict message gracefully."""
        mod, _, _, _, _ = _import_filesystem_handler()
        cls = mod.MonitoringFileHandler
        entry = {"type": "assistant", "message": "not a dict"}
        result = cls._extract_action_from_entry(entry)
        assert result is None


# =============================================
# SHORTEN MODEL TESTS
# =============================================


class TestShortenModel:
    """Tests for _shorten_model static method."""

    def test_empty_string(self):
        """Empty model should return empty string."""
        mod, _, _, _, _ = _import_filesystem_handler()
        assert mod.MonitoringFileHandler._shorten_model("") == ""

    def test_opus(self):
        """Should shorten opus models."""
        mod, _, _, _, _ = _import_filesystem_handler()
        result = mod.MonitoringFileHandler._shorten_model("claude-opus-4-20250514")
        assert result == "opus"

    def test_sonnet(self):
        """Should shorten sonnet models."""
        mod, _, _, _, _ = _import_filesystem_handler()
        result = mod.MonitoringFileHandler._shorten_model("claude-sonnet-4-20250514")
        assert result == "sonnet"

    def test_haiku(self):
        """Should shorten haiku models."""
        mod, _, _, _, _ = _import_filesystem_handler()
        result = mod.MonitoringFileHandler._shorten_model("claude-3-haiku-20241022")
        assert result == "haiku"

    def test_gpt_model(self):
        """Should return gpt models as-is."""
        mod, _, _, _, _ = _import_filesystem_handler()
        assert mod.MonitoringFileHandler._shorten_model("gpt-4o") == "gpt-4o"

    def test_o_model(self):
        """Should return o-series models as-is."""
        mod, _, _, _, _ = _import_filesystem_handler()
        result = mod.MonitoringFileHandler._shorten_model("o4-mini")
        assert result == "o4-mini"

    def test_fallback_long_model(self):
        """Should truncate unknown models to 15 chars."""
        mod, _, _, _, _ = _import_filesystem_handler()
        result = mod.MonitoringFileHandler._shorten_model("some-very-long-model-name-here")
        assert len(result) == 15

    def test_o_without_digit(self):
        """Prefix o without digits should hit fallback."""
        mod, _, _, _, _ = _import_filesystem_handler()
        result = mod.MonitoringFileHandler._shorten_model("orange")
        assert result == "orange"


# =============================================
# TAG BRANCH WITH MODEL TESTS
# =============================================


class TestTagBranchWithModel:
    """Tests for _tag_branch_with_model."""

    def test_with_known_model(self):
        """Should append model tag to branch."""
        mod, _, _, _, _ = _import_filesystem_handler()
        handler = _make_handler(mod)
        handler._session_models["pk"] = "opus"
        result = handler._tag_branch_with_model("pk", "PRAX")
        assert result == "PRAX/opus"

    def test_without_model(self):
        """Should return plain branch when no model known."""
        mod, _, _, _, _ = _import_filesystem_handler()
        handler = _make_handler(mod)
        result = handler._tag_branch_with_model("pk", "PRAX")
        assert result == "PRAX"
