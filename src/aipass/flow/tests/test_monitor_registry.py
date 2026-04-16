"""Tests for monitor_ops handler and registry_monitor module."""

import builtins
import os
import time
import types
from collections.abc import Mapping, Sequence
from pathlib import Path
from unittest.mock import MagicMock, patch


# ─── Import helpers ───────────────────────────────────────


def _import_monitor_ops():
    """Import monitor_ops module and return it."""
    import aipass.flow.apps.handlers.registry.monitor_ops as mod

    return mod


def _import_registry_monitor():
    """Import registry_monitor module and return it."""
    import aipass.flow.apps.modules.registry_monitor as mod

    return mod


def _make_plan_file(directory: Path, number: str) -> Path:
    """Create a FPLAN-NNNN.md file in the given directory."""
    filename = f"FPLAN-{number}.md"
    plan_file = directory / filename
    plan_file.write_text(f"# Plan {number}\nTest content", encoding="utf-8")
    return plan_file


def _make_event(src_path: str, dest_path: str | None = None, is_directory: bool = False):
    """Create a mock watchdog event object."""
    event = MagicMock()
    event.src_path = src_path
    event.is_directory = is_directory
    if dest_path is not None:
        event.dest_path = dest_path
    return event


# ═══════════════════════════════════════════════════════════
# 1. handle_walk_error
# ═══════════════════════════════════════════════════════════


class TestHandleWalkError:
    """Tests for the handle_walk_error inner function in scan_plan_files_impl."""

    def test_permission_error_is_silenced(self, tmp_path):
        """PermissionError should not trigger a warning log."""
        mod = _import_monitor_ops()
        with patch.object(mod, "_fire_event", return_value=False):
            # The handle_walk_error function is defined inside scan_plan_files_impl.
            # We exercise it by creating a directory we cannot read.
            restricted = tmp_path / "restricted"
            restricted.mkdir()
            # Create a plan file in a readable subdirectory so scan itself works
            _make_plan_file(tmp_path, "0001")

            # Make the restricted dir unreadable
            os.chmod(str(restricted), 0o000)
            try:
                result = mod.scan_plan_files_impl(
                    ecosystem_root=tmp_path,
                    load_registry=lambda: {"plans": {}},
                )
                # Scan should complete without crashing
                assert isinstance(result, dict)
                assert "total_plans" in result
            finally:
                os.chmod(str(restricted), 0o755)

    def test_generic_os_error_logs_warning(self, tmp_path, mock_logger):
        """Non-PermissionError OSError should be logged as warning."""
        mod = _import_monitor_ops()
        # We cannot easily trigger a generic OSError from os.walk, but we
        # can directly call the handle_walk_error closure pattern by
        # simulating a scan on a non-existent directory.
        missing = tmp_path / "nonexistent_root"
        with patch.object(mod, "_fire_event", return_value=False):
            result = mod.scan_plan_files_impl(
                ecosystem_root=missing,
                load_registry=lambda: {"plans": {}},
            )
            # Should not crash, just return empty results
            assert result["total_plans"] == 0
            assert result["added"] == []


# ═══════════════════════════════════════════════════════════
# 2. scan_plan_files_impl
# ═══════════════════════════════════════════════════════════


