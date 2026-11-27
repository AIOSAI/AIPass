# =================== META ====================
# Name: test_watchers_log_watcher.py
# Description: Unit tests for centralized system_logs log watcher
# Version: 1.3.1
# Created: 2026-04-03
# Modified: 2026-11-22
# =============================================

"""Tests for the centralized system_logs watcher (apps/handlers/watchers/log_watcher.py)."""

# The declared pass — what is NOT tested here, and what covers it instead:
# sentry: no-test-needed(covered_elsewhere) — the live system_logs observer: test_branch_log_events.py
# sentry: no-test-needed(external) — WatchdogObserver's event delivery is the watchdog package's

import hashlib
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import aipass.trigger.apps.handlers.error_registry as error_registry
import aipass.trigger.apps.handlers.watchers.log_watcher as wlw
import aipass.trigger.apps.modules.core as trigger_core
from aipass.prax import get_system_logs_dir

# Fixtures swap SYSTEM_LOGS_DIR and AIPASS_TEST_LOG_DIR per test; both sides are read at import, as the watcher's was.
_SYSTEM_LOGS_AT_IMPORT = wlw.SYSTEM_LOGS_DIR
_PRAX_SYSTEM_LOGS_AT_IMPORT = get_system_logs_dir()


@pytest.fixture(autouse=True)
def _mock_infrastructure(monkeypatch, tmp_path):
    """Replace every door the watcher opens onto live state, on the real modules.

    monkeypatch also undoes tests that assign ``wlw.SYSTEM_LOGS_DIR`` or ``wlw._log_observer``."""
    mock_logger = MagicMock()
    monkeypatch.setattr(wlw, "logger", mock_logger)

    # log_operation appends to the LIVE trigger logs/.
    mock_json_handler = MagicMock()
    mock_json_handler.log_operation = MagicMock(return_value=True)
    monkeypatch.setattr(wlw, "json_handler", mock_json_handler)

    # SYSTEM_LOGS_DIR is prax's answer at import: the LIVE system_logs outside pytest.
    monkeypatch.setattr(wlw, "SYSTEM_LOGS_DIR", tmp_path / "system_logs")

    # The lazy `from ... import report` reads the attribute at call time; left real,
    # an ERROR line writes a row into the LIVE registry.
    monkeypatch.setattr(error_registry, "report", MagicMock(return_value={}))

    # Never the live bus that would run medic's handlers.
    monkeypatch.setattr(trigger_core, "trigger", MagicMock())

    monkeypatch.setattr(wlw, "_log_observer", None)


class TestSystemLogsFolder:
    """The watcher reads the folder prax serves, never one counted up from this file."""

    def test_the_watcher_reads_prax_system_logs_folder_not_a_climb(self):
        assert _SYSTEM_LOGS_AT_IMPORT == _PRAX_SYSTEM_LOGS_AT_IMPORT


class TestGenerateErrorHash:
    """Tests for generate_error_hash pure function."""

    def test_deterministic(self):
        """Same inputs always produce the same hash."""
        h1 = wlw.generate_error_hash("mod_a", "something broke")
        h2 = wlw.generate_error_hash("mod_a", "something broke")
        assert h1 == h2

    def test_length_is_8(self):
        """Hash is exactly 8 characters long."""
        h = wlw.generate_error_hash("module", "message")
        assert len(h) == 8

    def test_matches_md5_prefix(self):
        """Hash matches the first 8 chars of MD5(module:message)."""
        expected = hashlib.md5("mymod:mymsg".encode()).hexdigest()[:8]
        assert wlw.generate_error_hash("mymod", "mymsg") == expected

    def test_different_inputs_different_hashes(self):
        """Different inputs produce different hashes."""
        h1 = wlw.generate_error_hash("mod_a", "err one")
        h2 = wlw.generate_error_hash("mod_b", "err two")
        assert h1 != h2


class TestDetectBranchFromLog:
    """Tests for detect_branch_from_log."""

    def test_branch_module_pattern(self):
        """sentry_audit.log returns SENTRY."""
        assert wlw.detect_branch_from_log("sentry_audit.log") == "sentry"

    def test_simple_log(self):
        """simple.log returns SIMPLE."""
        assert wlw.detect_branch_from_log("simple.log") == "simple"

    def test_full_path(self, tmp_path):
        """Works with a full path, not just filename."""
        assert wlw.detect_branch_from_log(str(tmp_path / "logs" / "trigger_events.log")) == "trigger"

    def test_multiple_underscores(self):
        """ai_mail_dispatch.log returns AI (first part before underscore)."""
        assert wlw.detect_branch_from_log("ai_mail_dispatch.log") == "ai"


