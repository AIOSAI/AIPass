# =================== AIPass ====================
# Name: test_monitor_module.py
# Description: Tests for the unified monitoring module
# Version: 1.0.0
# Created: 2026-04-03
# Modified: 2026-04-03
# =============================================

"""Tests for apps/modules/monitor.py

Covers:
- handle_command() dispatching (introspection, help, run, unknown subcommands)
- _get_watch_directories() registry-based directory enumeration
- PID cache functions (_parse_lock_pid, _refresh_pid_cache, _get_pid_for_branch)
- Threading management (_start_threads, _stop_threads, _display_worker)
- Event rendering and emission (_render_event, _emit_watcher_event)
- Inotify error handling and observer fallback
- File/log watcher workers
- Interactive loop and command dispatch
- _print_status, _run_monitor orchestration
"""

import json
import sys
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Shared helper: monitoring handler mock dict
# ---------------------------------------------------------------------------

_MONITORING_MOCKS = {
    "aipass.prax.apps.handlers.monitoring": MagicMock(),
    "aipass.prax.apps.handlers.monitoring.event_queue": MagicMock(),
    "aipass.prax.apps.handlers.monitoring.filesystem_handler": MagicMock(),
    "aipass.prax.apps.handlers.monitoring.log_watcher": MagicMock(),
    "aipass.prax.apps.handlers.monitoring.unified_stream": MagicMock(),
    "aipass.prax.apps.handlers.monitoring.module_tracker": MagicMock(),
    "aipass.prax.apps.handlers.monitoring.branch_detector": MagicMock(),
    "aipass.prax.apps.handlers.monitoring.interactive_filter": MagicMock(),
    "aipass.prax.apps.handlers.monitoring.monitoring_filters": MagicMock(),
    "aipass.prax.apps.handlers.monitoring.file_watcher_integration": MagicMock(),
    "aipass.prax.apps.handlers.monitoring.telegram_relay": MagicMock(),
    "aipass.prax.apps.handlers.monitoring.pid_cache": MagicMock(),
    "aipass.prax.apps.handlers.monitoring.instance_lock": MagicMock(),
}


def _import_monitor():
    """Import (or reload) the monitor module with all handler mocks active."""
    # Create fresh mocks each call so state doesn't leak between tests
    fresh_mocks = {k: MagicMock() for k in _MONITORING_MOCKS}
    with patch.dict(sys.modules, fresh_mocks):
        import importlib

        if "aipass.prax.apps.modules.monitor" in sys.modules:
            mod = importlib.reload(sys.modules["aipass.prax.apps.modules.monitor"])
        else:
            mod = importlib.import_module("aipass.prax.apps.modules.monitor")
        return mod


# ---------------------------------------------------------------------------
# handle_command tests
# ---------------------------------------------------------------------------


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
        """Unknown subcommand shows error + help, returns True."""
        mod = _import_monitor()
        with patch.object(mod, "print_help") as mock_help:
            result = mod.handle_command("monitor", ["bogus"])
            assert result is True
            mock_help.assert_called_once()
            # error() is the CLI mock -- check that it was called
            mod.error.assert_called()


# ---------------------------------------------------------------------------
# _dispatch_run routing tests (DPLAN-0257 — commons feed vs. branch log tail)
# ---------------------------------------------------------------------------

_COMMONS_FEED_TARGET = "aipass.prax.apps.handlers.monitoring.commons_feed.run_commons_feed"


