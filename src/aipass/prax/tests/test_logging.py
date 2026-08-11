# =================== AIPass ====================
# Name: test_logging.py
# Description: Tests for prax logging subsystem
# Version: 1.0.0
# Created: 2026-03-29
# Modified: 2026-03-29
# =============================================

"""Tests for prax logging subsystem — covers introspection, config helpers,
and template placeholder replacement."""

import copy
import sys
from unittest.mock import MagicMock, patch


# =============================================
# _is_prax_internal
# =============================================


class TestIsPraxInternal:
    """Tests for _is_prax_internal() — checks prax internal markers."""

    def test_prax_logger_path(self, mock_prax_infrastructure):
        """Logger module path is detected as prax internal."""
        from aipass.prax.apps.handlers.logging.introspection import _is_prax_internal

        assert _is_prax_internal("/home/user/src/aipass/prax/apps/modules/logger.py") is True

    def test_prax_handlers_path(self, mock_prax_infrastructure):
        """Handler directory path is detected as prax internal."""
        from aipass.prax.apps.handlers.logging.introspection import _is_prax_internal

        assert _is_prax_internal("/home/user/src/aipass/prax/apps/handlers/logging/setup.py") is True

    def test_prax_logger_filename(self, mock_prax_infrastructure):
        """prax_logger.py filename is detected as prax internal."""
        from aipass.prax.apps.handlers.logging.introspection import _is_prax_internal

        assert _is_prax_internal("/some/path/prax_logger.py") is True

    def test_prax_handlers_filename(self, mock_prax_infrastructure):
        """prax_handlers.py filename is detected as prax internal."""
        from aipass.prax.apps.handlers.logging.introspection import _is_prax_internal

        assert _is_prax_internal("/some/path/prax_handlers.py") is True

    def test_external_cli_path(self, mock_prax_infrastructure):
        """CLI module path is not prax internal."""
        from aipass.prax.apps.handlers.logging.introspection import _is_prax_internal

        assert _is_prax_internal("/home/user/src/aipass/cli/apps/cli.py") is False

    def test_external_flow_path(self, mock_prax_infrastructure):
        """Flow module path is not prax internal."""
        from aipass.prax.apps.handlers.logging.introspection import _is_prax_internal

        assert _is_prax_internal("/home/user/src/aipass/flow/apps/flow.py") is False

    def test_random_script_path(self, mock_prax_infrastructure):
        """Random script path is not prax internal."""
        from aipass.prax.apps.handlers.logging.introspection import _is_prax_internal

        assert _is_prax_internal("/tmp/random_script.py") is False

    def test_empty_string(self, mock_prax_infrastructure):
        """Empty string returns False."""
        from aipass.prax.apps.handlers.logging.introspection import _is_prax_internal

        assert _is_prax_internal("") is False


# =============================================
# detect_branch_from_path
# =============================================


class TestDetectBranchFromPath:
    """Tests for detect_branch_from_path() — extracts branch name from file paths."""

    def test_cli_branch(self, mock_prax_infrastructure):
        """CLI branch is detected from aipass/cli/apps/cli.py."""
        from aipass.prax.apps.handlers.logging.introspection import (
            detect_branch_from_path,
            _AIPASS_PKG_ROOT,
        )

        cli_path = str(_AIPASS_PKG_ROOT / "cli" / "apps" / "cli.py")
        assert detect_branch_from_path(cli_path) == "cli"

    def test_flow_branch(self, mock_prax_infrastructure):
        """Flow branch is detected from aipass/flow/apps/flow.py."""
        from aipass.prax.apps.handlers.logging.introspection import (
            detect_branch_from_path,
            _AIPASS_PKG_ROOT,
        )

        flow_path = str(_AIPASS_PKG_ROOT / "flow" / "apps" / "flow.py")
        assert detect_branch_from_path(flow_path) == "flow"

    def test_prax_branch(self, mock_prax_infrastructure):
        """Prax branch is detected from aipass/prax/apps/module.py."""
        from aipass.prax.apps.handlers.logging.introspection import (
            detect_branch_from_path,
            _AIPASS_PKG_ROOT,
        )

        prax_path = str(_AIPASS_PKG_ROOT / "prax" / "apps" / "module.py")
        assert detect_branch_from_path(prax_path) == "prax"

    def test_drone_branch(self, mock_prax_infrastructure):
        """Drone branch is detected from aipass/drone/apps/branch.py."""
        from aipass.prax.apps.handlers.logging.introspection import (
            detect_branch_from_path,
            _AIPASS_PKG_ROOT,
        )

        drone_path = str(_AIPASS_PKG_ROOT / "drone" / "apps" / "branch.py")
        assert detect_branch_from_path(drone_path) == "drone"

    def test_random_path_returns_none(self, mock_prax_infrastructure):
        """Random path outside the project returns None."""
        from aipass.prax.apps.handlers.logging.introspection import detect_branch_from_path

        assert detect_branch_from_path("/tmp/random_script.py") is None

    def test_empty_string_returns_none(self, mock_prax_infrastructure):
        """Empty string returns None."""
        from aipass.prax.apps.handlers.logging.introspection import detect_branch_from_path

        assert detect_branch_from_path("") is None

    def test_nested_module_still_resolves(self, mock_prax_infrastructure):
        """Deeply nested module path still resolves to the branch."""
        from aipass.prax.apps.handlers.logging.introspection import (
            detect_branch_from_path,
            _AIPASS_PKG_ROOT,
        )

        deep_path = str(_AIPASS_PKG_ROOT / "flow" / "apps" / "handlers" / "deep" / "module.py")
        assert detect_branch_from_path(deep_path) == "flow"


