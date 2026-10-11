# =================== AIPass ====================
# Name: test_git_module_merge.py
# Description: Tests for the merge and branches lane — protected-branch merge, return to dev, fetch-prune
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-08
# =============================================

"""Tests for apps/plugins/devpulse_ops/merge_plugin.py and apps/handlers/git/branches_handler.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(stdlib) — subprocess.run, which every git and gh call here reaches as a recorded stub

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from aipass.drone.apps.handlers.git.branches_handler import list_remote_branches, prune_temp_branches
from aipass.drone.apps.plugins.devpulse_ops.merge_plugin import merge_pr
from aipass.trigger.apps.modules import core as trigger_core


# ===========================================================================
# Fix 1 & 2: Protected-branch merge + return-to-dev (#625)
# ===========================================================================

_MERGE_MOD = "aipass.drone.apps.plugins.devpulse_ops.merge_plugin"


@pytest.fixture
def merge_bus(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Stand a recorder where merge_pr binds the bus, so no merge test fires the live one.

    merge_pr imports ``trigger`` from trigger's core at call time; replacing it at that
    home is what the call reaches (the leg-3 bus probe counted these five on the bus).
    """
    bus = MagicMock()
    monkeypatch.setattr(trigger_core, "trigger", bus)
    return bus


def _merge_side_effect(head_ref: str, current_branch: str = "main"):
    """Build a subprocess mock for merge_pr with configurable head ref."""

    def _run(cmd: list[str], **kwargs: object) -> MagicMock:
        r = MagicMock()
        r.returncode = 0
        r.stderr = ""
        r.stdout = ""
        if cmd[0] == "gh" and "view" in cmd:
            if ".headRefName" in cmd:
                r.stdout = f"{head_ref}\n"
            else:
                r.stdout = "PR Title\n"
        elif cmd[1:3] == ["rev-parse", "HEAD"]:
            r.stdout = "abc123\n"
        elif cmd[1:3] == ["rev-parse", "--abbrev-ref"]:
            r.stdout = f"{current_branch}\n"
        elif cmd[1:3] == ["checkout", "dev"]:
            r.returncode = 0
        return r

    return _run


