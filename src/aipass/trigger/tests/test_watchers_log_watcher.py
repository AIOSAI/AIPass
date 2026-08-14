"""Tests for the centralized system_logs watcher (apps/handlers/watchers/log_watcher.py)."""

# =================== META ====================
# Name: test_watchers_log_watcher.py
# Description: Unit tests for centralized system_logs log watcher
# Version: 1.2.0
# Created: 2026-04-03
# Modified: 2026-08-04
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
# Tests -- LogFileWatcher rotation tail drain
# ---------------------------------------------------------------------------


def _rotate_log(log_file: Path) -> Path:
    """
    Perform a real RotatingFileHandler-style rotation.

    Renames the live log to '<name>.log.1' (inode travels with the rename)
    and creates a fresh empty '<name>.log'.

    Args:
        log_file: Path to the live log file

    Returns:
        Path to the rotated-out backup file
    """
    backup = Path(f"{log_file}.1")
    if backup.exists():
        backup.unlink()
    log_file.rename(backup)
    log_file.write_text("", encoding="utf-8")
    return backup


def _rotate_chain(log_file: Path, backup_count: int = 3) -> Path:
    """
    Perform a real RotatingFileHandler rotation including backup shifting.

    Shifts '<name>.log.N' -> '<name>.log.N+1' (dropping the oldest), renames
    the live log to '<name>.log.1', then creates a fresh empty '<name>.log'.
    Inodes travel with the renames exactly as they do in production.

    Args:
        log_file: Path to the live log file
        backup_count: Number of backups kept (prax uses 3)

    Returns:
        Path to the newest backup file ('<name>.log.1')
    """
    for index in range(backup_count - 1, 0, -1):
        source = Path(f"{log_file}.{index}")
        target = Path(f"{log_file}.{index + 1}")
        if source.exists():
            if target.exists():
                target.unlink()
            source.rename(target)
    backup = Path(f"{log_file}.1")
    if backup.exists():
        backup.unlink()
    log_file.rename(backup)
    log_file.write_text("", encoding="utf-8")
    return backup


def _processed_lines(mock_proc) -> list:
    """Extract the log-line argument from every _process_log_line call."""
    return [call.args[1] for call in mock_proc.call_args_list]