class TestDispatchRun:
    """'run commons' opens the live social feed; --logs and mixed lists stay branch tail."""

    def test_bare_commons_routes_to_feed(self):
        """A standalone 'commons' target opens the feed, not the branch monitor."""
        mod = _import_monitor()
        mod.is_relay_enabled_by_env.return_value = False
        with (
            patch(_COMMONS_FEED_TARGET, return_value=True) as mock_feed,
            patch.object(mod, "_run_monitor") as mock_branch,
        ):
            result = mod.handle_command("monitor", ["run", "commons"])
            assert result is True
            mock_feed.assert_called_once_with([], relay_config=None)
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

    def test_commons_feed_loads_relay_config_when_relay_flag_set(self):
        """--relay on the feed path loads config via monitor.py's own _load_relay_config."""
        mod = _import_monitor()
        mod.is_relay_enabled_by_env.return_value = False
        with (
            patch(_COMMONS_FEED_TARGET, return_value=True) as mock_feed,
            patch.object(mod, "_load_relay_config", return_value={"bot_token": "x", "chat_id": 1}) as mock_load,
        ):
            mod.handle_command("monitor", ["run", "commons", "--relay"])
            mock_load.assert_called_once()
            mock_feed.assert_called_once_with(["--relay"], relay_config={"bot_token": "x", "chat_id": 1})

    def test_commons_feed_no_relay_config_when_relay_disabled(self):
        """Without --relay (and no env flag), relay_config stays None."""
        mod = _import_monitor()
        mod.is_relay_enabled_by_env.return_value = False
        with (
            patch(_COMMONS_FEED_TARGET, return_value=True) as mock_feed,
            patch.object(mod, "_load_relay_config") as mock_load,
        ):
            mod.handle_command("monitor", ["run", "commons"])
            mock_load.assert_not_called()
            mock_feed.assert_called_once_with([], relay_config=None)


# ---------------------------------------------------------------------------
# _get_watch_directories tests
# ---------------------------------------------------------------------------


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
        # Set up fake branch structure
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

        # No registry needed for this test
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
        # No apps/ entry
        assert (branch_dir / "apps") not in paths
        # But branch root and .trinity are still there
        assert branch_dir in paths
        assert trinity_dir in paths


# ---------------------------------------------------------------------------
# print_introspection tests (lines 130-167)
# ---------------------------------------------------------------------------


class TestPrintIntrospection:
    """Test print_introspection output."""

    def test_print_introspection_runs(self):
        """print_introspection runs without error and calls console.print."""
        mod = _import_monitor()
        mod.print_introspection()
        mod.json_handler.log_operation.assert_called()
        assert mod.console.print.call_count > 10


# ---------------------------------------------------------------------------
# print_help tests (lines 172-207)
# ---------------------------------------------------------------------------


class TestPrintHelp:
    """Test print_help output."""

    def test_print_help_runs(self):
        """print_help runs without error and calls console.print."""
        mod = _import_monitor()
        mod.print_help()
        assert mod.console.print.call_count > 10


# ---------------------------------------------------------------------------
# _render_event tests (lines 331-342)
# ---------------------------------------------------------------------------


class TestRenderEvent:
    """Test event rendering to console."""

    def test_render_command_event(self):
        """Command-type events call print_command_separator."""
        mod = _import_monitor()
        event = MagicMock()
        event.event_type = "command"
        event.branch = "FLOW"
        event.message = "seedgo audit"
        event.caller = "prax"
        event.action = "audit:flow"

        with patch.object(mod, "_get_pid_for_branch", return_value=None):
            mod._render_event(event)
        mod.print_command_separator.assert_called_once()

    def test_render_command_event_no_target(self):
        """Command event without colon in action passes target=None."""
        mod = _import_monitor()
        event = MagicMock()
        event.event_type = "command"
        event.branch = "FLOW"
        event.message = "seedgo audit"
        event.caller = "prax"
        event.action = "audit_only"

        with patch.object(mod, "_get_pid_for_branch", return_value=None):
            mod._render_event(event)
        mod.print_command_separator.assert_called_once()
        call_args = mod.print_command_separator.call_args
        assert call_args[0][3] is None

    def test_render_non_command_event(self):
        """Non-command events call print_event."""
        mod = _import_monitor()
        event = MagicMock()
        event.event_type = "file_change"
        event.branch = "FLOW"
        event.message = "STATUS.local.md modified"
        event.level = "info"

        with patch.object(mod, "_get_pid_for_branch", return_value=42):
            mod._render_event(event)
        mod.print_event.assert_called_once_with("file_change", "FLOW", "STATUS.local.md modified", "info", pid=42)

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
            mod._render_event(event)
        call_args = mod.print_command_separator.call_args
        assert call_args[0][3] is None


