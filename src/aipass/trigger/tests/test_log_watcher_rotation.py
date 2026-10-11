# =================== AIPass ====================
# Name: test_log_watcher_rotation.py
# Description: Tests for the branch log watcher's file reading, rotation drain and inode detection
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-08
# =============================================

"""Tests for apps/handlers/log_watcher.py's file reading and rotation (_read_new_lines, on_modified)."""

# Split from test_log_watcher.py (oversize_test_file, 2026-10-08): that file
# keeps parsing and detection; this one holds how the watcher reads a log file:
# new lines from the recorded position, the rotated-out tail drained across the
# backup chain, rotation found by inode, and the on_modified event that drives it.
# The watcher's live-state doors are closed by conftest's log_watcher_infrastructure.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(external) — WatchdogObserver's event delivery is the watchdog package's

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import aipass.trigger.apps.handlers.log_watcher as lw

pytestmark = pytest.mark.usefixtures("log_watcher_infrastructure")


# ---------------------------------------------------------------------------
# Tests -- BranchLogWatcher._read_new_lines
# ---------------------------------------------------------------------------


class TestReadNewLines:
    """Tests for BranchLogWatcher._read_new_lines with tmp_path."""

    def test_reads_new_content(self, tmp_path):
        """Reads only new content appended after initial position."""
        watcher = lw.BranchLogWatcher()

        log_file = tmp_path / "test.log"
        log_file.write_text("line1\n", encoding="utf-8")
        file_path = str(log_file)

        # Set position to end of initial content
        watcher.log_positions[file_path] = log_file.stat().st_size

        # Append new content with a fresh ERROR line
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"{now} | mod | ERROR | New failure\n")

        # Patch _mark_data_dirty to avoid touching the real file
        watcher._read_new_lines(file_path)

        # Position should have advanced
        assert watcher.log_positions[file_path] > 6  # beyond "line1\n"

    def test_handles_log_rotation(self, tmp_path):
        """Handles log rotation (file shrinks) by resetting position to 0."""
        watcher = lw.BranchLogWatcher()

        log_file = tmp_path / "rotated.log"
        log_file.write_text("lots of old content here\n", encoding="utf-8")
        file_path = str(log_file)

        # Set position beyond current size to simulate rotation
        watcher.log_positions[file_path] = 9999

        # Write new small content
        log_file.write_text("short\n", encoding="utf-8")

        watcher._read_new_lines(file_path)

        # Position should be at the end of the new content
        assert watcher.log_positions[file_path] == log_file.stat().st_size


# ---------------------------------------------------------------------------
# Tests -- BranchLogWatcher rotation tail drain
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
    return [call.args[0] for call in mock_proc.call_args_list]


