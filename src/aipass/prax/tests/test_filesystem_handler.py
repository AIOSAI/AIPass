# =================== AIPass ====================
# Name: test_filesystem_handler.py
# Description: Unit tests for filesystem_handler.py
# Version: 1.0.0
# Created: 2026-04-26
# Modified: 2026-04-26
# =============================================

"""Unit tests for MonitoringFileHandler.

Covers: __init__, watchdog event methods, agent activity parsing
(Claude Code, Codex), branch detection, model tag helpers,
internal event processing, and display name building.
"""

import importlib
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open as _mock_file_open

import pytest

_mopen = _mock_file_open

_INJECTED_MODULES = [
    "watchdog",
    "watchdog.events",
    "aipass.prax.apps.handlers.monitoring.event_queue",
    "aipass.prax.apps.handlers.monitoring.branch_detector",
    "aipass.prax.apps.handlers.monitoring.monitoring_filters",
    "aipass.prax.apps.handlers.monitoring.filesystem_handler",
]


@pytest.fixture(autouse=True)
def _cleanup_injected_modules():
    """Remove mocked monitoring modules from sys.modules after each test."""
    saved = {k: sys.modules[k] for k in _INJECTED_MODULES if k in sys.modules}
    yield
    for k in _INJECTED_MODULES:
        sys.modules.pop(k, None)
    for k, v in saved.items():
        sys.modules[k] = v


# =============================================
# MODULE IMPORT HELPER
# =============================================


def _import_filesystem_handler():
    """Import filesystem_handler with mocked watchdog and monitoring deps."""
    mod_name = "aipass.prax.apps.handlers.monitoring.filesystem_handler"
    sys.modules.pop(mod_name, None)

    # Mock watchdog.events
    mock_watchdog_events = MagicMock()

    class FakeFileSystemEventHandler:
        """Stub base class for watchdog handler."""

    mock_watchdog_events.FileSystemEventHandler = FakeFileSystemEventHandler
    sys.modules["watchdog"] = MagicMock()
    sys.modules["watchdog.events"] = mock_watchdog_events

    # Mock monitoring sub-modules
    mock_event_queue = MagicMock()
    mock_event_cls = MagicMock()
    mock_event_queue.MonitoringEvent = mock_event_cls
    mock_queue_instance = MagicMock()
    mock_queue_instance.enqueue = MagicMock(return_value=True)
    mock_event_queue.MonitoringQueue = MagicMock

    mock_branch_detector = MagicMock()
    mock_branch_detector.detect_branch_from_path = MagicMock(return_value="PRAX")

    mock_filters = MagicMock()
    mock_filters.should_monitor = MagicMock(return_value=True)
    mock_filters.get_priority = MagicMock(return_value="info")

    sys.modules["aipass.prax.apps.handlers.monitoring.event_queue"] = mock_event_queue
    sys.modules["aipass.prax.apps.handlers.monitoring.branch_detector"] = mock_branch_detector
    sys.modules["aipass.prax.apps.handlers.monitoring.monitoring_filters"] = mock_filters

    mod = importlib.import_module(mod_name)
    return mod, mock_event_queue, mock_branch_detector, mock_filters, mock_queue_instance


def _make_handler(mod, queue=None, command_indicator_files=None):
    """Create a MonitoringFileHandler with a given queue."""
    return mod.MonitoringFileHandler(
        event_queue=queue,
        command_indicator_files=command_indicator_files,
    )


# =============================================
# INIT TESTS
# =============================================


class TestInit:
    """Tests for MonitoringFileHandler.__init__."""

    def test_init_sets_queue(self):
        """Constructor should store event_queue reference."""
        mod, _, _, _, queue = _import_filesystem_handler()
        handler = _make_handler(mod, queue=queue)
        assert handler._event_queue is queue

    def test_init_no_queue(self):
        """Constructor with no queue should set None."""
        mod, _, _, _, _ = _import_filesystem_handler()
        handler = _make_handler(mod, queue=None)
        assert handler._event_queue is None

    def test_init_command_indicator_files_default(self):
        """Constructor should default command_indicator_files to empty dict."""
        mod, _, _, _, _ = _import_filesystem_handler()
        handler = _make_handler(mod)
        assert handler._command_indicator_files == {}

    def test_init_command_indicator_files_set(self):
        """Constructor should store command_indicator_files."""
        mod, _, _, _, _ = _import_filesystem_handler()
        cif = {"status.json": "status command"}
        handler = _make_handler(mod, command_indicator_files=cif)
        assert handler._command_indicator_files == cif

    def test_init_creates_tracking_dicts(self):
        """Constructor should initialize all tracking dictionaries."""
        mod, _, _, _, _ = _import_filesystem_handler()
        handler = _make_handler(mod)
        assert handler._last_file_command == {}
        assert handler._jsonl_positions == {}
        assert handler._last_agent_action == {}
        assert handler._session_models == {}
        assert handler._session_branches == {}
        assert isinstance(handler._branch_warn_logged, set)

    def test_init_logs_operation(self):
        """Constructor should call json_handler.log_operation."""
        mod, _, _, _, _ = _import_filesystem_handler()
        _make_handler(mod)
        mod.json_handler.log_operation.assert_called()