# ---------------------------------------------------------------------------
# _start_threads / _stop_threads tests (lines 298-326)
# ---------------------------------------------------------------------------


class TestThreadManagement:
    """Test thread start and stop functions."""

    def test_start_threads_creates_four_threads(self):
        """_start_threads creates and starts display, file watcher, log watcher, and rate tracker threads."""
        mod = _import_monitor()
        mock_thread = MagicMock()
        with patch("threading.Thread", return_value=mock_thread) as mock_cls:
            mod._start_threads()
        assert mock_cls.call_count == 4
        assert mock_thread.start.call_count == 4

    def test_stop_threads_sets_stop_event(self):
        """_stop_threads sets the stop event and stops the queue."""
        mod = _import_monitor()
        mock_queue = MagicMock()
        setattr(mod, "_event_queue", mock_queue)
        mod._stop_event.clear()

        mock_thread = MagicMock()
        mock_thread.is_alive.return_value = True
        setattr(mod, "_display_thread", mock_thread)
        setattr(mod, "_file_watcher_thread", mock_thread)
        setattr(mod, "_log_watcher_thread", mock_thread)

        mod._stop_threads()

        assert mod._stop_event.is_set()
        mock_queue.stop.assert_called_once()
        assert mock_thread.join.call_count == 3

    def test_stop_threads_handles_none_queue(self):
        """_stop_threads works when event queue is None."""
        mod = _import_monitor()
        setattr(mod, "_event_queue", None)
        setattr(mod, "_display_thread", None)
        setattr(mod, "_file_watcher_thread", None)
        setattr(mod, "_log_watcher_thread", None)

        # Should not raise
        mod._stop_threads()
        assert mod._stop_event.is_set()

    def test_stop_threads_skips_dead_threads(self):
        """_stop_threads skips threads that are not alive."""
        mod = _import_monitor()
        setattr(mod, "_event_queue", None)

        mock_thread = MagicMock()
        mock_thread.is_alive.return_value = False
        setattr(mod, "_display_thread", mock_thread)
        setattr(mod, "_file_watcher_thread", mock_thread)
        setattr(mod, "_log_watcher_thread", mock_thread)

        mod._stop_threads()
        mock_thread.join.assert_not_called()


# ---------------------------------------------------------------------------
# _display_worker tests (lines 349-356)
# ---------------------------------------------------------------------------


class TestDisplayWorker:
    """Test the display worker loop."""

    def test_display_worker_processes_event(self):
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
        setattr(mod, "_event_queue", mock_queue)
        mod._stop_event.clear()

        with patch.object(mod, "_render_event") as mock_render:
            mod._display_worker()
        mock_render.assert_called_once_with(mock_event)

    def test_display_worker_handles_none_queue(self):
        """Display worker sleeps when event queue is None, then stops."""
        mod = _import_monitor()
        setattr(mod, "_event_queue", None)
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


# ---------------------------------------------------------------------------
# _emit_watcher_event tests (lines 410-413)
# ---------------------------------------------------------------------------


class TestEmitWatcherEvent:
    """Test watcher event emission."""

    def test_emit_returns_early_when_no_queue(self):
        """Does nothing when event queue is None."""
        mod = _import_monitor()
        setattr(mod, "_event_queue", None)
        # Should not raise
        mod._emit_watcher_event("error", "test error")

    def test_emit_error_level_has_priority_1(self):
        """Error level events get priority 1."""
        mod = _import_monitor()
        mock_queue = MagicMock()
        setattr(mod, "_event_queue", mock_queue)

        mod._emit_watcher_event("error", "bad stuff happened")
        mock_queue.enqueue.assert_called_once()
        # MonitoringEvent is mocked, so check the kwargs it was constructed with
        me_cls = mod.MonitoringEvent
        me_cls.assert_called_once()
        call_kwargs = me_cls.call_args[1]
        assert call_kwargs["priority"] == 1

    def test_emit_warning_level_has_priority_2(self):
        """Non-error level events get priority 2."""
        mod = _import_monitor()
        mock_queue = MagicMock()
        setattr(mod, "_event_queue", mock_queue)

        mod._emit_watcher_event("warning", "something happened")
        mock_queue.enqueue.assert_called_once()
        me_cls = mod.MonitoringEvent
        me_cls.assert_called_once()
        call_kwargs = me_cls.call_args[1]
        assert call_kwargs["priority"] == 2


