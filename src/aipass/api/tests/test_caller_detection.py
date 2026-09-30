# =================== AIPass ====================
# Name: test_caller_detection.py
# Description: Tests for caller detection internals (uncovered functions)
# Version: 1.0.0
# Created: 2026-05-12
# Modified: 2026-09-29
# =============================================

"""Tests for apps/handlers/openrouter/caller.py, its internal detection functions."""

# Tests for openrouter.caller -- internal detection functions.
#
# Covers functions NOT tested in test_caller.py:
# - _detect_flow_caller
# - _detect_prax_caller
# - _create_fallback_info
# - detect_caller_from_stack
# - get_caller_info (stack inspection)

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(constant) — MODULE_NAME, MODULE_VERSION and CALLER_PATTERNS' text
# seedgo: no-test-needed(stdlib) — inspect.stack's frame order and pathlib's parts splitting
# seedgo: no-test-needed(duplicate_test) — detect_caller_category on its own, covered by test_caller.py

from pathlib import Path
from unittest.mock import patch, MagicMock

from aipass.api.apps.handlers.openrouter.caller import (
    _detect_flow_caller,
    _detect_prax_caller,
    _create_fallback_info,
    detect_caller_from_stack,
    get_caller_info,
)


class _PartsWhoseIndexFails(tuple):
    """Path parts whose index() raises and which hold no branch name.

    Only index() fails, as the fallback tests' docstrings say: the fallback then
    categorises the same path, and detect_caller_category no longer carries a try
    for parts that raise, an input no caller can make (api, fleet green leg 4).
    """

    def index(self, *args: object) -> int:
        raise ValueError("bad")


# =============================================
# _detect_flow_caller tests
# =============================================


class TestDetectFlowCaller:
    """Tests for caller._detect_flow_caller()."""

    @patch("aipass.api.apps.handlers.openrouter.caller.logger", autospec=True)
    def test_returns_flow_dict(self, _mock_logger: MagicMock, tmp_path: Path) -> None:
        """Given a path with 'flow', returns dict with category='flow'."""
        frame_path = tmp_path / "projects" / "aipass" / "src" / "aipass" / "flow" / "engine.py"
        result = _detect_flow_caller(frame_path)

        assert result["category"] == "flow"
        assert result["caller_name"] == "engine"
        assert result["caller_path"] == frame_path
        assert result["detection_method"] == "stack"

    @patch("aipass.api.apps.handlers.openrouter.caller.logger", autospec=True)
    def test_json_folder_points_to_flow_json(self, _mock_logger: MagicMock, tmp_path: Path) -> None:
        """json_folder should be <flow_root>/flow_json."""
        flow_root = tmp_path / "projects" / "aipass" / "src" / "aipass" / "flow"
        frame_path = flow_root / "sub" / "engine.py"
        result = _detect_flow_caller(frame_path)

        expected_json = flow_root / "flow_json"
        assert result["json_folder"] == expected_json

    @patch("aipass.api.apps.handlers.openrouter.caller.logger", autospec=True)
    def test_exception_returns_fallback(self, _mock_logger: MagicMock) -> None:
        """If parts.index raises, should fall back to _create_fallback_info."""
        bad_path = MagicMock(spec=Path)
        type(bad_path).parts = property(lambda self: _PartsWhoseIndexFails(("x",)))
        bad_path.stem = "broken"

        result = _detect_flow_caller(bad_path)

        assert result["detection_method"] == "fallback"


# =============================================
# _detect_prax_caller tests
# =============================================


