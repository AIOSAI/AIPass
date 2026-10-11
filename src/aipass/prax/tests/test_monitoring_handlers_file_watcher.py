# =================== AIPass ====================
# Name: test_monitoring_handlers_file_watcher.py
# Description: Unit tests for the monitoring file watcher integration
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-08
# =============================================

"""Tests for apps/handlers/monitoring/file_watcher_integration.py, split from test_monitoring_handlers.py."""

# Covers:
# - file_watcher_integration: load_branch_paths, file_event_callback,
#   get_file_watcher, is_file_watcher_running, get_file_watcher_stats,
#   FileWatcherManager.is_running, FileWatcherManager.get_stats

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(json_structure) — file_watcher_integration's log_operation records, doubled by the fixture

import json
from unittest.mock import MagicMock

import pytest

from aipass.prax.apps.handlers.config import load as config_load
from aipass.prax.apps.handlers.monitoring import file_watcher_integration
from aipass.prax.tests.support_test_monitoring_handlers import _write_registry

# =============================================
# FILE WATCHER INTEGRATION TESTS
# =============================================


_FILE_WATCHER_DOUBLES: dict[str, MagicMock] = {}


@pytest.fixture(autouse=True)
def _file_watcher_doubled(monkeypatch, tmp_path):
    """Double file_watcher_integration's collaborators where it binds them.

    The watcher and the event queue are replaced on the module itself, and the
    repo root the loader asks config.load for is this test's tmp_path, so a
    registry the test writes there is the one read. Replaces raw sys.modules
    assignments that nothing put back (prax, leg 12).
    """
    watcher = MagicMock()
    watcher.WATCHDOG_AVAILABLE = True
    watcher.start_monitoring = MagicMock(return_value=MagicMock())
    event_queue = MagicMock()
    event_queue.global_queue.enqueue = MagicMock(return_value=True)
    for name in ("start_monitoring", "stop_monitoring", "WATCHDOG_AVAILABLE"):
        monkeypatch.setattr(file_watcher_integration, name, getattr(watcher, name))
    monkeypatch.setattr(file_watcher_integration, "MonitoringEvent", event_queue.MonitoringEvent)
    monkeypatch.setattr(file_watcher_integration, "global_queue", event_queue.global_queue)
    monkeypatch.setattr(file_watcher_integration, "logger", MagicMock())
    monkeypatch.setattr(file_watcher_integration, "json_handler", MagicMock())
    monkeypatch.setattr(file_watcher_integration, "_file_watcher", None)
    monkeypatch.setattr(config_load, "_find_repo_root", lambda: tmp_path)
    monkeypatch.setitem(_FILE_WATCHER_DOUBLES, "watcher", watcher)
    monkeypatch.setitem(_FILE_WATCHER_DOUBLES, "event_queue", event_queue)


def _import_file_watcher_integration():
    """The top-bound module and the doubles the autouse fixture set on it."""
    return (
        file_watcher_integration,
        _FILE_WATCHER_DOUBLES["watcher"],
        _FILE_WATCHER_DOUBLES["event_queue"],
        config_load,
    )