# =============================================
# PROPERTY TESTS
# =============================================


class TestEventQueueProperty:
    """Tests for event_queue property getter/setter."""

    def test_getter_returns_queue(self):
        """Property getter should return the stored queue."""
        mod, _, _, _, queue = _import_filesystem_handler()
        handler = _make_handler(mod, queue=queue)
        assert handler.event_queue is queue

    def test_setter_replaces_queue(self):
        """Property setter should replace the queue."""
        mod, _, _, _, _ = _import_filesystem_handler()
        handler = _make_handler(mod, queue=None)
        assert handler.event_queue is None
        new_queue = MagicMock()
        handler.event_queue = new_queue
        assert handler.event_queue is new_queue


# =============================================
# WATCHDOG EVENT METHOD TESTS
# =============================================


class TestOnCreated:
    """Tests for on_created."""

    def test_file_event_calls_handle_event(self):
        """Should call _handle_event for non-directory events."""
        mod, _, _, _, queue = _import_filesystem_handler()
        handler = _make_handler(mod, queue=queue)
        event = MagicMock()
        event.is_directory = False
        event.src_path = "/some/file.py"
        with patch.object(handler, "_handle_event") as mock_handle:
            handler.on_created(event)
            mock_handle.assert_called_once_with("created", "/some/file.py")

    def test_directory_event_skipped(self):
        """Should skip directory events."""
        mod, _, _, _, queue = _import_filesystem_handler()
        handler = _make_handler(mod, queue=queue)
        event = MagicMock()
        event.is_directory = True
        with patch.object(handler, "_handle_event") as mock_handle:
            handler.on_created(event)
            mock_handle.assert_not_called()


class TestOnModified:
    """Tests for on_modified."""

    def test_file_event_calls_handle_event(self):
        """Should call _handle_event for non-directory events."""
        mod, _, _, _, queue = _import_filesystem_handler()
        handler = _make_handler(mod, queue=queue)
        event = MagicMock()
        event.is_directory = False
        event.src_path = "/some/file.py"
        with patch.object(handler, "_handle_event") as mock_handle:
            handler.on_modified(event)
            mock_handle.assert_called_once_with("modified", "/some/file.py")

    def test_directory_event_skipped(self):
        """Should skip directory events."""
        mod, _, _, _, _ = _import_filesystem_handler()
        handler = _make_handler(mod)
        event = MagicMock()
        event.is_directory = True
        with patch.object(handler, "_handle_event") as mock_handle:
            handler.on_modified(event)
            mock_handle.assert_not_called()


class TestOnDeleted:
    """Tests for on_deleted."""

    def test_file_event_calls_handle_event(self):
        """Should call _handle_event for non-directory events."""
        mod, _, _, _, queue = _import_filesystem_handler()
        handler = _make_handler(mod, queue=queue)
        event = MagicMock()
        event.is_directory = False
        event.src_path = "/some/file.py"
        with patch.object(handler, "_handle_event") as mock_handle:
            handler.on_deleted(event)
            mock_handle.assert_called_once_with("deleted", "/some/file.py")

    def test_directory_event_skipped(self):
        """Should skip directory events."""
        mod, _, _, _, _ = _import_filesystem_handler()
        handler = _make_handler(mod)
        event = MagicMock()
        event.is_directory = True
        with patch.object(handler, "_handle_event") as mock_handle:
            handler.on_deleted(event)
            mock_handle.assert_not_called()


