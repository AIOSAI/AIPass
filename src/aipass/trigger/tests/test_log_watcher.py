"""Tests for the branch log watcher handler (apps/handlers/log_watcher.py)."""

# =================== META ====================
# Name: test_log_watcher.py
# Description: Unit tests for branch log watcher event producer
# Version: 1.0.0
# Created: 2026-04-03
# Modified: 2026-04-03
# =============================================

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
# Tests -- _is_duplicate_error
# ---------------------------------------------------------------------------


class TestIsDuplicateError:
    """Tests for _is_duplicate_error."""

    def test_first_time_returns_false(self):
        """First occurrence of a hash is NOT a duplicate."""
        lw = _import_log_watcher()
        lw._seen_error_hashes.clear()
        # Patch _save_seen_hashes to avoid disk I/O
        with patch.object(lw, "_save_seen_hashes"):
            assert lw._is_duplicate_error("aabbccdd") is False

    def test_second_time_returns_true(self):
        """Second occurrence of the same hash IS a duplicate."""
        lw = _import_log_watcher()
        lw._seen_error_hashes.clear()
        with patch.object(lw, "_save_seen_hashes"):
            lw._is_duplicate_error("aabbccdd")
            assert lw._is_duplicate_error("aabbccdd") is True

    def test_hash_set_size_limit(self):
        """When set exceeds MAX_SEEN_HASHES, it is trimmed."""
        lw = _import_log_watcher()
        lw._seen_error_hashes.clear()
        with patch.object(lw, "_save_seen_hashes"):
            # Fill beyond the max
            for i in range(lw.MAX_SEEN_HASHES + 10):
                lw._is_duplicate_error(f"hash_{i:05d}")
            assert len(lw._seen_error_hashes) <= lw.MAX_SEEN_HASHES


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
        with patch.object(lw, "_save_seen_hashes"):
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
        with patch.object(lw, "_save_log_positions"):
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

        with patch.object(lw, "_save_log_positions"):
            watcher._read_new_lines(file_path)

        # Position should be at the end of the new content
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
