# =================== AIPass ====================
# Name: test_caller_detection.py
# Description: Tests for caller detection internals (uncovered functions)
# Version: 1.0.1
# Created: 2026-05-12
# Modified: 2026-11-15
# =============================================

"""Tests for apps/handlers/openrouter/caller.py, its internal detection functions."""

# The declared pass — what is NOT tested here, and what covers it instead:
# sentry: no-test-needed(constant) — MODULE_NAME, MODULE_VERSION and CALLER_PATTERNS' text
# sentry: no-test-needed(stdlib) — inspect.stack's frame order and pathlib's parts splitting

from pathlib import Path
from unittest.mock import patch, MagicMock

from aipass.api.apps.handlers.openrouter.caller import get_caller_info


class TestGetCallerInfo:
    """Tests for caller.get_caller_info()."""

    @patch("aipass.api.apps.handlers.openrouter.caller.json_handler", autospec=True)
    @patch("aipass.api.apps.handlers.openrouter.caller.logger", autospec=True)
    @patch("aipass.api.apps.handlers.openrouter.caller.inspect.stack")
    def test_detects_flow_frame(
        self,
        mock_stack: MagicMock,
        _mock_logger: MagicMock,
        _mock_jh: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Stack frame with 'flow' in path triggers flow detection."""
        src = tmp_path / "aipass" / "src" / "aipass"
        frame = MagicMock()
        frame.filename = str(src / "flow" / "engine.py")
        self_frame = MagicMock()
        self_frame.filename = str(src / "api" / "caller.py")
        mock_stack.return_value = [self_frame, frame]

        result = get_caller_info()

        assert result is not None
        assert result["category"] == "flow"
        assert result["caller_name"] == "engine"
        assert result["json_folder"] == src / "flow" / "flow_json"
        assert result["detection_method"] == "stack"

    @patch("aipass.api.apps.handlers.openrouter.caller.json_handler", autospec=True)
    @patch("aipass.api.apps.handlers.openrouter.caller.logger", autospec=True)
    @patch("aipass.api.apps.handlers.openrouter.caller.inspect.stack")
    def test_detects_prax_frame(
        self,
        mock_stack: MagicMock,
        _mock_logger: MagicMock,
        _mock_jh: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Stack frame with 'prax' in path triggers prax detection."""
        src = tmp_path / "aipass" / "src" / "aipass"
        frame = MagicMock()
        frame.filename = str(src / "prax" / "monitor.py")
        self_frame = MagicMock()
        self_frame.filename = str(src / "api" / "caller.py")
        mock_stack.return_value = [self_frame, frame]

        result = get_caller_info()

        assert result is not None
        assert result["category"] == "prax"
        assert result["caller_name"] == "monitor"
        assert result["json_folder"] == src / "prax" / "prax_json"
        assert result["detection_method"] == "stack"

    @patch("aipass.api.apps.handlers.openrouter.caller.json_handler", autospec=True)
    @patch("aipass.api.apps.handlers.openrouter.caller.logger", autospec=True)
    @patch("aipass.api.apps.handlers.openrouter.caller.inspect.stack")
    def test_returns_none_when_no_match(
        self,
        mock_stack: MagicMock,
        _mock_logger: MagicMock,
        _mock_jh: MagicMock,
        tmp_path: Path,
    ) -> None:
        """When no stack frame matches flow/prax, returns None."""
        src = tmp_path / "aipass" / "src" / "aipass"
        frame = MagicMock()
        frame.filename = str(src / "api" / "handler.py")
        self_frame = MagicMock()
        self_frame.filename = str(src / "api" / "caller.py")
        mock_stack.return_value = [self_frame, frame]

        result = get_caller_info()

        assert result is None

    @patch("aipass.api.apps.handlers.openrouter.caller.logger", autospec=True)
    @patch("aipass.api.apps.handlers.openrouter.caller.inspect.stack")
    def test_returns_none_on_exception(
        self,
        mock_stack: MagicMock,
        mock_logger: MagicMock,
    ) -> None:
        """When inspect.stack raises, returns None and logs error."""
        mock_stack.side_effect = RuntimeError("stack failed")

        result = get_caller_info()

        assert result is None
        mock_logger.error.assert_called_once_with("Caller detection failed: stack failed")
