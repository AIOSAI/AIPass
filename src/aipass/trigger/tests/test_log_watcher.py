# =================== META ====================
# Name: test_log_watcher.py
# Description: Unit tests for branch log watcher event producer
# Version: 1.4.0
# Created: 2026-04-03
# Modified: 2026-09-28
# =============================================

"""Tests for the branch log watcher handler (apps/handlers/log_watcher.py)."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(covered_elsewhere) — the centralized system_logs watcher, in test_watchers_log_watcher.py
# seedgo: no-test-needed(covered_elsewhere) — the daemon that starts start_branch_log_watcher: its own tests
# seedgo: no-test-needed(external) — WatchdogObserver's event delivery is the watchdog package's

import json
import hashlib
from datetime import datetime, timedelta
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

import aipass.trigger.apps.handlers.error_registry as error_registry
import aipass.trigger.apps.handlers.json.config_loader as config_loader
import aipass.trigger.apps.handlers.log_watcher as lw


# Synthetic path roots. _detect_branch_from_path, _should_process and
# _classify_log_path parse a path STRING and never touch disk, so these are
# inputs under test, not locations — but a literal /home/user or /tmp prefix
# reads as an assumption about the machine, so the roots are built instead.
# The POSIX shape IS part of the contract: these functions split on aipass/
# and logs/ segments, so the separator must stay "/" on every platform.
_SYNTHETIC_HOME = PurePosixPath("/synthetic/home")
_SYNTHETIC_ELSEWHERE = PurePosixPath("/synthetic/elsewhere")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _mock_infrastructure(monkeypatch, tmp_path):
    """Replace every door the watcher opens onto live state, on the real module.

    The module is imported once, at the top. Each outward function and every
    path constant it writes is set here and put back by monkeypatch; the
    module-level state a fresh import used to reset is reset here too.
    """
    monkeypatch.setattr(lw, "logger", MagicMock())

    # log_operation appends to the LIVE trigger logs/.
    mock_json_handler = MagicMock()
    mock_json_handler.log_operation = MagicMock(return_value=True)
    monkeypatch.setattr(lw, "json_handler", mock_json_handler)

    # Built under tmp_path so every trigger_data.json flush the product makes
    # lands in this test's own directory, never the live watcher positions.
    fake_trigger_root = tmp_path / "fake_trigger_root"
    fake_trigger_root.mkdir()
    monkeypatch.setattr(lw, "TRIGGER_DATA_FILE", fake_trigger_root / "trigger_data.json")
    monkeypatch.setattr(lw, "AIPASS_PKG_ROOT", tmp_path / "fake_aipass_pkg")
    monkeypatch.setattr(lw, "SYSTEM_LOGS_DIR", tmp_path / "system_logs")

    # -- error registry: the import-time binding and the lazy fallback import
    # both answer from this recorder, never the LIVE registry.
    registry_answer = MagicMock(return_value={"is_new": True, "count": 1, "id": "abc123"})
    monkeypatch.setattr(lw, "registry_report", registry_answer)
    monkeypatch.setattr(lw, "_REGISTRY_AVAILABLE", True)
    monkeypatch.setattr(error_registry, "report", registry_answer)

    # -- the operator switch for WARNING capture: read lazily per line.
    monkeypatch.setattr(config_loader, "section", MagicMock(return_value={}))

    # -- watchdog: no real observer is ever armed over a directory.
    monkeypatch.setattr(lw, "WatchdogObserver", MagicMock())

    # -- module state a fresh import used to start from.
    monkeypatch.setattr(lw, "_branch_log_observer", None)
    monkeypatch.setattr(lw, "_active_watcher", None)
    monkeypatch.setattr(lw, "_seen_error_hashes", set())
    monkeypatch.setattr(lw, "_fallback_error_counts", {})
    monkeypatch.setattr(lw, "_data_dirty", False)
    monkeypatch.setattr(lw, "_last_flush_time", 0.0)
    monkeypatch.setattr(lw, "_branch_names_cache", (0.0, ()))
    monkeypatch.setattr(lw, "_fire_event", None)
    monkeypatch.setattr(lw, "_warning_capture_cache", (0.0, True))


# ---------------------------------------------------------------------------
# Tests -- _generate_error_hash
# ---------------------------------------------------------------------------


class TestGenerateErrorHash:
    """Tests for _generate_error_hash pure function."""

    def test_deterministic(self):
        """Same inputs always produce the same hash."""
        h1 = lw._generate_error_hash("mod_a", "something broke")
        h2 = lw._generate_error_hash("mod_a", "something broke")
        assert h1 == h2

    def test_length_is_8(self):
        """Hash is exactly 8 characters long."""
        h = lw._generate_error_hash("module", "message")
        assert len(h) == 8

    def test_different_inputs_different_hashes(self):
        """Different module/message combos produce different hashes."""
        h1 = lw._generate_error_hash("mod_a", "error one")
        h2 = lw._generate_error_hash("mod_b", "error two")
        assert h1 != h2

    def test_matches_md5_prefix(self):
        """Hash matches the first 8 chars of MD5(module:message)."""
        expected = hashlib.md5("mymod:mymsg".encode()).hexdigest()[:8]
        assert lw._generate_error_hash("mymod", "mymsg") == expected


# ---------------------------------------------------------------------------
# Tests -- _detect_branch_from_path
# ---------------------------------------------------------------------------


class TestDetectBranchFromPath:
    """Tests for _detect_branch_from_path."""

    def test_standard_branch_logs_path(self):
        """Detects branch from src/aipass/<branch>/logs/file.log pattern."""
        path = str(_SYNTHETIC_HOME / "src" / "aipass" / "flow" / "logs" / "flow_planner.log")
        assert lw._detect_branch_from_path(path) == "FLOW"

    def test_system_logs_mapped_file(self):
        """Uses SYSTEM_LOGS_BRANCH_MAP for known filenames."""
        path = str(lw.SYSTEM_LOGS_DIR / "telegram_bridge.log")
        assert lw._detect_branch_from_path(path) == "API"

    def test_system_logs_prefix_match(self):
        """Matches prefix against known branch prefixes for system_logs files."""
        path = str(lw.SYSTEM_LOGS_DIR / "seedgo_audit.log")
        assert lw._detect_branch_from_path(path) == "SEEDGO"

    def test_system_logs_exact_stem_match(self):
        """Matches when stem equals a known prefix exactly."""
        path = str(lw.SYSTEM_LOGS_DIR / "prax.log")
        assert lw._detect_branch_from_path(path) == "PRAX"

    def test_unknown_path_returns_unknown(self):
        """Returns UNKNOWN for paths that do not match any pattern."""
        assert lw._detect_branch_from_path(str(_SYNTHETIC_ELSEWHERE / "some" / "random" / "path.log")) == "UNKNOWN"

    def test_failure_raises_instead_of_answering_unknown(self):
        """A path it cannot read raises; it is not filed under the UNKNOWN branch.

        UNKNOWN is a real answer (a log outside every known tree), so a
        failure returned as UNKNOWN fired an error_detected event for a branch
        nobody owns. The caller, _process_log_line, contains the raise and
        skips that one line (test_outer_exception_handler_catches_unexpected).
        Mutant run: `Path(log_path or "")` (a swallowed failure) reddens this.
        """
        unreadable: Any = None
        with pytest.raises(TypeError):
            lw._detect_branch_from_path(unreadable)


# ---------------------------------------------------------------------------
# Tests -- _parse_prax_log_line
# ---------------------------------------------------------------------------


class TestParsePraxLogLine:
    """Tests for _parse_prax_log_line."""

    def test_pipe_format_error(self):
        """Parses pipe-separated ERROR line correctly."""
        line = "2026-03-01 12:00:00.123 | my_module | ERROR | Something failed"
        result = lw._parse_prax_log_line(line)
        assert result is not None
        assert result["level"] == "ERROR"
        assert result["module"] == "my_module"
        assert result["message"] == "Something failed"
        assert "2026-03-01" in result["timestamp"]

    def test_pipe_format_critical(self):
        """Parses pipe-separated CRITICAL line correctly."""
        line = "2026-03-01 12:00:00.123 | core | CRITICAL | Fatal error"
        result = lw._parse_prax_log_line(line)
        assert result is not None
        assert result["level"] == "CRITICAL"

    def test_pipe_format_info_returns_none(self):
        """INFO level lines are not returned (only ERROR/CRITICAL)."""
        line = "2026-03-01 12:00:00.123 | my_module | INFO | All good"
        assert lw._parse_prax_log_line(line) is None

    def test_pipe_format_warning_returns_none(self):
        """WARNING level lines are not returned."""
        line = "2026-03-01 12:00:00.123 | my_module | WARNING | Watch out"
        assert lw._parse_prax_log_line(line) is None

    def test_dash_format_error(self):
        """Parses dash-separated ERROR line (Python logging format)."""
        line = "2026-02-10 15:12:29,460 - telegram_bridge - ERROR - Connection lost"
        result = lw._parse_prax_log_line(line)
        assert result is not None
        assert result["level"] == "ERROR"
        assert result["module"] == "telegram_bridge"
        assert result["message"] == "Connection lost"

    def test_malformed_line_returns_none(self):
        """Malformed line that does not match any format returns None."""
        assert lw._parse_prax_log_line("just some random text") is None

    def test_empty_line_returns_none(self):
        """Empty line returns None."""
        assert lw._parse_prax_log_line("") is None

    def test_failure_raises_instead_of_answering_none(self):
        """A line it cannot read raises; None means "not an error line".

        Returning None on a failure made the line look like an ordinary
        INFO line. The callers, _process_log_line and _process_warning_line,
        contain the raise and skip that one line
        (test_outer_exception_handler_catches_unexpected,
        test_unexpected_failure_is_contained).
        Mutant run: `if log_line is None: return None` ahead of the parse reddens this.
        """
        unreadable: Any = None
        with pytest.raises(TypeError):
            lw._parse_prax_log_line(unreadable)


# ---------------------------------------------------------------------------
# Tests -- _is_stale_entry
# ---------------------------------------------------------------------------


class TestIsStaleEntry:
    """Tests for _is_stale_entry."""

    def test_recent_timestamp_not_stale(self):
        """A timestamp within the threshold is NOT stale."""
        now = datetime.now()
        recent = now - timedelta(seconds=10)
        ts = recent.strftime("%Y-%m-%d %H:%M:%S.%f")
        assert lw._is_stale_entry(ts) is False

    def test_old_timestamp_is_stale(self):
        """A timestamp well beyond the threshold IS stale."""
        old = datetime.now() - timedelta(seconds=600)
        ts = old.strftime("%Y-%m-%d %H:%M:%S.%f")
        assert lw._is_stale_entry(ts) is True

    def test_unparseable_timestamp_returns_true(self):
        """An unparseable timestamp is treated as stale."""
        assert lw._is_stale_entry("not-a-timestamp") is True

    def test_comma_microsecond_format(self):
        """Python logging format with comma microseconds is parsed correctly."""
        recent = datetime.now() - timedelta(seconds=5)
        ts = recent.strftime("%Y-%m-%d %H:%M:%S,") + "123"
        assert lw._is_stale_entry(ts) is False


# ---------------------------------------------------------------------------
# Tests -- set_event_callback / clear_seen_hashes
# ---------------------------------------------------------------------------


class TestCallbackAndState:
    """Tests for set_event_callback and clear_seen_hashes."""

    def test_set_event_callback_sets_callback(self):
        """The last callback set receives the watcher's events; the one it replaced hears nothing."""
        replaced = MagicMock()
        cb = MagicMock()
        lw.set_event_callback(replaced)
        lw.set_event_callback(cb)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
        lw.BranchLogWatcher()._process_log_line(f"{now} | my_module | ERROR | Disk full", _BRANCH_LOG_PATH)
        replaced.assert_not_called()
        assert cb.call_args[0][0] == "error_detected"

    def test_clear_seen_hashes_empties_set(self, monkeypatch):
        """clear_seen_hashes empties the set in memory and on disk (mutant: its flush dropped)."""
        lw.TRIGGER_DATA_FILE.write_text(json.dumps({"seen_error_hashes": ["test_hash"]}), encoding="utf-8")
        monkeypatch.setattr(lw, "_seen_error_hashes", {"test_hash"})
        lw.clear_seen_hashes()
        assert lw.get_watcher_status()["seen_hashes_count"] == 0
        assert json.loads(lw.TRIGGER_DATA_FILE.read_text(encoding="utf-8"))["seen_error_hashes"] == []


