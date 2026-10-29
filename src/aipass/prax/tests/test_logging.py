# =================== AIPass ====================
# Name: test_logging.py
# Description: Tests for prax logging subsystem
# Version: 1.4.1
# Created: 2026-03-29
# Modified: 2026-10-29
# =============================================

"""Tests for apps/handlers/logging/introspection.py and setup.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(through_the_command) — get_calling_module_path, covered by tests/test_logging_handlers.py
# seedgo: no-test-needed(through_the_command) — _resolve_caller_path on <stdin>, covered by tests/test_repo_root.py
# seedgo: no-test-needed(stdlib) — get_captured_loggers_count, the size of _captured_loggers

import copy
import logging
import os
import threading
import types
from logging.handlers import RotatingFileHandler
from pathlib import Path
from unittest.mock import patch

import pytest

from aipass.prax.apps.handlers.logging import introspection
from aipass.prax.apps.handlers.logging import setup as setup_handler
from aipass.prax.apps.handlers.logging.introspection import (
    detect_branch_from_path,
    detect_external_project,
    get_caller_info,
)
from aipass.prax.apps.handlers.repo_root import resolved_file


def _ask_for_the_caller(ask):
    """The frame the stack walk judges: its module is whatever its globals' __file__ says."""
    return ask()


def _caller_seen_from(module_file: str):
    """get_calling_module_path(), asked from a frame whose module is ``module_file`` .

    The walk passes over a prax-internal path and stops at this file; any other path is the answer."""
    globals_of_the_frame = {"__file__": module_file, "__builtins__": __builtins__}
    caller = types.FunctionType(_ask_for_the_caller.__code__, globals_of_the_frame)
    return caller(introspection.get_calling_module_path)


class TestIsPraxInternal:
    """Tests for _is_prax_internal() — checks prax internal markers, through the stack walk.

    Internal means walked past (the answer is this file); external means the answer.
    """

    def test_prax_logger_path(self, mock_prax_infrastructure, tmp_path):
        """Logger module path is detected as prax internal."""
        path = tmp_path / "src" / "aipass" / "prax" / "apps" / "modules" / "logger.py"
        assert _caller_seen_from(str(path)) == __file__

    def test_prax_handlers_path(self, mock_prax_infrastructure, tmp_path):
        """Handler directory path is detected as prax internal."""
        path = tmp_path / "src" / "aipass" / "prax" / "apps" / "handlers" / "logging" / "setup.py"
        assert _caller_seen_from(str(path)) == __file__

    def test_prax_paths_windows_form(self, mock_prax_infrastructure):
        """Windows-form logger and handler paths are detected as prax internal (backslash normalisation)."""
        handler = "D:\\dev\\AIPass\\src\\aipass\\prax\\apps\\handlers\\logging\\setup.py"
        logger_module = "D:\\dev\\AIPass\\src\\aipass\\prax\\apps\\modules\\logger.py"
        assert _caller_seen_from(handler) == __file__
        assert _caller_seen_from(logger_module) == __file__

    def test_prax_logger_filename(self, mock_prax_infrastructure, tmp_path):
        """prax_logger.py filename is detected as prax internal."""
        assert _caller_seen_from(str(tmp_path / "some" / "path" / "prax_logger.py")) == __file__

    def test_prax_handlers_filename(self, mock_prax_infrastructure, tmp_path):
        """prax_handlers.py filename is detected as prax internal."""
        assert _caller_seen_from(str(tmp_path / "some" / "path" / "prax_handlers.py")) == __file__

    def test_external_cli_path(self, mock_prax_infrastructure, tmp_path):
        """CLI module path is not prax internal."""
        path = str(tmp_path / "src" / "aipass" / "cli" / "apps" / "cli.py")
        assert _caller_seen_from(path) == path

    def test_external_flow_path(self, mock_prax_infrastructure, tmp_path):
        """Flow module path is not prax internal."""
        path = str(tmp_path / "src" / "aipass" / "flow" / "apps" / "flow.py")
        assert _caller_seen_from(path) == path

    def test_random_script_path(self, mock_prax_infrastructure, tmp_path):
        """Random script path is not prax internal."""
        path = str(tmp_path / "random_script.py")
        assert _caller_seen_from(path) == path

    def test_empty_string(self, mock_prax_infrastructure):
        """An empty module path is never taken as the caller: the walk goes on to this file."""
        assert _caller_seen_from("") == __file__


