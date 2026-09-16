# =================== AIPass ====================
# Name: test_branch_loader.py
# Version: 1.1.0
# Description: Tests for branch_loader prompt handler (injection caps since 1.1.0)
# Branch: hooks
# Created: 2026-05-22
# Modified: 2026-09-15
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


class TestInjectedBlocksStayUnderTheirCaps:
    """DPLAN-0347 row 2: the branch block is capped at 9,000 chars, each integration prompt at 2,000.

    Patrick ruled the layer contract on 2026-09-15. The number is measured, not
    chosen: Claude Code persists a hook output over 10,000 UTF-16 units to a file
    and hands the model a 2,000-char preview, so a prompt that crosses the line
    is not read at all. A cut with a marker naming the file keeps the first
    9,000 chars live and tells the reader where the rest is.
    """

    @staticmethod
    def _seat(tmp_path, body):
        (tmp_path / ".trinity").mkdir()
        aipass_dir = tmp_path / ".aipass"
        aipass_dir.mkdir()
        (aipass_dir / "aipass_local_prompt.md").write_text(body, encoding="utf-8")
        return aipass_dir / "aipass_local_prompt.md"

    def _render(self, tmp_path):
        from aipass.hooks.apps.handlers.prompt.branch_loader import handle

        with _patch_cadence(_mock_cadence_fires()):
            return handle({"cwd": str(tmp_path)})["stdout"]

    def test_an_over_budget_prompt_is_cut_and_the_marker_names_the_file(self, tmp_path):
        prompt = self._seat(tmp_path, "\n".join(f"line {n} " + "x" * 80 for n in range(200)))
        rendered = self._render(tmp_path)

        assert len(rendered) <= 9000, f"branch block rendered {len(rendered)} chars"
        assert "cut at 9000 chars" in rendered
        assert str(prompt) in rendered, "a cut block must say where the rest lives"

    def test_a_prompt_under_the_budget_is_untouched(self, tmp_path):
        self._seat(tmp_path, "# Small\nbreadcrumbs only")
        rendered = self._render(tmp_path)

        assert "breadcrumbs only" in rendered
        assert "cut at" not in rendered

    def test_each_integration_prompt_is_capped_on_its_own(self, tmp_path):
        """Zero are live fleet-wide; the first one written is the one that would have blown the block."""
        self._seat(tmp_path, "# Small\nbreadcrumbs only")
        for name in ("alpha", "beta"):
            integration = tmp_path / "apps" / "integrations" / name
            integration.mkdir(parents=True)
            (integration / "private_prompt.md").write_text(f"{name}\n" + "y" * 5000, encoding="utf-8")

        rendered = self._render(tmp_path)

        assert rendered.count("cut at 2000 chars") == 2, "each prompt is cut against its own budget"
        assert "alpha" in rendered and "beta" in rendered
        assert len(rendered) < 4500, f"two capped integrations rendered {len(rendered)} chars"

    def test_the_cut_lands_on_a_line_boundary(self, tmp_path):
        self._seat(tmp_path, "\n".join(f"line {n}" for n in range(3000)))
        rendered = self._render(tmp_path)
        head = rendered.split("\n[… cut at")[0]

        assert head.endswith(tuple(str(d) for d in range(10))), "a block never stops mid-word"
