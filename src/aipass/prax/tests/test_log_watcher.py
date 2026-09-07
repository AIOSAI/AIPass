# =================== AIPass ====================
# Name: test_log_watcher.py
# Description: Tests for log file monitoring handler
# Version: 1.0.0
# Created: 2026-04-03
# Modified: 2026-04-03
# =============================================

"""Tests for apps/handlers/monitoring/log_watcher.py

Covers:
- LogFileWatcher._detect_log_level()  -- level detection from markers
- LogFileWatcher._extract_command_info() -- command pattern matching
- LogFileWatcher._parse_log_message()  -- pipe-delimited parsing
- start_log_watcher / stop_log_watcher / is_log_watcher_active
- initialize_positions() -- seek-to-end on startup
"""

import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _RealFSHandler:
    """Stub base so LogFileWatcher subclass methods are not swallowed by MagicMock."""

    pass


def _import_log_watcher() -> ModuleType:
    """Import log_watcher with all heavy deps mocked."""
    mock_observer_cls = MagicMock()
    mock_observer_instance = MagicMock()
    mock_observer_cls.return_value = mock_observer_instance

    mock_watchdog_observer = MagicMock()
    mock_watchdog_observer.Observer = mock_observer_cls

    # Provide a real base class for FileSystemEventHandler
    mock_watchdog_events = MagicMock()
    mock_watchdog_events.FileSystemEventHandler = _RealFSHandler

    mock_config = MagicMock()
    mock_config.get_system_logs_dir.return_value = Path("/fake/logs/system")

    mock_branch_detector = MagicMock()
    mock_branch_detector.detect_branch_from_log.return_value = "PRAX"

    mock_event_queue_mod = MagicMock()

    mock_trigger_mod = MagicMock()

    with patch.dict(
        sys.modules,
        {
            "watchdog": MagicMock(),
            "watchdog.observers": mock_watchdog_observer,
            "watchdog.events": mock_watchdog_events,
            "aipass.prax.apps.handlers.config.load": mock_config,
            "aipass.prax.apps.handlers.monitoring.event_queue": mock_event_queue_mod,
            "aipass.prax.apps.handlers.monitoring.branch_detector": mock_branch_detector,
            "aipass.trigger": MagicMock(),
            "aipass.trigger.apps": MagicMock(),
            "aipass.trigger.apps.modules": MagicMock(),
            "aipass.trigger.apps.modules.core": mock_trigger_mod,
        },
    ):
        import importlib

        if "aipass.prax.apps.handlers.monitoring.log_watcher" in sys.modules:
            mod = importlib.reload(sys.modules["aipass.prax.apps.handlers.monitoring.log_watcher"])
        else:
            mod = importlib.import_module("aipass.prax.apps.handlers.monitoring.log_watcher")

    return mod


def _make_watcher(mod: ModuleType):
    """Create a LogFileWatcher with a mock event queue."""
    mock_queue = MagicMock()
    watcher = mod.LogFileWatcher(mock_queue)
    return watcher, mock_queue


# ============================================================================
# _detect_log_level tests
# ============================================================================


class TestDetectLogLevel:
    """Test log level detection from raw log lines."""

    def test_error_markers(self):
        mod = _import_log_watcher()
        watcher, _ = _make_watcher(mod)
        for line in [
            "2025-11-23 10:00:00 - ERROR - Something broke",
            "[PRAX] 10:00:00 | module | ERROR | bad thing",
            "[ERROR] connection refused",
            "2025-11-23 - CRITICAL - fatal failure",
            " CRITICAL shutdown imminent",
            "[CRITICAL] out of memory",
        ]:
            assert watcher._detect_log_level(line) == "error", f"Expected 'error' for: {line}"

    def test_warning_markers(self):
        mod = _import_log_watcher()
        watcher, _ = _make_watcher(mod)
        for line in [
            "2025-11-23 - WARNING - disk space low",
            " WARNING deprecated function used",
            "[WARNING] slow query detected",
        ]:
            assert watcher._detect_log_level(line) == "warning", f"Expected 'warning' for: {line}"

    def test_debug_markers(self):
        mod = _import_log_watcher()
        watcher, _ = _make_watcher(mod)
        for line in [
            "2025-11-23 - DEBUG - entering function",
            " DEBUG variable x = 42",
            "[DEBUG] cache miss",
        ]:
            assert watcher._detect_log_level(line) == "debug", f"Expected 'debug' for: {line}"

    def test_info_default(self):
        mod = _import_log_watcher()
        watcher, _ = _make_watcher(mod)
        for line in [
            "2025-11-23 - INFO - server started",
            "Just a plain log line with no markers",
            "",
        ]:
            assert watcher._detect_log_level(line) == "info", f"Expected 'info' for: {line!r}"


# ============================================================================
# _extract_command_info tests
# ============================================================================