# ---------------------------------------------------------------------------
# Tests -- BranchLogWatcher._should_process
# ---------------------------------------------------------------------------


class TestShouldProcess:
    """Tests for BranchLogWatcher._should_process."""

    def test_log_file_in_branch_dir_accepted(self):
        """.log file inside /aipass/branch/logs/ is accepted."""
        watcher = lw.BranchLogWatcher()
        assert watcher._should_process(str(_SYNTHETIC_HOME / "src" / "aipass" / "flow" / "logs" / "flow.log")) is True

    def test_txt_file_rejected(self):
        """.txt file is rejected even if in the right directory."""
        watcher = lw.BranchLogWatcher()
        assert watcher._should_process(str(_SYNTHETIC_HOME / "src" / "aipass" / "flow" / "logs" / "notes.txt")) is False

    def test_excluded_file_rejected(self):
        """Excluded log files (e.g. dispatch.log) are rejected."""
        watcher = lw.BranchLogWatcher()
        assert (
            watcher._should_process(str(_SYNTHETIC_HOME / "src" / "aipass" / "flow" / "logs" / "dispatch.log")) is False
        )

    def test_system_logs_accepted(self):
        """Log file inside /system_logs/ is accepted."""
        watcher = lw.BranchLogWatcher()
        assert watcher._should_process(str(_SYNTHETIC_HOME / "system_logs" / "prax.log")) is True

    def test_random_log_outside_known_dirs_rejected(self):
        """Log file outside branch and system_logs dirs is rejected."""
        watcher = lw.BranchLogWatcher()
        assert watcher._should_process(str(_SYNTHETIC_ELSEWHERE / "random" / "output.log")) is False


# ---------------------------------------------------------------------------
# Tests -- BranchLogWatcher._process_log_line
# ---------------------------------------------------------------------------


class TestProcessLogLine:
    """Tests for BranchLogWatcher._process_log_line."""

    def test_fires_event_on_new_error(self):
        """Fires error_detected event for a new ERROR line via registry path."""
        fire = MagicMock()
        lw.set_event_callback(fire)
        watcher = lw.BranchLogWatcher()

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
        line = f"{now} | my_module | ERROR | Database connection failed"
        log_path = str(_SYNTHETIC_HOME / "src" / "aipass" / "flow" / "logs" / "flow.log")

        watcher._process_log_line(line, log_path)

        fire.assert_called_once()
        call_args = fire.call_args
        assert call_args[0][0] == "error_detected"
        assert call_args[1]["message"] == "Database connection failed"

    def test_skips_semantic_exclusion_patterns(self):
        """Lines matching semantic exclusion patterns are skipped."""
        fire = MagicMock()
        lw.set_event_callback(fire)
        watcher = lw.BranchLogWatcher()

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
        line = f"{now} | handler | ERROR | Processed error error_hash=abc123"
        watcher._process_log_line(line, str(_SYNTHETIC_HOME / "src" / "aipass" / "flow" / "logs" / "flow.log"))

        fire.assert_not_called()

    def test_skips_stale_entries(self):
        """Lines with stale timestamps are skipped."""
        fire = MagicMock()
        lw.set_event_callback(fire)
        watcher = lw.BranchLogWatcher()

        old = (datetime.now() - timedelta(seconds=600)).strftime("%Y-%m-%d %H:%M:%S.%f")
        line = f"{old} | mod | ERROR | Old error"
        watcher._process_log_line(line, str(_SYNTHETIC_HOME / "src" / "aipass" / "flow" / "logs" / "flow.log"))

        fire.assert_not_called()

    def test_skips_non_error_lines(self):
        """INFO-level lines are not processed (parse returns None)."""
        fire = MagicMock()
        lw.set_event_callback(fire)
        watcher = lw.BranchLogWatcher()

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
        line = f"{now} | mod | INFO | All good"
        watcher._process_log_line(line, str(_SYNTHETIC_HOME / "src" / "aipass" / "flow" / "logs" / "flow.log"))

        fire.assert_not_called()


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
# Tests -- start / stop / is_active / get_status
# ---------------------------------------------------------------------------


class TestStartStopStatus:
    """Tests for start_branch_log_watcher, stop, is_active, get_watcher_status."""

    def test_start_returns_none_when_watchdog_unavailable(self, monkeypatch):
        """start_branch_log_watcher returns None when WATCHDOG_AVAILABLE is False."""
        monkeypatch.setattr(lw, "WATCHDOG_AVAILABLE", False)
        result = lw.start_branch_log_watcher()
        assert result is None

    def test_is_branch_log_watcher_active_returns_false_when_not_started(self, monkeypatch):
        """is_branch_log_watcher_active returns False when no observer is set."""
        monkeypatch.setattr(lw, "_branch_log_observer", None)
        assert lw.is_branch_log_watcher_active() is False

    def test_get_watcher_status_returns_correct_shape(self):
        """get_watcher_status returns a dict with all expected keys."""
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
# Tests -- initialize_positions
# ---------------------------------------------------------------------------


