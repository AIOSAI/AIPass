# ===================AIPASS====================
# META DATA HEADER
# Name: tests/test_rollover.py
# Date: 2026-03-24
# Version: 1.1.2
# Modified: 2026-09-15
# Category: memory/tests
# =============================================

"""Tests for the rollover orchestration module.

Covers: from aipass.memory.apps.modules.rollover import handle_command

Tests command routing, handler discovery, and the SUBCOMMANDS dict.
All tests use mocks or tmp_path — no live filesystem or infrastructure access.
"""

import importlib
import sys
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers: build the full mock graph that rollover.py needs at import time
# ---------------------------------------------------------------------------


def _prepare_rollover_mocks(monkeypatch):
    """Insert mocks for every module-level import rollover.py touches.

    Returns a dict of key mock objects so tests can assert against them.
    """
    # FIRST LINE OF THE FIXTURE, before a single mock reaches sys.modules.
    # The `config` verbs live in modules/rollover_config.py and `_Json`,
    # `_emit` and `_refuse` in modules/rollover_json.py; rollover.py re-exports
    # both sets. BOTH modules must be first-imported against the REAL
    # aipass.cli, because whatever `console` and `error` each binds at import
    # time it keeps FOREVER — the module stays cached long after teardown
    # restores sys.modules. Standing below the cli stand-in was enough to hand
    # 191 of test_config_verbs.py's tests a MagicMock console that printed
    # nothing, in serial order only: --dist loadscope split the files across
    # workers and CI never saw it.
    real_rollover_config = importlib.import_module("aipass.memory.apps.modules.rollover_config")
    real_rollover_json = importlib.import_module("aipass.memory.apps.modules.rollover_json")

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
    real_help_flags = importlib.import_module("aipass.memory.apps.handlers.cli.help_flags")
    real_json_flag = importlib.import_module("aipass.memory.apps.handlers.cli.json_flag")
    real_branch_flag = importlib.import_module("aipass.memory.apps.handlers.cli.branch_flag")

    cli_pkg = MagicMock()
    cli_pkg.help_flags = real_help_flags
    cli_pkg.json_flag = real_json_flag
    cli_pkg.branch_flag = real_branch_flag

    # The todo-pad reports resolve a branch and read a pad: stubbed to the
    # honest "nothing resolved" line so routing tests never touch a real pad.
    mock_todo_report = MagicMock()
    no_branch = {"level": "line", "text": "Todos: no branch resolved (harness) - no todo pad checked"}
    mock_todo_report.check_pad = MagicMock(return_value=no_branch)
    mock_todo_report.roll_pad = MagicMock(return_value=no_branch)
    rollover_pkg.todo_report = mock_todo_report

    handlers_pkg = MagicMock()

    # (test_import_isolation.py) — a bare MagicMock has none, and any lazy

    # submodule import under it then dies with "is not a package".

    handlers_pkg.monitor = monitor_pkg
    handlers_pkg.rollover = rollover_pkg
    handlers_pkg.cli = cli_pkg

    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.cli", cli_pkg)
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.cli.help_flags", real_help_flags)
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.cli.json_flag", real_json_flag)
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.cli.branch_flag", real_branch_flag)
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.rollover.todo_report", mock_todo_report)
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers", handlers_pkg)
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.monitor", monitor_pkg)
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.monitor.detector", mock_detector)
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.monitor.memory_watcher", mock_memory_watcher)
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.rollover", rollover_pkg)
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.rollover.orchestrator", mock_orchestrator)
    # Patched attribute by attribute rather than through the sys.modules
    # stand-in, because `_refuse` reads `error` from ITS OWN globals - without
    # these three the mock error() the tests assert on is never called.
    # monkeypatch restores each one.
    monkeypatch.setattr(real_rollover_config, "console", mock_console)
    monkeypatch.setattr(real_rollover_config, "error", mock_error)
    monkeypatch.setattr(real_rollover_config, "detector", mock_detector)
    # And the same two on rollover_json, which is where `_emit` reads `console`
    # and `_refuse` reads `error` now — a patch on rollover_config no longer
    # reaches either of them. No `detector` there: that module never took one.
    monkeypatch.setattr(real_rollover_json, "console", mock_console)
    monkeypatch.setattr(real_rollover_json, "error", mock_error)

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
        "todo_report": mock_todo_report,
    }


_ROLLOVER_MODULE = "aipass.memory.apps.modules.rollover"