# ---------------------------------------------------------------------------
# _inotify_fix_message tests (lines 428-438)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# _start_observer_with_fallback tests (lines 446-472)
# ---------------------------------------------------------------------------


class TestStartObserverWithFallback:
    """Test watchdog observer startup with fallback."""

    def _import_with_watchdog(self):
        """Import monitor with watchdog modules also mocked."""
        extra = {
            "watchdog": MagicMock(),
            "watchdog.observers": MagicMock(),
            "watchdog.observers.polling": MagicMock(),
        }
        fresh_mocks = {k: MagicMock() for k in _MONITORING_MOCKS}
        fresh_mocks.update(extra)
        with patch.dict(sys.modules, fresh_mocks):
            import importlib

            if "aipass.prax.apps.modules.monitor" in sys.modules:
                mod = importlib.reload(sys.modules["aipass.prax.apps.modules.monitor"])
            else:
                mod = importlib.import_module("aipass.prax.apps.modules.monitor")
            return mod

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

    def test_fallback_to_polling(self, tmp_path):
        """Falls back to PollingObserver when inotify fails."""
        mod = self._import_with_watchdog()
        handler = MagicMock()
        watch_dirs = [(tmp_path, True)]
        setattr(mod, "_event_queue", MagicMock())

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

    def test_both_fail_returns_none(self, tmp_path):
        """Returns None when both inotify and polling fail."""
        mod = self._import_with_watchdog()
        handler = MagicMock()
        watch_dirs = [(tmp_path, True)]
        setattr(mod, "_event_queue", MagicMock())

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


# ---------------------------------------------------------------------------
# _file_watcher_worker tests (lines 479-511)
# ---------------------------------------------------------------------------


class TestFileWatcherWorker:
    """Test file watcher worker thread."""

    def test_no_watch_dirs_returns_early(self):
        """Worker returns early when no watch directories found."""
        mod = _import_monitor()
        setattr(mod, "_event_queue", MagicMock())

        mock_config = MagicMock()
        mock_config._find_repo_root.return_value = MagicMock()
        mock_fs_handler = MagicMock()

        with (
            patch.dict(
                sys.modules,
                {
                    "aipass.prax.apps.handlers.monitoring.filesystem_handler": mock_fs_handler,
                    "aipass.prax.apps.handlers.config.load": mock_config,
                },
            ),
            patch.object(mod, "_get_watch_directories", return_value=[]),
            patch.object(mod, "_emit_watcher_event") as mock_emit,
        ):
            mod._file_watcher_worker()
        mock_emit.assert_called_once()

    def test_observer_none_returns_early(self):
        """Worker returns early when observer startup fails."""
        mod = _import_monitor()
        setattr(mod, "_event_queue", MagicMock())

        mock_config = MagicMock()
        mock_config._find_repo_root.return_value = MagicMock()
        mock_fs_handler = MagicMock()

        with (
            patch.dict(
                sys.modules,
                {
                    "aipass.prax.apps.handlers.monitoring.filesystem_handler": mock_fs_handler,
                    "aipass.prax.apps.handlers.config.load": mock_config,
                },
            ),
            patch.object(mod, "_get_watch_directories", return_value=[("fakedir", True)]),
            patch.object(mod, "_start_observer_with_fallback", return_value=None),
        ):
            mod._file_watcher_worker()

    def test_worker_runs_loop_and_stops_observer(self, tmp_path):
        """Worker runs sleep loop and stops observer on stop_event."""
        mod = _import_monitor()
        setattr(mod, "_event_queue", MagicMock())
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
            patch.dict(
                sys.modules,
                {
                    "aipass.prax.apps.handlers.monitoring.filesystem_handler": mock_fs_handler,
                    "aipass.prax.apps.handlers.config.load": mock_config,
                },
            ),
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

        mock_observer.stop.assert_called_once()
        mock_observer.join.assert_called_once()


