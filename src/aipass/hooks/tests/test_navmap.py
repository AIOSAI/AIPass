# =================== AIPass ====================
# Name: test_navmap.py
# Version: 1.0.0
# Description: Tests for navmap prompt handler
# Branch: hooks
# Created: 2026-06-18
# Modified: 2026-06-18
# =============================================

"""Tests for handlers/prompt/navmap.py."""

import importlib
from unittest.mock import patch, MagicMock

_real_import_module = importlib.import_module
_CADENCE_MODULE = "aipass.hooks.apps.modules.cadence"


def _mock_cadence(fires: bool = True):
    """Return a mock cadence module with configurable should_fire."""
    mock = MagicMock()
    mock.should_fire.return_value = fires
    return mock


def _patch_cadence(cadence_mock=None, error=None):
    """Patch only the cadence import — load_content's own importlib.import_module
    call (for grounding_content) must still resolve to the real module."""

    def _side_effect(name, *args, **kwargs):
        if name == _CADENCE_MODULE:
            if error is not None:
                raise error
            return cadence_mock
        return _real_import_module(name, *args, **kwargs)

    return patch("importlib.import_module", side_effect=_side_effect)


class TestNavmapHandler:
    def test_loads_navmap(self, tmp_path, monkeypatch):
        from aipass.hooks.apps.handlers.prompt.navmap import handle

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
        from aipass.hooks.apps.handlers.prompt.navmap import handle

        monkeypatch.chdir(tmp_path)
        with patch.dict("os.environ", {"AIPASS_HOME": str(tmp_path)}):
            with _patch_cadence(_mock_cadence(True)):
                result = handle({})

        assert result["exit_code"] == 0
        assert result["stdout"] == ""
        assert "sound" not in result

    def test_empty_hook_data(self, tmp_path, monkeypatch):
        from aipass.hooks.apps.handlers.prompt.navmap import handle

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
        from aipass.hooks.apps.handlers.prompt.navmap import handle

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

    def test_fires_anyway_on_cadence_error(self, tmp_path, monkeypatch):
        from aipass.hooks.apps.handlers.prompt.navmap import handle

        aipass_dir = tmp_path / ".aipass"
        aipass_dir.mkdir()
        (aipass_dir / "tier1_navmap.md").write_text("navmap content", encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        with patch.dict("os.environ", {"AIPASS_HOME": str(tmp_path)}):
            with _patch_cadence(error=ImportError("no cadence")):
                result = handle({})

        assert result["exit_code"] == 0
        assert "navmap content" in result["stdout"]

    def test_external_project_gets_own_file(self, tmp_path, monkeypatch):
        from aipass.hooks.apps.handlers.prompt.navmap import handle

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
        from aipass.hooks.apps.handlers.prompt.navmap import handle

        monkeypatch.chdir(tmp_path)
        mock = _mock_cadence(False)

        with patch.dict("os.environ", {"AIPASS_HOME": str(tmp_path)}):
            with _patch_cadence(mock):
                handle({"some": "data"})

        mock.should_fire.assert_called_once_with("navmap", {"some": "data"})