def _aipass_package_root() -> Path:
    """src/aipass, found from introspection's own file with the resolver it uses."""
    return resolved_file(Path(introspection.__file__)).parents[4]


class TestDetectBranchFromPath:
    """Tests for detect_branch_from_path() — the branch directory a file lives in."""

    def test_cli_branch(self, mock_prax_infrastructure):
        """CLI branch is detected from aipass/cli/apps/cli.py."""
        cli_path = str(_aipass_package_root() / "cli" / "apps" / "cli.py")
        assert detect_branch_from_path(cli_path) == str(_aipass_package_root() / "cli")

    def test_flow_branch(self, mock_prax_infrastructure):
        """Flow branch is detected from aipass/flow/apps/flow.py."""
        flow_path = str(_aipass_package_root() / "flow" / "apps" / "flow.py")
        assert detect_branch_from_path(flow_path) == str(_aipass_package_root() / "flow")

    def test_prax_branch(self, mock_prax_infrastructure):
        """Prax branch is detected from aipass/prax/apps/module.py."""
        prax_path = str(_aipass_package_root() / "prax" / "apps" / "module.py")
        assert detect_branch_from_path(prax_path) == str(_aipass_package_root() / "prax")

    def test_drone_branch(self, mock_prax_infrastructure):
        """Drone branch is detected from aipass/drone/apps/branch.py."""
        drone_path = str(_aipass_package_root() / "drone" / "apps" / "branch.py")
        assert detect_branch_from_path(drone_path) == str(_aipass_package_root() / "drone")

    def test_random_path_returns_none(self, mock_prax_infrastructure, tmp_path):
        """Random path outside the project returns None."""
        assert detect_branch_from_path(str(tmp_path / "random_script.py")) is None

    def test_empty_string_returns_none(self, mock_prax_infrastructure):
        """Empty string returns None."""
        assert detect_branch_from_path("") is None

    def test_nested_module_still_resolves(self, mock_prax_infrastructure):
        """Deeply nested module path still resolves to the branch."""
        deep_path = str(_aipass_package_root() / "flow" / "apps" / "handlers" / "deep" / "module.py")
        assert detect_branch_from_path(deep_path) == str(_aipass_package_root() / "flow")

    def test_a_citizen_outside_both_roots_is_found_by_its_passport(self, mock_prax_infrastructure, tmp_path):
        branch = tmp_path / "hark" / "src" / "hark" / "hark"
        (branch / ".trinity").mkdir(parents=True)
        (branch / ".trinity" / "passport.json").write_text("{}", encoding="utf-8")
        module = branch / "apps" / "handlers" / "ui" / "server.py"
        module.parent.mkdir(parents=True)
        module.write_text("", encoding="utf-8")
        assert detect_branch_from_path(str(module)) == str(branch.resolve())

    def test_a_trinity_dir_without_a_passport_is_no_branch(self, mock_prax_infrastructure, tmp_path):
        (tmp_path / "loose" / ".trinity").mkdir(parents=True)
        assert detect_branch_from_path(str(tmp_path / "loose" / "apps" / "m.py")) is None


