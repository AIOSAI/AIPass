# =================== AIPass ====================
# Name: test_caller.py
# Description: Tests for OpenRouter caller detection handler
# Version: 1.0.1
# Created: 2026-04-03
# Modified: 2026-10-24
# =============================================

"""Tests for apps/handlers/openrouter/caller.py's detect_caller_category()."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(covered) — get_caller_info(), tests/test_caller_detection.py
# seedgo: no-test-needed(constant) — MODULE_NAME and MODULE_VERSION's display strings

from aipass.api.apps.handlers.openrouter.caller import detect_caller_category


class TestDetectCallerCategory:
    """Tests for caller.detect_caller_category()."""

    def test_flow_path_returns_flow(self, tmp_path):
        """Path containing 'flow' part should return 'flow'."""
        path = tmp_path / "projects" / "aipass" / "src" / "aipass" / "flow" / "engine.py"
        assert detect_caller_category(path) == "flow"

    def test_prax_path_returns_prax(self, tmp_path):
        """Path containing 'prax' part should return 'prax'."""
        path = tmp_path / "projects" / "aipass" / "src" / "aipass" / "prax" / "monitor.py"
        assert detect_caller_category(path) == "prax"

    def test_skills_path_returns_unknown(self, tmp_path):
        """Skills branch was removed — skills paths now return 'unknown'."""
        path = tmp_path / "projects" / "aipass" / "src" / "aipass" / "skills" / "skills_api" / "tool.py"
        assert detect_caller_category(path) == "unknown"

    def test_unknown_path_returns_unknown(self, tmp_path):
        """Path without flow or prax should return 'unknown'."""
        path = tmp_path / "projects" / "aipass" / "src" / "aipass" / "api" / "apps" / "handler.py"
        assert detect_caller_category(path) == "unknown"

    def test_flow_takes_priority_over_later_prax(self, tmp_path):
        """If 'flow' appears before 'prax' in path, should return 'flow'."""
        path = tmp_path / "flow" / "prax" / "script.py"
        assert detect_caller_category(path) == "flow"

    def test_prax_in_mixed_path(self, tmp_path):
        """'prax' in path should return 'prax' regardless of other parts."""
        path = tmp_path / "prax" / "other_module" / "script.py"
        assert detect_caller_category(path) == "prax"

    def test_a_path_with_no_branch_directory_returns_unknown(self, tmp_path):
        """A path with no branch directory in it should return 'unknown'."""
        path = tmp_path / "somefile.py"
        assert detect_caller_category(path) == "unknown"

    def test_deeply_nested_flow_path(self, tmp_path):
        """Deeply nested path with 'flow' should still return 'flow'."""
        path = tmp_path / "a" / "b" / "c" / "d" / "flow" / "e" / "f" / "g" / "handler.py"
        assert detect_caller_category(path) == "flow"
