# =================== AIPass ====================
# Name: test_filesystem_handler_agent_activity.py
# Description: Unit tests for filesystem_handler's JSONL reading and agent activity
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-23
# =============================================

"""Tests for apps/handlers/monitoring/filesystem_handler.py, its JSONL reading and agent activity."""

# Split from test_filesystem_handler.py (2026-10-08).
#
# Covers: _read_new_jsonl_lines, _safe_parse_json, _emit_agent_event,
# _parse_agent_activity (Claude Code), _check_command_indicator.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(through_the_command) — _shorten_model, covered by tests/test_filesystem_handler_tool_action.py

import json
from unittest.mock import MagicMock

import pytest

from aipass.prax.tests.support_test_filesystem_handler import _import_filesystem_handler, _make_handler, _on_disk

pytestmark = pytest.mark.usefixtures("_filesystem_handler_doubled")


# =============================================
# READ NEW JSONL LINES TESTS
# =============================================


class TestReadNewJsonlLines:
    """Tests for _read_new_jsonl_lines."""

    def test_reads_new_data(self, tmp_path):
        """Should read new lines since last position, and move the position to the end."""
        mod, _, _, _, _ = _import_filesystem_handler()
        handler = _make_handler(mod)
        data = '{"type": "test"}\n'
        path = _on_disk(tmp_path, data)
        result = handler._read_new_jsonl_lines(path, "pk")
        assert result == ['{"type": "test"}']
        assert handler._jsonl_positions["pk"] == path.stat().st_size

    def test_reads_only_what_was_appended(self, tmp_path):
        """A second read starts where the first stopped: old lines are not shown twice."""
        mod, _, _, _, _ = _import_filesystem_handler()
        handler = _make_handler(mod)
        path = _on_disk(tmp_path, '{"n": 1}\n')
        handler._read_new_jsonl_lines(path, "pk")
        path.write_bytes(path.read_bytes() + b'{"n": 2}\n')
        assert handler._read_new_jsonl_lines(path, "pk") == ['{"n": 2}']

    def test_no_new_data(self, tmp_path):
        """Should return None when no new data."""
        mod, _, _, _, _ = _import_filesystem_handler()
        handler = _make_handler(mod)
        path = _on_disk(tmp_path, '{"type": "old"}\n')
        handler._jsonl_positions["pk"] = path.stat().st_size
        result = handler._read_new_jsonl_lines(path, "pk")
        assert result is None

    def test_file_truncated_resets_position(self, tmp_path):
        """Should reset position when file shrinks (truncation)."""
        mod, _, _, _, _ = _import_filesystem_handler()
        handler = _make_handler(mod)
        handler._jsonl_positions["pk"] = 200
        result = handler._read_new_jsonl_lines(_on_disk(tmp_path, '{"type": "new"}\n'), "pk")
        assert result == ['{"type": "new"}']

    def test_empty_new_data(self, tmp_path):
        """Should return None when new data is all whitespace."""
        mod, _, _, _, _ = _import_filesystem_handler()
        handler = _make_handler(mod)
        result = handler._read_new_jsonl_lines(_on_disk(tmp_path, "   \n  \n"), "pk")
        assert result is None


# =============================================
# SAFE PARSE JSON TESTS
# =============================================


class TestSafeParseJson:
    """Tests for _safe_parse_json."""

    def test_valid_json(self):
        """Should parse valid JSON."""
        mod, _, _, _, _ = _import_filesystem_handler()
        handler = _make_handler(mod)
        result = handler._safe_parse_json('{"key": "value"}', "test")
        assert result == {"key": "value"}

    def test_invalid_json(self):
        """Should return None for invalid JSON."""
        mod, _, _, _, _ = _import_filesystem_handler()
        handler = _make_handler(mod)
        result = handler._safe_parse_json("not json", "test")
        assert result is None


# =============================================
# EMIT AGENT EVENT TESTS
# =============================================