class TestMergeProtectedBranch:
    """Fix 1: --delete-branch omitted for protected branches (dev, main)."""

    def test_dev_head_no_delete_branch(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, merge_bus: MagicMock
    ) -> None:
        """When PR head is dev, merge command must NOT include --delete-branch."""
        registry = tmp_path / "AIPASS_REGISTRY.json"
        registry.write_text("{}", encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        calls: list[list[str]] = []

        def _capture(cmd: list[str], **kw: object) -> MagicMock:
            calls.append(list(cmd))
            return _merge_side_effect("dev", "dev")(cmd, **kw)

        with patch(f"{_MERGE_MOD}.subprocess.run", side_effect=_capture):
            result = merge_pr("10", "devpulse")

        assert result["success"] is True
        merge_calls = [c for c in calls if c[:3] == ["gh", "pr", "merge"]]
        assert len(merge_calls) == 1
        assert "--delete-branch" not in merge_calls[0]
        merge_bus.fire.assert_called_once_with("pr_merged", pr_number="10", title="PR Title")

    def test_temp_branch_has_delete_branch(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, merge_bus: MagicMock
    ) -> None:
        """When PR head is a temp branch, merge command includes --delete-branch."""
        registry = tmp_path / "AIPASS_REGISTRY.json"
        registry.write_text("{}", encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        calls: list[list[str]] = []

        def _capture(cmd: list[str], **kw: object) -> MagicMock:
            calls.append(list(cmd))
            return _merge_side_effect("citizen/feature-x", "dev")(cmd, **kw)

        with patch(f"{_MERGE_MOD}.subprocess.run", side_effect=_capture):
            result = merge_pr("20", "devpulse")

        assert result["success"] is True
        merge_calls = [c for c in calls if c[:3] == ["gh", "pr", "merge"]]
        assert "--delete-branch" in merge_calls[0]
        merge_bus.fire.assert_called_once_with("pr_merged", pr_number="20", title="PR Title")

    def test_unknown_head_ref_fails_safe_no_delete(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, merge_bus: MagicMock
    ) -> None:
        """When the PR head ref can't be determined (empty), fail SAFE: never delete.

        Guards the exact path that destroyed `dev` in S183 — if gh can't report
        the head ref we must not fall back to deleting the branch.
        """
        registry = tmp_path / "AIPASS_REGISTRY.json"
        registry.write_text("{}", encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        calls: list[list[str]] = []

        def _capture(cmd: list[str], **kw: object) -> MagicMock:
            calls.append(list(cmd))
            return _merge_side_effect("", "dev")(cmd, **kw)

        with patch(f"{_MERGE_MOD}.subprocess.run", side_effect=_capture):
            result = merge_pr("30", "devpulse")

        assert result["success"] is True
        merge_calls = [c for c in calls if c[:3] == ["gh", "pr", "merge"]]
        assert len(merge_calls) == 1
        assert "--delete-branch" not in merge_calls[0]
        merge_bus.fire.assert_called_once_with("pr_merged", pr_number="30", title="PR Title")


class TestMergeReturnToDev:
    """Fix 2: After merge+sync, checkout dev (or warn if can't)."""

    def test_checkout_dev_after_merge(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, merge_bus: MagicMock
    ) -> None:
        """merge_pr issues 'git checkout dev' when not already on dev."""
        registry = tmp_path / "AIPASS_REGISTRY.json"
        registry.write_text("{}", encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        calls: list[list[str]] = []

        def _capture(cmd: list[str], **kw: object) -> MagicMock:
            calls.append(list(cmd))
            return _merge_side_effect("citizen/x", "main")(cmd, **kw)

        with patch(f"{_MERGE_MOD}.subprocess.run", side_effect=_capture):
            result = merge_pr("30", "devpulse")

        assert result["success"] is True
        checkout_calls = [c for c in calls if c[1:3] == ["checkout", "dev"]]
        assert len(checkout_calls) == 1
        merge_bus.fire.assert_called_once_with("pr_merged", pr_number="30", title="PR Title")

    def test_no_checkout_when_already_on_dev(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, merge_bus: MagicMock
    ) -> None:
        """merge_pr skips checkout dev when already on dev."""
        registry = tmp_path / "AIPASS_REGISTRY.json"
        registry.write_text("{}", encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        calls: list[list[str]] = []

        def _capture(cmd: list[str], **kw: object) -> MagicMock:
            calls.append(list(cmd))
            return _merge_side_effect("citizen/y", "dev")(cmd, **kw)

        with patch(f"{_MERGE_MOD}.subprocess.run", side_effect=_capture):
            result = merge_pr("31", "devpulse")

        assert result["success"] is True
        checkout_calls = [c for c in calls if c[1:3] == ["checkout", "dev"]]
        assert len(checkout_calls) == 0
        merge_bus.fire.assert_called_once_with("pr_merged", pr_number="31", title="PR Title")


# ===========================================================================
# Fix 3: Live-remote branches — fetch --prune before listing (#625)
# ===========================================================================

_BRANCHES_MOD = "aipass.drone.apps.handlers.git.branches_handler"


class TestBranchesFetchPrune:
    """Fix 3: list_remote_branches runs fetch --prune before git branch -r."""

    def test_fetch_prune_before_list(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """fetch --prune is called before git branch -r."""
        registry = tmp_path / "AIPASS_REGISTRY.json"
        registry.write_text("{}", encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        calls: list[list[str]] = []

        def _capture(cmd: list[str], **kw: object) -> MagicMock:
            calls.append(list(cmd))
            r = MagicMock()
            r.returncode = 0
            r.stderr = ""
            r.stdout = "  origin/main\n  origin/dev\n"
            return r

        with patch(f"{_BRANCHES_MOD}.subprocess.run", side_effect=_capture):
            result = list_remote_branches()

        assert result["count"] == 2
        cmd_summaries = [" ".join(c[:3]) for c in calls]
        assert "git fetch --prune" in cmd_summaries
        prune_idx = cmd_summaries.index("git fetch --prune")
        branch_idx = cmd_summaries.index("git branch -r")
        assert prune_idx < branch_idx

    def test_deleted_branch_not_listed(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """After prune, deleted remote branches do not appear."""
        registry = tmp_path / "AIPASS_REGISTRY.json"
        registry.write_text("{}", encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        def _run(cmd: list[str], **kw: object) -> MagicMock:
            r = MagicMock()
            r.returncode = 0
            r.stderr = ""
            if cmd[1:3] == ["branch", "-r"]:
                r.stdout = "  origin/main\n  origin/dev\n"
            else:
                r.stdout = ""
            return r

        with patch(f"{_BRANCHES_MOD}.subprocess.run", side_effect=_run):
            result = list_remote_branches()

        assert "deleted-branch" not in result["branches"]
        assert result["branches"] == ["main", "dev"]

    def test_offline_graceful(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """When fetch --prune fails (offline), listing still works with warning."""
        registry = tmp_path / "AIPASS_REGISTRY.json"
        registry.write_text("{}", encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        call_count = {"prune": 0}

        def _run(cmd: list[str], **kw: object) -> MagicMock:
            r = MagicMock()
            r.returncode = 0
            r.stderr = ""
            if cmd[1:3] == ["fetch", "--prune"]:
                call_count["prune"] += 1
                r.returncode = 1
                r.stderr = "fatal: Could not read from remote repository."
            elif cmd[1:3] == ["branch", "-r"]:
                r.stdout = "  origin/main\n"
            else:
                r.stdout = ""
            return r

        with patch(f"{_BRANCHES_MOD}.subprocess.run", side_effect=_run):
            result = list_remote_branches()

        assert call_count["prune"] == 1
        assert result["count"] == 1
        assert result["branches"] == ["main"]


# ===========================================================================
# Fix 4: Temp-branch hygiene — prune_temp_branches (#625)
# ===========================================================================


class TestPruneTempBranches:
    """Fix 4: prune_temp_branches deletes merged citizen/* branches."""

    def test_prunes_merged_citizen_branches(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Merged citizen/* branches are deleted."""
        registry = tmp_path / "AIPASS_REGISTRY.json"
        registry.write_text("{}", encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        def _run(cmd: list[str], **kw: object) -> MagicMock:
            r = MagicMock()
            r.returncode = 0
            r.stderr = ""
            if cmd[1:3] == ["branch", "--merged"]:
                r.stdout = "  main\n  dev\n  citizen/drone-fix\n  citizen/seedgo-pr\n"
            elif cmd[1:3] == ["branch", "-d"]:
                r.stdout = f"Deleted branch {cmd[3]}\n"
            return r

        with patch(f"{_BRANCHES_MOD}.subprocess.run", side_effect=_run):
            result = prune_temp_branches()

        assert result["count"] == 2
        assert "citizen/drone-fix" in result["pruned"]
        assert "citizen/seedgo-pr" in result["pruned"]

    def test_skips_non_citizen_branches(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Non-citizen branches (main, dev, feature/*) are not pruned."""
        registry = tmp_path / "AIPASS_REGISTRY.json"
        registry.write_text("{}", encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        def _run(cmd: list[str], **kw: object) -> MagicMock:
            r = MagicMock()
            r.returncode = 0
            r.stderr = ""
            if cmd[1:3] == ["branch", "--merged"]:
                r.stdout = "* main\n  dev\n  feature/old\n"
            return r

        with patch(f"{_BRANCHES_MOD}.subprocess.run", side_effect=_run):
            result = prune_temp_branches()

        assert result["count"] == 0
        assert result["pruned"] == []