class TestLoadBranchPaths:
    """Tests for load_branch_paths()."""

    def test_returns_branch_tuples(self, tmp_path):
        """Should return list of (name, Path) tuples from registry, folders that exist only."""
        mod, _, _, _ = _import_file_watcher_integration()
        for name in ("prax", "cli"):
            (tmp_path / name).mkdir()
        branches = [{"name": n, "path": str(tmp_path / n.lower())} for n in ("PRAX", "CLI", "GONE")]
        _write_registry(tmp_path, json.dumps({"branches": branches}))

        result = mod.load_branch_paths()

        assert result == [("PRAX", tmp_path / "prax"), ("CLI", tmp_path / "cli")]

    def test_with_branch_filter(self, tmp_path):
        """Should filter branches when branch_filter is provided."""
        mod, _, _, _ = _import_file_watcher_integration()
        for name in ("prax", "cli", "flow"):
            (tmp_path / name).mkdir()
        branches = [{"name": n, "path": str(tmp_path / n.lower())} for n in ("PRAX", "CLI", "FLOW")]
        _write_registry(tmp_path, json.dumps({"branches": branches}))

        result = mod.load_branch_paths(branch_filter=["prax", "FLOW"])

        assert [name for name, _ in result] == ["PRAX", "FLOW"]

    def test_missing_registry_returns_empty(self, tmp_path):
        """Should return empty list when registry file is missing.

        The absence is measured by the open FAILING, not by an exists() call
        that answered about a moment already over: the loader opens and handles
        FileNotFoundError, so no registry is written and nothing is stubbed.
        """
        mod, _, _, _ = _import_file_watcher_integration()

        result = mod.load_branch_paths()

        assert result == []
        # The message has to be the ABSENCE one, not the catch-all: a loader
        # that lost its guard also answers [] here, through the generic
        # "Could not read the branch registry" clause at the bottom, so the
        # return value alone cannot tell the two apart.
        warnings = " ".join(str(call) for call in mod.logger.warning.call_args_list)
        assert "No branch registry at" in warnings
        assert mod.logger.error.call_args_list == []

    def test_invalid_json_returns_empty(self, tmp_path):
        """Should return empty list on JSON decode error, and say it was the JSON."""
        mod, _, _, _ = _import_file_watcher_integration()
        _write_registry(tmp_path, "{invalid json")

        result = mod.load_branch_paths()

        assert result == []
        assert "The branch registry is not valid JSON (line 1)" in mod.logger.error.call_args.args[0]

    def test_empty_branches_returns_empty(self, tmp_path):
        """Should return empty list when branches array is empty."""
        mod, _, _, _ = _import_file_watcher_integration()
        _write_registry(tmp_path, json.dumps({"branches": []}))

        result = mod.load_branch_paths()

        assert result == []
        assert "lists no branches" in mod.logger.warning.call_args.args[0]


class TestFileEventCallback:
    """Tests for file_event_callback()."""

    def test_creates_monitoring_event(self, tmp_path):
        """Should create and enqueue a MonitoringEvent."""
        mod, _, mock_eq, _ = _import_file_watcher_integration()

        changed_file = str(tmp_path / "some" / "file.py")
        mod.file_event_callback("PRAX", "MODIFIED", changed_file)

        assert mod.MonitoringEvent.call_count == 1
        kwargs = mod.MonitoringEvent.call_args.kwargs
        assert (kwargs["branch"], kwargs["action"], kwargs["message"]) == ("PRAX", "modified", changed_file)
        mod.global_queue.enqueue.assert_called_once_with(mod.MonitoringEvent.return_value)

    def test_maps_event_types_correctly(self, tmp_path):
        """A known event type gets its mapped action and the priority that goes with it."""
        mod, _, mock_eq, _ = _import_file_watcher_integration()

        changed_file = str(tmp_path / "file.py")
        mod.file_event_callback("CLI", "CREATED", changed_file)

        kwargs = mod.MonitoringEvent.call_args.kwargs
        assert kwargs["action"] == "created"
        assert kwargs["priority"] == 2, "created is one of the three that outrank a modify"
        assert kwargs["event_type"] == "file"
        assert kwargs["branch"] == "CLI"
        assert kwargs["message"] == changed_file
        assert kwargs["level"] == "info"

    def test_handles_unknown_event_type(self, tmp_path):
        """An event type outside the map is lowercased and falls to the default priority."""
        mod, _, mock_eq, _ = _import_file_watcher_integration()

        mod.file_event_callback("FLOW", "RENAMED", str(tmp_path / "file.py"))

        kwargs = mod.MonitoringEvent.call_args.kwargs
        assert kwargs["action"] == "renamed"
        assert kwargs["priority"] == 3, "an unmapped action takes the priority_map default"
        assert kwargs["branch"] == "FLOW"

    def test_handles_exception(self, tmp_path):
        """A failing event build is swallowed: nothing is enqueued and the error is logged."""
        mod, _, mock_eq, _ = _import_file_watcher_integration()
        mod.MonitoringEvent.side_effect = Exception("boom")

        changed_file = str(tmp_path / "file.py")
        assert mod.file_event_callback("PRAX", "MODIFIED", changed_file) is None

        mock_eq.global_queue.enqueue.assert_not_called()
        mod.logger.error.assert_called_once()
        message = mod.logger.error.call_args.args[0]
        assert f"unexpected Exception (PRAX MODIFIED {changed_file})" in message
        assert "file watching continues" in message


