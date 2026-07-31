# =================== AIPass ====================
# Name: test_monitor_registry.py
# Description: Tests for monitor_ops handler and registry_monitor module
# Version: 2.0.0
# Created: 2026-03-08
# Modified: 2026-04-22
# =============================================

"""Tests for monitor_ops handler and registry_monitor module."""

import builtins
import os
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


# ═══════════════════════════════════════════════════════════
# 1. handle_walk_error
# ═══════════════════════════════════════════════════════════


class TestHandleWalkError:
    """Tests for the handle_walk_error inner function in scan_plan_files_impl."""

    def test_permission_error_is_silenced(self, tmp_path):
        """PermissionError should not trigger a warning log."""
        mod = _import_monitor_ops()
        with patch.object(mod, "_fire_event", return_value=False):
            restricted = tmp_path / "restricted"
            restricted.mkdir()
            _make_plan_file(tmp_path, "0001")

            os.chmod(str(restricted), 0o000)
            try:
                result = mod.scan_plan_files_impl(
                    ecosystem_root=tmp_path,
                    load_registry=lambda: {"plans": {}},
                )
                assert isinstance(result, dict)
                assert "total_plans" in result
            finally:
                os.chmod(str(restricted), 0o755)

    def test_generic_os_error_logs_warning(self, tmp_path, mock_logger):
        """Non-PermissionError OSError should be logged as warning."""
        mod = _import_monitor_ops()
        missing = tmp_path / "nonexistent_root"
        with patch.object(mod, "_fire_event", return_value=False):
            result = mod.scan_plan_files_impl(
                ecosystem_root=missing,
                load_registry=lambda: {"plans": {}},
            )
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
        _make_plan_file(tmp_path, "0001")
        (tmp_path / "DPLAN-0002.md").write_text("also a plan", encoding="utf-8")
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
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        _make_plan_file(git_dir, "0001")

        pycache_dir = tmp_path / "__pycache__"
        pycache_dir.mkdir()
        _make_plan_file(pycache_dir, "0002")

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

    def test_detects_plan_files_with_slug_and_date_suffix(self, tmp_path):
        """Real plan filenames carry a subject slug + date suffix and must still match."""
        mod = _import_monitor_ops()
        (tmp_path / "FPLAN-0001_some_subject_slug_2026-07-27.md").write_text("plan", encoding="utf-8")

        with patch.object(mod, "_fire_event", return_value=True):
            result = mod.scan_plan_files_impl(
                ecosystem_root=tmp_path,
                load_registry=lambda: {"plans": {}},
            )
        assert "0001" in result["added"]

    def test_ignored_folder_requires_exact_name_match(self, tmp_path):
        """Substring matches (e.g. 'dev' in 'devpulse') must not skip unrelated directories."""
        mod = _import_monitor_ops()
        lookalike_dir = tmp_path / "devpulse"
        lookalike_dir.mkdir()
        _make_plan_file(lookalike_dir, "0001")

        with patch.object(mod, "_fire_event", return_value=True):
            result = mod.scan_plan_files_impl(
                ecosystem_root=tmp_path,
                load_registry=lambda: {"plans": {}},
            )
        assert "0001" in result["added"]

    def test_dropbox_folder_is_ignored(self, tmp_path):
        """dropbox/ is a received-files inbox -- old snapshot copies must never register."""
        mod = _import_monitor_ops()
        dropbox_dir = tmp_path / "dropbox"
        dropbox_dir.mkdir()
        _make_plan_file(dropbox_dir, "0001")

        good_dir = tmp_path / "active"
        good_dir.mkdir()
        _make_plan_file(good_dir, "0002")

        with patch.object(mod, "_fire_event", return_value=True):
            result = mod.scan_plan_files_impl(
                ecosystem_root=tmp_path,
                load_registry=lambda: {"plans": {}},
            )
        assert "0001" not in result["added"]
        assert "0002" in result["added"]

    def test_dropbox_ignore_requires_exact_name_match(self, tmp_path):
        """Lookalike names (e.g. 'dropbox-clone') must not be skipped -- exact match only."""
        mod = _import_monitor_ops()
        lookalike_dir = tmp_path / "dropbox-clone"
        lookalike_dir.mkdir()
        _make_plan_file(lookalike_dir, "0001")

        with patch.object(mod, "_fire_event", return_value=True):
            result = mod.scan_plan_files_impl(
                ecosystem_root=tmp_path,
                load_registry=lambda: {"plans": {}},
            )
        assert "0001" in result["added"]

    def test_orphaned_closed_plan_does_not_fire_deleted(self, tmp_path):
        """Closed plans are expected to be archived out of the scan tree — not orphans."""
        mod = _import_monitor_ops()
        registry = {
            "plans": {
                "0001": {"file_path": str(tmp_path / "FPLAN-0001.md"), "status": "closed"},
                "0002": {"file_path": str(tmp_path / "FPLAN-0002.md"), "status": "open"},
            }
        }
        with patch.object(mod, "_fire_event", return_value=True):
            result = mod.scan_plan_files_impl(
                ecosystem_root=tmp_path,
                load_registry=lambda: registry,
            )
        assert "0001" not in result["removed"]
        assert "0002" in result["removed"]

    def test_detects_orphaned_registry_entries(self, tmp_path):
        """Registry entries with no matching file should fire deleted events."""
        mod = _import_monitor_ops()
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
# 3. get_status_impl
# ═══════════════════════════════════════════════════════════


class TestGetStatusImpl:
    """Tests for get_status_impl in monitor_ops."""

    def test_status_returns_correct_fields(self, tmp_path):
        """Status should return all expected fields."""
        mod = _import_monitor_ops()
        registry = {
            "plans": {
                "0001": {"status": "open"},
                "0002": {"status": "closed"},
                "0003": {"status": "open"},
            }
        }
        result = mod.get_status_impl(tmp_path, load_registry=lambda: registry)
        assert result["monitoring_active"] is False
        assert result["total_plans"] == 3
        assert result["open_plans"] == 2
        assert result["watch_location"] == str(tmp_path)
        assert result["module"] == "registry_monitor"
        assert result["version"] == "2.0.0"
        assert result["ignore_folders"] == len(mod.IGNORE_FOLDERS)

    def test_status_with_empty_registry(self, tmp_path):
        """Status should handle empty registry."""
        mod = _import_monitor_ops()
        result = mod.get_status_impl(tmp_path, load_registry=lambda: {"plans": {}})
        assert result["total_plans"] == 0
        assert result["open_plans"] == 0


# ═══════════════════════════════════════════════════════════
# 4. registry_monitor module wrappers
# ═══════════════════════════════════════════════════════════


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
# 5. _fire_event helper
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
