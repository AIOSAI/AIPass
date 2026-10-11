# =================== AIPass ====================
# Name: test_filesystem_handler.py
# Description: Unit tests for filesystem_handler.py
# Version: 1.3.0
# Created: 2026-04-26
# Modified: 2026-10-08
# =============================================

"""Tests for apps/handlers/monitoring/filesystem_handler.py, its watchdog events."""

# Unit tests for MonitoringFileHandler.
#
# Covers: __init__, watchdog event methods, internal event processing, and
# display name building. Split 2026-10-08: the tool action and model
# extraction, the Codex lane, and the JSONL reading and agent activity each
# have their own test_filesystem_handler_<topic>.py.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(through_the_command) — should_monitor, covered by tests/test_monitoring_filters.py
# seedgo: no-test-needed(through_the_command) — get_priority, covered by tests/test_monitoring_filters.py
# seedgo: no-test-needed(through_the_command) — detect_branch_from_path, covered by tests/test_monitoring_handlers.py
# seedgo: no-test-needed(json_structure) — the shape of __init__'s file_change_handled log_operation record

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from aipass.prax.tests.support_test_filesystem_handler import _import_filesystem_handler, _make_handler

pytestmark = pytest.mark.usefixtures("_filesystem_handler_doubled")


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
        assert handler._branch_warn_logged == set()

    def test_init_logs_operation(self):
        """Constructor should call json_handler.log_operation."""
        mod, _, _, _, queue = _import_filesystem_handler()
        with patch.object(mod, "json_handler") as recorder:
            _make_handler(mod, queue=queue)
        recorder.log_operation.assert_called_once_with("file_change_handled", {"has_queue": True})


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

    def test_move_to_trash(self, tmp_path):
        """Move to Trash should emit deleted event."""
        mod, _, _, _, queue = _import_filesystem_handler()
        handler = _make_handler(mod, queue=queue)
        event = MagicMock()
        event.is_directory = False
        event.src_path = "/some/file.py"
        event.dest_path = str(tmp_path / ".local" / "share" / "Trash" / "files" / "file.py")
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
# HANDLE EVENT TESTS
# =============================================