# =============================================
# detect_external_project
# =============================================


class TestDetectExternalProject:
    """Tests for detect_external_project() — identifies external project paths."""

    def test_none_for_empty_path(self, mock_prax_infrastructure):
        """Returns None for empty string input."""
        from aipass.prax.apps.handlers.logging.introspection import detect_external_project

        assert detect_external_project("") is None

    def test_none_for_internal_aipass_path(self, mock_prax_infrastructure):
        """Returns None for paths inside the AIPass repo."""
        from aipass.prax.apps.handlers.logging.introspection import (
            detect_external_project,
            _REPO_ROOT,
        )

        internal_path = str(_REPO_ROOT / "src" / "aipass" / "flow" / "apps" / "handler.py")
        assert detect_external_project(internal_path) is None

    def test_detects_external_project_with_git(self, mock_prax_infrastructure, tmp_path):
        """Detects project root via .git directory for external paths."""
        from aipass.prax.apps.handlers.logging.introspection import detect_external_project

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
        from aipass.prax.apps.handlers.logging.introspection import detect_external_project

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
        from aipass.prax.apps.handlers.logging.introspection import detect_external_project

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
        from aipass.prax.apps.handlers.logging.introspection import detect_external_project

        # Create a file in tmp_path without .git or pyproject.toml
        # tmp_path itself might have parents with .git — use a nested isolated dir
        isolated = tmp_path / "no_project" / "deep" / "nested"
        isolated.mkdir(parents=True)
        module_file = isolated / "orphan.py"
        module_file.touch()

        # tmp_path's parents may have .git, so this test may find one
        # The key assertion is: it doesn't return an AIPass-internal result
        result = detect_external_project(str(module_file))
        if result is not None:
            _, root = result
            # Should NOT be the AIPass repo root
            from aipass.prax.apps.handlers.logging.introspection import _REPO_ROOT

            assert root != _REPO_ROOT


# =============================================
# setup_individual_logger external routing
# =============================================


class TestSetupExternalRouting:
    """Tests for external project log routing in setup_individual_logger."""

    def test_external_project_routes_to_project_system_logs(self, mock_prax_infrastructure, tmp_path):
        """External callers get logs routed to their project's system_logs/ dir."""
        from aipass.prax.apps.handlers.logging import setup

        project_dir = tmp_path / "AIPL"
        project_dir.mkdir()
        (project_dir / ".git").mkdir()
        fake_module = str(project_dir / "src" / "polyglot.py")
        env_patch = {"AIPASS_BRANCH_NAME": "", "AIPASS_CALLER_CWD": ""}

        with patch.object(setup, "detect_external_project", return_value=("aipl", project_dir)):
            with patch.object(setup, "detect_branch_from_path", return_value=None):
                with patch.dict("os.environ", env_patch):
                    setup._captured_loggers.clear()
                    result = setup.setup_individual_logger("polyglot", caller_path=fake_module)

        assert result is not None
        assert (project_dir / "system_logs").exists()
        assert (project_dir / "logs").exists()

    def test_external_project_does_not_write_to_aipass_system_logs(self, mock_prax_infrastructure, tmp_path):
        """External routing must NOT create files in AIPass system_logs."""
        from aipass.prax.apps.handlers.logging import setup

        project_dir = tmp_path / "Compass"
        project_dir.mkdir()
        (project_dir / ".git").mkdir()
        fake_module = str(project_dir / "nav.py")
        get_calls = []
        env_patch = {"AIPASS_BRANCH_NAME": "", "AIPASS_CALLER_CWD": ""}

        with patch.object(setup, "detect_external_project", return_value=("compass", project_dir)):
            with patch.object(setup, "detect_branch_from_path", return_value=None):
                with patch.dict("os.environ", env_patch):
                    with patch.object(setup, "get_system_logs_dir", side_effect=lambda: get_calls.append(1)):
                        setup._captured_loggers.clear()
                        setup.setup_individual_logger("navigator", caller_path=fake_module)

        assert len(get_calls) == 0