class TestInitializePositions:
    """Tests for BranchLogWatcher.initialize_positions."""

    def test_snaps_to_eof_when_no_persisted(self, tmp_path, monkeypatch):
        """Without persisted positions, snaps all log files to EOF."""
        monkeypatch.setattr(lw, "AIPASS_PKG_ROOT", tmp_path / "aipass")
        monkeypatch.setattr(lw, "SYSTEM_LOGS_DIR", tmp_path / "system_logs")
        monkeypatch.setattr(lw, "_load_log_positions", MagicMock(return_value={}))
        branch_logs = tmp_path / "aipass" / "flow" / "logs"
        branch_logs.mkdir(parents=True)
        log_file = branch_logs / "core.log"
        log_file.write_text("line1\nline2\n", encoding="utf-8")
        watcher = lw.BranchLogWatcher()
        watcher.initialize_positions()
        assert watcher.log_positions[str(log_file)] == log_file.stat().st_size

    def test_uses_persisted_position_when_valid(self, tmp_path, monkeypatch):
        """Restores a persisted position that is within current file size."""
        monkeypatch.setattr(lw, "AIPASS_PKG_ROOT", tmp_path / "aipass")
        monkeypatch.setattr(lw, "SYSTEM_LOGS_DIR", tmp_path / "system_logs")
        branch_logs = tmp_path / "aipass" / "flow" / "logs"
        branch_logs.mkdir(parents=True)
        log_file = branch_logs / "core.log"
        log_file.write_text("line1\nline2\n", encoding="utf-8")
        saved_pos = 5
        monkeypatch.setattr(lw, "_load_log_positions", MagicMock(return_value={str(log_file): saved_pos}))
        watcher = lw.BranchLogWatcher()
        watcher.initialize_positions()
        assert watcher.log_positions[str(log_file)] == saved_pos

    def test_snaps_to_eof_when_persisted_beyond_size(self, tmp_path, monkeypatch):
        """Resets to EOF when persisted position exceeds current file size."""
        monkeypatch.setattr(lw, "AIPASS_PKG_ROOT", tmp_path / "aipass")
        monkeypatch.setattr(lw, "SYSTEM_LOGS_DIR", tmp_path / "system_logs")
        branch_logs = tmp_path / "aipass" / "flow" / "logs"
        branch_logs.mkdir(parents=True)
        log_file = branch_logs / "core.log"
        log_file.write_text("short", encoding="utf-8")
        monkeypatch.setattr(lw, "_load_log_positions", MagicMock(return_value={str(log_file): 999999}))
        watcher = lw.BranchLogWatcher()
        watcher.initialize_positions()
        assert watcher.log_positions[str(log_file)] == log_file.stat().st_size

    def test_skips_branches_without_logs_dir(self, tmp_path, monkeypatch):
        """Branch directories without a logs/ subdirectory are skipped."""
        monkeypatch.setattr(lw, "AIPASS_PKG_ROOT", tmp_path / "aipass")
        monkeypatch.setattr(lw, "SYSTEM_LOGS_DIR", tmp_path / "system_logs")
        monkeypatch.setattr(lw, "_load_log_positions", MagicMock(return_value={}))
        (tmp_path / "aipass" / "nologs").mkdir(parents=True)
        watcher = lw.BranchLogWatcher()
        watcher.initialize_positions()
        assert len(watcher.log_positions) == 0

    def test_initializes_system_logs(self, tmp_path, monkeypatch):
        """System log files are initialized to EOF during position setup."""
        monkeypatch.setattr(lw, "AIPASS_PKG_ROOT", tmp_path / "aipass")
        (tmp_path / "aipass").mkdir(parents=True)
        sys_logs = tmp_path / "system_logs"
        sys_logs.mkdir()
        monkeypatch.setattr(lw, "SYSTEM_LOGS_DIR", sys_logs)
        log_file = sys_logs / "app.log"
        log_file.write_text("data here\n", encoding="utf-8")
        monkeypatch.setattr(lw, "_load_log_positions", MagicMock(return_value={}))
        watcher = lw.BranchLogWatcher()
        watcher.initialize_positions()
        assert watcher.log_positions[str(log_file)] == log_file.stat().st_size


# ---------------------------------------------------------------------------
# Tests -- _load_seen_hashes
# ---------------------------------------------------------------------------


class TestLoadSeenHashes:
    """Tests for _load_seen_hashes persistence."""

    def test_loads_from_existing_file(self, tmp_path, monkeypatch):
        """Loads hashes from a valid trigger_data.json file."""
        data_file = tmp_path / "trigger_data.json"
        data_file.write_text(
            json.dumps({"seen_error_hashes": ["aaa", "bbb"]}),
            encoding="utf-8",
        )
        monkeypatch.setattr(lw, "TRIGGER_DATA_FILE", data_file)
        monkeypatch.setattr(lw, "_seen_error_hashes", set())
        assert self._seen_count_after_start(monkeypatch) == 2

    def test_handles_missing_file(self, tmp_path, monkeypatch):
        """Missing file leaves _seen_error_hashes unchanged (no crash)."""
        monkeypatch.setattr(lw, "TRIGGER_DATA_FILE", tmp_path / "nonexistent.json")
        monkeypatch.setattr(lw, "_seen_error_hashes", {"existing"})
        assert self._seen_count_after_start(monkeypatch) == 1

    def test_handles_corrupt_json(self, tmp_path, monkeypatch):
        """Corrupt JSON resets _seen_error_hashes to empty set."""
        data_file = tmp_path / "trigger_data.json"
        data_file.write_text("{invalid json", encoding="utf-8")
        monkeypatch.setattr(lw, "TRIGGER_DATA_FILE", data_file)
        monkeypatch.setattr(lw, "_seen_error_hashes", {"leftovers"})
        assert self._seen_count_after_start(monkeypatch) == 0

    def test_handles_missing_key(self, tmp_path, monkeypatch):
        """File exists but has no seen_error_hashes key -- loads empty."""
        data_file = tmp_path / "trigger_data.json"
        data_file.write_text(json.dumps({"other_key": 1}), encoding="utf-8")
        monkeypatch.setattr(lw, "TRIGGER_DATA_FILE", data_file)
        monkeypatch.setattr(lw, "_seen_error_hashes", {"old"})
        assert self._seen_count_after_start(monkeypatch) == 0

    @staticmethod
    def _seen_count_after_start(monkeypatch) -> int:
        """Start the watcher (observer is the fixture's recorder) and read the loaded hash count."""
        monkeypatch.setattr(lw, "WATCHDOG_AVAILABLE", True)
        lw.AIPASS_PKG_ROOT.mkdir(parents=True, exist_ok=True)
        lw.start_branch_log_watcher()
        return lw.get_watcher_status()["seen_hashes_count"]


# ---------------------------------------------------------------------------
# Tests -- _load_log_positions
# ---------------------------------------------------------------------------


class TestLoadLogPositions:
    """Tests for _load_log_positions persistence."""

    @staticmethod
    def _position_after_init(state: str | None) -> tuple:
        """Persist `state` (with {log} standing for a 200-byte branch log), initialize, return (position, size)."""
        log_file = lw.AIPASS_PKG_ROOT / "flow" / "logs" / "core.log"
        log_file.parent.mkdir(parents=True)
        log_file.write_text("x" * 199 + "\n", encoding="utf-8")
        if state is not None:
            lw.TRIGGER_DATA_FILE.write_text(state.replace("{log}", json.dumps(str(log_file))[1:-1]), encoding="utf-8")
        watcher = lw.BranchLogWatcher()
        watcher.initialize_positions()
        return watcher.log_positions[str(log_file)], log_file.stat().st_size

    def test_loads_positions_from_file(self):
        """A persisted position within the file is resumed from."""
        position, _ = self._position_after_init('{"log_positions": {"{log}": 42, "/b.log": 99}}')
        assert position == 42

    def test_returns_empty_for_missing_file(self):
        """No persisted state: the watcher snaps to end of file."""
        position, size = self._position_after_init(None)
        assert position == size

    def test_returns_empty_for_corrupt_json(self):
        """Corrupt JSON is treated as no state: snap to end of file."""
        position, size = self._position_after_init("not json!")
        assert position == size

    def test_returns_empty_when_positions_not_dict(self):
        """A non-dict log_positions is ignored: snap to end of file."""
        position, size = self._position_after_init('{"log_positions": "not_a_dict"}')
        assert position == size

    def test_coerces_values_to_int(self):
        """String position values are coerced to int."""
        position, _ = self._position_after_init('{"log_positions": {"{log}": "123"}}')
        assert position == 123
        assert isinstance(position, int)


# ---------------------------------------------------------------------------
# Tests -- log_inodes persistence (parallel key, backward compatible)
# ---------------------------------------------------------------------------


