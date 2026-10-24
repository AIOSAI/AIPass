# =================== AIPass ====================
# Name: test_watcher.py
# Description: Tests for file system watcher handlers
# Version: 1.2.0
# Created: 2026-04-03
# Modified: 2026-10-23
# =============================================

"""Tests for apps/handlers/discovery/watcher.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(json_structure) — _report_watcher_death's log_operation record, covered by that row

import subprocess
import sys
import time as _time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from aipass.prax.apps.handlers.discovery import watcher as discovery_watcher


def _discovery_watcher_doubled(monkeypatch, tmp_path):
    """The discovery watcher with its collaborators doubled where it binds them, its state fresh."""
    observer_cls = MagicMock()
    fake = tmp_path / "fake"
    monkeypatch.setattr(discovery_watcher, "WatchdogObserver", observer_cls)
    monkeypatch.setattr(discovery_watcher, "ECOSYSTEM_ROOT", fake / "ecosystem")
    monkeypatch.setattr(discovery_watcher, "get_system_logs_dir", lambda: fake / "logs" / "system")
    monkeypatch.setattr(discovery_watcher, "get_module_logs_dir", lambda module_name=None: fake / "logs" / "modules")
    monkeypatch.setattr(discovery_watcher, "load_module_registry", lambda: {})
    monkeypatch.setattr(discovery_watcher, "save_module_registry", MagicMock())
    monkeypatch.setattr(discovery_watcher, "json_handler", MagicMock())
    _fresh_watcher_state(monkeypatch)
    return discovery_watcher, observer_cls.return_value, observer_cls


def _fresh_watcher_state(monkeypatch):
    """The discovery watcher's state as a fresh import leaves it, undone after the test."""
    monkeypatch.setattr(discovery_watcher, "_observer", None)
    monkeypatch.setattr(discovery_watcher, "_LIVENESS", discovery_watcher.LivenessState())


class TestDiscoveryWatcher:
    """Tests for the discovery watcher that registers new Python modules."""

    @pytest.fixture(autouse=True)
    def _keep_monkeypatch(self, monkeypatch):
        self._monkeypatch = monkeypatch

    def _import_discovery_watcher(self, tmp_path):
        return _discovery_watcher_doubled(self._monkeypatch, tmp_path)

    def test_the_module_holds_no_trigger_at_import_time(self, tmp_path):
        """No module-level trigger import or fire gate: that import loaded dead package shells everywhere."""
        mod, _inst, _cls = self._import_discovery_watcher(tmp_path)

        assert not hasattr(mod, "_HAS_TRIGGER")
        assert not hasattr(mod, "trigger")

    def test_start_file_watcher_creates_and_starts_observer(self, tmp_path, monkeypatch):
        mod, observer_inst, _cls = self._import_discovery_watcher(tmp_path)
        monkeypatch.setattr(mod, "_observer", None)
        mod.start_file_watcher()
        observer_inst.schedule.assert_called_once()
        observer_inst.start.assert_called_once()
        assert getattr(mod, "_observer") is observer_inst

    def test_start_file_watcher_skips_if_already_running(self, tmp_path, monkeypatch):
        mod, observer_inst, obs_cls = self._import_discovery_watcher(tmp_path)
        existing_observer = MagicMock()
        existing_observer.is_alive.return_value = True
        monkeypatch.setattr(mod, "_observer", existing_observer)

        mod.start_file_watcher()

        observer_inst.start.assert_not_called()

    def test_stop_file_watcher_stops_and_clears(self, tmp_path, monkeypatch):
        mod, _inst, _cls = self._import_discovery_watcher(tmp_path)
        mock_obs = MagicMock()
        mock_obs.is_alive.return_value = True
        monkeypatch.setattr(mod, "_observer", mock_obs)

        mod.stop_file_watcher()

        mock_obs.stop.assert_called_once_with()
        mock_obs.join.assert_called_once_with()
        assert getattr(mod, "_observer") is None

    def test_stop_file_watcher_noop_when_not_running(self, tmp_path, monkeypatch):
        """No observer, or a dead one: neither is stopped or joined (stop() on a dead observer raises)."""
        mod, _inst, _cls = self._import_discovery_watcher(tmp_path)

        monkeypatch.setattr(mod, "_observer", None)
        assert mod.stop_file_watcher() is None
        assert getattr(mod, "_observer") is None

        dead = MagicMock()
        dead.is_alive.return_value = False
        monkeypatch.setattr(mod, "_observer", dead)

        mod.stop_file_watcher()

        dead.stop.assert_not_called()
        dead.join.assert_not_called()
        assert getattr(mod, "_observer") is dead

    def test_is_file_watcher_active_true_when_alive(self, tmp_path, monkeypatch):
        mod, _inst, _cls = self._import_discovery_watcher(tmp_path)
        mock_obs = MagicMock()
        mock_obs.is_alive.return_value = True
        monkeypatch.setattr(mod, "_observer", mock_obs)
        assert mod.is_file_watcher_active() is True

    def test_is_file_watcher_active_false_when_none(self, tmp_path, monkeypatch):
        mod, _inst, _cls = self._import_discovery_watcher(tmp_path)
        monkeypatch.setattr(mod, "_observer", None)
        assert mod.is_file_watcher_active() is False

    def test_is_file_watcher_active_false_when_dead(self, tmp_path, monkeypatch):
        mod, _inst, _cls = self._import_discovery_watcher(tmp_path)
        mock_obs = MagicMock()
        mock_obs.is_alive.return_value = False
        monkeypatch.setattr(mod, "_observer", mock_obs)
        assert mod.is_file_watcher_active() is False