class TestDetectLogLevel:
    """Tests for detect_log_level."""

    def test_error_dash_format(self):
        """Detects ERROR from dash-separated format."""
        assert wlw.detect_log_level("2026-01-01 - mod - ERROR - msg") == "error"

    def test_error_space_format(self):
        """Detects ERROR from space-separated format."""
        assert wlw.detect_log_level("2026-01-01 ERROR something") == "error"

    def test_error_bracket_format(self):
        """Detects ERROR from bracket format [ERROR]."""
        assert wlw.detect_log_level("[ERROR] something happened") == "error"

    def test_warning(self):
        """Detects WARNING level."""
        assert wlw.detect_log_level("2026-01-01 - mod - WARNING - msg") == "warning"

    def test_critical_maps_to_error(self):
        """CRITICAL level maps to error."""
        assert wlw.detect_log_level("2026-01-01 - mod - CRITICAL - msg") == "error"

    def test_debug(self):
        """Detects DEBUG level."""
        assert wlw.detect_log_level("2026-01-01 - mod - DEBUG - msg") == "debug"

    def test_info_default(self):
        """Lines without a recognized level default to info."""
        assert wlw.detect_log_level("just a plain log message") == "info"


class TestParseLogMessage:
    """Tests for parse_log_message."""

    def test_pipe_format_extracts_message(self):
        """Extracts message from pipe-separated format."""
        line = "2026-01-01 | mod | ERROR | Connection refused"
        assert wlw.parse_log_message(line) == "Connection refused"

    def test_pipe_format_with_pipes_in_message(self):
        """Handles messages that contain pipe characters."""
        line = "ts | mod | ERROR | a | b | c"
        assert wlw.parse_log_message(line) == "a | b | c"

    def test_non_pipe_returns_stripped_line(self):
        """Non-pipe line is returned stripped."""
        assert wlw.parse_log_message("  just a message  ") == "just a message"


class TestExtractModuleName:
    """Tests for extract_module_name."""

    def test_pipe_format_extracts_module(self):
        """Extracts module from second pipe-separated field."""
        line = "2026-01-01 | my_module | ERROR | msg"
        assert wlw.extract_module_name(line) == "my_module"

    def test_non_pipe_returns_unknown(self):
        """Non-pipe line returns 'unknown'."""
        assert wlw.extract_module_name("no pipes here") == "unknown"


class TestShouldSkipLog:
    """Tests for should_skip_log."""

    def test_initialization_line_skipped(self):
        """Initialization noise is skipped."""
        assert wlw.should_skip_log("Initializing trigger module") is True

    def test_module_initialized_skipped(self):
        """'Module initialized' line is skipped."""
        assert wlw.should_skip_log("Module initialized successfully") is True

    def test_configuration_loaded_skipped(self):
        """'Configuration loaded' line is skipped."""
        assert wlw.should_skip_log("Configuration loaded from config.json") is True

    def test_real_error_not_skipped(self):
        """Actual error messages are NOT skipped."""
        assert wlw.should_skip_log("Database connection failed") is False

    def test_cleanup_zero_skipped(self):
        """'Cleanup completed - Removed 0' noise line is skipped."""
        assert wlw.should_skip_log("Cleanup completed - Removed 0 entries") is True


class TestLogFileWatcherReadNewLines:
    """Tests for LogFileWatcher._read_new_lines with tmp_path."""

    def test_reads_new_content(self, tmp_path):
        """Reads only new content appended after initial position."""
        watcher = wlw.LogFileWatcher()

        log_file = tmp_path / "test.log"
        log_file.write_text("initial line\n", encoding="utf-8")
        file_path = str(log_file)

        watcher.log_positions[file_path] = log_file.stat().st_size

        with open(log_file, "a", encoding="utf-8") as f:
            f.write("2026-01-01 | mod | ERROR | New error\n")

        watcher._read_new_lines(file_path)

        assert watcher.log_positions[file_path] == log_file.stat().st_size

    def test_no_change_no_read(self, tmp_path):
        """When file has not changed since last position, nothing is read."""
        watcher = wlw.LogFileWatcher()

        log_file = tmp_path / "unchanged.log"
        log_file.write_text("line\n", encoding="utf-8")
        file_path = str(log_file)
        watcher.log_positions[file_path] = log_file.stat().st_size

        with patch.object(watcher, "_process_log_line") as mock_proc:
            watcher._read_new_lines(file_path)
            mock_proc.assert_not_called()