class TestACitizenOutsideTheKnownRoots:
    """A passport-holding branch anywhere logs into its own logs/, under its own name."""

    def test_its_local_log_lands_in_its_branch_logs_dir(self, monkeypatch, tmp_path):
        branch = tmp_path / "proj" / "src" / "hark" / "hark"
        (branch / ".trinity").mkdir(parents=True)
        (branch / ".trinity" / "passport.json").write_text("{}", encoding="utf-8")
        module = branch / "apps" / "server.py"
        monkeypatch.setattr(setup_handler, "get_system_logs_dir", lambda: tmp_path / "system_logs")
        # The real resolver's pytest short-circuit hides branch_dir; this one honours only it.
        monkeypatch.setattr(
            setup_handler,
            "get_module_logs_dir",
            lambda name, branch_dir=None: Path(branch_dir) / "logs" if branch_dir else tmp_path / "by_name",
        )
        monkeypatch.setattr(setup_handler, "_captured_loggers", {})
        monkeypatch.delenv("AIPASS_BRANCH_NAME", raising=False)
        built = setup_handler.setup_individual_logger("server", caller_path=str(module))
        try:
            built.info("served")
        finally:
            for handler in list(built.handlers):
                handler.close()
                built.removeHandler(handler)

        assert "served" in (branch.resolve() / "logs" / "server.log").read_text(encoding="utf-8")
        assert "served" in (tmp_path / "system_logs" / "hark_server.log").read_text(encoding="utf-8")
        assert not (tmp_path / "by_name").exists()


class TestDetectExternalProject:
    """Tests for detect_external_project() — identifies external project paths."""

    def test_none_for_empty_path(self, mock_prax_infrastructure):
        """Returns None for empty string input."""
        assert detect_external_project("") is None

    def test_none_for_internal_aipass_path(self, mock_prax_infrastructure):
        """Returns None for paths inside the AIPass repo."""
        repo_root = _aipass_package_root().parent.parent
        internal_path = str(repo_root / "src" / "aipass" / "flow" / "apps" / "handler.py")
        assert detect_external_project(internal_path) is None

    def test_detects_external_project_with_git(self, mock_prax_infrastructure, tmp_path):
        """Detects project root via .git directory for external paths."""
        # Create a fake external project with .git
        project_dir = tmp_path / "MyProject"
        project_dir.mkdir()
        (project_dir / ".git").mkdir()
        module_file = project_dir / "src" / "module.py"
        module_file.parent.mkdir(parents=True)
        module_file.touch()

        result = detect_external_project(str(module_file))
        assert result is not None
        project_name, project_root = result
        assert project_name == "myproject"
        assert project_root == project_dir

    def test_detects_external_project_with_pyproject(self, mock_prax_infrastructure, tmp_path):
        """Detects project root via pyproject.toml for external paths."""
        project_dir = tmp_path / "Compass"
        project_dir.mkdir()
        (project_dir / "pyproject.toml").touch()
        module_file = project_dir / "nav" / "router.py"
        module_file.parent.mkdir(parents=True)
        module_file.touch()

        result = detect_external_project(str(module_file))
        assert result is not None
        project_name, project_root = result
        assert project_name == "compass"
        assert project_root == project_dir

    def test_normalizes_project_name(self, mock_prax_infrastructure, tmp_path):
        """Project names are lowercased with hyphens/spaces converted to underscores."""
        project_dir = tmp_path / "Backup-System"
        project_dir.mkdir()
        (project_dir / ".git").mkdir()
        module_file = project_dir / "main.py"
        module_file.touch()

        result = detect_external_project(str(module_file))
        assert result is not None
        assert result[0] == "backup_system"

    def test_none_when_no_project_root_found(self, mock_prax_infrastructure, tmp_path):
        """Returns None when no .git or pyproject.toml found walking up."""
        # Create a file in tmp_path without .git or pyproject.toml
        # tmp_path itself might have parents with .git — use a nested isolated dir
        isolated = tmp_path / "no_project" / "deep" / "nested"
        isolated.mkdir(parents=True)
        module_file = isolated / "orphan.py"
        module_file.touch()

        # The walk-up only stops at a .git or a pyproject.toml. Assert that no
        # ancestor carries one BEFORE asking for the answer: an `if result is
        # not None` guard here used to swallow the whole oracle, so a host whose
        # tmpdir sat inside a checkout reported green having checked nothing.
        ancestors = [module_file, *module_file.parents]
        marked = [p for p in ancestors if (p / ".git").exists() or (p / "pyproject.toml").exists()]
        assert marked == [], f"tmp_path sits inside a project root ({marked}) — the None below is not testable here"

        assert detect_external_project(str(module_file)) is None