class TestOnMoved:
    """Tests for on_moved."""

    def test_move_to_trash(self):
        """Move to Trash should emit deleted event."""
        mod, _, _, _, queue = _import_filesystem_handler()
        handler = _make_handler(mod, queue=queue)
        event = MagicMock()
        event.is_directory = False
        event.src_path = "/some/file.py"
        event.dest_path = "/home/user/.local/share/Trash/files/file.py"
        with patch.object(handler, "_handle_event") as mock_handle:
            handler.on_moved(event)
            mock_handle.assert_called_once_with("deleted", "/some/file.py")

    def test_atomic_write_tmp_infix(self):
        """Move from .tmp. infix file should emit modified event."""
        mod, _, _, _, queue = _import_filesystem_handler()
        handler = _make_handler(mod, queue=queue)
        event = MagicMock()
        event.is_directory = False
        event.src_path = "/some/.tmp.file.py"
        event.dest_path = "/some/file.py"
        with patch.object(handler, "_handle_event") as mock_handle:
            handler.on_moved(event)
            mock_handle.assert_called_once_with("modified", "/some/file.py")

    def test_atomic_write_tmp_suffix(self):
        """Move from file ending in .tmp should emit modified event."""
        mod, _, _, _, queue = _import_filesystem_handler()
        handler = _make_handler(mod, queue=queue)
        event = MagicMock()
        event.is_directory = False
        event.src_path = "/some/file.py.tmp"
        event.dest_path = "/some/file.py"
        with patch.object(handler, "_handle_event") as mock_handle:
            handler.on_moved(event)
            mock_handle.assert_called_once_with("modified", "/some/file.py")

    def test_normal_move(self):
        """Normal move should emit moved event with dest path."""
        mod, _, _, _, queue = _import_filesystem_handler()
        handler = _make_handler(mod, queue=queue)
        event = MagicMock()
        event.is_directory = False
        event.src_path = "/some/old.py"
        event.dest_path = "/some/new.py"
        with patch.object(handler, "_handle_event") as mock_handle:
            handler.on_moved(event)
            mock_handle.assert_called_once_with("moved", "/some/new.py")

    def test_directory_event_skipped(self):
        """Should skip directory events."""
        mod, _, _, _, _ = _import_filesystem_handler()
        handler = _make_handler(mod)
        event = MagicMock()
        event.is_directory = True
        with patch.object(handler, "_handle_event") as mock_handle:
            handler.on_moved(event)
            mock_handle.assert_not_called()

    def test_bytes_paths(self):
        """Should handle bytes paths via decode."""
        mod, _, _, _, queue = _import_filesystem_handler()
        handler = _make_handler(mod, queue=queue)
        event = MagicMock()
        event.is_directory = False
        event.src_path = b"/some/old.py"
        event.dest_path = b"/some/new.py"
        with patch.object(handler, "_handle_event") as mock_handle:
            handler.on_moved(event)
            mock_handle.assert_called_once_with("moved", "/some/new.py")


# =============================================
# FORMAT TOOL ACTION TESTS
# =============================================


class TestFormatToolAction:
    """Tests for _format_tool_action static method."""

    def test_read_tool(self):
        """Should format Read tool with short filename."""
        mod, _, _, _, _ = _import_filesystem_handler()
        cls = mod.MonitoringFileHandler
        result = cls._format_tool_action({"name": "Read", "input": {"file_path": "/home/user/src/file.py"}})
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
# BRANCH FROM CWD TESTS
# =============================================


class TestBranchFromCwd:
    """Tests for _branch_from_cwd static method."""

    def test_aipass_branch(self):
        """Should extract branch name after aipass in path."""
        mod, _, _, _, _ = _import_filesystem_handler()
        cls = mod.MonitoringFileHandler
        result = cls._branch_from_cwd("/home/user/Projects/AIPass/src/aipass/prax")
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

    def test_no_aipass_no_src(self):
        """Should return None when no recognizable pattern."""
        mod, _, _, _, _ = _import_filesystem_handler()
        cls = mod.MonitoringFileHandler
        result = cls._branch_from_cwd("/tmp/random/dir")
        assert result is None

    def test_aipass_at_end_of_path(self):
        """Should return None when aipass is the last segment."""
        mod, _, _, _, _ = _import_filesystem_handler()
        cls = mod.MonitoringFileHandler
        result = cls._branch_from_cwd("/home/user/aipass")
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

    def test_reads_cwd_from_session_meta(self):
        """Should read CWD from first line of Codex JSONL."""
        mod, _, _, _, _ = _import_filesystem_handler()
        handler = _make_handler(mod)
        meta_line = json.dumps({"type": "session_meta", "payload": {"cwd": "/home/user/project"}})
        with patch("builtins.open", _mopen(read_data=meta_line + "\n")):
            result = handler._read_codex_cwd("/fake/session.jsonl")
        assert result == "/home/user/project"

    def test_empty_first_line(self):
        """Should return None for empty first line."""
        mod, _, _, _, _ = _import_filesystem_handler()
        handler = _make_handler(mod)
        with patch("builtins.open", _mopen(read_data="\n")):
            result = handler._read_codex_cwd("/fake/session.jsonl")
        assert result is None

    def test_not_session_meta(self):
        """Should return None if first line is not session_meta type."""
        mod, _, _, _, _ = _import_filesystem_handler()
        handler = _make_handler(mod)
        meta_line = json.dumps({"type": "event_msg", "payload": {}})
        with patch("builtins.open", _mopen(read_data=meta_line + "\n")):
            result = handler._read_codex_cwd("/fake/session.jsonl")
        assert result is None

    def test_os_error(self):
        """Should return None on OSError."""
        mod, _, _, _, _ = _import_filesystem_handler()
        handler = _make_handler(mod)
        with patch("builtins.open", side_effect=OSError("no file")):
            result = handler._read_codex_cwd("/fake/session.jsonl")
        assert result is None

    def test_json_decode_error(self):
        """Should return None on JSONDecodeError."""
        mod, _, _, _, _ = _import_filesystem_handler()
        handler = _make_handler(mod)
        with patch("builtins.open", _mopen(read_data="not json\n")):
            result = handler._read_codex_cwd("/fake/session.jsonl")
        assert result is None