def _rotate_log(log_file: Path) -> Path:
    """
    Perform a real RotatingFileHandler-style rotation."""
    backup = Path(f"{log_file}.1")
    if backup.exists():
        backup.unlink()
    log_file.rename(backup)
    log_file.write_text("", encoding="utf-8")
    return backup


def _rotate_chain(log_file: Path, backup_count: int = 3) -> Path:
    """
    Perform a real RotatingFileHandler rotation including backup shifting."""
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
        watcher = wlw.LogFileWatcher()

        log_file = tmp_path / "prax_core.log"
        log_file.write_text("2026-08-04 | mod | ERROR | already seen\n" * 20, encoding="utf-8")
        file_path = str(log_file)
        watcher._record_position(file_path, log_file.stat().st_size)

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
        """Drained lines get the same branch arg and should_skip_log filter."""
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
        assert all(call.args[0] == "prax" for call in mock_proc.call_args_list)
        assert all(call.args[2] == file_path for call in mock_proc.call_args_list)

    def test_stale_backup_inode_mismatch_not_reprocessed(self, tmp_path):
        """A stale '.log.1' from an earlier rotation is never re-read."""
        watcher = wlw.LogFileWatcher()

        log_file = tmp_path / "prax_core.log"
        log_file.write_text("old rotation content\n2026-08-04 | mod | ERROR | ancient\n", encoding="utf-8")
        _rotate_log(log_file)

        log_file.write_text("2026-08-04 | mod | ERROR | live line one\n", encoding="utf-8")
        file_path = str(log_file)
        watcher._record_position(file_path, log_file.stat().st_size)

        log_file.write_text("2026-08-04 | mod | ERROR | fresh\n", encoding="utf-8")
        watcher.log_positions[file_path] = 9999

        with patch.object(watcher, "_process_log_line") as mock_proc:
            watcher._read_new_lines(file_path)

        lines = _processed_lines(mock_proc)
        assert not any("ancient" in line for line in lines)
        assert any("fresh" in line for line in lines)

    def test_missing_backup_file_still_reads_new_file(self, tmp_path):
        """No '.log.1' present: no crash, the new file is still read."""
        watcher = wlw.LogFileWatcher()

        log_file = tmp_path / "prax_core.log"
        log_file.write_text("2026-08-04 | mod | ERROR | plenty of old content here\n", encoding="utf-8")
        file_path = str(log_file)
        watcher._record_position(file_path, log_file.stat().st_size)

        log_file.write_text("2026-08-04 | mod | ERROR | tiny\n", encoding="utf-8")

        with patch.object(watcher, "_process_log_line") as mock_proc:
            watcher._read_new_lines(file_path)

        lines = _processed_lines(mock_proc)
        assert lines == ["2026-08-04 | mod | ERROR | tiny"]
        assert watcher.log_positions[file_path] == log_file.stat().st_size

    def test_in_place_truncation_no_duplicate_processing(self, tmp_path):
        """Truncation in place (same inode) never re-fires the old content."""
        watcher = wlw.LogFileWatcher()

        log_file = tmp_path / "prax_core.log"
        file_path = str(log_file)
        log_file.write_text("2026-08-04 | mod | ERROR | first pass line\n", encoding="utf-8")

        backup = Path(f"{file_path}.1")
        backup.write_text("2026-08-04 | mod | ERROR | first pass line\n", encoding="utf-8")

        watcher._record_position(file_path, log_file.stat().st_size)

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

        Passes with and without the fix: the drain never runs on the non-shrink path."""
        watcher = wlw.LogFileWatcher()

        log_file = tmp_path / "prax_core.log"
        log_file.write_text("2026-08-04 | mod | ERROR | first\n", encoding="utf-8")
        file_path = str(log_file)
        watcher.log_positions[file_path] = log_file.stat().st_size

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
        watcher = wlw.LogFileWatcher()

        log_file = tmp_path / "prax_core.log"
        log_file.write_text("header\n", encoding="utf-8")
        file_path = str(log_file)
        watcher._record_position(file_path, log_file.stat().st_size)

        with open(log_file, "a", encoding="utf-8") as f:
            f.write("2026-08-04 | mod | ERROR | tail line\n")

        _rotate_log(log_file)

        with patch.object(watcher, "_process_log_line") as mock_proc:
            watcher._read_new_lines(file_path)
            watcher._read_new_lines(file_path)

        lines = _processed_lines(mock_proc)
        assert lines.count("2026-08-04 | mod | ERROR | tail line") == 1

    def test_unknown_inode_skips_drain(self, tmp_path):
        """Position recorded without an inode (old state) disables the drain.

        Passes with and without the fix: an unknown inode degrades to the pre-fix behaviour."""
        watcher = wlw.LogFileWatcher()

        log_file = tmp_path / "prax_core.log"
        log_file.write_text("2026-08-04 | mod | ERROR | tail line\n", encoding="utf-8")
        file_path = str(log_file)
        watcher.log_positions[file_path] = log_file.stat().st_size

        _rotate_log(log_file)
        log_file.write_text("2026-08-04 | mod | ERROR | new\n", encoding="utf-8")

        with patch.object(watcher, "_process_log_line") as mock_proc:
            watcher._read_new_lines(file_path)

        lines = _processed_lines(mock_proc)
        assert lines == ["2026-08-04 | mod | ERROR | new"]

    def test_rotated_file_smaller_than_position_skipped(self, tmp_path):
        """A backup shorter than the recorded position is not drained."""
        watcher = wlw.LogFileWatcher()

        log_file = tmp_path / "prax_core.log"
        log_file.write_text("2026-08-04 | mod | ERROR | content\n", encoding="utf-8")
        file_path = str(log_file)
        watcher._record_position(file_path, log_file.stat().st_size)
        watcher.log_positions[file_path] = 9999

        _rotate_log(log_file)
        log_file.write_text("2026-08-04 | mod | ERROR | new\n", encoding="utf-8")

        with patch.object(watcher, "_process_log_line") as mock_proc:
            watcher._read_new_lines(file_path)

        lines = _processed_lines(mock_proc)
        assert lines == ["2026-08-04 | mod | ERROR | new"]

    def test_drain_failure_does_not_block_new_file(self, tmp_path):
        """An exception inside the drain never prevents reading the new file."""
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
        watcher = wlw.LogFileWatcher()

        log_file = tmp_path / "prax_core.log"
        log_file.write_text("data\n", encoding="utf-8")
        file_path = str(log_file)

        watcher._record_position(file_path, 4)

        assert watcher.log_positions[file_path] == 4
        assert watcher.log_inodes[file_path] == log_file.stat().st_ino


def _fresh_lines(count: int) -> list:
    """Build a list of distinct full ERROR lines for the post-rotation file."""
    return [f"2026-08-04 | mod | ERROR | after rotation {i:03d}" for i in range(count)]


class TestLogFileWatcherInodeRotation:
    """Tests for rotation detected by inode and located across the backup chain."""

    def test_rotation_detected_when_new_file_already_grew(self, tmp_path):
        """A fresh log already past the old offset is still detected as rotated.

        A size-only check seeks into the middle of the new file and yields a partial line."""
        watcher = wlw.LogFileWatcher()

        log_file = tmp_path / "prax_core.log"
        log_file.write_text("2026-08-04 | mod | ERROR | already seen\n" * 20, encoding="utf-8")
        file_path = str(log_file)
        watcher._record_position(file_path, log_file.stat().st_size)
        recorded_pos = watcher.log_positions[file_path]

        with open(log_file, "a", encoding="utf-8") as f:
            f.write("2026-08-04 | mod | ERROR | missed one\n")

        _rotate_chain(log_file)

        fresh = _fresh_lines(40)
        log_file.write_text("\n".join(fresh) + "\n", encoding="utf-8")
        assert log_file.stat().st_size > recorded_pos

        with patch.object(watcher, "_process_log_line") as mock_proc:
            watcher._read_new_lines(file_path)

        lines = _processed_lines(mock_proc)
        assert any("missed one" in line for line in lines)
        assert [line for line in lines if "after rotation" in line] == fresh
        assert not any("already seen" in line for line in lines)
        assert watcher.log_positions[file_path] == log_file.stat().st_size

    def test_rotated_file_found_at_second_backup(self, tmp_path):
        """Two rotations: the tail is drained from '.log.2' and a warning is emitted."""
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

    def test_the_chain_depth_is_prax_backup_count_read_now(self, tmp_path, monkeypatch):
        """Pins the hardcoded depth of 3: prax keeping 5 backups left a tail at '.log.4' unread."""
        monkeypatch.setattr(wlw, "log_backup_count", lambda: 5)
        watcher = wlw.LogFileWatcher()
        log_file = tmp_path / "prax_core.log"
        log_file.write_text("header\n", encoding="utf-8")
        file_path = str(log_file)
        watcher._record_position(file_path, log_file.stat().st_size)
        with open(log_file, "a", encoding="utf-8") as f:
            f.write("2026-08-04 | mod | ERROR | tail four rotations back\n")
        for _ in range(4):
            _rotate_chain(log_file, backup_count=5)
        log_file.write_text("\n".join(_fresh_lines(2)) + "\n", encoding="utf-8")

        with patch.object(watcher, "_process_log_line") as mock_proc:
            watcher._read_new_lines(file_path)

        assert any("tail four rotations back" in line for line in _processed_lines(mock_proc))

    def test_tracked_inode_beyond_chain_reads_new_file_from_zero(self, tmp_path, monkeypatch):
        """Inode matching nothing within the chain: nothing drained, new file read whole."""
        monkeypatch.setattr(wlw, "log_backup_count", lambda: 3)
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
        """No-overreach guard: same inode plus a full backup chain never drains."""
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
        """No-overreach guard: an append with backups present stays on the normal path."""
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

        An st_ino of 0 must never read as a rotation."""
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