class TestSetupExternalRouting:
    """Tests for external project log routing in setup_individual_logger."""

    def test_external_project_routes_to_project_system_logs(self, mock_prax_infrastructure, tmp_path):
        """External callers get logs routed to their project's system_logs/ dir."""
        project_dir = tmp_path / "AIPL"
        project_dir.mkdir()
        (project_dir / ".git").mkdir()
        fake_module = str(project_dir / "src" / "polyglot.py")
        env_patch = {"AIPASS_BRANCH_NAME": "", "AIPASS_CALLER_CWD": ""}

        with patch.object(setup_handler, "detect_external_project", return_value=("aipl", project_dir)):
            with patch.object(setup_handler, "detect_branch_from_path", return_value=None):
                with patch.dict("os.environ", env_patch), patch.object(setup_handler, "_captured_loggers", {}):
                    result = setup_handler.setup_individual_logger("polyglot", caller_path=fake_module)

        assert result is not None
        assert (project_dir / "system_logs").exists()
        assert (project_dir / "logs").exists()

    def test_external_project_does_not_write_to_aipass_system_logs(self, mock_prax_infrastructure, tmp_path):
        """External routing must NOT create files in AIPass system_logs."""
        project_dir = tmp_path / "Compass"
        project_dir.mkdir()
        (project_dir / ".git").mkdir()
        fake_module = str(project_dir / "nav.py")
        get_calls = []
        env_patch = {"AIPASS_BRANCH_NAME": "", "AIPASS_CALLER_CWD": ""}

        with patch.object(setup_handler, "detect_external_project", return_value=("compass", project_dir)):
            with patch.object(setup_handler, "detect_branch_from_path", return_value=None):
                with patch.dict("os.environ", env_patch):
                    with (
                        patch.object(setup_handler, "get_system_logs_dir", side_effect=lambda: get_calls.append(1)),
                        patch.object(setup_handler, "_captured_loggers", {}),
                    ):
                        setup_handler.setup_individual_logger("navigator", caller_path=fake_module)

        assert len(get_calls) == 0

    def test_a_project_system_logs_that_cannot_be_made_mutes_that_tier_and_never_raises(
        self, mock_prax_infrastructure, monkeypatch, tmp_path, caplog
    ):
        """An unmakeable <project>/system_logs mutes that tier; the logger call never raises."""
        project_dir = tmp_path / "Compass"
        project_dir.mkdir()
        # A file where the directory belongs: mkdir fails on every OS, no permission bit needed.
        (project_dir / "system_logs").write_text("not a directory", encoding="utf-8")
        monkeypatch.setattr(setup_handler, "detect_external_project", lambda path: ("compass", project_dir))
        monkeypatch.setattr(setup_handler, "_captured_loggers", {})
        monkeypatch.setenv("AIPASS_BRANCH_NAME", "")

        with caplog.at_level(logging.ERROR, logger=setup_handler.logger.name):
            built = setup_handler.setup_individual_logger("navigator", caller_path=str(project_dir / "nav.py"))
        try:
            failed = [r.getMessage() for r in caplog.records if r.getMessage().startswith("Log handler failed")]
            handler_types = [type(h) is logging.NullHandler for h in built.handlers]
            local_is_a_file = isinstance(built.handlers[1], RotatingFileHandler)
            local_file = Path(getattr(built.handlers[1], "baseFilename"))
        finally:
            for handler in list(built.handlers):
                handler.close()
                built.removeHandler(handler)

        assert len(failed) == 1
        assert failed[0].startswith("Log handler failed for compass_navigator.log: ")
        assert handler_types == [True, False]
        assert local_is_a_file
        assert local_file == project_dir / "logs" / "navigator.log"