class TestExtractCommandInfo:
    """Test command pattern extraction from log lines."""

    def test_drone_started_args(self):
        mod = _import_log_watcher()
        watcher, _ = _make_watcher(mod)
        line = "[drone] Drone started with args: ['close', 'plan', '0098']"
        result = watcher._extract_command_info(line)
        assert result is not None
        assert "drone" in result["command"]
        assert "close" in result["command"]

    def test_flow_creating_plan(self):
        mod = _import_log_watcher()
        watcher, _ = _make_watcher(mod)
        line = "[FLOW] Creating new flow plan"
        result = watcher._extract_command_info(line)
        assert result is not None
        assert "flow create plan" in result["command"]

    def test_flow_closing_plan(self):
        mod = _import_log_watcher()
        watcher, _ = _make_watcher(mod)
        line = "[FLOW] Closing FPLAN-0164"
        result = watcher._extract_command_info(line)
        assert result is not None
        assert "flow close plan" in result["command"]
        assert "0164" in result["command"]

    def test_flow_opening_plan(self):
        mod = _import_log_watcher()
        watcher, _ = _make_watcher(mod)
        line = "[FLOW] Opening FPLAN-0098"
        result = watcher._extract_command_info(line)
        assert result is not None
        assert "flow open plan" in result["command"]
        assert "0098" in result["command"]

    def test_seedgo_audit(self):
        mod = _import_log_watcher()
        watcher, _ = _make_watcher(mod)
        line = "[seedgo] Auditing PRAX branch"
        result = watcher._extract_command_info(line)
        assert result is not None
        assert "seedgo audit" in result["command"]
        assert result["target"] == "PRAX"

    def test_ai_mail_send(self):
        mod = _import_log_watcher()
        watcher, _ = _make_watcher(mod)
        line = "[ai_mail] Sending message to @flow"
        result = watcher._extract_command_info(line)
        assert result is not None
        assert "ai_mail send" in result["command"]
        assert result["target"] == "FLOW"

    def test_ai_mail_inbox(self):
        mod = _import_log_watcher()
        watcher, _ = _make_watcher(mod)
        line = "[ai_mail] checking inbox"
        result = watcher._extract_command_info(line)
        assert result is not None
        assert "ai_mail inbox" in result["command"]

    def test_prax_monitor(self):
        mod = _import_log_watcher()
        watcher, _ = _make_watcher(mod)
        line = "[prax] Starting monitor session"
        result = watcher._extract_command_info(line)
        assert result is not None
        assert "prax monitor" in result["command"]

    def test_prax_status(self):
        mod = _import_log_watcher()
        watcher, _ = _make_watcher(mod)
        line = "[prax] Running status check"
        result = watcher._extract_command_info(line)
        assert result is not None
        assert "prax status" in result["command"]

    def test_backup_snapshot(self):
        mod = _import_log_watcher()
        watcher, _ = _make_watcher(mod)
        line = "[backup] Starting snapshot"
        result = watcher._extract_command_info(line)
        assert result is not None
        assert "backup snapshot" in result["command"]

    def test_caller_attribution_routing(self):
        mod = _import_log_watcher()
        watcher, _ = _make_watcher(mod)
        line = "Routing @flow [CALLER:PRAX] \u2192 create ['.', 'Subject']"
        result = watcher._extract_command_info(line)
        assert result is not None
        assert result["caller"] == "PRAX"
        assert result["target"] == "FLOW"

    def test_executing_command_with_caller(self):
        mod = _import_log_watcher()
        watcher, _ = _make_watcher(mod)
        line = "Executing command [CALLER:SEEDGO]: /path/to/aipass/prax/apps/status.py audit @prax"
        result = watcher._extract_command_info(line)
        assert result is not None
        assert result["caller"] == "SEEDGO"

    def test_non_command_line_returns_none(self):
        mod = _import_log_watcher()
        watcher, _ = _make_watcher(mod)
        line = "2025-11-23 - INFO - Just a normal log line"
        result = watcher._extract_command_info(line)
        assert result is None

    def test_memory_rollover(self):
        mod = _import_log_watcher()
        watcher, _ = _make_watcher(mod)
        line = "[memory] Starting rollover process"
        result = watcher._extract_command_info(line)
        assert result is not None
        assert "memory rollover" in result["command"]

    def test_spawn_create_branch(self):
        mod = _import_log_watcher()
        watcher, _ = _make_watcher(mod)
        line = "[spawn] Creating branch NEWMOD"
        result = watcher._extract_command_info(line)
        assert result is not None
        assert "spawn create branch" in result["command"]
        assert result["target"] == "NEWMOD"

    def test_trigger_fired(self):
        mod = _import_log_watcher()
        watcher, _ = _make_watcher(mod)
        line = "[trigger] Event fired: module_discovered"
        result = watcher._extract_command_info(line)
        assert result is not None
        assert "trigger fire" in result["command"]


# ============================================================================
# _parse_log_message tests
# ============================================================================