# ---------------------------------------------------------------------------
# _start_log_watcher_with_fallback tests (lines 519-535)
# ---------------------------------------------------------------------------


class TestStartLogWatcherWithFallback:
    """Test log watcher startup with fallback."""

    def test_success_on_first_try(self):
        """Returns True when start_log_watcher succeeds."""
        mod = _import_monitor()
        mock_queue = MagicMock()

        mock_lw = MagicMock()
        mock_lw.start_log_watcher = MagicMock()

        with patch.dict(
            sys.modules,
            {"aipass.prax.apps.handlers.monitoring.log_watcher": mock_lw},
        ):
            result = mod._start_log_watcher_with_fallback(mock_queue)
        assert result is True

    def test_fallback_to_polling(self):
        """Falls back to polling when inotify fails."""
        mod = _import_monitor()
        mock_queue = MagicMock()
        setattr(mod, "_event_queue", MagicMock())

        import errno

        mock_lw = MagicMock()
        call_count = 0

        def _start(eq, use_polling=False):
            """Fail on first call, succeed on second."""
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise OSError(errno.ENOSPC, "inotify limit")

        mock_lw.start_log_watcher = _start

        with patch.dict(
            sys.modules,
            {"aipass.prax.apps.handlers.monitoring.log_watcher": mock_lw},
        ):
            result = mod._start_log_watcher_with_fallback(mock_queue)
        assert result is True

    def test_both_fail_returns_false(self):
        """Returns False when both inotify and polling fail."""
        mod = _import_monitor()
        mock_queue = MagicMock()
        setattr(mod, "_event_queue", MagicMock())

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

        with patch.dict(
            sys.modules,
            {"aipass.prax.apps.handlers.monitoring.log_watcher": mock_lw},
        ):
            result = mod._start_log_watcher_with_fallback(mock_queue)
        assert result is False


# ---------------------------------------------------------------------------
# _log_watcher_worker tests (lines 542-555)
# ---------------------------------------------------------------------------


class TestLogWatcherWorker:
    """Test log watcher worker thread."""

    def test_returns_early_when_no_queue(self):
        """Worker returns early when event queue is None."""
        mod = _import_monitor()
        setattr(mod, "_event_queue", None)

        mock_lw = MagicMock()
        with patch.dict(
            sys.modules,
            {"aipass.prax.apps.handlers.monitoring.log_watcher": mock_lw},
        ):
            mod._log_watcher_worker()
        mock_lw.start_log_watcher.assert_not_called()

    def test_returns_early_on_watcher_failure(self):
        """Worker returns when log watcher startup fails."""
        mod = _import_monitor()
        setattr(mod, "_event_queue", MagicMock())

        with patch.object(mod, "_start_log_watcher_with_fallback", return_value=False):
            mock_lw = MagicMock()
            with patch.dict(
                sys.modules,
                {"aipass.prax.apps.handlers.monitoring.log_watcher": mock_lw},
            ):
                mod._log_watcher_worker()

    def test_worker_runs_loop_and_stops(self):
        """Worker runs sleep loop and calls stop_log_watcher on stop_event."""
        mod = _import_monitor()
        setattr(mod, "_event_queue", MagicMock())
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
            patch.dict(
                sys.modules,
                {"aipass.prax.apps.handlers.monitoring.log_watcher": mock_lw},
            ),
            patch("time.sleep", side_effect=_sleep),
        ):
            mod._log_watcher_worker()
        mock_lw.stop_log_watcher.assert_called_once()


# ---------------------------------------------------------------------------
# _handle_interactive_cmd tests (lines 560-567)
# ---------------------------------------------------------------------------