class TestLogInodesPersistence:
    """Tests for the 'log_inodes' key alongside 'log_positions'."""

    def test_flush_and_load_round_trip(self, tmp_path, monkeypatch):
        """Positions and inodes round-trip through trigger_data.json."""
        data_file = tmp_path / "trigger_data.json"
        monkeypatch.setattr(lw, "TRIGGER_DATA_FILE", data_file)
        monkeypatch.setattr(
            lw, "_active_watcher", SimpleNamespace(log_positions={"/a.log": 50}, log_inodes={"/a.log": 4242})
        )
        monkeypatch.setattr(lw, "_seen_error_hashes", set())

        lw.stop_branch_log_watcher()

        assert lw._load_log_positions() == {"/a.log": 50}
        assert self._initialized().log_inodes == {"/a.log": 4242}

    def test_position_shape_unchanged(self, tmp_path, monkeypatch):
        """log_positions stays a plain Dict[str, int] - inodes live elsewhere."""
        data_file = tmp_path / "trigger_data.json"
        monkeypatch.setattr(lw, "TRIGGER_DATA_FILE", data_file)
        monkeypatch.setattr(
            lw, "_active_watcher", SimpleNamespace(log_positions={"/a.log": 50}, log_inodes={"/a.log": 4242})
        )
        monkeypatch.setattr(lw, "_seen_error_hashes", set())

        lw.stop_branch_log_watcher()

        written = json.loads(data_file.read_text(encoding="utf-8"))
        assert written["log_positions"] == {"/a.log": 50}
        assert written["log_inodes"] == {"/a.log": 4242}

    def test_old_format_state_loads_without_error(self, tmp_path, monkeypatch):
        """State written before this change (no log_inodes) still loads."""
        data_file = tmp_path / "trigger_data.json"
        data_file.write_text(
            json.dumps({"log_positions": {"/a.log": 12}, "seen_error_hashes": ["abc"]}),
            encoding="utf-8",
        )
        monkeypatch.setattr(lw, "TRIGGER_DATA_FILE", data_file)

        assert lw._load_log_positions() == {"/a.log": 12}
        assert self._initialized().log_inodes == {}

    def test_flush_without_watcher_leaves_position_state_untouched(self, tmp_path, monkeypatch):
        """clear_seen_hashes with no active watcher does not wipe on-disk position state.

        With no watcher there is no in-memory position state to write, so
        log_positions/log_inodes already on disk must survive the hash-only
        flush rather than being clobbered with empty dicts.
        """
        data_file = tmp_path / "trigger_data.json"
        data_file.write_text(
            json.dumps({"log_positions": {"/a.log": 50}, "log_inodes": {"/a.log": 7}}),
            encoding="utf-8",
        )
        monkeypatch.setattr(lw, "TRIGGER_DATA_FILE", data_file)
        monkeypatch.setattr(lw, "_active_watcher", None)
        monkeypatch.setattr(lw, "_seen_error_hashes", {"h1"})

        lw.clear_seen_hashes()

        written = json.loads(data_file.read_text(encoding="utf-8"))
        assert written["log_positions"] == {"/a.log": 50}
        assert written["log_inodes"] == {"/a.log": 7}
        assert written["seen_error_hashes"] == []

    def test_load_returns_empty_for_missing_file(self, tmp_path, monkeypatch):
        """Missing trigger_data.json yields an empty inode map."""
        monkeypatch.setattr(lw, "TRIGGER_DATA_FILE", tmp_path / "nope.json")
        assert self._initialized().log_inodes == {}

    def test_load_returns_empty_when_not_dict(self, tmp_path, monkeypatch):
        """Non-dict log_inodes value is ignored."""
        data_file = tmp_path / "trigger_data.json"
        data_file.write_text(json.dumps({"log_inodes": "nope"}), encoding="utf-8")
        monkeypatch.setattr(lw, "TRIGGER_DATA_FILE", data_file)
        assert self._initialized().log_inodes == {}

    @staticmethod
    def _initialized() -> Any:
        """A watcher initialized over an empty branch tree: its inodes come only from persisted state."""
        lw.AIPASS_PKG_ROOT.mkdir(parents=True, exist_ok=True)
        watcher = lw.BranchLogWatcher()
        watcher.initialize_positions()
        return watcher

    def test_flush_persists_inodes(self, tmp_path, monkeypatch):
        """Stopping the watcher writes its inodes to disk."""
        data_file = tmp_path / "trigger_data.json"
        monkeypatch.setattr(lw, "TRIGGER_DATA_FILE", data_file)
        monkeypatch.setattr(lw, "_data_dirty", True)
        monkeypatch.setattr(
            lw, "_active_watcher", SimpleNamespace(log_positions={"/x.log": 42}, log_inodes={"/x.log": 909})
        )
        monkeypatch.setattr(lw, "_seen_error_hashes", set())

        lw.stop_branch_log_watcher()

        assert json.loads(data_file.read_text(encoding="utf-8"))["log_inodes"] == {"/x.log": 909}

    def test_initialize_positions_records_inodes(self, tmp_path, monkeypatch):
        """initialize_positions records an inode for every tracked file."""
        monkeypatch.setattr(lw, "AIPASS_PKG_ROOT", tmp_path / "aipass")
        monkeypatch.setattr(lw, "SYSTEM_LOGS_DIR", tmp_path / "system_logs")
        monkeypatch.setattr(lw, "_load_log_positions", MagicMock(return_value={}))
        branch_logs = tmp_path / "aipass" / "flow" / "logs"
        branch_logs.mkdir(parents=True)
        log_file = branch_logs / "core.log"
        log_file.write_text("line1\nline2\n", encoding="utf-8")

        watcher = lw.BranchLogWatcher()
        watcher.initialize_positions()

        assert watcher.log_inodes[str(log_file)] == log_file.stat().st_ino

    def test_initialize_positions_with_old_state(self, tmp_path, monkeypatch):
        """Old-format persisted state (no log_inodes) initializes cleanly."""
        data_file = tmp_path / "trigger_data.json"
        monkeypatch.setattr(lw, "TRIGGER_DATA_FILE", data_file)
        monkeypatch.setattr(lw, "AIPASS_PKG_ROOT", tmp_path / "aipass")
        monkeypatch.setattr(lw, "SYSTEM_LOGS_DIR", tmp_path / "system_logs")
        branch_logs = tmp_path / "aipass" / "flow" / "logs"
        branch_logs.mkdir(parents=True)
        log_file = branch_logs / "core.log"
        log_file.write_text("line1\nline2\n", encoding="utf-8")
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

    def test_rapid_events_coalesce_into_one_write(self, tmp_path, monkeypatch):
        """N rapid modify events on a branch log produce at most 1 write within the interval."""
        data_file = tmp_path / "trigger_data.json"
        monkeypatch.setattr(lw, "TRIGGER_DATA_FILE", data_file)
        monkeypatch.setattr(lw, "_last_flush_time", 0.0)
        monkeypatch.setattr(lw, "_data_dirty", False)
        log_file = tmp_path / "aipass" / "flow" / "logs" / "core.log"
        log_file.parent.mkdir(parents=True)
        watcher = lw.BranchLogWatcher()
        monkeypatch.setattr(lw, "_active_watcher", watcher)
        event = SimpleNamespace(is_directory=False, src_path=str(log_file))

        write_count = 0
        real_write = lw.atomic_write_json

        def counting_write(path, data):
            """Wrapper that increments write_count on each call."""
            nonlocal write_count
            write_count += 1
            real_write(path, data)

        with patch.object(lw, "atomic_write_json", side_effect=counting_write):
            for n in range(20):
                with log_file.open("a", encoding="utf-8") as fh:
                    fh.write(f"INFO line {n}\n")
                watcher.on_modified(event)

        assert write_count == 1

    def test_flush_writes_both_positions_and_hashes(self, tmp_path, monkeypatch):
        """_flush_trigger_data writes both log_positions and seen_error_hashes."""
        data_file = tmp_path / "trigger_data.json"
        monkeypatch.setattr(lw, "TRIGGER_DATA_FILE", data_file)
        monkeypatch.setattr(lw, "_data_dirty", True)
        monkeypatch.setattr(
            lw, "_active_watcher", SimpleNamespace(log_positions={"/x.log": 42}, log_inodes={"/x.log": 4242})
        )
        monkeypatch.setattr(lw, "_seen_error_hashes", {"hash1", "hash2"})

        lw.stop_branch_log_watcher()

        data = json.loads(data_file.read_text(encoding="utf-8"))
        assert data["log_positions"] == {"/x.log": 42}
        assert set(data["seen_error_hashes"]) == {"hash1", "hash2"}

    def test_flush_merges_with_existing_data(self, tmp_path, monkeypatch):
        """Unrelated keys already in trigger_data.json survive a flush."""
        data_file = tmp_path / "trigger_data.json"
        data_file.write_text(
            json.dumps({"unrelated_key": {"keep": "me"}}),
            encoding="utf-8",
        )
        monkeypatch.setattr(lw, "TRIGGER_DATA_FILE", data_file)
        monkeypatch.setattr(lw, "_data_dirty", True)
        monkeypatch.setattr(
            lw, "_active_watcher", SimpleNamespace(log_positions={"/b.log": 77}, log_inodes={"/b.log": 7777})
        )
        monkeypatch.setattr(lw, "_seen_error_hashes", {"x"})

        lw.stop_branch_log_watcher()

        written = json.loads(data_file.read_text(encoding="utf-8"))
        assert written["unrelated_key"] == {"keep": "me"}
        assert written["log_positions"] == {"/b.log": 77}
        assert written["seen_error_hashes"] == ["x"]

    def test_flush_handles_write_error(self, tmp_path, monkeypatch):
        """Write failure logs a warning but does not raise."""
        monkeypatch.setattr(lw, "TRIGGER_DATA_FILE", tmp_path / "trigger_data.json")
        monkeypatch.setattr(lw, "_data_dirty", True)
        monkeypatch.setattr(
            lw, "_active_watcher", SimpleNamespace(log_positions={"/c.log": 10}, log_inodes={"/c.log": 1010})
        )
        monkeypatch.setattr(lw, "_seen_error_hashes", {"z"})

        with patch.object(lw, "logger") as mock_logger:
            with patch.object(lw, "atomic_write_json", side_effect=PermissionError("denied")):
                lw.stop_branch_log_watcher()

        warnings = [str(call.args) for call in mock_logger.warning.call_args_list]
        assert any("Failed to flush trigger_data.json" in warning for warning in warnings)

    def test_restart_survival(self, tmp_path, monkeypatch):
        """Flushed data survives reload — positions and hashes intact."""
        data_file = tmp_path / "trigger_data.json"
        monkeypatch.setattr(lw, "TRIGGER_DATA_FILE", data_file)
        monkeypatch.setattr(
            lw, "_active_watcher", SimpleNamespace(log_positions={"/srv.log": 999}, log_inodes={"/srv.log": 777})
        )
        monkeypatch.setattr(lw, "_seen_error_hashes", {"abc", "def"})
        monkeypatch.setattr(lw, "_data_dirty", True)

        lw.stop_branch_log_watcher()

        loaded_positions = lw._load_log_positions()
        assert loaded_positions == {"/srv.log": 999}

        monkeypatch.setattr(lw, "_seen_error_hashes", set())
        assert TestLoadSeenHashes._seen_count_after_start(monkeypatch) == 2

    def test_force_flush_writes_even_when_not_dirty(self, tmp_path, monkeypatch):
        """force=True writes regardless of _data_dirty flag."""
        data_file = tmp_path / "trigger_data.json"
        monkeypatch.setattr(lw, "TRIGGER_DATA_FILE", data_file)
        monkeypatch.setattr(lw, "_data_dirty", False)
        monkeypatch.setattr(
            lw, "_active_watcher", SimpleNamespace(log_positions={"/f.log": 10}, log_inodes={"/f.log": 1010})
        )
        monkeypatch.setattr(lw, "_seen_error_hashes", set())

        lw.stop_branch_log_watcher()

        assert data_file.exists()
        data = json.loads(data_file.read_text(encoding="utf-8"))
        assert data["log_positions"] == {"/f.log": 10}

    def test_dirty_flag_cleared_after_flush(self, monkeypatch):
        """_data_dirty is False after a successful flush."""
        monkeypatch.setattr(lw, "_data_dirty", True)
        monkeypatch.setattr(lw, "_active_watcher", None)
        lw._flush_trigger_data(force=True)
        assert lw._data_dirty is False

    def test_stop_watcher_forces_flush(self, tmp_path, monkeypatch):
        """stop_branch_log_watcher calls _flush_trigger_data(force=True) (mutant: the observer left unjoined)."""
        mock_watcher = MagicMock()
        mock_watcher.log_positions = {"/a.log": 50}
        monkeypatch.setattr(lw, "_active_watcher", mock_watcher)
        observer = MagicMock()
        observer.is_alive.return_value = True
        monkeypatch.setattr(lw, "_branch_log_observer", observer)

        with patch.object(lw, "_flush_trigger_data") as mock_flush:
            lw.stop_branch_log_watcher()
            mock_flush.assert_called_once_with(force=True)
        observer.join.assert_called_once_with(timeout=5.0)
        assert lw.is_branch_log_watcher_active() is False