def _error_line(message: str) -> str:
    """Build a fresh-timestamped ERROR line in Prax format."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
    return f"{now} | mod | ERROR | {message}\n"


class TestRotationDrain:
    """Tests for draining the unread tail of a rotated-out branch log."""

    def test_rotation_drains_unread_tail(self, tmp_path):
        """Lines written between last position and rotation ARE processed."""
        watcher = lw.BranchLogWatcher()

        log_file = tmp_path / "core.log"
        # Bulk of the file is already processed (mirrors a log near its size cap)
        log_file.write_text(_error_line("already seen") * 20, encoding="utf-8")
        file_path = str(log_file)
        watcher._record_position(file_path, log_file.stat().st_size)

        # Unread tail: written after last position, before rotation
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(_error_line("missed one"))
            f.write(_error_line("missed two"))

        _rotate_log(log_file)
        log_file.write_text(_error_line("after rotation"), encoding="utf-8")

        with patch.object(watcher, "_process_log_line") as mock_proc:
            watcher._read_new_lines(file_path)

        lines = _processed_lines(mock_proc)
        assert any("missed one" in line for line in lines)
        assert any("missed two" in line for line in lines)
        assert any("after rotation" in line for line in lines)
        assert not any("already seen" in line for line in lines)
        assert all(call.args[1] == file_path for call in mock_proc.call_args_list)

    def test_stale_backup_inode_mismatch_not_reprocessed(self, tmp_path):
        """A stale '.log.1' from an earlier rotation is never re-read."""
        watcher = lw.BranchLogWatcher()

        log_file = tmp_path / "core.log"
        log_file.write_text(_error_line("ancient"), encoding="utf-8")
        # Earlier rotation happened before we started tracking the live file
        _rotate_log(log_file)

        log_file.write_text(_error_line("live line one"), encoding="utf-8")
        file_path = str(log_file)
        watcher._record_position(file_path, log_file.stat().st_size)

        # Live file shrinks but the stale backup still sits there
        log_file.write_text(_error_line("fresh"), encoding="utf-8")
        watcher.log_positions[file_path] = 9999

        with patch.object(watcher, "_process_log_line") as mock_proc:
            watcher._read_new_lines(file_path)

        lines = _processed_lines(mock_proc)
        assert not any("ancient" in line for line in lines)
        assert any("fresh" in line for line in lines)

    def test_missing_backup_file_still_reads_new_file(self, tmp_path):
        """No '.log.1' present: no crash, the new file is still read."""
        watcher = lw.BranchLogWatcher()

        log_file = tmp_path / "core.log"
        log_file.write_text(_error_line("plenty of old content in here"), encoding="utf-8")
        file_path = str(log_file)
        watcher._record_position(file_path, log_file.stat().st_size)

        log_file.write_text(_error_line("tiny"), encoding="utf-8")

        with patch.object(watcher, "_process_log_line") as mock_proc:
            watcher._read_new_lines(file_path)

        lines = _processed_lines(mock_proc)
        assert len(lines) == 1
        assert "tiny" in lines[0]
        assert watcher.log_positions[file_path] == log_file.stat().st_size

    def test_in_place_truncation_no_duplicate_processing(self, tmp_path):
        """Truncation in place (same inode) never re-fires the old content."""
        watcher = lw.BranchLogWatcher()

        log_file = tmp_path / "core.log"
        file_path = str(log_file)
        old_content = _error_line("first pass line with plenty of length")
        log_file.write_text(old_content, encoding="utf-8")

        # A stale backup exists holding a copy of the same text, different inode
        Path(f"{file_path}.1").write_text(old_content, encoding="utf-8")

        watcher._record_position(file_path, log_file.stat().st_size)

        # Truncate in place - inode is unchanged
        inode_before = log_file.stat().st_ino
        with open(log_file, "w", encoding="utf-8") as f:
            f.write(_error_line("short"))
        assert log_file.stat().st_ino == inode_before

        with patch.object(watcher, "_process_log_line") as mock_proc:
            watcher._read_new_lines(file_path)

        lines = _processed_lines(mock_proc)
        assert len(lines) == 1
        assert "short" in lines[0]

    def test_normal_append_never_drains(self, tmp_path):
        """No-overreach guard: an ordinary append never touches the drain path.

        This test passes with and without the fix - it exists to prove the
        drain does not run on the normal (non-shrink) path.
        """
        watcher = lw.BranchLogWatcher()

        log_file = tmp_path / "core.log"
        log_file.write_text(_error_line("first"), encoding="utf-8")
        file_path = str(log_file)
        watcher.log_positions[file_path] = log_file.stat().st_size

        # A backup with other content exists but must be ignored
        Path(f"{file_path}.1").write_text(_error_line("backup only"), encoding="utf-8")

        with open(log_file, "a", encoding="utf-8") as f:
            f.write(_error_line("appended"))

        with patch.object(watcher, "_process_log_line") as mock_proc:
            watcher._read_new_lines(file_path)

        lines = _processed_lines(mock_proc)
        assert len(lines) == 1
        assert "appended" in lines[0]

    def test_repeat_shrink_event_does_not_drain_twice(self, tmp_path):
        """Two events after one rotation drain the tail exactly once."""
        watcher = lw.BranchLogWatcher()

        log_file = tmp_path / "core.log"
        log_file.write_text("header\n", encoding="utf-8")
        file_path = str(log_file)
        watcher._record_position(file_path, log_file.stat().st_size)

        with open(log_file, "a", encoding="utf-8") as f:
            f.write(_error_line("tail line"))

        # Rotate, leaving the new live file EMPTY (nothing written yet)
        _rotate_log(log_file)

        with patch.object(watcher, "_process_log_line") as mock_proc:
            watcher._read_new_lines(file_path)
            watcher._read_new_lines(file_path)

        lines = _processed_lines(mock_proc)
        assert len([line for line in lines if "tail line" in line]) == 1

    def test_unknown_inode_skips_drain(self, tmp_path):
        """Position recorded without an inode (old state) disables the drain.

        No-overreach guard: passes with and without the fix - it proves an
        unknown inode degrades to exactly the pre-fix behaviour.
        """
        watcher = lw.BranchLogWatcher()

        log_file = tmp_path / "core.log"
        log_file.write_text(_error_line("tail line that is fairly long"), encoding="utf-8")
        file_path = str(log_file)
        # Position only - exactly what older on-disk state restores
        watcher.log_positions[file_path] = log_file.stat().st_size

        _rotate_log(log_file)
        log_file.write_text(_error_line("new"), encoding="utf-8")

        with patch.object(watcher, "_process_log_line") as mock_proc:
            watcher._read_new_lines(file_path)

        lines = _processed_lines(mock_proc)
        assert len(lines) == 1
        assert "new" in lines[0]

    def test_rotated_file_smaller_than_position_skipped(self, tmp_path):
        """A backup shorter than the recorded position is not drained."""
        watcher = lw.BranchLogWatcher()

        log_file = tmp_path / "core.log"
        log_file.write_text(_error_line("content"), encoding="utf-8")
        file_path = str(log_file)
        watcher._record_position(file_path, log_file.stat().st_size)
        watcher.log_positions[file_path] = 9999

        _rotate_log(log_file)
        log_file.write_text(_error_line("new"), encoding="utf-8")

        with patch.object(watcher, "_process_log_line") as mock_proc:
            watcher._read_new_lines(file_path)

        lines = _processed_lines(mock_proc)
        assert len(lines) == 1
        assert "new" in lines[0]

    def test_drain_failure_does_not_block_new_file(self, tmp_path):
        """An exception inside the drain never prevents reading the new file."""
        watcher = lw.BranchLogWatcher()

        log_file = tmp_path / "core.log"
        log_file.write_text(_error_line("old content that is long enough"), encoding="utf-8")
        file_path = str(log_file)
        watcher._record_position(file_path, log_file.stat().st_size)

        _rotate_log(log_file)
        log_file.write_text(_error_line("new"), encoding="utf-8")

        with patch.object(watcher, "_drain_rotated_tail", side_effect=RuntimeError("boom")):
            with patch.object(watcher, "_process_log_line") as mock_proc:
                watcher._read_new_lines(file_path)

        lines = _processed_lines(mock_proc)
        assert len(lines) == 1
        assert "new" in lines[0]

    def test_record_position_tracks_inode(self, tmp_path):
        """_record_position stores the current inode alongside the offset."""
        watcher = lw.BranchLogWatcher()

        log_file = tmp_path / "core.log"
        log_file.write_text("data\n", encoding="utf-8")
        file_path = str(log_file)

        watcher._record_position(file_path, 4)

        assert watcher.log_positions[file_path] == 4
        assert watcher.log_inodes[file_path] == log_file.stat().st_ino


# ---------------------------------------------------------------------------
# Tests -- BranchLogWatcher inode-based rotation detection
# ---------------------------------------------------------------------------


def _fresh_lines(count: int) -> list:
    """Build a list of distinct full ERROR lines for the post-rotation file."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
    return [f"{now} | mod | ERROR | after rotation {i:03d}" for i in range(count)]