class TestHandleInteractiveCmd:
    """Test interactive command dispatch."""

    def test_help_command(self):
        """Help command calls get_help_text and prints it."""
        mod = _import_monitor()
        mock_help = MagicMock(return_value="help text here")
        mod._handle_interactive_cmd("help", mock_help)
        mock_help.assert_called_once()
        mod.console.print.assert_called()

    def test_status_command(self):
        """Status command calls _print_status."""
        mod = _import_monitor()
        with patch.object(mod, "_print_status") as mock_status:
            mod._handle_interactive_cmd("status", MagicMock())
        mock_status.assert_called_once()

    def test_unknown_command(self):
        """Unknown command prints error."""
        mod = _import_monitor()
        mod._handle_interactive_cmd("bogus", MagicMock())
        mod.error.assert_called()


# ---------------------------------------------------------------------------
# _interactive_loop tests (lines 575-609)
# ---------------------------------------------------------------------------


class TestInteractiveLoop:
    """Test interactive command loop."""

    def test_non_tty_passive_mode(self):
        """Non-TTY mode runs passive loop until stop event."""
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
            patch("time.sleep", side_effect=_sleep),
        ):
            mod._interactive_loop()

    def test_non_tty_keyboard_interrupt(self):
        """Non-TTY mode handles KeyboardInterrupt gracefully."""
        mod = _import_monitor()
        mod._stop_event.clear()

        with (
            patch.object(sys.stdin, "isatty", return_value=False),
            patch("time.sleep", side_effect=KeyboardInterrupt),
        ):
            mod._interactive_loop()

    def test_tty_quit_command(self):
        """TTY mode exits on 'quit' command."""
        mod = _import_monitor()
        mod._stop_event.clear()

        mock_filter = MagicMock()
        mock_filter.parse_command = MagicMock(return_value=("quit", []))
        mock_filter.get_help_text = MagicMock(return_value="help")

        with (
            patch.object(sys.stdin, "isatty", return_value=True),
            patch("builtins.input", return_value="quit"),
            patch.dict(
                sys.modules,
                {
                    "aipass.prax.apps.handlers.monitoring.interactive_filter": mock_filter,
                },
            ),
        ):
            mod._interactive_loop()

    def test_tty_exit_command(self):
        """TTY mode exits on 'exit' command."""
        mod = _import_monitor()
        mod._stop_event.clear()

        mock_filter = MagicMock()
        mock_filter.parse_command = MagicMock(return_value=("exit", []))

        with (
            patch.object(sys.stdin, "isatty", return_value=True),
            patch("builtins.input", return_value="exit"),
            patch.dict(
                sys.modules,
                {
                    "aipass.prax.apps.handlers.monitoring.interactive_filter": mock_filter,
                },
            ),
        ):
            mod._interactive_loop()

    def test_tty_q_command(self):
        """TTY mode exits on 'q' command."""
        mod = _import_monitor()
        mod._stop_event.clear()

        mock_filter = MagicMock()
        mock_filter.parse_command = MagicMock(return_value=("q", []))

        with (
            patch.object(sys.stdin, "isatty", return_value=True),
            patch("builtins.input", return_value="q"),
            patch.dict(
                sys.modules,
                {
                    "aipass.prax.apps.handlers.monitoring.interactive_filter": mock_filter,
                },
            ),
        ):
            mod._interactive_loop()

    def test_tty_empty_input_skipped(self):
        """Empty input is ignored in TTY mode."""
        mod = _import_monitor()
        mod._stop_event.clear()

        call_count = 0

        def _input(prompt=""):
            """Return empty first, then quit."""
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return ""
            return "quit"

        mock_filter = MagicMock()
        returns = iter([("", []), ("quit", [])])
        mock_filter.parse_command = MagicMock(side_effect=lambda x: next(returns))

        with (
            patch.object(sys.stdin, "isatty", return_value=True),
            patch("builtins.input", side_effect=_input),
            patch.dict(
                sys.modules,
                {
                    "aipass.prax.apps.handlers.monitoring.interactive_filter": mock_filter,
                },
            ),
        ):
            mod._interactive_loop()

    def test_tty_none_cmd_skipped(self):
        """None command from parse_command is skipped."""
        mod = _import_monitor()
        mod._stop_event.clear()

        call_count = 0

        def _input(prompt=""):
            """Return text first, then quit."""
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return "something"
            return "quit"

        mock_filter = MagicMock()
        returns = iter([(None, []), ("quit", [])])
        mock_filter.parse_command = MagicMock(side_effect=lambda x: next(returns))

        with (
            patch.object(sys.stdin, "isatty", return_value=True),
            patch("builtins.input", side_effect=_input),
            patch.dict(
                sys.modules,
                {
                    "aipass.prax.apps.handlers.monitoring.interactive_filter": mock_filter,
                },
            ),
        ):
            mod._interactive_loop()

    def test_tty_keyboard_interrupt(self):
        """TTY mode handles KeyboardInterrupt gracefully."""
        mod = _import_monitor()
        mod._stop_event.clear()

        mock_filter = MagicMock()

        with (
            patch.object(sys.stdin, "isatty", return_value=True),
            patch("builtins.input", side_effect=KeyboardInterrupt),
            patch.dict(
                sys.modules,
                {
                    "aipass.prax.apps.handlers.monitoring.interactive_filter": mock_filter,
                },
            ),
        ):
            mod._interactive_loop()

    def test_tty_eof_error(self):
        """TTY mode handles EOFError gracefully."""
        mod = _import_monitor()
        mod._stop_event.clear()

        mock_filter = MagicMock()

        with (
            patch.object(sys.stdin, "isatty", return_value=True),
            patch("builtins.input", side_effect=EOFError),
            patch.dict(
                sys.modules,
                {
                    "aipass.prax.apps.handlers.monitoring.interactive_filter": mock_filter,
                },
            ),
        ):
            mod._interactive_loop()

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
            patch.dict(
                sys.modules,
                {
                    "aipass.prax.apps.handlers.monitoring.interactive_filter": mock_filter,
                },
            ),
            patch.object(mod, "_handle_interactive_cmd") as mock_handler,
        ):
            mod._interactive_loop()
        mock_handler.assert_called_once()