class TestDetectPraxCaller:
    """Tests for caller._detect_prax_caller()."""

    @patch("aipass.api.apps.handlers.openrouter.caller.logger", autospec=True)
    def test_returns_prax_dict(self, _mock_logger: MagicMock, tmp_path: Path) -> None:
        """Given a path with 'prax', returns dict with category='prax'."""
        frame_path = tmp_path / "projects" / "aipass" / "src" / "aipass" / "prax" / "monitor.py"
        result = _detect_prax_caller(frame_path)

        assert result["category"] == "prax"
        assert result["caller_name"] == "monitor"
        assert result["caller_path"] == frame_path
        assert result["detection_method"] == "stack"

    @patch("aipass.api.apps.handlers.openrouter.caller.logger", autospec=True)
    def test_json_folder_points_to_prax_json(self, _mock_logger: MagicMock, tmp_path: Path) -> None:
        """json_folder should be <prax_root>/prax_json."""
        prax_root = tmp_path / "projects" / "aipass" / "src" / "aipass" / "prax"
        frame_path = prax_root / "sub" / "monitor.py"
        result = _detect_prax_caller(frame_path)

        expected_json = prax_root / "prax_json"
        assert result["json_folder"] == expected_json

    @patch("aipass.api.apps.handlers.openrouter.caller.logger", autospec=True)
    def test_exception_returns_fallback(self, _mock_logger: MagicMock) -> None:
        """If parts.index raises, should fall back."""
        bad_path = MagicMock(spec=Path)
        type(bad_path).parts = property(lambda self: _PartsWhoseIndexFails(("x",)))
        bad_path.stem = "broken"

        result = _detect_prax_caller(bad_path)

        assert result["detection_method"] == "fallback"


# =============================================
# _create_fallback_info tests
# =============================================


class TestCreateFallbackInfo:
    """Tests for caller._create_fallback_info()."""

    @patch("aipass.api.apps.handlers.openrouter.caller.logger", autospec=True)
    def test_returns_fallback_dict(self, _mock_logger: MagicMock, tmp_path: Path) -> None:
        """Fallback info should have detection_method='fallback' and json_folder=None."""
        frame_path = tmp_path / "some" / "random" / "script.py"
        result = _create_fallback_info(frame_path)

        assert result["detection_method"] == "fallback"
        assert result["caller_name"] == "script"
        assert result["caller_path"] == frame_path
        assert result["json_folder"] is None

    @patch("aipass.api.apps.handlers.openrouter.caller.logger", autospec=True)
    def test_category_from_detect_caller_category(self, _mock_logger: MagicMock, tmp_path: Path) -> None:
        """Fallback delegates category detection to detect_caller_category."""
        flow_path = tmp_path / "a" / "flow" / "thing.py"
        result = _create_fallback_info(flow_path)

        assert result["category"] == "flow"

    @patch("aipass.api.apps.handlers.openrouter.caller.logger", autospec=True)
    def test_unknown_category_fallback(self, _mock_logger: MagicMock, tmp_path: Path) -> None:
        """Path without flow/prax yields category='unknown'."""
        other_path = tmp_path / "some_tool.py"
        result = _create_fallback_info(other_path)

        assert result["category"] == "unknown"


# =============================================
# detect_caller_from_stack tests
# =============================================


class TestDetectCallerFromStack:
    """Tests for caller.detect_caller_from_stack()."""

    @patch("aipass.api.apps.handlers.openrouter.caller.get_caller_info")
    def test_returns_name_and_folder_when_info_available(self, mock_get_info: MagicMock, tmp_path: Path) -> None:
        """When get_caller_info returns data, extracts name and folder."""
        json_folder = tmp_path / "flow" / "flow_json"
        mock_get_info.return_value = {
            "caller_name": "engine",
            "json_folder": json_folder,
        }

        name, folder = detect_caller_from_stack()

        assert name == "engine"
        assert folder == json_folder

    @patch("aipass.api.apps.handlers.openrouter.caller.get_caller_info")
    def test_returns_none_tuple_when_no_info(self, mock_get_info: MagicMock) -> None:
        """When get_caller_info returns None, returns (None, None)."""
        mock_get_info.return_value = None

        name, folder = detect_caller_from_stack()

        assert name is None
        assert folder is None


# =============================================
# get_caller_info tests
# =============================================


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
