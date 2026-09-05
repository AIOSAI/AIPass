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

import subprocess
import sys
import threading
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

            for key in list(sys.modules):
                if key.startswith("aipass.prax.apps.handlers.watcher"):
                    sys.modules.pop(key, None)
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

            for key in list(sys.modules):
                if key.startswith("aipass.prax.apps.handlers.watcher"):
                    sys.modules.pop(key, None)
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


# ============================================================================
# DISCOVERY/WATCHER.PY - DISPATCHER SURVIVAL (DPLAN-0305)
# ============================================================================
#
# These tests run against a REAL watchdog Observer on a REAL temp directory,
# deliberately, and none of them may be converted to mocks.
#
# The bug they pin killed the machine on 2026-08-18: an unguarded stat() on a
# file that vanished between event and handler raised FileNotFoundError, which
# escaped on_created into watchdog's dispatcher loop. That loop catches only
# queue.Empty (observers/api.py::EventDispatcher.run), so the dispatcher thread
# died permanently and silently while the emitter kept filling an unbounded
# queue — six long-running processes reached ~2.3GB each over 15 hours.
#
# A MagicMock dispatcher cannot die, so a mocked version of this test would pass
# against the broken code. The thread has to be real for the assertion to mean
# anything (prax observation, 2026-08-10: "a mocked output surface cannot fail").

import time as _time

import pytest


