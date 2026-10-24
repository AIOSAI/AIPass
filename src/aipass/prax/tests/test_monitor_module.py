# =================== AIPass ====================
# Name: test_monitor_module.py
# Description: Tests for the unified monitoring module
# Version: 1.1.0
# Created: 2026-04-03
# Modified: 2026-10-24
# =============================================

"""Tests for apps/modules/monitor.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(through_the_command) — _report_render_failures, covered by tests/test_display_resilience.py
# seedgo: no-test-needed(through_the_command) — _standalone_run_args, covered by tests/test_display_resilience.py
# seedgo: no-test-needed(through_the_command) — _rate_tracker_worker's scan_rates, covered by tests/test_rate_tracker.py
# seedgo: no-test-needed(through_the_command) — the run -h screen, covered by tests/test_help_flag_safety.py
# seedgo: no-test-needed(json_structure) — _run_monitor's log_operation("monitor_started") record, covered by that row

import json
import sys
import threading
from contextlib import contextmanager
from unittest.mock import MagicMock, call, patch

import pytest

from aipass.prax.apps.handlers.cli.arg_gate import UnknownArgument
from aipass.prax.apps.handlers.config import load as config_load
from aipass.prax.apps.handlers.monitoring import filesystem_handler, interactive_filter, log_watcher
from aipass.prax.apps.handlers.monitoring.branch_scope import BranchScope
from aipass.prax.apps.modules import monitor


# Each collaborator is doubled where monitor binds it and its run state reset per test;
# the console is the real one, read with capsys.

_DOUBLED_COLLABORATORS = (
    "logger",
    "json_handler",
    "print_event",
    "print_command_separator",
    "print_hook_event",
    "MonitoringQueue",
    "MonitoringEvent",
    "instance_lock",
    "_get_pid_for_branch",
)

_RUN_STATE_NONE = (
    "_event_queue",
    "_display_thread",
    "_file_watcher_thread",
    "_log_watcher_thread",
    "_rate_tracker_thread",
    "_active_scope",
)


@pytest.fixture(autouse=True)
def _monitor_doubled(monkeypatch):
    for name in _DOUBLED_COLLABORATORS:
        monkeypatch.setattr(monitor, name, MagicMock())
    for name in _RUN_STATE_NONE:
        monkeypatch.setattr(monitor, name, None)
    monkeypatch.setattr(monitor, "_stop_event", threading.Event())
    monkeypatch.setattr(monitor, "_render_failures", 0)
    monkeypatch.setattr(monitor, "_last_render_warning", 0.0)


def _import_monitor():
    """The top-bound monitor; the autouse fixture above has doubled its edges."""
    return monitor


def _doubled(name: str) -> MagicMock:
    """The double the autouse fixture set on monitor under this name."""
    double = getattr(monitor, name)
    assert isinstance(double, MagicMock), f"monitor.{name} is not doubled"
    return double


# The names monitor imports inside its functions, per real module.
_LAZY_NAMES = {
    filesystem_handler: ("MonitoringFileHandler",),
    config_load: ("_find_repo_root", "get_system_logs_dir"),
    log_watcher: ("start_log_watcher", "stop_log_watcher"),
    interactive_filter: ("parse_command", "get_help_text"),
}


@contextmanager
def _lazy_from(*pairs):
    """Point every name monitor imports lazily from each real module at the double's attribute."""
    with pytest.MonkeyPatch.context() as mp:
        for module, double in pairs:
            for name in _LAZY_NAMES[module]:
                mp.setattr(module, name, getattr(double, name))
        yield


class TestHandleCommand:
    """Test the top-level command router."""

    def test_returns_false_for_non_monitor_command(self):
        """handle_command returns False for commands other than 'monitor'."""
        mod = _import_monitor()
        assert mod.handle_command("status", []) is False

    def test_no_args_calls_print_introspection(self):
        """Bare 'monitor' with no args shows introspection and returns True."""
        mod = _import_monitor()
        with patch.object(mod, "print_introspection") as mock_intro:
            result = mod.handle_command("monitor", [])
            assert result is True
            mock_intro.assert_called_once()

    def test_help_flag_calls_print_help(self):
        """--help flag shows help and returns True."""
        mod = _import_monitor()
        for flag in ("--help", "-h", "help"):
            with patch.object(mod, "print_help") as mock_help:
                result = mod.handle_command("monitor", [flag])
                assert result is True
                mock_help.assert_called_once()

    def test_run_subcommand_calls_run_monitor(self):
        """'run' subcommand delegates to _run_monitor."""
        mod = _import_monitor()
        with patch.object(mod, "_run_monitor", return_value=True) as mock_run:
            result = mod.handle_command("monitor", ["run"])
            assert result is True
            mock_run.assert_called_once_with([])

    def test_run_subcommand_passes_trailing_args(self):
        """Extra args after 'run' are forwarded to _run_monitor."""
        mod = _import_monitor()
        with patch.object(mod, "_run_monitor", return_value=True) as mock_run:
            mod.handle_command("monitor", ["run", "seedgo,cli"])
            mock_run.assert_called_once_with(["seedgo,cli"])

    def test_unknown_subcommand_prints_error_and_help(self):
        """Unknown subcommand is refused by name: returning True would read as success to the router."""
        mod = _import_monitor()

        with pytest.raises(UnknownArgument) as refusal:
            mod.handle_command("monitor", ["bogus"])

        assert refusal.value.verb == "monitor"
        assert refusal.value.token == "bogus"


_COMMONS_FEED_TARGET = "aipass.prax.apps.handlers.monitoring.commons_feed.run_commons_feed"


