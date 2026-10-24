# =================== AIPass ====================
# Name: tests/test_rollover.py
# Description: Tests for the rollover module's command routing and SUBCOMMANDS
# Version: 1.2.0
# Created: 2026-03-24
# Modified: 2026-10-23
# Category: memory/tests
# =============================================

"""Tests for apps/modules/rollover.py."""

# Covers: from aipass.memory.apps.modules.rollover import handle_command

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(covered_elsewhere) — execute_rollover behind run_rollover, in tests/test_orchestrator_exec.py
# seedgo: no-test-needed(covered_elsewhere) — the rollover_config verbs re-exported here, in tests/test_config_verbs.py
# seedgo: no-test-needed(covered_elsewhere) — check_all_branches behind check_triggers, in tests/test_detector.py

import importlib
import sys
from unittest.mock import MagicMock, patch

import pytest

from aipass.memory.apps.modules import rollover as rollover_module


def _prepare_rollover_mocks(monkeypatch):
    """Insert mocks for every module-level import rollover.py touches."""
    # Must run before any mock reaches sys.modules: both modules keep forever the
    # `console`/`error` they bind at first import, so they must bind the REAL aipass.cli.
    real_rollover_config = importlib.import_module("aipass.memory.apps.modules.rollover_config")
    real_rollover_json = importlib.import_module("aipass.memory.apps.modules.rollover_json")

    # error() is replaced on each module that bound it: the real one marks the process's command failed.
    mock_error = MagicMock()
    mock_warning = MagicMock()

    mock_detector = MagicMock()
    mock_detector.check_all_branches = MagicMock(return_value={"success": True, "triggers": []})
    mock_detector.get_rollover_stats = MagicMock(
        return_value={"success": True, "total_branches": 0, "files_checked": 0, "files_ready": 0, "branches": {}}
    )

    mock_orchestrator = MagicMock()
    mock_orchestrator.execute_rollover = MagicMock(return_value={"success": True, "triggers_count": 0})

    mock_memory_watcher = MagicMock()
    mock_memory_watcher.check_and_rollover = MagicMock()

    monitor_pkg = MagicMock()
    monitor_pkg.detector = mock_detector
    monitor_pkg.memory_watcher = mock_memory_watcher

    rollover_pkg = MagicMock()
    rollover_pkg.orchestrator = mock_orchestrator

    # Real flag helpers so the routing guards are real. Every cli submodule rollover.py imports must be
    # listed here AND in sys.modules below: cli_pkg has no __path__, so the import resolves only from there.
    real_help_flags = importlib.import_module("aipass.memory.apps.handlers.cli.help_flags")
    real_json_flag = importlib.import_module("aipass.memory.apps.handlers.cli.json_flag")
    real_branch_flag = importlib.import_module("aipass.memory.apps.handlers.cli.branch_flag")

    cli_pkg = MagicMock()
    cli_pkg.help_flags = real_help_flags
    cli_pkg.json_flag = real_json_flag
    cli_pkg.branch_flag = real_branch_flag

    # Stubbed to the "nothing resolved" line so routing tests never touch a real pad.
    mock_todo_report = MagicMock()
    no_branch = {"level": "line", "text": "Todos: no branch resolved (harness) - no todo pad checked"}
    mock_todo_report.check_pad = MagicMock(return_value=no_branch)
    mock_todo_report.roll_pad = MagicMock(return_value=no_branch)
    rollover_pkg.todo_report = mock_todo_report

    handlers_pkg = MagicMock()
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
    # Patched on the module itself: `_refuse` reads `error` from its own globals, not the stand-in.
    monkeypatch.setattr(real_rollover_config, "error", mock_error)
    monkeypatch.setattr(real_rollover_config, "detector", mock_detector)
    monkeypatch.setattr(real_rollover_json, "error", mock_error)

    # intake is a lazy import inside process_plans_command.
    mock_plans_processor = MagicMock()
    mock_plans_processor.process_plans = MagicMock(
        return_value={"success": True, "files_processed": 0, "total_chunks": 0}
    )
    intake_pkg = MagicMock()
    intake_pkg.plans_processor = mock_plans_processor
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.intake", intake_pkg)
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.intake.plans_processor", mock_plans_processor)

    return {
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
    """Prepare mocks and re-import rollover; evictions go through monkeypatch so teardown restores the cache."""
    mocks = _prepare_rollover_mocks(monkeypatch)

    # setitem first so teardown knows the prior state; a bare pop leaks the mock-bound module.
    monkeypatch.setitem(sys.modules, _ROLLOVER_MODULE, None)
    del sys.modules[_ROLLOVER_MODULE]

    # Else `from package import rollover` hands back the cached module unexecuted.
    parent = importlib.import_module("aipass.memory.apps.modules")
    monkeypatch.setattr(parent, "rollover", None, raising=False)
    delattr(parent, "rollover")

    from aipass.memory.apps.modules import rollover

    monkeypatch.setattr(rollover, "error", mocks["error"])
    monkeypatch.setattr(rollover, "warning", mocks["warning"])

    return rollover, mocks


class TestMockedCliPackageIsComplete:
    """Every cli submodule rollover.py imports must be registered real: the MagicMock cli has no __path__."""

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
        """Drop every cli submodule from the cache first (a fresh CI worker); the fixture must still resolve them."""
        cli = importlib.import_module("aipass.memory.apps.handlers.cli")
        for name in sorted(self._imported_cli_submodules()):
            key = f"aipass.memory.apps.handlers.cli.{name}"
            monkeypatch.setitem(sys.modules, key, None)
            del sys.modules[key]
            monkeypatch.setattr(cli, name, None, raising=False)
            delattr(cli, name)
        rollover, _mocks = _import_rollover(monkeypatch)
        calls = _record(monkeypatch, rollover, "check_triggers")
        assert rollover.handle_command("rollover", ["check"]) is True
        assert calls == [((None,), {})], "the re-imported module did not route `check`"


class TestMockedReimportIsUndoneAtTeardown:
    """The rollover module this file binds to a MagicMock cli must not outlive the test that made it."""

    def test_sys_modules_and_the_parent_attribute_are_restored(self) -> None:
        parent = importlib.import_module("aipass.memory.apps.modules")
        module_before = sys.modules.get(_ROLLOVER_MODULE)
        attr_before = getattr(parent, "rollover", None)

        with pytest.MonkeyPatch.context() as mp:
            rollover, mocks = _import_rollover(mp)
            assert rollover.error is mocks["error"]
            assert rollover is not module_before

        assert sys.modules.get(_ROLLOVER_MODULE) is module_before, "the mock-bound rollover outlived its test"
        assert getattr(parent, "rollover", None) is attr_before, (
            "the parent package still names the mock-bound rollover"
        )

    def test_the_cold_cache_test_puts_the_cli_submodules_back(self) -> None:
        """The cold-cache test re-imports help_flags, json_flag and branch_flag; teardown must undo it."""
        cold = TestMockedCliPackageIsComplete()
        names = sorted(cold._imported_cli_submodules())
        assert names == ["branch_flag", "help_flags", "json_flag"], names
        keys = {name: f"aipass.memory.apps.handlers.cli.{name}" for name in names}
        cli = importlib.import_module("aipass.memory.apps.handlers.cli")
        modules_before = {name: importlib.import_module(key) for name, key in keys.items()}
        attrs_before = {name: getattr(cli, name, None) for name in names}

        with pytest.MonkeyPatch.context() as mp:
            cold.test_reimport_survives_a_cold_submodule_cache(mp)
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


class TestSubcommands:
    """Verify the _SUBCOMMANDS dict exists with expected keys."""

    def test_subcommands_exists(self, monkeypatch):
        rollover, _ = _import_rollover(monkeypatch)
        assert hasattr(rollover, "_SUBCOMMANDS")

    def test_subcommands_has_run(self, monkeypatch):
        rollover, _ = _import_rollover(monkeypatch)
        assert "run" in rollover.SUBCOMMANDS

    def test_subcommands_has_status(self, monkeypatch):
        rollover, _ = _import_rollover(monkeypatch)
        assert "status" in rollover.SUBCOMMANDS

    def test_subcommands_has_check(self, monkeypatch):
        rollover, _ = _import_rollover(monkeypatch)
        assert "check" in rollover.SUBCOMMANDS

    def test_subcommands_are_the_published_four_with_one_line_help(self, monkeypatch):
        """The map IS the help surface: the four verbs are named, each with a non-empty one-line text."""
        rollover, _ = _import_rollover(monkeypatch)
        assert set(rollover.SUBCOMMANDS) == {"run", "status", "check", "push"}
        for key, value in rollover.SUBCOMMANDS.items():
            assert value.strip(), f"{key} has no description — --help would print a bare verb"
            assert "\n" not in value, f"{key}'s description spans lines and would break the help table"


def _record(monkeypatch, module, name):
    """Stand a recorder in for one of rollover's own verbs; the route is the claim, not the verb's work."""
    calls = []
    monkeypatch.setattr(module, name, lambda *a, **k: calls.append((a, k)))
    return calls


class TestHandleCommand:
    """Verify handle_command routes subcommands correctly."""

    def test_rollover_run_returns_true(self, monkeypatch):
        rollover, _ = _import_rollover(monkeypatch)
        calls = _record(monkeypatch, rollover, "run_rollover")
        assert rollover.handle_command("rollover", ["run"]) is True
        assert calls == [((None,), {})]

    def test_rollover_status_returns_true(self, monkeypatch):
        rollover, _ = _import_rollover(monkeypatch)
        calls = _record(monkeypatch, rollover, "show_status")
        assert rollover.handle_command("rollover", ["status"]) is True
        assert calls == [((), {})]

    def test_rollover_check_returns_true(self, monkeypatch):
        rollover, _ = _import_rollover(monkeypatch)
        calls = _record(monkeypatch, rollover, "check_triggers")
        assert rollover.handle_command("rollover", ["check"]) is True
        assert calls == [((None,), {})]

    def test_rollover_no_args_returns_true(self, monkeypatch):
        """No args triggers introspection, still returns True."""
        rollover, _ = _import_rollover(monkeypatch)
        calls = _record(monkeypatch, rollover, "print_introspection")
        assert rollover.handle_command("rollover", []) is True
        assert calls == [((), {})]

    def test_rollover_help_returns_true(self, monkeypatch):
        rollover, _ = _import_rollover(monkeypatch)
        calls = _record(monkeypatch, rollover, "print_help")
        assert rollover.handle_command("rollover", ["--help"]) is True
        assert calls == [((), {})]

    def test_rollover_h_flag_returns_true(self, monkeypatch):
        rollover, _ = _import_rollover(monkeypatch)
        calls = _record(monkeypatch, rollover, "print_help")
        assert rollover.handle_command("rollover", ["-h"]) is True
        assert calls == [((), {})]

    def test_rollover_help_word_returns_true(self, monkeypatch):
        rollover, _ = _import_rollover(monkeypatch)
        calls = _record(monkeypatch, rollover, "print_help")
        assert rollover.handle_command("rollover", ["help"]) is True
        assert calls == [((), {})]

    def test_rollover_unknown_subcommand_returns_true(self, monkeypatch):
        """Unknown subcommand still returns True (handled with error message)."""
        rollover, mocks = _import_rollover(monkeypatch)
        result = rollover.handle_command("rollover", ["nonexistent"])
        assert result is True
        mocks["error"].assert_called()

    def test_toplevel_status_returns_true(self, monkeypatch):
        rollover, _ = _import_rollover(monkeypatch)
        calls = _record(monkeypatch, rollover, "show_status")
        assert rollover.handle_command("status", []) is True
        assert calls == [((), {})]

    def test_toplevel_check_returns_true(self, monkeypatch):
        rollover, _ = _import_rollover(monkeypatch)
        calls = _record(monkeypatch, rollover, "check_triggers")
        assert rollover.handle_command("check", []) is True
        assert calls == [((None,), {})]

    def test_toplevel_process_plans_returns_true(self, monkeypatch):
        rollover, _ = _import_rollover(monkeypatch)
        calls = _record(monkeypatch, rollover, "process_plans_command")
        assert rollover.handle_command("process-plans", []) is True
        assert calls == [((), {})]

    def test_toplevel_help_returns_true(self, monkeypatch):
        rollover, _ = _import_rollover(monkeypatch)
        calls = _record(monkeypatch, rollover, "print_help")
        assert rollover.handle_command("--help", []) is True
        assert calls == [((), {})]

    def test_toplevel_h_returns_true(self, monkeypatch):
        rollover, _ = _import_rollover(monkeypatch)
        calls = _record(monkeypatch, rollover, "print_help")
        assert rollover.handle_command("-h", []) is True
        assert calls == [((), {})]

    def test_toplevel_help_word_returns_true(self, monkeypatch):
        rollover, _ = _import_rollover(monkeypatch)
        calls = _record(monkeypatch, rollover, "print_help")
        assert rollover.handle_command("help", []) is True
        assert calls == [((), {})]

    def test_unknown_command_returns_false(self, monkeypatch):
        rollover, _ = _import_rollover(monkeypatch)
        assert rollover.handle_command("completely-unknown", []) is False

    def test_empty_string_command_returns_false(self, monkeypatch):
        rollover, _ = _import_rollover(monkeypatch)
        assert rollover.handle_command("", []) is False


class TestSubcommandHelpFlag:
    """A trailing --help asks a question; it must never perform the action (push would reset the fleet)."""

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


class TestDiscoverHandlers:
    """Verify the handler walk, read through its one caller: the introspection screen."""

    @staticmethod
    def _connected(capsys) -> tuple[dict[str, list[str]], list[str]]:
        """The "Connected Handlers" block of the screen: the map it shows, and its raw lines."""
        rollover_module.print_introspection()
        lines = [line.strip() for line in capsys.readouterr().out.splitlines()]
        block = lines[lines.index("Connected Handlers:") + 1 :]
        block = block[: block.index("")]
        shown = {}
        for line in block:
            if line == "No handlers found":
                continue
            directory, _, files = line.partition("  ")
            shown[directory.removeprefix("handlers/").rstrip("/")] = files.strip().split(", ") if files.strip() else []
        return shown, block

    def test_returns_empty_dict_when_no_handlers_dir(self, monkeypatch, tmp_path, capsys):
        """Returns empty dict when handlers/ directory does not exist."""
        fake_module = tmp_path / "modules" / "rollover.py"
        fake_module.parent.mkdir(parents=True)
        fake_module.write_text("", encoding="utf-8")

        monkeypatch.setattr(rollover_module, "__file__", str(fake_module))
        result, block = self._connected(capsys)

        assert result == {}
        assert block == ["No handlers found"]

    def test_discovers_py_files_in_handler_dirs(self, monkeypatch, tmp_path, capsys):
        """Discovers .py files inside handler subdirectories."""
        modules_dir = tmp_path / "apps" / "modules"
        modules_dir.mkdir(parents=True)
        fake_module = modules_dir / "rollover.py"
        fake_module.write_text("", encoding="utf-8")

        handlers_dir = tmp_path / "apps" / "handlers"
        handlers_dir.mkdir(parents=True)

        monitor_dir = handlers_dir / "monitor"
        monitor_dir.mkdir()
        (monitor_dir / "detector.py").write_text("", encoding="utf-8")
        (monitor_dir / "memory_watcher.py").write_text("", encoding="utf-8")
        (monitor_dir / "__init__.py").write_text("", encoding="utf-8")

        rollover_dir = handlers_dir / "rollover"
        rollover_dir.mkdir()
        (rollover_dir / "orchestrator.py").write_text("", encoding="utf-8")

        monkeypatch.setattr(rollover_module, "__file__", str(fake_module))
        result, _ = self._connected(capsys)

        assert "monitor" in result
        assert "detector.py" in result["monitor"]
        assert "memory_watcher.py" in result["monitor"]
        assert "__init__.py" not in result["monitor"]

        assert "rollover" in result
        assert "orchestrator.py" in result["rollover"]

    def test_excludes_pycache_directories(self, monkeypatch, tmp_path, capsys):
        """Directories starting with __ are excluded."""
        modules_dir = tmp_path / "apps" / "modules"
        modules_dir.mkdir(parents=True)
        fake_module = modules_dir / "rollover.py"
        fake_module.write_text("", encoding="utf-8")

        handlers_dir = tmp_path / "apps" / "handlers"
        handlers_dir.mkdir(parents=True)

        pycache = handlers_dir / "__pycache__"
        pycache.mkdir()
        (pycache / "something.py").write_text("", encoding="utf-8")

        monkeypatch.setattr(rollover_module, "__file__", str(fake_module))
        result, _ = self._connected(capsys)

        assert "__pycache__" not in result

    def test_excludes_empty_handler_dirs(self, monkeypatch, tmp_path, capsys):
        """Directories with no .py files (only __init__.py) are excluded."""
        modules_dir = tmp_path / "apps" / "modules"
        modules_dir.mkdir(parents=True)
        fake_module = modules_dir / "rollover.py"
        fake_module.write_text("", encoding="utf-8")

        handlers_dir = tmp_path / "apps" / "handlers"
        empty_handler = handlers_dir / "empty_handler"
        empty_handler.mkdir(parents=True)
        (empty_handler / "__init__.py").write_text("", encoding="utf-8")

        monkeypatch.setattr(rollover_module, "__file__", str(fake_module))
        result, _ = self._connected(capsys)

        assert "empty_handler" not in result

    def test_returns_sorted_keys_and_values(self, monkeypatch, tmp_path, capsys):
        """Handler dirs and their files are sorted alphabetically."""
        modules_dir = tmp_path / "apps" / "modules"
        modules_dir.mkdir(parents=True)
        fake_module = modules_dir / "rollover.py"
        fake_module.write_text("", encoding="utf-8")

        handlers_dir = tmp_path / "apps" / "handlers"
        handlers_dir.mkdir(parents=True)

        for name in ["zebra", "alpha"]:
            d = handlers_dir / name
            d.mkdir()
            (d / "b_file.py").write_text("", encoding="utf-8")
            (d / "a_file.py").write_text("", encoding="utf-8")

        monkeypatch.setattr(rollover_module, "__file__", str(fake_module))
        result, _ = self._connected(capsys)

        keys = list(result.keys())
        assert keys == sorted(keys), "Handler directory keys should be sorted"

        for dir_name, files in result.items():
            assert files == sorted(files), f"Files in {dir_name} should be sorted"

    def test_ignores_non_py_files(self, monkeypatch, tmp_path, capsys):
        """Non-.py files in handler directories are excluded."""
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

        monkeypatch.setattr(rollover_module, "__file__", str(fake_module))
        result, _ = self._connected(capsys)

        assert result["mixed"] == ["handler.py"]