def _import_rollover(monkeypatch):
    """Prepare mocks and import (or reimport) the rollover module.

    The re-import binds rollover to the MagicMock cli, so its error() marks
    nothing. Both evictions go through monkeypatch, which records what stood
    there - the real module, or nothing - and teardown puts exactly that back.
    A bare pop left the mock-bound module cached after teardown: the next
    in-process memory.main() on that xdist worker routed `rollover <bogus>`
    through the mock error() and exited 0 (test_contracts, macOS red on
    02610e3b and 561678fd).

    Returns (rollover_module, mocks_dict).
    """
    mocks = _prepare_rollover_mocks(monkeypatch)

    # setitem first so teardown knows the prior state, then evict so the
    # import below re-executes the module against the mocks.
    monkeypatch.setitem(sys.modules, _ROLLOVER_MODULE, None)
    del sys.modules[_ROLLOVER_MODULE]

    # The parent package's cached attribute, the same way: `from package
    # import rollover` would otherwise hand back the cached module unexecuted.
    parent = importlib.import_module("aipass.memory.apps.modules")
    monkeypatch.setattr(parent, "rollover", None, raising=False)
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
        imported = self._imported_cli_submodules()
        assert imported == {"help_flags", "json_flag", "branch_flag"}, (
            f"rollover.py's cli submodule imports moved to {sorted(imported)} — an empty or "
            "shrunken set would make the loop below register nothing and still read green"
        )
        for name in imported:
            key = f"aipass.memory.apps.handlers.cli.{name}"
            assert key in sys.modules, f"{key} imported by rollover.py but not registered by the fixture"
            assert not isinstance(sys.modules[key], MagicMock), f"{key} must be the real module, not a mock"

    def test_reimport_survives_a_cold_submodule_cache(self, monkeypatch):
        """Drop every cli submodule from the cache first -- the CI condition.

        Without the fixture registering them, this is the exact
        ModuleNotFoundError the runner reported. The drop is recorded first,
        the way _import_rollover evicts: the fixture re-imports each one, and
        a bare pop left those new help_flags / json_flag / branch_flag objects
        cached and named by the cli package after teardown.
        """
        cli = importlib.import_module("aipass.memory.apps.handlers.cli")
        for name in sorted(self._imported_cli_submodules()):
            key = f"aipass.memory.apps.handlers.cli.{name}"
            monkeypatch.setitem(sys.modules, key, None)
            del sys.modules[key]
            monkeypatch.setattr(cli, name, None, raising=False)
            delattr(cli, name)
        rollover, _mocks = _import_rollover(monkeypatch)
        assert rollover.handle_command("rollover", ["check"]) is True


class TestMockedReimportIsUndoneAtTeardown:
    """The rollover module this file binds to a MagicMock cli must not outlive the test that made it.

    It did, through a bare sys.modules.pop: test_contracts' in-process
    memory.main() later on the same xdist worker discovered the cached module,
    its mock error() marked no failure, and `rollover <bogus>` exited 0
    instead of 2 - red on macOS only, where loadscope's size-ordered queue
    ran this file's classes first on that worker.
    """

    def test_sys_modules_and_the_parent_attribute_are_restored(self) -> None:
        parent = importlib.import_module("aipass.memory.apps.modules")
        module_before = sys.modules.get(_ROLLOVER_MODULE)
        attr_before = getattr(parent, "rollover", None)

        with pytest.MonkeyPatch.context() as mp:
            rollover, mocks = _import_rollover(mp)
            # Guard the guard: the re-import really is bound to the mock.
            assert rollover.error is mocks["error"]
            assert rollover is not module_before

        assert sys.modules.get(_ROLLOVER_MODULE) is module_before, "the mock-bound rollover outlived its test"
        assert getattr(parent, "rollover", None) is attr_before, (
            "the parent package still names the mock-bound rollover"
        )

    def test_the_cold_cache_test_puts_the_cli_submodules_back(self) -> None:
        """The cold-cache test re-imports help_flags, json_flag and branch_flag; teardown must undo it.

        A bare sys.modules.pop there left the re-imported objects cached and on
        the cli package after teardown (seedgo's runtime plugin, 2026-09-15).
        """
        cold = TestMockedCliPackageIsComplete()
        names = sorted(cold._imported_cli_submodules())
        assert names == ["branch_flag", "help_flags", "json_flag"], names
        keys = {name: f"aipass.memory.apps.handlers.cli.{name}" for name in names}
        cli = importlib.import_module("aipass.memory.apps.handlers.cli")
        modules_before = {name: importlib.import_module(key) for name, key in keys.items()}
        attrs_before = {name: getattr(cli, name, None) for name in names}

        with pytest.MonkeyPatch.context() as mp:
            cold.test_reimport_survives_a_cold_submodule_cache(mp)
            # Guard the guard: the body really minted new module objects.
            reimported = [name for name, key in keys.items() if sys.modules[key] is not modules_before[name]]
            assert reimported == names, f"only {reimported} were re-imported"

        leaked = [name for name, key in keys.items() if sys.modules.get(key) is not modules_before[name]]
        renamed = [name for name in names if getattr(cli, name, None) is not attrs_before[name]]
        assert leaked == [], f"the re-imported {leaked} outlived the cold-cache test in sys.modules"
        assert renamed == [], f"the cli package still names the re-imported {renamed}"


def rollover_module_path() -> str:
    """Path to the rollover module's source, without importing it."""
    import importlib.util

    spec = importlib.util.find_spec("aipass.memory.apps.modules.rollover")
    assert spec is not None and spec.origin is not None, "aipass.memory.apps.modules.rollover has no source"
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

    def test_subcommands_are_the_published_five_with_one_line_help(self, monkeypatch):
        """The map IS the help surface, so its keys and its text both count.

        Was an isinstance sweep: it passed for an empty map and for a map whose
        every description had been replaced by the empty string. The verbs are
        named here so a silent removal is red, and the text is required to be a
        non-empty single line because `--help` prints one row per entry.
        """
        rollover, _ = _import_rollover(monkeypatch)
        assert set(rollover._SUBCOMMANDS) == {"run", "status", "check", "report-lines", "push"}
        for key, value in rollover._SUBCOMMANDS.items():
            assert value.strip(), f"{key} has no description — --help would print a bare verb"
            assert "\n" not in value, f"{key}'s description spans lines and would break the help table"


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