class TestDispatcherSurvivesHandlerFailure:
    """The discovery handler must never be able to kill its own dispatcher."""

    def _real_watcher_module(self):
        """Import the REAL discovery watcher, with only registry writes stubbed."""
        import importlib

        for key in list(sys.modules):
            if key.startswith("aipass.prax.apps.handlers.discovery"):
                sys.modules.pop(key, None)
        return importlib.import_module("aipass.prax.apps.handlers.discovery.watcher")

    def _start_real_observer(self, mod, root: Path):
        """Start a real observer, or skip if this host cannot give us inotify."""
        from watchdog.observers import Observer

        handler = mod.PythonFileWatcher()
        observer = Observer()
        try:
            observer.schedule(handler, str(root), recursive=True)
            observer.start()
        except OSError as e:  # inotify limit reached on a loaded CI box
            pytest.skip(f"cannot start a real observer here: {e}")
        return observer

    def test_a_vanishing_file_does_not_kill_the_dispatcher(self, tmp_path, monkeypatch):
        """THE regression pin: the exact 02:19 event, end to end, real threads.

        Create a .py file and delete it in the same breath, so the handler's
        stat() lands on a path that no longer exists. Before the guard this
        killed the dispatcher thread outright.
        """
        mod = self._real_watcher_module()
        monkeypatch.setattr(mod, "ECOSYSTEM_ROOT", tmp_path)
        monkeypatch.setattr(mod, "load_module_registry", lambda: {})
        monkeypatch.setattr(mod, "save_module_registry", lambda modules: None)
        monkeypatch.setattr(mod, "should_ignore_path", lambda p: False)

        observer = self._start_real_observer(mod, tmp_path)
        try:
            _time.sleep(0.3)
            assert observer.is_alive(), "fixture broken: dispatcher was not alive to begin with"

            victim = tmp_path / "probe.py"
            victim.write_text("x = 1\n")
            victim.unlink()  # gone before the handler can stat it
            _time.sleep(1.0)

            assert observer.is_alive(), (
                "the dispatcher thread died on a vanishing file — this is the DPLAN-0305 leak: "
                "the emitter keeps filling an unbounded queue that nobody drains again"
            )
        finally:
            observer.stop()
            observer.join(timeout=5)

    def test_the_queue_still_drains_after_a_handler_failure(self, tmp_path, monkeypatch):
        """Surviving is not enough — it has to keep CONSUMING.

        An alive-but-stuck dispatcher leaks exactly like a dead one, so assert
        against the queue itself rather than only the thread's liveness flag.
        """
        mod = self._real_watcher_module()
        monkeypatch.setattr(mod, "ECOSYSTEM_ROOT", tmp_path)
        monkeypatch.setattr(mod, "load_module_registry", lambda: {})
        monkeypatch.setattr(mod, "save_module_registry", lambda modules: None)
        monkeypatch.setattr(mod, "should_ignore_path", lambda p: False)

        observer = self._start_real_observer(mod, tmp_path)
        try:
            _time.sleep(0.3)
            victim = tmp_path / "probe.py"
            victim.write_text("x = 1\n")
            victim.unlink()
            _time.sleep(0.5)

            # Generate traffic the dispatcher must chew through.
            for i in range(40):
                (tmp_path / f"noise_{i}.txt").write_text("n")
            _time.sleep(1.5)

            assert observer.event_queue.qsize() == 0, (
                f"{observer.event_queue.qsize()} events are stranded in the queue — "
                "the dispatcher is no longer draining, which is the leak"
            )
        finally:
            observer.stop()
            observer.join(timeout=5)

    def test_no_exception_of_any_type_escapes_on_created(self, tmp_path, monkeypatch):
        """The guard must be `except Exception`, not `except FileNotFoundError`.

        FileNotFoundError is only the failure we happened to hit. Any exception
        reaching the dispatcher is equally fatal, so this raises something with
        no relationship to the filesystem and asserts the same containment.
        """
        mod = self._real_watcher_module()
        monkeypatch.setattr(mod, "ECOSYSTEM_ROOT", tmp_path)

        class _Boom(Exception):
            pass

        def _explode():
            raise _Boom("registry is unreachable")

        monkeypatch.setattr(mod, "load_module_registry", _explode)
        monkeypatch.setattr(mod, "should_ignore_path", lambda p: False)

        handler = mod.PythonFileWatcher()
        event = MagicMock()
        event.event_type = "created"  # dispatch() routes on this
        event.is_directory = False
        event.src_path = str(tmp_path / "anything.py")

        handler.dispatch(event)  # must not raise — the dispatcher calls it exactly like this

    def test_a_swallowed_failure_is_still_reported(self, tmp_path, monkeypatch):
        """Swallowing must not mean hiding — 15 silent hours is what made it costly."""
        mod = self._real_watcher_module()
        monkeypatch.setattr(mod, "ECOSYSTEM_ROOT", tmp_path)
        monkeypatch.setattr(mod, "should_ignore_path", lambda p: False)

        def _explode():
            raise RuntimeError("registry is unreachable")

        monkeypatch.setattr(mod, "load_module_registry", _explode)

        errors = []
        monkeypatch.setattr(mod.logger, "error", lambda msg, *a, **kw: errors.append(str(msg)))

        handler = mod.PythonFileWatcher()
        event = MagicMock()
        event.event_type = "created"  # dispatch() routes on this
        event.is_directory = False
        event.src_path = str(tmp_path / "anything.py")
        handler.dispatch(event)

        assert errors, "the handler swallowed a failure without saying anything"
        assert "anything.py" in errors[0], "the report must name the file that failed"
        assert "RuntimeError" in errors[0], "the report must name the error type"

    def test_a_healthy_created_file_is_still_registered(self, tmp_path, monkeypatch):
        """The guard must not have turned discovery into a no-op.

        A vacuity floor: if on_created silently stopped working, every test above
        would still pass. This one fails if the handler no longer registers.

        The size is written in BINARY and asserted against the file's own
        `stat().st_size`. The first version of this pin compared the recorded size
        to `len("y = 2\n")` — the length of the Python string — and went red on
        Windows CI with `assert 7 == 6`, because `write_text` translates `\n` to
        `\r\n` there. Production was honest the whole time: the handler records
        the true on-disk size. The pin was the platform-naive half, and what it
        should say is "the registered size is the REAL size", not "the size is 6".
        """
        mod = self._real_watcher_module()
        monkeypatch.setattr(mod, "ECOSYSTEM_ROOT", tmp_path)
        monkeypatch.setattr(mod, "should_ignore_path", lambda p: False)
        monkeypatch.setattr(mod, "load_module_registry", lambda: {})

        saved = {}
        monkeypatch.setattr(mod, "save_module_registry", lambda modules: saved.update(modules))

        real_file = tmp_path / "keeper.py"
        real_file.write_bytes(b"y = 2\n")  # binary: exactly 6 bytes on every platform

        handler = mod.PythonFileWatcher()
        event = MagicMock()
        event.event_type = "created"  # dispatch() routes on this
        event.is_directory = False
        event.src_path = str(real_file)
        handler.dispatch(event)

        assert "keeper" in saved, "a perfectly good new module was not registered"
        assert saved["keeper"]["size"] == real_file.stat().st_size
        assert saved["keeper"]["size"] == 6, "binary write should be 6 bytes on every platform"

    def test_the_recorded_size_is_the_real_size_under_crlf(self, tmp_path, monkeypatch):
        """The Windows half of the size pin, run on Linux.

        Windows text mode turns `\n` into `\r\n`, so a file whose Python string
        is 6 characters occupies 7 bytes on disk. That difference is exactly what
        reddened CI. Writing CRLF explicitly reproduces the Windows byte layout on
        any platform, so the property — the registry records what the OS actually
        holds, whatever the line ending — is proven in both worlds from one lane.

        Same split as the 2026-08-08 Windows path work: run the platform branch by
        name rather than claiming a platform the suite never executes.
        """
        mod = self._real_watcher_module()
        monkeypatch.setattr(mod, "ECOSYSTEM_ROOT", tmp_path)
        monkeypatch.setattr(mod, "should_ignore_path", lambda p: False)
        monkeypatch.setattr(mod, "load_module_registry", lambda: {})

        saved = {}
        monkeypatch.setattr(mod, "save_module_registry", lambda modules: saved.update(modules))

        crlf_file = tmp_path / "crlf.py"
        crlf_file.write_bytes(b"y = 2\r\n")  # what Windows text mode produces
        assert crlf_file.stat().st_size == 7, "fixture broken: CRLF file should be 7 bytes"

        handler = mod.PythonFileWatcher()
        event = MagicMock()
        event.event_type = "created"
        event.is_directory = False
        event.src_path = str(crlf_file)
        handler.dispatch(event)

        assert "crlf" in saved
        assert saved["crlf"]["size"] == crlf_file.stat().st_size == 7, (
            "the registry must record the bytes the OS holds, not the length of a Python string"
        )

    def test_the_file_is_stat_ed_once_not_twice(self, tmp_path, monkeypatch):
        """Two stats are two chances to lose the same race the guard now catches.

        The original built `size` and `modified_time` from separate stat() calls,
        so a file could vanish between them and produce a torn description.
        """
        mod = self._real_watcher_module()
        monkeypatch.setattr(mod, "ECOSYSTEM_ROOT", tmp_path)
        monkeypatch.setattr(mod, "should_ignore_path", lambda p: False)
        monkeypatch.setattr(mod, "load_module_registry", lambda: {})
        monkeypatch.setattr(mod, "save_module_registry", lambda modules: None)

        real_file = tmp_path / "counted.py"
        real_file.write_text("z = 3\n")

        calls = []
        original_stat = Path.stat

        def counting_stat(self, *args, **kwargs):
            if self == real_file:
                calls.append(1)
            return original_stat(self, *args, **kwargs)

        monkeypatch.setattr(Path, "stat", counting_stat)

        handler = mod.PythonFileWatcher()
        event = MagicMock()
        event.event_type = "created"  # dispatch() routes on this
        event.is_directory = False
        event.src_path = str(real_file)
        handler.dispatch(event)

        assert len(calls) == 1, f"expected exactly one stat() on the target, got {len(calls)}"