# ---------------------------------------------------------------------------
# Tests -- _is_stale_entry (additional format coverage)
# ---------------------------------------------------------------------------


class TestIsStaleEntryFormats:
    """Additional format coverage for _is_stale_entry."""

    def test_iso_format_with_microseconds_fresh(self):
        """ISO format with microseconds: T separator and dot microseconds."""
        recent = datetime.now() - timedelta(seconds=5)
        ts = recent.strftime("%Y-%m-%dT%H:%M:%S.%f")
        assert lw._is_stale_entry(ts) is False

    def test_iso_format_simple_stale(self):
        """ISO format without microseconds, stale timestamp."""
        old = datetime.now() - timedelta(seconds=600)
        ts = old.strftime("%Y-%m-%dT%H:%M:%S")
        assert lw._is_stale_entry(ts) is True

    def test_simple_format_no_microseconds_fresh(self):
        """Simple YYYY-MM-DD HH:MM:SS format, fresh."""
        recent = datetime.now() - timedelta(seconds=2)
        ts = recent.strftime("%Y-%m-%d %H:%M:%S")
        assert lw._is_stale_entry(ts) is False

    def test_whitespace_stripped(self):
        """Leading/trailing whitespace is stripped before parsing."""
        recent = datetime.now() - timedelta(seconds=5)
        ts = "  " + recent.strftime("%Y-%m-%d %H:%M:%S.%f") + "  "
        assert lw._is_stale_entry(ts) is False

    def test_empty_string_returns_true(self):
        """Empty string is unparseable and treated as stale."""
        assert lw._is_stale_entry("") is True


# ---------------------------------------------------------------------------
# Tests -- _detect_branch_from_path (additional edge cases)
# ---------------------------------------------------------------------------


class TestDetectBranchFromPathEdgeCases:
    """Additional edge cases for _detect_branch_from_path."""

    def test_pycache_directory_ignored(self):
        """__pycache__ after aipass/ is not treated as a branch."""
        path = str(_SYNTHETIC_HOME / "src" / "aipass" / "__pycache__" / "logs" / "something.log")
        assert lw._detect_branch_from_path(path) == "UNKNOWN"

    def test_system_logs_unknown_file(self):
        """Unknown file in system_logs returns UNKNOWN."""
        path = str(lw.SYSTEM_LOGS_DIR / "completely_random.log")
        assert lw._detect_branch_from_path(path) == "UNKNOWN"

    def test_multiple_aipass_segments(self):
        """First valid aipass/branch/logs/ match wins."""
        path = str(Path(_SYNTHETIC_HOME) / "src" / "aipass" / "trigger" / "logs" / "inner.log")
        assert lw._detect_branch_from_path(path) == "TRIGGER"

    def test_aipass_without_logs_subdir(self):
        """aipass/branch without /logs/ segment returns UNKNOWN."""
        path = str(Path(_SYNTHETIC_HOME) / "src" / "aipass" / "drone" / "core.log")
        assert lw._detect_branch_from_path(path) == "UNKNOWN"

    def test_system_logs_ai_mail_prefix(self):
        """Multi-word prefix (ai_mail) is matched correctly."""
        path = str(lw.SYSTEM_LOGS_DIR / "ai_mail_delivery.log")
        assert lw._detect_branch_from_path(path) == "AI_MAIL"


# ---------------------------------------------------------------------------
# Tests -- _parse_prax_log_line (additional edge cases)
# ---------------------------------------------------------------------------


class TestParsePraxLogLineEdgeCases:
    """Additional edge cases for _parse_prax_log_line."""

    def test_dash_format_critical(self):
        """Dash format with CRITICAL level is accepted."""
        line = "2026-04-26 10:00:00,100 - core - CRITICAL - System down"
        result = lw._parse_prax_log_line(line)
        assert result is not None
        assert result["level"] == "CRITICAL"
        assert result["module"] == "core"
        assert result["message"] == "System down"

    def test_dash_format_info_returns_none(self):
        """Dash format with INFO level returns None."""
        line = "2026-04-26 10:00:00,100 - core - INFO - All is well"
        assert lw._parse_prax_log_line(line) is None

    def test_pipe_format_too_few_parts(self):
        """Pipe format with fewer than 4 parts returns None."""
        line = "2026-04-26 10:00:00 | only_two_parts"
        assert lw._parse_prax_log_line(line) is None

    def test_dash_format_too_few_parts(self):
        """Dash format with fewer than 4 parts returns None."""
        line = "2026-04-26 - module_only"
        assert lw._parse_prax_log_line(line) is None

    def test_pipe_format_warning_level_returns_none(self):
        """Pipe format with WARNING level (not error) returns None."""
        line = "2026-04-26 10:00:00 | mod | WARNING | caution"
        assert lw._parse_prax_log_line(line) is None

    def test_dash_format_debug_level_returns_none(self):
        """Dash format with DEBUG level returns None."""
        line = "2026-04-26 10:00:00,100 - mod - DEBUG - tracing"
        assert lw._parse_prax_log_line(line) is None