class TestParseLogMessage:
    """Test pipe-delimited log line parsing."""

    def test_four_part_format(self):
        mod = _import_log_watcher()
        watcher, _ = _make_watcher(mod)
        line = "[PRAX] 2025-11-23 10:00:00 | prax.status | INFO | Server started successfully"
        result = watcher._parse_log_message(line)
        assert result == "Server started successfully"

    def test_multi_pipe_message(self):
        mod = _import_log_watcher()
        watcher, _ = _make_watcher(mod)
        line = "[PRAX] 2025-11-23 | source | WARNING | First part | second part"
        result = watcher._parse_log_message(line)
        assert result == "First part | second part"

    def test_two_part_format(self):
        mod = _import_log_watcher()
        watcher, _ = _make_watcher(mod)
        line = "source | The actual message"
        result = watcher._parse_log_message(line)
        assert result == "The actual message"

    def test_no_pipe_fallback(self):
        mod = _import_log_watcher()
        watcher, _ = _make_watcher(mod)
        line = "Just a plain line with no pipes"
        result = watcher._parse_log_message(line)
        assert result == "Just a plain line with no pipes"

    def test_strips_whitespace(self):
        mod = _import_log_watcher()
        watcher, _ = _make_watcher(mod)
        line = "  [PRAX] 2025-11-23 | source | INFO | message with spaces   "
        result = watcher._parse_log_message(line)
        assert result == "message with spaces"


# ============================================================================
# start/stop/is_active lifecycle tests
# ============================================================================


class TestLogWatcherLifecycle:
    """Test start_log_watcher, stop_log_watcher, is_log_watcher_active."""

    def test_start_creates_and_starts_observer(self):
        mod = _import_log_watcher()
        mock_queue = MagicMock()
        mock_observer = MagicMock()

        setattr(mod, "_log_observer", None)

        with patch.object(mod, "WatchdogObserver", return_value=mock_observer):
            with patch.object(mod, "get_system_logs_dir", return_value=Path("/fake/logs")):
                result = mod.start_log_watcher(mock_queue)

        assert result is mock_observer
        mock_observer.schedule.assert_called_once()
        mock_observer.start.assert_called_once()

    def test_start_with_polling_mode(self):
        mod = _import_log_watcher()
        mock_queue = MagicMock()
        mock_observer = MagicMock()
        mock_polling_cls = MagicMock(return_value=mock_observer)

        setattr(mod, "_log_observer", None)

        with patch.dict(
            sys.modules,
            {
                "watchdog.observers.polling": MagicMock(PollingObserver=mock_polling_cls),
            },
        ):
            with patch.object(mod, "get_system_logs_dir", return_value=Path("/fake/logs")):
                result = mod.start_log_watcher(mock_queue, use_polling=True)

        assert result is mock_observer
        mock_observer.start.assert_called_once()

    def test_stop_stops_and_clears(self):
        mod = _import_log_watcher()
        mock_obs = MagicMock()
        mock_obs.is_alive.return_value = True
        setattr(mod, "_log_observer", mock_obs)

        mod.stop_log_watcher()

        mock_obs.stop.assert_called_once()
        mock_obs.join.assert_called_once_with(timeout=5.0)
        assert getattr(mod, "_log_observer") is None

    def test_stop_noop_when_not_running(self):
        mod = _import_log_watcher()
        setattr(mod, "_log_observer", None)
        # Should not raise
        mod.stop_log_watcher()

    def test_is_active_true_when_alive(self):
        mod = _import_log_watcher()
        mock_obs = MagicMock()
        mock_obs.is_alive.return_value = True
        setattr(mod, "_log_observer", mock_obs)
        assert mod.is_log_watcher_active() is True

    def test_is_active_false_when_none(self):
        mod = _import_log_watcher()
        setattr(mod, "_log_observer", None)
        assert mod.is_log_watcher_active() is False

    def test_is_active_false_when_dead(self):
        mod = _import_log_watcher()
        mock_obs = MagicMock()
        mock_obs.is_alive.return_value = False
        setattr(mod, "_log_observer", mock_obs)
        assert mod.is_log_watcher_active() is False


# ============================================================================
# initialize_positions tests
# ============================================================================


class TestInitializePositions:
    """Test seek-to-end initialization."""

    def test_initializes_to_end_of_existing_files(self, tmp_path):
        mod = _import_log_watcher()
        watcher, _ = _make_watcher(mod)

        # Create fake log files with known content
        log1 = tmp_path / "prax_flow.log"
        log1.write_text("line 1\nline 2\nline 3\n", encoding="utf-8")
        log2 = tmp_path / "prax_drone.log"
        log2.write_text("short\n", encoding="utf-8")

        with patch.object(mod, "get_system_logs_dir", return_value=tmp_path):
            watcher.initialize_positions()

        # Positions should be set to file sizes
        assert watcher.log_positions[str(log1)] == log1.stat().st_size
        assert watcher.log_positions[str(log2)] == log2.stat().st_size

    def test_handles_nonexistent_log_dir(self, tmp_path):
        mod = _import_log_watcher()
        watcher, _ = _make_watcher(mod)
        nonexistent = tmp_path / "does_not_exist"

        with patch.object(mod, "get_system_logs_dir", return_value=nonexistent):
            # Should not raise
            watcher.initialize_positions()

        assert watcher.log_positions == {}

    def test_ignores_non_log_files(self, tmp_path):
        mod = _import_log_watcher()
        watcher, _ = _make_watcher(mod)

        # Create a .log file and a .txt file
        log_file = tmp_path / "test.log"
        log_file.write_text("content\n", encoding="utf-8")
        txt_file = tmp_path / "test.txt"
        txt_file.write_text("not a log\n", encoding="utf-8")

        with patch.object(mod, "get_system_logs_dir", return_value=tmp_path):
            watcher.initialize_positions()

        assert str(log_file) in watcher.log_positions
        assert str(txt_file) not in watcher.log_positions