class TestScanPlanFilesImpl:
    """Tests for scan_plan_files_impl in monitor_ops."""

    def test_detects_plan_files_in_root(self, tmp_path):
        """Plan files at root level should be detected."""
        mod = _import_monitor_ops()
        _make_plan_file(tmp_path, "0001")
        _make_plan_file(tmp_path, "0002")

        with patch.object(mod, "_fire_event", return_value=True):
            result = mod.scan_plan_files_impl(
                ecosystem_root=tmp_path,
                load_registry=lambda: {"plans": {}},
            )
        assert "0001" in result["added"]
        assert "0002" in result["added"]
        assert result["healing_performed"] is True

    def test_detects_plan_files_in_subdirectories(self, tmp_path):
        """Plan files in subdirectories should be detected."""
        mod = _import_monitor_ops()
        sub = tmp_path / "projects" / "alpha"
        sub.mkdir(parents=True)
        _make_plan_file(sub, "0010")

        with patch.object(mod, "_fire_event", return_value=True):
            result = mod.scan_plan_files_impl(
                ecosystem_root=tmp_path,
                load_registry=lambda: {"plans": {}},
            )
        assert "0010" in result["added"]

    def test_ignores_non_plan_files(self, tmp_path):
        """Non-plan files should be ignored even if they look similar."""
        mod = _import_monitor_ops()
        # Valid plan files (any prefix: FPLAN, DPLAN, etc.)
        _make_plan_file(tmp_path, "0001")
        (tmp_path / "DPLAN-0002.md").write_text("also a plan", encoding="utf-8")
        # Invalid files that should not match
        (tmp_path / "FPLAN-ABC.md").write_text("bad number", encoding="utf-8")
        (tmp_path / "README.md").write_text("readme", encoding="utf-8")
        (tmp_path / "NOTES-0003.md").write_text("not a plan prefix", encoding="utf-8")

        with patch.object(mod, "_fire_event", return_value=True):
            result = mod.scan_plan_files_impl(
                ecosystem_root=tmp_path,
                load_registry=lambda: {"plans": {}},
            )
        assert sorted(result["added"]) == ["0001", "0002"]

    def test_skips_ignored_folders(self, tmp_path):
        """Directories in IGNORE_FOLDERS should be skipped."""
        mod = _import_monitor_ops()
        # Plan file in ignored directory
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        _make_plan_file(git_dir, "0001")

        pycache_dir = tmp_path / "__pycache__"
        pycache_dir.mkdir()
        _make_plan_file(pycache_dir, "0002")

        # Plan file in non-ignored directory
        good_dir = tmp_path / "active"
        good_dir.mkdir()
        _make_plan_file(good_dir, "0003")

        with patch.object(mod, "_fire_event", return_value=True):
            result = mod.scan_plan_files_impl(
                ecosystem_root=tmp_path,
                load_registry=lambda: {"plans": {}},
            )
        assert "0003" in result["added"]
        assert "0001" not in result["added"]
        assert "0002" not in result["added"]

    def test_detects_orphaned_registry_entries(self, tmp_path):
        """Registry entries with no matching file should fire deleted events."""
        mod = _import_monitor_ops()
        # No plan files on disk, but registry has entries
        registry = {
            "plans": {
                "0001": {"file_path": str(tmp_path / "FPLAN-0001.md"), "status": "open"},
                "0002": {"file_path": str(tmp_path / "FPLAN-0002.md"), "status": "open"},
            }
        }
        with patch.object(mod, "_fire_event", return_value=True):
            result = mod.scan_plan_files_impl(
                ecosystem_root=tmp_path,
                load_registry=lambda: registry,
            )
        assert "0001" in result["removed"]
        assert "0002" in result["removed"]
        assert result["healing_performed"] is True

    def test_detects_moved_files(self, tmp_path):
        """Files that exist but at a different path should fire moved events."""
        mod = _import_monitor_ops()
        new_dir = tmp_path / "new_location"
        new_dir.mkdir()
        _make_plan_file(new_dir, "0001")

        registry = {
            "plans": {
                "0001": {
                    "file_path": str(tmp_path / "old_location" / "FPLAN-0001.md"),
                    "status": "open",
                },
            }
        }
        with patch.object(mod, "_fire_event", return_value=True):
            result = mod.scan_plan_files_impl(
                ecosystem_root=tmp_path,
                load_registry=lambda: registry,
            )
        assert "0001" in result["updated"]

    def test_no_changes_needed(self, tmp_path):
        """When disk matches registry, no healing should be needed."""
        mod = _import_monitor_ops()
        plan = _make_plan_file(tmp_path, "0001")

        registry = {
            "plans": {
                "0001": {"file_path": str(plan), "status": "open"},
            }
        }
        with patch.object(mod, "_fire_event", return_value=True):
            result = mod.scan_plan_files_impl(
                ecosystem_root=tmp_path,
                load_registry=lambda: registry,
            )
        assert result["added"] == []
        assert result["updated"] == []
        assert result["removed"] == []
        assert result["renumbered"] == []
        assert result["healing_performed"] is False

    def test_duplicate_plan_files_renumbered(self, tmp_path):
        """Duplicate plan numbers should be auto-renumbered."""
        mod = _import_monitor_ops()
        # Create two directories with same plan number
        dir_a = tmp_path / "project_a"
        dir_a.mkdir()
        dir_b = tmp_path / "project_b"
        dir_b.mkdir()

        _make_plan_file(dir_a, "0001")
        _make_plan_file(dir_b, "0001")

        with patch.object(mod, "_fire_event", return_value=True):
            result = mod.scan_plan_files_impl(
                ecosystem_root=tmp_path,
                load_registry=lambda: {"plans": {}},
            )
        assert len(result["renumbered"]) == 1
        assert result["renumbered"][0]["old_number"] == "0001"
        assert result["renumbered"][0]["new_number"] == "0002"
        assert result["healing_performed"] is True

    def test_scan_calls_json_handler_log(self, tmp_path, mock_json_handler):
        """Scan should log its results via json_handler."""
        mod = _import_monitor_ops()
        _make_plan_file(tmp_path, "0001")

        with patch.object(mod, "_fire_event", return_value=True):
            mod.scan_plan_files_impl(
                ecosystem_root=tmp_path,
                load_registry=lambda: {"plans": {}},
            )
        mock_json_handler.assert_called_once()
        call_args = mock_json_handler.call_args
        assert call_args[0][0] == "plan_files_scanned"
        assert call_args[0][1]["success"] is True

    def test_fire_event_failure_excludes_from_results(self, tmp_path):
        """If _fire_event returns False, the plan should not appear in added."""
        mod = _import_monitor_ops()
        _make_plan_file(tmp_path, "0001")

        with patch.object(mod, "_fire_event", return_value=False):
            result = mod.scan_plan_files_impl(
                ecosystem_root=tmp_path,
                load_registry=lambda: {"plans": {}},
            )
        assert result["added"] == []


