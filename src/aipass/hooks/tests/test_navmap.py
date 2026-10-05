# =================== AIPass ====================
# Name: test_navmap.py
# Version: 1.1.2
# Description: Tests for navmap prompt handler
# Branch: hooks
# Created: 2026-06-18
# Modified: 2026-10-05
# =============================================

"""Tests for apps/handlers/prompt/navmap.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(documentation) — that load_content() and handle() carry docstrings
# seedgo: no-test-needed(ruff) — that the module parses and its logger import resolves
# seedgo: no-test-needed(generated) — the navmap text itself; grounding_content.load_navmap reads it from disk

import contextlib
import sys
from collections.abc import Iterator
from typing import Any
from unittest.mock import patch, MagicMock

import pytest

from aipass.hooks.apps.handlers.prompt.navmap import handle

_CADENCE_MODULE = "aipass.hooks.apps.modules.cadence"


def _mock_cadence(fires: bool = True):
    """Return a mock cadence module with configurable should_fire."""
    mock = MagicMock()
    mock.should_fire.return_value = fires
    return mock


@contextlib.contextmanager
def _patch_cadence(cadence_mock: Any = None, missing: bool = False) -> Iterator[None]:
    """Stand the cadence module in sys.modules, where the real import_module looks first.

    importlib itself is never replaced (fleet green leg 7, stdlib_patch), so
    load_content's own import of grounding_content resolves to the real module.
    missing=True registers None under the name: the real import then raises
    ModuleNotFoundError, the stdlib's documented answer for a None entry.
    """
    with pytest.MonkeyPatch.context() as mp:
        if missing:
            mp.setitem(sys.modules, _CADENCE_MODULE, None)
        else:
            cadence_mock.__spec__ = None  # a MagicMock's __spec__ reads as a module still initializing
            mp.setitem(sys.modules, _CADENCE_MODULE, cadence_mock)
        yield


class TestNavmapHandler:
    def test_loads_navmap(self, tmp_path, monkeypatch):
        aipass_dir = tmp_path / ".aipass"
        aipass_dir.mkdir()
        prompt = aipass_dir / "tier1_navmap.md"
        prompt.write_text("# Navigation Map\nAgents and services", encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        with patch.dict("os.environ", {"AIPASS_HOME": str(tmp_path)}):
            with _patch_cadence(_mock_cadence(True)):
                result = handle({})

        assert result["exit_code"] == 0
        assert "Navigation Map" in result["stdout"]
        assert "Agents and services" in result["stdout"]
        assert result["sound"] == "navmap"

    def test_returns_empty_when_file_missing(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with patch.dict("os.environ", {"AIPASS_HOME": str(tmp_path)}):
            with _patch_cadence(_mock_cadence(True)):
                result = handle({})

        assert result["exit_code"] == 0
        assert result["stdout"] == ""
        assert "sound" not in result

    def test_empty_hook_data(self, tmp_path, monkeypatch):
        aipass_dir = tmp_path / ".aipass"
        aipass_dir.mkdir()
        (aipass_dir / "tier1_navmap.md").write_text("navmap content", encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        with patch.dict("os.environ", {"AIPASS_HOME": str(tmp_path)}):
            with _patch_cadence(_mock_cadence(True)):
                result = handle({})

        assert result["exit_code"] == 0
        assert result["stdout"] == "navmap content"

    def test_skips_on_cadence_skip(self, tmp_path, monkeypatch):
        aipass_dir = tmp_path / ".aipass"
        aipass_dir.mkdir()
        (aipass_dir / "tier1_navmap.md").write_text("content", encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        with patch.dict("os.environ", {"AIPASS_HOME": str(tmp_path)}):
            with _patch_cadence(_mock_cadence(False)):
                result = handle({})

        assert result["stdout"] == ""
        assert result["exit_code"] == 0
        assert "sound" not in result

    def test_is_withheld_on_cadence_error(self, tmp_path, monkeypatch):
        """The degraded fail mode (DPLAN-0347): the kernel fires alone and says why."""
        aipass_dir = tmp_path / ".aipass"
        aipass_dir.mkdir()
        (aipass_dir / "tier1_navmap.md").write_text("navmap content", encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        with patch.dict("os.environ", {"AIPASS_HOME": str(tmp_path)}):
            with _patch_cadence(missing=True):
                result = handle({})

        assert result == {"stdout": "", "exit_code": 0}

    def test_external_project_gets_own_file(self, tmp_path, monkeypatch):
        project = tmp_path / "my-project"
        project.mkdir()
        aipass_dir = project / ".aipass"
        aipass_dir.mkdir()
        (aipass_dir / "tier1_navmap.md").write_text("# Project Navmap", encoding="utf-8")
        monkeypatch.chdir(project)

        with patch.dict("os.environ", {"AIPASS_HOME": "/some/other/path"}):
            with _patch_cadence(_mock_cadence(True)):
                result = handle({})

        assert result["exit_code"] == 0
        assert "Project Navmap" in result["stdout"]
        assert result["sound"] == "navmap"

    def test_cadence_called_with_navmap_name(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        mock = _mock_cadence(False)

        with patch.dict("os.environ", {"AIPASS_HOME": str(tmp_path)}):
            with _patch_cadence(mock):
                handle({"some": "data"})

        mock.should_fire.assert_called_once_with("navmap", {"some": "data"})