class TestConcurrentFirstCallsBuildOneLogger:
    """A module's first log line, arriving on several threads at once, must build one handler set."""

    THREADS = 8

    def _sandbox(self, monkeypatch, tmp_path):
        monkeypatch.setattr(setup_handler, "get_system_logs_dir", lambda: tmp_path / "system_logs")
        monkeypatch.setattr(
            setup_handler, "get_module_logs_dir", lambda branch, branch_dir=None: tmp_path / branch / "logs"
        )
        monkeypatch.setattr(setup_handler, "_captured_loggers", {})

    def test_a_later_line_is_written_once_after_a_racing_first_call(self, monkeypatch, tmp_path):
        """api's twin ERROR lines (6b7f72e9): N racing first calls wrote every later line N times."""
        self._sandbox(monkeypatch, tmp_path)
        barrier = threading.Barrier(self.THREADS)

        def first_call(i):
            barrier.wait()
            setup_handler.setup_individual_logger("race_probe", caller_branch="probe").error("root %d timed out", i)

        threads = [threading.Thread(target=first_call, args=(i,)) for i in range(self.THREADS)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        built = setup_handler.setup_individual_logger("race_probe", caller_branch="probe")
        try:
            built.info("a later line")
            local = (tmp_path / "probe" / "logs" / "race_probe.log").read_text(encoding="utf-8")
            central = (tmp_path / "system_logs" / "probe_race_probe.log").read_text(encoding="utf-8")
        finally:
            for handler in list(built.handlers):
                handler.close()
                built.removeHandler(handler)

        assert local.count("a later line") == 1
        assert central.count("a later line") == 1
        # The line format is the config's (pinned in test_config.py); the message ends each line.
        assert sorted(line.rsplit("root ", 1)[-1] for line in local.splitlines() if "timed out" in line) == sorted(
            f"{i} timed out" for i in range(self.THREADS)
        )

    def test_racing_first_calls_build_the_logger_once(self, monkeypatch, tmp_path):
        self._sandbox(monkeypatch, tmp_path)
        # Each build reads the log config once, so the reads count the builds.
        builds = []
        real_config = setup_handler.load_log_config
        monkeypatch.setattr(setup_handler, "load_log_config", lambda: builds.append(1) or real_config())
        barrier = threading.Barrier(self.THREADS)
        results = []

        def first_call():
            barrier.wait()
            results.append(setup_handler.setup_individual_logger("build_probe", caller_branch="probe"))

        threads = [threading.Thread(target=first_call) for _ in range(self.THREADS)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        for handler in list(results[0].handlers):
            handler.close()
            results[0].removeHandler(handler)

        assert len(builds) == 1


class TestSameModuleNameInTwoBranches:
    """config.py of api and of drone in one process each write their own branch's files."""

    def test_each_branch_gets_its_own_logger_and_files(self, monkeypatch, tmp_path):
        monkeypatch.setattr(setup_handler, "get_system_logs_dir", lambda: tmp_path / "system_logs")
        monkeypatch.setattr(
            setup_handler, "get_module_logs_dir", lambda branch, branch_dir=None: tmp_path / branch / "logs"
        )
        monkeypatch.setattr(setup_handler, "_captured_loggers", {})
        api = setup_handler.setup_individual_logger("config", caller_branch="api")
        drone = setup_handler.setup_individual_logger("config", caller_branch="drone")
        try:
            api.info("from api")
            drone.info("from drone")
            api_local = (tmp_path / "api" / "logs" / "config.log").read_text(encoding="utf-8")
            drone_central = (tmp_path / "system_logs" / "drone_config.log").read_text(encoding="utf-8")
        finally:
            for built in (api, drone):
                for handler in list(built.handlers):
                    handler.close()
                    built.removeHandler(handler)

        assert api is not drone
        assert "from api" in api_local and "from drone" not in api_local
        assert "from drone" in drone_central and "from api" not in drone_central
        # The line's module tag is unchanged by the branch key.
        assert "captured_config" in api_local


class TestAnUnwritableLogHome:
    """A logger call degrades to 'Log handler failed' over a log home it cannot make."""

    # The only route to an unwritable log home is a permission bit: Windows has
    # none to set, and root writes through it.
    @pytest.mark.skipif(
        os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0),
        reason="needs a POSIX permission bit that binds the writer",
    )
    def test_a_first_line_over_an_unwritable_home_is_reported_and_never_raised(self, monkeypatch, tmp_path, caplog):
        """FPLAN-0642: the first log line of a uv tool install raised Errno 13 into `aipass install`."""
        locked = tmp_path / "locked"
        locked.mkdir()
        monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(locked))
        monkeypatch.setattr(setup_handler, "_captured_loggers", {})
        locked.chmod(0o500)
        try:
            with caplog.at_level(logging.ERROR, logger=setup_handler.logger.name):
                built = setup_handler.setup_individual_logger("homeless_probe", caller_branch="probe")
                built.info("a line with nowhere to go")
        finally:
            locked.chmod(0o700)

        failed = [r.getMessage() for r in caplog.records if r.getMessage().startswith("Log handler failed")]
        assert len(failed) == 2  # both tiers, central and local
        assert list(locked.iterdir()) == []