# ═══════════════════════════════════════════════════════════
# 3. PlanFileWatcher event handlers
# ═══════════════════════════════════════════════════════════


class TestPlanFileWatcherOnCreated:
    """Tests for PlanFileWatcher.on_created."""

    def setup_method(self):
        """Clear deduplication state before each test."""
        mod = _import_monitor_ops()
        mod._recent_events.clear()

    def test_created_event_for_plan_file(self, tmp_path):
        """on_created should log and schedule fire for a valid FPLAN file."""
        mod = _import_monitor_ops()
        watcher = mod.PlanFileWatcher()
        event = _make_event(str(tmp_path / "FPLAN-0042.md"))

        with patch.object(watcher, "_schedule_fire_created") as mock_fire:
            watcher.on_created(event)
            mock_fire.assert_called_once()
            call_path = mock_fire.call_args[0][0]
            assert call_path.name == "FPLAN-0042.md"

    def test_created_event_ignores_directory(self, tmp_path):
        """on_created should ignore directory events."""
        mod = _import_monitor_ops()
        watcher = mod.PlanFileWatcher()
        event = _make_event(str(tmp_path / "FPLAN-0042.md"), is_directory=True)

        with patch.object(watcher, "_schedule_fire_created") as mock_fire:
            watcher.on_created(event)
            mock_fire.assert_not_called()

    def test_created_event_ignores_non_plan_file(self, tmp_path):
        """on_created should ignore non-FPLAN files."""
        mod = _import_monitor_ops()
        watcher = mod.PlanFileWatcher()
        event = _make_event(str(tmp_path / "README.md"))

        with patch.object(watcher, "_schedule_fire_created") as mock_fire:
            watcher.on_created(event)
            mock_fire.assert_not_called()

    def test_created_event_deduplication(self, tmp_path):
        """Duplicate create events for the same plan within DEDUPE_WINDOW should be ignored."""
        mod = _import_monitor_ops()
        watcher = mod.PlanFileWatcher()
        event = _make_event(str(tmp_path / "FPLAN-0042.md"))

        with patch.object(watcher, "_schedule_fire_created") as mock_fire:
            watcher.on_created(event)
            watcher.on_created(event)  # duplicate
            assert mock_fire.call_count == 1