# ============================================================================
# ADDITIONAL COVERAGE TESTS
# ============================================================================


class TestGenerateErrorHash:
    """Test _generate_error_hash deduplication helper."""

    def test_returns_8_char_hex(self):
        """Hash should be an 8-character hexadecimal string."""
        mod = _import_log_watcher()
        result = mod._generate_error_hash("mymodule", "something broke")
        assert len(result) == 8
        assert all(c in "0123456789abcdef" for c in result)

    def test_same_input_same_hash(self):
        """Identical module+message should produce identical hashes."""
        mod = _import_log_watcher()
        h1 = mod._generate_error_hash("mod", "error msg")
        h2 = mod._generate_error_hash("mod", "error msg")
        assert h1 == h2

    def test_different_input_different_hash(self):
        """Different inputs should produce different hashes."""
        mod = _import_log_watcher()
        h1 = mod._generate_error_hash("mod_a", "error one")
        h2 = mod._generate_error_hash("mod_b", "error two")
        assert h1 != h2


class TestTriggerImportFallback:
    """Test trigger import fallback when trigger module is unavailable."""

    def test_has_trigger_flag_set(self):
        """HAS_TRIGGER should be set based on trigger import availability."""
        mod = _import_log_watcher()
        # With our mock setup, trigger is available
        assert hasattr(mod, "HAS_TRIGGER")


class TestProcessLogLine:
    """Test _process_log_line dispatching."""

    def test_empty_line_skipped(self):
        """Empty/whitespace lines should be skipped entirely."""
        mod = _import_log_watcher()
        watcher, mock_queue = _make_watcher(mod)

        watcher._process_log_line("PRAX", "   ", "/fake/file.log")
        mock_queue.enqueue.assert_not_called()

    def test_command_line_emits_separator(self):
        """Command lines should emit a command separator, not a log event."""
        mod = _import_log_watcher()
        watcher, mock_queue = _make_watcher(mod)

        with (
            patch.object(
                watcher,
                "_extract_command_info",
                return_value={"command": "test cmd", "caller": None, "target": None},
            ),
            patch.object(watcher, "_emit_command_separator") as mock_sep,
            patch.object(watcher, "_emit_log_event") as mock_log,
        ):
            watcher._process_log_line("PRAX", "some command line", "/f.log")

        mock_sep.assert_called_once()
        mock_log.assert_not_called()

    def test_regular_line_emits_log_event(self):
        """Non-command lines should emit a log event."""
        mod = _import_log_watcher()
        watcher, mock_queue = _make_watcher(mod)

        with (
            patch.object(watcher, "_extract_command_info", return_value=None),
            patch.object(watcher, "_emit_log_event") as mock_log,
        ):
            watcher._process_log_line("PRAX", "normal log line", "/f.log")

        mock_log.assert_called_once()


class TestReadNewContent:
    """Test _read_new_content file tailing."""

    def test_reads_new_content(self, tmp_path):
        """Should read content added after last known position."""
        mod = _import_log_watcher()
        watcher, _ = _make_watcher(mod)

        log_file = tmp_path / "test.log"
        log_file.write_text("old line\n", encoding="utf-8")
        old_size = log_file.stat().st_size
        watcher.log_positions[str(log_file)] = old_size

        # Append new content
        with log_file.open("a", encoding="utf-8") as f:
            f.write("new line\n")

        result = watcher._read_new_content(str(log_file))
        assert result is not None
        assert "new line" in result

    def test_returns_none_when_no_new_content(self, tmp_path):
        """Should return None when file hasn't grown."""
        mod = _import_log_watcher()
        watcher, _ = _make_watcher(mod)

        log_file = tmp_path / "test.log"
        log_file.write_text("existing\n", encoding="utf-8")
        watcher.log_positions[str(log_file)] = log_file.stat().st_size

        result = watcher._read_new_content(str(log_file))
        assert result is None

    def test_resets_position_on_truncation(self, tmp_path):
        """Should reset position to 0 when file is smaller than last pos."""
        mod = _import_log_watcher()
        watcher, _ = _make_watcher(mod)

        log_file = tmp_path / "test.log"
        log_file.write_text("short\n", encoding="utf-8")
        watcher.log_positions[str(log_file)] = 99999  # Way past end

        result = watcher._read_new_content(str(log_file))
        assert result is not None
        assert "short" in result

    def test_returns_none_for_whitespace_only_content(self, tmp_path):
        """Should return None when new content is only whitespace."""
        mod = _import_log_watcher()
        watcher, _ = _make_watcher(mod)

        log_file = tmp_path / "test.log"
        log_file.write_text("initial\n", encoding="utf-8")
        old_size = log_file.stat().st_size
        watcher.log_positions[str(log_file)] = old_size

        # Append only whitespace
        with log_file.open("a", encoding="utf-8") as f:
            f.write("   \n  \n")

        result = watcher._read_new_content(str(log_file))
        assert result is None