class TestGetFileWatcher:
    """Tests for get_file_watcher() singleton."""

    def test_returns_file_watcher_manager(self):
        """get_file_watcher() builds an idle manager on the global queue and caches it."""
        mod, _, mock_eq, _ = _import_file_watcher_integration()
        setattr(mod, "_file_watcher", None)

        watcher = mod.get_file_watcher()

        assert isinstance(watcher, mod.FileWatcherManager)
        assert watcher.queue is mock_eq.global_queue, "no queue argument means the global one"
        assert watcher.running is False
        assert watcher.observer is None
        assert watcher.branch_paths == []
        assert watcher.branch_filter is None
        assert mod._file_watcher is watcher, "the singleton slot must hold what was handed back"

    def test_returns_same_instance(self):
        """get_file_watcher() should return singleton."""
        mod, _, _, _ = _import_file_watcher_integration()
        setattr(mod, "_file_watcher", None)
        first = mod.get_file_watcher()
        second = mod.get_file_watcher()
        assert first is second


class TestIsFileWatcherRunning:
    """Tests for is_file_watcher_running() module-level function."""

    def test_false_when_not_started(self):
        """Should return False when watcher has not been started."""
        mod, _, _, _ = _import_file_watcher_integration()
        setattr(mod, "_file_watcher", None)
        assert mod.is_file_watcher_running() is False

    def test_true_when_running(self):
        """Should return True when watcher is running."""
        mod, _, _, _ = _import_file_watcher_integration()
        watcher = mod.FileWatcherManager()
        watcher.running = True
        setattr(mod, "_file_watcher", watcher)
        assert mod.is_file_watcher_running() is True


class TestGetFileWatcherStats:
    """Tests for get_file_watcher_stats() module-level function."""

    def test_returns_stats_dict(self):
        """Should return stats dictionary from the manager."""
        mod, _, _, _ = _import_file_watcher_integration()
        setattr(mod, "_file_watcher", None)
        stats = mod.get_file_watcher_stats()
        assert stats == {
            "running": False,
            "branches_watched": 0,
            "branch_names": [],
            "watchdog_available": mod.WATCHDOG_AVAILABLE,
        }

    def test_reflects_manager_state(self, tmp_path):
        """Stats should reflect current manager state."""
        mod, _, _, _ = _import_file_watcher_integration()
        watcher = mod.FileWatcherManager()
        watcher.running = True
        watcher.branch_paths = [("PRAX", tmp_path / "prax"), ("CLI", tmp_path / "cli")]
        setattr(mod, "_file_watcher", watcher)
        stats = mod.get_file_watcher_stats()
        assert stats["running"] is True
        assert stats["branches_watched"] == 2
        assert "PRAX" in stats["branch_names"]


class TestFileWatcherManagerIsRunning:
    """Tests for FileWatcherManager.is_running() instance method."""

    def test_false_initially(self):
        """is_running() should be False for new instance."""
        mod, _, _, _ = _import_file_watcher_integration()
        mgr = mod.FileWatcherManager()
        assert mgr.is_running() is False

    def test_true_after_setting(self):
        """is_running() should reflect running state."""
        mod, _, _, _ = _import_file_watcher_integration()
        mgr = mod.FileWatcherManager()
        mgr.running = True
        assert mgr.is_running() is True

    def test_false_after_stop(self):
        """is_running() should be False after stop()."""
        mod, _, _, _ = _import_file_watcher_integration()
        mgr = mod.FileWatcherManager()
        mgr.running = True
        mgr.observer = MagicMock()
        mgr.stop()
        assert mgr.is_running() is False


class TestFileWatcherManagerGetStats:
    """Tests for FileWatcherManager.get_stats() instance method."""

    def test_default_stats(self):
        """get_stats() on fresh instance should show defaults."""
        mod, _, _, _ = _import_file_watcher_integration()
        mgr = mod.FileWatcherManager()
        stats = mgr.get_stats()
        assert stats["running"] is False
        assert stats["branches_watched"] == 0
        assert stats["branch_names"] == []
        assert "watchdog_available" in stats

    def test_stats_with_branches(self, tmp_path):
        """get_stats() should list watched branches."""
        mod, _, _, _ = _import_file_watcher_integration()
        mgr = mod.FileWatcherManager()
        mgr.branch_paths = [
            ("SEEDGO", tmp_path / "seedgo"),
            ("DRONE", tmp_path / "drone"),
        ]
        mgr.running = True
        stats = mgr.get_stats()
        assert stats["running"] is True
        assert stats["branches_watched"] == 2
        assert "SEEDGO" in stats["branch_names"]
        assert "DRONE" in stats["branch_names"]