class TestDispatchRun:
    """'run commons' opens the live social feed; --logs and mixed lists stay branch tail."""

    def test_bare_commons_routes_to_feed(self):
        """A standalone 'commons' target opens the feed, not the branch monitor."""
        mod = _import_monitor()
        with (
            patch(_COMMONS_FEED_TARGET, return_value=True) as mock_feed,
            patch.object(mod, "_run_monitor") as mock_branch,
        ):
            result = mod.handle_command("monitor", ["run", "commons"])
            assert result is True
            mock_feed.assert_called_once_with([])
            mock_branch.assert_not_called()

    def test_commons_logs_escape_routes_to_branch_tail(self):
        """'commons --logs' is the escape hatch back to the old branch-log tail."""
        mod = _import_monitor()
        with (
            patch(_COMMONS_FEED_TARGET) as mock_feed,
            patch.object(mod, "_run_monitor", return_value=True) as mock_branch,
        ):
            result = mod.handle_command("monitor", ["run", "commons", "--logs"])
            assert result is True
            mock_branch.assert_called_once_with(["commons"])
            mock_feed.assert_not_called()

    def test_mixed_branch_list_with_commons_stays_branch_tail(self):
        """A mixed list (e.g. 'seedgo,commons') treats commons as a branch — feed is standalone-only."""
        mod = _import_monitor()
        with (
            patch(_COMMONS_FEED_TARGET) as mock_feed,
            patch.object(mod, "_run_monitor", return_value=True) as mock_branch,
        ):
            result = mod.handle_command("monitor", ["run", "seedgo,commons"])
            assert result is True
            mock_branch.assert_called_once_with(["seedgo,commons"])
            mock_feed.assert_not_called()

    @pytest.mark.parametrize("run_args", [["--relay"], ["commons", "--relay"], ["seedgo", "-x"]])
    def test_unknown_flag_is_refused_before_anything_starts(self, run_args):
        """A flag `run` does not define (the retired --relay included) exits 1, never starts a monitor."""
        mod = _import_monitor()
        with (
            patch(_COMMONS_FEED_TARGET) as mock_feed,
            patch.object(mod, "_run_monitor") as mock_branch,
            pytest.raises(mod.UnknownArgument) as exc,
        ):
            mod.handle_command("monitor", ["run", *run_args])
        assert exc.value.token == run_args[-1]
        mock_feed.assert_not_called()
        mock_branch.assert_not_called()


class TestGetWatchDirectories:
    """Test directory enumeration from registry."""

    def test_returns_empty_when_no_registry(self, tmp_path):
        """No AIPASS_REGISTRY.json -> empty list (no .claude/projects either)."""
        mod = _import_monitor()
        with patch("pathlib.Path.home", return_value=tmp_path / "fakehome"):
            result = mod._get_watch_directories(tmp_path)
        assert result == []

    def test_includes_apps_and_trinity_dirs(self, tmp_path):
        """Registry with a branch that has apps/ and .trinity/ dirs."""
        mod = _import_monitor()
        branch_dir = tmp_path / "src" / "aipass" / "flow"
        apps_dir = branch_dir / "apps"
        trinity_dir = branch_dir / ".trinity"
        apps_dir.mkdir(parents=True)
        trinity_dir.mkdir(parents=True)

        registry = {"branches": [{"name": "flow", "path": "src/aipass/flow"}]}
        registry_file = tmp_path / "AIPASS_REGISTRY.json"
        registry_file.write_text(json.dumps(registry), encoding="utf-8")

        with patch("pathlib.Path.home", return_value=tmp_path / "fakehome"):
            result = mod._get_watch_directories(tmp_path)

        paths = [p for p, _r in result]
        recursives = {str(p): r for p, r in result}

        assert apps_dir in paths, "apps/ directory should be included"
        assert branch_dir in paths, "branch root should be included"
        assert trinity_dir in paths, "trinity/ directory should be included"

        # apps/ is watched recursively, branch root and .trinity are not
        assert recursives[str(apps_dir)] is True
        assert recursives[str(branch_dir)] is False
        assert recursives[str(trinity_dir)] is False

    def test_skips_nonexistent_branch_paths(self, tmp_path):
        """Branches whose path doesn't exist on disk are skipped."""
        mod = _import_monitor()
        registry = {"branches": [{"name": "ghost", "path": "src/aipass/ghost"}]}
        registry_file = tmp_path / "AIPASS_REGISTRY.json"
        registry_file.write_text(json.dumps(registry), encoding="utf-8")

        with patch("pathlib.Path.home", return_value=tmp_path / "fakehome"):
            result = mod._get_watch_directories(tmp_path)

        assert result == []

    def test_includes_claude_projects_when_exists(self, tmp_path):
        """~/.claude/projects is included when it exists."""
        mod = _import_monitor()
        fakehome = tmp_path / "fakehome"
        claude_projects = fakehome / ".claude" / "projects"
        claude_projects.mkdir(parents=True)

        with patch("pathlib.Path.home", return_value=fakehome):
            result = mod._get_watch_directories(tmp_path)

        paths = [p for p, _r in result]
        assert claude_projects in paths
        recursives = {str(p): r for p, r in result}
        assert recursives[str(claude_projects)] is True

    def test_branch_without_apps_dir(self, tmp_path):
        """Branch that exists but has no apps/ dir still includes root and .trinity."""
        mod = _import_monitor()
        branch_dir = tmp_path / "src" / "aipass" / "minimal"
        trinity_dir = branch_dir / ".trinity"
        branch_dir.mkdir(parents=True)
        trinity_dir.mkdir(parents=True)

        registry = {"branches": [{"name": "minimal", "path": "src/aipass/minimal"}]}
        registry_file = tmp_path / "AIPASS_REGISTRY.json"
        registry_file.write_text(json.dumps(registry), encoding="utf-8")

        with patch("pathlib.Path.home", return_value=tmp_path / "fakehome"):
            result = mod._get_watch_directories(tmp_path)

        paths = [p for p, _r in result]
        assert (branch_dir / "apps") not in paths
        assert branch_dir in paths
        assert trinity_dir in paths


