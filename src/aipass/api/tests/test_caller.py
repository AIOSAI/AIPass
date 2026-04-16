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
- detect_caller_category for unknown paths (including former skills paths)
"""

from unittest.mock import patch, MagicMock
from pathlib import Path


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

    def test_skills_path_returns_unknown(self):
        """Skills branch was removed — skills paths now return 'unknown'."""
        path = Path("/home/user/projects/aipass/src/aipass/skills/skills_api/tool.py")
        assert detect_caller_category(path) == "unknown"

    def test_unknown_path_returns_unknown(self):
        """Path without flow or prax should return 'unknown'."""
        path = Path("/home/user/projects/aipass/src/aipass/api/apps/handler.py")
        assert detect_caller_category(path) == "unknown"

    def test_flow_takes_priority_over_later_prax(self):
        """If 'flow' appears before 'prax' in path, should return 'flow'."""
        path = Path("/home/user/flow/prax/script.py")
        assert detect_caller_category(path) == "flow"

    def test_prax_in_mixed_path(self):
        """'prax' in path should return 'prax' regardless of other parts."""
        path = Path("/home/user/prax/other_module/script.py")
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