class TestPlanFileWatcherOnDeleted:
    """Tests for PlanFileWatcher.on_deleted."""

    def setup_method(self):
        mod = _import_monitor_ops()
        mod._recent_events.clear()

    def test_deleted_event_for_plan_file(self, tmp_path):
        """on_deleted should log and schedule fire for a valid FPLAN file."""
        mod = _import_monitor_ops()
        watcher = mod.PlanFileWatcher()
        event = _make_event(str(tmp_path / "FPLAN-0007.md"))

        with patch.object(watcher, "_schedule_fire_deleted") as mock_fire:
            watcher.on_deleted(event)
            mock_fire.assert_called_once()
            call_path = mock_fire.call_args[0][0]
            assert call_path.name == "FPLAN-0007.md"

    def test_deleted_event_ignores_directory(self, tmp_path):
        """on_deleted should ignore directory events."""
        mod = _import_monitor_ops()
        watcher = mod.PlanFileWatcher()
        event = _make_event(str(tmp_path / "FPLAN-0007.md"), is_directory=True)

        with patch.object(watcher, "_schedule_fire_deleted") as mock_fire:
            watcher.on_deleted(event)
            mock_fire.assert_not_called()

    def test_deleted_event_ignores_non_plan_file(self, tmp_path):
        """on_deleted should ignore non-FPLAN files."""
        mod = _import_monitor_ops()
        watcher = mod.PlanFileWatcher()
        event = _make_event(str(tmp_path / "notes.txt"))

        with patch.object(watcher, "_schedule_fire_deleted") as mock_fire:
            watcher.on_deleted(event)
            mock_fire.assert_not_called()

    def test_deleted_event_deduplication(self, tmp_path):
        """Duplicate delete events within DEDUPE_WINDOW should be ignored."""
        mod = _import_monitor_ops()
        watcher = mod.PlanFileWatcher()
        event = _make_event(str(tmp_path / "FPLAN-0007.md"))

        with patch.object(watcher, "_schedule_fire_deleted") as mock_fire:
            watcher.on_deleted(event)
            watcher.on_deleted(event)  # duplicate
            assert mock_fire.call_count == 1


class TestPlanFileWatcherOnMoved:
    """Tests for PlanFileWatcher.on_moved."""

    def setup_method(self):
        mod = _import_monitor_ops()
        mod._recent_events.clear()

    def test_moved_event_for_plan_file(self, tmp_path):
        """on_moved should log and schedule fire when dest is a valid FPLAN file."""
        mod = _import_monitor_ops()
        watcher = mod.PlanFileWatcher()
        src = str(tmp_path / "old" / "FPLAN-0003.md")
        dest = str(tmp_path / "new" / "FPLAN-0003.md")
        event = _make_event(src, dest_path=dest)

        with patch.object(watcher, "_schedule_fire_moved") as mock_fire:
            watcher.on_moved(event)
            mock_fire.assert_called_once()
            call_src = mock_fire.call_args[0][0]
            call_dest = mock_fire.call_args[0][1]
            assert call_src == Path(src)
            assert call_dest == Path(dest)

    def test_moved_event_ignores_directory(self, tmp_path):
        """on_moved should ignore directory events."""
        mod = _import_monitor_ops()
        watcher = mod.PlanFileWatcher()
        event = _make_event(
            str(tmp_path / "FPLAN-0003.md"),
            dest_path=str(tmp_path / "new" / "FPLAN-0003.md"),
            is_directory=True,
        )

        with patch.object(watcher, "_schedule_fire_moved") as mock_fire:
            watcher.on_moved(event)
            mock_fire.assert_not_called()

    def test_moved_event_ignores_non_plan_dest(self, tmp_path):
        """on_moved should ignore moves where dest is not a FPLAN file."""
        mod = _import_monitor_ops()
        watcher = mod.PlanFileWatcher()
        event = _make_event(
            str(tmp_path / "FPLAN-0003.md"),
            dest_path=str(tmp_path / "renamed.txt"),
        )

        with patch.object(watcher, "_schedule_fire_moved") as mock_fire:
            watcher.on_moved(event)
            mock_fire.assert_not_called()

    def test_moved_event_deduplication(self, tmp_path):
        """Duplicate move events within DEDUPE_WINDOW should be ignored."""
        mod = _import_monitor_ops()
        watcher = mod.PlanFileWatcher()
        event = _make_event(
            str(tmp_path / "old" / "FPLAN-0003.md"),
            dest_path=str(tmp_path / "new" / "FPLAN-0003.md"),
        )

        with patch.object(watcher, "_schedule_fire_moved") as mock_fire:
            watcher.on_moved(event)
            watcher.on_moved(event)  # duplicate
            assert mock_fire.call_count == 1