class TestPrintIntrospection:
    """Test print_introspection output."""

    def test_print_introspection_runs(self, capsys):
        """print_introspection logs its call and prints the module's self-map."""
        mod = _import_monitor()
        with patch.object(mod, "json_handler") as recorder:
            mod.print_introspection()
        recorder.log_operation.assert_called_once_with("print_introspection", {"module": "monitor"})
        lines = capsys.readouterr().out.splitlines()
        assert "PRAX Monitor Module" in lines
        assert len(lines) > 10


class TestPrintHelp:
    """Test print_help output."""

    def test_print_help_runs(self, capsys):
        """print_help prints the help screen."""
        mod = _import_monitor()
        mod.print_help()
        lines = capsys.readouterr().out.splitlines()
        assert "PRAX Monitor - Unified Branch Monitoring" in lines
        assert len(lines) > 10


class TestRenderEvent:
    """Test event rendering to console."""

    @pytest.mark.parametrize(
        ("action", "expected_target"),
        [("audit:flow", "flow"), ("audit_only", None)],
    )
    def test_render_command_event_target_parsed_from_action(self, action, expected_target):
        """A command event reaches print_command_separator with the target parsed out of its action."""
        mod = _import_monitor()
        event = MagicMock()
        event.event_type = "command"
        event.branch = "FLOW"
        event.message = "seedgo audit"
        event.caller = "prax"
        event.action = action

        with patch.object(mod, "_get_pid_for_branch", return_value=None):
            mod._print_event_to_console(event)

        _doubled("print_command_separator").assert_called_once_with("FLOW", "seedgo audit", "prax", expected_target)

    def test_render_non_command_event(self):
        """Non-command events call print_event."""
        mod = _import_monitor()
        event = MagicMock()
        event.event_type = "file_change"
        event.branch = "FLOW"
        event.message = "STATUS.local.md modified"
        event.level = "info"

        with patch.object(mod, "_get_pid_for_branch", return_value=42):
            mod._print_event_to_console(event)
        _doubled("print_event").assert_called_once_with(
            "file_change", "FLOW", "STATUS.local.md modified", "info", pid=42
        )

    def test_render_command_event_action_with_empty_target(self):
        """Command event with action 'audit:' (empty after colon) passes target=None."""
        mod = _import_monitor()
        event = MagicMock()
        event.event_type = "command"
        event.branch = "FLOW"
        event.message = "test"
        event.caller = "prax"
        event.action = "audit:"

        with patch.object(mod, "_get_pid_for_branch", return_value=None):
            mod._print_event_to_console(event)
        call_args = _doubled("print_command_separator").call_args
        assert call_args[0][3] is None


class TestThreadManagement:
    """Test thread start and stop functions."""

    @pytest.mark.parametrize(("holds_lock", "threads"), [(True, 4), (False, 3)])
    def test_rate_tracker_starts_only_in_the_lock_holder(self, holds_lock, threads):
        """Display, file and log watchers always start; the rate tracker only where the instance lock is held."""
        mod = _import_monitor()
        _doubled("instance_lock").try_acquire.return_value = holds_lock
        mock_thread = MagicMock()
        with patch("threading.Thread", return_value=mock_thread) as mock_cls:
            mod._start_threads()
        assert mock_cls.call_count == threads
        assert mock_thread.start.call_count == threads

    def test_stop_threads_sets_stop_event(self, monkeypatch):
        """_stop_threads sets the stop event and stops the queue."""
        mod = _import_monitor()
        mock_queue = MagicMock()
        monkeypatch.setattr(mod, "_event_queue", mock_queue)
        mod._stop_event.clear()

        mock_thread = MagicMock()
        mock_thread.is_alive.return_value = True
        monkeypatch.setattr(mod, "_display_thread", mock_thread)
        monkeypatch.setattr(mod, "_file_watcher_thread", mock_thread)
        monkeypatch.setattr(mod, "_log_watcher_thread", mock_thread)

        mod._stop_threads()

        assert mod._stop_event.is_set()
        mock_queue.stop.assert_called_once()
        assert mock_thread.join.call_count == 3

    def test_stop_threads_handles_none_queue(self, monkeypatch):
        """_stop_threads works when event queue is None."""
        mod = _import_monitor()
        monkeypatch.setattr(mod, "_event_queue", None)
        monkeypatch.setattr(mod, "_display_thread", None)
        monkeypatch.setattr(mod, "_file_watcher_thread", None)
        monkeypatch.setattr(mod, "_log_watcher_thread", None)

        mod._stop_threads()
        assert mod._stop_event.is_set()

    def test_stop_threads_skips_dead_threads(self, monkeypatch):
        """_stop_threads skips threads that are not alive."""
        mod = _import_monitor()
        monkeypatch.setattr(mod, "_event_queue", None)

        mock_thread = MagicMock()
        mock_thread.is_alive.return_value = False
        monkeypatch.setattr(mod, "_display_thread", mock_thread)
        monkeypatch.setattr(mod, "_file_watcher_thread", mock_thread)
        monkeypatch.setattr(mod, "_log_watcher_thread", mock_thread)

        mod._stop_threads()
        mock_thread.join.assert_not_called()


class TestDisplayWorker:
    """Test the display worker loop."""

    def test_display_worker_processes_event(self, monkeypatch):
        """Display worker dequeues and renders events."""
        mod = _import_monitor()
        mock_event = MagicMock()
        mock_event.event_type = "log"
        mock_event.branch = "FLOW"
        mock_event.message = "test"
        mock_event.level = "info"

        mock_queue = MagicMock()
        call_count = 0

        def _dequeue(timeout=0.1):
            """Return mock event once, then signal stop."""
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mock_event
            mod._stop_event.set()
            return None

        mock_queue.dequeue = _dequeue
        monkeypatch.setattr(mod, "_event_queue", mock_queue)
        mod._stop_event.clear()

        with patch.object(mod, "_print_event_to_console") as mock_render:
            mod._display_worker()
        mock_render.assert_called_once_with(mock_event)

    def test_display_worker_handles_none_queue(self, monkeypatch):
        """Display worker sleeps when event queue is None, then stops."""
        mod = _import_monitor()
        monkeypatch.setattr(mod, "_event_queue", None)
        mod._stop_event.clear()

        call_count = 0

        def _sleep(duration):
            """Count calls and set stop event after threshold."""
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                mod._stop_event.set()

        with patch("time.sleep", side_effect=_sleep):
            mod._display_worker()
        assert call_count >= 2