class TestWatcherLiveness:
    """A liveness check that cannot fire after startup is not a liveness check.

    `is_file_watcher_active()` existed and was even called — but only from
    `SystemLogger._ensure_watcher`, whose body runs once per process behind a
    `_watcher_started` flag that is never reset. It therefore answered at the one
    moment the watcher could not yet have died, and never again. The dispatcher
    died at 02:19 on 2026-08-18 and no process noticed for 15 hours.
    """

    def _fresh_module(self):
        import importlib

        for key in list(sys.modules):
            if key.startswith("aipass.prax.apps.handlers.discovery"):
                sys.modules.pop(key, None)
        mod = importlib.import_module("aipass.prax.apps.handlers.discovery.watcher")
        mod._LIVENESS.last_check = 0.0
        mod._LIVENESS.death_reported = False
        return mod

    def _dead_observer(self):
        obs = MagicMock()
        obs.is_alive.return_value = False
        obs.event_queue.qsize.return_value = 91234
        return obs

    def test_a_dead_watcher_is_reported_loudly(self, monkeypatch):
        mod = self._fresh_module()
        monkeypatch.setattr(mod, "_observer", self._dead_observer())
        errors = []
        monkeypatch.setattr(mod.logger, "error", lambda msg, *a, **kw: errors.append(str(msg)))

        assert mod.check_file_watcher_liveness() is False
        assert errors, "the watcher died and nothing was logged — this is the 15-hour silence"
        assert "DEAD" in errors[0]

    def test_the_death_report_carries_the_queue_depth(self, monkeypatch):
        """The number that makes it actionable: how much memory is being retained."""
        mod = self._fresh_module()
        monkeypatch.setattr(mod, "_observer", self._dead_observer())
        errors = []
        monkeypatch.setattr(mod.logger, "error", lambda msg, *a, **kw: errors.append(str(msg)))

        mod.check_file_watcher_liveness()
        assert "91234" in errors[0], "the report should say how many events are stranded"

    def test_the_death_is_reported_once_not_on_every_check(self, monkeypatch):
        """prax owns the runaway-log detector; a health check must not flood."""
        mod = self._fresh_module()
        monkeypatch.setattr(mod, "_observer", self._dead_observer())
        errors = []
        monkeypatch.setattr(mod.logger, "error", lambda msg, *a, **kw: errors.append(str(msg)))

        for _ in range(50):
            mod.check_file_watcher_liveness(force=True)

        assert len(errors) == 1, f"death reported {len(errors)} times — that is a log flood"

    def test_a_live_watcher_reports_nothing(self, monkeypatch):
        mod = self._fresh_module()
        obs = MagicMock()
        obs.is_alive.return_value = True
        monkeypatch.setattr(mod, "_observer", obs)
        errors = []
        monkeypatch.setattr(mod.logger, "error", lambda msg, *a, **kw: errors.append(str(msg)))

        assert mod.check_file_watcher_liveness() is True
        assert not errors

    def test_no_watcher_in_this_process_is_healthy_not_dead(self, monkeypatch):
        """Most processes never start one; absence must not read as failure."""
        mod = self._fresh_module()
        monkeypatch.setattr(mod, "_observer", None)
        errors = []
        monkeypatch.setattr(mod.logger, "error", lambda msg, *a, **kw: errors.append(str(msg)))

        assert mod.check_file_watcher_liveness() is True
        assert not errors

    def test_the_check_is_throttled(self, monkeypatch):
        """It sits on the logging path — it must not call is_alive() every time."""
        mod = self._fresh_module()
        obs = MagicMock()
        obs.is_alive.return_value = True
        monkeypatch.setattr(mod, "_observer", obs)

        for _ in range(200):
            mod.check_file_watcher_liveness()

        assert obs.is_alive.call_count == 1, (
            f"is_alive() ran {obs.is_alive.call_count} times for 200 log calls — throttle is not working"
        )

    def test_a_restarted_watcher_clears_the_latch(self, monkeypatch):
        """A second death must be announced too, not suppressed by the first."""
        mod = self._fresh_module()
        dead = self._dead_observer()
        monkeypatch.setattr(mod, "_observer", dead)
        errors = []
        monkeypatch.setattr(mod.logger, "error", lambda msg, *a, **kw: errors.append(str(msg)))

        mod.check_file_watcher_liveness(force=True)
        assert len(errors) == 1

        alive = MagicMock()
        alive.is_alive.return_value = True
        monkeypatch.setattr(mod, "_observer", alive)
        mod.check_file_watcher_liveness(force=True)  # recovery clears the latch

        monkeypatch.setattr(mod, "_observer", self._dead_observer())
        mod.check_file_watcher_liveness(force=True)
        assert len(errors) == 2, "a second, distinct death went unreported"

    def test_the_liveness_check_never_raises(self, monkeypatch):
        """It is called BY the logger. A health check that breaks logging is worse."""
        mod = self._fresh_module()
        exploding = MagicMock()
        exploding.is_alive.side_effect = RuntimeError("observer internals exploded")
        monkeypatch.setattr(mod, "_observer", exploding)

        assert mod.check_file_watcher_liveness(force=True) is True  # fails open

    def test_a_failed_trigger_does_not_silence_the_log_line(self, monkeypatch):
        """The log line is the primary report; trigger is the nice-to-have."""
        mod = self._fresh_module()
        monkeypatch.setattr(mod, "_observer", self._dead_observer())
        errors = []
        monkeypatch.setattr(mod.logger, "error", lambda msg, *a, **kw: errors.append(str(msg)))
        monkeypatch.setattr(mod, "_HAS_TRIGGER", True)
        broken = MagicMock()
        broken.fire.side_effect = OSError("trigger bus unavailable")
        monkeypatch.setattr(mod, "trigger", broken)

        mod.check_file_watcher_liveness(force=True)
        assert errors, "a broken trigger swallowed the death report"

    def test_the_common_case_does_not_touch_the_lock(self, monkeypatch):
        """The hot path must stay lock-free.

        This runs on EVERY log call in the ecosystem. Throttling alone is not
        enough: if the throttle check moves inside the lock, behaviour is
        identical and every log call in every process starts serialising on a
        single mutex. That regression is invisible to every other test here —
        it changes cost, not answers — so it gets its own pin.
        """
        mod = self._fresh_module()
        obs = MagicMock()
        obs.is_alive.return_value = True
        monkeypatch.setattr(mod, "_observer", obs)

        acquisitions = {"n": 0}
        real_lock = mod._LIVENESS.lock

        class CountingLock:
            def __enter__(self):
                acquisitions["n"] += 1
                return real_lock.__enter__()

            def __exit__(self, *exc):
                return real_lock.__exit__(*exc)

        monkeypatch.setattr(mod._LIVENESS, "lock", CountingLock())

        for _ in range(200):
            mod.check_file_watcher_liveness()

        assert acquisitions["n"] == 1, (
            f"the lock was taken {acquisitions['n']} times for 200 log calls — "
            "the throttle check has moved inside the lock and every log call now contends"
        )