# ---------------------------------------------------------------------------
# Tests -- BranchLogWatcher._should_process (additional edge cases)
# ---------------------------------------------------------------------------


class TestShouldProcessEdgeCases:
    """Additional edge cases for BranchLogWatcher._should_process."""

    def test_excluded_file_case_insensitive(self):
        """Exclusion matching is case-insensitive."""
        watcher = lw.BranchLogWatcher()
        path = str(Path(_SYNTHETIC_HOME) / "src" / "aipass" / "flow" / "logs" / "DISPATCH.LOG")
        assert watcher._should_process(path) is False

    def test_non_log_extension_py(self):
        """.py file is rejected."""
        watcher = lw.BranchLogWatcher()
        path = str(Path(_SYNTHETIC_HOME) / "src" / "aipass" / "flow" / "logs" / "handler.py")
        assert watcher._should_process(path) is False

    def test_excluded_trigger_log_watcher(self):
        """trigger_log_watcher.log is excluded (self-referential)."""
        watcher = lw.BranchLogWatcher()
        path = str(Path(_SYNTHETIC_HOME) / "src" / "aipass" / "trigger" / "logs" / "trigger_log_watcher.log")
        assert watcher._should_process(path) is False

    def test_excluded_medic_suppressed(self):
        """medic_suppressed.jsonl is excluded."""
        watcher = lw.BranchLogWatcher()
        path = str(Path(_SYNTHETIC_HOME) / "src" / "aipass" / "flow" / "logs" / "medic_suppressed.jsonl")
        assert watcher._should_process(path) is False


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
        assert lw._data_dirty is False

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
        assert lw._data_dirty is True

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


# ---------------------------------------------------------------------------
# Tests -- BranchLogWatcher._process_log_line (deeper coverage)
# ---------------------------------------------------------------------------

_BRANCH_LOG_PATH = str(Path(_SYNTHETIC_HOME) / "src" / "aipass" / "flow" / "logs" / "flow.log")


class TestProcessLogLineDeeper:
    """Deeper coverage for BranchLogWatcher._process_log_line."""

    def _make_error_line(self, message: str = "Something broke") -> str:
        """Build a fresh ERROR line with current timestamp."""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
        return f"{now} | test_mod | ERROR | {message}"

    def test_semantic_exclusion_fingerprint(self):
        """Line containing 'fingerprint' in message is skipped."""
        fire = MagicMock()
        lw.set_event_callback(fire)
        watcher = lw.BranchLogWatcher()
        line = self._make_error_line("Error with fingerprint=xyz789")
        watcher._process_log_line(line, _BRANCH_LOG_PATH)
        fire.assert_not_called()

    def test_semantic_exclusion_registry_id(self):
        """Line containing 'registry_id' in message is skipped."""
        fire = MagicMock()
        lw.set_event_callback(fire)
        watcher = lw.BranchLogWatcher()
        line = self._make_error_line("Logged with registry_id=r001")
        watcher._process_log_line(line, _BRANCH_LOG_PATH)
        fire.assert_not_called()

    def test_registry_path_fires_event_with_registry_data(self, monkeypatch):
        """Registry available: fires event with registry metadata."""
        fire = MagicMock()
        lw.set_event_callback(fire)
        monkeypatch.setattr(lw, "_REGISTRY_AVAILABLE", True)

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
        monkeypatch.setattr(lw, "registry_report", mock_report)

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

    def test_registry_report_exception_falls_to_fallback(self, monkeypatch):
        """Registry report raises: falls through to fallback path."""
        fire = MagicMock()
        lw.set_event_callback(fire)
        monkeypatch.setattr(lw, "_REGISTRY_AVAILABLE", True)

        monkeypatch.setattr(lw, "registry_report", MagicMock(side_effect=RuntimeError("registry down")))

        # The lazy fallback reaches the registry and it fails too: the
        # watcher is left with its own local count.
        monkeypatch.setattr(error_registry, "report", MagicMock(side_effect=ImportError("registry gone")))
        watcher = lw.BranchLogWatcher()
        line = self._make_error_line("Fallback triggered")
        watcher._process_log_line(line, _BRANCH_LOG_PATH)

        fire.assert_called_once()
        call_kwargs = fire.call_args[1]
        assert call_kwargs["message"] == "Fallback triggered"
        assert call_kwargs["count"] == 1

    def test_fallback_lazy_import_succeeds(self, monkeypatch):
        """Fallback path: lazy import succeeds, fires event."""
        fire = MagicMock()
        lw.set_event_callback(fire)
        monkeypatch.setattr(lw, "_REGISTRY_AVAILABLE", False)

        watcher = lw.BranchLogWatcher()
        line = self._make_error_line("Lazy import works")
        watcher._process_log_line(line, _BRANCH_LOG_PATH)

        fire.assert_called_once()
        call_kwargs = fire.call_args[1]
        assert call_kwargs["message"] == "Lazy import works"

    def test_local_count_tracking_increments(self, monkeypatch):
        """Local count path: repeated errors increment counter."""
        fire = MagicMock()
        lw.set_event_callback(fire)
        monkeypatch.setattr(lw, "_REGISTRY_AVAILABLE", True)
        monkeypatch.setattr(lw, "registry_report", MagicMock(side_effect=RuntimeError("registry down")))

        monkeypatch.setattr(error_registry, "report", MagicMock(side_effect=ImportError("registry gone")))
        watcher = lw.BranchLogWatcher()
        line = self._make_error_line("Repeated failure")
        watcher._process_log_line(line, _BRANCH_LOG_PATH)
        watcher._process_log_line(line, _BRANCH_LOG_PATH)

        assert fire.call_count == 2
        second_call = fire.call_args_list[1][1]
        assert second_call["count"] == 2

    def test_outer_exception_handler_catches_unexpected(self):
        """Outer try/except catches unexpected errors without raising."""
        fire = MagicMock()
        lw.set_event_callback(fire)
        watcher = lw.BranchLogWatcher()

        with patch.object(
            lw,
            "_parse_prax_log_line",
            side_effect=TypeError("boom"),
        ):
            watcher._process_log_line("any line", str(_SYNTHETIC_ELSEWHERE / "any" / "path.log"))

        fire.assert_not_called()


# ---------------------------------------------------------------------------
# Tests -- WARNING capture for the escalation lane (DPLAN-0283 WS-A)
# ---------------------------------------------------------------------------


def _set_warning_capture(lw, enabled: bool, monkeypatch) -> MagicMock:
    """Answer the operator config the way a real config_loader would.

    config_loader is imported lazily inside _warning_capture_enabled, so the
    answer is configured on the mocked handlers.json package and the 60s TTL
    cache is dropped.
    """
    section = MagicMock(return_value={"watch_branch_log_warnings": enabled})
    monkeypatch.setattr(config_loader, "section", section)
    monkeypatch.setattr(lw, "_warning_capture_cache", (0.0, True))
    return section