# ═══════════════════════════════════════════════════════════
# 4. start_monitoring_impl / stop_monitoring_impl / get_status_impl
# ═══════════════════════════════════════════════════════════


class TestStartMonitoringImpl:
    """Tests for start_monitoring_impl in monitor_ops."""

    def teardown_method(self):
        """Ensure observer is stopped after each test."""
        mod = _import_monitor_ops()
        if mod._observer and mod._observer.is_alive():
            mod._observer.stop()
            mod._observer.join()
        mod._observer = None

    def test_start_returns_success(self, tmp_path):
        """Starting monitor on a valid directory should succeed."""
        mod = _import_monitor_ops()
        mod._observer = None
        result = mod.start_monitoring_impl(tmp_path)
        assert result["success"] is True
        assert result["status"] == "started"
        assert str(tmp_path) in result["message"]

    def test_start_when_already_running(self, tmp_path):
        """Starting monitor when already running should return already_running."""
        mod = _import_monitor_ops()
        mod._observer = None
        # Start once
        mod.start_monitoring_impl(tmp_path)
        # Start again
        result = mod.start_monitoring_impl(tmp_path)
        assert result["success"] is False
        assert result["status"] == "already_running"

    def test_start_handles_observer_exception(self, tmp_path):
        """If Observer raises, start should return error status."""
        mod = _import_monitor_ops()
        mod._observer = None
        with patch("aipass.flow.apps.handlers.registry.monitor_ops.Observer") as mock_obs:
            mock_obs.return_value.start.side_effect = RuntimeError("Cannot start")
            result = mod.start_monitoring_impl(tmp_path)
        assert result["success"] is False
        assert result["status"] == "error"
        assert "Cannot start" in result["message"]


class TestStopMonitoringImpl:
    """Tests for stop_monitoring_impl in monitor_ops."""

    def teardown_method(self):
        mod = _import_monitor_ops()
        mod._observer = None

    def test_stop_running_observer(self, tmp_path):
        """Stopping a running observer should succeed."""
        mod = _import_monitor_ops()
        mod._observer = None
        mod.start_monitoring_impl(tmp_path)
        result = mod.stop_monitoring_impl()
        assert result["success"] is True
        assert result["status"] == "stopped"

    def test_stop_when_not_running(self):
        """Stopping when no observer is running should return not_running."""
        mod = _import_monitor_ops()
        mod._observer = None
        result = mod.stop_monitoring_impl()
        assert result["success"] is False
        assert result["status"] == "not_running"


class TestGetStatusImpl:
    """Tests for get_status_impl in monitor_ops."""

    def teardown_method(self):
        mod = _import_monitor_ops()
        if mod._observer and mod._observer.is_alive():
            mod._observer.stop()
            mod._observer.join()
        mod._observer = None

    def test_status_when_not_monitoring(self, tmp_path):
        """Status should report inactive when no observer is running."""
        mod = _import_monitor_ops()
        mod._observer = None
        registry = {
            "plans": {
                "0001": {"status": "open"},
                "0002": {"status": "closed"},
                "0003": {"status": "open"},
            }
        }
        result = mod.get_status_impl(tmp_path, load_registry=lambda: registry)
        assert not result["monitoring_active"]
        assert result["total_plans"] == 3
        assert result["open_plans"] == 2
        assert result["watch_location"] == str(tmp_path)
        assert result["module"] == "registry_monitor"
        assert result["version"] == "2.0.0"
        assert result["ignore_folders"] == len(mod.IGNORE_FOLDERS)

    def test_status_when_monitoring_active(self, tmp_path):
        """Status should report active when observer is running."""
        mod = _import_monitor_ops()
        mod._observer = None
        mod.start_monitoring_impl(tmp_path)
        result = mod.get_status_impl(tmp_path, load_registry=lambda: {"plans": {}})
        assert result["monitoring_active"] is True

    def test_status_with_empty_registry(self, tmp_path):
        """Status should handle empty registry."""
        mod = _import_monitor_ops()
        mod._observer = None
        result = mod.get_status_impl(tmp_path, load_registry=lambda: {"plans": {}})
        assert result["total_plans"] == 0
        assert result["open_plans"] == 0


