"""Tests for the branch log watcher handler (apps/handlers/log_watcher.py)."""

# =================== META ====================
# Name: test_log_watcher.py
# Description: Unit tests for branch log watcher event producer
# Version: 1.2.0
# Created: 2026-04-03
# Modified: 2026-08-04
# =============================================

import json
import sys
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _mock_infrastructure(monkeypatch):
    """Mock heavy infrastructure imports before log_watcher module loads."""

    mock_logger = MagicMock()
    mock_logger.info = MagicMock()
    mock_logger.warning = MagicMock()

    # -- prax logger --------------------------------------------------------
    prax_logger_mod = MagicMock()
    prax_logger_mod.get_direct_logger = MagicMock(return_value=mock_logger)
    monkeypatch.setitem(sys.modules, "aipass.prax", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.prax.apps", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.prax.apps.modules", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.prax.apps.modules.logger", prax_logger_mod)

    # -- trigger json handler -----------------------------------------------
    mock_json_handler = MagicMock()
    mock_json_handler.log_operation = MagicMock(return_value=True)
    json_pkg = MagicMock()
    json_pkg.json_handler = mock_json_handler
    monkeypatch.setitem(sys.modules, "aipass.trigger.apps.handlers.json", json_pkg)
    json_mod = MagicMock()
    json_mod.log_operation = mock_json_handler.log_operation
    monkeypatch.setitem(sys.modules, "aipass.trigger.apps.handlers.json.json_handler", json_mod)

    # -- trigger config (TRIGGER_ROOT, AIPASS_PKG_ROOT) ---------------------
    from aipass.trigger.apps.config import atomic_write_json

    mock_config = MagicMock()
    mock_config.TRIGGER_ROOT = Path("/tmp/fake_trigger_root")
    mock_config.AIPASS_PKG_ROOT = Path("/tmp/fake_aipass_pkg")
    mock_config.atomic_write_json = atomic_write_json
    monkeypatch.setitem(sys.modules, "aipass.trigger.apps.config", mock_config)

    # -- error_registry (report) -------------------------------------------
    mock_registry = MagicMock()
    mock_registry.report = MagicMock(return_value={"is_new": True, "count": 1, "id": "abc123"})
    monkeypatch.setitem(sys.modules, "aipass.trigger.apps.handlers.error_registry", mock_registry)

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
    monkeypatch.delitem(sys.modules, "aipass.trigger.apps.handlers.log_watcher", raising=False)


def _import_log_watcher():
    """Import log_watcher module fresh (after mocks are in place)."""
    import aipass.trigger.apps.handlers.log_watcher as lw

    return lw


# ---------------------------------------------------------------------------
# Tests -- _generate_error_hash
# ---------------------------------------------------------------------------


class TestGenerateErrorHash:
    """Tests for _generate_error_hash pure function."""

    def test_deterministic(self):
        """Same inputs always produce the same hash."""
        lw = _import_log_watcher()
        h1 = lw._generate_error_hash("mod_a", "something broke")
        h2 = lw._generate_error_hash("mod_a", "something broke")
        assert h1 == h2

    def test_length_is_8(self):
        """Hash is exactly 8 characters long."""
        lw = _import_log_watcher()
        h = lw._generate_error_hash("module", "message")
        assert len(h) == 8

    def test_different_inputs_different_hashes(self):
        """Different module/message combos produce different hashes."""
        lw = _import_log_watcher()
        h1 = lw._generate_error_hash("mod_a", "error one")
        h2 = lw._generate_error_hash("mod_b", "error two")
        assert h1 != h2

    def test_matches_md5_prefix(self):
        """Hash matches the first 8 chars of MD5(module:message)."""
        lw = _import_log_watcher()
        expected = hashlib.md5("mymod:mymsg".encode()).hexdigest()[:8]
        assert lw._generate_error_hash("mymod", "mymsg") == expected


# ---------------------------------------------------------------------------
# Tests -- _detect_branch_from_path
# ---------------------------------------------------------------------------


class TestDetectBranchFromPath:
    """Tests for _detect_branch_from_path."""

    def test_standard_branch_logs_path(self):
        """Detects branch from src/aipass/<branch>/logs/file.log pattern."""
        lw = _import_log_watcher()
        path = "/home/user/src/aipass/flow/logs/flow_planner.log"
        assert lw._detect_branch_from_path(path) == "FLOW"

    def test_system_logs_mapped_file(self):
        """Uses SYSTEM_LOGS_BRANCH_MAP for known filenames."""
        lw = _import_log_watcher()
        path = str(lw.SYSTEM_LOGS_DIR / "telegram_bridge.log")
        assert lw._detect_branch_from_path(path) == "API"

    def test_system_logs_prefix_match(self):
        """Matches prefix against known branch prefixes for system_logs files."""
        lw = _import_log_watcher()
        path = str(lw.SYSTEM_LOGS_DIR / "seedgo_audit.log")
        assert lw._detect_branch_from_path(path) == "SEEDGO"

    def test_system_logs_exact_stem_match(self):
        """Matches when stem equals a known prefix exactly."""
        lw = _import_log_watcher()
        path = str(lw.SYSTEM_LOGS_DIR / "prax.log")
        assert lw._detect_branch_from_path(path) == "PRAX"

    def test_unknown_path_returns_unknown(self):
        """Returns UNKNOWN for paths that do not match any pattern."""
        lw = _import_log_watcher()
        assert lw._detect_branch_from_path("/some/random/path.log") == "UNKNOWN"


# ---------------------------------------------------------------------------
# Tests -- _parse_prax_log_line
# ---------------------------------------------------------------------------


class TestParsePraxLogLine:
    """Tests for _parse_prax_log_line."""

    def test_pipe_format_error(self):
        """Parses pipe-separated ERROR line correctly."""
        lw = _import_log_watcher()
        line = "2026-03-01 12:00:00.123 | my_module | ERROR | Something failed"
        result = lw._parse_prax_log_line(line)
        assert result is not None
        assert result["level"] == "ERROR"
        assert result["module"] == "my_module"
        assert result["message"] == "Something failed"
        assert "2026-03-01" in result["timestamp"]

    def test_pipe_format_critical(self):
        """Parses pipe-separated CRITICAL line correctly."""
        lw = _import_log_watcher()
        line = "2026-03-01 12:00:00.123 | core | CRITICAL | Fatal error"
        result = lw._parse_prax_log_line(line)
        assert result is not None
        assert result["level"] == "CRITICAL"

    def test_pipe_format_info_returns_none(self):
        """INFO level lines are not returned (only ERROR/CRITICAL)."""
        lw = _import_log_watcher()
        line = "2026-03-01 12:00:00.123 | my_module | INFO | All good"
        assert lw._parse_prax_log_line(line) is None

    def test_pipe_format_warning_returns_none(self):
        """WARNING level lines are not returned."""
        lw = _import_log_watcher()
        line = "2026-03-01 12:00:00.123 | my_module | WARNING | Watch out"
        assert lw._parse_prax_log_line(line) is None

    def test_dash_format_error(self):
        """Parses dash-separated ERROR line (Python logging format)."""
        lw = _import_log_watcher()
        line = "2026-02-10 15:12:29,460 - telegram_bridge - ERROR - Connection lost"
        result = lw._parse_prax_log_line(line)
        assert result is not None
        assert result["level"] == "ERROR"
        assert result["module"] == "telegram_bridge"
        assert result["message"] == "Connection lost"

    def test_malformed_line_returns_none(self):
        """Malformed line that does not match any format returns None."""
        lw = _import_log_watcher()
        assert lw._parse_prax_log_line("just some random text") is None

    def test_empty_line_returns_none(self):
        """Empty line returns None."""
        lw = _import_log_watcher()
        assert lw._parse_prax_log_line("") is None


# ---------------------------------------------------------------------------
# Tests -- _is_stale_entry
# ---------------------------------------------------------------------------


class TestIsStaleEntry:
    """Tests for _is_stale_entry."""

    def test_recent_timestamp_not_stale(self):
        """A timestamp within the threshold is NOT stale."""
        lw = _import_log_watcher()
        now = datetime.now()
        recent = now - timedelta(seconds=10)
        ts = recent.strftime("%Y-%m-%d %H:%M:%S.%f")
        assert lw._is_stale_entry(ts) is False

    def test_old_timestamp_is_stale(self):
        """A timestamp well beyond the threshold IS stale."""
        lw = _import_log_watcher()
        old = datetime.now() - timedelta(seconds=600)
        ts = old.strftime("%Y-%m-%d %H:%M:%S.%f")
        assert lw._is_stale_entry(ts) is True

    def test_unparseable_timestamp_returns_true(self):
        """An unparseable timestamp is treated as stale."""
        lw = _import_log_watcher()
        assert lw._is_stale_entry("not-a-timestamp") is True

    def test_comma_microsecond_format(self):
        """Python logging format with comma microseconds is parsed correctly."""
        lw = _import_log_watcher()
        recent = datetime.now() - timedelta(seconds=5)
        ts = recent.strftime("%Y-%m-%d %H:%M:%S,") + "123"
        assert lw._is_stale_entry(ts) is False


# ---------------------------------------------------------------------------
# Tests -- set_event_callback / clear_seen_hashes
# ---------------------------------------------------------------------------


class TestCallbackAndState:
    """Tests for set_event_callback and clear_seen_hashes."""

    def test_set_event_callback_sets_callback(self):
        """set_event_callback stores the callback in module-level _fire_event."""
        lw = _import_log_watcher()
        cb = MagicMock()
        lw.set_event_callback(cb)
        assert lw._fire_event is cb

    def test_clear_seen_hashes_empties_set(self):
        """clear_seen_hashes empties the _seen_error_hashes set."""
        lw = _import_log_watcher()
        lw._seen_error_hashes.add("test_hash")
        with patch.object(lw, "_flush_trigger_data"):
            lw.clear_seen_hashes()
        assert len(lw._seen_error_hashes) == 0


# ---------------------------------------------------------------------------
# Tests -- BranchLogWatcher._should_process
# ---------------------------------------------------------------------------


class TestShouldProcess:
    """Tests for BranchLogWatcher._should_process."""

    def test_log_file_in_branch_dir_accepted(self):
        """.log file inside /aipass/branch/logs/ is accepted."""
        lw = _import_log_watcher()
        watcher = lw.BranchLogWatcher()
        assert watcher._should_process("/src/aipass/flow/logs/flow.log") is True

    def test_txt_file_rejected(self):
        """.txt file is rejected even if in the right directory."""
        lw = _import_log_watcher()
        watcher = lw.BranchLogWatcher()
        assert watcher._should_process("/src/aipass/flow/logs/notes.txt") is False

    def test_excluded_file_rejected(self):
        """Excluded log files (e.g. dispatch.log) are rejected."""
        lw = _import_log_watcher()
        watcher = lw.BranchLogWatcher()
        assert watcher._should_process("/src/aipass/flow/logs/dispatch.log") is False

    def test_system_logs_accepted(self):
        """Log file inside /system_logs/ is accepted."""
        lw = _import_log_watcher()
        watcher = lw.BranchLogWatcher()
        assert watcher._should_process("/home/user/system_logs/prax.log") is True

    def test_random_log_outside_known_dirs_rejected(self):
        """Log file outside branch and system_logs dirs is rejected."""
        lw = _import_log_watcher()
        watcher = lw.BranchLogWatcher()
        assert watcher._should_process("/tmp/random/output.log") is False


# ---------------------------------------------------------------------------
# Tests -- BranchLogWatcher._process_log_line
# ---------------------------------------------------------------------------


class TestProcessLogLine:
    """Tests for BranchLogWatcher._process_log_line."""

    def test_fires_event_on_new_error(self):
        """Fires error_detected event for a new ERROR line via registry path."""
        lw = _import_log_watcher()
        fire = MagicMock()
        lw.set_event_callback(fire)
        watcher = lw.BranchLogWatcher()

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
        line = f"{now} | my_module | ERROR | Database connection failed"
        log_path = "/src/aipass/flow/logs/flow.log"

        watcher._process_log_line(line, log_path)

        fire.assert_called_once()
        call_args = fire.call_args
        assert call_args[0][0] == "error_detected"
        assert call_args[1]["message"] == "Database connection failed"

    def test_skips_semantic_exclusion_patterns(self):
        """Lines matching semantic exclusion patterns are skipped."""
        lw = _import_log_watcher()
        fire = MagicMock()
        lw.set_event_callback(fire)
        watcher = lw.BranchLogWatcher()

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
        line = f"{now} | handler | ERROR | Processed error error_hash=abc123"
        watcher._process_log_line(line, "/src/aipass/flow/logs/flow.log")

        fire.assert_not_called()

    def test_skips_stale_entries(self):
        """Lines with stale timestamps are skipped."""
        lw = _import_log_watcher()
        fire = MagicMock()
        lw.set_event_callback(fire)
        watcher = lw.BranchLogWatcher()

        old = (datetime.now() - timedelta(seconds=600)).strftime("%Y-%m-%d %H:%M:%S.%f")
        line = f"{old} | mod | ERROR | Old error"
        watcher._process_log_line(line, "/src/aipass/flow/logs/flow.log")

        fire.assert_not_called()

    def test_skips_non_error_lines(self):
        """INFO-level lines are not processed (parse returns None)."""
        lw = _import_log_watcher()
        fire = MagicMock()
        lw.set_event_callback(fire)
        watcher = lw.BranchLogWatcher()

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
        line = f"{now} | mod | INFO | All good"
        watcher._process_log_line(line, "/src/aipass/flow/logs/flow.log")

        fire.assert_not_called()


# ---------------------------------------------------------------------------
# Tests -- BranchLogWatcher._read_new_lines
# ---------------------------------------------------------------------------


class TestReadNewLines:
    """Tests for BranchLogWatcher._read_new_lines with tmp_path."""

    def test_reads_new_content(self, tmp_path):
        """Reads only new content appended after initial position."""
        lw = _import_log_watcher()
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

        # Patch _save_log_positions to avoid touching the real file
        with patch.object(lw, "_mark_data_dirty"):
            watcher._read_new_lines(file_path)

        # Position should have advanced
        assert watcher.log_positions[file_path] > 6  # beyond "line1\n"

    def test_handles_log_rotation(self, tmp_path):
        """Handles log rotation (file shrinks) by resetting position to 0."""
        lw = _import_log_watcher()
        watcher = lw.BranchLogWatcher()

        log_file = tmp_path / "rotated.log"
        log_file.write_text("lots of old content here\n", encoding="utf-8")
        file_path = str(log_file)

        # Set position beyond current size to simulate rotation
        watcher.log_positions[file_path] = 9999

        # Write new small content
        log_file.write_text("short\n", encoding="utf-8")

        with patch.object(lw, "_mark_data_dirty"):
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
        lw = _import_log_watcher()
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

        with patch.object(lw, "_mark_data_dirty"):
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
        lw = _import_log_watcher()
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

        with patch.object(lw, "_mark_data_dirty"):
            with patch.object(watcher, "_process_log_line") as mock_proc:
                watcher._read_new_lines(file_path)

        lines = _processed_lines(mock_proc)
        assert not any("ancient" in line for line in lines)
        assert any("fresh" in line for line in lines)

    def test_missing_backup_file_still_reads_new_file(self, tmp_path):
        """No '.log.1' present: no crash, the new file is still read."""
        lw = _import_log_watcher()
        watcher = lw.BranchLogWatcher()

        log_file = tmp_path / "core.log"
        log_file.write_text(_error_line("plenty of old content in here"), encoding="utf-8")
        file_path = str(log_file)
        watcher._record_position(file_path, log_file.stat().st_size)

        log_file.write_text(_error_line("tiny"), encoding="utf-8")

        with patch.object(lw, "_mark_data_dirty"):
            with patch.object(watcher, "_process_log_line") as mock_proc:
                watcher._read_new_lines(file_path)

        lines = _processed_lines(mock_proc)
        assert len(lines) == 1
        assert "tiny" in lines[0]
        assert watcher.log_positions[file_path] == log_file.stat().st_size

    def test_in_place_truncation_no_duplicate_processing(self, tmp_path):
        """Truncation in place (same inode) never re-fires the old content."""
        lw = _import_log_watcher()
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

        with patch.object(lw, "_mark_data_dirty"):
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
        lw = _import_log_watcher()
        watcher = lw.BranchLogWatcher()

        log_file = tmp_path / "core.log"
        log_file.write_text(_error_line("first"), encoding="utf-8")
        file_path = str(log_file)
        watcher.log_positions[file_path] = log_file.stat().st_size

        # A backup with other content exists but must be ignored
        Path(f"{file_path}.1").write_text(_error_line("backup only"), encoding="utf-8")

        with open(log_file, "a", encoding="utf-8") as f:
            f.write(_error_line("appended"))

        with patch.object(lw, "_mark_data_dirty"):
            with patch.object(watcher, "_process_log_line") as mock_proc:
                watcher._read_new_lines(file_path)

        lines = _processed_lines(mock_proc)
        assert len(lines) == 1
        assert "appended" in lines[0]

    def test_repeat_shrink_event_does_not_drain_twice(self, tmp_path):
        """Two events after one rotation drain the tail exactly once."""
        lw = _import_log_watcher()
        watcher = lw.BranchLogWatcher()

        log_file = tmp_path / "core.log"
        log_file.write_text("header\n", encoding="utf-8")
        file_path = str(log_file)
        watcher._record_position(file_path, log_file.stat().st_size)

        with open(log_file, "a", encoding="utf-8") as f:
            f.write(_error_line("tail line"))

        # Rotate, leaving the new live file EMPTY (nothing written yet)
        _rotate_log(log_file)

        with patch.object(lw, "_mark_data_dirty"):
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
        lw = _import_log_watcher()
        watcher = lw.BranchLogWatcher()

        log_file = tmp_path / "core.log"
        log_file.write_text(_error_line("tail line that is fairly long"), encoding="utf-8")
        file_path = str(log_file)
        # Position only - exactly what older on-disk state restores
        watcher.log_positions[file_path] = log_file.stat().st_size

        _rotate_log(log_file)
        log_file.write_text(_error_line("new"), encoding="utf-8")

        with patch.object(lw, "_mark_data_dirty"):
            with patch.object(watcher, "_process_log_line") as mock_proc:
                watcher._read_new_lines(file_path)

        lines = _processed_lines(mock_proc)
        assert len(lines) == 1
        assert "new" in lines[0]

    def test_rotated_file_smaller_than_position_skipped(self, tmp_path):
        """A backup shorter than the recorded position is not drained."""
        lw = _import_log_watcher()
        watcher = lw.BranchLogWatcher()

        log_file = tmp_path / "core.log"
        log_file.write_text(_error_line("content"), encoding="utf-8")
        file_path = str(log_file)
        watcher._record_position(file_path, log_file.stat().st_size)
        watcher.log_positions[file_path] = 9999

        _rotate_log(log_file)
        log_file.write_text(_error_line("new"), encoding="utf-8")

        with patch.object(lw, "_mark_data_dirty"):
            with patch.object(watcher, "_process_log_line") as mock_proc:
                watcher._read_new_lines(file_path)

        lines = _processed_lines(mock_proc)
        assert len(lines) == 1
        assert "new" in lines[0]

    def test_drain_failure_does_not_block_new_file(self, tmp_path):
        """An exception inside the drain never prevents reading the new file."""
        lw = _import_log_watcher()
        watcher = lw.BranchLogWatcher()

        log_file = tmp_path / "core.log"
        log_file.write_text(_error_line("old content that is long enough"), encoding="utf-8")
        file_path = str(log_file)
        watcher._record_position(file_path, log_file.stat().st_size)

        _rotate_log(log_file)
        log_file.write_text(_error_line("new"), encoding="utf-8")

        with patch.object(lw, "_mark_data_dirty"):
            with patch.object(watcher, "_drain_rotated_tail", side_effect=RuntimeError("boom")):
                with patch.object(watcher, "_process_log_line") as mock_proc:
                    watcher._read_new_lines(file_path)

        lines = _processed_lines(mock_proc)
        assert len(lines) == 1
        assert "new" in lines[0]

    def test_record_position_tracks_inode(self, tmp_path):
        """_record_position stores the current inode alongside the offset."""
        lw = _import_log_watcher()
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
        lw = _import_log_watcher()
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

        with patch.object(lw, "_mark_data_dirty"):
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
        lw = _import_log_watcher()
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

        with patch.object(lw, "_mark_data_dirty"):
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
        lw = _import_log_watcher()
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

        with patch.object(lw, "_mark_data_dirty"):
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
        lw = _import_log_watcher()
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

        with patch.object(lw, "_mark_data_dirty"):
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
        lw = _import_log_watcher()
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

        with patch.object(lw, "_mark_data_dirty"):
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
        lw = _import_log_watcher()
        watcher = lw.BranchLogWatcher()

        log_file = tmp_path / "core.log"
        log_file.write_text(_error_line("tail line that is fairly long"), encoding="utf-8")
        file_path = str(log_file)
        watcher.log_positions[file_path] = log_file.stat().st_size
        watcher.log_inodes[file_path] = 0

        _rotate_chain(log_file)
        log_file.write_text(_error_line("new"), encoding="utf-8")

        with patch.object(lw, "_mark_data_dirty"):
            with patch.object(watcher, "_process_log_line") as mock_proc:
                watcher._read_new_lines(file_path)

        lines = _processed_lines(mock_proc)
        assert len(lines) == 1
        assert "new" in lines[0]
        assert watcher.log_positions[file_path] == log_file.stat().st_size


# ---------------------------------------------------------------------------
# Tests -- start / stop / is_active / get_status
# ---------------------------------------------------------------------------


class TestStartStopStatus:
    """Tests for start_branch_log_watcher, stop, is_active, get_watcher_status."""

    def test_start_returns_none_when_watchdog_unavailable(self):
        """start_branch_log_watcher returns None when WATCHDOG_AVAILABLE is False."""
        lw = _import_log_watcher()
        lw.WATCHDOG_AVAILABLE = False
        result = lw.start_branch_log_watcher()
        assert result is None

    def test_is_branch_log_watcher_active_returns_false_when_not_started(self):
        """is_branch_log_watcher_active returns False when no observer is set."""
        lw = _import_log_watcher()
        lw._branch_log_observer = None
        assert lw.is_branch_log_watcher_active() is False

    def test_get_watcher_status_returns_correct_shape(self):
        """get_watcher_status returns a dict with all expected keys."""
        lw = _import_log_watcher()
        status = lw.get_watcher_status()
        assert isinstance(status, dict)
        expected_keys = {
            "active",
            "watchdog_available",
            "seen_hashes_count",
            "tracked_log_files",
            "excluded_files",
            "stale_threshold_seconds",
            "aipass_root",
        }
        assert expected_keys == set(status.keys())

    def test_get_watcher_status_values(self):
        """get_watcher_status returns sensible values."""
        lw = _import_log_watcher()
        status = lw.get_watcher_status()
        assert status["stale_threshold_seconds"] == 300
        assert isinstance(status["excluded_files"], list)
        assert len(status["excluded_files"]) > 0


# ---------------------------------------------------------------------------
# Tests -- on_modified
# ---------------------------------------------------------------------------


class TestOnModified:
    """Tests for BranchLogWatcher.on_modified."""

    def test_skips_directory_events(self):
        """Directory events are ignored by on_modified."""
        lw = _import_log_watcher()
        watcher = lw.BranchLogWatcher()
        watcher._read_new_lines = MagicMock()
        event = MagicMock()
        event.is_directory = True
        event.src_path = "/some/dir"
        watcher.on_modified(event)
        watcher._read_new_lines.assert_not_called()

    def test_skips_excluded_files(self):
        """Files that fail _should_process are not read."""
        lw = _import_log_watcher()
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
        lw = _import_log_watcher()
        watcher = lw.BranchLogWatcher()
        watcher._should_process = MagicMock(return_value=True)
        watcher._read_new_lines = MagicMock()
        event = MagicMock()
        event.is_directory = False
        event.src_path = "/some/branch/logs/core.log"
        watcher.on_modified(event)
        watcher._read_new_lines.assert_called_once_with("/some/branch/logs/core.log")

    def test_handles_read_exception(self):
        """IOError during _read_new_lines is handled without raising."""
        lw = _import_log_watcher()
        watcher = lw.BranchLogWatcher()
        watcher._should_process = MagicMock(return_value=True)
        watcher._read_new_lines = MagicMock(side_effect=IOError("disk error"))
        event = MagicMock()
        event.is_directory = False
        event.src_path = "/some/core.log"
        watcher.on_modified(event)


# ---------------------------------------------------------------------------
# Tests -- initialize_positions
# ---------------------------------------------------------------------------


class TestInitializePositions:
    """Tests for BranchLogWatcher.initialize_positions."""

    def test_snaps_to_eof_when_no_persisted(self, tmp_path):
        """Without persisted positions, snaps all log files to EOF."""
        lw = _import_log_watcher()
        lw.AIPASS_PKG_ROOT = tmp_path / "aipass"
        lw.SYSTEM_LOGS_DIR = tmp_path / "system_logs"
        lw._load_log_positions = MagicMock(return_value={})
        branch_logs = tmp_path / "aipass" / "flow" / "logs"
        branch_logs.mkdir(parents=True)
        log_file = branch_logs / "core.log"
        log_file.write_text("line1\nline2\n")
        watcher = lw.BranchLogWatcher()
        watcher.initialize_positions()
        assert watcher.log_positions[str(log_file)] == log_file.stat().st_size

    def test_uses_persisted_position_when_valid(self, tmp_path):
        """Restores a persisted position that is within current file size."""
        lw = _import_log_watcher()
        lw.AIPASS_PKG_ROOT = tmp_path / "aipass"
        lw.SYSTEM_LOGS_DIR = tmp_path / "system_logs"
        branch_logs = tmp_path / "aipass" / "flow" / "logs"
        branch_logs.mkdir(parents=True)
        log_file = branch_logs / "core.log"
        log_file.write_text("line1\nline2\n")
        saved_pos = 5
        lw._load_log_positions = MagicMock(return_value={str(log_file): saved_pos})
        watcher = lw.BranchLogWatcher()
        watcher.initialize_positions()
        assert watcher.log_positions[str(log_file)] == saved_pos

    def test_snaps_to_eof_when_persisted_beyond_size(self, tmp_path):
        """Resets to EOF when persisted position exceeds current file size."""
        lw = _import_log_watcher()
        lw.AIPASS_PKG_ROOT = tmp_path / "aipass"
        lw.SYSTEM_LOGS_DIR = tmp_path / "system_logs"
        branch_logs = tmp_path / "aipass" / "flow" / "logs"
        branch_logs.mkdir(parents=True)
        log_file = branch_logs / "core.log"
        log_file.write_text("short")
        lw._load_log_positions = MagicMock(return_value={str(log_file): 999999})
        watcher = lw.BranchLogWatcher()
        watcher.initialize_positions()
        assert watcher.log_positions[str(log_file)] == log_file.stat().st_size

    def test_skips_branches_without_logs_dir(self, tmp_path):
        """Branch directories without a logs/ subdirectory are skipped."""
        lw = _import_log_watcher()
        lw.AIPASS_PKG_ROOT = tmp_path / "aipass"
        lw.SYSTEM_LOGS_DIR = tmp_path / "system_logs"
        lw._load_log_positions = MagicMock(return_value={})
        (tmp_path / "aipass" / "nologs").mkdir(parents=True)
        watcher = lw.BranchLogWatcher()
        watcher.initialize_positions()
        assert len(watcher.log_positions) == 0

    def test_initializes_system_logs(self, tmp_path):
        """System log files are initialized to EOF during position setup."""
        lw = _import_log_watcher()
        lw.AIPASS_PKG_ROOT = tmp_path / "aipass"
        (tmp_path / "aipass").mkdir(parents=True)
        sys_logs = tmp_path / "system_logs"
        sys_logs.mkdir()
        lw.SYSTEM_LOGS_DIR = sys_logs
        log_file = sys_logs / "app.log"
        log_file.write_text("data here\n")
        lw._load_log_positions = MagicMock(return_value={})
        watcher = lw.BranchLogWatcher()
        watcher.initialize_positions()
        assert watcher.log_positions[str(log_file)] == log_file.stat().st_size


# ---------------------------------------------------------------------------
# Tests -- _load_seen_hashes
# ---------------------------------------------------------------------------


class TestLoadSeenHashes:
    """Tests for _load_seen_hashes persistence."""

    def test_loads_from_existing_file(self, tmp_path):
        """Loads hashes from a valid trigger_data.json file."""
        lw = _import_log_watcher()
        data_file = tmp_path / "trigger_data.json"
        data_file.write_text(
            json.dumps({"seen_error_hashes": ["aaa", "bbb"]}),
            encoding="utf-8",
        )
        lw.TRIGGER_DATA_FILE = data_file
        lw._seen_error_hashes = set()
        lw._load_seen_hashes()
        assert lw._seen_error_hashes == {"aaa", "bbb"}

    def test_handles_missing_file(self, tmp_path):
        """Missing file leaves _seen_error_hashes unchanged (no crash)."""
        lw = _import_log_watcher()
        lw.TRIGGER_DATA_FILE = tmp_path / "nonexistent.json"
        lw._seen_error_hashes = {"existing"}
        lw._load_seen_hashes()
        assert lw._seen_error_hashes == {"existing"}

    def test_handles_corrupt_json(self, tmp_path):
        """Corrupt JSON resets _seen_error_hashes to empty set."""
        lw = _import_log_watcher()
        data_file = tmp_path / "trigger_data.json"
        data_file.write_text("{invalid json", encoding="utf-8")
        lw.TRIGGER_DATA_FILE = data_file
        lw._seen_error_hashes = {"leftovers"}
        lw._load_seen_hashes()
        assert lw._seen_error_hashes == set()

    def test_handles_missing_key(self, tmp_path):
        """File exists but has no seen_error_hashes key -- loads empty."""
        lw = _import_log_watcher()
        data_file = tmp_path / "trigger_data.json"
        data_file.write_text(json.dumps({"other_key": 1}), encoding="utf-8")
        lw.TRIGGER_DATA_FILE = data_file
        lw._seen_error_hashes = {"old"}
        lw._load_seen_hashes()
        assert lw._seen_error_hashes == set()


# ---------------------------------------------------------------------------
# Tests -- _save_seen_hashes
# ---------------------------------------------------------------------------


class TestSaveSeenHashes:
    """Tests for _save_seen_hashes persistence."""

    def test_saves_to_new_file(self, tmp_path):
        """Creates trigger_data.json when it does not exist yet."""
        lw = _import_log_watcher()
        data_file = tmp_path / "trigger_data.json"
        lw.TRIGGER_DATA_FILE = data_file
        lw._seen_error_hashes = {"hash1", "hash2"}
        lw._save_seen_hashes()
        written = json.loads(data_file.read_text(encoding="utf-8"))
        assert set(written["seen_error_hashes"]) == {"hash1", "hash2"}

    def test_merges_with_existing_data(self, tmp_path):
        """Preserves other keys already in trigger_data.json."""
        lw = _import_log_watcher()
        data_file = tmp_path / "trigger_data.json"
        data_file.write_text(
            json.dumps({"log_positions": {"/a.log": 100}}),
            encoding="utf-8",
        )
        lw.TRIGGER_DATA_FILE = data_file
        lw._seen_error_hashes = {"x"}
        lw._save_seen_hashes()
        written = json.loads(data_file.read_text(encoding="utf-8"))
        assert written["log_positions"] == {"/a.log": 100}
        assert written["seen_error_hashes"] == ["x"]

    def test_handles_write_error(self, tmp_path):
        """Write failure logs warning but does not raise."""
        lw = _import_log_watcher()
        bad_path = tmp_path / "nope" / "nope" / "trigger_data.json"
        lw.TRIGGER_DATA_FILE = bad_path
        lw._seen_error_hashes = {"z"}
        with patch.object(lw, "atomic_write_json", side_effect=PermissionError("denied")):
            lw._save_seen_hashes()


# ---------------------------------------------------------------------------
# Tests -- _load_log_positions
# ---------------------------------------------------------------------------


class TestLoadLogPositions:
    """Tests for _load_log_positions persistence."""

    def test_loads_positions_from_file(self, tmp_path):
        """Returns positions dict when trigger_data.json has log_positions."""
        lw = _import_log_watcher()
        data_file = tmp_path / "trigger_data.json"
        data_file.write_text(
            json.dumps({"log_positions": {"/a.log": 42, "/b.log": 99}}),
            encoding="utf-8",
        )
        lw.TRIGGER_DATA_FILE = data_file
        result = lw._load_log_positions()
        assert result == {"/a.log": 42, "/b.log": 99}

    def test_returns_empty_for_missing_file(self, tmp_path):
        """Returns empty dict when file does not exist."""
        lw = _import_log_watcher()
        lw.TRIGGER_DATA_FILE = tmp_path / "nonexistent.json"
        assert lw._load_log_positions() == {}

    def test_returns_empty_for_corrupt_json(self, tmp_path):
        """Returns empty dict when file has corrupt JSON."""
        lw = _import_log_watcher()
        data_file = tmp_path / "trigger_data.json"
        data_file.write_text("not json!", encoding="utf-8")
        lw.TRIGGER_DATA_FILE = data_file
        assert lw._load_log_positions() == {}

    def test_returns_empty_when_positions_not_dict(self, tmp_path):
        """Returns empty dict when log_positions is not a dict."""
        lw = _import_log_watcher()
        data_file = tmp_path / "trigger_data.json"
        data_file.write_text(
            json.dumps({"log_positions": "not_a_dict"}),
            encoding="utf-8",
        )
        lw.TRIGGER_DATA_FILE = data_file
        assert lw._load_log_positions() == {}

    def test_coerces_values_to_int(self, tmp_path):
        """String position values are coerced to int."""
        lw = _import_log_watcher()
        data_file = tmp_path / "trigger_data.json"
        data_file.write_text(
            json.dumps({"log_positions": {"/x.log": "123"}}),
            encoding="utf-8",
        )
        lw.TRIGGER_DATA_FILE = data_file
        result = lw._load_log_positions()
        assert result["/x.log"] == 123
        assert isinstance(result["/x.log"], int)


# ---------------------------------------------------------------------------
# Tests -- _save_log_positions
# ---------------------------------------------------------------------------


class TestSaveLogPositions:
    """Tests for _save_log_positions persistence."""

    def test_saves_positions_to_new_file(self, tmp_path):
        """Creates file with log_positions key."""
        lw = _import_log_watcher()
        data_file = tmp_path / "trigger_data.json"
        lw.TRIGGER_DATA_FILE = data_file
        lw._save_log_positions({"/a.log": 50})
        written = json.loads(data_file.read_text(encoding="utf-8"))
        assert written["log_positions"] == {"/a.log": 50}

    def test_merges_with_existing_data(self, tmp_path):
        """Preserves other keys in trigger_data.json."""
        lw = _import_log_watcher()
        data_file = tmp_path / "trigger_data.json"
        data_file.write_text(
            json.dumps({"seen_error_hashes": ["abc"]}),
            encoding="utf-8",
        )
        lw.TRIGGER_DATA_FILE = data_file
        lw._save_log_positions({"/b.log": 77})
        written = json.loads(data_file.read_text(encoding="utf-8"))
        assert written["seen_error_hashes"] == ["abc"]
        assert written["log_positions"] == {"/b.log": 77}

    def test_handles_write_error(self, tmp_path):
        """Write failure logs warning but does not raise."""
        lw = _import_log_watcher()
        lw.TRIGGER_DATA_FILE = tmp_path / "trigger_data.json"
        with patch.object(lw, "atomic_write_json", side_effect=OSError("disk full")):
            lw._save_log_positions({"/c.log": 10})


# ---------------------------------------------------------------------------
# Tests -- log_inodes persistence (parallel key, backward compatible)
# ---------------------------------------------------------------------------


class TestLogInodesPersistence:
    """Tests for the 'log_inodes' key alongside 'log_positions'."""

    def test_save_and_load_round_trip(self, tmp_path):
        """Positions and inodes round-trip through trigger_data.json."""
        lw = _import_log_watcher()
        data_file = tmp_path / "trigger_data.json"
        lw.TRIGGER_DATA_FILE = data_file

        lw._save_log_positions({"/a.log": 50}, {"/a.log": 4242})

        assert lw._load_log_positions() == {"/a.log": 50}
        assert lw._load_log_inodes() == {"/a.log": 4242}

    def test_position_shape_unchanged(self, tmp_path):
        """log_positions stays a plain Dict[str, int] - inodes live elsewhere."""
        lw = _import_log_watcher()
        data_file = tmp_path / "trigger_data.json"
        lw.TRIGGER_DATA_FILE = data_file

        lw._save_log_positions({"/a.log": 50}, {"/a.log": 4242})

        written = json.loads(data_file.read_text(encoding="utf-8"))
        assert written["log_positions"] == {"/a.log": 50}
        assert written["log_inodes"] == {"/a.log": 4242}

    def test_old_format_state_loads_without_error(self, tmp_path):
        """State written before this change (no log_inodes) still loads."""
        lw = _import_log_watcher()
        data_file = tmp_path / "trigger_data.json"
        data_file.write_text(
            json.dumps({"log_positions": {"/a.log": 12}, "seen_error_hashes": ["abc"]}),
            encoding="utf-8",
        )
        lw.TRIGGER_DATA_FILE = data_file

        assert lw._load_log_positions() == {"/a.log": 12}
        assert lw._load_log_inodes() == {}

    def test_save_without_inodes_leaves_key_untouched(self, tmp_path):
        """Omitting inodes does not wipe an existing log_inodes key.

        No-overreach guard: passes with and without the fix - the old
        single-argument save path must keep working untouched.
        """
        lw = _import_log_watcher()
        data_file = tmp_path / "trigger_data.json"
        data_file.write_text(
            json.dumps({"log_inodes": {"/a.log": 7}}),
            encoding="utf-8",
        )
        lw.TRIGGER_DATA_FILE = data_file

        lw._save_log_positions({"/a.log": 50})

        written = json.loads(data_file.read_text(encoding="utf-8"))
        assert written["log_inodes"] == {"/a.log": 7}

    def test_load_returns_empty_for_missing_file(self, tmp_path):
        """Missing trigger_data.json yields an empty inode map."""
        lw = _import_log_watcher()
        lw.TRIGGER_DATA_FILE = tmp_path / "nope.json"
        assert lw._load_log_inodes() == {}

    def test_load_returns_empty_when_not_dict(self, tmp_path):
        """Non-dict log_inodes value is ignored."""
        lw = _import_log_watcher()
        data_file = tmp_path / "trigger_data.json"
        data_file.write_text(json.dumps({"log_inodes": "nope"}), encoding="utf-8")
        lw.TRIGGER_DATA_FILE = data_file
        assert lw._load_log_inodes() == {}

    def test_flush_persists_inodes(self, tmp_path):
        """_flush_trigger_data writes the watcher's inodes to disk."""
        lw = _import_log_watcher()
        data_file = tmp_path / "trigger_data.json"
        lw.TRIGGER_DATA_FILE = data_file
        lw._data_dirty = True
        lw._active_watcher = MagicMock()
        lw._active_watcher.log_positions = {"/x.log": 42}
        lw._active_watcher.log_inodes = {"/x.log": 909}
        lw._seen_error_hashes = set()

        lw._flush_trigger_data(force=True)

        assert lw._load_log_inodes() == {"/x.log": 909}

    def test_initialize_positions_records_inodes(self, tmp_path):
        """initialize_positions records an inode for every tracked file."""
        lw = _import_log_watcher()
        lw.AIPASS_PKG_ROOT = tmp_path / "aipass"
        lw.SYSTEM_LOGS_DIR = tmp_path / "system_logs"
        lw._load_log_positions = MagicMock(return_value={})
        branch_logs = tmp_path / "aipass" / "flow" / "logs"
        branch_logs.mkdir(parents=True)
        log_file = branch_logs / "core.log"
        log_file.write_text("line1\nline2\n")

        watcher = lw.BranchLogWatcher()
        watcher.initialize_positions()

        assert watcher.log_inodes[str(log_file)] == log_file.stat().st_ino

    def test_initialize_positions_with_old_state(self, tmp_path):
        """Old-format persisted state (no log_inodes) initializes cleanly."""
        lw = _import_log_watcher()
        data_file = tmp_path / "trigger_data.json"
        lw.TRIGGER_DATA_FILE = data_file
        lw.AIPASS_PKG_ROOT = tmp_path / "aipass"
        lw.SYSTEM_LOGS_DIR = tmp_path / "system_logs"
        branch_logs = tmp_path / "aipass" / "flow" / "logs"
        branch_logs.mkdir(parents=True)
        log_file = branch_logs / "core.log"
        log_file.write_text("line1\nline2\n")
        data_file.write_text(
            json.dumps({"log_positions": {str(log_file): 6}}),
            encoding="utf-8",
        )

        watcher = lw.BranchLogWatcher()
        watcher.initialize_positions()

        assert watcher.log_positions[str(log_file)] == 6
        assert watcher.log_inodes[str(log_file)] == log_file.stat().st_ino


# ---------------------------------------------------------------------------
# Tests -- debounced trigger_data.json writer
# ---------------------------------------------------------------------------


class TestDebouncedWriter:
    """Tests for time-based debounced coalesced writes to trigger_data.json."""

    def test_rapid_events_coalesce_into_one_write(self, tmp_path):
        """N rapid _mark_data_dirty calls produce at most 1 write within the interval."""
        lw = _import_log_watcher()
        data_file = tmp_path / "trigger_data.json"
        lw.TRIGGER_DATA_FILE = data_file
        lw._last_flush_time = 0.0
        lw._data_dirty = False
        lw._active_watcher = MagicMock()
        lw._active_watcher.log_positions = {"/a.log": 100}
        lw._active_watcher.log_inodes = {"/a.log": 111}

        write_count = 0
        real_write = lw.atomic_write_json

        def counting_write(path, data):
            """Wrapper that increments write_count on each call."""
            nonlocal write_count
            write_count += 1
            real_write(path, data)

        with patch.object(lw, "atomic_write_json", side_effect=counting_write):
            for _ in range(20):
                lw._mark_data_dirty()

        assert write_count == 1

    def test_flush_writes_both_positions_and_hashes(self, tmp_path):
        """_flush_trigger_data writes both log_positions and seen_error_hashes."""
        lw = _import_log_watcher()
        data_file = tmp_path / "trigger_data.json"
        lw.TRIGGER_DATA_FILE = data_file
        lw._data_dirty = True
        lw._active_watcher = MagicMock()
        lw._active_watcher.log_positions = {"/x.log": 42}
        lw._active_watcher.log_inodes = {"/x.log": 4242}
        lw._seen_error_hashes = {"hash1", "hash2"}

        lw._flush_trigger_data(force=True)

        data = json.loads(data_file.read_text(encoding="utf-8"))
        assert data["log_positions"] == {"/x.log": 42}
        assert set(data["seen_error_hashes"]) == {"hash1", "hash2"}

    def test_restart_survival(self, tmp_path):
        """Flushed data survives reload — positions and hashes intact."""
        lw = _import_log_watcher()
        data_file = tmp_path / "trigger_data.json"
        lw.TRIGGER_DATA_FILE = data_file
        lw._active_watcher = MagicMock()
        lw._active_watcher.log_positions = {"/srv.log": 999}
        lw._active_watcher.log_inodes = {"/srv.log": 777}
        lw._seen_error_hashes = {"abc", "def"}
        lw._data_dirty = True

        lw._flush_trigger_data(force=True)

        loaded_positions = lw._load_log_positions()
        assert loaded_positions == {"/srv.log": 999}

        lw._load_seen_hashes()
        assert lw._seen_error_hashes == {"abc", "def"}

    def test_force_flush_writes_even_when_not_dirty(self, tmp_path):
        """force=True writes regardless of _data_dirty flag."""
        lw = _import_log_watcher()
        data_file = tmp_path / "trigger_data.json"
        lw.TRIGGER_DATA_FILE = data_file
        lw._data_dirty = False
        lw._active_watcher = MagicMock()
        lw._active_watcher.log_positions = {"/f.log": 10}
        lw._active_watcher.log_inodes = {"/f.log": 1010}
        lw._seen_error_hashes = set()

        lw._flush_trigger_data(force=True)

        assert data_file.exists()
        data = json.loads(data_file.read_text(encoding="utf-8"))
        assert data["log_positions"] == {"/f.log": 10}

    def test_dirty_flag_cleared_after_flush(self):
        """_data_dirty is False after a successful flush."""
        lw = _import_log_watcher()
        lw._data_dirty = True
        lw._active_watcher = None
        with patch.object(lw, "atomic_write_json"):
            lw._flush_trigger_data(force=True)
        assert lw._data_dirty is False

    def test_stop_watcher_forces_flush(self, tmp_path):
        """stop_branch_log_watcher calls _flush_trigger_data(force=True)."""
        lw = _import_log_watcher()
        mock_watcher = MagicMock()
        mock_watcher.log_positions = {"/a.log": 50}
        lw._active_watcher = mock_watcher
        lw._branch_log_observer = MagicMock()
        lw._branch_log_observer.is_alive.return_value = True

        with patch.object(lw, "_flush_trigger_data") as mock_flush:
            lw.stop_branch_log_watcher()
            mock_flush.assert_called_once_with(force=True)


# ---------------------------------------------------------------------------
# Tests -- _is_stale_entry (additional format coverage)
# ---------------------------------------------------------------------------


class TestIsStaleEntryFormats:
    """Additional format coverage for _is_stale_entry."""

    def test_iso_format_with_microseconds_fresh(self):
        """ISO format with microseconds: T separator and dot microseconds."""
        lw = _import_log_watcher()
        recent = datetime.now() - timedelta(seconds=5)
        ts = recent.strftime("%Y-%m-%dT%H:%M:%S.%f")
        assert lw._is_stale_entry(ts) is False

    def test_iso_format_simple_stale(self):
        """ISO format without microseconds, stale timestamp."""
        lw = _import_log_watcher()
        old = datetime.now() - timedelta(seconds=600)
        ts = old.strftime("%Y-%m-%dT%H:%M:%S")
        assert lw._is_stale_entry(ts) is True

    def test_simple_format_no_microseconds_fresh(self):
        """Simple YYYY-MM-DD HH:MM:SS format, fresh."""
        lw = _import_log_watcher()
        recent = datetime.now() - timedelta(seconds=2)
        ts = recent.strftime("%Y-%m-%d %H:%M:%S")
        assert lw._is_stale_entry(ts) is False

    def test_whitespace_stripped(self):
        """Leading/trailing whitespace is stripped before parsing."""
        lw = _import_log_watcher()
        recent = datetime.now() - timedelta(seconds=5)
        ts = "  " + recent.strftime("%Y-%m-%d %H:%M:%S.%f") + "  "
        assert lw._is_stale_entry(ts) is False

    def test_empty_string_returns_true(self):
        """Empty string is unparseable and treated as stale."""
        lw = _import_log_watcher()
        assert lw._is_stale_entry("") is True


# ---------------------------------------------------------------------------
# Tests -- _detect_branch_from_path (additional edge cases)
# ---------------------------------------------------------------------------


class TestDetectBranchFromPathEdgeCases:
    """Additional edge cases for _detect_branch_from_path."""

    def test_pycache_directory_ignored(self):
        """__pycache__ after aipass/ is not treated as a branch."""
        lw = _import_log_watcher()
        path = str(Path("/home/user/src") / "aipass" / "__pycache__" / "logs" / "something.log")
        assert lw._detect_branch_from_path(path) == "UNKNOWN"

    def test_system_logs_unknown_file(self):
        """Unknown file in system_logs returns UNKNOWN."""
        lw = _import_log_watcher()
        path = str(lw.SYSTEM_LOGS_DIR / "completely_random.log")
        assert lw._detect_branch_from_path(path) == "UNKNOWN"

    def test_multiple_aipass_segments(self):
        """First valid aipass/branch/logs/ match wins."""
        lw = _import_log_watcher()
        path = str(Path("/src") / "aipass" / "trigger" / "logs" / "inner.log")
        assert lw._detect_branch_from_path(path) == "TRIGGER"

    def test_aipass_without_logs_subdir(self):
        """aipass/branch without /logs/ segment returns UNKNOWN."""
        lw = _import_log_watcher()
        path = str(Path("/src") / "aipass" / "drone" / "core.log")
        assert lw._detect_branch_from_path(path) == "UNKNOWN"

    def test_system_logs_ai_mail_prefix(self):
        """Multi-word prefix (ai_mail) is matched correctly."""
        lw = _import_log_watcher()
        path = str(lw.SYSTEM_LOGS_DIR / "ai_mail_delivery.log")
        assert lw._detect_branch_from_path(path) == "AI_MAIL"


# ---------------------------------------------------------------------------
# Tests -- _parse_prax_log_line (additional edge cases)
# ---------------------------------------------------------------------------


class TestParsePraxLogLineEdgeCases:
    """Additional edge cases for _parse_prax_log_line."""

    def test_dash_format_critical(self):
        """Dash format with CRITICAL level is accepted."""
        lw = _import_log_watcher()
        line = "2026-04-26 10:00:00,100 - core - CRITICAL - System down"
        result = lw._parse_prax_log_line(line)
        assert result is not None
        assert result["level"] == "CRITICAL"
        assert result["module"] == "core"
        assert result["message"] == "System down"

    def test_dash_format_info_returns_none(self):
        """Dash format with INFO level returns None."""
        lw = _import_log_watcher()
        line = "2026-04-26 10:00:00,100 - core - INFO - All is well"
        assert lw._parse_prax_log_line(line) is None

    def test_pipe_format_too_few_parts(self):
        """Pipe format with fewer than 4 parts returns None."""
        lw = _import_log_watcher()
        line = "2026-04-26 10:00:00 | only_two_parts"
        assert lw._parse_prax_log_line(line) is None

    def test_dash_format_too_few_parts(self):
        """Dash format with fewer than 4 parts returns None."""
        lw = _import_log_watcher()
        line = "2026-04-26 - module_only"
        assert lw._parse_prax_log_line(line) is None

    def test_pipe_format_warning_level_returns_none(self):
        """Pipe format with WARNING level (not error) returns None."""
        lw = _import_log_watcher()
        line = "2026-04-26 10:00:00 | mod | WARNING | caution"
        assert lw._parse_prax_log_line(line) is None

    def test_dash_format_debug_level_returns_none(self):
        """Dash format with DEBUG level returns None."""
        lw = _import_log_watcher()
        line = "2026-04-26 10:00:00,100 - mod - DEBUG - tracing"
        assert lw._parse_prax_log_line(line) is None


# ---------------------------------------------------------------------------
# Tests -- BranchLogWatcher._should_process (additional edge cases)
# ---------------------------------------------------------------------------


class TestShouldProcessEdgeCases:
    """Additional edge cases for BranchLogWatcher._should_process."""

    def test_excluded_file_case_insensitive(self):
        """Exclusion matching is case-insensitive."""
        lw = _import_log_watcher()
        watcher = lw.BranchLogWatcher()
        path = str(Path("/src") / "aipass" / "flow" / "logs" / "DISPATCH.LOG")
        assert watcher._should_process(path) is False

    def test_non_log_extension_py(self):
        """.py file is rejected."""
        lw = _import_log_watcher()
        watcher = lw.BranchLogWatcher()
        path = str(Path("/src") / "aipass" / "flow" / "logs" / "handler.py")
        assert watcher._should_process(path) is False

    def test_excluded_trigger_log_watcher(self):
        """trigger_log_watcher.log is excluded (self-referential)."""
        lw = _import_log_watcher()
        watcher = lw.BranchLogWatcher()
        path = str(Path("/src") / "aipass" / "trigger" / "logs" / "trigger_log_watcher.log")
        assert watcher._should_process(path) is False

    def test_excluded_medic_suppressed(self):
        """medic_suppressed.jsonl is excluded."""
        lw = _import_log_watcher()
        watcher = lw.BranchLogWatcher()
        path = str(Path("/src") / "aipass" / "flow" / "logs" / "medic_suppressed.jsonl")
        assert watcher._should_process(path) is False


# ---------------------------------------------------------------------------
# Tests -- BranchLogWatcher._read_new_lines (deeper coverage)
# ---------------------------------------------------------------------------


class TestReadNewLinesDeeper:
    """Deeper coverage for BranchLogWatcher._read_new_lines."""

    def test_no_read_when_size_unchanged(self, tmp_path):
        """When file size equals last position, no reading occurs."""
        lw = _import_log_watcher()
        watcher = lw.BranchLogWatcher()
        log_file = tmp_path / "unchanged.log"
        log_file.write_text("content\n", encoding="utf-8")
        file_path = str(log_file)
        current_size = log_file.stat().st_size
        watcher.log_positions[file_path] = current_size

        watcher._process_log_line = MagicMock()
        with patch.object(lw, "_mark_data_dirty"):
            watcher._read_new_lines(file_path)

        watcher._process_log_line.assert_not_called()
        assert watcher.log_positions[file_path] == current_size

    def test_debounce_flushes_when_interval_elapsed(self, tmp_path):
        """_flush_trigger_data fires when flush interval has elapsed."""
        lw = _import_log_watcher()
        watcher = lw.BranchLogWatcher()
        log_file = tmp_path / "interval.log"
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
        log_file.write_text(f"{now} | mod | ERROR | fail\n", encoding="utf-8")
        file_path = str(log_file)
        watcher.log_positions[file_path] = 0

        lw._last_flush_time = 0.0
        with patch.object(lw, "_flush_trigger_data") as mock_flush:
            watcher._read_new_lines(file_path)
            mock_flush.assert_called_once()

    def test_debounce_skips_flush_within_interval(self, tmp_path):
        """_flush_trigger_data is NOT called when within flush interval."""
        lw = _import_log_watcher()
        import time

        watcher = lw.BranchLogWatcher()
        log_file = tmp_path / "notsaved.log"
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
        log_file.write_text(f"{now} | mod | ERROR | fail\n", encoding="utf-8")
        file_path = str(log_file)
        watcher.log_positions[file_path] = 0

        lw._last_flush_time = time.monotonic()
        with patch.object(lw, "_flush_trigger_data") as mock_flush:
            watcher._read_new_lines(file_path)
            mock_flush.assert_not_called()
        assert lw._data_dirty is True

    def test_blank_lines_are_skipped(self, tmp_path):
        """Blank lines in new content do not trigger _process_log_line."""
        lw = _import_log_watcher()
        watcher = lw.BranchLogWatcher()
        log_file = tmp_path / "blanks.log"
        log_file.write_text("\n\n\n", encoding="utf-8")
        file_path = str(log_file)
        watcher.log_positions[file_path] = 0

        watcher._process_log_line = MagicMock()
        with patch.object(lw, "_mark_data_dirty"):
            watcher._read_new_lines(file_path)
        watcher._process_log_line.assert_not_called()

    def test_file_truncated_resets_position(self, tmp_path):
        """When file is smaller than stored position, resets to 0."""
        lw = _import_log_watcher()
        watcher = lw.BranchLogWatcher()
        log_file = tmp_path / "truncated.log"
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
        log_file.write_text(f"{now} | mod | ERROR | after rotation\n", encoding="utf-8")
        file_path = str(log_file)
        watcher.log_positions[file_path] = 99999

        watcher._process_log_line = MagicMock()
        with patch.object(lw, "_mark_data_dirty"):
            watcher._read_new_lines(file_path)

        watcher._process_log_line.assert_called_once()


# ---------------------------------------------------------------------------
# Tests -- BranchLogWatcher._process_log_line (deeper coverage)
# ---------------------------------------------------------------------------

_BRANCH_LOG_PATH = str(Path("/src") / "aipass" / "flow" / "logs" / "flow.log")


class TestProcessLogLineDeeper:
    """Deeper coverage for BranchLogWatcher._process_log_line."""

    def _make_error_line(self, message: str = "Something broke") -> str:
        """Build a fresh ERROR line with current timestamp."""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
        return f"{now} | test_mod | ERROR | {message}"

    def test_non_error_line_returns_early(self):
        """INFO-level line parsed as None, no event fired."""
        lw = _import_log_watcher()
        fire = MagicMock()
        lw.set_event_callback(fire)
        watcher = lw.BranchLogWatcher()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
        watcher._process_log_line(f"{now} | mod | INFO | Fine", "/a.log")
        fire.assert_not_called()

    def test_semantic_exclusion_error_hash(self):
        """Line containing 'error_hash' in message is skipped."""
        lw = _import_log_watcher()
        fire = MagicMock()
        lw.set_event_callback(fire)
        watcher = lw.BranchLogWatcher()
        line = self._make_error_line("Processed error error_hash=abc123")
        watcher._process_log_line(line, _BRANCH_LOG_PATH)
        fire.assert_not_called()

    def test_semantic_exclusion_fingerprint(self):
        """Line containing 'fingerprint' in message is skipped."""
        lw = _import_log_watcher()
        fire = MagicMock()
        lw.set_event_callback(fire)
        watcher = lw.BranchLogWatcher()
        line = self._make_error_line("Error with fingerprint=xyz789")
        watcher._process_log_line(line, _BRANCH_LOG_PATH)
        fire.assert_not_called()

    def test_semantic_exclusion_registry_id(self):
        """Line containing 'registry_id' in message is skipped."""
        lw = _import_log_watcher()
        fire = MagicMock()
        lw.set_event_callback(fire)
        watcher = lw.BranchLogWatcher()
        line = self._make_error_line("Logged with registry_id=r001")
        watcher._process_log_line(line, _BRANCH_LOG_PATH)
        fire.assert_not_called()

    def test_stale_entry_skipped(self):
        """Line with old timestamp is skipped."""
        lw = _import_log_watcher()
        fire = MagicMock()
        lw.set_event_callback(fire)
        watcher = lw.BranchLogWatcher()
        old = (datetime.now() - timedelta(seconds=600)).strftime("%Y-%m-%d %H:%M:%S.%f")
        line = f"{old} | mod | ERROR | Old error"
        watcher._process_log_line(line, _BRANCH_LOG_PATH)
        fire.assert_not_called()

    def test_registry_path_fires_event_with_registry_data(self):
        """Registry available: fires event with registry metadata."""
        lw = _import_log_watcher()
        fire = MagicMock()
        lw.set_event_callback(fire)
        lw._REGISTRY_AVAILABLE = True

        mock_report = MagicMock(
            return_value={
                "is_new": True,
                "count": 1,
                "id": "reg123",
                "fingerprint": "fp456",
                "first_seen": "2026-04-26",
                "last_seen": "2026-04-26",
            }
        )
        lw.registry_report = mock_report

        watcher = lw.BranchLogWatcher()
        line = self._make_error_line("DB connection lost")
        watcher._process_log_line(line, _BRANCH_LOG_PATH)

        fire.assert_called_once()
        call_kwargs = fire.call_args[1]
        assert call_kwargs["branch"] == "FLOW"
        assert call_kwargs["message"] == "DB connection lost"
        assert call_kwargs["registry_id"] == "reg123"
        assert call_kwargs["fingerprint"] == "fp456"
        assert call_kwargs["count"] == 1

    def test_registry_path_fire_event_none_logs_warning(self):
        """Registry available but _fire_event is None: logs warning."""
        lw = _import_log_watcher()
        lw._fire_event = None
        lw._REGISTRY_AVAILABLE = True

        mock_report = MagicMock(
            return_value={
                "is_new": True,
                "count": 1,
                "id": "reg999",
            }
        )
        lw.registry_report = mock_report

        watcher = lw.BranchLogWatcher()
        line = self._make_error_line("No callback set")
        watcher._process_log_line(line, _BRANCH_LOG_PATH)

    def test_registry_report_exception_falls_to_fallback(self):
        """Registry report raises: falls through to fallback path."""
        lw = _import_log_watcher()
        fire = MagicMock()
        lw.set_event_callback(fire)
        lw._REGISTRY_AVAILABLE = True

        lw.registry_report = MagicMock(side_effect=RuntimeError("registry down"))

        with patch.dict(
            sys.modules,
            {"aipass.trigger.apps.handlers.error_registry": None},
        ):
            watcher = lw.BranchLogWatcher()
            lw._fallback_error_counts.clear()
            line = self._make_error_line("Fallback triggered")
            watcher._process_log_line(line, _BRANCH_LOG_PATH)

        fire.assert_called_once()
        call_kwargs = fire.call_args[1]
        assert call_kwargs["message"] == "Fallback triggered"
        assert call_kwargs["count"] == 1

    def test_fallback_lazy_import_succeeds(self):
        """Fallback path: lazy import succeeds, fires event."""
        lw = _import_log_watcher()
        fire = MagicMock()
        lw.set_event_callback(fire)
        lw._REGISTRY_AVAILABLE = False

        watcher = lw.BranchLogWatcher()
        line = self._make_error_line("Lazy import works")
        watcher._process_log_line(line, _BRANCH_LOG_PATH)

        fire.assert_called_once()
        call_kwargs = fire.call_args[1]
        assert call_kwargs["message"] == "Lazy import works"

    def test_local_count_tracking_increments(self):
        """Local count path: repeated errors increment counter."""
        lw = _import_log_watcher()
        fire = MagicMock()
        lw.set_event_callback(fire)
        lw._REGISTRY_AVAILABLE = True
        lw.registry_report = MagicMock(side_effect=RuntimeError("registry down"))
        lw._fallback_error_counts.clear()

        with patch.dict(
            sys.modules,
            {"aipass.trigger.apps.handlers.error_registry": None},
        ):
            watcher = lw.BranchLogWatcher()
            line = self._make_error_line("Repeated failure")
            watcher._process_log_line(line, _BRANCH_LOG_PATH)
            watcher._process_log_line(line, _BRANCH_LOG_PATH)

        assert fire.call_count == 2
        second_call = fire.call_args_list[1][1]
        assert second_call["count"] == 2

    def test_local_count_fire_event_none_logs_warning(self):
        """Local count with _fire_event=None: logs warning, no crash."""
        lw = _import_log_watcher()
        lw._fire_event = None
        lw._REGISTRY_AVAILABLE = True
        lw.registry_report = MagicMock(side_effect=RuntimeError("registry down"))
        lw._fallback_error_counts.clear()

        with patch.dict(
            sys.modules,
            {"aipass.trigger.apps.handlers.error_registry": None},
        ):
            watcher = lw.BranchLogWatcher()
            line = self._make_error_line("No callback at all")
            watcher._process_log_line(line, _BRANCH_LOG_PATH)

    def test_outer_exception_handler_catches_unexpected(self):
        """Outer try/except catches unexpected errors without raising."""
        lw = _import_log_watcher()
        fire = MagicMock()
        lw.set_event_callback(fire)
        watcher = lw.BranchLogWatcher()

        with patch.object(
            lw,
            "_parse_prax_log_line",
            side_effect=TypeError("boom"),
        ):
            watcher._process_log_line("any line", "/any/path.log")

        fire.assert_not_called()
