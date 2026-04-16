# ===================AIPASS====================
# META DATA HEADER
# Name: tests/test_rollover.py
# Date: 2026-03-24
# Version: 1.0.0
# Category: memory/tests
# =============================================

"""Tests for the rollover orchestration module.

Covers: from aipass.memory.apps.modules.rollover import handle_command

Tests command routing, handler discovery, and the SUBCOMMANDS dict.
All tests use mocks or tmp_path — no live filesystem or infrastructure access.
"""

import sys
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers: build the full mock graph that rollover.py needs at import time
# ---------------------------------------------------------------------------


def _prepare_rollover_mocks(monkeypatch):
    """Insert mocks for every module-level import rollover.py touches.

    Returns a dict of key mock objects so tests can assert against them.
    """
    # rich
    mock_panel = MagicMock()
    mock_box = MagicMock()
    rich_panel_mod = MagicMock()
    rich_panel_mod.Panel = mock_panel
    rich_box_mod = MagicMock()
    rich_box_mod.box = mock_box
    monkeypatch.setitem(sys.modules, "rich.panel", rich_panel_mod)
    monkeypatch.setitem(sys.modules, "rich", MagicMock())

    # aipass.cli console / error / warning
    mock_console = MagicMock()
    mock_error = MagicMock()
    mock_warning = MagicMock()
    cli_modules_mod = MagicMock()
    cli_modules_mod.console = mock_console
    cli_modules_mod.error = mock_error
    cli_modules_mod.warning = mock_warning
    monkeypatch.setitem(sys.modules, "aipass.cli", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.cli.apps", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.cli.apps.modules", cli_modules_mod)

    # aipass.memory handler sub-packages
    mock_detector = MagicMock()
    mock_detector.check_all_branches = MagicMock(return_value={"success": True, "triggers": []})
    mock_detector.get_rollover_stats = MagicMock(
        return_value={"success": True, "total_branches": 0, "files_checked": 0, "files_ready": 0, "branches": {}}
    )

    mock_orchestrator = MagicMock()
    mock_orchestrator.execute_rollover = MagicMock(return_value={"success": True, "triggers_count": 0})
    mock_orchestrator.sync_line_counts = MagicMock(return_value={"success": True, "updated": 0, "failed": 0})

    mock_memory_watcher = MagicMock()
    mock_memory_watcher.check_and_rollover = MagicMock()

    monitor_pkg = MagicMock()
    monitor_pkg.detector = mock_detector
    monitor_pkg.memory_watcher = mock_memory_watcher

    rollover_pkg = MagicMock()
    rollover_pkg.orchestrator = mock_orchestrator

    handlers_pkg = MagicMock()
    handlers_pkg.monitor = monitor_pkg
    handlers_pkg.rollover = rollover_pkg

    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers", handlers_pkg)
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.monitor", monitor_pkg)
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.monitor.detector", mock_detector)
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.monitor.memory_watcher", mock_memory_watcher)
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.rollover", rollover_pkg)
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.rollover.orchestrator", mock_orchestrator)

    # intake (lazy import inside process_plans_command)
    mock_plans_processor = MagicMock()
    mock_plans_processor.process_plans = MagicMock(
        return_value={"success": True, "files_processed": 0, "total_chunks": 0}
    )
    intake_pkg = MagicMock()
    intake_pkg.plans_processor = mock_plans_processor
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.intake", intake_pkg)
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.intake.plans_processor", mock_plans_processor)

    return {
        "console": mock_console,
        "error": mock_error,
        "warning": mock_warning,
        "detector": mock_detector,
        "orchestrator": mock_orchestrator,
        "memory_watcher": mock_memory_watcher,
        "plans_processor": mock_plans_processor,
    }


def _import_rollover(monkeypatch):
    """Prepare mocks and import (or reimport) the rollover module.

    Returns (rollover_module, mocks_dict).
    """
    mocks = _prepare_rollover_mocks(monkeypatch)

    # Remove cached module so it re-imports with our mocks
    sys.modules.pop("aipass.memory.apps.modules.rollover", None)

    # Also clear the parent package's cached attribute so Python
    # re-executes the module code with fresh mocks.
    parent = sys.modules.get("aipass.memory.apps.modules")
    if parent is not None and hasattr(parent, "rollover"):
        delattr(parent, "rollover")

    from aipass.memory.apps.modules import rollover

    return rollover, mocks


# ===========================================================================
# Tests: _SUBCOMMANDS dict
# ===========================================================================


class TestSubcommands:
    """Verify the _SUBCOMMANDS dict exists with expected keys."""

    def test_subcommands_exists(self, monkeypatch):
        rollover, _ = _import_rollover(monkeypatch)
        assert hasattr(rollover, "_SUBCOMMANDS")

    def test_subcommands_has_run(self, monkeypatch):
        rollover, _ = _import_rollover(monkeypatch)
        assert "run" in rollover._SUBCOMMANDS

    def test_subcommands_has_status(self, monkeypatch):
        rollover, _ = _import_rollover(monkeypatch)
        assert "status" in rollover._SUBCOMMANDS

    def test_subcommands_has_check(self, monkeypatch):
        rollover, _ = _import_rollover(monkeypatch)
        assert "check" in rollover._SUBCOMMANDS

    def test_subcommands_has_sync_lines(self, monkeypatch):
        rollover, _ = _import_rollover(monkeypatch)
        assert "sync-lines" in rollover._SUBCOMMANDS

    def test_subcommands_values_are_strings(self, monkeypatch):
        rollover, _ = _import_rollover(monkeypatch)
        for key, value in rollover._SUBCOMMANDS.items():
            assert isinstance(key, str), f"Key {key!r} is not a string"
            assert isinstance(value, str), f"Value for {key!r} is not a string"