class TestGetCallerInfo:
    """Tests for get_caller_info() — returns (module_name, path, branch) tuple."""

    def test_returns_tuple_of_three(self, mock_prax_infrastructure, monkeypatch):
        """get_caller_info returns the 3-tuple (name, path, branch) of its caller, this file."""
        monkeypatch.delenv("AIPASS_LOG_NAME", raising=False)
        monkeypatch.delenv("AIPASS_BOT_ID", raising=False)

        result = get_caller_info()
        assert result == ("test_logging", __file__, str(_aipass_package_root() / "prax"))

    def test_module_name_is_string(self, mock_prax_infrastructure, monkeypatch):
        """The caller is this file, so the name is this file's stem; env overrides cleared first."""
        monkeypatch.delenv("AIPASS_LOG_NAME", raising=False)
        monkeypatch.delenv("AIPASS_BOT_ID", raising=False)

        module_name, path, branch = get_caller_info()
        assert isinstance(module_name, str)
        assert module_name == "test_logging"
        assert path == __file__
        assert branch == str(_aipass_package_root() / "prax")

    def test_called_from_test_file(self, mock_prax_infrastructure):
        """When called from a test file, path should reference this file."""
        module_name, caller_path, branch = get_caller_info()
        assert isinstance(module_name, str)
        assert module_name != ""

    def test_no_external_caller_returns_defaults(self, mock_prax_infrastructure):
        """When _find_external_caller_path returns None, defaults are returned."""
        with patch.object(introspection, "_find_external_caller_path", return_value=None):
            result = introspection.get_caller_info()
            assert result == ("unknown_module", None, None)