class TestOnModified:
    """Test on_modified event handler."""

    def test_processes_valid_log_file(self, tmp_path):
        """Should process a valid log file in the system logs directory."""
        mod = _import_log_watcher()
        watcher, mock_queue = _make_watcher(mod)

        log_file = tmp_path / "prax.log"
        log_file.write_text("line one\n", encoding="utf-8")
        watcher.log_positions[str(log_file)] = 0

        event = MagicMock()
        event.is_directory = False
        event.src_path = str(log_file)

        with (
            patch.object(mod, "get_system_logs_dir", return_value=tmp_path),
            patch.object(mod, "detect_branch_from_log", return_value="PRAX"),
            patch.object(watcher, "_process_log_line") as mock_process,
        ):
            watcher.on_modified(event)

        mock_process.assert_called()

    def test_handles_read_exception(self):
        """Should catch exceptions during log reading."""
        mod = _import_log_watcher()
        watcher, mock_queue = _make_watcher(mod)

        event = MagicMock()
        event.is_directory = False
        event.src_path = "/fake/logs/system/crash.log"

        with (
            patch.object(mod, "get_system_logs_dir", return_value=Path("/fake/logs/system")),
            patch.object(watcher, "_read_new_content", side_effect=OSError("disk error")),
        ):
            # Should not raise
            watcher.on_modified(event)

        mock_queue.enqueue.assert_not_called()


class TestShouldDisplayLog:
    """Test _should_display_log filter."""

    def test_always_returns_true(self):
        """Current implementation shows all log lines."""
        mod = _import_log_watcher()
        watcher, _ = _make_watcher(mod)
        assert watcher._should_display_log("any line") is True
        assert watcher._should_display_log("") is True


class TestMatchFlowCommand:
    """Test _match_flow_command pattern matching."""

    def test_loaded_module_command(self):
        """Should detect flow command from 'Loaded module' line."""
        mod = _import_log_watcher()
        watcher, _ = _make_watcher(mod)
        # Clear any prior flow commands to avoid dedup
        watcher.last_command_per_branch.clear()

        result = watcher._match_flow_command("Loaded module: flow_planner")
        assert result is not None
        assert result["command"] == "flow command"

    def test_loaded_module_suppressed_when_duplicate(self):
        """Should suppress duplicate 'Loaded module' commands."""
        mod = _import_log_watcher()
        watcher, _ = _make_watcher(mod)
        watcher.last_command_per_branch["FLOW"] = "FLOW:flow command"

        result = watcher._match_flow_command("Loaded module: flow_planner")
        assert result is None

    def test_non_flow_line_returns_none(self):
        """Should return None for unrecognized flow lines."""
        mod = _import_log_watcher()
        watcher, _ = _make_watcher(mod)
        result = watcher._match_flow_command("Just a normal log line")
        assert result is None


class TestExtractCommandInfoAdditional:
    """Additional command extraction tests for uncovered patterns."""

    def test_seedgo_checklist_running(self):
        """Should detect seedgo checklist commands."""
        mod = _import_log_watcher()
        watcher, _ = _make_watcher(mod)
        line = "standards_checklist Running full standard check on prax"
        result = watcher._extract_command_info(line)
        assert result is not None
        assert "seedgo checklist" in result["command"]

    def test_backup_versioned(self):
        """Should detect backup versioned commands."""
        mod = _import_log_watcher()
        watcher, _ = _make_watcher(mod)
        line = "[backup] Starting versioned backup"
        result = watcher._extract_command_info(line)
        assert result is not None
        assert "backup versioned" in result["command"]

    def test_backup_sync(self):
        """Should detect backup sync commands."""
        mod = _import_log_watcher()
        watcher, _ = _make_watcher(mod)
        line = "[backup] Running sync operation"
        result = watcher._extract_command_info(line)
        assert result is not None
        assert "backup sync" in result["command"]

    def test_memory_search(self):
        """Should detect memory search commands."""
        mod = _import_log_watcher()
        watcher, _ = _make_watcher(mod)
        line = "[memory] Handling search query for branch status"
        result = watcher._extract_command_info(line)
        assert result is not None
        assert "memory search" in result["command"]

    def test_trigger_triggered(self):
        """Should detect trigger events with 'triggered' keyword."""
        mod = _import_log_watcher()
        watcher, _ = _make_watcher(mod)
        line = "[trigger] Rule triggered: error_threshold"
        result = watcher._extract_command_info(line)
        assert result is not None
        assert "trigger fire" in result["command"]

    def test_ai_mail_send_without_target(self):
        """Should handle ai_mail send without a parseable recipient."""
        mod = _import_log_watcher()
        watcher, _ = _make_watcher(mod)
        line = "[ai_mail] Sending broadcast message"
        result = watcher._extract_command_info(line)
        assert result is not None
        assert "ai_mail send" in result["command"]

    def test_drone_started_without_bracket_prefix(self):
        """Should detect 'Drone started with args' without [drone] prefix."""
        mod = _import_log_watcher()
        watcher, _ = _make_watcher(mod)
        line = "Drone started with args: ['audit', '@prax']"
        result = watcher._extract_command_info(line)
        assert result is not None
        assert "drone" in result["command"]
        assert "audit" in result["command"]