class TestInodeRotationDetection:
    """Tests for rotation detected by inode and located across the backup chain."""

    def test_rotation_detected_when_new_file_already_grew(self, tmp_path):
        """A fresh log already past the old offset is still detected as rotated.

        The size-only check missed this entirely and seeked into the middle of
        the brand new file, yielding a partial line.
        """
        watcher = lw.BranchLogWatcher()

        log_file = tmp_path / "core.log"
        log_file.write_text(_error_line("already seen") * 20, encoding="utf-8")
        file_path = str(log_file)
        watcher._record_position(file_path, log_file.stat().st_size)
        recorded_pos = watcher.log_positions[file_path]

        with open(log_file, "a", encoding="utf-8") as f:
            f.write(_error_line("missed one"))

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
        watcher = lw.BranchLogWatcher()

        log_file = tmp_path / "core.log"
        log_file.write_text("header line\n", encoding="utf-8")
        file_path = str(log_file)
        watcher._record_position(file_path, log_file.stat().st_size)

        with open(log_file, "a", encoding="utf-8") as f:
            f.write(_error_line("tail from two rotations ago"))

        tracked_inode = log_file.stat().st_ino
        _rotate_chain(log_file)  # tracked file -> .log.1
        _rotate_chain(log_file)  # tracked file -> .log.2
        assert Path(f"{file_path}.2").stat().st_ino == tracked_inode

        log_file.write_text(_error_line("brand new"), encoding="utf-8")

        with patch.object(lw, "logger") as mock_logger:
            with patch.object(watcher, "_process_log_line") as mock_proc:
                watcher._read_new_lines(file_path)

        lines = _processed_lines(mock_proc)
        assert any("tail from two rotations ago" in line for line in lines)
        assert any("brand new" in line for line in lines)

        warnings = [str(call.args) for call in mock_logger.warning.call_args_list]
        assert any("not replayed" in warning and ".log.2" in warning for warning in warnings)

    def test_tracked_inode_beyond_chain_reads_new_file_from_zero(self, tmp_path):
        """Inode matching nothing within the chain: nothing drained, new file read whole."""
        watcher = lw.BranchLogWatcher()

        log_file = tmp_path / "core.log"
        log_file.write_text("header\n", encoding="utf-8")
        file_path = str(log_file)
        watcher._record_position(file_path, log_file.stat().st_size)
        tracked_inode = log_file.stat().st_ino

        with open(log_file, "a", encoding="utf-8") as f:
            f.write(_error_line("lost tail"))

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
        watcher = lw.BranchLogWatcher()

        log_file = tmp_path / "core.log"
        file_path = str(log_file)
        for name in ("chain three", "chain two", "chain one"):
            log_file.write_text(_error_line(name), encoding="utf-8")
            _rotate_chain(log_file)

        log_file.write_text(_error_line("live content line"), encoding="utf-8")
        watcher._record_position(file_path, log_file.stat().st_size)

        inode_before = log_file.stat().st_ino
        with open(log_file, "w", encoding="utf-8") as f:
            f.write(_error_line("short"))
        assert log_file.stat().st_ino == inode_before

        with patch.object(watcher, "_process_log_line") as mock_proc:
            watcher._read_new_lines(file_path)

        lines = _processed_lines(mock_proc)
        assert len(lines) == 1
        assert "short" in lines[0]

    def test_normal_append_with_backup_chain_never_drains(self, tmp_path):
        """No-overreach guard: an append with backups present stays on the normal path.

        Passes with and without the fix - it proves the chain walk only runs
        when the inode actually changed.
        """
        watcher = lw.BranchLogWatcher()

        log_file = tmp_path / "core.log"
        file_path = str(log_file)
        for name in ("chain three", "chain two", "chain one"):
            log_file.write_text(_error_line(name), encoding="utf-8")
            _rotate_chain(log_file)

        log_file.write_text(_error_line("first"), encoding="utf-8")
        watcher._record_position(file_path, log_file.stat().st_size)

        with open(log_file, "a", encoding="utf-8") as f:
            f.write(_error_line("appended"))

        with patch.object(watcher, "_process_log_line") as mock_proc:
            watcher._read_new_lines(file_path)

        lines = _processed_lines(mock_proc)
        assert len(lines) == 1
        assert "appended" in lines[0]

    def test_zero_inode_falls_back_to_size_check(self, tmp_path):
        """No-overreach guard: a recorded inode of 0 is treated as unknown.

        Passes with and without the fix - some Windows filesystems report
        st_ino 0, which must never be trusted as a rotation signal.
        """
        watcher = lw.BranchLogWatcher()

        log_file = tmp_path / "core.log"
        log_file.write_text(_error_line("tail line that is fairly long"), encoding="utf-8")
        file_path = str(log_file)
        watcher.log_positions[file_path] = log_file.stat().st_size
        watcher.log_inodes[file_path] = 0

        _rotate_chain(log_file)
        log_file.write_text(_error_line("new"), encoding="utf-8")

        with patch.object(watcher, "_process_log_line") as mock_proc:
            watcher._read_new_lines(file_path)

        lines = _processed_lines(mock_proc)
        assert len(lines) == 1
        assert "new" in lines[0]
        assert watcher.log_positions[file_path] == log_file.stat().st_size