class TestStartStopActive:
    """Tests for start_log_watcher, stop_log_watcher, is_log_watcher_active."""

    def test_start_returns_none_when_dir_missing(self, tmp_path, monkeypatch):
        """start_log_watcher returns None when SYSTEM_LOGS_DIR does not exist."""
        monkeypatch.setattr(wlw, "SYSTEM_LOGS_DIR", tmp_path / "nonexistent")
        assert wlw.start_log_watcher() is None

    def test_is_log_watcher_active_false_when_not_started(self, monkeypatch):
        """is_log_watcher_active returns False when no observer is set."""
        monkeypatch.setattr(wlw, "_log_observer", None)
        assert wlw.is_log_watcher_active() is False

    def test_is_log_watcher_active_false_when_observer_dead(self, monkeypatch):
        """is_log_watcher_active returns False when observer is not alive."""
        mock_obs = MagicMock()
        mock_obs.is_alive.return_value = False
        monkeypatch.setattr(wlw, "_log_observer", mock_obs)
        assert wlw.is_log_watcher_active() is False


class TestWatcherOnModified:
    """Tests for LogFileWatcher.on_modified."""

    def test_skips_directory_events(self):
        watcher = wlw.LogFileWatcher()
        watcher._read_new_lines = MagicMock()
        event = MagicMock()
        event.is_directory = True
        event.src_path = "/some/dir"
        watcher.on_modified(event)
        watcher._read_new_lines.assert_not_called()

    def test_skips_non_log_files(self, monkeypatch, tmp_path):
        logs_dir = tmp_path / "system_logs"
        monkeypatch.setattr(wlw, "SYSTEM_LOGS_DIR", logs_dir)
        watcher = wlw.LogFileWatcher()
        watcher._read_new_lines = MagicMock()
        event = MagicMock()
        event.is_directory = False
        event.src_path = str(logs_dir / "data.txt")
        watcher.on_modified(event)
        watcher._read_new_lines.assert_not_called()

    def test_skips_files_outside_system_logs(self, monkeypatch, tmp_path):
        monkeypatch.setattr(wlw, "SYSTEM_LOGS_DIR", tmp_path / "system_logs")
        watcher = wlw.LogFileWatcher()
        watcher._read_new_lines = MagicMock()
        event = MagicMock()
        event.is_directory = False
        event.src_path = str(tmp_path / "other" / "place" / "app.log")
        watcher.on_modified(event)
        watcher._read_new_lines.assert_not_called()

    def test_processes_valid_log_file(self, monkeypatch, tmp_path):
        logs_dir = tmp_path / "system_logs"
        monkeypatch.setattr(wlw, "SYSTEM_LOGS_DIR", logs_dir)
        watcher = wlw.LogFileWatcher()
        watcher._read_new_lines = MagicMock()
        event = MagicMock()
        event.is_directory = False
        event.src_path = str(logs_dir / "app.log")
        watcher.on_modified(event)
        watcher._read_new_lines.assert_called_once_with(str(logs_dir / "app.log"))

    def test_a_read_failure_is_reported_and_costs_only_that_event(self, monkeypatch, tmp_path):
        """IOError is swallowed — but it is named, and the watcher keeps watching.

        This observer feeds error_detected; a silent swallow leaves system_logs unread."""
        logs_dir = tmp_path / "system_logs"
        monkeypatch.setattr(wlw, "SYSTEM_LOGS_DIR", logs_dir)
        watcher = wlw.LogFileWatcher()
        watcher._read_new_lines = MagicMock(side_effect=IOError("disk error"))
        event = MagicMock()
        event.is_directory = False
        event.src_path = str(logs_dir / "app.log")

        watcher.on_modified(event)

        warned: MagicMock = wlw.logger.warning  # type: ignore[assignment]
        warned.assert_called_once()
        reported_args = warned.call_args.args
        assert str(logs_dir / "app.log") == reported_args[1], f"the failing file must be named: {reported_args}"
        assert "disk error" in str(reported_args[2]), f"the cause must be named, got: {reported_args}"

        watcher._read_new_lines.side_effect = None
        watcher.on_modified(event)
        assert watcher._read_new_lines.call_count == 2