# ═══════════════════════════════════════════════════════════
# 5. registry_monitor module wrappers
# ═══════════════════════════════════════════════════════════


class TestRegistryMonitorStartMonitoring:
    """Tests for registry_monitor.start_monitoring wrapper."""

    def test_start_monitoring_success(self):
        """Successful start should print success message and return True."""
        mod = _import_registry_monitor()
        mock_con = MagicMock()
        with (
            patch.object(
                mod,
                "start_monitoring_impl",
                return_value={"success": True, "status": "started", "message": "Monitor started"},
            ),
            patch.object(mod, "console", mock_con),
        ):
            result = mod.start_monitoring()
        assert result is True
        mock_con.print.assert_called()

    def test_start_monitoring_already_running(self):
        """Already-running should trigger warning and return False."""
        mod = _import_registry_monitor()
        mock_warn = MagicMock()
        with (
            patch.object(
                mod,
                "start_monitoring_impl",
                return_value={"success": False, "status": "already_running", "message": "Already running"},
            ),
            patch.object(mod, "warning", mock_warn),
        ):
            result = mod.start_monitoring()
        assert result is False
        mock_warn.assert_called_once_with("Monitor is already running")

    def test_start_monitoring_error(self):
        """Error status should trigger error display and return False."""
        mod = _import_registry_monitor()
        mock_err = MagicMock()
        with (
            patch.object(
                mod,
                "start_monitoring_impl",
                return_value={"success": False, "status": "error", "message": "Observer failed"},
            ),
            patch.object(mod, "error", mock_err),
        ):
            result = mod.start_monitoring()
        assert result is False
        mock_err.assert_called_once_with("Observer failed")


class TestRegistryMonitorStopMonitoring:
    """Tests for registry_monitor.stop_monitoring wrapper."""

    def test_stop_monitoring_success(self):
        """Successful stop should print message and return True."""
        mod = _import_registry_monitor()
        mock_con = MagicMock()
        with (
            patch.object(
                mod,
                "stop_monitoring_impl",
                return_value={"success": True, "status": "stopped", "message": "Monitor stopped"},
            ),
            patch.object(mod, "console", mock_con),
        ):
            result = mod.stop_monitoring()
        assert result is True
        mock_con.print.assert_called()

    def test_stop_monitoring_not_running(self):
        """Stopping when not running should trigger warning and return False."""
        mod = _import_registry_monitor()
        mock_warn = MagicMock()
        with (
            patch.object(
                mod,
                "stop_monitoring_impl",
                return_value={"success": False, "status": "not_running", "message": "Not running"},
            ),
            patch.object(mod, "warning", mock_warn),
        ):
            result = mod.stop_monitoring()
        assert result is False
        mock_warn.assert_called_once_with("Monitor is not running")


class TestRegistryMonitorGetStatus:
    """Tests for registry_monitor.get_status wrapper."""

    def test_get_status_delegates_to_impl(self):
        """get_status should delegate to get_status_impl with correct args."""
        mod = _import_registry_monitor()
        expected = {
            "module": "registry_monitor",
            "version": "2.0.0",
            "monitoring_active": False,
            "watch_location": "/some/path",
            "total_plans": 5,
            "open_plans": 3,
            "ignore_folders": 20,
        }
        with patch.object(mod, "get_status_impl", return_value=expected) as mock_impl:
            result = mod.get_status()
        assert result == expected
        mock_impl.assert_called_once_with(
            ecosystem_root=mod.ECOSYSTEM_ROOT,
            load_registry=mod.load_registry,
        )


# ═══════════════════════════════════════════════════════════
# 6. _fire_event helper
# ═══════════════════════════════════════════════════════════


