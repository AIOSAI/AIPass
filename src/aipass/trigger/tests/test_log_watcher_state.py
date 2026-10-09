# =================== AIPass ====================
# Name: test_log_watcher_state.py
# Description: Tests for the branch log watcher's state: positions, seen hashes, start/stop and the debounced writer
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-08
# =============================================

"""Tests for apps/handlers/log_watcher.py's persisted state and lifecycle (trigger_data.json, start/stop)."""

# Split from test_log_watcher.py (oversize_test_file, 2026-10-08): that file
# keeps parsing and detection; this one holds what the watcher remembers and how
# it starts and stops: the event callback and seen hashes, start/stop/status,
# initialize_positions, the positions and inodes persisted in trigger_data.json,
# and the debounced writer that flushes them.
# The watcher's live-state doors are closed by conftest's log_watcher_infrastructure.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(covered_elsewhere) — the daemon that starts start_branch_log_watcher: its own tests

import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

import aipass.trigger.apps.handlers.log_watcher as lw
from aipass.trigger.tests.support_log_watcher import _BRANCH_LOG_PATH

pytestmark = pytest.mark.usefixtures("log_watcher_infrastructure")


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
            "pending_flush",
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


def _a_branch_log() -> Path:
    """A 200-byte branch log under the patched package root, where initialize_positions looks."""
    log_file = lw.AIPASS_PKG_ROOT / "flow" / "logs" / "core.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    log_file.write_text("x" * 199 + "\n", encoding="utf-8")
    return log_file


def _restarted() -> Any:
    """A fresh watcher initialized the way a restart does: persisted positions first, end of file otherwise."""
    watcher = lw.BranchLogWatcher()
    watcher.initialize_positions()
    return watcher


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
        """Positions and inodes round-trip through trigger_data.json.

        Read back by a restarted watcher since leg 7 (it called _load_log_positions
        directly): a position the restart did not restore would snap to the
        log's end, 200. Mutant run (leg 7): _load_log_positions answering {}
        reddens this at the position assert.
        """
        data_file = tmp_path / "trigger_data.json"
        monkeypatch.setattr(lw, "TRIGGER_DATA_FILE", data_file)
        log = _a_branch_log()
        monkeypatch.setattr(
            lw, "_active_watcher", SimpleNamespace(log_positions={str(log): 50}, log_inodes={"/a.log": 4242})
        )
        monkeypatch.setattr(lw, "_seen_error_hashes", set())

        lw.stop_branch_log_watcher()

        restarted = _restarted()
        assert restarted.log_positions[str(log)] == 50
        assert restarted.log_inodes["/a.log"] == 4242

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
        """State written before this change (no log_inodes) still loads.

        Read back by a restarted watcher since leg 7 (it called _load_log_positions
        directly); the only inode it holds is the live stat of the one real log.
        Mutant run (leg 7): _load_log_positions answering {} reddens the position assert.
        """
        log = _a_branch_log()
        data_file = tmp_path / "trigger_data.json"
        data_file.write_text(
            json.dumps({"log_positions": {str(log): 12}, "seen_error_hashes": ["abc"]}),
            encoding="utf-8",
        )
        monkeypatch.setattr(lw, "TRIGGER_DATA_FILE", data_file)

        restarted = _restarted()
        assert restarted.log_positions[str(log)] == 12
        assert list(restarted.log_inodes) == [str(log)], "an inode came from a state file that holds none"

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
        """Flushed data survives reload — positions and hashes intact.

        Positions read back by a restarted watcher since leg 7 (it called
        _load_log_positions directly). Mutant run (leg 7): _load_log_positions
        answering {} reddens the position assert.
        """
        data_file = tmp_path / "trigger_data.json"
        monkeypatch.setattr(lw, "TRIGGER_DATA_FILE", data_file)
        log = _a_branch_log()
        monkeypatch.setattr(
            lw, "_active_watcher", SimpleNamespace(log_positions={str(log): 150}, log_inodes={"/srv.log": 777})
        )
        monkeypatch.setattr(lw, "_seen_error_hashes", {"abc", "def"})
        monkeypatch.setattr(lw, "_data_dirty", True)

        lw.stop_branch_log_watcher()

        assert _restarted().log_positions[str(log)] == 150

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
        """pending_flush reads False after a successful flush.

        Flushed through stop_branch_log_watcher, which forces the same flush,
        since leg 7 (it called _flush_trigger_data directly). Read through the
        status answer since leg 10, which added pending_flush. Mutant run: the
        flush leaving the flag set reddens this.
        """
        monkeypatch.setattr(lw, "_data_dirty", True)
        monkeypatch.setattr(lw, "_active_watcher", SimpleNamespace(log_positions={}, log_inodes={}))
        lw.stop_branch_log_watcher()
        assert lw.get_watcher_status()["pending_flush"] is False

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
