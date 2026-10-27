# =================== AIPass ====================
# Name: test_navmap.py
# Version: 1.2.0
# Description: Tests for navmap prompt handler and its edit-time cap warning
# Branch: hooks
# Created: 2026-06-18
# Modified: 2026-10-26
# =============================================

"""Tests for apps/handlers/prompt/navmap.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(documentation) — that load_content() and handle() carry docstrings
# seedgo: no-test-needed(ruff) — that the module parses and its logger import resolves
# seedgo: no-test-needed(generated) — the navmap text itself; grounding_content.load_navmap reads it from disk

import contextlib
import json
import sys
from collections.abc import Iterator
from typing import Any
from unittest.mock import patch, MagicMock

import pytest

from aipass.hooks.apps.handlers.prompt.navmap import NAVMAP_CHAR_CAP, handle, handle_edit

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


def _navmap(root, chars: int):
    navmap = root / ".aipass" / "tier1_navmap.md"
    navmap.parent.mkdir(parents=True, exist_ok=True)
    navmap.write_text("x" * chars, encoding="utf-8")
    return navmap


class TestNavmapCapWarning:
    def test_an_edit_over_the_cap_names_the_file_and_the_count(self, tmp_path):
        navmap = _navmap(tmp_path, NAVMAP_CHAR_CAP + 422)
        result = handle_edit({"tool_name": "Edit", "tool_input": {"file_path": str(navmap)}})
        context = json.loads(result["stdout"])["hookSpecificOutput"]["additionalContext"]
        assert str(navmap) in context
        assert f"{NAVMAP_CHAR_CAP + 422:,} chars, 422 over" in context
        assert result["exit_code"] == 0

    def test_an_edit_at_the_cap_is_silent(self, tmp_path):
        navmap = _navmap(tmp_path, NAVMAP_CHAR_CAP)
        assert handle_edit({"tool_name": "Write", "tool_input": {"file_path": str(navmap)}})["stdout"] == ""

    def test_another_file_over_the_cap_is_silent(self, tmp_path):
        other = tmp_path / ".aipass" / "tier0_kernel.md"
        other.parent.mkdir()
        other.write_text("x" * (NAVMAP_CHAR_CAP + 1), encoding="utf-8")
        assert handle_edit({"tool_name": "Edit", "tool_input": {"file_path": str(other)}})["stdout"] == ""

    def test_a_shell_write_over_the_cap_is_caught(self, tmp_path):
        navmap = _navmap(tmp_path, NAVMAP_CHAR_CAP + 1)
        hook_data = {
            "tool_name": "Bash",
            "tool_input": {"command": "echo more >> .aipass/tier1_navmap.md"},
            "cwd": str(tmp_path),
        }
        assert str(navmap) in json.loads(handle_edit(hook_data)["stdout"])["systemMessage"]