class TestLogFileWatcherRotationDrain:
    """Tests for draining the unread tail of a rotated-out log file."""

    def test_rotation_drains_unread_tail(self, tmp_path):
        """Lines written between last position and rotation ARE processed."""
        wlw = _import_watchers_lw()
        watcher = wlw.LogFileWatcher()

        log_file = tmp_path / "prax_core.log"
        # Bulk of the file is already processed (mirrors a log near its size cap)
        log_file.write_text("2026-08-04 | mod | ERROR | already seen\n" * 20, encoding="utf-8")
        file_path = str(log_file)
        watcher._record_position(file_path, log_file.stat().st_size)

        # Unread tail: written after last position, before rotation
        with open(log_file, "a", encoding="utf-8") as f:
            f.write("2026-08-04 | mod | ERROR | missed one\n")
            f.write("2026-08-04 | mod | ERROR | missed two\n")

        _rotate_log(log_file)
        log_file.write_text("2026-08-04 | mod | ERROR | after rotation\n", encoding="utf-8")

        with patch.object(watcher, "_process_log_line") as mock_proc:
            watcher._read_new_lines(file_path)

        lines = _processed_lines(mock_proc)
        assert any("missed one" in line for line in lines)
        assert any("missed two" in line for line in lines)
        assert any("after rotation" in line for line in lines)
        assert not any("already seen" in line for line in lines)

    def test_drain_uses_branch_and_noise_filter(self, tmp_path):
        """Drained lines get the same branch arg and _should_skip_log filter."""
        wlw = _import_watchers_lw()
        watcher = wlw.LogFileWatcher()

        log_file = tmp_path / "prax_core.log"
        log_file.write_text("header\n", encoding="utf-8")
        file_path = str(log_file)
        watcher._record_position(file_path, log_file.stat().st_size)

        with open(log_file, "a", encoding="utf-8") as f:
            f.write("2026-08-04 | mod | INFO | Module initialized\n")
            f.write("2026-08-04 | mod | ERROR | real tail failure\n")

        _rotate_log(log_file)

        with patch.object(watcher, "_process_log_line") as mock_proc:
            watcher._read_new_lines(file_path)

        lines = _processed_lines(mock_proc)
        assert any("real tail failure" in line for line in lines)
        assert not any("Module initialized" in line for line in lines)
        assert all(call.args[0] == "PRAX" for call in mock_proc.call_args_list)
        assert all(call.args[2] == file_path for call in mock_proc.call_args_list)

    def test_stale_backup_inode_mismatch_not_reprocessed(self, tmp_path):
        """A stale '.log.1' from an earlier rotation is never re-read."""
        wlw = _import_watchers_lw()
        watcher = wlw.LogFileWatcher()

        log_file = tmp_path / "prax_core.log"
        log_file.write_text("old rotation content\n2026-08-04 | mod | ERROR | ancient\n", encoding="utf-8")
        # Earlier rotation happened before we started tracking the live file
        _rotate_log(log_file)

        # Now the live file is a DIFFERENT inode with its own content
        log_file.write_text("2026-08-04 | mod | ERROR | live line one\n", encoding="utf-8")
        file_path = str(log_file)
        watcher._record_position(file_path, log_file.stat().st_size)

        # Live file is truncated (shrinks) but the stale backup still sits there
        log_file.write_text("2026-08-04 | mod | ERROR | fresh\n", encoding="utf-8")
        watcher.log_positions[file_path] = 9999

        with patch.object(watcher, "_process_log_line") as mock_proc:
            watcher._read_new_lines(file_path)

        lines = _processed_lines(mock_proc)
        assert not any("ancient" in line for line in lines)
        assert any("fresh" in line for line in lines)

    def test_missing_backup_file_still_reads_new_file(self, tmp_path):
        """No '.log.1' present: no crash, the new file is still read."""
        wlw = _import_watchers_lw()
        watcher = wlw.LogFileWatcher()

        log_file = tmp_path / "prax_core.log"
        log_file.write_text("2026-08-04 | mod | ERROR | plenty of old content here\n", encoding="utf-8")
        file_path = str(log_file)
        watcher._record_position(file_path, log_file.stat().st_size)

        # Shrink with no backup file at all
        log_file.write_text("2026-08-04 | mod | ERROR | tiny\n", encoding="utf-8")

        with patch.object(watcher, "_process_log_line") as mock_proc:
            watcher._read_new_lines(file_path)

        lines = _processed_lines(mock_proc)
        assert lines == ["2026-08-04 | mod | ERROR | tiny"]
        assert watcher.log_positions[file_path] == log_file.stat().st_size

    def test_in_place_truncation_no_duplicate_processing(self, tmp_path):
        """Truncation in place (same inode) never re-fires the old content."""
        wlw = _import_watchers_lw()
        watcher = wlw.LogFileWatcher()

        log_file = tmp_path / "prax_core.log"
        file_path = str(log_file)
        log_file.write_text("2026-08-04 | mod | ERROR | first pass line\n", encoding="utf-8")

        # A stale backup exists holding a copy of the same text, different inode
        backup = Path(f"{file_path}.1")
        backup.write_text("2026-08-04 | mod | ERROR | first pass line\n", encoding="utf-8")

        watcher._record_position(file_path, log_file.stat().st_size)

        # Truncate in place - inode is unchanged
        inode_before = log_file.stat().st_ino
        with open(log_file, "w", encoding="utf-8") as f:
            f.write("2026-08-04 | mod | ERROR | short\n")
        assert log_file.stat().st_ino == inode_before

        with patch.object(watcher, "_process_log_line") as mock_proc:
            watcher._read_new_lines(file_path)

        lines = _processed_lines(mock_proc)
        assert lines == ["2026-08-04 | mod | ERROR | short"]

    def test_normal_append_never_drains(self, tmp_path):
        """No-overreach guard: an ordinary append never touches the drain path.

        This test passes with and without the fix - it exists to prove the
        drain does not run on the normal (non-shrink) path.
        """
        wlw = _import_watchers_lw()
        watcher = wlw.LogFileWatcher()

        log_file = tmp_path / "prax_core.log"
        log_file.write_text("2026-08-04 | mod | ERROR | first\n", encoding="utf-8")
        file_path = str(log_file)
        watcher.log_positions[file_path] = log_file.stat().st_size

        # A backup with the SAME content exists but must be ignored
        backup = Path(f"{file_path}.1")
        backup.write_text("2026-08-04 | mod | ERROR | backup only\n", encoding="utf-8")

        with open(log_file, "a", encoding="utf-8") as f:
            f.write("2026-08-04 | mod | ERROR | appended\n")

        with patch.object(watcher, "_process_log_line") as mock_proc:
            watcher._read_new_lines(file_path)

        lines = _processed_lines(mock_proc)
        assert lines == ["2026-08-04 | mod | ERROR | appended"]

    def test_repeat_shrink_event_does_not_drain_twice(self, tmp_path):
        """Two events after one rotation drain the tail exactly once."""
        wlw = _import_watchers_lw()
        watcher = wlw.LogFileWatcher()

        log_file = tmp_path / "prax_core.log"
        log_file.write_text("header\n", encoding="utf-8")
        file_path = str(log_file)
        watcher._record_position(file_path, log_file.stat().st_size)

        with open(log_file, "a", encoding="utf-8") as f:
            f.write("2026-08-04 | mod | ERROR | tail line\n")

        # Rotate, leaving the new live file EMPTY (nothing written yet)
        _rotate_log(log_file)

        with patch.object(watcher, "_process_log_line") as mock_proc:
            watcher._read_new_lines(file_path)
            watcher._read_new_lines(file_path)

        lines = _processed_lines(mock_proc)
        assert lines.count("2026-08-04 | mod | ERROR | tail line") == 1

    def test_unknown_inode_skips_drain(self, tmp_path):
        """Position recorded without an inode (old state) disables the drain.

        No-overreach guard: passes with and without the fix - it proves an
        unknown inode degrades to exactly the pre-fix behaviour.
        """
        wlw = _import_watchers_lw()
        watcher = wlw.LogFileWatcher()

        log_file = tmp_path / "prax_core.log"
        log_file.write_text("2026-08-04 | mod | ERROR | tail line\n", encoding="utf-8")
        file_path = str(log_file)
        # Position only - exactly what an older in-memory/on-disk state holds
        watcher.log_positions[file_path] = log_file.stat().st_size

        _rotate_log(log_file)
        log_file.write_text("2026-08-04 | mod | ERROR | new\n", encoding="utf-8")

        with patch.object(watcher, "_process_log_line") as mock_proc:
            watcher._read_new_lines(file_path)

        lines = _processed_lines(mock_proc)
        assert lines == ["2026-08-04 | mod | ERROR | new"]

    def test_rotated_file_smaller_than_position_skipped(self, tmp_path):
        """A backup shorter than the recorded position is not drained."""
        wlw = _import_watchers_lw()
        watcher = wlw.LogFileWatcher()

        log_file = tmp_path / "prax_core.log"
        log_file.write_text("2026-08-04 | mod | ERROR | content\n", encoding="utf-8")
        file_path = str(log_file)
        watcher._record_position(file_path, log_file.stat().st_size)
        # Pretend we were further along than the file ever got
        watcher.log_positions[file_path] = 9999

        _rotate_log(log_file)
        log_file.write_text("2026-08-04 | mod | ERROR | new\n", encoding="utf-8")

        with patch.object(watcher, "_process_log_line") as mock_proc:
            watcher._read_new_lines(file_path)

        lines = _processed_lines(mock_proc)
        assert lines == ["2026-08-04 | mod | ERROR | new"]

    def test_drain_failure_does_not_block_new_file(self, tmp_path):
        """An exception inside the drain never prevents reading the new file."""
        wlw = _import_watchers_lw()
        watcher = wlw.LogFileWatcher()

        log_file = tmp_path / "prax_core.log"
        log_file.write_text("2026-08-04 | mod | ERROR | old content here\n", encoding="utf-8")
        file_path = str(log_file)
        watcher._record_position(file_path, log_file.stat().st_size)

        _rotate_log(log_file)
        log_file.write_text("2026-08-04 | mod | ERROR | new\n", encoding="utf-8")

        with patch.object(watcher, "_drain_rotated_tail", side_effect=RuntimeError("boom")):
            with patch.object(watcher, "_process_log_line") as mock_proc:
                watcher._read_new_lines(file_path)

        lines = _processed_lines(mock_proc)
        assert lines == ["2026-08-04 | mod | ERROR | new"]

    def test_record_position_tracks_inode(self, tmp_path):
        """_record_position stores the current inode alongside the offset."""
        wlw = _import_watchers_lw()
        watcher = wlw.LogFileWatcher()

        log_file = tmp_path / "prax_core.log"
        log_file.write_text("data\n", encoding="utf-8")
        file_path = str(log_file)

        watcher._record_position(file_path, 4)

        assert watcher.log_positions[file_path] == 4
        assert watcher.log_inodes[file_path] == log_file.stat().st_ino