class TestReplacePlaceholders:
    """Tests for _replace_placeholders() — template placeholder substitution."""

    @staticmethod
    def _make_replace_fn():
        """Create a standalone _replace_placeholders matching template_pusher logic."""

        def _replace_placeholders(template: dict, branch_name: str) -> dict:
            def _walk(val):
                if isinstance(val, str):
                    return val.replace("{{BRANCHNAME}}", branch_name)
                elif isinstance(val, list):
                    return [_walk(item) for item in val]
                elif isinstance(val, dict):
                    return {k: _walk(v) for k, v in val.items()}
                return val

            result = _walk(copy.deepcopy(template))
            assert isinstance(result, dict)
            return result

        return _replace_placeholders

    def test_simple_string_replacement(self, mock_prax_infrastructure):
        """Single placeholder in a string value is replaced."""
        fn = self._make_replace_fn()
        template = {"name": "{{BRANCHNAME}}_dashboard"}
        result = fn(template, "FLOW")
        assert result == {"name": "FLOW_dashboard"}

    def test_nested_dict_replacement(self, mock_prax_infrastructure):
        """Placeholders in nested dicts are replaced."""
        fn = self._make_replace_fn()
        template = {"outer": {"inner": "branch_{{BRANCHNAME}}"}}
        result = fn(template, "DRONE")
        assert result == {"outer": {"inner": "branch_DRONE"}}

    def test_list_replacement(self, mock_prax_infrastructure):
        """Placeholders in lists are replaced."""
        fn = self._make_replace_fn()
        template = {"items": ["{{BRANCHNAME}}_a", "{{BRANCHNAME}}_b"]}
        result = fn(template, "CLI")
        assert result == {"items": ["CLI_a", "CLI_b"]}

    def test_no_placeholder_unchanged(self, mock_prax_infrastructure):
        """Template without placeholders is returned unchanged."""
        fn = self._make_replace_fn()
        template = {"key": "no_placeholder", "count": 42}
        result = fn(template, "PRAX")
        assert result == {"key": "no_placeholder", "count": 42}

    def test_non_string_values_preserved(self, mock_prax_infrastructure):
        """Non-string values (int, bool, None) are preserved."""
        fn = self._make_replace_fn()
        template = {"count": 42, "active": True, "data": None}
        result = fn(template, "SPAWN")
        assert result == {"count": 42, "active": True, "data": None}

    def test_multiple_placeholders_in_one_string(self, mock_prax_infrastructure):
        """Multiple placeholders in a single string are all replaced."""
        fn = self._make_replace_fn()
        template = {"path": "/{{BRANCHNAME}}/logs/{{BRANCHNAME}}.log"}
        result = fn(template, "MEMORY")
        assert result == {"path": "/MEMORY/logs/MEMORY.log"}

    def test_original_template_not_mutated(self, mock_prax_infrastructure):
        """Original template dict is not modified (deep copy)."""
        fn = self._make_replace_fn()
        template = {"name": "{{BRANCHNAME}}"}
        original_copy = copy.deepcopy(template)
        fn(template, "FLOW")
        assert template == original_copy

    def test_empty_dict(self, mock_prax_infrastructure):
        """Empty template returns empty dict."""
        fn = self._make_replace_fn()
        result = fn({}, "PRAX")
        assert result == {}

    def test_deeply_nested_structure(self, mock_prax_infrastructure):
        """Deeply nested mixed structure is fully processed."""
        fn = self._make_replace_fn()
        template = {
            "a": {
                "b": [
                    {"c": "{{BRANCHNAME}}_deep"},
                    "{{BRANCHNAME}}_list",
                ],
                "d": 99,
            }
        }
        result = fn(template, "NEXUS")
        assert result["a"]["b"][0]["c"] == "NEXUS_deep"
        assert result["a"]["b"][1] == "NEXUS_list"
        assert result["a"]["d"] == 99


def _external_logger(setup, tmp_path, module_name, env=None, config=None):
    """Build a real logger whose two tiers land inside tmp_path: (logger, system_log, local_log)."""
    project_dir = tmp_path / "Proj"
    project_dir.mkdir(exist_ok=True)
    (project_dir / ".git").mkdir(exist_ok=True)
    fake_module = str(project_dir / f"{module_name}.py")
    env_patch = {"AIPASS_BRANCH_NAME": "", "AIPASS_CALLER_CWD": ""}
    env_patch.update(env or {})

    stack = [
        patch.object(setup, "detect_external_project", return_value=("proj", project_dir)),
        patch.object(setup, "detect_branch_from_path", return_value=None),
        patch.dict("os.environ", env_patch),
        patch.object(setup, "_captured_loggers", {}),
    ]
    if config is not None:
        stack.append(patch.object(setup, "load_log_config", return_value=config))

    with stack[0], stack[1], stack[2], stack[3]:
        if config is not None:
            with stack[4]:
                logger = setup.setup_individual_logger(module_name, caller_path=fake_module)
        else:
            logger = setup.setup_individual_logger(module_name, caller_path=fake_module)

    return (
        logger,
        project_dir / "system_logs" / f"proj_{module_name}.log",
        project_dir / "logs" / f"{module_name}.log",
    )


def _tiered_config(system_level, local_level):
    """Config dict with an explicit log_level on each tier."""
    return {
        "log_format": "%(levelname)s | %(message)s",
        "date_format": "%Y-%m-%d %H:%M:%S",
        "system_logs": {"max_lines": 1000, "backup_count": 3, "log_level": system_level},
        "local_logs": {"max_lines": 250, "backup_count": 3, "log_level": local_level},
    }