class TestWatcherInitializePositions:
    """Tests for LogFileWatcher.initialize_positions."""

    def test_initializes_to_eof(self, tmp_path, monkeypatch):
        sys_logs = tmp_path / "system_logs"
        sys_logs.mkdir()
        monkeypatch.setattr(wlw, "SYSTEM_LOGS_DIR", sys_logs)
        log_file = sys_logs / "app.log"
        log_file.write_text("test data\n", encoding="utf-8")
        watcher = wlw.LogFileWatcher()
        watcher.initialize_positions()
        assert watcher.log_positions[str(log_file)] == log_file.stat().st_size

    def test_initializes_inodes(self, tmp_path, monkeypatch):
        """Inodes are recorded alongside positions at startup."""
        sys_logs = tmp_path / "system_logs"
        sys_logs.mkdir()
        monkeypatch.setattr(wlw, "SYSTEM_LOGS_DIR", sys_logs)
        log_file = sys_logs / "app.log"
        log_file.write_text("test data\n", encoding="utf-8")
        watcher = wlw.LogFileWatcher()
        watcher.initialize_positions()
        assert watcher.log_inodes[str(log_file)] == log_file.stat().st_ino

    def test_handles_missing_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr(wlw, "SYSTEM_LOGS_DIR", tmp_path / "nonexistent")
        watcher = wlw.LogFileWatcher()
        watcher.initialize_positions()
        assert len(watcher.log_positions) == 0

    def test_multiple_files(self, tmp_path, monkeypatch):
        sys_logs = tmp_path / "system_logs"
        sys_logs.mkdir()
        monkeypatch.setattr(wlw, "SYSTEM_LOGS_DIR", sys_logs)
        f1 = sys_logs / "a.log"
        f2 = sys_logs / "b.log"
        f1.write_text("aaa", encoding="utf-8")
        f2.write_text("bbbbb", encoding="utf-8")
        watcher = wlw.LogFileWatcher()
        watcher.initialize_positions()
        assert watcher.log_positions[str(f1)] == 3
        assert watcher.log_positions[str(f2)] == 5

    def test_ignores_non_log_files(self, tmp_path, monkeypatch):
        sys_logs = tmp_path / "system_logs"
        sys_logs.mkdir()
        monkeypatch.setattr(wlw, "SYSTEM_LOGS_DIR", sys_logs)
        (sys_logs / "data.txt").write_text("not a log", encoding="utf-8")
        (sys_logs / "real.log").write_text("log data", encoding="utf-8")
        watcher = wlw.LogFileWatcher()
        watcher.initialize_positions()
        assert len(watcher.log_positions) == 1