# ---------------------------------------------------------------------------
# _print_status tests (lines 616-621)
# ---------------------------------------------------------------------------


class TestPrintStatusMonitor:
    """Test status display function."""

    def test_print_status_with_queue(self):
        """Status display includes queue size when queue exists."""
        mod = _import_monitor()
        mock_queue = MagicMock()
        mock_queue.size.return_value = 5
        setattr(mod, "_event_queue", mock_queue)

        mod._print_status()
        assert mod.console.print.call_count >= 3

    def test_print_status_without_queue(self):
        """Status display works when event queue is None."""
        mod = _import_monitor()
        setattr(mod, "_event_queue", None)
        mod._print_status()
        assert mod.console.print.call_count >= 2


# ---------------------------------------------------------------------------
# _run_monitor tests (lines 256-290)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# _get_watch_directories edge cases (lines 389-403)
# ---------------------------------------------------------------------------


class TestGetWatchDirectoriesEdgeCases:
    """Test edge cases in _get_watch_directories."""

    def test_corrupted_registry_json(self, tmp_path):
        """Corrupted registry JSON logs warning and continues."""
        mod = _import_monitor()
        registry_file = tmp_path / "AIPASS_REGISTRY.json"
        registry_file.write_text("{bad json!!}", encoding="utf-8")

        with patch("pathlib.Path.home", return_value=tmp_path / "fakehome"):
            result = mod._get_watch_directories(tmp_path)
        assert isinstance(result, list)

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


# ---------------------------------------------------------------------------
# Branch scoping — `monitor run seedgo,cli` (devpulse 5331acc2)
# ---------------------------------------------------------------------------


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