# =============================================
# GET CODEX BRANCH TESTS
# =============================================


class TestGetCodexBranch:
    """Tests for _get_codex_branch."""

    def test_cached_branch(self):
        """Should return cached branch if present."""
        mod, _, _, _, _ = _import_filesystem_handler()
        handler = _make_handler(mod)
        handler._session_branches["key1"] = "CACHED"
        result = handler._get_codex_branch("/fake/file.jsonl", "key1")
        assert result == "CACHED"

    def test_reads_cwd_and_detects_branch(self):
        """Should read CWD and detect branch from it."""
        mod, _, _, _, _ = _import_filesystem_handler()
        handler = _make_handler(mod)
        meta_line = json.dumps(
            {
                "type": "session_meta",
                "payload": {"cwd": "/home/user/Projects/AIPass/src/aipass/prax"},
            }
        )
        with patch("builtins.open", _mopen(read_data=meta_line + "\n")):
            result = handler._get_codex_branch("/fake/file.jsonl", "key2")
        assert result == "PRAX"
        assert handler._session_branches["key2"] == "PRAX"

    def test_no_cwd_returns_codex(self):
        """Should return CODEX when CWD cannot be read."""
        mod, _, _, _, _ = _import_filesystem_handler()
        handler = _make_handler(mod)
        with patch("builtins.open", _mopen(read_data="\n")):
            result = handler._get_codex_branch("/fake/file.jsonl", "key3")
        assert result == "CODEX"

    def test_cwd_but_no_branch_returns_codex(self):
        """Should return CODEX when CWD has no branch pattern."""
        mod, _, _, _, _ = _import_filesystem_handler()
        handler = _make_handler(mod)
        meta_line = json.dumps({"type": "session_meta", "payload": {"cwd": "/tmp/nowhere"}})
        with patch("builtins.open", _mopen(read_data=meta_line + "\n")):
            result = handler._get_codex_branch("/fake/file.jsonl", "key4")
        assert result == "CODEX"


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
# READ NEW JSONL LINES TESTS
# =============================================