class TestMatchExecutingCommand:
    """Test _match_executing_command pattern matching."""

    def test_returns_none_when_no_cmd_match(self):
        """Should return None when command pattern doesn't match."""
        mod = _import_log_watcher()
        watcher, _ = _make_watcher(mod)
        result = watcher._match_executing_command("Executing something weird")
        assert result is None

    def test_extracts_caller_and_simplifies_path(self):
        """Should extract caller and simplify aipass paths to @branch."""
        mod = _import_log_watcher()
        watcher, _ = _make_watcher(mod)
        line = "Executing command [CALLER:DRONE]: /path/to/aipass/seedgo/apps/audit.py @prax"
        result = watcher._match_executing_command(line)
        assert result is not None
        assert result["caller"] == "DRONE"
        assert result["target"] == "PRAX"

    def test_without_caller(self):
        """Should work without CALLER tag."""
        mod = _import_log_watcher()
        watcher, _ = _make_watcher(mod)
        line = "Executing command: /path/to/aipass/flow run"
        result = watcher._match_executing_command(line)
        assert result is not None
        assert result["caller"] is None


class TestExtractTargetFromCmd:
    """Test _extract_target_from_cmd static method."""

    def test_extracts_at_target(self):
        """Should extract target from @branch pattern."""
        mod = _import_log_watcher()
        result = mod.LogFileWatcher._extract_target_from_cmd("audit @prax")
        assert result == "PRAX"

    def test_extracts_path_target(self):
        """Should extract target from /aipass/branch pattern."""
        mod = _import_log_watcher()
        result = mod.LogFileWatcher._extract_target_from_cmd("/path/to/aipass/seedgo/run.py")
        assert result == "SEEDGO"

    def test_returns_none_when_no_target(self):
        """Should return None when no target pattern matches."""
        mod = _import_log_watcher()
        result = mod.LogFileWatcher._extract_target_from_cmd("plain command")
        assert result is None


class TestEmitCommandSeparator:
    """Test _emit_command_separator event emission."""

    def test_dict_format(self):
        """Should handle dict command_info format."""
        mod = _import_log_watcher()
        watcher, mock_queue = _make_watcher(mod)
        watcher.last_command_per_branch.clear()

        watcher._emit_command_separator("PRAX", {"command": "test cmd", "caller": "DRONE", "target": "FLOW"})
        mock_queue.enqueue.assert_called_once()

    def test_tuple_format(self):
        """Should handle legacy tuple (command, caller) format."""
        mod = _import_log_watcher()
        watcher, mock_queue = _make_watcher(mod)
        watcher.last_command_per_branch.clear()

        watcher._emit_command_separator("PRAX", ("test cmd", "DRONE"))
        mock_queue.enqueue.assert_called_once()

    def test_string_format(self):
        """Should handle plain string command format."""
        mod = _import_log_watcher()
        watcher, mock_queue = _make_watcher(mod)
        watcher.last_command_per_branch.clear()

        watcher._emit_command_separator("PRAX", "test cmd")
        mock_queue.enqueue.assert_called_once()

    def test_deduplication(self):
        """Should skip duplicate consecutive commands for same branch."""
        mod = _import_log_watcher()
        watcher, mock_queue = _make_watcher(mod)
        watcher.last_command_per_branch.clear()

        cmd_info = {"command": "same cmd", "caller": None, "target": None}
        watcher._emit_command_separator("PRAX", cmd_info)
        watcher._emit_command_separator("PRAX", cmd_info)

        assert mock_queue.enqueue.call_count == 1

    def test_target_stored_in_action(self):
        """Should store target in action field when target is provided."""
        mod = _import_log_watcher()
        watcher, mock_queue = _make_watcher(mod)
        watcher.last_command_per_branch.clear()

        watcher._emit_command_separator("PRAX", {"command": "cmd", "caller": None, "target": "FLOW"})

        enqueued_event = mock_queue.enqueue.call_args[0][0]
        assert "FLOW" in enqueued_event.action


