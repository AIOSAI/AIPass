# =================== AIPass ====================
# Name: test_devpulse_plugins.py
# Description: Tests for devpulse_ops plugins — merge, smart-sync, fix
# Version: 1.0.0
# Created: 2026-03-30
# Modified: 2026-03-30
# =============================================

"""Tests for devpulse_ops plugins — merge, smart-sync, fix."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from aipass.drone.apps.plugins.devpulse_ops.merge_plugin import merge_pr
from aipass.drone.apps.plugins.devpulse_ops.sync_plugin import smart_sync
from aipass.drone.apps.plugins.devpulse_ops.fix_plugin import fix_git_state


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture()
def devpulse_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a temp directory with a devpulse passport."""
    trinity = tmp_path / ".trinity"
    trinity.mkdir()
    passport = trinity / "passport.json"
    passport.write_text(
        json.dumps({
            "branch_info": {"branch_name": "devpulse"},
            "identity": {"name": "devpulse"},
        }),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture()
def seedgo_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a temp directory with a seedgo passport (unauthorized)."""
    trinity = tmp_path / ".trinity"
    trinity.mkdir()
    passport = trinity / "passport.json"
    passport.write_text(
        json.dumps({
            "branch_info": {"branch_name": "seedgo"},
            "identity": {"name": "seedgo"},
        }),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture()
def repo_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a temp repo root with AIPASS_REGISTRY.json and .git dir."""
    registry = tmp_path / "AIPASS_REGISTRY.json"
    registry.write_text("{}", encoding="utf-8")
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    monkeypatch.chdir(tmp_path)
    return tmp_path


# ===========================================================================
# 1. Auth denial for each command
# ===========================================================================


class TestAuthDenialMerge:
    """merge command should deny unauthorized callers."""

    def test_merge_unauthorized(self, seedgo_dir: Path) -> None:
        from aipass.drone.apps.modules.git_module import handle_command

        result = handle_command("merge", ["42"])
        assert result["exit_code"] == 1
        assert "not authorized" in result["stderr"]


class TestAuthDenialSmartSync:
    """smart-sync command should deny unauthorized callers."""

    def test_smart_sync_unauthorized(self, seedgo_dir: Path) -> None:
        from aipass.drone.apps.modules.git_module import handle_command

        result = handle_command("smart-sync", [])
        assert result["exit_code"] == 1
        assert "not authorized" in result["stderr"]


class TestAuthDenialFix:
    """fix command should deny unauthorized callers."""

    def test_fix_unauthorized(self, seedgo_dir: Path) -> None:
        from aipass.drone.apps.modules.git_module import handle_command

        result = handle_command("fix", [])
        assert result["exit_code"] == 1
        assert "not authorized" in result["stderr"]


# ===========================================================================
# 2. merge_pr tests
# ===========================================================================


class TestMergePrHappyPath:
    """merge_pr should squash-merge, pull, and return commit + title."""

    @patch("aipass.drone.apps.plugins.devpulse_ops.merge_plugin.find_repo_root")
    @patch("aipass.drone.apps.plugins.devpulse_ops.merge_plugin.subprocess.run")
    def test_merge_pr_success(
        self, mock_run: MagicMock, mock_root: MagicMock, tmp_path: Path
    ) -> None:
        mock_root.return_value = tmp_path

        def side_effect(cmd: list[str], **kwargs: object) -> MagicMock:
            proc = MagicMock()
            proc.returncode = 0
            proc.stderr = ""
            if cmd[:3] == ["gh", "pr", "merge"]:
                proc.stdout = "Merged\n"
            elif cmd[:2] == ["git", "pull"]:
                proc.stdout = "Already up to date.\n"
            elif cmd[:3] == ["git", "rev-parse", "HEAD"]:
                proc.stdout = "abc1234def5678\n"
            elif cmd[:3] == ["gh", "pr", "view"]:
                proc.stdout = "feat: awesome feature\n"
            else:
                proc.stdout = ""
            return proc

        mock_run.side_effect = side_effect

        result = merge_pr("42", "devpulse")

        assert result["success"] is True
        assert result["pr_number"] == "42"
        assert result["title"] == "feat: awesome feature"
        assert result["merge_commit"] == "abc1234def5678"
        assert "42" in result["message"]


class TestMergePrFailure:
    """merge_pr should return error when gh pr merge fails."""

    @patch("aipass.drone.apps.plugins.devpulse_ops.merge_plugin.find_repo_root")
    @patch("aipass.drone.apps.plugins.devpulse_ops.merge_plugin.subprocess.run")
    def test_merge_pr_merge_fails(
        self, mock_run: MagicMock, mock_root: MagicMock, tmp_path: Path
    ) -> None:
        mock_root.return_value = tmp_path

        proc = MagicMock()
        proc.returncode = 1
        proc.stderr = "PR is not mergeable"
        proc.stdout = ""
        mock_run.return_value = proc

        result = merge_pr("99", "devpulse")

        assert result["success"] is False
        assert "Merge failed" in result["message"]
        assert "not mergeable" in result["message"]


# ===========================================================================
# 3. smart_sync tests
# ===========================================================================


class TestSmartSyncUpToDate:
    """smart_sync should report up-to-date when not behind."""

    @patch("aipass.drone.apps.plugins.devpulse_ops.sync_plugin.find_repo_root")
    @patch("aipass.drone.apps.plugins.devpulse_ops.sync_plugin.subprocess.run")
    def test_smart_sync_up_to_date(
        self, mock_run: MagicMock, mock_root: MagicMock, tmp_path: Path
    ) -> None:
        mock_root.return_value = tmp_path

        def side_effect(cmd: list[str], **kwargs: object) -> MagicMock:
            proc = MagicMock()
            proc.returncode = 0
            proc.stderr = ""
            if cmd[:3] == ["git", "fetch", "origin"]:
                proc.stdout = ""
            elif cmd[:3] == ["git", "rev-list", "--left-right"]:
                proc.stdout = "0\t0\n"
            else:
                proc.stdout = ""
            return proc

        mock_run.side_effect = side_effect

        result = smart_sync("devpulse")

        assert result["success"] is True
        assert result["rebased"] is False
        assert "up to date" in result["message"]


class TestSmartSyncBehind:
    """smart_sync should rebase when behind origin."""

    @patch("aipass.drone.apps.plugins.devpulse_ops.sync_plugin.find_repo_root")
    @patch("aipass.drone.apps.plugins.devpulse_ops.sync_plugin.subprocess.run")
    def test_smart_sync_behind_rebase_success(
        self, mock_run: MagicMock, mock_root: MagicMock, tmp_path: Path
    ) -> None:
        mock_root.return_value = tmp_path

        def side_effect(cmd: list[str], **kwargs: object) -> MagicMock:
            proc = MagicMock()
            proc.returncode = 0
            proc.stderr = ""
            if cmd[:3] == ["git", "fetch", "origin"]:
                proc.stdout = ""
            elif cmd[:3] == ["git", "rev-list", "--left-right"]:
                proc.stdout = "0\t3\n"
            elif cmd[:3] == ["git", "rebase", "origin/main"]:
                proc.stdout = "Successfully rebased\n"
            else:
                proc.stdout = ""
            return proc

        mock_run.side_effect = side_effect

        result = smart_sync("devpulse")

        assert result["success"] is True
        assert result["rebased"] is True
        assert result["behind"] == 3


class TestSmartSyncDivergedRebaseSuccess:
    """smart_sync should rebase when diverged (behind > 0) and rebase succeeds."""

    @patch("aipass.drone.apps.plugins.devpulse_ops.sync_plugin.find_repo_root")
    @patch("aipass.drone.apps.plugins.devpulse_ops.sync_plugin.subprocess.run")
    def test_smart_sync_diverged_rebase_ok(
        self, mock_run: MagicMock, mock_root: MagicMock, tmp_path: Path
    ) -> None:
        mock_root.return_value = tmp_path

        def side_effect(cmd: list[str], **kwargs: object) -> MagicMock:
            proc = MagicMock()
            proc.returncode = 0
            proc.stderr = ""
            if cmd[:3] == ["git", "fetch", "origin"]:
                proc.stdout = ""
            elif cmd[:3] == ["git", "rev-list", "--left-right"]:
                proc.stdout = "2\t5\n"
            elif cmd[:3] == ["git", "rebase", "origin/main"]:
                proc.stdout = "Successfully rebased\n"
            else:
                proc.stdout = ""
            return proc

        mock_run.side_effect = side_effect

        result = smart_sync("devpulse")

        assert result["success"] is True
        assert result["rebased"] is True
        assert result["ahead"] == 2
        assert result["behind"] == 5


class TestSmartSyncRebaseConflict:
    """smart_sync should abort rebase on conflict and return error."""

    @patch("aipass.drone.apps.plugins.devpulse_ops.sync_plugin.find_repo_root")
    @patch("aipass.drone.apps.plugins.devpulse_ops.sync_plugin.subprocess.run")
    def test_smart_sync_rebase_conflict(
        self, mock_run: MagicMock, mock_root: MagicMock, tmp_path: Path
    ) -> None:
        mock_root.return_value = tmp_path

        def side_effect(cmd: list[str], **kwargs: object) -> MagicMock:
            proc = MagicMock()
            proc.stderr = ""
            if cmd[:3] == ["git", "fetch", "origin"]:
                proc.returncode = 0
                proc.stdout = ""
            elif cmd[:3] == ["git", "rev-list", "--left-right"]:
                proc.returncode = 0
                proc.stdout = "1\t2\n"
            elif cmd[:3] == ["git", "rebase", "origin/main"]:
                proc.returncode = 1
                proc.stdout = ""
                proc.stderr = "CONFLICT"
            elif cmd[:3] == ["git", "rebase", "--abort"]:
                proc.returncode = 0
                proc.stdout = ""
            else:
                proc.returncode = 0
                proc.stdout = ""
            return proc

        mock_run.side_effect = side_effect

        result = smart_sync("devpulse")

        assert result["success"] is False
        assert "conflict" in result["message"].lower()
        assert result["rebased"] is False


# ===========================================================================
# 4. fix_git_state tests
# ===========================================================================


class TestFixStuckRebase:
    """fix_git_state should abort a stuck rebase."""

    @patch("aipass.drone.apps.plugins.devpulse_ops.fix_plugin.find_repo_root")
    @patch("aipass.drone.apps.plugins.devpulse_ops.fix_plugin.subprocess.run")
    def test_fix_stuck_rebase(
        self, mock_run: MagicMock, mock_root: MagicMock, tmp_path: Path
    ) -> None:
        mock_root.return_value = tmp_path
        # Create .git/rebase-merge to simulate stuck rebase
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        (git_dir / "rebase-merge").mkdir()

        def side_effect(cmd: list[str], **kwargs: object) -> MagicMock:
            proc = MagicMock()
            proc.returncode = 0
            proc.stderr = ""
            proc.stdout = ""
            if cmd[:3] == ["git", "symbolic-ref", "-q"]:
                proc.stdout = "refs/heads/main\n"
            elif cmd[:3] == ["git", "rev-list", "--left-right"]:
                proc.stdout = "0\t0\n"
            elif cmd[:3] == ["git", "diff", "--cached"]:
                proc.stdout = ""
            return proc

        mock_run.side_effect = side_effect

        result = fix_git_state("devpulse")

        assert result["success"] is True
        assert any("rebase" in a.lower() for a in result["actions_taken"])


class TestFixDetachedHead:
    """fix_git_state should checkout main on detached HEAD."""

    @patch("aipass.drone.apps.plugins.devpulse_ops.fix_plugin.find_repo_root")
    @patch("aipass.drone.apps.plugins.devpulse_ops.fix_plugin.subprocess.run")
    def test_fix_detached_head(
        self, mock_run: MagicMock, mock_root: MagicMock, tmp_path: Path
    ) -> None:
        mock_root.return_value = tmp_path
        git_dir = tmp_path / ".git"
        git_dir.mkdir()

        def side_effect(cmd: list[str], **kwargs: object) -> MagicMock:
            proc = MagicMock()
            proc.stderr = ""
            proc.stdout = ""
            if cmd[:3] == ["git", "symbolic-ref", "-q"]:
                proc.returncode = 1  # detached HEAD
            elif cmd[:3] == ["git", "checkout", "main"]:
                proc.returncode = 0
            elif cmd[:3] == ["git", "rev-list", "--left-right"]:
                proc.returncode = 0
                proc.stdout = "0\t0\n"
            elif cmd[:3] == ["git", "diff", "--cached"]:
                proc.returncode = 0
                proc.stdout = ""
            else:
                proc.returncode = 0
            return proc

        mock_run.side_effect = side_effect

        result = fix_git_state("devpulse")

        assert result["success"] is True
        assert any("detached" in a.lower() for a in result["actions_taken"])


class TestFixDiverged:
    """fix_git_state should report divergence and suggest smart-sync."""

    @patch("aipass.drone.apps.plugins.devpulse_ops.fix_plugin.find_repo_root")
    @patch("aipass.drone.apps.plugins.devpulse_ops.fix_plugin.subprocess.run")
    def test_fix_diverged_suggests_sync(
        self, mock_run: MagicMock, mock_root: MagicMock, tmp_path: Path
    ) -> None:
        mock_root.return_value = tmp_path
        git_dir = tmp_path / ".git"
        git_dir.mkdir()

        def side_effect(cmd: list[str], **kwargs: object) -> MagicMock:
            proc = MagicMock()
            proc.returncode = 0
            proc.stderr = ""
            proc.stdout = ""
            if cmd[:3] == ["git", "symbolic-ref", "-q"]:
                proc.stdout = "refs/heads/main\n"
            elif cmd[:3] == ["git", "rev-list", "--left-right"]:
                proc.stdout = "3\t2\n"  # diverged
            elif cmd[:3] == ["git", "diff", "--cached"]:
                proc.stdout = ""
            return proc

        mock_run.side_effect = side_effect

        result = fix_git_state("devpulse")

        assert result["success"] is True
        assert any("smart-sync" in a for a in result["actions_taken"])


class TestFixCleanState:
    """fix_git_state should report nothing to fix when clean."""

    @patch("aipass.drone.apps.plugins.devpulse_ops.fix_plugin.find_repo_root")
    @patch("aipass.drone.apps.plugins.devpulse_ops.fix_plugin.subprocess.run")
    def test_fix_clean_state(
        self, mock_run: MagicMock, mock_root: MagicMock, tmp_path: Path
    ) -> None:
        mock_root.return_value = tmp_path
        git_dir = tmp_path / ".git"
        git_dir.mkdir()

        def side_effect(cmd: list[str], **kwargs: object) -> MagicMock:
            proc = MagicMock()
            proc.returncode = 0
            proc.stderr = ""
            proc.stdout = ""
            if cmd[:3] == ["git", "symbolic-ref", "-q"]:
                proc.stdout = "refs/heads/main\n"
            elif cmd[:3] == ["git", "rev-list", "--left-right"]:
                proc.stdout = "0\t0\n"
            elif cmd[:3] == ["git", "diff", "--cached"]:
                proc.stdout = ""
            return proc

        mock_run.side_effect = side_effect

        result = fix_git_state("devpulse")

        assert result["success"] is True
        assert len(result["actions_taken"]) == 0
        assert "nothing to fix" in result["message"].lower()


# ===========================================================================
# 5. Routing tests
# ===========================================================================


class TestGitModuleRouting:
    """Test that git_module routes merge, smart-sync, fix correctly."""

    def test_merge_in_commands(self) -> None:
        from aipass.drone.apps.modules.git_module import _COMMANDS

        assert "merge" in _COMMANDS

    def test_smart_sync_in_commands(self) -> None:
        from aipass.drone.apps.modules.git_module import _COMMANDS

        assert "smart-sync" in _COMMANDS

    def test_fix_in_commands(self) -> None:
        from aipass.drone.apps.modules.git_module import _COMMANDS

        assert "fix" in _COMMANDS

    def test_get_help_includes_merge(self) -> None:
        from aipass.drone.apps.modules.git_module import get_help

        assert "merge" in get_help()

    def test_get_help_includes_smart_sync(self) -> None:
        from aipass.drone.apps.modules.git_module import get_help

        assert "smart-sync" in get_help()

    def test_get_help_includes_fix(self) -> None:
        from aipass.drone.apps.modules.git_module import get_help

        assert "fix" in get_help()

    def test_get_help_merge_specific(self) -> None:
        from aipass.drone.apps.modules.git_module import get_help

        help_text = get_help("merge")
        assert "squash" in help_text.lower() or "Squash" in help_text

    def test_get_help_smart_sync_specific(self) -> None:
        from aipass.drone.apps.modules.git_module import get_help

        help_text = get_help("smart-sync")
        assert "rebase" in help_text.lower()

    def test_get_help_fix_specific(self) -> None:
        from aipass.drone.apps.modules.git_module import get_help

        help_text = get_help("fix")
        assert "broken" in help_text.lower() or "fix" in help_text.lower()

    def test_get_introspective_includes_plugins(self) -> None:
        from aipass.drone.apps.modules.git_module import get_introspective

        intro = get_introspective()
        assert "merge_plugin" in intro
        assert "sync_plugin" in intro
        assert "fix_plugin" in intro

    def test_handle_merge_no_args(self) -> None:
        from aipass.drone.apps.modules.git_module import handle_command

        result = handle_command("merge", [])
        assert result["exit_code"] == 1
        assert "Usage" in result["stderr"]

    @patch("aipass.drone.apps.plugins.devpulse_ops.auth.verify_caller")
    @patch("aipass.drone.apps.plugins.devpulse_ops.merge_plugin.find_repo_root")
    @patch("aipass.drone.apps.plugins.devpulse_ops.merge_plugin.subprocess.run")
    def test_handle_merge_routes_correctly(
        self,
        mock_run: MagicMock,
        mock_root: MagicMock,
        mock_verify: MagicMock,
        tmp_path: Path,
    ) -> None:
        from aipass.drone.apps.modules.git_module import handle_command

        mock_verify.return_value = "devpulse"
        mock_root.return_value = tmp_path

        proc = MagicMock()
        proc.returncode = 0
        proc.stderr = ""
        proc.stdout = "ok\n"
        mock_run.return_value = proc

        result = handle_command("merge", ["42"])
        assert result["exit_code"] == 0

    @patch("aipass.drone.apps.plugins.devpulse_ops.auth.verify_caller")
    @patch("aipass.drone.apps.plugins.devpulse_ops.sync_plugin.find_repo_root")
    @patch("aipass.drone.apps.plugins.devpulse_ops.sync_plugin.subprocess.run")
    def test_handle_smart_sync_routes_correctly(
        self,
        mock_run: MagicMock,
        mock_root: MagicMock,
        mock_verify: MagicMock,
        tmp_path: Path,
    ) -> None:
        from aipass.drone.apps.modules.git_module import handle_command

        mock_verify.return_value = "devpulse"
        mock_root.return_value = tmp_path

        def side_effect(cmd: list[str], **kwargs: object) -> MagicMock:
            proc = MagicMock()
            proc.returncode = 0
            proc.stderr = ""
            if cmd[:3] == ["git", "rev-list", "--left-right"]:
                proc.stdout = "0\t0\n"
            else:
                proc.stdout = ""
            return proc

        mock_run.side_effect = side_effect

        result = handle_command("smart-sync", [])
        assert result["exit_code"] == 0

    @patch("aipass.drone.apps.plugins.devpulse_ops.auth.verify_caller")
    @patch("aipass.drone.apps.plugins.devpulse_ops.fix_plugin.find_repo_root")
    @patch("aipass.drone.apps.plugins.devpulse_ops.fix_plugin.subprocess.run")
    def test_handle_fix_routes_correctly(
        self,
        mock_run: MagicMock,
        mock_root: MagicMock,
        mock_verify: MagicMock,
        tmp_path: Path,
    ) -> None:
        from aipass.drone.apps.modules.git_module import handle_command

        mock_verify.return_value = "devpulse"
        mock_root.return_value = tmp_path
        git_dir = tmp_path / ".git"
        git_dir.mkdir()

        def side_effect(cmd: list[str], **kwargs: object) -> MagicMock:
            proc = MagicMock()
            proc.returncode = 0
            proc.stderr = ""
            proc.stdout = ""
            if cmd[:3] == ["git", "symbolic-ref", "-q"]:
                proc.stdout = "refs/heads/main\n"
            elif cmd[:3] == ["git", "rev-list", "--left-right"]:
                proc.stdout = "0\t0\n"
            elif cmd[:3] == ["git", "diff", "--cached"]:
                proc.stdout = ""
            return proc

        mock_run.side_effect = side_effect

        result = handle_command("fix", [])
        assert result["exit_code"] == 0