class TestEmitWatcherEvent:
    """Test watcher event emission."""

    def test_emit_returns_early_when_no_queue(self, monkeypatch):
        """No queue means no event is ever built — the early return is visible, not silent."""
        mod = _import_monitor()
        monkeypatch.setattr(mod, "_event_queue", None)

        assert mod._emit_watcher_event("error", "test error") is None

        # The consequence of the early return: the event was never constructed,
        # so nothing was handed to a queue that does not exist.
        _doubled("MonitoringEvent").assert_not_called()

    def test_emit_error_level_has_priority_1(self, monkeypatch):
        """Error level events get priority 1."""
        mod = _import_monitor()
        mock_queue = MagicMock()
        monkeypatch.setattr(mod, "_event_queue", mock_queue)

        mod._emit_watcher_event("error", "bad stuff happened")
        mock_queue.enqueue.assert_called_once()
        me_cls = _doubled("MonitoringEvent")
        me_cls.assert_called_once()
        call_kwargs = me_cls.call_args[1]
        assert call_kwargs["priority"] == 1

    def test_emit_warning_level_has_priority_2(self, monkeypatch):
        """Non-error level events get priority 2."""
        mod = _import_monitor()
        mock_queue = MagicMock()
        monkeypatch.setattr(mod, "_event_queue", mock_queue)

        mod._emit_watcher_event("warning", "something happened")
        mock_queue.enqueue.assert_called_once()
        me_cls = _doubled("MonitoringEvent")
        me_cls.assert_called_once()
        call_kwargs = me_cls.call_args[1]
        assert call_kwargs["priority"] == 2


class TestInotifyFixMessage:
    """Test inotify error message generation."""

    def test_enospc_message(self):
        """ENOSPC error returns max_user_watches fix message."""
        mod = _import_monitor()
        import errno

        err = OSError(errno.ENOSPC, "No space left on device")
        result = mod._inotify_fix_message(err)
        assert "max_user_watches" in result

    def test_emfile_message(self):
        """EMFILE error returns max_user_instances fix message."""
        mod = _import_monitor()
        import errno

        err = OSError(errno.EMFILE, "Too many open files")
        result = mod._inotify_fix_message(err)
        assert "max_user_instances" in result

    def test_other_error_message(self):
        """Other errors return generic inotify error message."""
        mod = _import_monitor()
        err = OSError(99, "Unknown error")
        result = mod._inotify_fix_message(err)
        assert "inotify error" in result


class TestStartObserverWithFallback:
    """Test watchdog observer startup with fallback."""

    def _import_with_watchdog(self):
        """The top-bound monitor: it imports watchdog nowhere at module level."""
        return monitor

    def test_success_path(self, tmp_path):
        """Observer starts successfully on first try."""
        mod = self._import_with_watchdog()
        handler = MagicMock()
        watch_dirs = [(tmp_path, True)]

        mock_observer = MagicMock()
        with patch.dict(
            sys.modules,
            {"watchdog.observers": MagicMock(Observer=MagicMock(return_value=mock_observer))},
        ):
            result = mod._start_observer_with_fallback(handler, watch_dirs)
        assert result is mock_observer
        mock_observer.start.assert_called_once()

    def test_fallback_to_polling(self, tmp_path, monkeypatch):
        """Falls back to PollingObserver when inotify fails."""
        mod = self._import_with_watchdog()
        handler = MagicMock()
        watch_dirs = [(tmp_path, True)]
        monkeypatch.setattr(mod, "_event_queue", MagicMock())

        import errno

        mock_observer_fail = MagicMock()
        mock_observer_fail.start.side_effect = OSError(errno.ENOSPC, "inotify limit")
        mock_polling_observer = MagicMock()

        mock_observer_mod = MagicMock()
        mock_observer_mod.Observer = MagicMock(return_value=mock_observer_fail)

        mock_polling_mod = MagicMock()
        mock_polling_mod.PollingObserver = MagicMock(return_value=mock_polling_observer)

        with patch.dict(
            sys.modules,
            {
                "watchdog.observers": mock_observer_mod,
                "watchdog.observers.polling": mock_polling_mod,
            },
        ):
            result = mod._start_observer_with_fallback(handler, watch_dirs)

        assert result is mock_polling_observer
        mock_polling_observer.start.assert_called_once()

    def test_both_fail_returns_none(self, tmp_path, monkeypatch):
        """Returns None when both inotify and polling fail."""
        mod = self._import_with_watchdog()
        handler = MagicMock()
        watch_dirs = [(tmp_path, True)]
        monkeypatch.setattr(mod, "_event_queue", MagicMock())

        import errno

        mock_observer_fail = MagicMock()
        mock_observer_fail.start.side_effect = OSError(errno.ENOSPC, "inotify limit")

        mock_observer_mod = MagicMock()
        mock_observer_mod.Observer = MagicMock(return_value=mock_observer_fail)

        mock_polling_mod = MagicMock()
        mock_polling_mod.PollingObserver = MagicMock(side_effect=RuntimeError("polling failed"))

        with patch.dict(
            sys.modules,
            {
                "watchdog.observers": mock_observer_mod,
                "watchdog.observers.polling": mock_polling_mod,
            },
        ):
            result = mod._start_observer_with_fallback(handler, watch_dirs)

        assert result is None