# ---------------------------------------------------------------------------
# Tests -- LogFileWatcher inode-based rotation detection
# ---------------------------------------------------------------------------


def _fresh_lines(count: int) -> list:
    """Build a list of distinct full ERROR lines for the post-rotation file."""
    return [f"2026-08-04 | mod | ERROR | after rotation {i:03d}" for i in range(count)]


class TestLogFileWatcherInodeRotation:
    """Tests for rotation detected by inode and located across the backup chain."""

    def test_rotation_detected_when_new_file_already_grew(self, tmp_path):
        """A fresh log already past the old offset is still detected as rotated.

        The size-only check missed this entirely and seeked into the middle of
        the brand new file, yielding a partial line.
        """
        wlw = _import_watchers_lw()
        watcher = wlw.LogFileWatcher()

        log_file = tmp_path / "prax_core.log"
        log_file.write_text("2026-08-04 | mod | ERROR | already seen\n" * 20, encoding="utf-8")
        file_path = str(log_file)
        watcher._record_position(file_path, log_file.stat().st_size)
        recorded_pos = watcher.log_positions[file_path]

        with open(log_file, "a", encoding="utf-8") as f:
            f.write("2026-08-04 | mod | ERROR | missed one\n")

        _rotate_chain(log_file)

        # New file is LARGER than the recorded offset - there is no shrink to see
        fresh = _fresh_lines(40)
        log_file.write_text("\n".join(fresh) + "\n", encoding="utf-8")
        assert log_file.stat().st_size > recorded_pos

        with patch.object(watcher, "_process_log_line") as mock_proc:
            watcher._read_new_lines(file_path)

        lines = _processed_lines(mock_proc)
        assert any("missed one" in line for line in lines)
        # Read from position 0: every fresh line whole, none dropped, none partial
        assert [line for line in lines if "after rotation" in line] == fresh
        assert not any("already seen" in line for line in lines)
        assert watcher.log_positions[file_path] == log_file.stat().st_size

    def test_rotated_file_found_at_second_backup(self, tmp_path):
        """Two rotations: the tail is drained from '.log.2' and a warning is emitted."""
        wlw = _import_watchers_lw()
        watcher = wlw.LogFileWatcher()

        log_file = tmp_path / "prax_core.log"
        log_file.write_text("header line\n", encoding="utf-8")
        file_path = str(log_file)
        watcher._record_position(file_path, log_file.stat().st_size)

        with open(log_file, "a", encoding="utf-8") as f:
            f.write("2026-08-04 | mod | ERROR | tail from two rotations ago\n")

        tracked_inode = log_file.stat().st_ino
        _rotate_chain(log_file)  # tracked file -> .log.1
        _rotate_chain(log_file)  # tracked file -> .log.2
        assert Path(f"{file_path}.2").stat().st_ino == tracked_inode

        log_file.write_text("2026-08-04 | mod | ERROR | brand new\n", encoding="utf-8")

        with patch.object(wlw, "logger") as mock_logger:
            with patch.object(watcher, "_process_log_line") as mock_proc:
                watcher._read_new_lines(file_path)

        lines = _processed_lines(mock_proc)
        assert any("tail from two rotations ago" in line for line in lines)
        assert any("brand new" in line for line in lines)

        warnings = [str(call.args) for call in mock_logger.warning.call_args_list]
        assert any("not replayed" in warning and ".log.2" in warning for warning in warnings)

    def test_tracked_inode_beyond_chain_reads_new_file_from_zero(self, tmp_path):
        """Inode matching nothing within the chain: nothing drained, new file read whole."""
        wlw = _import_watchers_lw()
        watcher = wlw.LogFileWatcher()

        log_file = tmp_path / "prax_core.log"
        log_file.write_text("header\n", encoding="utf-8")
        file_path = str(log_file)
        watcher._record_position(file_path, log_file.stat().st_size)
        tracked_inode = log_file.stat().st_ino

        with open(log_file, "a", encoding="utf-8") as f:
            f.write("2026-08-04 | mod | ERROR | lost tail\n")

        # Four rotations push the tracked file to '.log.4' - past the depth cap
        for _ in range(4):
            _rotate_chain(log_file, backup_count=5)
        assert Path(f"{file_path}.4").stat().st_ino == tracked_inode

        fresh = _fresh_lines(40)
        log_file.write_text("\n".join(fresh) + "\n", encoding="utf-8")

        with patch.object(watcher, "_process_log_line") as mock_proc:
            watcher._read_new_lines(file_path)

        lines = _processed_lines(mock_proc)
        assert not any("lost tail" in line for line in lines)
        assert lines == fresh
        assert watcher.log_positions[file_path] == log_file.stat().st_size

    def test_in_place_truncation_with_backup_chain_no_drain(self, tmp_path):
        """No-overreach guard: same inode plus a full backup chain never drains.

        Passes with and without the fix - it proves walking the chain did not
        turn an in-place truncation into a false rotation.
        """
        wlw = _import_watchers_lw()
        watcher = wlw.LogFileWatcher()

        log_file = tmp_path / "prax_core.log"
        file_path = str(log_file)
        for name in ("chain three", "chain two", "chain one"):
            log_file.write_text(f"2026-08-04 | mod | ERROR | {name}\n", encoding="utf-8")
            _rotate_chain(log_file)

        log_file.write_text("2026-08-04 | mod | ERROR | live content line\n", encoding="utf-8")
        watcher._record_position(file_path, log_file.stat().st_size)

        inode_before = log_file.stat().st_ino
        with open(log_file, "w", encoding="utf-8") as f:
            f.write("2026-08-04 | mod | ERROR | short\n")
        assert log_file.stat().st_ino == inode_before

        with patch.object(watcher, "_process_log_line") as mock_proc:
            watcher._read_new_lines(file_path)

        lines = _processed_lines(mock_proc)
        assert lines == ["2026-08-04 | mod | ERROR | short"]

    def test_normal_append_with_backup_chain_never_drains(self, tmp_path):
        """No-overreach guard: an append with backups present stays on the normal path.

        Passes with and without the fix - it proves the chain walk only runs
        when the inode actually changed.
        """
        wlw = _import_watchers_lw()
        watcher = wlw.LogFileWatcher()

        log_file = tmp_path / "prax_core.log"
        file_path = str(log_file)
        for name in ("chain three", "chain two", "chain one"):
            log_file.write_text(f"2026-08-04 | mod | ERROR | {name}\n", encoding="utf-8")
            _rotate_chain(log_file)

        log_file.write_text("2026-08-04 | mod | ERROR | first\n", encoding="utf-8")
        watcher._record_position(file_path, log_file.stat().st_size)

        with open(log_file, "a", encoding="utf-8") as f:
            f.write("2026-08-04 | mod | ERROR | appended\n")

        with patch.object(watcher, "_process_log_line") as mock_proc:
            watcher._read_new_lines(file_path)

        lines = _processed_lines(mock_proc)
        assert lines == ["2026-08-04 | mod | ERROR | appended"]

    def test_zero_inode_falls_back_to_size_check(self, tmp_path):
        """No-overreach guard: a recorded inode of 0 is treated as unknown.

        Passes with and without the fix - some Windows filesystems report
        st_ino 0, which must never be trusted as a rotation signal.
        """
        wlw = _import_watchers_lw()
        watcher = wlw.LogFileWatcher()

        log_file = tmp_path / "prax_core.log"
        log_file.write_text("2026-08-04 | mod | ERROR | tail line that is long\n", encoding="utf-8")
        file_path = str(log_file)
        watcher.log_positions[file_path] = log_file.stat().st_size
        watcher.log_inodes[file_path] = 0

        _rotate_chain(log_file)
        log_file.write_text("2026-08-04 | mod | ERROR | new\n", encoding="utf-8")

        with patch.object(watcher, "_process_log_line") as mock_proc:
            watcher._read_new_lines(file_path)

        lines = _processed_lines(mock_proc)
        assert lines == ["2026-08-04 | mod | ERROR | new"]
        assert watcher.log_positions[file_path] == log_file.stat().st_size


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