class TestReadNewJsonlLines:
    """Tests for _read_new_jsonl_lines."""

    def test_reads_new_data(self):
        """Should read new lines since last position."""
        mod, _, _, _, _ = _import_filesystem_handler()
        handler = _make_handler(mod)
        mock_path = MagicMock()
        mock_path.stat.return_value.st_size = 50
        data = '{"type": "test"}\n'
        with patch("builtins.open", _mopen(read_data=data)):
            result = handler._read_new_jsonl_lines(mock_path, "pk")
        assert result is not None
        assert len(result) == 1

    def test_no_new_data(self):
        """Should return None when no new data."""
        mod, _, _, _, _ = _import_filesystem_handler()
        handler = _make_handler(mod)
        handler._jsonl_positions["pk"] = 100
        mock_path = MagicMock()
        mock_path.stat.return_value.st_size = 100
        result = handler._read_new_jsonl_lines(mock_path, "pk")
        assert result is None

    def test_file_truncated_resets_position(self):
        """Should reset position when file shrinks (truncation)."""
        mod, _, _, _, _ = _import_filesystem_handler()
        handler = _make_handler(mod)
        handler._jsonl_positions["pk"] = 200
        mock_path = MagicMock()
        mock_path.stat.return_value.st_size = 50
        data = '{"type": "new"}\n'
        with patch("builtins.open", _mopen(read_data=data)):
            result = handler._read_new_jsonl_lines(mock_path, "pk")
        assert result is not None

    def test_empty_new_data(self):
        """Should return None when new data is all whitespace."""
        mod, _, _, _, _ = _import_filesystem_handler()
        handler = _make_handler(mod)
        mock_path = MagicMock()
        mock_path.stat.return_value.st_size = 50
        with patch("builtins.open", _mopen(read_data="   \n  \n")):
            result = handler._read_new_jsonl_lines(mock_path, "pk")
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

    def test_parses_lines_and_emits(self):
        """Should parse new JSONL lines and emit agent event."""
        mod, _, _, _, queue = _import_filesystem_handler()
        handler = _make_handler(mod, queue=queue)
        mock_path = MagicMock()
        mock_path.stat.return_value.st_size = 100
        mock_path.__str__ = MagicMock(return_value="/fake/codex.jsonl")
        mock_path.name = "codex.jsonl"
        line = json.dumps(
            {
                "type": "event_msg",
                "payload": {"type": "user_message"},
            }
        )
        with patch("builtins.open", _mopen(read_data=line + "\n")):
            result = handler._parse_codex_activity(mock_path, "CODEX")
        assert result is True
        queue.enqueue.assert_called()

    def test_no_new_lines(self):
        """Should return True when no new lines."""
        mod, _, _, _, queue = _import_filesystem_handler()
        handler = _make_handler(mod, queue=queue)
        mock_path = MagicMock()
        mock_path.stat.return_value.st_size = 50
        mock_path.__str__ = MagicMock(return_value="/fake/codex.jsonl")
        handler._jsonl_positions["/fake/codex.jsonl"] = 50
        result = handler._parse_codex_activity(mock_path, "CODEX")
        assert result is True

    def test_malformed_json_skipped(self):
        """Should skip malformed JSON lines."""
        mod, _, _, _, queue = _import_filesystem_handler()
        handler = _make_handler(mod, queue=queue)
        mock_path = MagicMock()
        mock_path.stat.return_value.st_size = 100
        mock_path.__str__ = MagicMock(return_value="/fake/codex.jsonl")
        mock_path.name = "codex.jsonl"
        with patch("builtins.open", _mopen(read_data="not json\n")):
            result = handler._parse_codex_activity(mock_path, "CODEX")
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

    def test_extracts_model_from_turn_context(self):
        """Should extract model from turn_context entries."""
        mod, _, _, _, queue = _import_filesystem_handler()
        handler = _make_handler(mod, queue=queue)
        mock_path = MagicMock()
        mock_path.stat.return_value.st_size = 200
        mock_path.__str__ = MagicMock(return_value="/fake/codex.jsonl")
        mock_path.name = "codex.jsonl"
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
        with patch("builtins.open", _mopen(read_data=lines + "\n")):
            handler._parse_codex_activity(mock_path, "CODEX")
        assert handler._session_models.get("/fake/codex.jsonl") == "o4-mini"

    def test_no_actionable_lines(self):
        """Should return True when all lines produce no action."""
        mod, _, _, _, queue = _import_filesystem_handler()
        handler = _make_handler(mod, queue=queue)
        mock_path = MagicMock()
        mock_path.stat.return_value.st_size = 100
        mock_path.__str__ = MagicMock(return_value="/fake/codex.jsonl")
        mock_path.name = "codex.jsonl"
        line = json.dumps({"type": "session_meta", "payload": {}})
        with patch("builtins.open", _mopen(read_data=line + "\n")):
            result = handler._parse_codex_activity(mock_path, "CODEX")
        assert result is True
        queue.enqueue.assert_not_called()


# =============================================
# PARSE AGENT ACTIVITY (CLAUDE CODE) TESTS
# =============================================