# ============================================================================
# THE OPTIONAL TRIGGER IMPORT - it must never take prax's import down
# ============================================================================

_DENY_TRIGGER = '''
import importlib.abc
import sys

TARGET = "aipass.trigger.apps.modules.core"


class DenyTrigger(importlib.abc.MetaPathFinder):
    """Make the optional cross-branch import fail the way it failed for real."""

    def find_spec(self, fullname, path=None, target=None):
        if fullname == TARGET:
            raise OSError(2, "No such file or directory")
        return None


sys.meta_path.insert(0, DenyTrigger())
'''


def _run_with_trigger_denied(body: str) -> subprocess.CompletedProcess:
    """Run ``body`` in a fresh interpreter where importing trigger raises OSError.

    A subprocess because the claim is about IMPORT TIME: watcher.py's fallback runs
    once, at module level, and this process already imported it successfully. Fed on
    STDIN rather than -c so a traceback names real line numbers.
    """
    script = _DENY_TRIGGER + body
    return subprocess.run(
        [sys.executable, "-"],
        input=script,
        text=True,
        capture_output=True,
        cwd=str(Path(__file__).resolve().parents[3]),
    )


class TestOptionalTriggerIntegration:
    """`trigger` is declared optional. The fallback must be as wide as the failures.

    MEASURED 2026-08-31: it was not. The except clause caught only ImportError, and
    @trigger's own handlers/__init__.py guard raised FileNotFoundError — an OSError,
    not an ImportError — while resolving a frame filename without a working
    directory. So prax's whole logger import chain died on a failure in a dependency
    prax had already declared it could live without. The bug is not that trigger
    raised; a peer branch is allowed to be broken. The bug is that "graceful
    fallback if trigger not available" was written to cover one spelling of
    unavailable.
    """

    def test_the_denial_is_live(self):
        """Negative control FOR the positive control below.

        If the injected finder never fires, the next test passes for the boring
        reason that trigger imports fine on this machine — a green that proves
        nothing. This asserts the hostile world is actually hostile before any
        test relies on it.
        """
        result = _run_with_trigger_denied(
            "\n"
            "try:\n"
            "    import aipass.trigger.apps.modules.core  # noqa: F401\n"
            "except BaseException as exc:\n"
            "    print('DENIED', type(exc).__name__, isinstance(exc, OSError))\n"
            "else:\n"
            "    print('NOT DENIED')\n"
        )
        # FileNotFoundError, not the bare OSError raised: Python's errno mapping
        # picks the subclass for errno 2. That is exactly the exception @trigger's
        # guard produced on the real machine, so the world is faithful, not merely
        # similar. The pin asserts the CATEGORY the fallback has to cover.
        assert "DENIED FileNotFoundError True" in result.stdout, (
            "the meta_path finder did not deny the trigger import, so every pin built "
            f"on this world is vacuous.\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_an_oserror_from_the_optional_import_falls_back(self):
        """Prax imports, and knows trigger is absent, when trigger raises OSError."""
        result = _run_with_trigger_denied(
            "\nfrom aipass.prax.apps.handlers.discovery import watcher\nprint('HAS_TRIGGER', watcher._HAS_TRIGGER)\n"
        )
        assert result.returncode == 0, (
            "an OSError from the OPTIONAL trigger import killed prax's watcher import.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert "HAS_TRIGGER False" in result.stdout, (
            "the import survived but still believes trigger is available — the fallback "
            f"did not run.\nstdout: {result.stdout}"
        )

    def test_the_public_logger_survives_it_too(self):
        """The chain that actually broke: modules/logger.py -> watcher -> trigger.

        Pinned at the public entry point rather than only at the handler, because
        the handler is an implementation detail and every other branch in the fleet
        reaches this through `get_system_logger`.
        """
        result = _run_with_trigger_denied(
            "\n"
            "from aipass.prax.apps.modules.logger import get_system_logger\n"
            "get_system_logger().info('the optional dependency is absent and that is fine')\n"
            "print('LOGGER OK')\n"
        )
        assert "LOGGER OK" in result.stdout, (
            "prax's public logger could not be built while trigger was unavailable.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )


# ============================================================================
# THE BACKGROUND START — the walk must not be on a thread anyone waits on
# ============================================================================


class TestTheBackgroundStartDoesNotMakeTheCallerWait:
    """Scheduling the watch is slow, and the first log line used to pay for it.

    MEASURED 2026-09-04, this repo, 1605 directories under ECOSYSTEM_ROOT:
    start_file_watcher() costs 0.119s in the calling thread when that thread is
    alone and 13.9s — 117x — with one other Python thread busy, because watchdog
    installs one inotify watch per directory and each of those syscalls drops
    the GIL and has to win it back. SystemLogger._ensure_watcher called it on
    the first log line of the process, so a test suite whose only crime was to
    log something stalled for seconds on a watcher it never asked for.

    These pin the property that fixes it — the caller returns while the walk is
    still running — and the two things that property could easily break: a
    second observer installed behind the first, and an inotify failure that no
    longer has a caller to raise to.
    """

    def _module_and_a_gated_observer(self):
        """The discovery watcher with a schedule() that blocks until released."""
        mod, observer_inst, _cls = TestDiscoveryWatcher()._import_discovery_watcher()
        setattr(mod, "_observer", None)
        setattr(mod, "_start_thread", None)

        gate = threading.Event()
        observer_inst.schedule.side_effect = lambda *args, **kwargs: gate.wait(30)
        return mod, observer_inst, gate

    def test_the_caller_returns_while_the_walk_is_still_running(self):
        """The whole point: the walk outlives the call that asked for it."""
        mod, observer_inst, gate = self._module_and_a_gated_observer()

        try:
            mod.start_file_watcher_in_background()

            # Still inside schedule(), which has not been released.
            assert getattr(mod, "_start_thread").is_alive()
            assert getattr(mod, "_observer") is None

            gate.set()
            getattr(mod, "_start_thread").join(timeout=10)

            observer_inst.schedule.assert_called_once()
            observer_inst.start.assert_called_once()
            assert getattr(mod, "_observer") is observer_inst
        finally:
            gate.set()

    def test_a_second_call_during_the_walk_starts_no_second_observer(self):
        """Two walks install two watches on every directory and deliver every
        event twice — the failure mode a non-blocking start invites."""
        mod, observer_inst, gate = self._module_and_a_gated_observer()

        try:
            mod.start_file_watcher_in_background()
            mod.start_file_watcher_in_background()
            mod.start_file_watcher_in_background()

            gate.set()
            getattr(mod, "_start_thread").join(timeout=10)

            observer_inst.schedule.assert_called_once()
            observer_inst.start.assert_called_once()
        finally:
            gate.set()

    def test_a_synchronous_start_during_the_walk_waits_and_installs_nothing(self):
        """The other half of the same rule: the two doors share one lock."""
        mod, observer_inst, gate = self._module_and_a_gated_observer()

        try:
            mod.start_file_watcher_in_background()
            gate.set()
            getattr(mod, "_start_thread").join(timeout=10)

            mod.start_file_watcher()

            observer_inst.schedule.assert_called_once()
        finally:
            gate.set()

    def test_an_inotify_limit_is_logged_not_raised(self):
        """There is no caller left to hand the OSError to.

        _ensure_watcher used to catch it and warn; on a thread nobody joins an
        escaping exception is a silent death, so the warning moved inside with
        the same words.
        """
        mod, observer_inst, _cls = TestDiscoveryWatcher()._import_discovery_watcher()
        setattr(mod, "_observer", None)
        setattr(mod, "_start_thread", None)
        observer_inst.schedule.side_effect = OSError("inotify watch limit reached")

        with patch.object(mod, "logger") as mock_logger:
            mod.start_file_watcher_in_background()
            getattr(mod, "_start_thread").join(timeout=10)

            assert getattr(mod, "_observer") is None
            warnings = " ".join(str(call) for call in mock_logger.warning.call_args_list)
            assert "inotify limit reached" in warnings