class TestHandleEvent:
    """Tests for _handle_event."""

    def test_basic_file_event(self, tmp_path):
        """Should create and enqueue a file event."""
        mod, _, mock_bd, mock_filters, queue = _import_filesystem_handler()
        handler = _make_handler(mod, queue=queue)
        mock_filters.should_monitor.return_value = True
        mock_filters.get_priority.return_value = "info"
        mock_bd.detect_branch_from_path.return_value = "PRAX"
        handler._handle_event(
            "modified",
            str(tmp_path / "src" / "aipass" / "prax" / "apps" / "test.py"),
        )
        kwargs = mod.MonitoringEvent.call_args.kwargs
        assert (kwargs["event_type"], kwargs["branch"], kwargs["action"]) == ("file", "PRAX", "modified")
        queue.enqueue.assert_called_once_with(mod.MonitoringEvent.return_value)

    def test_skips_unmonitored_files(self, tmp_path):
        """Should skip files that should_monitor returns False for."""
        mod, _, _, mock_filters, queue = _import_filesystem_handler()
        handler = _make_handler(mod, queue=queue)
        mock_filters.should_monitor.return_value = False
        handler._handle_event("modified", str(tmp_path / "ignored.txt"))
        queue.enqueue.assert_not_called()

    def test_claude_code_jsonl(self, tmp_path):
        """Should parse Claude Code JSONL files."""
        mod, _, mock_bd, mock_filters, queue = _import_filesystem_handler()
        handler = _make_handler(mod, queue=queue)
        mock_filters.should_monitor.return_value = True
        mock_bd.detect_branch_from_path.return_value = "PRAX"
        session = tmp_path / ".claude" / "projects" / "abc" / "session.jsonl"
        with patch.object(handler, "_parse_agent_activity", return_value=True) as mock_parse:
            handler._handle_event("modified", str(session))
            mock_parse.assert_called_once_with(session, "PRAX")

    def test_claude_code_subagent(self, tmp_path):
        """Should tag subagent JSONL files with agent suffix."""
        mod, _, mock_bd, mock_filters, queue = _import_filesystem_handler()
        handler = _make_handler(mod, queue=queue)
        mock_filters.should_monitor.return_value = True
        mock_bd.detect_branch_from_path.return_value = "PRAX"
        with patch.object(handler, "_parse_agent_activity", return_value=True) as mock_parse:
            handler._handle_event(
                "modified",
                str(tmp_path / ".claude" / "projects" / "abc" / "subagents" / "session.jsonl"),
            )
            call_args = mock_parse.call_args
            assert "PRAX agent" in str(call_args)

    def test_codex_jsonl(self, tmp_path):
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
                session = tmp_path / ".codex" / "sessions" / "session.jsonl"
                handler._handle_event("modified", str(session))
                mock_parse.assert_called_once_with(session, "PRAX")

    def test_claude_code_jsonl_windows_form(self):
        """A Windows-form Claude Code JSONL path is still parsed as agent activity.

        Mutant: testing ".claude/projects/" against the raw path_str again reddens this.
        """
        mod, _, mock_bd, mock_filters, queue = _import_filesystem_handler()
        handler = _make_handler(mod, queue=queue)
        mock_filters.should_monitor.return_value = True
        mock_bd.detect_branch_from_path.return_value = "PRAX"
        with patch.object(handler, "_parse_agent_activity", return_value=True) as mock_parse:
            windows_form = "D:\\dev\\.claude\\projects\\abc\\session.jsonl"
            handler._handle_event("modified", windows_form)
            mock_parse.assert_called_once_with(Path(windows_form), "PRAX")

    def test_claude_code_subagent_windows_form(self):
        """A Windows-form subagent JSONL path is still tagged with the agent suffix.

        Mutant: testing "/subagents/" against the raw path_str again reddens this.
        """
        mod, _, mock_bd, mock_filters, queue = _import_filesystem_handler()
        handler = _make_handler(mod, queue=queue)
        mock_filters.should_monitor.return_value = True
        mock_bd.detect_branch_from_path.return_value = "PRAX"
        with patch.object(handler, "_parse_agent_activity", return_value=True) as mock_parse:
            handler._handle_event(
                "modified",
                "D:\\dev\\.claude\\projects\\abc\\subagents\\session.jsonl",
            )
            assert mock_parse.call_args.args[1] == "PRAX agent"

    def test_codex_jsonl_windows_form(self):
        """A Windows-form Codex JSONL path is still parsed, and the raw path goes on unchanged.

        Mutant: testing ".codex/sessions/" against the raw path_str again reddens this.
        """
        mod, _, mock_bd, mock_filters, queue = _import_filesystem_handler()
        handler = _make_handler(mod, queue=queue)
        mock_filters.should_monitor.return_value = True
        mock_bd.detect_branch_from_path.return_value = "CODEX"
        raw = "D:\\dev\\.codex\\sessions\\session.jsonl"
        with patch.object(handler, "_get_codex_branch", return_value="PRAX") as mock_branch:
            with patch.object(
                handler,
                "_parse_codex_activity",
                return_value=True,
            ) as mock_parse:
                handler._handle_event("modified", raw)
                mock_parse.assert_called_once()
                assert mock_branch.call_args.args[1] == raw

    def test_exception_caught(self, tmp_path):
        """A failure inside the handler costs the event, never the watcher.

        The observable consequence of the guard: the event is DROPPED (no
        MonitoringEvent is built, nothing reaches the queue) and the operator is
        told which file and which error type in plain language.
        """
        mod, mock_eq, _, mock_filters, queue = _import_filesystem_handler()
        handler = _make_handler(mod, queue=queue)
        mock_filters.should_monitor.side_effect = Exception("boom")
        failing_path = str(tmp_path / "file.py")

        with patch.object(mod, "logger") as log:
            assert handler._handle_event("modified", failing_path) is None

        mock_eq.MonitoringEvent.assert_not_called()
        queue.enqueue.assert_not_called()
        message = log.error.call_args.args[0]
        assert failing_path in message, "the report must name the file that failed"
        assert "Exception on modified" in message, "the report must name the error type and the action"
        assert "file watching continues" in message

    def test_priority_levels_mapped(self, tmp_path):
        """Should map priority levels correctly."""
        mod, mock_eq, mock_bd, mock_filters, queue = _import_filesystem_handler()
        handler = _make_handler(mod, queue=queue)
        mock_filters.should_monitor.return_value = True
        mock_filters.get_priority.return_value = "error"
        mock_bd.detect_branch_from_path.return_value = "PRAX"
        event_path = tmp_path / "src" / "aipass" / "prax" / "test.py"
        handler._handle_event("modified", str(event_path))
        call_kwargs = mock_eq.MonitoringEvent.call_args
        assert "error" in str(call_kwargs)
        # The level is asked for this path and this action (prax, leg 13: an
        # action dropped from the call survived every test in this file).
        mock_filters.get_priority.assert_called_once_with(event_path, "modified")

    def test_the_sandbox_root_reaches_should_monitor(self, tmp_path):
        """should_monitor is judged against the root the handler was given (prax, leg 4)."""
        mod, _eq, _bd, mock_filters, queue = _import_filesystem_handler()
        handler = mod.MonitoringFileHandler(event_queue=queue, sandbox_root=tmp_path)
        mock_filters.should_monitor.return_value = False
        event_path = tmp_path / "branch" / "dropbox" / "handed.py"
        handler._handle_event("modified", str(event_path))
        mock_filters.should_monitor.assert_called_once_with(event_path, tmp_path)
        queue.enqueue.assert_not_called()

    def test_unknown_priority_defaults_to_info(self, tmp_path):
        """Should default to info for unknown priority levels."""
        mod, mock_eq, mock_bd, mock_filters, queue = _import_filesystem_handler()
        handler = _make_handler(mod, queue=queue)
        mock_filters.should_monitor.return_value = True
        mock_filters.get_priority.return_value = "custom_level"
        mock_bd.detect_branch_from_path.return_value = "PRAX"
        handler._handle_event("modified", str(tmp_path / "src" / "aipass" / "prax" / "test.py"))
        call_kwargs = mock_eq.MonitoringEvent.call_args
        assert "info" in str(call_kwargs)