def _warning_line(message: str = "Queue depth at 91%", module: str = "watcher", level: str = "WARNING") -> str:
    """Build a fresh prax-format WARNING line."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
    return f"{now} | {module} | {level} | {message}"


class TestLevelConstants:
    """The two level sets the parser is driven with."""

    def test_error_levels(self):
        """CRITICAL rides with ERROR — both mean something broke."""
        assert lw.ERROR_LEVELS == ("ERROR", "CRITICAL")

    def test_warning_levels_include_the_short_alias(self):
        """Loggers emit both WARNING and WARN; missing WARN would drop half the lines."""
        assert lw.WARNING_LEVELS == ("WARNING", "WARN")

    def test_the_two_sets_do_not_overlap(self):
        """A line can never be counted as both an error and a warning."""
        assert not set(lw.ERROR_LEVELS) & set(lw.WARNING_LEVELS)


class TestParsePraxLogLineLevels:
    """The parser takes the levels it should accept as an argument."""

    def test_warning_parsed_with_warning_levels(self):
        """A WARNING line parses when WARNING_LEVELS is passed."""
        parsed = lw._parse_prax_log_line(_warning_line(), levels=lw.WARNING_LEVELS)
        assert parsed is not None
        assert parsed["level"] == "WARNING"
        assert parsed["module"] == "watcher"
        assert parsed["message"] == "Queue depth at 91%"

    def test_warn_alias_parsed(self):
        """The WARN spelling parses the same way."""
        parsed = lw._parse_prax_log_line(_warning_line(level="WARN"), levels=lw.WARNING_LEVELS)
        assert parsed is not None
        assert parsed["level"] == "WARN"

    def test_python_dash_format_warning_parsed(self):
        """Python logging format is supported for warnings too."""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S,%f")
        parsed = lw._parse_prax_log_line(f"{now} - watcher - WARNING - Queue depth", levels=lw.WARNING_LEVELS)
        assert parsed is not None
        assert parsed["level"] == "WARNING"
        assert parsed["message"] == "Queue depth"

    def test_error_is_not_a_warning(self):
        """An ERROR line is not collected by the warning lane."""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
        assert lw._parse_prax_log_line(f"{now} | mod | ERROR | boom", levels=lw.WARNING_LEVELS) is None

    def test_default_levels_still_ignore_warnings(self):
        """The default stays ERROR-only, so the error path is unchanged."""
        assert lw._parse_prax_log_line(_warning_line()) is None


class TestProcessWarningLine:
    """WARNING lines feed the escalation lane and nothing else.

    They never enter the error registry and never dispatch anyone — before
    this path existed, a branch warning was read by nothing at all.
    """

    def test_fires_warning_logged(self, monkeypatch):
        """A fresh WARNING line fires the event with the lane's fields."""
        _set_warning_capture(lw, True, monkeypatch)
        fire = MagicMock()
        lw.set_event_callback(fire)
        watcher = lw.BranchLogWatcher()
        line = _warning_line()

        watcher._process_warning_line(line, _BRANCH_LOG_PATH)

        fire.assert_called_once()
        assert fire.call_args[0][0] == "warning_logged"
        kwargs = fire.call_args[1]
        assert kwargs["branch"] == "FLOW"
        assert kwargs["module_name"] == "watcher"
        assert kwargs["level"] == "WARNING"
        assert kwargs["message"] == "Queue depth at 91%"
        assert kwargs["log_file"] == _BRANCH_LOG_PATH
        assert kwargs["raw_line"] == line

    def test_warn_alias_fires(self, monkeypatch):
        """WARN is the same signal as WARNING."""
        _set_warning_capture(lw, True, monkeypatch)
        fire = MagicMock()
        lw.set_event_callback(fire)
        watcher = lw.BranchLogWatcher()

        watcher._process_warning_line(_warning_line(level="WARN"), _BRANCH_LOG_PATH)

        assert fire.call_args[0][0] == "warning_logged"

    def test_info_fires_nothing(self, monkeypatch):
        """INFO is not a failure signal — the lane must not count it."""
        _set_warning_capture(lw, True, monkeypatch)
        fire = MagicMock()
        lw.set_event_callback(fire)
        watcher = lw.BranchLogWatcher()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")

        watcher._process_warning_line(f"{now} | mod | INFO | All good", _BRANCH_LOG_PATH)

        fire.assert_not_called()

    def test_stale_warning_fires_nothing(self, monkeypatch):
        """A replayed rotation must not re-count old warnings."""
        _set_warning_capture(lw, True, monkeypatch)
        fire = MagicMock()
        lw.set_event_callback(fire)
        watcher = lw.BranchLogWatcher()
        old = (datetime.now() - timedelta(seconds=600)).strftime("%Y-%m-%d %H:%M:%S.%f")

        watcher._process_warning_line(f"{old} | watcher | WARNING | Queue depth at 91%", _BRANCH_LOG_PATH)

        fire.assert_not_called()

    def test_semantic_exclusion_fires_nothing(self, monkeypatch):
        """A line ABOUT an error artifact is not new signal."""
        _set_warning_capture(lw, True, monkeypatch)
        fire = MagicMock()
        lw.set_event_callback(fire)
        watcher = lw.BranchLogWatcher()

        watcher._process_warning_line(_warning_line("Retrying error_hash=abc123"), _BRANCH_LOG_PATH)

        fire.assert_not_called()

    def test_capture_disabled_by_config_fires_nothing(self, monkeypatch):
        """An operator can switch branch-log warning reading off entirely."""
        _set_warning_capture(lw, False, monkeypatch)
        fire = MagicMock()
        lw.set_event_callback(fire)
        watcher = lw.BranchLogWatcher()

        watcher._process_warning_line(_warning_line(), _BRANCH_LOG_PATH)

        fire.assert_not_called()

    def test_capture_enabled_by_config_fires(self, monkeypatch):
        """Positive control for the switch: the identical line fires when it is on.

        Mutant: the event renamed error_detected.
        """
        _set_warning_capture(lw, True, monkeypatch)
        fire = MagicMock()
        lw.set_event_callback(fire)
        watcher = lw.BranchLogWatcher()

        watcher._process_warning_line(_warning_line(), _BRANCH_LOG_PATH)

        fire.assert_called_once()
        assert fire.call_args[0][0] == "warning_logged"

    def test_unexpected_failure_is_contained(self, monkeypatch):
        """The watcher must survive a warning it cannot parse."""
        _set_warning_capture(lw, True, monkeypatch)
        fire = MagicMock()
        lw.set_event_callback(fire)
        watcher = lw.BranchLogWatcher()

        with patch.object(lw, "_parse_prax_log_line", side_effect=TypeError("boom")):
            watcher._process_warning_line(_warning_line(), _BRANCH_LOG_PATH)

        fire.assert_not_called()


class TestWarningCaptureEnabled:
    """Reading the switch runs per log line, so it is cached and fails open."""

    def test_reads_the_operator_setting(self, monkeypatch):
        """False in the config means false here."""
        _set_warning_capture(lw, False, monkeypatch)
        fire = MagicMock()
        lw.set_event_callback(fire)
        lw.BranchLogWatcher()._process_log_line(_warning_line(), _BRANCH_LOG_PATH)
        fire.assert_not_called()

    def test_answer_is_cached_between_lines(self, monkeypatch):
        """A config file read per log line would put file IO on the hot path."""
        section = _set_warning_capture(lw, True, monkeypatch)
        lw.set_event_callback(MagicMock())
        watcher = lw.BranchLogWatcher()

        for n in range(3):
            watcher._process_log_line(_warning_line(f"Queue depth at 9{n}%"), _BRANCH_LOG_PATH)

        section.assert_called_once_with("escalation")

    def test_unreadable_config_keeps_capture_on(self, monkeypatch):
        """Fails OPEN: losing the count silently is the failure the lane exists to stop."""
        monkeypatch.setattr(config_loader, "section", MagicMock(side_effect=OSError("disk gone")))
        monkeypatch.setattr(lw, "_warning_capture_cache", (0.0, False))
        fire = MagicMock()
        lw.set_event_callback(fire)

        lw.BranchLogWatcher()._process_log_line(_warning_line(), _BRANCH_LOG_PATH)

        assert fire.call_args[0][0] == "warning_logged"

    def test_missing_key_defaults_to_on(self, monkeypatch):
        """A config predating this setting still watches warnings."""
        monkeypatch.setattr(config_loader, "section", MagicMock(return_value={}))
        monkeypatch.setattr(lw, "_warning_capture_cache", (0.0, False))
        fire = MagicMock()
        lw.set_event_callback(fire)

        lw.BranchLogWatcher()._process_log_line(_warning_line(), _BRANCH_LOG_PATH)

        assert fire.call_args[0][0] == "warning_logged"


class TestProcessLogLineRoutesWarnings:
    """One entry point routes a line to the error path or the warning path."""

    def test_warning_line_reaches_the_warning_path(self, monkeypatch):
        """A WARNING line falls through the ERROR parse into warning_logged."""
        _set_warning_capture(lw, True, monkeypatch)
        fire = MagicMock()
        lw.set_event_callback(fire)
        watcher = lw.BranchLogWatcher()

        watcher._process_log_line(_warning_line(), _BRANCH_LOG_PATH)

        fire.assert_called_once()
        assert fire.call_args[0][0] == "warning_logged"

    def test_error_line_still_takes_the_error_path(self, monkeypatch):
        """The error path is unchanged: an ERROR line never becomes a warning."""
        _set_warning_capture(lw, True, monkeypatch)
        fire = MagicMock()
        lw.set_event_callback(fire)
        watcher = lw.BranchLogWatcher()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")

        watcher._process_log_line(f"{now} | my_module | ERROR | Database connection failed", _BRANCH_LOG_PATH)

        fire.assert_called_once()
        assert fire.call_args[0][0] == "error_detected"

    def test_info_line_reaches_neither_path(self, monkeypatch):
        """INFO is dropped by both parsers."""
        _set_warning_capture(lw, True, monkeypatch)
        fire = MagicMock()
        lw.set_event_callback(fire)
        watcher = lw.BranchLogWatcher()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")

        watcher._process_log_line(f"{now} | mod | INFO | All good", _BRANCH_LOG_PATH)

        fire.assert_not_called()


# ---------------------------------------------------------------------------
# Tests -- system_logs twins (double-processing, devpulse e9d92ed2)
# ---------------------------------------------------------------------------