class TestEmitAgentEvent:
    """Tests for _emit_agent_event."""

    def test_emits_event(self):
        """Should create and enqueue an agent event."""
        mod, _, _, _, queue = _import_filesystem_handler()
        handler = _make_handler(mod, queue=queue)
        result = handler._emit_agent_event("pk", "PRAX", "Testing")
        assert result is True
        queue.enqueue.assert_called_once()
        assert handler._last_agent_action["pk"] == "Testing"

    def test_deduplicates(self):
        """Should not emit duplicate actions."""
        mod, _, _, _, queue = _import_filesystem_handler()
        handler = _make_handler(mod, queue=queue)
        handler._last_agent_action["pk"] = "Same action"
        result = handler._emit_agent_event("pk", "PRAX", "Same action")
        assert result is True
        queue.enqueue.assert_not_called()

    def test_no_queue(self):
        """Should work without a queue (still records action)."""
        mod, _, _, _, _ = _import_filesystem_handler()
        handler = _make_handler(mod, queue=None)
        result = handler._emit_agent_event("pk", "PRAX", "Action")
        assert result is True
        assert handler._last_agent_action["pk"] == "Action"

    def test_tags_branch_with_model(self):
        """Should append model tag to branch."""
        mod, mock_eq, _, _, queue = _import_filesystem_handler()
        handler = _make_handler(mod, queue=queue)
        handler._session_models["pk"] = "opus"
        handler._emit_agent_event("pk", "PRAX", "Testing")
        call_kwargs = mock_eq.MonitoringEvent.call_args
        assert "PRAX/opus" in str(call_kwargs)


# =============================================
# PARSE AGENT ACTIVITY (CLAUDE CODE) TESTS
# =============================================