# Real Observer on a real temp dir, never mocks: a MagicMock dispatcher cannot die. watchdog's
# dispatcher loop catches only queue.Empty, so an escaping handler error kills it and the queue grows unbounded.


class TestDispatcherSurvivesHandlerFailure:
    """The discovery handler must never be able to kill its own dispatcher."""

    @pytest.fixture(autouse=True)
    def _keep_monkeypatch(self, monkeypatch):
        self._monkeypatch = monkeypatch

    def _real_watcher_module(self):
        """The REAL discovery watcher, bound at the top, its state fresh."""
        _fresh_watcher_state(self._monkeypatch)
        return discovery_watcher

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

    def _close_the_far_side(self, mod, monkeypatch, tmp_path: Path) -> MagicMock:
        """Stub the log-dir resolvers and logger a registering on_created reaches; returns the logger recorder."""
        monkeypatch.setattr(mod, "get_system_logs_dir", lambda: tmp_path / "system_logs")
        monkeypatch.setattr(mod, "get_module_logs_dir", lambda name: tmp_path / name / "logs")
        recorder = MagicMock()
        monkeypatch.setattr(mod, "logger", recorder)
        return recorder

    def test_a_vanishing_file_does_not_kill_the_dispatcher(self, tmp_path, monkeypatch):
        """A .py file deleted before the handler's stat() must not kill the dispatcher thread."""
        mod = self._real_watcher_module()
        monkeypatch.setattr(mod, "ECOSYSTEM_ROOT", tmp_path)
        monkeypatch.setattr(mod, "load_module_registry", lambda: {})
        monkeypatch.setattr(mod, "save_module_registry", lambda modules: None)
        monkeypatch.setattr(mod, "should_ignore_path", lambda p: p.parent != tmp_path)
        monkeypatch.setattr(mod, "_get_trigger", lambda: None)
        self._close_the_far_side(mod, monkeypatch, tmp_path)

        observer = self._start_real_observer(mod, tmp_path)
        try:
            _time.sleep(0.3)
            assert observer.is_alive(), "fixture broken: dispatcher was not alive to begin with"

            victim = tmp_path / "probe.py"
            victim.write_text("x = 1\n", encoding="utf-8")
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
        """Surviving is not enough: an alive-but-stuck dispatcher leaks too, so the queue must drain."""
        mod = self._real_watcher_module()
        monkeypatch.setattr(mod, "ECOSYSTEM_ROOT", tmp_path)
        monkeypatch.setattr(mod, "load_module_registry", lambda: {})
        monkeypatch.setattr(mod, "save_module_registry", lambda modules: None)
        monkeypatch.setattr(mod, "should_ignore_path", lambda p: p.parent != tmp_path)
        monkeypatch.setattr(mod, "_get_trigger", lambda: None)
        self._close_the_far_side(mod, monkeypatch, tmp_path)

        observer = self._start_real_observer(mod, tmp_path)
        try:
            _time.sleep(0.3)
            victim = tmp_path / "probe.py"
            victim.write_text("x = 1\n", encoding="utf-8")
            victim.unlink()
            _time.sleep(0.5)

            for i in range(40):
                (tmp_path / f"noise_{i}.txt").write_text("n", encoding="utf-8")
            _time.sleep(1.5)

            assert observer.event_queue.qsize() == 0, (
                f"{observer.event_queue.qsize()} events are stranded in the queue — "
                "the dispatcher is no longer draining, which is the leak"
            )
        finally:
            observer.stop()
            observer.join(timeout=5)

    def test_no_exception_of_any_type_escapes_on_created(self, tmp_path, monkeypatch):
        """The guard must be `except Exception`: any exception reaching the dispatcher is fatal."""
        mod = self._real_watcher_module()
        monkeypatch.setattr(mod, "ECOSYSTEM_ROOT", tmp_path)

        class _Boom(Exception):
            pass

        def _explode():
            raise _Boom("registry is unreachable")

        monkeypatch.setattr(mod, "load_module_registry", _explode)
        asked = []
        monkeypatch.setattr(mod, "should_ignore_path", lambda p: asked.append(p) or p.parent != tmp_path)

        saved = []
        monkeypatch.setattr(mod, "save_module_registry", lambda modules: saved.append(modules))

        errors = []
        monkeypatch.setattr(mod.logger, "error", lambda msg, *a, **kw: errors.append(str(msg)))

        handler = mod.PythonFileWatcher()
        event = MagicMock()
        event.event_type = "created"  # dispatch() routes on this
        event.is_directory = False
        event.src_path = str(tmp_path / "anything.py")

        assert handler.dispatch(event) is None

        assert errors, "a _Boom escaped or vanished silently"
        assert "_Boom" in errors[0], "the report must name the error type it did not expect"
        assert "anything.py" in errors[0], "the report must name the file that failed"
        assert saved == [], "the event must be dropped, not half-registered"
        assert asked == [tmp_path / "anything.py"], "the ignore filter was never consulted"

    def test_a_swallowed_failure_is_still_reported(self, tmp_path, monkeypatch):
        """Swallowing must not mean hiding: the failure is reported, naming file and type."""
        mod = self._real_watcher_module()
        monkeypatch.setattr(mod, "ECOSYSTEM_ROOT", tmp_path)
        asked = []
        monkeypatch.setattr(mod, "should_ignore_path", lambda p: asked.append(p) or p.parent != tmp_path)

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
        assert asked == [tmp_path / "anything.py"], "the ignore filter was never consulted"

    def test_a_file_that_vanished_is_a_miss_not_an_error(self, tmp_path, monkeypatch):
        """A file gone before its stat is the ordinary case: dropped and logged at info, never ERROR."""
        mod = self._real_watcher_module()
        monkeypatch.setattr(mod, "ECOSYSTEM_ROOT", tmp_path)
        asked = []
        monkeypatch.setattr(mod, "should_ignore_path", lambda p: asked.append(p) or p.parent != tmp_path)
        monkeypatch.setattr(mod, "load_module_registry", lambda: {})
        monkeypatch.setattr(mod, "save_module_registry", lambda modules: None)

        errors, infos = [], []
        monkeypatch.setattr(mod.logger, "error", lambda msg, *a, **kw: errors.append(str(msg)))
        monkeypatch.setattr(mod.logger, "info", lambda msg, *a, **kw: infos.append(str(msg)))

        gone = tmp_path / "vanished.py"
        event = MagicMock()
        event.event_type = "created"
        event.is_directory = False
        event.src_path = str(gone)
        handler = mod.PythonFileWatcher()
        handler.dispatch(event)

        assert not errors, f"a file vanishing before its stat is not an error: {errors}"
        assert any("vanished.py" in line for line in infos), (
            f"the miss must still be on the record, naming the file: {infos}"
        )
        assert asked == [gone], "the ignore filter was never consulted"

    def test_a_healthy_created_file_is_still_registered(self, tmp_path, monkeypatch):
        """Vacuity floor: a healthy new file is still registered, at its real on-disk size (bytes, not str)."""
        mod = self._real_watcher_module()
        monkeypatch.setattr(mod, "ECOSYSTEM_ROOT", tmp_path)
        asked = []
        monkeypatch.setattr(mod, "should_ignore_path", lambda p: asked.append(p) or p.parent != tmp_path)
        monkeypatch.setattr(mod, "load_module_registry", lambda: {})
        bus = MagicMock()
        monkeypatch.setattr(mod, "_get_trigger", lambda: bus)

        saved = {}
        monkeypatch.setattr(mod, "save_module_registry", lambda modules: saved.update(modules))
        self._close_the_far_side(mod, monkeypatch, tmp_path)

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
        assert saved["keeper"]["system_log_file"] == str(tmp_path / "system_logs" / "prax_keeper.log")
        assert saved["keeper"]["log_file"] == str(tmp_path / "prax" / "logs" / "keeper.log")
        assert asked == [real_file], "the ignore filter was never consulted"
        bus.fire.assert_called_once_with(
            "module_discovered", module_name="keeper", file_path=str(real_file), relative_path="keeper.py"
        )

    def test_an_unreadable_registry_is_never_overwritten_by_one_new_module(self, tmp_path, monkeypatch):
        """An unreadable registry (None) is never replaced by one new entry: nothing saved, nothing fired."""
        mod = self._real_watcher_module()
        monkeypatch.setattr(mod, "ECOSYSTEM_ROOT", tmp_path)
        monkeypatch.setattr(mod, "should_ignore_path", lambda p: p.parent != tmp_path)
        monkeypatch.setattr(mod, "load_module_registry", lambda: None)
        bus = MagicMock()
        monkeypatch.setattr(mod, "_get_trigger", lambda: bus)
        saves = []
        monkeypatch.setattr(mod, "save_module_registry", saves.append)
        log = self._close_the_far_side(mod, monkeypatch, tmp_path)

        real_file = tmp_path / "keeper.py"
        real_file.write_bytes(b"y = 2\n")
        handler = mod.PythonFileWatcher()
        event = MagicMock()
        event.event_type = "created"
        event.is_directory = False
        event.src_path = str(real_file)
        handler.dispatch(event)

        assert saves == []
        bus.fire.assert_not_called()
        log.error.assert_not_called()
        log.warning.assert_called_once_with(
            f"[watcher] The module registry could not be read, so {real_file} was not registered"
        )

    def test_a_file_created_in_a_dropbox_or_an_archive_is_not_registered(self, tmp_path, monkeypatch):
        """Nothing looks into a dropbox or a sandbox like .archive; the live file beside them is the control."""
        mod = self._real_watcher_module()
        monkeypatch.setattr(mod, "ECOSYSTEM_ROOT", tmp_path)
        monkeypatch.setattr(mod, "should_ignore_path", lambda p: p.suffix != ".py")
        monkeypatch.setattr(mod, "load_module_registry", lambda: {})
        monkeypatch.setattr(mod, "_get_trigger", lambda: MagicMock())
        saved = {}
        monkeypatch.setattr(mod, "save_module_registry", lambda modules: saved.update(modules))
        self._close_the_far_side(mod, monkeypatch, tmp_path)

        handler = mod.PythonFileWatcher()
        for rel in ("dropbox/handed.py", ".archive/old.py", "apps/live.py"):
            created = tmp_path.joinpath("branch", *rel.split("/"))
            created.parent.mkdir(parents=True, exist_ok=True)
            created.write_bytes(b"x = 1\n")
            event = MagicMock()
            event.event_type = "created"
            event.is_directory = False
            event.src_path = str(created)
            handler.dispatch(event)

        assert set(saved) == {"live"}

    def test_the_recorded_size_is_the_real_size_under_crlf(self, tmp_path, monkeypatch):
        """The Windows half of the size pin, run on Linux: CRLF bytes are recorded as the OS holds them."""
        mod = self._real_watcher_module()
        monkeypatch.setattr(mod, "ECOSYSTEM_ROOT", tmp_path)
        asked = []
        monkeypatch.setattr(mod, "should_ignore_path", lambda p: asked.append(p) or p.parent != tmp_path)
        monkeypatch.setattr(mod, "load_module_registry", lambda: {})
        bus = MagicMock()
        monkeypatch.setattr(mod, "_get_trigger", lambda: bus)

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
        assert asked == [crlf_file], "the ignore filter was never consulted"
        bus.fire.assert_called_once_with(
            "module_discovered", module_name="crlf", file_path=str(crlf_file), relative_path="crlf.py"
        )

    def test_the_file_is_stat_ed_once_not_twice(self, tmp_path, monkeypatch):
        """One stat, not two: a file vanishing between two stats gives a torn description."""
        mod = self._real_watcher_module()
        monkeypatch.setattr(mod, "ECOSYSTEM_ROOT", tmp_path)
        asked = []
        monkeypatch.setattr(mod, "should_ignore_path", lambda p: asked.append(p) or p.parent != tmp_path)
        monkeypatch.setattr(mod, "load_module_registry", lambda: {})
        monkeypatch.setattr(mod, "save_module_registry", lambda modules: None)
        bus = MagicMock()
        monkeypatch.setattr(mod, "_get_trigger", lambda: bus)

        real_file = tmp_path / "counted.py"
        real_file.write_text("z = 3\n", encoding="utf-8")

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
        assert asked == [real_file], "the ignore filter was never consulted"
        bus.fire.assert_called_once_with(
            "module_discovered", module_name="counted", file_path=str(real_file), relative_path="counted.py"
        )

    def test_a_discovered_module_reaches_the_bus(self, tmp_path, monkeypatch):
        """`module_discovered` actually fires; a module-level trigger gate once kept it dead."""
        mod = self._real_watcher_module()
        monkeypatch.setattr(mod, "ECOSYSTEM_ROOT", tmp_path)
        asked = []
        monkeypatch.setattr(mod, "should_ignore_path", lambda p: asked.append(p) or p.parent != tmp_path)
        monkeypatch.setattr(mod, "load_module_registry", lambda: {})
        monkeypatch.setattr(mod, "save_module_registry", lambda modules: None)
        bus = MagicMock()
        monkeypatch.setattr(mod, "_get_trigger", lambda: bus)

        new_file = tmp_path / "brand_new.py"
        new_file.write_text("x = 1\n", encoding="utf-8")

        event = MagicMock()
        event.event_type = "created"
        event.is_directory = False
        event.src_path = str(new_file)
        mod.PythonFileWatcher().dispatch(event)

        assert bus.fire.call_count == 1
        assert bus.fire.call_args[0][0] == "module_discovered"
        assert bus.fire.call_args[1]["module_name"] == "brand_new"
        assert asked == [new_file], "the ignore filter was never consulted"

    def test_a_failed_discovery_fire_does_not_lose_the_registry_write(self, tmp_path, monkeypatch):
        """The registry entry is the product, the event the notification: a raising trigger is survived."""
        mod = self._real_watcher_module()
        monkeypatch.setattr(mod, "ECOSYSTEM_ROOT", tmp_path)
        asked = []
        monkeypatch.setattr(mod, "should_ignore_path", lambda p: asked.append(p) or p.parent != tmp_path)
        monkeypatch.setattr(mod, "load_module_registry", lambda: {})
        saved = {}
        monkeypatch.setattr(mod, "save_module_registry", lambda modules: saved.update(modules))
        bus = MagicMock()
        bus.fire.side_effect = OSError("trigger bus unavailable")
        monkeypatch.setattr(mod, "_get_trigger", lambda: bus)

        new_file = tmp_path / "survivor.py"
        new_file.write_text("x = 1\n", encoding="utf-8")

        event = MagicMock()
        event.event_type = "created"
        event.is_directory = False
        event.src_path = str(new_file)
        mod.PythonFileWatcher().dispatch(event)  # must not raise

        assert "survivor" in saved, "a broken trigger cost the registry its entry"
        assert asked == [new_file], "the ignore filter was never consulted"

    def test_a_host_without_trigger_still_registers_the_module(self, tmp_path, monkeypatch):
        """`_get_trigger()` returning None is the normal answer on such a host."""
        mod = self._real_watcher_module()
        monkeypatch.setattr(mod, "ECOSYSTEM_ROOT", tmp_path)
        asked = []
        monkeypatch.setattr(mod, "should_ignore_path", lambda p: asked.append(p) or p.parent != tmp_path)
        monkeypatch.setattr(mod, "load_module_registry", lambda: {})
        saved = {}
        monkeypatch.setattr(mod, "save_module_registry", lambda modules: saved.update(modules))
        monkeypatch.setattr(mod, "_get_trigger", lambda: None)

        new_file = tmp_path / "lonely.py"
        new_file.write_text("x = 1\n", encoding="utf-8")

        event = MagicMock()
        event.event_type = "created"
        event.is_directory = False
        event.src_path = str(new_file)
        mod.PythonFileWatcher().dispatch(event)

        assert "lonely" in saved
        assert asked == [new_file], "the ignore filter was never consulted"