def _dual_write_tree(tmp_path, branch: str, module: str):
    """Build the tree prax actually produces: the same line in two files.

    Returns (branch_log, system_log), both real files under tmp_path.
    """
    branch_log = tmp_path / "aipass" / branch / "logs" / f"{module}.log"
    branch_log.parent.mkdir(parents=True, exist_ok=True)
    branch_log.touch()
    system_log = tmp_path / "system_logs" / f"{branch}_{module}.log"
    system_log.parent.mkdir(parents=True, exist_ok=True)
    system_log.touch()
    return branch_log, system_log


def _point_at_tree(lw, monkeypatch, tmp_path) -> None:
    """Aim the watcher's roots at a temp tree and drop the branch-name cache."""
    monkeypatch.setattr(lw, "AIPASS_PKG_ROOT", tmp_path / "aipass")
    monkeypatch.setattr(lw, "SYSTEM_LOGS_DIR", tmp_path / "system_logs")
    monkeypatch.setattr(lw, "_branch_names_cache", (0.0, ()))


class TestSystemLogTwinIsNotProcessedTwice:
    """Prax writes every branch line to BOTH the branch's own logs/ dir and
    system_logs/<branch>_<module>.log, and this watcher schedules both trees.
    One physical line was therefore counted twice — once attributed by
    directory, once by a filename guess.

    Live evidence (2026-08-14): escalation signatures 0249c13b4d64 (HOOKS,
    src/aipass/hooks/logs/edit_gate.log) and 690de8d87cdc (UNKNOWN,
    system_logs/hooks_edit_gate.log) hold the SAME three sample lines with
    consecutive sequence numbers 8514/8515 — one reader, two files. Reported
    by devpulse in e9d92ed2. Measured: 230 of 243 system_logs files are
    twin-backed.
    """

    def test_dual_written_system_log_is_skipped(self, monkeypatch, tmp_path):
        """The system_logs copy is dropped when its branch twin exists."""
        _point_at_tree(lw, monkeypatch, tmp_path)
        _, system_log = _dual_write_tree(tmp_path, "hooks", "edit_gate")
        watcher = lw.BranchLogWatcher()

        assert watcher._should_process(str(system_log)) is False

    def test_the_branch_copy_is_the_one_kept(self, monkeypatch, tmp_path):
        """The attributed copy keeps being read — coverage is not lost."""
        _point_at_tree(lw, monkeypatch, tmp_path)
        branch_log, _ = _dual_write_tree(tmp_path, "hooks", "edit_gate")
        watcher = lw.BranchLogWatcher()

        assert watcher._should_process(str(branch_log)) is True

    def test_system_log_without_a_twin_is_still_watched(self, monkeypatch, tmp_path):
        """A real system-level log — no branch writes it — stays watched."""
        _point_at_tree(lw, monkeypatch, tmp_path)
        orphan = tmp_path / "system_logs" / "telegram-bot-api.log"
        orphan.parent.mkdir(parents=True, exist_ok=True)
        orphan.touch()
        watcher = lw.BranchLogWatcher()

        assert watcher._should_process(str(orphan)) is True

    def test_multi_word_branch_name_resolves_its_twin(self, monkeypatch, tmp_path):
        """ai_mail_dispatch_monitor.log resolves to ai_mail, not 'ai'."""
        _point_at_tree(lw, monkeypatch, tmp_path)
        _, system_log = _dual_write_tree(tmp_path, "ai_mail", "dispatch_monitor")
        watcher = lw.BranchLogWatcher()

        assert watcher._should_process(str(system_log)) is False

    def test_same_name_without_a_real_twin_file_is_not_skipped(self, monkeypatch, tmp_path):
        """A branch dir alone is not enough — the twin FILE must exist."""
        _point_at_tree(lw, monkeypatch, tmp_path)
        (tmp_path / "aipass" / "hooks" / "logs").mkdir(parents=True)
        system_log = tmp_path / "system_logs" / "hooks_edit_gate.log"
        system_log.parent.mkdir(parents=True, exist_ok=True)
        system_log.touch()
        watcher = lw.BranchLogWatcher()

        assert watcher._should_process(str(system_log)) is True

    def test_one_line_written_to_both_files_fires_once(self, monkeypatch, tmp_path):
        """The regression itself: prax's dual write yields ONE event."""
        _point_at_tree(lw, monkeypatch, tmp_path)
        _set_warning_capture(lw, True, monkeypatch)
        branch_log, system_log = _dual_write_tree(tmp_path, "hooks", "edit_gate")
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"{now} | captured_edit_gate | WARNING | [HOOKS] edit_gate: todos over limit (11/10)\n"
        branch_log.write_text(line, encoding="utf-8")
        system_log.write_text(line, encoding="utf-8")

        fire = MagicMock()
        lw.set_event_callback(fire)
        watcher = lw.BranchLogWatcher()
        for path in (branch_log, system_log):
            watcher.on_modified(SimpleNamespace(is_directory=False, src_path=str(path)))

        assert fire.call_count == 1
        assert fire.call_args.kwargs["branch"] == "HOOKS"


class TestSystemLogAttributionComesFromTheLiveTree:
    """The branch prefixes were a hardcoded list of 11 names while the tree
    held 17 branches. Every system_logs file belonging to one of the missing
    six (@hooks, @backup, @commons, @daemon, @skills, @aipass) was attributed
    to UNKNOWN — the fault was the list, not the log.
    """

    def test_unlisted_branch_attributes_from_the_tree(self, monkeypatch, tmp_path):
        """hooks/ exists on disk, so hooks_*.log is HOOKS — never UNKNOWN."""
        _point_at_tree(lw, monkeypatch, tmp_path)
        (tmp_path / "aipass" / "hooks").mkdir(parents=True)
        path = str(tmp_path / "system_logs" / "hooks_edit_gate.log")

        assert lw._detect_branch_from_path(path) == "HOOKS"

    def test_non_citizen_still_reports_unknown(self, monkeypatch, tmp_path):
        """UNKNOWN keeps its meaning: nobody in the tree owns this log."""
        _point_at_tree(lw, monkeypatch, tmp_path)
        (tmp_path / "aipass" / "hooks").mkdir(parents=True)
        path = str(tmp_path / "system_logs" / "marketstand_listings.log")

        assert lw._detect_branch_from_path(path) == "UNKNOWN"

    def test_static_prefixes_are_a_floor_not_a_ceiling(self, monkeypatch, tmp_path):
        """An unreadable tree falls back to the static list instead of UNKNOWN."""
        _point_at_tree(lw, monkeypatch, tmp_path)
        path = str(tmp_path / "system_logs" / "seedgo_audit.log")

        assert lw._detect_branch_from_path(path) == "SEEDGO"


# ---------------------------------------------------------------------------
# Tests -- path classification is separator-agnostic (Windows CI, 70a10016)
# ---------------------------------------------------------------------------


class TestLogPathClassificationOnBothPlatforms:
    """`_should_process` classified paths with `"/logs/" in file_path`, so every
    Windows path — `...\\aipass\\hooks\\logs\\edit_gate.log` — fell through to
    "foreign" and was dropped. Four tests went red on the first honest Windows
    CI run (devpulse, 70a10016, 2026-08-18).

    A separator string test cannot be fixed by normalising on one platform and
    hoping; the classifier takes a PurePath, so these cases prove BOTH flavours
    from either runner.
    """

    def test_windows_branch_log_is_a_branch_log(self):
        """The exact path shape Windows CI reported."""
        from pathlib import PureWindowsPath

        path = PureWindowsPath(r"C:\p\AIPass\src\aipass\hooks\logs\edit_gate.log")
        assert lw._classify_log_path(path) == "branch"

    def test_posix_branch_log_is_a_branch_log(self):
        """The same answer from the other separator."""
        from pathlib import PurePosixPath

        path = PurePosixPath("/p/AIPass/src/aipass/hooks/logs/edit_gate.log")
        assert lw._classify_log_path(path) == "branch"

    def test_windows_system_log_is_a_system_log(self):
        """system_logs/ is recognised through backslashes too."""
        from pathlib import PureWindowsPath

        path = PureWindowsPath(r"C:\p\AIPass\system_logs\telegram-bot-api.log")
        assert lw._classify_log_path(path) == "system"

    def test_posix_system_log_is_a_system_log(self):
        """Same, forward slashes."""
        from pathlib import PurePosixPath

        assert lw._classify_log_path(PurePosixPath("/p/system_logs/x.log")) == "system"

    def test_unrelated_path_is_foreign_on_both(self):
        """A log outside both trees stays foreign, either separator."""
        from pathlib import PureWindowsPath

        assert lw._classify_log_path(PureWindowsPath(r"C:\tmp\random\output.log")) == "foreign"
        assert lw._classify_log_path(_SYNTHETIC_ELSEWHERE / "random" / "output.log") == "foreign"

    def test_aipass_without_a_logs_dir_is_not_a_branch_log(self):
        """Both components are required, not either."""
        from pathlib import PureWindowsPath

        path = PureWindowsPath(r"C:\p\src\aipass\drone\core.log")
        assert lw._classify_log_path(path) == "foreign"