class TestParseAgentActivity:
    """Tests for _parse_agent_activity (Claude Code JSONL)."""

    def test_parses_and_emits_event(self, tmp_path):
        """Should parse JSONL and emit agent event."""
        mod, _, _, _, queue = _import_filesystem_handler()
        handler = _make_handler(mod, queue=queue)
        entry = {
            "type": "assistant",
            "message": {"content": [{"type": "thinking"}]},
        }
        result = handler._parse_agent_activity(_on_disk(tmp_path, json.dumps(entry) + "\n", "claude.jsonl"), "PRAX")
        assert result is True
        queue.enqueue.assert_called()

    def test_no_new_data(self, tmp_path):
        """Should return True when no new data."""
        mod, _, _, _, queue = _import_filesystem_handler()
        handler = _make_handler(mod, queue=queue)
        path = _on_disk(tmp_path, '{"type": "old"}\n', "claude.jsonl")
        handler._jsonl_positions[str(path)] = path.stat().st_size
        result = handler._parse_agent_activity(path, "PRAX")
        assert result is True
        queue.enqueue.assert_not_called()

    def test_file_truncated(self, tmp_path):
        """Should reset position when file shrinks, and read the file from its start."""
        mod, _, _, _, queue = _import_filesystem_handler()
        handler = _make_handler(mod, queue=queue)
        entry = {"type": "user", "message": {"content": "hello"}}
        path = _on_disk(tmp_path, json.dumps(entry) + "\n", "claude.jsonl")
        handler._jsonl_positions[str(path)] = 1000
        result = handler._parse_agent_activity(path, "PRAX")
        assert result is True
        assert handler._jsonl_positions[str(path)] == path.stat().st_size

    def test_a_second_poll_emits_only_what_was_appended(self, tmp_path):
        """The second read starts where the first stopped: old actions are not shown again.

        Green from its first run; its proof is the mutant that seeks to 0.
        """
        mod, mock_eq, _, _, queue = _import_filesystem_handler()
        handler = _make_handler(mod, queue=queue)

        def tool(name: str) -> str:
            entry = {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": name, "input": {}}]}}
            return json.dumps(entry) + "\n"

        path = _on_disk(tmp_path, tool("FirstTool") + tool("SecondTool"), "claude.jsonl")
        handler._parse_agent_activity(path, "PRAX")
        path.write_bytes(path.read_bytes() + tool("ThirdTool").encode("utf-8"))
        handler._parse_agent_activity(path, "PRAX")

        messages = [kwargs["message"] for _args, kwargs in mock_eq.MonitoringEvent.call_args_list]
        assert len(messages) == 3
        assert "ThirdTool" in messages[-1]

    def test_malformed_line_skipped(self, tmp_path):
        """Should skip malformed JSON lines."""
        mod, _, _, _, queue = _import_filesystem_handler()
        handler = _make_handler(mod, queue=queue)
        good_entry = json.dumps({"type": "user", "message": {"content": "hi"}})
        data = "not json\n" + good_entry + "\n"
        result = handler._parse_agent_activity(_on_disk(tmp_path, data, "claude.jsonl"), "PRAX")
        assert result is True
        queue.enqueue.assert_called()

    def test_deduplicates(self, tmp_path):
        """Should not emit duplicate actions."""
        mod, _, _, _, queue = _import_filesystem_handler()
        handler = _make_handler(mod, queue=queue)
        entry = {"type": "user", "message": {"content": "hello"}}
        path = _on_disk(tmp_path, json.dumps(entry) + "\n", "claude.jsonl")
        handler._last_agent_action[str(path)] = "User message"
        result = handler._parse_agent_activity(path, "PRAX")
        assert result is True

    def test_extracts_model(self, tmp_path):
        """Should extract model from entries."""
        mod, _, _, _, queue = _import_filesystem_handler()
        handler = _make_handler(mod, queue=queue)
        entry = {
            "type": "assistant",
            "message": {
                "model": "claude-opus-4-20250514",
                "content": [{"type": "thinking"}],
            },
        }
        path = _on_disk(tmp_path, json.dumps(entry) + "\n", "claude.jsonl")
        handler._parse_agent_activity(path, "PRAX")
        assert handler._session_models.get(str(path)) == "opus"

    def test_exception_returns_false(self):
        """Should return False on unexpected exception."""
        mod, _, _, _, queue = _import_filesystem_handler()
        handler = _make_handler(mod, queue=queue)
        mock_path = MagicMock()
        mock_path.stat.side_effect = Exception("boom")
        mock_path.__str__ = MagicMock(return_value="/fake/claude.jsonl")
        mock_path.name = "claude.jsonl"
        result = handler._parse_agent_activity(mock_path, "PRAX")
        assert result is False

    def test_empty_lines_after_split(self, tmp_path):
        """Should return True when all lines are empty after strip."""
        mod, _, _, _, queue = _import_filesystem_handler()
        handler = _make_handler(mod, queue=queue)
        result = handler._parse_agent_activity(_on_disk(tmp_path, "  \n  \n", "claude.jsonl"), "PRAX")
        assert result is True

    def test_no_actionable_entries(self, tmp_path):
        """Should return True when entries produce no actions."""
        mod, _, _, _, queue = _import_filesystem_handler()
        handler = _make_handler(mod, queue=queue)
        entry = {"type": "progress"}
        result = handler._parse_agent_activity(_on_disk(tmp_path, json.dumps(entry) + "\n", "claude.jsonl"), "PRAX")
        assert result is True
        queue.enqueue.assert_not_called()

    def test_no_queue_still_returns_true(self, tmp_path):
        """Should return True even with no queue."""
        mod, _, _, _, _ = _import_filesystem_handler()
        handler = _make_handler(mod, queue=None)
        entry = {"type": "user", "message": {"content": "hi"}}
        result = handler._parse_agent_activity(_on_disk(tmp_path, json.dumps(entry) + "\n", "claude.jsonl"), "PRAX")
        assert result is True

    def test_batch_cap_limits_emitted_events(self, tmp_path):
        """Should only emit last N events when batch exceeds cap."""
        mod, _, _, _, queue = _import_filesystem_handler()
        handler = _make_handler(mod, queue=queue)
        entries = []
        tools = ["Read", "Edit", "Write", "Grep", "Glob", "Bash"]
        for i, tool in enumerate(tools):
            entries.append(
                {
                    "type": "assistant",
                    "message": {"content": [{"type": "tool_use", "name": tool, "input": {"file_path": f"f{i}.py"}}]},
                }
            )
        data = "\n".join(json.dumps(e) for e in entries) + "\n"
        result = handler._parse_agent_activity(_on_disk(tmp_path, data, "claude.jsonl"), "PRAX")
        assert result is True
        cap = mod.MonitoringFileHandler._MAX_AGENT_EVENTS_PER_BATCH
        assert queue.enqueue.call_count == cap

    def test_batch_cap_emits_tail_not_head(self, tmp_path):
        """Should emit the last actions in a large batch, not the first."""
        mod, mock_eq, _, _, queue = _import_filesystem_handler()
        handler = _make_handler(mod, queue=queue)
        entries = []
        for i in range(6):
            entries.append(
                {
                    "type": "assistant",
                    "message": {"content": [{"type": "tool_use", "name": f"Tool{i}", "input": {}}]},
                }
            )
        data = "\n".join(json.dumps(e) for e in entries) + "\n"
        handler._parse_agent_activity(_on_disk(tmp_path, data, "claude.jsonl"), "PRAX")
        cap = mod.MonitoringFileHandler._MAX_AGENT_EVENTS_PER_BATCH
        assert queue.enqueue.call_count == cap
        last_call_kwargs = mock_eq.MonitoringEvent.call_args_list[-1][1]
        assert "Tool5" in last_call_kwargs["message"]
        first_call_kwargs = mock_eq.MonitoringEvent.call_args_list[-cap][1]
        assert "Tool3" in first_call_kwargs["message"]


# =============================================
# CHECK COMMAND INDICATOR TESTS
# =============================================


class TestCheckCommandIndicator:
    """Tests for _check_command_indicator."""

    def test_emits_command_event(self):
        """Should emit command event for matching file."""
        mod, _, _, _, queue = _import_filesystem_handler()
        cif = {"status.json": "status command"}
        handler = _make_handler(mod, queue=queue, command_indicator_files=cif)
        file_path = MagicMock()
        file_path.name = "status.json"
        handler._check_command_indicator("modified", file_path, "PRAX")
        kwargs = mod.MonitoringEvent.call_args.kwargs
        assert (kwargs["event_type"], kwargs["branch"], kwargs["message"]) == ("command", "PRAX", "status command")
        queue.enqueue.assert_called_once_with(mod.MonitoringEvent.return_value)

    def test_skips_non_modified(self):
        """Should skip non-modified events."""
        mod, _, _, _, queue = _import_filesystem_handler()
        cif = {"status.json": "status command"}
        handler = _make_handler(mod, queue=queue, command_indicator_files=cif)
        file_path = MagicMock()
        file_path.name = "status.json"
        handler._check_command_indicator("created", file_path, "PRAX")
        queue.enqueue.assert_not_called()

    def test_skips_non_indicator_file(self):
        """Should skip files not in indicator list."""
        mod, _, _, _, queue = _import_filesystem_handler()
        cif = {"status.json": "status command"}
        handler = _make_handler(mod, queue=queue, command_indicator_files=cif)
        file_path = MagicMock()
        file_path.name = "other.json"
        handler._check_command_indicator("modified", file_path, "PRAX")
        queue.enqueue.assert_not_called()

    def test_deduplicates_command(self):
        """Should not emit duplicate commands."""
        mod, _, _, _, queue = _import_filesystem_handler()
        cif = {"status.json": "status command"}
        handler = _make_handler(mod, queue=queue, command_indicator_files=cif)
        file_path = MagicMock()
        file_path.name = "status.json"
        handler._check_command_indicator("modified", file_path, "PRAX")
        queue.enqueue.reset_mock()
        handler._check_command_indicator("modified", file_path, "PRAX")
        queue.enqueue.assert_not_called()

    def test_no_queue(self):
        """Should not crash without a queue."""
        mod, _, _, _, _ = _import_filesystem_handler()
        cif = {"status.json": "status command"}
        handler = _make_handler(mod, queue=None, command_indicator_files=cif)
        file_path = MagicMock()
        file_path.name = "status.json"
        handler._check_command_indicator("modified", file_path, "PRAX")


class TestFirstSeenTranscript:
    """A transcript first seen on 'modified' starts at its end; one seen on 'created' from its start."""

    @staticmethod
    def _transcript(tmp_path):
        entry = {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "OldTool", "input": {}}]}}
        path = tmp_path / ".claude" / "projects" / "abc" / "session.jsonl"
        path.parent.mkdir(parents=True)
        path.write_bytes((json.dumps(entry) + "\n").encode("utf-8"))
        return path

    def test_modified_first_shows_no_history(self, tmp_path):
        mod, mock_eq, _, _, queue = _import_filesystem_handler()
        handler = _make_handler(mod, queue=queue)
        path = self._transcript(tmp_path)
        handler._handle_event("modified", str(path))
        assert handler._jsonl_positions[str(path)] == path.stat().st_size
        assert not any("OldTool" in str(c) for c in mock_eq.MonitoringEvent.call_args_list)

    def test_created_reads_from_the_start(self, tmp_path):
        mod, mock_eq, _, _, queue = _import_filesystem_handler()
        handler = _make_handler(mod, queue=queue)
        path = self._transcript(tmp_path)
        handler._handle_event("created", str(path))
        assert any("OldTool" in str(c) for c in mock_eq.MonitoringEvent.call_args_list)

    def test_partial_last_line_waits_for_its_newline(self, tmp_path):
        mod, _, _, _, _ = _import_filesystem_handler()
        handler = _make_handler(mod)
        path = _on_disk(tmp_path, '{"n": 1}\n{"n": ')
        assert handler._read_new_jsonl_lines(path, "pk") == ['{"n": 1}']
        path.write_bytes(path.read_bytes() + b'2}\n')
        assert handler._read_new_jsonl_lines(path, "pk") == ['{"n": 2}']
