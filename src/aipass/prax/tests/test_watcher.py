# =================== AIPass ====================
# Name: test_watcher.py
# Description: Tests for file system watcher handlers
# Version: 1.0.0
# Created: 2026-04-03
# Modified: 2026-04-03
# =============================================

"""Tests for:
- apps/handlers/watcher/monitor.py  (BranchFileHandler, start/stop_monitoring)
- apps/handlers/discovery/watcher.py (PythonFileWatcher, start/stop_file_watcher)
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch


# ============================================================================
# WATCHER/MONITOR.PY - BranchFileHandler and start/stop_monitoring
# ============================================================================


class TestBranchFileHandler:
    """Tests for BranchFileHandler event callbacks and filtering."""

    def _make_handler(self):
        """Create a BranchFileHandler with a mock callback."""

        # Provide a real base class so subclass methods work properly
        class _RealFSHandler:
            """Stub base so BranchFileHandler methods are not swallowed."""

            pass

        mock_watchdog_events = MagicMock()
        mock_watchdog_events.FileSystemEventHandler = _RealFSHandler
        mock_watchdog_events.FileSystemEvent = MagicMock()
        mock_watchdog_observer = MagicMock()
        with patch.dict(
            sys.modules,
            {
                "watchdog": MagicMock(),
                "watchdog.observers": mock_watchdog_observer,
                "watchdog.events": mock_watchdog_events,
            },
        ):
            import importlib

            if "aipass.prax.apps.handlers.watcher.monitor" in sys.modules:
                mod = importlib.reload(sys.modules["aipass.prax.apps.handlers.watcher.monitor"])
            else:
                mod = importlib.import_module("aipass.prax.apps.handlers.watcher.monitor")

        callback = MagicMock()
        handler = mod.BranchFileHandler("TEST", callback)
        return handler, callback, mod

    def _make_event(self, src_path: str, is_directory: bool = False, dest_path: str | None = None):
        event = MagicMock()
        event.src_path = src_path
        event.is_directory = is_directory
        if dest_path is not None:
            event.dest_path = dest_path
        return event

    # --- Callback firing tests ---

    def test_on_created_fires_callback(self):
        handler, callback, _mod = self._make_handler()
        event = self._make_event("/repo/src/aipass/flow/apps/module.py")
        handler.on_created(event)
        callback.assert_called_once_with("TEST", "CREATED", "/repo/src/aipass/flow/apps/module.py")

    def test_on_modified_fires_callback(self):
        handler, callback, _mod = self._make_handler()
        event = self._make_event("/repo/src/aipass/flow/apps/module.py")
        handler.on_modified(event)
        callback.assert_called_once_with("TEST", "MODIFIED", "/repo/src/aipass/flow/apps/module.py")

    def test_on_deleted_fires_callback(self):
        handler, callback, _mod = self._make_handler()
        event = self._make_event("/repo/src/aipass/flow/apps/module.py")
        handler.on_deleted(event)
        callback.assert_called_once_with("TEST", "DELETED", "/repo/src/aipass/flow/apps/module.py")

    def test_on_moved_fires_callback_with_arrow(self):
        handler, callback, _mod = self._make_handler()
        event = self._make_event("/repo/old.py", dest_path="/repo/new.py")
        handler.on_moved(event)
        callback.assert_called_once_with("TEST", "MOVED", "/repo/old.py \u2192 /repo/new.py")

    # --- Ignore logic ---

    def test_ignores_directory_events(self):
        handler, callback, _mod = self._make_handler()
        event = self._make_event("/repo/src/aipass/flow/apps/", is_directory=True)
        handler.on_created(event)
        callback.assert_not_called()

    def test_ignores_log_files(self):
        handler, callback, _mod = self._make_handler()
        event = self._make_event("/repo/logs/prax.log")
        handler.on_modified(event)
        callback.assert_not_called()

    def test_ignores_tmp_files(self):
        handler, callback, _mod = self._make_handler()
        for path in ("/repo/data.tmp", "/repo/.tmp.xyz"):
            event = self._make_event(path)
            handler.on_created(event)
        callback.assert_not_called()

    def test_ignores_backup_files(self):
        handler, callback, _mod = self._make_handler()
        for path in ("/repo/file.backup", "/repo/file.bak", "/repo/file~"):
            event = self._make_event(path)
            handler.on_modified(event)
        callback.assert_not_called()

    def test_ignores_vim_swap_files(self):
        handler, callback, _mod = self._make_handler()
        for path in ("/repo/.file.swp", "/repo/.file.swo"):
            event = self._make_event(path)
            handler.on_created(event)
        callback.assert_not_called()

    def test_ignores_system_directories(self):
        handler, callback, _mod = self._make_handler()
        ignore_paths = [
            "/repo/.claude/settings.json",
            "/repo/.git/objects/abc",
            "/repo/__pycache__/mod.pyc",
            "/repo/.pytest_cache/v/cache.json",
            "/repo/node_modules/pkg/index.js",
            "/repo/.venv/lib/site.py",
            "/repo/venv/lib/site.py",
            "/repo/.local/share/data",
            "/repo/.cache/fontconfig",
            "/repo/.config/user.json",
            "/repo/.vscode/settings.json",
            "/repo/system_logs/prax.log",
        ]
        for path in ignore_paths:
            event = self._make_event(path)
            handler.on_modified(event)
        callback.assert_not_called()

    def test_does_not_ignore_normal_python_file(self):
        handler, callback, _mod = self._make_handler()
        event = self._make_event("/repo/src/aipass/prax/apps/modules/status.py")
        handler.on_modified(event)
        callback.assert_called_once()


# ============================================================================
# WATCHER/MONITOR.PY - start_monitoring / stop_monitoring
# ============================================================================


class TestStartStopMonitoring:
    """Tests for start_monitoring and stop_monitoring functions."""

    def _import_watcher_monitor(self):
        mock_observer_cls = MagicMock()
        mock_observer_instance = MagicMock()
        mock_observer_cls.return_value = mock_observer_instance

        mock_watchdog_observer = MagicMock()
        mock_watchdog_observer.Observer = mock_observer_cls

        mock_watchdog_events = MagicMock()

        with patch.dict(
            sys.modules,
            {
                "watchdog": MagicMock(),
                "watchdog.observers": mock_watchdog_observer,
                "watchdog.events": mock_watchdog_events,
            },
        ):
            import importlib

            if "aipass.prax.apps.handlers.watcher.monitor" in sys.modules:
                mod = importlib.reload(sys.modules["aipass.prax.apps.handlers.watcher.monitor"])
            else:
                mod = importlib.import_module("aipass.prax.apps.handlers.watcher.monitor")

        # Force WATCHDOG_AVAILABLE = True and Observer to be our mock
        setattr(mod, "WATCHDOG_AVAILABLE", True)
        setattr(mod, "Observer", mock_observer_cls)

        return mod, mock_observer_instance, mock_observer_cls

    def test_start_monitoring_schedules_paths(self, tmp_path):
        mod, observer_inst, _cls = self._import_watcher_monitor()
        branch_dir = tmp_path / "flow"
        branch_dir.mkdir()
        callback = MagicMock()

        result = mod.start_monitoring([("FLOW", branch_dir)], callback)

        assert result is observer_inst
        observer_inst.schedule.assert_called_once()
        observer_inst.start.assert_called_once()

    def test_start_monitoring_skips_nonexistent_paths(self, tmp_path):
        mod, observer_inst, _cls = self._import_watcher_monitor()
        callback = MagicMock()

        result = mod.start_monitoring([("GHOST", tmp_path / "nonexistent")], callback)

        assert result is observer_inst
        observer_inst.schedule.assert_not_called()
        observer_inst.start.assert_called_once()

    def test_start_monitoring_returns_none_when_watchdog_unavailable(self):
        mod, _inst, _cls = self._import_watcher_monitor()
        setattr(mod, "WATCHDOG_AVAILABLE", False)
        result = mod.start_monitoring([], MagicMock())
        assert result is None

    def test_stop_monitoring_stops_and_joins(self):
        mod, observer_inst, _cls = self._import_watcher_monitor()
        mod.stop_monitoring(observer_inst)
        observer_inst.stop.assert_called_once()
        observer_inst.join.assert_called_once()

    def test_stop_monitoring_handles_none(self):
        mod, _inst, _cls = self._import_watcher_monitor()
        # Should not raise
        mod.stop_monitoring(None)


# ============================================================================
# DISCOVERY/WATCHER.PY - PythonFileWatcher, start/stop/is_active
# ============================================================================


class TestDiscoveryWatcher:
    """Tests for the discovery watcher that registers new Python modules."""

    def _import_discovery_watcher(self):
        mock_observer_cls = MagicMock()
        mock_observer_instance = MagicMock()
        mock_observer_cls.return_value = mock_observer_instance

        mock_watchdog_observer = MagicMock()
        mock_watchdog_observer.Observer = mock_observer_cls

        mock_watchdog_events = MagicMock()

        mock_config = MagicMock()
        mock_config.ECOSYSTEM_ROOT = Path("/fake/ecosystem")
        mock_config.get_system_logs_dir.return_value = Path("/fake/logs/system")
        mock_config.get_module_logs_dir.return_value = Path("/fake/logs/modules")

        mock_registry_load = MagicMock()
        mock_registry_load.load_module_registry.return_value = {}

        mock_registry_save = MagicMock()

        mock_filtering = MagicMock()
        mock_filtering.should_ignore_path.return_value = False

        mock_trigger_mod = MagicMock()

        with patch.dict(
            sys.modules,
            {
                "watchdog": MagicMock(),
                "watchdog.observers": mock_watchdog_observer,
                "watchdog.events": mock_watchdog_events,
                "aipass.prax.apps.handlers.config.load": mock_config,
                "aipass.prax.apps.handlers.registry.load": mock_registry_load,
                "aipass.prax.apps.handlers.registry.save": mock_registry_save,
                "aipass.prax.apps.handlers.discovery.filtering": mock_filtering,
                "aipass.trigger": MagicMock(),
                "aipass.trigger.apps": MagicMock(),
                "aipass.trigger.apps.modules": MagicMock(),
                "aipass.trigger.apps.modules.core": mock_trigger_mod,
            },
        ):
            import importlib

            if "aipass.prax.apps.handlers.discovery.watcher" in sys.modules:
                mod = importlib.reload(sys.modules["aipass.prax.apps.handlers.discovery.watcher"])
            else:
                mod = importlib.import_module("aipass.prax.apps.handlers.discovery.watcher")

        setattr(mod, "WatchdogObserver", mock_observer_cls)
        return mod, mock_observer_instance, mock_observer_cls

    def test_start_file_watcher_creates_and_starts_observer(self):
        mod, observer_inst, _cls = self._import_discovery_watcher()
        setattr(mod, "_observer", None)  # Ensure clean state
        mod.start_file_watcher()
        observer_inst.schedule.assert_called_once()
        observer_inst.start.assert_called_once()
        assert getattr(mod, "_observer") is observer_inst

    def test_start_file_watcher_skips_if_already_running(self):
        mod, observer_inst, obs_cls = self._import_discovery_watcher()
        existing_observer = MagicMock()
        existing_observer.is_alive.return_value = True
        setattr(mod, "_observer", existing_observer)

        mod.start_file_watcher()

        # Should not create a new observer
        observer_inst.start.assert_not_called()

    def test_stop_file_watcher_stops_and_clears(self):
        mod, _inst, _cls = self._import_discovery_watcher()
        mock_obs = MagicMock()
        mock_obs.is_alive.return_value = True
        setattr(mod, "_observer", mock_obs)

        mod.stop_file_watcher()

        mock_obs.stop.assert_called_once()
        mock_obs.join.assert_called_once()
        assert getattr(mod, "_observer") is None

    def test_stop_file_watcher_noop_when_not_running(self):
        mod, _inst, _cls = self._import_discovery_watcher()
        setattr(mod, "_observer", None)
        # Should not raise
        mod.stop_file_watcher()

    def test_is_file_watcher_active_true_when_alive(self):
        mod, _inst, _cls = self._import_discovery_watcher()
        mock_obs = MagicMock()
        mock_obs.is_alive.return_value = True
        setattr(mod, "_observer", mock_obs)
        assert mod.is_file_watcher_active() is True

    def test_is_file_watcher_active_false_when_none(self):
        mod, _inst, _cls = self._import_discovery_watcher()
        setattr(mod, "_observer", None)
        assert mod.is_file_watcher_active() is False

    def test_is_file_watcher_active_false_when_dead(self):
        mod, _inst, _cls = self._import_discovery_watcher()
        mock_obs = MagicMock()
        mock_obs.is_alive.return_value = False
        setattr(mod, "_observer", mock_obs)
        assert mod.is_file_watcher_active() is False
