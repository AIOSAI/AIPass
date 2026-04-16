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
"""

import json
import sys
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# handle_command tests
# ---------------------------------------------------------------------------


class TestHandleCommand:
    """Test the top-level command router."""

    def _import_monitor(self):
        """Import monitor module fresh (after conftest mocks are in place)."""
        # Additional mocks for monitoring handler imports
        with patch.dict(
            sys.modules,
            {
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
            },
        ):
            import importlib

            if "aipass.prax.apps.modules.monitor" in sys.modules:
                mod = importlib.reload(sys.modules["aipass.prax.apps.modules.monitor"])
            else:
                mod = importlib.import_module("aipass.prax.apps.modules.monitor")
            return mod

    def test_returns_false_for_non_monitor_command(self):
        """handle_command returns False for commands other than 'monitor'."""
        mod = self._import_monitor()
        assert mod.handle_command("status", []) is False

    def test_no_args_calls_print_introspection(self):
        """Bare 'monitor' with no args shows introspection and returns True."""
        mod = self._import_monitor()
        with patch.object(mod, "print_introspection") as mock_intro:
            result = mod.handle_command("monitor", [])
            assert result is True
            mock_intro.assert_called_once()

    def test_help_flag_calls_print_help(self):
        """--help flag shows help and returns True."""
        mod = self._import_monitor()
        for flag in ("--help", "-h", "help"):
            with patch.object(mod, "print_help") as mock_help:
                result = mod.handle_command("monitor", [flag])
                assert result is True
                mock_help.assert_called_once()

    def test_run_subcommand_calls_run_monitor(self):
        """'run' subcommand delegates to _run_monitor."""
        mod = self._import_monitor()
        with patch.object(mod, "_run_monitor", return_value=True) as mock_run:
            result = mod.handle_command("monitor", ["run"])
            assert result is True
            mock_run.assert_called_once_with([])

    def test_run_subcommand_passes_trailing_args(self):
        """Extra args after 'run' are forwarded to _run_monitor."""
        mod = self._import_monitor()
        with patch.object(mod, "_run_monitor", return_value=True) as mock_run:
            mod.handle_command("monitor", ["run", "seedgo,cli"])
            mock_run.assert_called_once_with(["seedgo,cli"])

    def test_unknown_subcommand_prints_error_and_help(self):
        """Unknown subcommand shows error + help, returns True."""
        mod = self._import_monitor()
        with patch.object(mod, "print_help") as mock_help:
            result = mod.handle_command("monitor", ["bogus"])
            assert result is True
            mock_help.assert_called_once()
            # error() is the CLI mock -- check that it was called
            mod.error.assert_called()


# ---------------------------------------------------------------------------
# _get_watch_directories tests
# ---------------------------------------------------------------------------


class TestGetWatchDirectories:
    """Test directory enumeration from registry."""

    def _import_monitor(self):
        with patch.dict(
            sys.modules,
            {
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
            },
        ):
            import importlib

            if "aipass.prax.apps.modules.monitor" in sys.modules:
                mod = importlib.reload(sys.modules["aipass.prax.apps.modules.monitor"])
            else:
                mod = importlib.import_module("aipass.prax.apps.modules.monitor")
            return mod

    def test_returns_empty_when_no_registry(self, tmp_path):
        """No AIPASS_REGISTRY.json -> empty list (no .claude/projects either)."""
        mod = self._import_monitor()
        with patch("pathlib.Path.home", return_value=tmp_path / "fakehome"):
            result = mod._get_watch_directories(tmp_path)
        assert result == []

    def test_includes_apps_and_trinity_dirs(self, tmp_path):
        """Registry with a branch that has apps/ and .trinity/ dirs."""
        mod = self._import_monitor()
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
        mod = self._import_monitor()
        registry = {"branches": [{"name": "ghost", "path": "src/aipass/ghost"}]}
        registry_file = tmp_path / "AIPASS_REGISTRY.json"
        registry_file.write_text(json.dumps(registry), encoding="utf-8")

        with patch("pathlib.Path.home", return_value=tmp_path / "fakehome"):
            result = mod._get_watch_directories(tmp_path)

        assert result == []

    def test_includes_claude_projects_when_exists(self, tmp_path):
        """~/.claude/projects is included when it exists."""
        mod = self._import_monitor()
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
        mod = self._import_monitor()
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