class TestFileWatcherWorker:
    """Test file watcher worker thread."""

    def test_no_watch_dirs_returns_early(self, monkeypatch):
        """Worker returns early when no watch directories found."""
        mod = _import_monitor()
        monkeypatch.setattr(mod, "_event_queue", MagicMock())

        mock_config = MagicMock()
        mock_config._find_repo_root.return_value = MagicMock()
        mock_fs_handler = MagicMock()

        with (
            _lazy_from((filesystem_handler, mock_fs_handler), (config_load, mock_config)),
            patch.object(mod, "_get_watch_directories", return_value=[]),
            patch.object(mod, "_emit_watcher_event") as mock_emit,
        ):
            mod._file_watcher_worker()
        mock_emit.assert_called_once_with("warning", "File watcher: no watch directories found — file events disabled")
        # The handler is sandboxed to the repo root the worker resolved.
        built = mock_fs_handler.MonitoringFileHandler.call_args.kwargs
        assert built["sandbox_root"] is mock_config._find_repo_root.return_value
        assert built["event_queue"] is mod._event_queue

    def test_observer_none_returns_early(self, monkeypatch):
        """A failed observer startup ends the worker before the watch loop is ever entered."""
        mod = _import_monitor()
        monkeypatch.setattr(mod, "_event_queue", MagicMock())

        mock_config = MagicMock()
        mock_config._find_repo_root.return_value = MagicMock()
        mock_fs_handler = MagicMock()

        with (
            _lazy_from((filesystem_handler, mock_fs_handler), (config_load, mock_config)),
            patch.object(mod, "_get_watch_directories", return_value=[("fakedir", True)]),
            patch.object(mod, "_start_observer_with_fallback", return_value=None) as mock_start,
            patch.object(mod, "_emit_watcher_event") as mock_emit,
            patch("time.sleep") as mock_sleep,
        ):
            assert mod._file_watcher_worker() is None

        # It got as far as trying to start, then stopped: no watch loop ran, and
        # the "no directories" warning belongs to the other early return, not this one.
        mock_start.assert_called_once()
        mock_sleep.assert_not_called()
        mock_emit.assert_not_called()

    def test_worker_runs_loop_and_stops_observer(self, tmp_path, monkeypatch):
        """Worker runs sleep loop and stops observer on stop_event."""
        mod = _import_monitor()
        monkeypatch.setattr(mod, "_event_queue", MagicMock())
        mod._stop_event.clear()

        mock_config = MagicMock()
        mock_config._find_repo_root.return_value = tmp_path
        mock_fs_handler = MagicMock()
        mock_observer = MagicMock()

        call_count = 0

        def _sleep(duration):
            """Count calls and set stop event."""
            nonlocal call_count
            call_count += 1
            if call_count >= 1:
                mod._stop_event.set()

        with (
            _lazy_from((filesystem_handler, mock_fs_handler), (config_load, mock_config)),
            patch.object(
                mod,
                "_get_watch_directories",
                return_value=[(tmp_path, True)],
            ),
            patch.object(
                mod,
                "_start_observer_with_fallback",
                return_value=mock_observer,
            ),
            patch("time.sleep", side_effect=_sleep),
        ):
            mod._file_watcher_worker()

        # stop() and join() take nothing here: the claim is each ran once, with no timeout handed on.
        mock_observer.stop.assert_called_once_with()
        mock_observer.join.assert_called_once_with()


class TestStartLogWatcherWithFallback:
    """Test log watcher startup with fallback."""

    def test_success_on_first_try(self):
        """Returns True when start_log_watcher succeeds."""
        mod = _import_monitor()
        mock_queue = MagicMock()

        mock_lw = MagicMock()
        mock_lw.start_log_watcher = MagicMock()

        with _lazy_from((log_watcher, mock_lw)):
            result = mod._start_log_watcher_with_fallback(mock_queue)
        assert result is True
        mock_lw.start_log_watcher.assert_called_once_with(mock_queue)

    def test_fallback_to_polling(self, monkeypatch):
        """Falls back to polling when inotify fails."""
        mod = _import_monitor()
        mock_queue = MagicMock()
        monkeypatch.setattr(mod, "_event_queue", MagicMock())

        import errno

        mock_lw = MagicMock()
        call_count = 0
        starts: list[tuple] = []

        def _start(eq, use_polling=False):
            """Fail on first call, succeed on second."""
            nonlocal call_count
            call_count += 1
            starts.append((eq, use_polling))
            if call_count == 1:
                raise OSError(errno.ENOSPC, "inotify limit")

        mock_lw.start_log_watcher = _start

        with _lazy_from((log_watcher, mock_lw)):
            result = mod._start_log_watcher_with_fallback(mock_queue)
        assert result is True
        assert starts == [(mock_queue, False), (mock_queue, True)]

    def test_both_fail_returns_false(self, monkeypatch):
        """Returns False when both inotify and polling fail."""
        mod = _import_monitor()
        mock_queue = MagicMock()
        monkeypatch.setattr(mod, "_event_queue", MagicMock())

        import errno

        mock_lw = MagicMock()
        call_count = 0

        def _start(eq, use_polling=False):
            """Fail on first call with OSError, fail on second with RuntimeError."""
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise OSError(errno.ENOSPC, "inotify limit")
            raise RuntimeError("polling also failed")

        mock_lw.start_log_watcher = _start

        with _lazy_from((log_watcher, mock_lw)):
            result = mod._start_log_watcher_with_fallback(mock_queue)
        assert result is False


