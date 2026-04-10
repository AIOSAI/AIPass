# =================== AIPass ====================
# Name: test_caller.py
# Description: Tests for OpenRouter caller detection handler
# Version: 1.0.0
# Created: 2026-04-03
# Modified: 2026-04-03
# =============================================

"""
Tests for openrouter.caller — caller detection handler.

Tests:
- detect_caller_category for flow paths
- detect_caller_category for prax paths
- detect_caller_category for skills paths
- detect_caller_category for unknown paths
- detect_caller_category with 'skills' as substring in a part
"""

from unittest.mock import patch, MagicMock
from pathlib import Path

import pytest

from aipass.api.apps.handlers.openrouter.caller import detect_caller_category


# =============================================
# detect_caller_category tests
# =============================================


class TestDetectCallerCategory:
    """Tests for caller.detect_caller_category()."""

    def test_flow_path_returns_flow(self):
        """Path containing 'flow' part should return 'flow'."""
        path = Path("/home/user/projects/aipass/src/aipass/flow/engine.py")
        assert detect_caller_category(path) == "flow"

    def test_prax_path_returns_prax(self):
        """Path containing 'prax' part should return 'prax'."""
        path = Path("/home/user/projects/aipass/src/aipass/prax/monitor.py")
        assert detect_caller_category(path) == "prax"

    def test_skills_exact_part_returns_skills(self):
        """Path with exact 'skills' directory should return 'skills'."""
        path = Path("/home/user/projects/aipass/src/aipass/skills/skills_api/tool.py")
        assert detect_caller_category(path) == "skills"

    def test_skills_substring_returns_skills(self):
        """Path with 'skills' as substring in a part (e.g., 'skills_api') should return 'skills'."""
        path = Path("/home/user/projects/aipass/src/aipass/modules/skills_custom/handler.py")
        assert detect_caller_category(path) == "skills"

    def test_unknown_path_returns_unknown(self):
        """Path without flow, prax, or skills should return 'unknown'."""
        path = Path("/home/user/projects/aipass/src/aipass/api/apps/handler.py")
        assert detect_caller_category(path) == "unknown"

    def test_flow_takes_priority_over_later_prax(self):
        """If 'flow' appears before 'prax' in path, should return 'flow'."""
        path = Path("/home/user/flow/prax/script.py")
        assert detect_caller_category(path) == "flow"

    def test_prax_takes_priority_over_skills(self):
        """If 'prax' appears before a skills part, should return 'prax'."""
        path = Path("/home/user/prax/skills_module/script.py")
        assert detect_caller_category(path) == "prax"

    def test_root_path_returns_unknown(self):
        """Root-level path should return 'unknown'."""
        path = Path("/somefile.py")
        assert detect_caller_category(path) == "unknown"

    def test_deeply_nested_flow_path(self):
        """Deeply nested path with 'flow' should still return 'flow'."""
        path = Path("/a/b/c/d/flow/e/f/g/handler.py")
        assert detect_caller_category(path) == "flow"

    @patch("aipass.api.apps.handlers.openrouter.caller.logger")
    def test_exception_returns_unknown(self, mock_logger):
        """If an exception occurs, should return 'unknown' and log error."""
        bad_path = MagicMock(spec=Path)
        bad_path.parts = property(lambda self: (_ for _ in ()).throw(RuntimeError("boom")))
        type(bad_path).parts = property(lambda self: (_ for _ in ()).throw(RuntimeError("boom")))

        result = detect_caller_category(bad_path)

        assert result == "unknown"
        mock_logger.error.assert_called_once()