# ===========================================================================
# Tests: handle_command routing
# ===========================================================================


class TestHandleCommand:
    """Verify handle_command routes subcommands correctly."""

    # -- rollover subcommands via 'rollover' command + args --

    def test_rollover_run_returns_true(self, monkeypatch):
        rollover, _ = _import_rollover(monkeypatch)
        assert rollover.handle_command("rollover", ["run"]) is True

    def test_rollover_status_returns_true(self, monkeypatch):
        rollover, _ = _import_rollover(monkeypatch)
        assert rollover.handle_command("rollover", ["status"]) is True

    def test_rollover_check_returns_true(self, monkeypatch):
        rollover, _ = _import_rollover(monkeypatch)
        assert rollover.handle_command("rollover", ["check"]) is True

    def test_rollover_sync_lines_returns_true(self, monkeypatch):
        rollover, _ = _import_rollover(monkeypatch)
        assert rollover.handle_command("rollover", ["sync-lines"]) is True

    def test_rollover_no_args_returns_true(self, monkeypatch):
        """No args triggers introspection, still returns True."""
        rollover, _ = _import_rollover(monkeypatch)
        assert rollover.handle_command("rollover", []) is True

    def test_rollover_help_returns_true(self, monkeypatch):
        rollover, _ = _import_rollover(monkeypatch)
        assert rollover.handle_command("rollover", ["--help"]) is True

    def test_rollover_h_flag_returns_true(self, monkeypatch):
        rollover, _ = _import_rollover(monkeypatch)
        assert rollover.handle_command("rollover", ["-h"]) is True

    def test_rollover_help_word_returns_true(self, monkeypatch):
        rollover, _ = _import_rollover(monkeypatch)
        assert rollover.handle_command("rollover", ["help"]) is True

    def test_rollover_unknown_subcommand_returns_true(self, monkeypatch):
        """Unknown subcommand still returns True (handled with error message)."""
        rollover, mocks = _import_rollover(monkeypatch)
        result = rollover.handle_command("rollover", ["nonexistent"])
        assert result is True
        mocks["error"].assert_called()

    # -- backward-compatible top-level commands --

    def test_toplevel_status_returns_true(self, monkeypatch):
        rollover, _ = _import_rollover(monkeypatch)
        assert rollover.handle_command("status", []) is True

    def test_toplevel_check_returns_true(self, monkeypatch):
        rollover, _ = _import_rollover(monkeypatch)
        assert rollover.handle_command("check", []) is True

    def test_toplevel_sync_lines_returns_true(self, monkeypatch):
        rollover, _ = _import_rollover(monkeypatch)
        assert rollover.handle_command("sync-lines", []) is True

    def test_toplevel_process_plans_returns_true(self, monkeypatch):
        rollover, _ = _import_rollover(monkeypatch)
        assert rollover.handle_command("process-plans", []) is True

    def test_toplevel_help_returns_true(self, monkeypatch):
        rollover, _ = _import_rollover(monkeypatch)
        assert rollover.handle_command("--help", []) is True

    def test_toplevel_h_returns_true(self, monkeypatch):
        rollover, _ = _import_rollover(monkeypatch)
        assert rollover.handle_command("-h", []) is True

    def test_toplevel_help_word_returns_true(self, monkeypatch):
        rollover, _ = _import_rollover(monkeypatch)
        assert rollover.handle_command("help", []) is True

    # -- unknown command returns False --

    def test_unknown_command_returns_false(self, monkeypatch):
        rollover, _ = _import_rollover(monkeypatch)
        assert rollover.handle_command("completely-unknown", []) is False

    def test_empty_string_command_returns_false(self, monkeypatch):
        rollover, _ = _import_rollover(monkeypatch)
        assert rollover.handle_command("", []) is False


# ===========================================================================
# Tests: _discover_handlers
# ===========================================================================


