"""Tests for the centralized system_logs watcher (apps/handlers/watchers/log_watcher.py)."""

# =================== META ====================
# Name: test_watchers_log_watcher.py
# Description: Unit tests for centralized system_logs log watcher
# Version: 1.0.0
# Created: 2026-04-03
# Modified: 2026-04-03
# =============================================

import sys
import hashlib
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _mock_infrastructure(monkeypatch):
    """Mock heavy infrastructure imports before watchers/log_watcher loads."""

    mock_logger = MagicMock()
    mock_logger.info = MagicMock()
    mock_logger.warning = MagicMock()

    # -- prax logger (imported as `from aipass.prax import logger`) ----------
    prax_mod = MagicMock()
    prax_mod.logger = mock_logger
    monkeypatch.setitem(sys.modules, "aipass.prax", prax_mod)
    monkeypatch.setitem(sys.modules, "aipass.prax.apps", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.prax.apps.modules", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.prax.apps.modules.logger", MagicMock())

    # -- trigger json handler -----------------------------------------------
    mock_json_handler = MagicMock()
    mock_json_handler.log_operation = MagicMock(return_value=True)
    json_pkg = MagicMock()
    json_pkg.json_handler = mock_json_handler
    monkeypatch.setitem(sys.modules, "aipass.trigger.apps.handlers.json", json_pkg)
    json_mod = MagicMock()
    json_mod.log_operation = mock_json_handler.log_operation
    monkeypatch.setitem(sys.modules, "aipass.trigger.apps.handlers.json.json_handler", json_mod)

    # -- trigger config (TRIGGER_ROOT) --------------------------------------
    from aipass.trigger.apps.config import atomic_write_json

    mock_config = MagicMock()
    mock_config.TRIGGER_ROOT = Path("/tmp/fake_trigger_root")
    mock_config.atomic_write_json = atomic_write_json
    monkeypatch.setitem(sys.modules, "aipass.trigger.apps.config", mock_config)

    # -- trigger core (trigger.fire) ----------------------------------------
    mock_trigger_obj = MagicMock()
    mock_core = MagicMock()
    mock_core.trigger = mock_trigger_obj
    monkeypatch.setitem(sys.modules, "aipass.trigger.apps.modules.core", mock_core)

    # -- watchdog (make it available) ---------------------------------------
    mock_observer_cls = MagicMock()
    mock_observer_mod = MagicMock()
    mock_observer_mod.Observer = mock_observer_cls
    monkeypatch.setitem(sys.modules, "watchdog", MagicMock())
    monkeypatch.setitem(sys.modules, "watchdog.observers", mock_observer_mod)

    mock_events_mod = MagicMock()
    mock_events_mod.FileSystemEventHandler = type("FakeFileSystemEventHandler", (object,), {})
    monkeypatch.setitem(sys.modules, "watchdog.events", mock_events_mod)

    # -- Force re-import so mocks take effect -------------------------------
    monkeypatch.delitem(
        sys.modules,
        "aipass.trigger.apps.handlers.watchers.log_watcher",
        raising=False,
    )


def _import_watchers_lw():
    """Import watchers/log_watcher module fresh (after mocks are in place)."""
    import aipass.trigger.apps.handlers.watchers.log_watcher as wlw

    return wlw


# ---------------------------------------------------------------------------
# Tests -- _generate_error_hash
# ---------------------------------------------------------------------------


class TestGenerateErrorHash:
    """Tests for _generate_error_hash pure function."""

    def test_deterministic(self):
        """Same inputs always produce the same hash."""
        wlw = _import_watchers_lw()
        h1 = wlw._generate_error_hash("mod_a", "something broke")
        h2 = wlw._generate_error_hash("mod_a", "something broke")
        assert h1 == h2

    def test_length_is_8(self):
        """Hash is exactly 8 characters long."""
        wlw = _import_watchers_lw()
        h = wlw._generate_error_hash("module", "message")
        assert len(h) == 8

    def test_matches_md5_prefix(self):
        """Hash matches the first 8 chars of MD5(module:message)."""
        wlw = _import_watchers_lw()
        expected = hashlib.md5("mymod:mymsg".encode()).hexdigest()[:8]
        assert wlw._generate_error_hash("mymod", "mymsg") == expected

    def test_different_inputs_different_hashes(self):
        """Different inputs produce different hashes."""
        wlw = _import_watchers_lw()
        h1 = wlw._generate_error_hash("mod_a", "err one")
        h2 = wlw._generate_error_hash("mod_b", "err two")
        assert h1 != h2