class TestParseAgentActivity:
    """Tests for _parse_agent_activity (Claude Code JSONL)."""

    def test_parses_and_emits_event(self):
        """Should parse JSONL and emit agent event."""
        mod, _, _, _, queue = _import_filesystem_handler()
        handler = _make_handler(mod, queue=queue)
        mock_path = MagicMock()
        mock_path.stat.return_value.st_size = 200
        mock_path.__str__ = MagicMock(return_value="/fake/claude.jsonl")
        mock_path.name = "claude.jsonl"
        entry = {
            "type": "assistant",
            "message": {"content": [{"type": "thinking"}]},
        }
        with patch("builtins.open", _mopen(read_data=json.dumps(entry) + "\n")):
            result = handler._parse_agent_activity(mock_path, "PRAX")
        assert result is True
        queue.enqueue.assert_called()

    def test_no_new_data(self):
        """Should return True when no new data."""
        mod, _, _, _, queue = _import_filesystem_handler()
        handler = _make_handler(mod, queue=queue)
        mock_path = MagicMock()
        mock_path.stat.return_value.st_size = 50
        mock_path.__str__ = MagicMock(return_value="/fake/claude.jsonl")
        handler._jsonl_positions["/fake/claude.jsonl"] = 50
        result = handler._parse_agent_activity(mock_path, "PRAX")
        assert result is True

    def test_file_truncated(self):
        """Should reset position when file shrinks."""
        mod, _, _, _, queue = _import_filesystem_handler()
        handler = _make_handler(mod, queue=queue)
        handler._jsonl_positions["/fake/claude.jsonl"] = 1000
        mock_path = MagicMock()
        mock_path.stat.return_value.st_size = 100
        mock_path.__str__ = MagicMock(return_value="/fake/claude.jsonl")
        mock_path.name = "claude.jsonl"
        entry = {"type": "user", "message": {"content": "hello"}}
        with patch("builtins.open", _mopen(read_data=json.dumps(entry) + "\n")):
            result = handler._parse_agent_activity(mock_path, "PRAX")
        assert result is True

    def test_malformed_line_skipped(self):
        """Should skip malformed JSON lines."""
        mod, _, _, _, queue = _import_filesystem_handler()
        handler = _make_handler(mod, queue=queue)
        mock_path = MagicMock()
        mock_path.stat.return_value.st_size = 200
        mock_path.__str__ = MagicMock(return_value="/fake/claude.jsonl")
        mock_path.name = "claude.jsonl"
        good_entry = json.dumps({"type": "user", "message": {"content": "hi"}})
        data = "not json\n" + good_entry + "\n"
        with patch("builtins.open", _mopen(read_data=data)):
            result = handler._parse_agent_activity(mock_path, "PRAX")
        assert result is True
        queue.enqueue.assert_called()

    def test_deduplicates(self):
        """Should not emit duplicate actions."""
        mod, _, _, _, queue = _import_filesystem_handler()
        handler = _make_handler(mod, queue=queue)
        handler._last_agent_action["/fake/claude.jsonl"] = "User message"
        mock_path = MagicMock()
        mock_path.stat.return_value.st_size = 100
        mock_path.__str__ = MagicMock(return_value="/fake/claude.jsonl")
        mock_path.name = "claude.jsonl"
        entry = {"type": "user", "message": {"content": "hello"}}
        with patch("builtins.open", _mopen(read_data=json.dumps(entry) + "\n")):
            result = handler._parse_agent_activity(mock_path, "PRAX")
        assert result is True

    def test_extracts_model(self):
        """Should extract model from entries."""
        mod, _, _, _, queue = _import_filesystem_handler()
        handler = _make_handler(mod, queue=queue)
        mock_path = MagicMock()
        mock_path.stat.return_value.st_size = 200
        mock_path.__str__ = MagicMock(return_value="/fake/claude.jsonl")
        mock_path.name = "claude.jsonl"
        entry = {
            "type": "assistant",
            "message": {
                "model": "claude-opus-4-20250514",
                "content": [{"type": "thinking"}],
            },
        }
        with patch("builtins.open", _mopen(read_data=json.dumps(entry) + "\n")):
            handler._parse_agent_activity(mock_path, "PRAX")
        assert handler._session_models.get("/fake/claude.jsonl") == "opus"

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

    def test_empty_lines_after_split(self):
        """Should return True when all lines are empty after strip."""
        mod, _, _, _, queue = _import_filesystem_handler()
        handler = _make_handler(mod, queue=queue)
        mock_path = MagicMock()
        mock_path.stat.return_value.st_size = 100
        mock_path.__str__ = MagicMock(return_value="/fake/claude.jsonl")
        mock_path.name = "claude.jsonl"
        with patch("builtins.open", _mopen(read_data="  \n  \n")):
            result = handler._parse_agent_activity(mock_path, "PRAX")
        assert result is True

    def test_no_actionable_entries(self):
        """Should return True when entries produce no actions."""
        mod, _, _, _, queue = _import_filesystem_handler()
        handler = _make_handler(mod, queue=queue)
        mock_path = MagicMock()
        mock_path.stat.return_value.st_size = 100
        mock_path.__str__ = MagicMock(return_value="/fake/claude.jsonl")
        mock_path.name = "claude.jsonl"
        entry = {"type": "progress"}
        with patch("builtins.open", _mopen(read_data=json.dumps(entry) + "\n")):
            result = handler._parse_agent_activity(mock_path, "PRAX")
        assert result is True
        queue.enqueue.assert_not_called()

    def test_no_queue_still_returns_true(self):
        """Should return True even with no queue."""
        mod, _, _, _, _ = _import_filesystem_handler()
        handler = _make_handler(mod, queue=None)
        mock_path = MagicMock()
        mock_path.stat.return_value.st_size = 100
        mock_path.__str__ = MagicMock(return_value="/fake/claude.jsonl")
        mock_path.name = "claude.jsonl"
        entry = {"type": "user", "message": {"content": "hi"}}
        with patch("builtins.open", _mopen(read_data=json.dumps(entry) + "\n")):
            result = handler._parse_agent_activity(mock_path, "PRAX")
        assert result is True

    def test_batch_cap_limits_emitted_events(self):
        """Should only emit last N events when batch exceeds cap."""
        mod, _, _, _, queue = _import_filesystem_handler()
        handler = _make_handler(mod, queue=queue)
        mock_path = MagicMock()
        mock_path.__str__ = MagicMock(return_value="/fake/claude.jsonl")
        mock_path.name = "claude.jsonl"
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
        mock_path.stat.return_value.st_size = len(data)
        with patch("builtins.open", _mopen(read_data=data)):
            result = handler._parse_agent_activity(mock_path, "PRAX")
        assert result is True
        cap = mod.MonitoringFileHandler._MAX_AGENT_EVENTS_PER_BATCH
        assert queue.enqueue.call_count == cap

    def test_batch_cap_emits_tail_not_head(self):
        """Should emit the last actions in a large batch, not the first."""
        mod, mock_eq, _, _, queue = _import_filesystem_handler()
        handler = _make_handler(mod, queue=queue)
        mock_path = MagicMock()
        mock_path.__str__ = MagicMock(return_value="/fake/claude.jsonl")
        mock_path.name = "claude.jsonl"
        entries = []
        for i in range(6):
            entries.append(
                {
                    "type": "assistant",
                    "message": {"content": [{"type": "tool_use", "name": f"Tool{i}", "input": {}}]},
                }
            )
        data = "\n".join(json.dumps(e) for e in entries) + "\n"
        mock_path.stat.return_value.st_size = len(data)
        with patch("builtins.open", _mopen(read_data=data)):
            handler._parse_agent_activity(mock_path, "PRAX")
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
        queue.enqueue.assert_called_once()

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