def _printed(mod):
    """All strings passed to console.print during the call."""
    return [str(c.args[0]) for c in mod.console.print.call_args_list if c.args]


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

    def test_relay_flag_is_not_a_branch(self):
        """--relay is stripped before scope parsing."""
        mod = _import_monitor()
        queue = _run_scoped(mod, ["--relay"])
        assert _installed_scope_is_unscoped(queue)


class TestBannerTruth:
    """The banner may never claim 'all branches, no filters' while scoped."""

    def test_unscoped_banner_unchanged(self):
        mod = _import_monitor()
        _run_scoped(mod, [])
        assert any("all branches, all levels, no filters" in line for line in _printed(mod))

    def test_scoped_banner_names_the_scope(self):
        mod = _import_monitor()
        _run_scoped(mod, ["devpulse,seedgo"])
        assert any("DEVPULSE, SEEDGO" in line for line in _printed(mod))

    def test_scoped_banner_drops_the_all_branches_claim(self):
        mod = _import_monitor()
        _run_scoped(mod, ["devpulse"])
        for line in _printed(mod):
            assert "all branches" not in line, f"scoped run still claims all branches: {line}"
            assert "no filters" not in line, f"scoped run still claims no filters: {line}"

    def test_status_unscoped_unchanged(self):
        mod = _import_monitor()
        setattr(mod, "_event_queue", None)
        setattr(mod, "_active_scope", None)
        mod._print_status()
        assert any("all branches, all levels, no filters" in line for line in _printed(mod))

    def test_status_names_the_scope(self):
        """`status` inside a scoped monitor reports the scope, not 'no filters'."""
        from aipass.prax.apps.handlers.monitoring.branch_scope import BranchScope

        mod = _import_monitor()
        queue = MagicMock()
        queue.size.return_value = 2
        queue.suppressed_count.return_value = 41
        setattr(mod, "_event_queue", queue)
        setattr(mod, "_active_scope", BranchScope(["SEEDGO"]))

        mod._print_status()
        lines = _printed(mod)
        assert any("SEEDGO" in line for line in lines)
        assert not any("no filters" in line for line in lines)
        assert any("41" in line for line in lines), "hidden-event count explains a quiet screen"


class TestUnknownScopeWarning:
    """A typo'd branch would otherwise be an empty screen with no explanation."""

    def test_unknown_branch_warns(self):
        mod = _import_monitor()
        with patch.object(mod, "_known_branch_names", return_value={"SEEDGO", "PRAX"}):
            _run_scoped(mod, ["seedgoo"])
        assert any("seedgoo" in line.lower() for line in _printed(mod))

    def test_known_branch_does_not_warn(self):
        mod = _import_monitor()
        with patch.object(mod, "_known_branch_names", return_value={"SEEDGO", "PRAX"}):
            _run_scoped(mod, ["seedgo"])
        assert not any("not a known branch" in line.lower() for line in _printed(mod))

    def test_no_registry_means_no_warning(self):
        """Cannot check == cannot claim. An empty registry read never cries wolf."""
        mod = _import_monitor()
        with patch.object(mod, "_known_branch_names", return_value=set()):
            _run_scoped(mod, ["whatever"])
        assert not any("not a known branch" in line.lower() for line in _printed(mod))

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

    def test_emit_watcher_event_bypasses_scope(self):
        mod = _import_monitor()
        queue = MagicMock()
        setattr(mod, "_event_queue", queue)
        mod._emit_watcher_event("error", "File watcher: completely unavailable")
        assert queue.enqueue.call_args.kwargs.get("bypass_scope") is True


class TestIntrospectionTruth:
    """Introspection lists what the handlers actually expose."""

    def test_no_filterstate_claim(self):
        """interactive_filter.py has no FilterState — it never had one."""
        mod = _import_monitor()
        mod.print_introspection()
        assert not any("FilterState" in line for line in _printed(mod))

    def test_branch_scope_handler_listed(self):
        mod = _import_monitor()
        mod.print_introspection()
        assert any("branch_scope.py" in line for line in _printed(mod))