class TestLogWatcherWorker:
    """Test log watcher worker thread."""

    def test_returns_early_when_no_queue(self, monkeypatch):
        """Worker returns early when event queue is None."""
        mod = _import_monitor()
        monkeypatch.setattr(mod, "_event_queue", None)

        mock_lw = MagicMock()
        with _lazy_from((log_watcher, mock_lw)):
            mod._log_watcher_worker()
        mock_lw.start_log_watcher.assert_not_called()

    def test_returns_early_on_watcher_failure(self, monkeypatch):
        """A refused startup returns before the try/finally, so nothing is torn down."""
        mod = _import_monitor()
        queue = MagicMock()
        monkeypatch.setattr(mod, "_event_queue", queue)

        with patch.object(mod, "_start_log_watcher_with_fallback", return_value=False) as mock_start:
            mock_lw = MagicMock()
            with (
                _lazy_from((log_watcher, mock_lw)),
                patch("time.sleep") as mock_sleep,
            ):
                assert mod._log_watcher_worker() is None

        mock_start.assert_called_once_with(queue)
        # The sibling test proves a successful start reaches stop_log_watcher via
        # `finally`. Returning before the `try` means that teardown never runs.
        mock_lw.stop_log_watcher.assert_not_called()
        mock_sleep.assert_not_called()

    def test_worker_runs_loop_and_stops(self, monkeypatch):
        """Worker runs sleep loop and calls stop_log_watcher on stop_event."""
        mod = _import_monitor()
        monkeypatch.setattr(mod, "_event_queue", MagicMock())
        mod._stop_event.clear()

        mock_lw = MagicMock()
        call_count = 0

        def _sleep(duration):
            """Count calls and set stop event."""
            nonlocal call_count
            call_count += 1
            if call_count >= 1:
                mod._stop_event.set()

        with (
            patch.object(mod, "_start_log_watcher_with_fallback", return_value=True),
            _lazy_from((log_watcher, mock_lw)),
            patch("time.sleep", side_effect=_sleep),
        ):
            mod._log_watcher_worker()
        mock_lw.stop_log_watcher.assert_called_once_with()


class TestHandleInteractiveCmd:
    """Test interactive command dispatch."""

    def test_help_command(self, capsys):
        """Help command calls get_help_text and prints it."""
        mod = _import_monitor()
        mock_help = MagicMock(return_value="help text here")
        mod._handle_interactive_cmd("help", mock_help)
        mock_help.assert_called_once_with()
        assert capsys.readouterr().out == "help text here\n"

    def test_status_command(self):
        """Status command calls _print_status."""
        mod = _import_monitor()
        with patch.object(mod, "_print_status") as mock_status:
            mod._handle_interactive_cmd("status", MagicMock())
        mock_status.assert_called_once_with()

    def test_unknown_command(self):
        """Unknown command prints error."""
        mod = _import_monitor()
        with patch.object(mod, "error") as recorder:
            mod._handle_interactive_cmd("bogus", MagicMock())
        recorder.assert_called_once_with("Unknown command: bogus")


class TestInteractiveLoop:
    """Test interactive command loop."""

    def test_non_tty_passive_mode(self, capsys):
        """Without a TTY the loop says so, sleeps in half-seconds, and leaves quietly."""
        mod = _import_monitor()
        mod._stop_event.clear()

        call_count = 0

        def _sleep(duration):
            """Count calls and set stop event after threshold."""
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                mod._stop_event.set()

        with (
            patch.object(sys.stdin, "isatty", return_value=False),
            patch("time.sleep", side_effect=_sleep) as mock_sleep,
        ):
            assert mod._interactive_loop() is None

        _doubled("logger").info.assert_called_once_with("[monitor] No TTY detected - passive mode (Ctrl+C to stop)")
        assert call_count == 2, "the loop must re-check the stop event, not sleep once and leave"
        assert mock_sleep.call_args_list == [call(0.5), call(0.5)]
        # A clean stop-event exit is not an interruption: nothing is printed.
        assert capsys.readouterr().out == ""

    def test_non_tty_keyboard_interrupt(self, capsys):
        """Ctrl+C in passive mode prints the stopping banner and returns without setting the stop event."""
        mod = _import_monitor()
        mod._stop_event.clear()

        with (
            patch.object(sys.stdin, "isatty", return_value=False),
            patch("time.sleep", side_effect=KeyboardInterrupt),
        ):
            assert mod._interactive_loop() is None

        assert capsys.readouterr().out == "\nStopping monitoring...\n"
        _doubled("logger").info.assert_any_call("[monitor] Stopped by user (passive mode)")
        # _run_monitor's own finally owns the stop event; the loop only leaves.
        assert mod._stop_event.is_set() is False

    @pytest.mark.parametrize("alias", ["quit", "exit", "q"])
    def test_tty_quit_command(self, alias, capsys):
        """Every exit alias breaks the TTY loop on its first turn and says so on the console."""
        mod = _import_monitor()
        mod._stop_event.clear()

        mock_filter = MagicMock()
        mock_filter.parse_command = MagicMock(return_value=(alias, []))
        mock_filter.get_help_text = MagicMock(return_value="help")

        with (
            patch.object(sys.stdin, "isatty", return_value=True),
            # An alias that stopped breaking the loop would read a second line;
            # the EOFError makes that a red instead of a hang.
            patch("builtins.input", side_effect=[alias, EOFError()]) as mock_input,
            patch.object(mod, "_handle_interactive_cmd") as mock_handle,
            _lazy_from((interactive_filter, mock_filter)),
        ):
            mod._interactive_loop()

        mock_input.assert_called_once()
        mock_filter.parse_command.assert_called_once_with(alias)
        mock_handle.assert_not_called()
        assert capsys.readouterr().out == "Stopping monitoring...\n"

    def test_tty_keyboard_interrupt(self, capsys):
        """Ctrl+C at the prompt breaks the loop after one read and says so on the console."""
        mod = _import_monitor()
        mod._stop_event.clear()

        mock_filter = MagicMock()

        with (
            patch.object(sys.stdin, "isatty", return_value=True),
            patch("builtins.input", side_effect=KeyboardInterrupt) as mock_input,
            _lazy_from((interactive_filter, mock_filter)),
        ):
            assert mod._interactive_loop() is None

        mock_input.assert_called_once()
        # The interrupt beat the parser to it, so no line was ever dispatched.
        mock_filter.parse_command.assert_not_called()
        assert capsys.readouterr().out == "\nStopping monitoring...\n"
        _doubled("logger").info.assert_called_once_with("[monitor] Stopped by user")
        assert mod._stop_event.is_set() is False

    def test_tty_eof_error(self, capsys):
        """A closed stdin ends the loop silently — logged, but nothing printed at the user."""
        mod = _import_monitor()
        mod._stop_event.clear()

        mock_filter = MagicMock()

        with (
            patch.object(sys.stdin, "isatty", return_value=True),
            patch("builtins.input", side_effect=EOFError) as mock_input,
            _lazy_from((interactive_filter, mock_filter)),
        ):
            assert mod._interactive_loop() is None

        mock_input.assert_called_once()
        _doubled("logger").info.assert_called_once_with("[monitor] EOF received, stopping interactive loop")
        # Unlike Ctrl+C, EOF is not announced: a piped-in stdin ending is not news.
        assert capsys.readouterr().out == ""
        assert mod._stop_event.is_set() is False

    def test_tty_dispatches_interactive_cmd(self):
        """TTY mode dispatches non-quit commands to _handle_interactive_cmd."""
        mod = _import_monitor()
        mod._stop_event.clear()

        call_count = 0

        def _input(prompt=""):
            """Return status first, then quit."""
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return "status"
            return "quit"

        mock_filter = MagicMock()
        returns = iter([("status", []), ("quit", [])])
        mock_filter.parse_command = MagicMock(side_effect=lambda x: next(returns))
        mock_filter.get_help_text = MagicMock(return_value="help text")

        with (
            patch.object(sys.stdin, "isatty", return_value=True),
            patch("builtins.input", side_effect=_input),
            _lazy_from((interactive_filter, mock_filter)),
            patch.object(mod, "_handle_interactive_cmd") as mock_handler,
        ):
            mod._interactive_loop()
        mock_handler.assert_called_once_with("status", mock_filter.get_help_text)