# =============================================
# HANDLE EVENT TESTS
# =============================================


class TestHandleEvent:
    """Tests for _handle_event."""

    def test_basic_file_event(self):
        """Should create and enqueue a file event."""
        mod, _, mock_bd, mock_filters, queue = _import_filesystem_handler()
        handler = _make_handler(mod, queue=queue)
        mock_filters.should_monitor.return_value = True
        mock_filters.get_priority.return_value = "info"
        mock_bd.detect_branch_from_path.return_value = "PRAX"
        handler._handle_event(
            "modified",
            "/home/user/src/aipass/prax/apps/test.py",
        )
        queue.enqueue.assert_called()

    def test_skips_unmonitored_files(self):
        """Should skip files that should_monitor returns False for."""
        mod, _, _, mock_filters, queue = _import_filesystem_handler()
        handler = _make_handler(mod, queue=queue)
        mock_filters.should_monitor.return_value = False
        handler._handle_event("modified", "/tmp/ignored.txt")
        queue.enqueue.assert_not_called()

    def test_claude_code_jsonl(self):
        """Should parse Claude Code JSONL files."""
        mod, _, mock_bd, mock_filters, queue = _import_filesystem_handler()
        handler = _make_handler(mod, queue=queue)
        mock_filters.should_monitor.return_value = True
        mock_bd.detect_branch_from_path.return_value = "PRAX"
        with patch.object(handler, "_parse_agent_activity", return_value=True) as mock_parse:
            handler._handle_event(
                "modified",
                "/home/user/.claude/projects/abc/session.jsonl",
            )
            mock_parse.assert_called_once()

    def test_claude_code_subagent(self):
        """Should tag subagent JSONL files with agent suffix."""
        mod, _, mock_bd, mock_filters, queue = _import_filesystem_handler()
        handler = _make_handler(mod, queue=queue)
        mock_filters.should_monitor.return_value = True
        mock_bd.detect_branch_from_path.return_value = "PRAX"
        with patch.object(handler, "_parse_agent_activity", return_value=True) as mock_parse:
            handler._handle_event(
                "modified",
                "/home/user/.claude/projects/abc/subagents/session.jsonl",
            )
            call_args = mock_parse.call_args
            assert "PRAX agent" in str(call_args)

    def test_codex_jsonl(self):
        """Should parse Codex JSONL files."""
        mod, _, mock_bd, mock_filters, queue = _import_filesystem_handler()
        handler = _make_handler(mod, queue=queue)
        mock_filters.should_monitor.return_value = True
        mock_bd.detect_branch_from_path.return_value = "CODEX"
        with patch.object(handler, "_get_codex_branch", return_value="PRAX"):
            with patch.object(
                handler,
                "_parse_codex_activity",
                return_value=True,
            ) as mock_parse:
                handler._handle_event(
                    "modified",
                    "/home/user/.codex/sessions/session.jsonl",
                )
                mock_parse.assert_called_once()

    def test_exception_caught(self):
        """A failure inside the handler costs the event, never the watcher.

        The observable consequence of the guard: the event is DROPPED (no
        MonitoringEvent is built, nothing reaches the queue) and the operator is
        told which file and which error type in plain language.
        """
        mod, mock_eq, _, mock_filters, queue = _import_filesystem_handler()
        handler = _make_handler(mod, queue=queue)
        mock_filters.should_monitor.side_effect = Exception("boom")

        with patch.object(mod, "logger") as log:
            assert handler._handle_event("modified", "/some/file.py") is None

        mock_eq.MonitoringEvent.assert_not_called()
        queue.enqueue.assert_not_called()
        message = log.error.call_args.args[0]
        assert "/some/file.py" in message, "the report must name the file that failed"
        assert "Exception on modified" in message, "the report must name the error type and the action"
        assert "file watching continues" in message

    def test_priority_levels_mapped(self):
        """Should map priority levels correctly."""
        mod, mock_eq, mock_bd, mock_filters, queue = _import_filesystem_handler()
        handler = _make_handler(mod, queue=queue)
        mock_filters.should_monitor.return_value = True
        mock_filters.get_priority.return_value = "error"
        mock_bd.detect_branch_from_path.return_value = "PRAX"
        handler._handle_event("modified", "/home/user/src/aipass/prax/test.py")
        call_kwargs = mock_eq.MonitoringEvent.call_args
        assert "error" in str(call_kwargs)

    def test_unknown_priority_defaults_to_info(self):
        """Should default to info for unknown priority levels."""
        mod, mock_eq, mock_bd, mock_filters, queue = _import_filesystem_handler()
        handler = _make_handler(mod, queue=queue)
        mock_filters.should_monitor.return_value = True
        mock_filters.get_priority.return_value = "custom_level"
        mock_bd.detect_branch_from_path.return_value = "PRAX"
        handler._handle_event("modified", "/home/user/src/aipass/prax/test.py")
        call_kwargs = mock_eq.MonitoringEvent.call_args
        assert "info" in str(call_kwargs)