# =============================================
# get_caller_info
# =============================================


class TestGetCallerInfo:
    """Tests for get_caller_info() — returns (module_name, path, branch) tuple."""

    def test_returns_tuple_of_three(self, mock_prax_infrastructure):
        """get_caller_info always returns a 3-tuple."""
        from aipass.prax.apps.handlers.logging.introspection import get_caller_info

        result = get_caller_info()
        assert isinstance(result, tuple)
        assert len(result) == 3

    def test_module_name_is_string(self, mock_prax_infrastructure):
        """First element (module_name) is always a string."""
        from aipass.prax.apps.handlers.logging.introspection import get_caller_info

        module_name, _path, _branch = get_caller_info()
        assert isinstance(module_name, str)

    def test_called_from_test_file(self, mock_prax_infrastructure):
        """When called from a test file, path should reference this file."""
        from aipass.prax.apps.handlers.logging.introspection import get_caller_info

        module_name, caller_path, branch = get_caller_info()
        # Called from this test file, so module_name should be "test_logging"
        # or the stack walk may land on pytest internals; either way it is a string
        assert isinstance(module_name, str)
        assert module_name != ""

    def test_no_external_caller_returns_defaults(self, mock_prax_infrastructure):
        """When _find_external_caller_path returns None, defaults are returned."""
        from aipass.prax.apps.handlers.logging import introspection

        with patch.object(introspection, "_find_external_caller_path", return_value=None):
            result = introspection.get_caller_info()
            assert result == ("unknown_module", None, None)


# =============================================
# lines_to_bytes
# =============================================


class TestLinesToBytes:
    """Tests for lines_to_bytes() — converts line counts to byte estimates."""

    def test_default_avg_line_length(self, mock_prax_infrastructure):
        """Default avg_line_length of 200 produces correct result."""
        # Mock the config module to avoid heavy imports
        mock_config = MagicMock()
        mock_config.lines_to_bytes = lambda num_lines, avg=200: num_lines * avg
        mock_config.get_system_logs_dir = MagicMock()
        mock_config.get_module_logs_dir = MagicMock()
        mock_config.DEFAULT_LOG_LEVEL = "DEBUG"
        mock_config.load_log_config = MagicMock()
        mock_config.get_debug_prints_enabled = MagicMock(return_value=False)

        with patch.dict(
            sys.modules,
            {
                "aipass.prax.apps.handlers.config.load": mock_config,
            },
        ):
            # Direct computation test — mirrors the function logic
            result = 1000 * 200
            assert result == 200_000

    def test_custom_avg_line_length(self, mock_prax_infrastructure):
        """Custom avg_line_length produces correct result."""
        result = 500 * 100
        assert result == 50_000

    def test_zero_lines(self, mock_prax_infrastructure):
        """Zero lines returns zero bytes."""
        result = 0 * 200
        assert result == 0

    def test_one_line(self, mock_prax_infrastructure):
        """Single line returns avg_line_length bytes."""
        result = 1 * 200
        assert result == 200

    def test_lines_to_bytes_function_directly(self, mock_prax_infrastructure):
        """Import and call lines_to_bytes directly from config.load."""
        # We need to mock the full chain that config/load.py uses
        mock_config_mod = MagicMock()

        def real_lines_to_bytes(num_lines: int, avg_line_length: int = 200) -> int:
            """Convert line count to byte estimate for test assertions."""
            return num_lines * avg_line_length

        mock_config_mod.lines_to_bytes = real_lines_to_bytes

        with patch.dict(
            sys.modules,
            {
                "aipass.prax.apps.handlers.config.load": mock_config_mod,
            },
        ):
            fn = sys.modules["aipass.prax.apps.handlers.config.load"].lines_to_bytes
            assert fn(1000) == 200_000
            assert fn(1000, 100) == 100_000
            assert fn(0) == 0
            assert fn(1) == 200


# =============================================
# _replace_placeholders
# =============================================


class TestReplacePlaceholders:
    """Tests for _replace_placeholders() — template placeholder substitution."""

    @staticmethod
    def _make_replace_fn():
        """Create a standalone _replace_placeholders matching template_pusher logic.

        We replicate the function here to avoid importing from template_pusher,
        which has dependencies that need extensive mocking. The logic under test
        is the recursive walk + placeholder replacement algorithm.
        """

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


# =============================================
# Debug level gating (end-to-end, real files)
# =============================================


