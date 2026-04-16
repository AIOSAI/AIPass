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