# =============================================
# BUILD DISPLAY NAME TESTS
# =============================================


class TestBuildDisplayName:
    """Tests for _build_display_name static method."""

    def test_apps_prefix(self):
        """Should return path from apps onwards."""
        mod, _, _, _, _ = _import_filesystem_handler()
        cls = mod.MonitoringFileHandler
        result = cls._build_display_name(Path("/home/user/src/aipass/prax/apps/handlers/test.py"))
        assert result == "apps/handlers/test.py"

    def test_handlers_prefix(self):
        """Should return path from handlers onwards."""
        mod, _, _, _, _ = _import_filesystem_handler()
        cls = mod.MonitoringFileHandler
        result = cls._build_display_name(Path("/home/user/handlers/monitoring/file.py"))
        assert result == "handlers/monitoring/file.py"

    def test_modules_prefix(self):
        """Should return path from modules onwards."""
        mod, _, _, _, _ = _import_filesystem_handler()
        cls = mod.MonitoringFileHandler
        result = cls._build_display_name(Path("/home/user/modules/logger.py"))
        assert result == "modules/logger.py"

    def test_docs_prefix(self):
        """Should return path from docs onwards."""
        mod, _, _, _, _ = _import_filesystem_handler()
        cls = mod.MonitoringFileHandler
        result = cls._build_display_name(Path("/home/user/docs/readme.md"))
        assert result == "docs/readme.md"

    def test_templates_prefix(self):
        """Should return path from templates onwards."""
        mod, _, _, _, _ = _import_filesystem_handler()
        cls = mod.MonitoringFileHandler
        result = cls._build_display_name(Path("/home/user/templates/base.html"))
        assert result == "templates/base.html"

    def test_no_known_prefix(self):
        """Should return filename when no known prefix found."""
        mod, _, _, _, _ = _import_filesystem_handler()
        cls = mod.MonitoringFileHandler
        result = cls._build_display_name(Path("/home/user/random/file.py"))
        assert result == "file.py"