# ---------------------------------------------------------------------------
# Tests -- on_modified
# ---------------------------------------------------------------------------


class TestOnModified:
    """Tests for BranchLogWatcher.on_modified."""

    def test_skips_directory_events(self):
        """Directory events are ignored by on_modified."""
        watcher = lw.BranchLogWatcher()
        watcher._read_new_lines = MagicMock()
        event = MagicMock()
        event.is_directory = True
        event.src_path = "/some/dir"
        watcher.on_modified(event)
        watcher._read_new_lines.assert_not_called()

    def test_skips_excluded_files(self):
        """Files that fail _should_process are not read."""
        watcher = lw.BranchLogWatcher()
        watcher._should_process = MagicMock(return_value=False)
        watcher._read_new_lines = MagicMock()
        event = MagicMock()
        event.is_directory = False
        event.src_path = "/some/excluded.log"
        watcher.on_modified(event)
        watcher._read_new_lines.assert_not_called()

    def test_processes_valid_file(self):
        """Valid log file triggers _read_new_lines with correct path."""
        watcher = lw.BranchLogWatcher()
        watcher._should_process = MagicMock(return_value=True)
        watcher._read_new_lines = MagicMock()
        event = MagicMock()
        event.is_directory = False
        event.src_path = "/some/branch/logs/core.log"
        watcher.on_modified(event)
        watcher._read_new_lines.assert_called_once_with("/some/branch/logs/core.log")

    def test_a_read_failure_is_reported_and_costs_only_that_event(self):
        """IOError is swallowed — but it is named, and the watcher keeps watching.

        Not raising was the whole assertion, and a bare `except: pass` passes
        it. Two things make the swallow legitimate instead of a black hole: the
        failure reaches the log with the file that caused it, and the next
        event on the same watcher is still processed. A watcher that silently
        stopped reading after one bad event would look identical otherwise.
        """
        watcher = lw.BranchLogWatcher()
        watcher._should_process = MagicMock(return_value=True)
        watcher._read_new_lines = MagicMock(side_effect=IOError("disk error"))
        event = MagicMock()
        event.is_directory = False
        event.src_path = "/some/core.log"

        watcher.on_modified(event)

        warned: MagicMock = lw.logger.warning  # type: ignore[assignment]
        warned.assert_called_once()
        # Assert on the call's own arguments, not a repr of the call — repr
        # doubles backslashes in a Windows path, so a path search through it
        # can never match even a correctly-built expected string.
        reported_args = warned.call_args.args
        assert "/some/core.log" == reported_args[1], f"the failing file must be named, got: {reported_args}"
        assert "disk error" in str(reported_args[2]), f"the cause must be named, got: {reported_args}"

        watcher._read_new_lines.side_effect = None
        watcher.on_modified(event)
        assert watcher._read_new_lines.call_count == 2