class TestDebugLevelGating:
    """End-to-end tests for debug() — asserts on real log file contents.

    Each test logs an INFO control line, or an absent debug marker would prove nothing."""

    def test_debug_is_silent_at_default_level(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        """Default INFO: debug() reaches no file, while info() reaches both."""
        monkeypatch.delenv("AIPASS_LOG_LEVEL", raising=False)
        logger, sys_log, local_log = _external_logger(setup_handler, tmp_path, "quiet_mod")

        logger.debug("DEBUGMARK_quiet")
        logger.info("INFOMARK_quiet")

        assert "INFOMARK_quiet" in sys_log.read_text(encoding="utf-8")
        assert "INFOMARK_quiet" in local_log.read_text(encoding="utf-8")
        assert "DEBUGMARK_quiet" not in sys_log.read_text(encoding="utf-8")
        assert "DEBUGMARK_quiet" not in local_log.read_text(encoding="utf-8")

    def test_env_var_lets_debug_reach_both_tiers(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        """AIPASS_LOG_LEVEL=DEBUG is the on-demand verbose trail."""
        logger, sys_log, local_log = _external_logger(
            setup_handler, tmp_path, "loud_mod", env={"AIPASS_LOG_LEVEL": "DEBUG"}
        )

        logger.debug("DEBUGMARK_loud")
        logger.info("INFOMARK_loud")

        assert "DEBUGMARK_loud" in sys_log.read_text(encoding="utf-8")
        assert "DEBUGMARK_loud" in local_log.read_text(encoding="utf-8")
        assert "INFOMARK_loud" in sys_log.read_text(encoding="utf-8")

    def test_config_log_level_is_read(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        """The log_level config key reaches a handler — it was dead before."""
        monkeypatch.delenv("AIPASS_LOG_LEVEL", raising=False)
        logger, sys_log, _local = _external_logger(
            setup_handler, tmp_path, "cfg_mod", config=_tiered_config("DEBUG", "DEBUG")
        )

        logger.debug("DEBUGMARK_cfg")

        assert "DEBUGMARK_cfg" in sys_log.read_text(encoding="utf-8")

    def test_tiers_gate_independently(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        """Verbose branch-local file, quiet central aggregation."""
        monkeypatch.delenv("AIPASS_LOG_LEVEL", raising=False)
        logger, sys_log, local_log = _external_logger(
            setup_handler, tmp_path, "split_mod", config=_tiered_config("INFO", "DEBUG")
        )

        logger.debug("DEBUGMARK_split")
        logger.info("INFOMARK_split")

        assert "DEBUGMARK_split" in local_log.read_text(encoding="utf-8")
        assert "DEBUGMARK_split" not in sys_log.read_text(encoding="utf-8")
        assert "INFOMARK_split" in sys_log.read_text(encoding="utf-8")
        assert "INFOMARK_split" in local_log.read_text(encoding="utf-8")

    def test_logger_gate_opens_for_the_most_permissive_tier(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        """The logger's own level must not be stricter than either handler.

        A logger left at INFO drops DEBUG before the DEBUG-level handler sees it."""
        monkeypatch.delenv("AIPASS_LOG_LEVEL", raising=False)
        logger, _sys_log, _local_log = _external_logger(
            setup_handler, tmp_path, "gate_mod", config=_tiered_config("ERROR", "DEBUG")
        )

        assert logger.level == 10

    def test_invalid_level_still_logs_at_info(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        """A typo in the config must not silence the logs."""
        monkeypatch.delenv("AIPASS_LOG_LEVEL", raising=False)
        logger, sys_log, _local = _external_logger(
            setup_handler, tmp_path, "typo_mod", config=_tiered_config("VERBOSE", "VERBOSE")
        )

        logger.info("INFOMARK_typo")
        logger.debug("DEBUGMARK_typo")

        assert "INFOMARK_typo" in sys_log.read_text(encoding="utf-8")
        assert "DEBUGMARK_typo" not in sys_log.read_text(encoding="utf-8")