class TestEmitLogEvent:
    """Test _emit_log_event event emission."""

    def test_emits_log_event(self):
        """Should create and enqueue a log monitoring event."""
        mod = _import_log_watcher()
        watcher, mock_queue = _make_watcher(mod)

        watcher._emit_log_event("PRAX", "test message", "info")
        mock_queue.enqueue.assert_called_once()

    def test_error_level_fires_trigger(self):
        """Should fire trigger event for ERROR level logs."""
        mod = _import_log_watcher()
        watcher, mock_queue = _make_watcher(mod)

        # Set up trigger mock
        mock_trigger = MagicMock()
        setattr(mod, "HAS_TRIGGER", True)
        setattr(mod, "trigger", mock_trigger)

        watcher._emit_log_event(
            "PRAX",
            "[PRAX] 2025-01-01 | mymodule | ERROR | something broke",
            "error",
            "/fake/prax.log",
        )

        mock_trigger.fire.assert_called_once()
        call_kwargs = mock_trigger.fire.call_args
        assert call_kwargs[0][0] == "error_detected"
        assert call_kwargs[1]["branch"] == "PRAX"

    def test_info_level_does_not_fire_trigger(self):
        """Should not fire trigger for non-error levels."""
        mod = _import_log_watcher()
        watcher, mock_queue = _make_watcher(mod)

        mock_trigger = MagicMock()
        setattr(mod, "HAS_TRIGGER", True)
        setattr(mod, "trigger", mock_trigger)

        watcher._emit_log_event("PRAX", "normal info", "info")
        mock_trigger.fire.assert_not_called()

    def test_trigger_not_fired_when_unavailable(self):
        """Should skip trigger when HAS_TRIGGER is False."""
        mod = _import_log_watcher()
        watcher, mock_queue = _make_watcher(mod)

        setattr(mod, "HAS_TRIGGER", False)
        setattr(mod, "trigger", None)

        # Should not raise
        watcher._emit_log_event("PRAX", "error msg", "error")
        mock_queue.enqueue.assert_called_once()

    def test_error_with_no_log_file_path(self):
        """Should use 'unknown' for log_file when path not provided."""
        mod = _import_log_watcher()
        watcher, mock_queue = _make_watcher(mod)

        mock_trigger = MagicMock()
        setattr(mod, "HAS_TRIGGER", True)
        setattr(mod, "trigger", mock_trigger)

        watcher._emit_log_event("PRAX", "error msg", "error")

        call_kwargs = mock_trigger.fire.call_args[1]
        assert call_kwargs["log_file"] == "unknown"

    def test_error_extracts_module_name_from_pipe_format(self):
        """Should extract module name from pipe-delimited log lines."""
        mod = _import_log_watcher()
        watcher, mock_queue = _make_watcher(mod)

        mock_trigger = MagicMock()
        setattr(mod, "HAS_TRIGGER", True)
        setattr(mod, "trigger", mock_trigger)

        watcher._emit_log_event(
            "PRAX",
            "[PRAX] 2025-01-01 | mymod.handler | ERROR | crash",
            "error",
            "/fake/log.log",
        )

        call_kwargs = mock_trigger.fire.call_args[1]
        assert call_kwargs["module_name"] == "mymod.handler"


class TestStartLogWatcherAdditional:
    """Additional tests for start_log_watcher."""

    def test_stops_existing_observer_before_starting(self):
        """Should stop existing observer if already running."""
        mod = _import_log_watcher()
        mock_queue = MagicMock()
        mock_old_observer = MagicMock()
        mock_old_observer.is_alive.return_value = True
        setattr(mod, "_log_observer", mock_old_observer)

        mock_new_observer = MagicMock()

        with (
            patch.object(mod, "WatchdogObserver", return_value=mock_new_observer),
            patch.object(mod, "get_system_logs_dir", return_value=Path("/fake/logs")),
            patch.object(mod, "stop_log_watcher") as mock_stop,
        ):
            mod.start_log_watcher(mock_queue)

        mock_stop.assert_called_once()


class TestInitializePositionsAdditional:
    """Additional tests for initialize_positions."""

    def test_handles_stat_exception(self, tmp_path):
        """Should handle exceptions when getting file size."""
        mod = _import_log_watcher()
        watcher, _ = _make_watcher(mod)

        log_file = tmp_path / "bad.log"
        log_file.write_text("content\n", encoding="utf-8")

        original_stat = Path.stat

        def failing_stat(self_path, *args, **kwargs):
            """Fail stat only for .log files, not directory existence."""
            if str(self_path).endswith(".log"):
                raise OSError("stat failed")
            return original_stat(self_path, *args, **kwargs)

        with (
            patch.object(mod, "get_system_logs_dir", return_value=tmp_path),
            patch.object(Path, "stat", failing_stat),
        ):
            watcher.initialize_positions()

        assert str(log_file) not in watcher.log_positions