# ---------------------------------------------------------------------------
# Tests -- _detect_branch_from_log
# ---------------------------------------------------------------------------


class TestDetectBranchFromLog:
    """Tests for _detect_branch_from_log."""

    def test_branch_module_pattern(self):
        """seedgo_audit.log returns SEEDGO."""
        wlw = _import_watchers_lw()
        assert wlw._detect_branch_from_log("seedgo_audit.log") == "SEEDGO"

    def test_simple_log(self):
        """simple.log returns SIMPLE."""
        wlw = _import_watchers_lw()
        assert wlw._detect_branch_from_log("simple.log") == "SIMPLE"

    def test_full_path(self):
        """Works with a full path, not just filename."""
        wlw = _import_watchers_lw()
        assert wlw._detect_branch_from_log("/var/logs/trigger_events.log") == "TRIGGER"

    def test_multiple_underscores(self):
        """ai_mail_dispatch.log returns AI (first part before underscore)."""
        wlw = _import_watchers_lw()
        assert wlw._detect_branch_from_log("ai_mail_dispatch.log") == "AI"


# ---------------------------------------------------------------------------
# Tests -- _detect_log_level
# ---------------------------------------------------------------------------


class TestDetectLogLevel:
    """Tests for _detect_log_level."""

    def test_error_dash_format(self):
        """Detects ERROR from dash-separated format."""
        wlw = _import_watchers_lw()
        assert wlw._detect_log_level("2026-01-01 - mod - ERROR - msg") == "error"

    def test_error_space_format(self):
        """Detects ERROR from space-separated format."""
        wlw = _import_watchers_lw()
        assert wlw._detect_log_level("2026-01-01 ERROR something") == "error"

    def test_error_bracket_format(self):
        """Detects ERROR from bracket format [ERROR]."""
        wlw = _import_watchers_lw()
        assert wlw._detect_log_level("[ERROR] something happened") == "error"

    def test_warning(self):
        """Detects WARNING level."""
        wlw = _import_watchers_lw()
        assert wlw._detect_log_level("2026-01-01 - mod - WARNING - msg") == "warning"

    def test_critical_maps_to_error(self):
        """CRITICAL level maps to error."""
        wlw = _import_watchers_lw()
        assert wlw._detect_log_level("2026-01-01 - mod - CRITICAL - msg") == "error"

    def test_debug(self):
        """Detects DEBUG level."""
        wlw = _import_watchers_lw()
        assert wlw._detect_log_level("2026-01-01 - mod - DEBUG - msg") == "debug"

    def test_info_default(self):
        """Lines without a recognized level default to info."""
        wlw = _import_watchers_lw()
        assert wlw._detect_log_level("just a plain log message") == "info"


# ---------------------------------------------------------------------------
# Tests -- _parse_log_message
# ---------------------------------------------------------------------------


class TestParseLogMessage:
    """Tests for _parse_log_message."""

    def test_pipe_format_extracts_message(self):
        """Extracts message from pipe-separated format."""
        wlw = _import_watchers_lw()
        line = "2026-01-01 | mod | ERROR | Connection refused"
        assert wlw._parse_log_message(line) == "Connection refused"

    def test_pipe_format_with_pipes_in_message(self):
        """Handles messages that contain pipe characters."""
        wlw = _import_watchers_lw()
        line = "ts | mod | ERROR | a | b | c"
        assert wlw._parse_log_message(line) == "a | b | c"

    def test_non_pipe_returns_stripped_line(self):
        """Non-pipe line is returned stripped."""
        wlw = _import_watchers_lw()
        assert wlw._parse_log_message("  just a message  ") == "just a message"


# ---------------------------------------------------------------------------
# Tests -- _extract_module_name
# ---------------------------------------------------------------------------


class TestExtractModuleName:
    """Tests for _extract_module_name."""

    def test_pipe_format_extracts_module(self):
        """Extracts module from second pipe-separated field."""
        wlw = _import_watchers_lw()
        line = "2026-01-01 | my_module | ERROR | msg"
        assert wlw._extract_module_name(line) == "my_module"

    def test_non_pipe_returns_unknown(self):
        """Non-pipe line returns 'unknown'."""
        wlw = _import_watchers_lw()
        assert wlw._extract_module_name("no pipes here") == "unknown"


