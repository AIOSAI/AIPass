# =================== AIPass ====================
# Name: test_tier0_kernel.py
# Version: 1.1.0
# Description: Tests for tier0_kernel prompt handler
# Branch: hooks
# Created: 2026-06-18
# Modified: 2026-09-16
# =============================================

"""Tests for handlers/prompt/tier0_kernel.py."""

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


class TestTier0KernelHandler:
    def test_loads_tier0_kernel(self, tmp_path, monkeypatch):
        from aipass.hooks.apps.handlers.prompt.tier0_kernel import handle

        aipass_dir = tmp_path / ".aipass"
        aipass_dir.mkdir()
        prompt = aipass_dir / "tier0_kernel.md"
        prompt.write_text("# Tier 0 Kernel\nAlways on", encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        with patch.dict("os.environ", {"AIPASS_HOME": str(tmp_path)}):
            with _patch_cadence(_mock_cadence(True)):
                result = handle({})

        assert result["exit_code"] == 0
        assert "Tier 0 Kernel" in result["stdout"]
        assert "Always on" in result["stdout"]
        assert result["sound"] == "tier0 kernel"

    def test_returns_empty_when_file_missing(self, tmp_path, monkeypatch):
        from aipass.hooks.apps.handlers.prompt.tier0_kernel import handle

        monkeypatch.chdir(tmp_path)
        with patch.dict("os.environ", {"AIPASS_HOME": str(tmp_path)}):
            with _patch_cadence(_mock_cadence(True)):
                result = handle({})

        assert result["exit_code"] == 0
        assert result["stdout"] == ""
        assert "sound" not in result

    def test_empty_hook_data(self, tmp_path, monkeypatch):
        from aipass.hooks.apps.handlers.prompt.tier0_kernel import handle

        aipass_dir = tmp_path / ".aipass"
        aipass_dir.mkdir()
        (aipass_dir / "tier0_kernel.md").write_text("content", encoding="utf-8")
        # A whole stamped tree: a kernel with no navmap beside it is a degraded
        # tree now, and this test is about the empty payload, not the banner.
        (aipass_dir / "tier1_navmap.md").write_text("navmap", encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        with patch.dict("os.environ", {"AIPASS_HOME": str(tmp_path)}):
            with _patch_cadence(_mock_cadence(True)):
                result = handle({})

        assert result["exit_code"] == 0
        assert result["stdout"] == "content"

    def test_skips_on_cadence_skip(self, tmp_path, monkeypatch):
        from aipass.hooks.apps.handlers.prompt.tier0_kernel import handle

        aipass_dir = tmp_path / ".aipass"
        aipass_dir.mkdir()
        (aipass_dir / "tier0_kernel.md").write_text("content", encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        with patch.dict("os.environ", {"AIPASS_HOME": str(tmp_path)}):
            with _patch_cadence(_mock_cadence(False)):
                result = handle({})

        assert result["stdout"] == ""
        assert result["exit_code"] == 0
        assert "sound" not in result

    def test_fires_anyway_on_cadence_error(self, tmp_path, monkeypatch):
        from aipass.hooks.apps.handlers.prompt.tier0_kernel import handle

        aipass_dir = tmp_path / ".aipass"
        aipass_dir.mkdir()
        (aipass_dir / "tier0_kernel.md").write_text("kernel content", encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        with patch.dict("os.environ", {"AIPASS_HOME": str(tmp_path)}):
            with _patch_cadence(error=ImportError("no cadence")):
                result = handle({})

        assert result["exit_code"] == 0
        assert "kernel content" in result["stdout"]

    def test_external_project_gets_own_file(self, tmp_path, monkeypatch):
        from aipass.hooks.apps.handlers.prompt.tier0_kernel import handle

        project = tmp_path / "my-project"
        project.mkdir()
        aipass_dir = project / ".aipass"
        aipass_dir.mkdir()
        (aipass_dir / "tier0_kernel.md").write_text("# Project Kernel", encoding="utf-8")
        monkeypatch.chdir(project)

        with patch.dict("os.environ", {"AIPASS_HOME": "/some/other/path"}):
            with _patch_cadence(_mock_cadence(True)):
                result = handle({})

        assert result["exit_code"] == 0
        assert "Project Kernel" in result["stdout"]
        assert result["sound"] == "tier0 kernel"

    def test_cadence_called_with_tier0_name(self, tmp_path, monkeypatch):
        from aipass.hooks.apps.handlers.prompt.tier0_kernel import handle

        monkeypatch.chdir(tmp_path)
        mock = _mock_cadence(False)

        with patch.dict("os.environ", {"AIPASS_HOME": str(tmp_path)}):
            with _patch_cadence(mock):
                handle({"some": "data"})

        mock.should_fire.assert_called_once_with("tier0", {"some": "data"})


class TestDegradedGroundingIsLoud:
    """DPLAN-0347, hooks row 1: the kernel carries the news when grounding this seat was promised did not load.

    Both directions are pinned, because the silent side is the one that was
    measured: four of four stamped projects on the machine this shipped from
    carry no branch prompt and no passport by design, and a banner there on
    every beat would be a permanent false alarm.
    """

    @staticmethod
    def _stamped(root, *, kernel=True, navmap=True):
        aipass_dir = root / ".aipass"
        aipass_dir.mkdir(parents=True, exist_ok=True)
        if kernel:
            (aipass_dir / "tier0_kernel.md").write_text("KERNEL", encoding="utf-8")
        if navmap:
            (aipass_dir / "tier1_navmap.md").write_text("NAVMAP", encoding="utf-8")
        return root

    def test_a_whole_stamped_project_that_is_not_a_branch_hears_nothing(self, tmp_path, monkeypatch):
        from aipass.hooks.apps.handlers.prompt.tier0_kernel import handle

        project = self._stamped(tmp_path / "project")
        monkeypatch.chdir(project)
        with patch.dict("os.environ", {"AIPASS_HOME": ""}), _patch_cadence(_mock_cadence(True)):
            result = handle({"cwd": str(project)})

        assert result["stdout"] == "KERNEL"

    def test_a_branch_missing_its_prompt_gets_the_kernel_and_the_reason(self, tmp_path, monkeypatch):
        from aipass.hooks.apps.handlers.prompt.tier0_kernel import handle

        project = self._stamped(tmp_path / "project")
        seat = project / "src" / "pkg" / "seat"
        (seat / ".trinity").mkdir(parents=True)
        (seat / ".trinity" / "passport.json").write_text('{"identity": {"role": "r"}}', encoding="utf-8")
        monkeypatch.chdir(seat)
        with patch.dict("os.environ", {"AIPASS_HOME": ""}), _patch_cadence(_mock_cadence(True)):
            result = handle({"cwd": str(seat)})

        out = result["stdout"]
        assert out.startswith("[GROUNDING DEGRADED")
        assert "branch: seat is a branch but .aipass/aipass_local_prompt.md is missing" in out
        assert "Carried: identity, kernel, navmap." in out
        assert out.endswith("KERNEL"), "the kernel still goes out, after the banner"

    def test_a_corrupt_passport_is_named_with_the_parse_error(self, tmp_path, monkeypatch):
        from aipass.hooks.apps.handlers.prompt.tier0_kernel import handle

        project = self._stamped(tmp_path / "project")
        seat = project / "src" / "pkg" / "seat"
        (seat / ".aipass").mkdir(parents=True)
        (seat / ".aipass" / "aipass_local_prompt.md").write_text("PROMPT", encoding="utf-8")
        (seat / ".trinity").mkdir()
        (seat / ".trinity" / "passport.json").write_text("{not json", encoding="utf-8")
        monkeypatch.chdir(seat)
        with patch.dict("os.environ", {"AIPASS_HOME": ""}), _patch_cadence(_mock_cadence(True)):
            result = handle({"cwd": str(seat)})

        assert "identity: loading it raised JSONDecodeError" in result["stdout"]

    def test_a_missing_kernel_still_says_why_instead_of_going_quiet(self, tmp_path, monkeypatch):
        from aipass.hooks.apps.handlers.prompt.tier0_kernel import handle

        project = self._stamped(tmp_path / "project", kernel=False)
        monkeypatch.chdir(project)
        with patch.dict("os.environ", {"AIPASS_HOME": ""}), _patch_cadence(_mock_cadence(True)):
            result = handle({"cwd": str(project)})

        assert result["stdout"].startswith("[GROUNDING DEGRADED")
        assert "kernel: this tree is AIPass-stamped but .aipass/tier0_kernel.md is missing" in result["stdout"]
        assert result["sound"] == "tier0 kernel"

    def test_the_banner_never_carries_the_home_directory(self, tmp_path, monkeypatch):
        from pathlib import Path

        from aipass.hooks.apps.modules import grounding_content

        with patch.object(grounding_content, "load_kernel", side_effect=OSError(f"denied: {Path.home()}/x")):
            _, failures = grounding_content.grounding_report({"cwd": str(tmp_path)})

        assert failures and str(Path.home()) not in failures[0]
        assert "~/x" in failures[0]


class TestCadenceDegradedMode:
    """DPLAN-0347 row 1, the room's ruling: when cadence cannot count, the kernel fires alone and says so."""

    @staticmethod
    def _project(root):
        aipass_dir = root / ".aipass"
        aipass_dir.mkdir(parents=True)
        (aipass_dir / "tier0_kernel.md").write_text("KERNEL", encoding="utf-8")
        (aipass_dir / "tier1_navmap.md").write_text("NAVMAP", encoding="utf-8")
        return root

    def test_a_degraded_cadence_puts_the_reason_on_the_kernel(self, tmp_path, monkeypatch):
        from aipass.hooks.apps.handlers.prompt.tier0_kernel import handle

        project = self._project(tmp_path / "project")
        monkeypatch.chdir(project)
        cadence = _mock_cadence(True)
        cadence.degraded_reason.return_value = "no CLAUDE_CODE_SESSION_ID in the environment"
        with patch.dict("os.environ", {"AIPASS_HOME": ""}), _patch_cadence(cadence):
            result = handle({"cwd": str(project)})

        out = result["stdout"]
        assert out.startswith("[GROUNDING DEGRADED")
        assert "Carried: kernel." in out, "navmap loaded but is withheld, so it is not carried"
        assert "navmap, branch, identity: WITHHELD" in out and "CLAUDE_CODE_SESSION_ID" in out
        assert out.endswith("KERNEL")

    def test_a_cadence_that_will_not_import_still_gets_the_kernel_out_with_the_cause(self, tmp_path, monkeypatch):
        from aipass.hooks.apps.handlers.prompt.tier0_kernel import handle

        project = self._project(tmp_path / "project")
        monkeypatch.chdir(project)
        with patch.dict("os.environ", {"AIPASS_HOME": ""}), _patch_cadence(error=ImportError("no cadence")):
            result = handle({"cwd": str(project)})

        assert "the cadence module raised ImportError: no cadence" in result["stdout"]
        assert result["stdout"].endswith("KERNEL")

    def test_a_healthy_cadence_adds_nothing(self, tmp_path, monkeypatch):
        from aipass.hooks.apps.handlers.prompt.tier0_kernel import handle

        project = self._project(tmp_path / "project")
        monkeypatch.chdir(project)
        cadence = _mock_cadence(True)
        cadence.degraded_reason.return_value = None
        with patch.dict("os.environ", {"AIPASS_HOME": ""}), _patch_cadence(cadence):
            assert handle({"cwd": str(project)})["stdout"] == "KERNEL"