class TestPrintStatusMonitor:
    """Test status display function."""

    def test_print_status_with_queue(self, monkeypatch, capsys):
        """Status display includes queue size when queue exists."""
        mod = _import_monitor()
        mock_queue = MagicMock()
        mock_queue.size.return_value = 5
        monkeypatch.setattr(mod, "_event_queue", mock_queue)

        mod._print_status()
        assert "  Queue size: 5" in capsys.readouterr().out.splitlines()

    def test_print_status_without_queue(self, monkeypatch, capsys):
        """Status display works when event queue is None."""
        mod = _import_monitor()
        monkeypatch.setattr(mod, "_event_queue", None)
        mod._print_status()
        lines = capsys.readouterr().out.splitlines()
        assert "Monitoring Status:" in lines
        assert not any(line.startswith("  Queue size:") for line in lines)


class TestRunMonitor:
    """Test the _run_monitor orchestration function."""

    def test_run_monitor_normal_exit(self):
        """_run_monitor starts threads, runs interactive loop, stops threads, then exits."""
        mod = _import_monitor()
        import pytest

        with (
            patch.object(mod, "_start_threads"),
            patch.object(mod, "_interactive_loop"),
            patch.object(mod, "_stop_threads"),
            patch.object(sys.stdin, "isatty", return_value=True),
            pytest.raises(SystemExit) as exc_info,
        ):
            mod._run_monitor(["all"])
        assert exc_info.value.code == 0

    def test_run_monitor_keyboard_interrupt(self):
        """_run_monitor handles KeyboardInterrupt from interactive loop."""
        mod = _import_monitor()
        import pytest

        with (
            patch.object(mod, "_start_threads"),
            patch.object(mod, "_interactive_loop", side_effect=KeyboardInterrupt),
            patch.object(mod, "_stop_threads"),
            patch.object(sys.stdin, "isatty", return_value=True),
            pytest.raises(SystemExit) as exc_info,
        ):
            mod._run_monitor([])
        assert exc_info.value.code == 0

    def test_run_monitor_non_tty(self):
        """_run_monitor displays non-TTY message when no TTY detected."""
        mod = _import_monitor()
        import pytest

        with (
            patch.object(mod, "_start_threads"),
            patch.object(mod, "_interactive_loop"),
            patch.object(mod, "_stop_threads"),
            patch.object(sys.stdin, "isatty", return_value=False),
            pytest.raises(SystemExit),
        ):
            mod._run_monitor([])


class TestGetWatchDirectoriesEdgeCases:
    """Test edge cases in _get_watch_directories."""

    def test_corrupted_registry_json(self, tmp_path):
        """A registry that will not parse contributes no watches, and the log names the reason."""
        mod = _import_monitor()
        registry_file = tmp_path / "AIPASS_REGISTRY.json"
        registry_file.write_text("{bad json!!}", encoding="utf-8")

        with patch("pathlib.Path.home", return_value=tmp_path / "fakehome"):
            result = mod._get_watch_directories(tmp_path)

        assert isinstance(result, list)
        assert result == []
        _doubled("logger").warning.assert_called_once()
        assert "Could not read the branch registry (JSONDecodeError)" in _doubled("logger").warning.call_args.args[0]

    def test_includes_codex_sessions(self, tmp_path):
        """~/.codex/sessions is included when it exists."""
        mod = _import_monitor()
        fakehome = tmp_path / "fakehome"
        codex_sessions = fakehome / ".codex" / "sessions"
        codex_sessions.mkdir(parents=True)

        with patch("pathlib.Path.home", return_value=fakehome):
            result = mod._get_watch_directories(tmp_path)

        paths = [p for p, _r in result]
        assert codex_sessions in paths


def _run_scoped(mod, args):
    """Run _run_monitor with threads/loop stubbed; returns the mocked queue instance."""
    import pytest

    with (
        patch.object(mod, "_start_threads"),
        patch.object(mod, "_interactive_loop"),
        patch.object(mod, "_stop_threads"),
        patch.object(sys.stdin, "isatty", return_value=True),
        pytest.raises(SystemExit),
    ):
        mod._run_monitor(args)
    return mod.MonitoringQueue.return_value