# ---------------------------------------------------------------------------
# Tests -- on_modified
# ---------------------------------------------------------------------------


class TestWatcherOnModified:
    """Tests for LogFileWatcher.on_modified."""

    def test_skips_directory_events(self):
        wlw = _import_watchers_lw()
        watcher = wlw.LogFileWatcher()
        watcher._read_new_lines = MagicMock()
        event = MagicMock()
        event.is_directory = True
        event.src_path = "/some/dir"
        watcher.on_modified(event)
        watcher._read_new_lines.assert_not_called()

    def test_skips_non_log_files(self):
        wlw = _import_watchers_lw()
        logs_dir = Path("/fake/system_logs")
        wlw.SYSTEM_LOGS_DIR = logs_dir
        watcher = wlw.LogFileWatcher()
        watcher._read_new_lines = MagicMock()
        event = MagicMock()
        event.is_directory = False
        # Use str(Path(...)) so separator matches SYSTEM_LOGS_DIR on all platforms
        event.src_path = str(logs_dir / "data.txt")
        watcher.on_modified(event)
        watcher._read_new_lines.assert_not_called()

    def test_skips_files_outside_system_logs(self):
        wlw = _import_watchers_lw()
        wlw.SYSTEM_LOGS_DIR = Path("/fake/system_logs")
        watcher = wlw.LogFileWatcher()
        watcher._read_new_lines = MagicMock()
        event = MagicMock()
        event.is_directory = False
        event.src_path = str(Path("/other/place/app.log"))
        watcher.on_modified(event)
        watcher._read_new_lines.assert_not_called()

    def test_processes_valid_log_file(self):
        wlw = _import_watchers_lw()
        logs_dir = Path("/fake/system_logs")
        wlw.SYSTEM_LOGS_DIR = logs_dir
        watcher = wlw.LogFileWatcher()
        watcher._read_new_lines = MagicMock()
        event = MagicMock()
        event.is_directory = False
        event.src_path = str(logs_dir / "app.log")
        watcher.on_modified(event)
        watcher._read_new_lines.assert_called_once_with(str(logs_dir / "app.log"))

    def test_handles_read_exception(self):
        wlw = _import_watchers_lw()
        logs_dir = Path("/fake/system_logs")
        wlw.SYSTEM_LOGS_DIR = logs_dir
        watcher = wlw.LogFileWatcher()
        watcher._read_new_lines = MagicMock(side_effect=IOError("disk error"))
        event = MagicMock()
        event.is_directory = False
        event.src_path = str(logs_dir / "app.log")
        watcher.on_modified(event)