class TestExtractHookInfo:
    """Test _extract_hook_info for structured [HOOKS] log lines."""

    def test_fired_line_extracted(self):
        """Should extract name, action, and key-value details from a fired line."""
        mod = _import_log_watcher()
        watcher, _ = _make_watcher(mod)

        # Real format hooks emits: action is the bare second word, no action= field.
        line = "[HOOKS] cadence fired loader=global turn=35 period=5 offset=0 session=abc12345"
        result = watcher._extract_hook_info(line)
        assert result is not None
        assert result["name"] == "cadence"
        assert result["action"] == "fired"
        assert result["loader"] == "global"
        assert result["turn"] == "35"

    def test_skipped_line_extracted(self):
        """Should extract skipped hook events."""
        mod = _import_log_watcher()
        watcher, _ = _make_watcher(mod)

        line = "[HOOKS] cadence skipped loader=branch turn=37 period=5 offset=0 session=abc12345"
        result = watcher._extract_hook_info(line)
        assert result is not None
        assert result["name"] == "cadence"
        assert result["action"] == "skipped"
        assert result["loader"] == "branch"

    def test_non_hook_line_returns_none(self):
        """Non-hook log lines should return None."""
        mod = _import_log_watcher()
        watcher, _ = _make_watcher(mod)

        result = watcher._extract_hook_info("[FLOW] Creating plan FPLAN-0099")
        assert result is None

    def test_hook_info_line_returns_none(self):
        """A [HOOKS] info/error line (colon after the name) is not a fire/skip event → None."""
        mod = _import_log_watcher()
        watcher, _ = _make_watcher(mod)

        # These are real cadence info lines; the colon stops the action capture.
        assert watcher._extract_hook_info("[HOOKS] cadence: config load failed, using defaults") is None
        assert watcher._extract_hook_info("[HOOKS] cadence: counter reset for post-compact re-injection") is None


class TestEmitHookEvent:
    """Test _emit_hook_event queues properly."""

    def test_fired_event_queued_with_correct_kwargs(self):
        """Fired hook events should pass event_type=hook, level=success to MonitoringEvent."""
        mod = _import_log_watcher()
        watcher, mock_queue = _make_watcher(mod)

        mock_event_cls = MagicMock()
        with patch.object(mod, "MonitoringEvent", mock_event_cls):
            hook_info = {
                "name": "cadence",
                "action": "fired",
                "loader": "global",
                "turn": "35",
                "period": "5",
                "offset": "0",
                "session": "abc12345",
            }
            watcher._emit_hook_event("HOOKS", hook_info)

        mock_event_cls.assert_called_once()
        kwargs = mock_event_cls.call_args[1]
        assert kwargs["event_type"] == "hook"
        assert kwargs["action"] == "fired"
        assert kwargs["level"] == "success"
        assert "cadence:fired" in kwargs["message"]
        assert "loader=global" in kwargs["message"]
        assert "t=35" in kwargs["message"]
        assert "p=5" in kwargs["message"]
        assert "s=abc12345" in kwargs["message"]

    def test_skipped_event_queued_with_info_level(self):
        """Skipped hook events should pass level=info to MonitoringEvent."""
        mod = _import_log_watcher()
        watcher, mock_queue = _make_watcher(mod)

        mock_event_cls = MagicMock()
        with patch.object(mod, "MonitoringEvent", mock_event_cls):
            hook_info = {"name": "cadence", "action": "skipped", "loader": "branch", "turn": "37"}
            watcher._emit_hook_event("HOOKS", hook_info)

        kwargs = mock_event_cls.call_args[1]
        assert kwargs["action"] == "skipped"
        assert kwargs["level"] == "info"

    def test_process_log_line_routes_hook_to_emit(self):
        """Hook lines in _process_log_line should route to _emit_hook_event, not _emit_log_event."""
        mod = _import_log_watcher()
        watcher, mock_queue = _make_watcher(mod)

        with (
            patch.object(watcher, "_emit_hook_event") as mock_hook,
            patch.object(watcher, "_emit_command_separator") as mock_cmd,
            patch.object(watcher, "_emit_log_event") as mock_log,
        ):
            watcher._process_log_line(
                "HOOKS",
                "[HOOKS] cadence fired loader=global turn=35 period=5 offset=0 session=abc",
                "/fake/file.log",
            )

        mock_hook.assert_called_once()
        mock_cmd.assert_not_called()
        mock_log.assert_not_called()

    def test_process_real_pipe_delimited_hook_line(self):
        """Real log lines are pipe-delimited — hook detection must match through the prefix."""
        mod = _import_log_watcher()
        watcher, mock_queue = _make_watcher(mod)

        real_line = (
            "2026-06-09 19:56:04 | captured_cadence | INFO | "
            "[HOOKS] cadence skipped loader=branch turn=18 period=5 offset=0 session=c98a722b"
        )

        with (
            patch.object(watcher, "_emit_hook_event") as mock_hook,
            patch.object(watcher, "_emit_command_separator") as mock_cmd,
            patch.object(watcher, "_emit_log_event") as mock_log,
        ):
            watcher._process_log_line("HOOKS", real_line, "/fake/hooks_cadence.log")

        mock_hook.assert_called_once()
        hook_info = mock_hook.call_args[0][1]
        assert hook_info["name"] == "cadence"
        assert hook_info["action"] == "skipped"
        assert hook_info["loader"] == "branch"
        assert hook_info["turn"] == "18"
        mock_cmd.assert_not_called()
        mock_log.assert_not_called()