# ---------------------------------------------------------------------------
# Tests -- BranchLogWatcher._read_new_lines (deeper coverage)
# ---------------------------------------------------------------------------


class TestReadNewLinesDeeper:
    """Deeper coverage for BranchLogWatcher._read_new_lines."""

    def test_no_read_when_size_unchanged(self, tmp_path):
        """When file size equals last position, no reading occurs."""
        watcher = lw.BranchLogWatcher()
        log_file = tmp_path / "unchanged.log"
        log_file.write_text("content\n", encoding="utf-8")
        file_path = str(log_file)
        current_size = log_file.stat().st_size
        watcher.log_positions[file_path] = current_size

        watcher._process_log_line = MagicMock()
        watcher._read_new_lines(file_path)

        watcher._process_log_line.assert_not_called()
        assert watcher.log_positions[file_path] == current_size

    def test_debounce_flushes_when_interval_elapsed(self, tmp_path, monkeypatch):
        """The read position reaches trigger_data.json once the interval has elapsed.

        Mutant: positions left out of the flush.
        """
        watcher = lw.BranchLogWatcher()
        log_file = tmp_path / "interval.log"
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
        log_file.write_text(f"{now} | mod | ERROR | fail\n", encoding="utf-8")
        file_path = str(log_file)
        watcher.log_positions[file_path] = 0

        monkeypatch.setattr(lw, "_active_watcher", watcher)
        monkeypatch.setattr(lw, "_last_flush_time", 0.0)
        watcher._read_new_lines(file_path)

        flushed = json.loads(lw.TRIGGER_DATA_FILE.read_text(encoding="utf-8"))
        assert flushed["log_positions"] == {file_path: log_file.stat().st_size}
        assert lw.get_watcher_status()["pending_flush"] is False

    def test_debounce_skips_flush_within_interval(self, tmp_path, monkeypatch):
        """_flush_trigger_data is NOT called when within flush interval."""
        import time

        watcher = lw.BranchLogWatcher()
        log_file = tmp_path / "notsaved.log"
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
        log_file.write_text(f"{now} | mod | ERROR | fail\n", encoding="utf-8")
        file_path = str(log_file)
        watcher.log_positions[file_path] = 0

        monkeypatch.setattr(lw, "_last_flush_time", time.monotonic())
        with patch.object(lw, "_flush_trigger_data") as mock_flush:
            watcher._read_new_lines(file_path)
            mock_flush.assert_not_called()
        assert lw.get_watcher_status()["pending_flush"] is True

    def test_blank_lines_are_skipped(self, tmp_path):
        """Blank lines in new content do not trigger _process_log_line."""
        watcher = lw.BranchLogWatcher()
        log_file = tmp_path / "blanks.log"
        log_file.write_text("\n\n\n", encoding="utf-8")
        file_path = str(log_file)
        watcher.log_positions[file_path] = 0

        watcher._process_log_line = MagicMock()
        watcher._read_new_lines(file_path)
        watcher._process_log_line.assert_not_called()

    def test_file_truncated_resets_position(self, tmp_path):
        """When file is smaller than stored position, resets to 0 (mutant: the truncation reset set to 1, not 0)."""
        watcher = lw.BranchLogWatcher()
        log_file = tmp_path / "truncated.log"
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
        log_file.write_text(f"{now} | mod | ERROR | after rotation\n", encoding="utf-8")
        file_path = str(log_file)
        watcher.log_positions[file_path] = 99999

        watcher._process_log_line = MagicMock()
        watcher._read_new_lines(file_path)

        watcher._process_log_line.assert_called_once_with(f"{now} | mod | ERROR | after rotation", file_path)
        assert watcher.log_positions[file_path] == log_file.stat().st_size