# ---------------------------------------------------------------------------
# Tests -- initialize_positions
# ---------------------------------------------------------------------------


class TestWatcherInitializePositions:
    """Tests for LogFileWatcher.initialize_positions."""

    def test_initializes_to_eof(self, tmp_path):
        wlw = _import_watchers_lw()
        sys_logs = tmp_path / "system_logs"
        sys_logs.mkdir()
        wlw.SYSTEM_LOGS_DIR = sys_logs
        log_file = sys_logs / "app.log"
        log_file.write_text("test data\n")
        watcher = wlw.LogFileWatcher()
        watcher.initialize_positions()
        assert watcher.log_positions[str(log_file)] == log_file.stat().st_size

    def test_initializes_inodes(self, tmp_path):
        """Inodes are recorded alongside positions at startup."""
        wlw = _import_watchers_lw()
        sys_logs = tmp_path / "system_logs"
        sys_logs.mkdir()
        wlw.SYSTEM_LOGS_DIR = sys_logs
        log_file = sys_logs / "app.log"
        log_file.write_text("test data\n")
        watcher = wlw.LogFileWatcher()
        watcher.initialize_positions()
        assert watcher.log_inodes[str(log_file)] == log_file.stat().st_ino

    def test_handles_missing_dir(self, tmp_path):
        wlw = _import_watchers_lw()
        wlw.SYSTEM_LOGS_DIR = tmp_path / "nonexistent"
        watcher = wlw.LogFileWatcher()
        watcher.initialize_positions()
        assert len(watcher.log_positions) == 0

    def test_multiple_files(self, tmp_path):
        wlw = _import_watchers_lw()
        sys_logs = tmp_path / "system_logs"
        sys_logs.mkdir()
        wlw.SYSTEM_LOGS_DIR = sys_logs
        f1 = sys_logs / "a.log"
        f2 = sys_logs / "b.log"
        f1.write_text("aaa")
        f2.write_text("bbbbb")
        watcher = wlw.LogFileWatcher()
        watcher.initialize_positions()
        assert watcher.log_positions[str(f1)] == 3
        assert watcher.log_positions[str(f2)] == 5

    def test_ignores_non_log_files(self, tmp_path):
        wlw = _import_watchers_lw()
        sys_logs = tmp_path / "system_logs"
        sys_logs.mkdir()
        wlw.SYSTEM_LOGS_DIR = sys_logs
        (sys_logs / "data.txt").write_text("not a log")
        (sys_logs / "real.log").write_text("log data")
        watcher = wlw.LogFileWatcher()
        watcher.initialize_positions()
        assert len(watcher.log_positions) == 1