class TestDiscoverHandlers:
    """Verify _discover_handlers scans handler directories correctly."""

    def test_returns_empty_dict_when_no_handlers_dir(self, monkeypatch, tmp_path):
        """Returns empty dict when handlers/ directory does not exist."""
        rollover, _ = _import_rollover(monkeypatch)

        # Point __file__ at a location with no handlers/ sibling
        fake_module = tmp_path / "modules" / "rollover.py"
        fake_module.parent.mkdir(parents=True)
        fake_module.write_text("", encoding="utf-8")

        with patch.object(rollover, "__file__", str(fake_module)):
            result = rollover._discover_handlers()

        assert result == {}

    def test_discovers_py_files_in_handler_dirs(self, monkeypatch, tmp_path):
        """Discovers .py files inside handler subdirectories."""
        rollover, _ = _import_rollover(monkeypatch)

        # Build fake handler structure
        # modules/rollover.py -> parent.parent = apps -> handlers is sibling
        modules_dir = tmp_path / "apps" / "modules"
        modules_dir.mkdir(parents=True)
        fake_module = modules_dir / "rollover.py"
        fake_module.write_text("", encoding="utf-8")

        handlers_dir = tmp_path / "apps" / "handlers"
        handlers_dir.mkdir(parents=True)

        # Create handler dirs with .py files
        monitor_dir = handlers_dir / "monitor"
        monitor_dir.mkdir()
        (monitor_dir / "detector.py").write_text("", encoding="utf-8")
        (monitor_dir / "memory_watcher.py").write_text("", encoding="utf-8")
        (monitor_dir / "__init__.py").write_text("", encoding="utf-8")

        rollover_dir = handlers_dir / "rollover"
        rollover_dir.mkdir()
        (rollover_dir / "orchestrator.py").write_text("", encoding="utf-8")

        with patch.object(rollover, "__file__", str(fake_module)):
            result = rollover._discover_handlers()

        assert "monitor" in result
        assert "detector.py" in result["monitor"]
        assert "memory_watcher.py" in result["monitor"]
        # __init__.py should be excluded
        assert "__init__.py" not in result["monitor"]

        assert "rollover" in result
        assert "orchestrator.py" in result["rollover"]

    def test_excludes_pycache_directories(self, monkeypatch, tmp_path):
        """Directories starting with __ are excluded."""
        rollover, _ = _import_rollover(monkeypatch)

        modules_dir = tmp_path / "apps" / "modules"
        modules_dir.mkdir(parents=True)
        fake_module = modules_dir / "rollover.py"
        fake_module.write_text("", encoding="utf-8")

        handlers_dir = tmp_path / "apps" / "handlers"
        handlers_dir.mkdir(parents=True)

        pycache = handlers_dir / "__pycache__"
        pycache.mkdir()
        (pycache / "something.py").write_text("", encoding="utf-8")

        with patch.object(rollover, "__file__", str(fake_module)):
            result = rollover._discover_handlers()

        assert "__pycache__" not in result

    def test_excludes_empty_handler_dirs(self, monkeypatch, tmp_path):
        """Directories with no .py files (only __init__.py) are excluded."""
        rollover, _ = _import_rollover(monkeypatch)

        modules_dir = tmp_path / "apps" / "modules"
        modules_dir.mkdir(parents=True)
        fake_module = modules_dir / "rollover.py"
        fake_module.write_text("", encoding="utf-8")

        handlers_dir = tmp_path / "apps" / "handlers"
        empty_handler = handlers_dir / "empty_handler"
        empty_handler.mkdir(parents=True)
        (empty_handler / "__init__.py").write_text("", encoding="utf-8")

        with patch.object(rollover, "__file__", str(fake_module)):
            result = rollover._discover_handlers()

        assert "empty_handler" not in result

    def test_returns_sorted_keys_and_values(self, monkeypatch, tmp_path):
        """Handler dirs and their files are sorted alphabetically."""
        rollover, _ = _import_rollover(monkeypatch)

        modules_dir = tmp_path / "apps" / "modules"
        modules_dir.mkdir(parents=True)
        fake_module = modules_dir / "rollover.py"
        fake_module.write_text("", encoding="utf-8")

        handlers_dir = tmp_path / "apps" / "handlers"
        handlers_dir.mkdir(parents=True)

        # Create dirs in non-alphabetical order
        for name in ["zebra", "alpha"]:
            d = handlers_dir / name
            d.mkdir()
            (d / "b_file.py").write_text("", encoding="utf-8")
            (d / "a_file.py").write_text("", encoding="utf-8")

        with patch.object(rollover, "__file__", str(fake_module)):
            result = rollover._discover_handlers()

        keys = list(result.keys())
        assert keys == sorted(keys), "Handler directory keys should be sorted"

        for dir_name, files in result.items():
            assert files == sorted(files), f"Files in {dir_name} should be sorted"

    def test_ignores_non_py_files(self, monkeypatch, tmp_path):
        """Non-.py files in handler directories are excluded."""
        rollover, _ = _import_rollover(monkeypatch)

        modules_dir = tmp_path / "apps" / "modules"
        modules_dir.mkdir(parents=True)
        fake_module = modules_dir / "rollover.py"
        fake_module.write_text("", encoding="utf-8")

        handlers_dir = tmp_path / "apps" / "handlers"
        mixed_dir = handlers_dir / "mixed"
        mixed_dir.mkdir(parents=True)
        (mixed_dir / "handler.py").write_text("", encoding="utf-8")
        (mixed_dir / "README.md").write_text("", encoding="utf-8")
        (mixed_dir / "config.json").write_text("", encoding="utf-8")

        with patch.object(rollover, "__file__", str(fake_module)):
            result = rollover._discover_handlers()

        assert result["mixed"] == ["handler.py"]