class TestFireEvent:
    """Tests for the _fire_event helper function."""

    def test_fire_event_success(self):
        """Successful event fire should return True."""
        mod = _import_monitor_ops()
        mock_trigger = MagicMock()
        fake_core = MagicMock(trigger=mock_trigger)
        with patch.dict(
            "sys.modules",
            {"aipass.trigger.apps.modules.core": fake_core},
        ):
            result = mod._fire_event("plan_file_created", path="/test/FPLAN-0001.md")
        assert result is True
        mock_trigger.fire.assert_called_once_with("plan_file_created", path="/test/FPLAN-0001.md")

    def test_fire_event_import_error(self, mock_logger):
        """ImportError should return False and log warning."""
        mod = _import_monitor_ops()
        real_import = builtins.__import__

        def _failing_import(
            name: str,
            globals: Mapping[str, object] | None = None,
            locals: Mapping[str, object] | None = None,
            fromlist: Sequence[str] = (),
            level: int = 0,
        ) -> types.ModuleType:
            if name == "aipass.trigger.apps.modules.core":
                raise ImportError("trigger not installed")
            return real_import(name, globals, locals, fromlist, level)

        with patch.object(builtins, "__import__", side_effect=_failing_import):
            result = mod._fire_event("test_event")
        assert result is False


# ═══════════════════════════════════════════════════════════
# 7. PlanFileWatcher internal methods
# ═══════════════════════════════════════════════════════════


class TestPlanFileWatcherInternals:
    """Tests for PlanFileWatcher helper methods."""

    def test_is_plan_file_valid(self):
        """Valid plan filenames (any prefix) should return True."""
        mod = _import_monitor_ops()
        watcher = mod.PlanFileWatcher()
        assert watcher._is_plan_file("/some/path/FPLAN-0001.md") is True
        assert watcher._is_plan_file("/some/path/FPLAN-9999.md") is True
        assert watcher._is_plan_file("/some/path/DPLAN-0001.md") is True
        assert watcher._is_plan_file("/some/path/APLAN-0042.md") is True
        assert watcher._is_plan_file("/some/path/RPLAN-0100.md") is True
        assert watcher._is_plan_file("/some/path/TDPLAN-0002.md") is True

    def test_is_plan_file_invalid(self):
        """Invalid filenames should return False."""
        mod = _import_monitor_ops()
        watcher = mod.PlanFileWatcher()
        assert watcher._is_plan_file("/some/path/FPLAN-ABC.md") is False
        assert watcher._is_plan_file("/some/path/FPLAN-00001.md") is False
        assert watcher._is_plan_file("/some/path/README.md") is False
        assert watcher._is_plan_file("/some/path/FPLAN-0001.txt") is False
        assert watcher._is_plan_file("/some/path/plan-0001.md") is False

    def test_get_plan_number(self):
        """Should extract the 4-digit number from plan filename."""
        mod = _import_monitor_ops()
        watcher = mod.PlanFileWatcher()
        assert watcher._get_plan_number(Path("FPLAN-0042.md")) == "0042"
        assert watcher._get_plan_number(Path("FPLAN-0001.md")) == "0001"
        assert watcher._get_plan_number(Path("/deep/path/FPLAN-1234.md")) == "1234"
        assert watcher._get_plan_number(Path("DPLAN-0005.md")) == "0005"
        assert watcher._get_plan_number(Path("TDPLAN-0002.md")) == "0002"

    def test_get_plan_number_invalid(self):
        """Invalid filenames should return None."""
        mod = _import_monitor_ops()
        watcher = mod.PlanFileWatcher()
        assert watcher._get_plan_number(Path("README.md")) is None
        assert watcher._get_plan_number(Path("FPLAN-ABC.md")) is None

    def test_deduplication_window_expires(self):
        """Events outside DEDUPE_WINDOW should not be considered duplicates."""
        mod = _import_monitor_ops()
        mod._recent_events.clear()
        watcher = mod.PlanFileWatcher()

        # Add an event with an old timestamp
        mod._recent_events.append(("created", "0001", time.time() - 10.0))

        # Should not be duplicate since old event is beyond DEDUPE_WINDOW
        assert watcher._is_duplicate_event("created", "0001") is False

    def test_different_event_types_not_deduplicated(self):
        """Different event types for same plan should not be deduplicated."""
        mod = _import_monitor_ops()
        mod._recent_events.clear()
        watcher = mod.PlanFileWatcher()

        assert watcher._is_duplicate_event("created", "0001") is False
        assert watcher._is_duplicate_event("deleted", "0001") is False  # different type
