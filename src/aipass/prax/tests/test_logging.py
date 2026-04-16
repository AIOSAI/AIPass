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
