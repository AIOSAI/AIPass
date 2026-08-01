# =================== AIPass ====================
# Name: test_branch_loader.py
# Version: 1.0.0
# Description: Tests for branch_loader prompt handler
# Branch: hooks
# Created: 2026-05-22
# Modified: 2026-05-22
# =============================================

"""Tests for handlers/prompt/branch_loader.py."""

import importlib
from pathlib import Path
from unittest.mock import patch, MagicMock

_real_import_module = importlib.import_module
_CADENCE_MODULE = "aipass.hooks.apps.modules.cadence"


def _mock_cadence_fires():
    """Return a mock cadence module where should_fire always returns True."""
    mock = MagicMock()
    mock.should_fire.return_value = True
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


class TestBranchLoaderHandler:
    def test_loads_branch_prompt(self, tmp_path):
        from aipass.hooks.apps.handlers.prompt.branch_loader import handle

        trinity = tmp_path / ".trinity"
        trinity.mkdir()
        aipass_dir = tmp_path / ".aipass"
        aipass_dir.mkdir()
        prompt = aipass_dir / "aipass_local_prompt.md"
        prompt.write_text("# Test Branch\nSome instructions", encoding="utf-8")

        with _patch_cadence(_mock_cadence_fires()):
            result = handle({"cwd": str(tmp_path)})

        assert result["exit_code"] == 0
        assert "Branch Context:" in result["stdout"]
        assert "Some instructions" in result["stdout"]
        assert result["sound"] == "branch prompt"

    def test_loads_private_integrations(self, tmp_path):
        from aipass.hooks.apps.handlers.prompt.branch_loader import handle

        trinity = tmp_path / ".trinity"
        trinity.mkdir()
        integration = tmp_path / "apps" / "integrations" / "test_int"
        integration.mkdir(parents=True)
        private = integration / "private_prompt.md"
        private.write_text("# Private Integration\nSecret stuff", encoding="utf-8")

        with _patch_cadence(_mock_cadence_fires()):
            result = handle({"cwd": str(tmp_path)})

        assert "Private Integration" in result["stdout"]
        assert result["sound"] == "branch prompt"

    def test_loads_both_prompt_and_integrations(self, tmp_path):
        from aipass.hooks.apps.handlers.prompt.branch_loader import handle

        trinity = tmp_path / ".trinity"
        trinity.mkdir()
        aipass_dir = tmp_path / ".aipass"
        aipass_dir.mkdir()
        (aipass_dir / "aipass_local_prompt.md").write_text("Branch prompt", encoding="utf-8")
        integration = tmp_path / "apps" / "integrations" / "compass"
        integration.mkdir(parents=True)
        (integration / "private_prompt.md").write_text("Compass prompt", encoding="utf-8")

        with _patch_cadence(_mock_cadence_fires()):
            result = handle({"cwd": str(tmp_path)})

        assert "Branch prompt" in result["stdout"]
        assert "Compass prompt" in result["stdout"]

    def test_returns_empty_when_no_branch_root(self, tmp_path):
        from aipass.hooks.apps.handlers.prompt.branch_loader import handle

        with _patch_cadence(_mock_cadence_fires()):
            result = handle({"cwd": str(tmp_path)})

        assert result["stdout"] == ""
        assert "sound" not in result

    def test_stops_at_repo_root(self, tmp_path):
        from aipass.hooks.apps.handlers.prompt.branch_loader import handle

        (tmp_path / ".git").mkdir()
        nested = tmp_path / "some" / "deep" / "path"
        nested.mkdir(parents=True)

        with _patch_cadence(_mock_cadence_fires()):
            result = handle({"cwd": str(nested)})

        assert result["stdout"] == ""
        assert "sound" not in result

    def test_walks_up_to_find_branch(self, tmp_path):
        from aipass.hooks.apps.handlers.prompt.branch_loader import handle

        trinity = tmp_path / ".trinity"
        trinity.mkdir()
        aipass_dir = tmp_path / ".aipass"
        aipass_dir.mkdir()
        (aipass_dir / "aipass_local_prompt.md").write_text("Found it", encoding="utf-8")
        nested = tmp_path / "apps" / "handlers" / "security"
        nested.mkdir(parents=True)

        with _patch_cadence(_mock_cadence_fires()):
            result = handle({"cwd": str(nested)})

        assert "Found it" in result["stdout"]

    def test_empty_hook_data(self):
        from aipass.hooks.apps.handlers.prompt.branch_loader import handle

        # Path.cwd patch must be OUTSIDE the importlib patch — mock.patch uses
        # importlib.import_module to resolve "pathlib", which the inner mock hijacks.
        with patch("pathlib.Path.cwd", return_value=Path("/tmp/nonexistent")):
            with _patch_cadence(_mock_cadence_fires()):
                result = handle({})

        assert result["exit_code"] == 0
        assert result["stdout"] == ""
        assert "sound" not in result

    def test_no_prompt_file_but_has_branch_root(self, tmp_path):
        from aipass.hooks.apps.handlers.prompt.branch_loader import handle

        trinity = tmp_path / ".trinity"
        trinity.mkdir()

        with _patch_cadence(_mock_cadence_fires()):
            result = handle({"cwd": str(tmp_path)})

        assert result["stdout"] == ""
        assert "sound" not in result

    def test_includes_source_path_in_output(self, tmp_path):
        from aipass.hooks.apps.handlers.prompt.branch_loader import handle

        trinity = tmp_path / ".trinity"
        trinity.mkdir()
        aipass_dir = tmp_path / ".aipass"
        aipass_dir.mkdir()
        (aipass_dir / "aipass_local_prompt.md").write_text("content", encoding="utf-8")

        with _patch_cadence(_mock_cadence_fires()):
            result = handle({"cwd": str(tmp_path)})

        assert "Source:" in result["stdout"]