def _installed_scope_is_unscoped(queue):
    """True when nothing was installed, or what was installed filters nothing."""
    if not queue.set_scope.called:
        return True
    scope = queue.set_scope.call_args.args[0]
    return scope is None or scope.is_scoped is False


def _printed(capsys) -> list[str]:
    """Every line the real console printed during the call, read with capsys (prax, leg 11)."""
    return capsys.readouterr().out.splitlines()


class TestBranchScopeWiring:
    """The branch list reaches the queue instead of being logged and dropped."""

    def test_scope_installed_on_queue(self):
        """`run seedgo,cli` sets a scope naming exactly those branches."""
        mod = _import_monitor()
        queue = _run_scoped(mod, ["seedgo,cli"])
        queue.set_scope.assert_called_once()
        scope = queue.set_scope.call_args.args[0]
        assert scope.names == ("SEEDGO", "CLI")

    def test_bare_run_installs_no_scope(self):
        """All-branches monitoring must not gain a filter."""
        mod = _import_monitor()
        queue = _run_scoped(mod, [])
        assert _installed_scope_is_unscoped(queue)

    def test_all_keyword_installs_no_scope(self):
        mod = _import_monitor()
        queue = _run_scoped(mod, ["all"])
        assert _installed_scope_is_unscoped(queue)


class TestBannerTruth:
    """The banner may never claim 'all branches, no filters' while scoped."""

    def test_unscoped_banner_unchanged(self, capsys):
        mod = _import_monitor()
        _run_scoped(mod, [])
        assert any("all branches, all levels, no filters" in line for line in _printed(capsys))

    def test_scoped_banner_names_the_scope(self, capsys):
        mod = _import_monitor()
        _run_scoped(mod, ["devpulse,seedgo"])
        assert any("DEVPULSE, SEEDGO" in line for line in _printed(capsys))

    def test_scoped_banner_drops_the_all_branches_claim(self, capsys):
        mod = _import_monitor()
        _run_scoped(mod, ["devpulse"])
        lines = _printed(capsys)
        # The floor: a banner that printed nothing would pass the loop below in silence.
        assert len(lines) >= 1, "the scoped run printed no banner at all - the loop below proves nothing"
        assert any("DEVPULSE" in line for line in lines), "the scope must still be named somewhere"
        for line in lines:
            assert "all branches" not in line, f"scoped run still claims all branches: {line}"
            assert "no filters" not in line, f"scoped run still claims no filters: {line}"

    def test_status_unscoped_unchanged(self, monkeypatch, capsys):
        mod = _import_monitor()
        monkeypatch.setattr(mod, "_event_queue", None)
        monkeypatch.setattr(mod, "_active_scope", None)
        mod._print_status()
        assert any("all branches, all levels, no filters" in line for line in _printed(capsys))

    def test_status_names_the_scope(self, monkeypatch, capsys):
        """`status` inside a scoped monitor reports the scope, not 'no filters'."""
        mod = _import_monitor()
        queue = MagicMock()
        queue.size.return_value = 2
        queue.suppressed_count.return_value = 41
        monkeypatch.setattr(mod, "_event_queue", queue)
        monkeypatch.setattr(mod, "_active_scope", BranchScope(["SEEDGO"]))

        mod._print_status()
        lines = _printed(capsys)
        assert any("SEEDGO" in line for line in lines)
        assert not any("no filters" in line for line in lines)
        assert any("41" in line for line in lines), "hidden-event count explains a quiet screen"


class TestUnknownScopeWarning:
    """A typo'd branch would otherwise be an empty screen with no explanation."""

    def test_unknown_branch_warns(self, capsys):
        mod = _import_monitor()
        with patch.object(mod, "_known_branch_names", return_value={"SEEDGO", "PRAX"}):
            _run_scoped(mod, ["seedgoo"])
        assert any("seedgoo" in line.lower() for line in _printed(capsys))

    def test_known_branch_does_not_warn(self, capsys):
        mod = _import_monitor()
        with patch.object(mod, "_known_branch_names", return_value={"SEEDGO", "PRAX"}):
            _run_scoped(mod, ["seedgo"])
        assert not any("not a known branch" in line.lower() for line in _printed(capsys))

    def test_no_registry_means_no_warning(self, capsys):
        """Cannot check == cannot claim. An empty registry read never cries wolf."""
        mod = _import_monitor()
        with patch.object(mod, "_known_branch_names", return_value=set()):
            _run_scoped(mod, ["whatever"])
        assert not any("not a known branch" in line.lower() for line in _printed(capsys))

    def test_known_branch_names_survives_failure(self):
        """A broken registry read must not stop the monitor from starting."""
        mod = _import_monitor()
        with patch(
            "aipass.prax.apps.handlers.monitoring.branch_detector.get_detector",
            side_effect=OSError("nope"),
        ):
            assert mod._known_branch_names() == set()


class TestWatcherEventsBypassScope:
    """'File watcher unavailable' must not be filtered out by a branch scope."""

    def test_emit_watcher_event_bypasses_scope(self, monkeypatch):
        mod = _import_monitor()
        queue = MagicMock()
        monkeypatch.setattr(mod, "_event_queue", queue)
        mod._emit_watcher_event("error", "File watcher: completely unavailable")
        assert queue.enqueue.call_args.kwargs.get("bypass_scope") is True


class TestIntrospectionTruth:
    """Introspection lists what the handlers actually expose."""

    def test_no_filterstate_claim(self, capsys):
        """interactive_filter.py has no FilterState — it never had one."""
        mod = _import_monitor()
        mod.print_introspection()
        assert not any("FilterState" in line for line in _printed(capsys))

    def test_branch_scope_handler_listed(self, capsys):
        mod = _import_monitor()
        mod.print_introspection()
        assert any("branch_scope.py" in line for line in _printed(capsys))