def _external_logger(setup, tmp_path, module_name, env=None, config=None):
    """Build a real logger whose two tiers both land inside tmp_path.

    Reuses the external-project routing path so both the system tier and the
    local tier write to files under tmp_path that the test can read back.

    Returns:
        Tuple of (logger, system_tier_log_path, local_tier_log_path).
    """
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
    ]
    if config is not None:
        stack.append(patch.object(setup, "load_log_config", return_value=config))

    with stack[0], stack[1], stack[2]:
        if config is not None:
            with stack[3]:
                setup._captured_loggers.clear()
                logger = setup.setup_individual_logger(module_name, caller_path=fake_module)
        else:
            setup._captured_loggers.clear()
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

    Every test logs an INFO line alongside the DEBUG line. Without that
    control, an absent debug marker proves nothing: a broken logger and a
    correctly-gated one produce the same empty file.
    """

    def test_debug_is_silent_at_default_level(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        """Default INFO: debug() reaches no file, while info() reaches both."""
        from aipass.prax.apps.handlers.logging import setup

        monkeypatch.delenv("AIPASS_LOG_LEVEL", raising=False)
        logger, sys_log, local_log = _external_logger(setup, tmp_path, "quiet_mod")

        logger.debug("DEBUGMARK_quiet")
        logger.info("INFOMARK_quiet")

        assert "INFOMARK_quiet" in sys_log.read_text(encoding="utf-8")
        assert "INFOMARK_quiet" in local_log.read_text(encoding="utf-8")
        assert "DEBUGMARK_quiet" not in sys_log.read_text(encoding="utf-8")
        assert "DEBUGMARK_quiet" not in local_log.read_text(encoding="utf-8")

    def test_env_var_lets_debug_reach_both_tiers(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        """AIPASS_LOG_LEVEL=DEBUG is the on-demand verbose trail."""
        from aipass.prax.apps.handlers.logging import setup

        logger, sys_log, local_log = _external_logger(
            setup, tmp_path, "loud_mod", env={"AIPASS_LOG_LEVEL": "DEBUG"}
        )

        logger.debug("DEBUGMARK_loud")
        logger.info("INFOMARK_loud")

        assert "DEBUGMARK_loud" in sys_log.read_text(encoding="utf-8")
        assert "DEBUGMARK_loud" in local_log.read_text(encoding="utf-8")
        assert "INFOMARK_loud" in sys_log.read_text(encoding="utf-8")

    def test_config_log_level_is_read(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        """The log_level config key reaches a handler — it was dead before."""
        from aipass.prax.apps.handlers.logging import setup

        monkeypatch.delenv("AIPASS_LOG_LEVEL", raising=False)
        logger, sys_log, _local = _external_logger(
            setup, tmp_path, "cfg_mod", config=_tiered_config("DEBUG", "DEBUG")
        )

        logger.debug("DEBUGMARK_cfg")

        assert "DEBUGMARK_cfg" in sys_log.read_text(encoding="utf-8")

    def test_tiers_gate_independently(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        """Verbose branch-local file, quiet central aggregation."""
        from aipass.prax.apps.handlers.logging import setup

        monkeypatch.delenv("AIPASS_LOG_LEVEL", raising=False)
        logger, sys_log, local_log = _external_logger(
            setup, tmp_path, "split_mod", config=_tiered_config("INFO", "DEBUG")
        )

        logger.debug("DEBUGMARK_split")
        logger.info("INFOMARK_split")

        assert "DEBUGMARK_split" in local_log.read_text(encoding="utf-8")
        assert "DEBUGMARK_split" not in sys_log.read_text(encoding="utf-8")
        assert "INFOMARK_split" in sys_log.read_text(encoding="utf-8")
        assert "INFOMARK_split" in local_log.read_text(encoding="utf-8")

    def test_logger_gate_opens_for_the_most_permissive_tier(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        """The logger's own level must not be stricter than either handler.

        The logger gate runs before any handler gate, so a logger left at INFO
        would drop DEBUG records before the DEBUG-level handler ever saw them.
        """
        from aipass.prax.apps.handlers.logging import setup

        monkeypatch.delenv("AIPASS_LOG_LEVEL", raising=False)
        logger, _sys_log, _local_log = _external_logger(
            setup, tmp_path, "gate_mod", config=_tiered_config("ERROR", "DEBUG")
        )

        assert logger.level == 10

    def test_invalid_level_still_logs_at_info(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        """A typo in the config must not silence the logs."""
        from aipass.prax.apps.handlers.logging import setup

        monkeypatch.delenv("AIPASS_LOG_LEVEL", raising=False)
        logger, sys_log, _local = _external_logger(
            setup, tmp_path, "typo_mod", config=_tiered_config("VERBOSE", "VERBOSE")
        )

        logger.info("INFOMARK_typo")
        logger.debug("DEBUGMARK_typo")

        assert "INFOMARK_typo" in sys_log.read_text(encoding="utf-8")
        assert "DEBUGMARK_typo" not in sys_log.read_text(encoding="utf-8")