# ---------------------------------------------------------------------------
# system_logs ownership — the branch watcher is the sole owner
# ---------------------------------------------------------------------------


class TestSystemLogsOwnership:
    """Patrick's ruling (2026-08-14): one owner for system_logs, not two.

    Both watchers used to register the directory, so one condition minted two
    escalation signatures with different attribution — the branch watcher
    resolving the owning branch, this watcher reporting UNKNOWN. Measured cost:
    4 of 14 digests in 24h were the same condition twice.
    """

    def test_start_declines_even_when_it_could_start(self, tmp_path, monkeypatch):
        """Watchdog available and the directory present — still declines.

        The two pre-existing None returns are inability. This one is a
        deliberate refusal, so it has to be proven under conditions where the
        old code WOULD have started an observer.
        """
        wlw = _import_watchers_lw()
        wlw.WATCHDOG_AVAILABLE = True
        wlw.SYSTEM_LOGS_DIR = tmp_path
        (tmp_path / "hooks_edit_gate.log").write_text("x", encoding="utf-8")

        scheduled = MagicMock()
        monkeypatch.setattr(wlw, "WatchdogObserver", MagicMock(return_value=scheduled))

        assert wlw.start_log_watcher() is None
        scheduled.schedule.assert_not_called()
        scheduled.start.assert_not_called()

    def test_start_leaves_no_observer_behind(self, tmp_path, monkeypatch):
        """Declining must not park a live observer in module state."""
        wlw = _import_watchers_lw()
        wlw.WATCHDOG_AVAILABLE = True
        wlw.SYSTEM_LOGS_DIR = tmp_path
        wlw._log_observer = None
        monkeypatch.setattr(wlw, "WatchdogObserver", MagicMock())

        wlw.start_log_watcher()

        assert wlw._log_observer is None
        assert wlw.is_log_watcher_active() is False

    def test_owner_is_named_in_module_state(self):
        """The ruling is readable from the code, not just from a commit."""
        wlw = _import_watchers_lw()
        assert wlw.SYSTEM_LOGS_OWNER == "branch_log_events"