class TestWatcherLiveness:
    """A liveness check that cannot fire after startup is not a liveness check."""

    @pytest.fixture(autouse=True)
    def _keep_monkeypatch(self, monkeypatch):
        self._monkeypatch = monkeypatch

    def _fresh_module(self):
        """The discovery watcher bound at the top, with a liveness record never checked."""
        _fresh_watcher_state(self._monkeypatch)
        return discovery_watcher

    def _dead_observer(self):
        obs = MagicMock()
        obs.is_alive.return_value = False
        obs.event_queue.qsize.return_value = 91234
        return obs

    def _recording_bus(self, mod, monkeypatch):
        """Replace the fire binding, `_get_trigger`, with a recorder: no death reaches the real bus."""
        bus = MagicMock()
        monkeypatch.setattr(mod, "_get_trigger", lambda: bus)
        return bus

    def test_a_dead_watcher_is_reported_loudly(self, monkeypatch):
        """A dead watcher is logged at ERROR and fired as file_watcher_died."""
        mod = self._fresh_module()
        monkeypatch.setattr(mod, "_observer", self._dead_observer())
        errors = []
        monkeypatch.setattr(mod.logger, "error", lambda msg, *a, **kw: errors.append(str(msg)))
        bus = self._recording_bus(mod, monkeypatch)

        assert mod.check_file_watcher_liveness() is False
        assert errors, "the watcher died and nothing was logged — this is the 15-hour silence"
        assert "DEAD" in errors[0]
        bus.fire.assert_called_once_with("file_watcher_died", watch_root=str(mod.ECOSYSTEM_ROOT), queued_events=91234)

    def test_the_death_report_carries_the_queue_depth(self, monkeypatch):
        """The number that makes it actionable: how much memory is being retained."""
        mod = self._fresh_module()
        monkeypatch.setattr(mod, "_observer", self._dead_observer())
        errors = []
        monkeypatch.setattr(mod.logger, "error", lambda msg, *a, **kw: errors.append(str(msg)))
        bus = self._recording_bus(mod, monkeypatch)

        mod.check_file_watcher_liveness()
        assert "91234" in errors[0], "the report should say how many events are stranded"
        assert bus.fire.call_args.kwargs["queued_events"] == 91234

    def test_the_death_is_reported_once_not_on_every_check(self, monkeypatch):
        """prax owns the runaway-log detector; a health check must not flood."""
        mod = self._fresh_module()
        monkeypatch.setattr(mod, "_observer", self._dead_observer())
        errors = []
        monkeypatch.setattr(mod.logger, "error", lambda msg, *a, **kw: errors.append(str(msg)))
        bus = self._recording_bus(mod, monkeypatch)

        for _ in range(50):
            mod.check_file_watcher_liveness(force=True)

        assert len(errors) == 1, f"death reported {len(errors)} times — that is a log flood"
        assert bus.fire.call_count == 1, f"death fired {bus.fire.call_count} times on the bus"

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
        bus = self._recording_bus(mod, monkeypatch)

        mod.check_file_watcher_liveness(force=True)
        assert len(errors) == 1

        alive = MagicMock()
        alive.is_alive.return_value = True
        monkeypatch.setattr(mod, "_observer", alive)
        mod.check_file_watcher_liveness(force=True)  # recovery clears the latch

        monkeypatch.setattr(mod, "_observer", self._dead_observer())
        mod.check_file_watcher_liveness(force=True)
        assert len(errors) == 2, "a second, distinct death went unreported"
        assert [c.args[0] for c in bus.fire.call_args_list] == ["file_watcher_died", "file_watcher_died"]

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
        broken = MagicMock()
        broken.fire.side_effect = OSError("trigger bus unavailable")
        monkeypatch.setattr(mod, "_get_trigger", lambda: broken)

        mod.check_file_watcher_liveness(force=True)
        assert len(errors) == 1, "a broken trigger swallowed the death report"
        assert errors[0].startswith("[watcher] DISCOVERY WATCHER IS DEAD")

    def test_the_death_actually_reaches_the_bus(self, monkeypatch):
        """The death fire is reachable: a module-level trigger gate once kept it closed in every process."""
        mod = self._fresh_module()
        monkeypatch.setattr(mod, "_observer", self._dead_observer())
        bus = MagicMock()
        monkeypatch.setattr(mod, "_get_trigger", lambda: bus)

        mod.check_file_watcher_liveness(force=True)

        assert bus.fire.call_count == 1
        assert bus.fire.call_args[0][0] == "file_watcher_died"

    def test_a_trigger_that_cannot_be_imported_is_simply_skipped(self, monkeypatch):
        """No trigger on the host: the death report still goes out, nothing raises."""
        mod = self._fresh_module()
        monkeypatch.setattr(mod, "_observer", self._dead_observer())
        errors = []
        monkeypatch.setattr(mod.logger, "error", lambda msg, *a, **kw: errors.append(str(msg)))
        monkeypatch.setattr(mod, "_get_trigger", lambda: None)

        assert mod.check_file_watcher_liveness(force=True) is False
        assert errors, "no trigger meant no death report at all"

    def test_the_common_case_does_not_touch_the_lock(self, monkeypatch):
        """The hot path, run on every log call, stays lock-free: a throttle inside the lock changes cost, not answers."""
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
    """Run ``body`` in a fresh interpreter where importing trigger raises OSError (an import-time claim)."""
    script = _DENY_TRIGGER + body
    return subprocess.run(
        [sys.executable, "-"],
        input=script,
        text=True,
        encoding="utf-8",
        capture_output=True,
        cwd=str(Path(__file__).resolve().parents[3]),
    )