# =============================================
# BUILD DISPLAY NAME TESTS
# =============================================


class TestBuildDisplayName:
    """Tests for _build_display_name static method."""

    def test_apps_prefix(self, tmp_path):
        """Should return path from apps onwards."""
        mod, _, _, _, _ = _import_filesystem_handler()
        cls = mod.MonitoringFileHandler
        result = cls._build_display_name(tmp_path / "src" / "aipass" / "prax" / "apps" / "handlers" / "test.py")
        assert result == "apps/handlers/test.py"

    def test_handlers_prefix(self, tmp_path):
        """Should return path from handlers onwards."""
        mod, _, _, _, _ = _import_filesystem_handler()
        cls = mod.MonitoringFileHandler
        result = cls._build_display_name(tmp_path / "handlers" / "monitoring" / "file.py")
        assert result == "handlers/monitoring/file.py"

    def test_modules_prefix(self, tmp_path):
        """Should return path from modules onwards."""
        mod, _, _, _, _ = _import_filesystem_handler()
        cls = mod.MonitoringFileHandler
        result = cls._build_display_name(tmp_path / "modules" / "logger.py")
        assert result == "modules/logger.py"

    def test_docs_prefix(self, tmp_path):
        """Should return path from docs onwards."""
        mod, _, _, _, _ = _import_filesystem_handler()
        cls = mod.MonitoringFileHandler
        result = cls._build_display_name(tmp_path / "docs" / "readme.md")
        assert result == "docs/readme.md"

    def test_templates_prefix(self, tmp_path):
        """Should return path from templates onwards."""
        mod, _, _, _, _ = _import_filesystem_handler()
        cls = mod.MonitoringFileHandler
        result = cls._build_display_name(tmp_path / "templates" / "base.html")
        assert result == "templates/base.html"

    def test_no_known_prefix(self, tmp_path):
        """Should return filename when no known prefix found."""
        mod, _, _, _, _ = _import_filesystem_handler()
        cls = mod.MonitoringFileHandler
        result = cls._build_display_name(tmp_path / "random" / "file.py")
        assert result == "file.py"
