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

    # (test_import_isolation.py) — a bare MagicMock has none, and any lazy

    # submodule import under it then dies with "is not a package".

    monitor_pkg.detector = mock_detector
    monitor_pkg.memory_watcher = mock_memory_watcher

    rollover_pkg = MagicMock()

    # (test_import_isolation.py) — a bare MagicMock has none, and any lazy

    # submodule import under it then dies with "is not a package".

    rollover_pkg.orchestrator = mock_orchestrator

    # help_flags and json_flag are pure argument inspection with no
    # dependencies — mocking them would only hide whether the routing guards
    # actually hold, so use the real ones.
    #
    # EVERY module the rollover module imports from this package has to be
    # listed here AND in sys.modules below. cli_pkg is a MagicMock, so the
    # package it stands in for has no __path__: `from ...cli.json_flag import
    # x` then resolves out of sys.modules or not at all. It resolved on a dev
    # machine only because some earlier test in the same process had already
    # imported the real one; on a fresh CI worker running this file first, all
    # 18 tests in this class died at import with "cli is not a package".
    import importlib

    real_help_flags = importlib.import_module("aipass.memory.apps.handlers.cli.help_flags")
    real_json_flag = importlib.import_module("aipass.memory.apps.handlers.cli.json_flag")
    cli_pkg = MagicMock()
    cli_pkg.help_flags = real_help_flags
    cli_pkg.json_flag = real_json_flag

    handlers_pkg = MagicMock()

    # (test_import_isolation.py) — a bare MagicMock has none, and any lazy

    # submodule import under it then dies with "is not a package".

    handlers_pkg.monitor = monitor_pkg
    handlers_pkg.rollover = rollover_pkg
    handlers_pkg.cli = cli_pkg

    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.cli", cli_pkg)
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.cli.help_flags", real_help_flags)
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.cli.json_flag", real_json_flag)
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
# Tests: the mocked cli package covers every submodule the code imports
# ===========================================================================


class TestMockedCliPackageIsComplete:
    """The fixture stands a MagicMock in for handlers.cli. A MagicMock has no
    __path__, so `from ...cli.<name> import x` can only resolve out of
    sys.modules -- and on a dev machine it resolves by accident, because some
    earlier test in the same process already imported the real one. On a fresh
    CI worker running this file first, it does not resolve at all.

    That is exactly how a `json_flag` import added on 08-16 turned all 18
    TestHandleCommand tests red on ubuntu while staying green here. This test
    reads rollover.py's own import lines, so the NEXT submodule added to that
    package fails here instead of on a runner three days later.
    """

    def _imported_cli_submodules(self):
        import re
        from pathlib import Path as _Path

        source = _Path(rollover_module_path()).read_text(encoding="utf-8")
        return set(re.findall(r"from aipass\.memory\.apps\.handlers\.cli\.(\w+) import", source))

    def test_at_least_one_is_imported(self, monkeypatch):
        """Guard the guard: a regex that matched nothing would assert nothing."""
        assert self._imported_cli_submodules()

    def test_every_imported_submodule_is_registered_real(self, monkeypatch):
        _import_rollover(monkeypatch)
        for name in self._imported_cli_submodules():
            key = f"aipass.memory.apps.handlers.cli.{name}"
            assert key in sys.modules, f"{key} imported by rollover.py but not registered by the fixture"
            assert not isinstance(sys.modules[key], MagicMock), f"{key} must be the real module, not a mock"

    def test_reimport_survives_a_cold_submodule_cache(self, monkeypatch):
        """Drop every cli submodule from the cache first -- the CI condition.

        Without the fixture registering them, this is the exact
        ModuleNotFoundError the runner reported.
        """
        for name in self._imported_cli_submodules():
            sys.modules.pop(f"aipass.memory.apps.handlers.cli.{name}", None)
        rollover, _mocks = _import_rollover(monkeypatch)
        assert rollover.handle_command("rollover", ["check"]) is True


def rollover_module_path():
    """Path to the rollover module's source, without importing it."""
    import importlib.util

    spec = importlib.util.find_spec("aipass.memory.apps.modules.rollover")
    return spec.origin


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

    def test_subcommands_has_report_lines(self, monkeypatch):
        """Renamed 2026-08-27 — `sync-lines` synced nothing after the health stamp went."""
        rollover, _ = _import_rollover(monkeypatch)
        assert "report-lines" in rollover._SUBCOMMANDS
        assert "sync-lines" not in rollover._SUBCOMMANDS
        assert rollover.RENAMED_VERBS["sync-lines"] == "report-lines"

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
# Tests: a help flag AFTER the subcommand must not execute the subcommand
# ===========================================================================


class TestSubcommandHelpFlag:
    """A trailing --help asks a question; it must never perform the action.

    The routing used to read help flags at args[0] only, so
    'rollover push --help' fired the system-wide per_branch reset — the
    dangerous direction for every write subcommand this module owns.
    """

    def test_push_help_does_not_push(self, monkeypatch):
        rollover, _ = _import_rollover(monkeypatch)
        with patch.object(rollover, "push_defaults") as pushed:
            assert rollover.handle_command("rollover", ["push", "--help"]) is True
        pushed.assert_not_called()

    def test_run_help_does_not_run_rollover(self, monkeypatch):
        rollover, _ = _import_rollover(monkeypatch)
        with patch.object(rollover, "run_rollover") as ran:
            assert rollover.handle_command("rollover", ["run", "--help"]) is True
        ran.assert_not_called()

    def test_report_lines_help_does_not_report(self, monkeypatch):
        rollover, _ = _import_rollover(monkeypatch)
        with patch.object(rollover, "report_line_counts") as reported:
            assert rollover.handle_command("rollover", ["report-lines", "-h"]) is True
        reported.assert_not_called()

    def test_the_retired_name_help_does_not_report_either(self, monkeypatch):
        """The rename must not smuggle a run past the help gate."""
        rollover, _ = _import_rollover(monkeypatch)
        with patch.object(rollover, "report_line_counts") as reported:
            assert rollover.handle_command("rollover", ["sync-lines", "-h"]) is True
        reported.assert_not_called()

    def test_check_help_prints_help_not_check(self, monkeypatch):
        rollover, _ = _import_rollover(monkeypatch)
        with patch.object(rollover, "check_triggers") as checked:
            with patch.object(rollover, "print_help") as helped:
                assert rollover.handle_command("rollover", ["check", "help"]) is True
        checked.assert_not_called()
        helped.assert_called_once()

    def test_help_flag_in_later_position_still_caught(self, monkeypatch):
        """The flag need not sit directly after the subcommand."""
        rollover, _ = _import_rollover(monkeypatch)
        with patch.object(rollover, "push_defaults") as pushed:
            assert rollover.handle_command("rollover", ["push", "--force", "--help"]) is True
        pushed.assert_not_called()

    def test_unknown_subcommand_with_help_prints_help(self, monkeypatch):
        """Help wins over the unknown-subcommand error — the user is asking."""
        rollover, _ = _import_rollover(monkeypatch)
        with patch.object(rollover, "print_help") as helped:
            assert rollover.handle_command("rollover", ["nonexistent", "--help"]) is True
        helped.assert_called_once()

    def test_subcommand_without_help_flag_still_executes(self, monkeypatch):
        """The guard must not swallow ordinary invocations."""
        rollover, _ = _import_rollover(monkeypatch)
        with patch.object(rollover, "check_triggers") as checked:
            assert rollover.handle_command("rollover", ["check"]) is True
        checked.assert_called_once()


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