class TestOptionalTriggerIntegration:
    """`trigger` is declared optional. The fallback must be as wide as the failures, OSError included."""

    def test_the_denial_is_live(self):
        """Negative control: the denied world is actually hostile, or every pin below is vacuous."""
        result = _run_with_trigger_denied(
            "\n"
            "try:\n"
            "    import aipass.trigger.apps.modules.core  # noqa: F401\n"
            "except BaseException as exc:\n"
            "    print('DENIED', type(exc).__name__, isinstance(exc, OSError))\n"
            "else:\n"
            "    print('NOT DENIED')\n"
        )
        # errno 2 maps to FileNotFoundError, the OSError subclass trigger's guard really raised.
        assert "DENIED FileNotFoundError True" in result.stdout, (
            "the meta_path finder did not deny the trigger import, so every pin built "
            f"on this world is vacuous.\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_an_oserror_from_the_optional_import_falls_back(self):
        """An OSError from the optional import is caught at the fire site (None) and prax keeps running."""
        result = _run_with_trigger_denied(
            "\nfrom aipass.prax.apps.handlers.discovery import watcher\n"
            "print('IMPORTED OK')\n"
            "print('TRIGGER', watcher._get_trigger())\n"
        )
        assert result.returncode == 0, (
            "an OSError from the OPTIONAL trigger import killed prax's watcher import.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert "IMPORTED OK" in result.stdout
        assert "TRIGGER None" in result.stdout, (
            "the fire site did not fall back — an OSError escaped the guard.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_a_denied_trigger_does_not_stop_the_discovery_scan(self, tmp_path):
        """The behaviour the guard exists for: discovery completes without trigger, rooted at tmp_path."""
        result = _run_with_trigger_denied(
            "\nimport os\n"
            f"os.environ['AIPASS_TEST_LOG_DIR'] = {str(tmp_path / 'logs')!r}\n"
            "from aipass.prax.apps.handlers.discovery import watcher\n"
            "watcher.load_module_registry = lambda: {}\n"
            "watcher.save_module_registry = lambda modules, **kw: True\n"
            "from unittest.mock import MagicMock\n"
            "from pathlib import Path\n"
            f"watcher.ECOSYSTEM_ROOT = Path({str(tmp_path)!r})\n"
            "probe = Path(watcher.ECOSYSTEM_ROOT) / 'denied_trigger_probe.py'\n"
            "probe.parent.mkdir(parents=True, exist_ok=True)\n"
            "probe.write_text('# throwaway\\n', encoding='utf-8')\n"
            "ev = MagicMock(); ev.is_directory = False; ev.src_path = str(probe)\n"
            "try:\n"
            "    watcher.PythonFileWatcher().on_created(ev)\n"
            "    print('SCAN OK')\n"
            "finally:\n"
            "    probe.unlink(missing_ok=True)\n"
        )
        assert "SCAN OK" in result.stdout, (
            "a denied trigger import stopped the file-discovery path.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_the_public_logger_survives_it_too(self):
        """The chain that broke, pinned at the public door every branch uses: get_system_logger."""
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