# ---------------------------------------------------------------------------
# Tests -- _should_skip_log
# ---------------------------------------------------------------------------


class TestShouldSkipLog:
    """Tests for _should_skip_log."""

    def test_initialization_line_skipped(self):
        """Initialization noise is skipped."""
        wlw = _import_watchers_lw()
        assert wlw._should_skip_log("Initializing trigger module") is True

    def test_module_initialized_skipped(self):
        """'Module initialized' line is skipped."""
        wlw = _import_watchers_lw()
        assert wlw._should_skip_log("Module initialized successfully") is True

    def test_configuration_loaded_skipped(self):
        """'Configuration loaded' line is skipped."""
        wlw = _import_watchers_lw()
        assert wlw._should_skip_log("Configuration loaded from config.json") is True

    def test_real_error_not_skipped(self):
        """Actual error messages are NOT skipped."""
        wlw = _import_watchers_lw()
        assert wlw._should_skip_log("Database connection failed") is False

    def test_cleanup_zero_skipped(self):
        """'Cleanup completed - Removed 0' noise line is skipped."""
        wlw = _import_watchers_lw()
        assert wlw._should_skip_log("Cleanup completed - Removed 0 entries") is True


# ---------------------------------------------------------------------------
# Tests -- LogFileWatcher._read_new_lines
# ---------------------------------------------------------------------------


class TestLogFileWatcherReadNewLines:
    """Tests for LogFileWatcher._read_new_lines with tmp_path."""

    def test_reads_new_content(self, tmp_path):
        """Reads only new content appended after initial position."""
        wlw = _import_watchers_lw()
        watcher = wlw.LogFileWatcher()

        log_file = tmp_path / "test.log"
        log_file.write_text("initial line\n", encoding="utf-8")
        file_path = str(log_file)

        # Set position to end of initial content
        watcher.log_positions[file_path] = log_file.stat().st_size

        # Append new error content
        with open(log_file, "a", encoding="utf-8") as f:
            f.write("2026-01-01 | mod | ERROR | New error\n")

        watcher._read_new_lines(file_path)

        # Position should have advanced past new content
        assert watcher.log_positions[file_path] == log_file.stat().st_size

    def test_no_change_no_read(self, tmp_path):
        """When file has not changed since last position, nothing is read."""
        wlw = _import_watchers_lw()
        watcher = wlw.LogFileWatcher()

        log_file = tmp_path / "unchanged.log"
        log_file.write_text("line\n", encoding="utf-8")
        file_path = str(log_file)
        watcher.log_positions[file_path] = log_file.stat().st_size

        # Patch _process_log_line to verify it is NOT called
        with patch.object(watcher, "_process_log_line") as mock_proc:
            watcher._read_new_lines(file_path)
            mock_proc.assert_not_called()


# ---------------------------------------------------------------------------
# Tests -- start / stop / is_active
# ---------------------------------------------------------------------------


class TestStartStopActive:
    """Tests for start_log_watcher, stop_log_watcher, is_log_watcher_active."""

    def test_start_returns_none_when_watchdog_unavailable(self):
        """start_log_watcher returns None when WATCHDOG_AVAILABLE is False."""
        wlw = _import_watchers_lw()
        wlw.WATCHDOG_AVAILABLE = False
        assert wlw.start_log_watcher() is None

    def test_start_returns_none_when_dir_missing(self, tmp_path):
        """start_log_watcher returns None when SYSTEM_LOGS_DIR does not exist."""
        wlw = _import_watchers_lw()
        wlw.SYSTEM_LOGS_DIR = tmp_path / "nonexistent"
        assert wlw.start_log_watcher() is None

    def test_is_log_watcher_active_false_when_not_started(self):
        """is_log_watcher_active returns False when no observer is set."""
        wlw = _import_watchers_lw()
        wlw._log_observer = None
        assert wlw.is_log_watcher_active() is False

    def test_is_log_watcher_active_false_when_observer_dead(self):
        """is_log_watcher_active returns False when observer is not alive."""
        wlw = _import_watchers_lw()
        mock_obs = MagicMock()
        mock_obs.is_alive.return_value = False
        wlw._log_observer = mock_obs
        assert wlw.is_log_watcher_active() is False