class TestSystemLogsOwnership:
    """The owner's ruling: one owner for system_logs, not two.

    One condition must not mint two escalation signatures with different attribution."""

    def test_start_declines_even_when_it_could_start(self, tmp_path, monkeypatch):
        """The directory present — still declines: a deliberate refusal."""
        monkeypatch.setattr(wlw, "SYSTEM_LOGS_DIR", tmp_path)
        (tmp_path / "hooks_edit_gate.log").write_text("x", encoding="utf-8")

        assert wlw.start_log_watcher() is None

    def test_start_leaves_no_observer_behind(self, tmp_path, monkeypatch):
        """Declining must not park an observer in module state."""
        monkeypatch.setattr(wlw, "SYSTEM_LOGS_DIR", tmp_path)
        monkeypatch.setattr(wlw, "_log_observer", None)

        wlw.start_log_watcher()

        assert wlw.is_log_watcher_active() is False

    def test_owner_is_named_in_module_state(self):
        """The ruling is readable from the code, not just from a commit."""
        assert wlw.SYSTEM_LOGS_OWNER == "branch_log_events"


def _modified(log_file: Path) -> MagicMock:
    """A watchdog modified event for ``log_file``."""
    return MagicMock(is_directory=False, src_path=str(log_file))


class TestAFailureReachesTheCallback:
    """A line that cannot be handled raises to on_modified's warning; it is never consumed in silence."""

    def test_a_line_the_bus_refuses_is_not_read_past(self, tmp_path, monkeypatch):
        """Pins the default: a line that failed to process was skipped and its offset advanced past it."""
        log_file = tmp_path / "system_logs" / "prax_core.log"
        log_file.parent.mkdir()
        log_file.write_text("2026-08-04 | mod | INFO | seen\n", encoding="utf-8")
        watcher = wlw.LogFileWatcher()
        watcher.initialize_positions()
        before = watcher.log_positions[str(log_file)]
        with open(log_file, "a", encoding="utf-8") as f:
            f.write("2026-08-04 | mod | WARNING | disk filling\n")
        monkeypatch.setattr(trigger_core, "trigger", MagicMock(**{"fire.side_effect": RuntimeError("bus down")}))

        log = MagicMock()
        monkeypatch.setattr(wlw, "logger", log)

        watcher.on_modified(_modified(log_file))

        assert watcher.log_positions[str(log_file)] == before
        assert "bus down" in str(log.warning.call_args.args[2])

    def test_an_unreadable_registry_fires_no_unfingerprinted_stand_in(self, tmp_path, monkeypatch):
        log_file = tmp_path / "system_logs" / "prax_core.log"
        log_file.parent.mkdir()
        log_file.write_text("2026-08-04 | mod | INFO | seen\n", encoding="utf-8")
        watcher = wlw.LogFileWatcher()
        watcher.initialize_positions()
        before = watcher.log_positions[str(log_file)]
        with open(log_file, "a", encoding="utf-8") as f:
            f.write("2026-08-04 | mod | ERROR | disk gone\n")
        monkeypatch.setattr(error_registry, "report", MagicMock(side_effect=ValueError("registry torn")))
        bus = MagicMock()
        monkeypatch.setattr(trigger_core, "trigger", bus)
        log = MagicMock()
        monkeypatch.setattr(wlw, "logger", log)

        watcher.on_modified(_modified(log_file))

        bus.fire.assert_not_called()
        assert watcher.log_positions[str(log_file)] == before
        assert "registry torn" in str(log.warning.call_args.args[2])

    def test_an_unreadable_rotated_backup_is_named_by_the_reader(self, tmp_path, monkeypatch):
        """Pins the default: the drain swallowed its own read error; now it raises to the reader, which names it."""
        log_file = tmp_path / "system_logs" / "prax_core.log"
        log_file.parent.mkdir()
        log_file.write_text("2026-08-04 | mod | INFO | seen\n", encoding="utf-8")
        watcher = wlw.LogFileWatcher()
        watcher.initialize_positions()
        with open(log_file, "a", encoding="utf-8") as f:
            f.write("2026-08-04 | mod | WARNING | unread tail\n")
        _rotate_log(log_file)
        log_file.write_text("2026-08-04 | mod | INFO | fresh\n", encoding="utf-8")
        real_open = open

        def deny_backup(path, *args, **kwargs):
            if str(path).endswith(".log.1"):
                raise PermissionError("backup denied")
            return real_open(path, *args, **kwargs)

        monkeypatch.setattr(wlw, "open", deny_backup, raising=False)
        log = MagicMock()
        monkeypatch.setattr(wlw, "logger", log)

        watcher.on_modified(_modified(log_file))

        warned = [call.args for call in log.warning.call_args_list]
        assert any("Failed to drain rotated tail" in args[0] and "backup denied" in str(args[2]) for args in warned)
