# =================== AIPass ====================
# Name: test_git_access.py
# Description: Tests for tier-based git access, new handlers, and PR deprecation
# Version: 1.0.0
# Created: 2026-05-12
# Modified: 2026-05-12
# =============================================

"""Tests for tier-based git access, new handlers (diff, log, commit, checkout), and PR deprecation."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from aipass.drone.apps.plugins.devpulse_ops.auth import (
    GIT_ACCESS_TIERS,
    verify_git_access,
)
from aipass.drone.apps.handlers.git.diff_handler import get_branch_diff
from aipass.drone.apps.handlers.git.log_handler import get_git_log
from aipass.drone.apps.handlers.git.commit_handler import commit_changes, stage_branch_dir
from aipass.drone.apps.handlers.git.checkout_handler import checkout_branch
from aipass.drone.apps.modules.git_module import handle_command


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
        json.dumps({"branch_info": {"branch_name": "devpulse"}}),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture()
def seedgo_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a temp directory with a non-owner passport."""
    trinity = tmp_path / ".trinity"
    trinity.mkdir()
    passport = trinity / "passport.json"
    passport.write_text(
        json.dumps({"branch_info": {"branch_name": "seedgo"}}),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture()
def repo_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a temp repo root with AIPASS_REGISTRY.json."""
    registry = tmp_path / "AIPASS_REGISTRY.json"
    registry.write_text("{}", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    return tmp_path


# ===========================================================================
# 1. GIT_ACCESS_TIERS config structure
# ===========================================================================


class TestGitAccessTiers:
    """Verify the tier config is correctly structured."""

    def test_tiers_has_global_and_owner(self) -> None:
        assert "global" in GIT_ACCESS_TIERS
        assert "owner" in GIT_ACCESS_TIERS

    def test_global_commands(self) -> None:
        cmds = GIT_ACCESS_TIERS["global"]["commands"]
        assert "status" in cmds
        assert "diff" in cmds
        assert "log" in cmds
        assert "lock" in cmds

    def test_owner_commands(self) -> None:
        cmds = GIT_ACCESS_TIERS["owner"]["commands"]
        assert "commit" in cmds
        assert "checkout" in cmds
        assert "sync" in cmds
        assert "unlock" in cmds
        assert "pr" in cmds
        assert "merge" in cmds
        assert "smart-sync" in cmds
        assert "fix" in cmds

    def test_owner_allowed_callers(self) -> None:
        allowed = GIT_ACCESS_TIERS["owner"]["allowed_callers"]
        assert allowed == ["devpulse"]

    def test_pr_in_owner_tier(self) -> None:
        cmds = GIT_ACCESS_TIERS["owner"]["commands"]
        assert "pr" in cmds


# ===========================================================================
# 2. verify_git_access — tier enforcement
# ===========================================================================


class TestVerifyGitAccessGlobal:
    """Global-tier commands should pass for any caller."""

    def test_status_allowed_for_any_branch(self, devpulse_dir: Path) -> None:
        assert verify_git_access("status") == "devpulse"

    def test_diff_allowed_for_seedgo(self, seedgo_dir: Path) -> None:
        assert verify_git_access("diff") == "seedgo"

    def test_log_allowed_for_any_branch(self, seedgo_dir: Path) -> None:
        assert verify_git_access("log") == "seedgo"

    def test_lock_allowed_for_any_branch(self, seedgo_dir: Path) -> None:
        assert verify_git_access("lock") == "seedgo"


class TestVerifyGitAccessOwner:
    """Owner-tier commands should only pass for devpulse."""

    def test_commit_allowed_for_devpulse(self, devpulse_dir: Path) -> None:
        assert verify_git_access("commit") == "devpulse"

    def test_commit_denied_for_seedgo(self, seedgo_dir: Path) -> None:
        with pytest.raises(PermissionError, match="not authorized"):
            verify_git_access("commit")

    def test_checkout_denied_for_seedgo(self, seedgo_dir: Path) -> None:
        with pytest.raises(PermissionError, match="not authorized"):
            verify_git_access("checkout")

    def test_sync_denied_for_seedgo(self, seedgo_dir: Path) -> None:
        with pytest.raises(PermissionError, match="not authorized"):
            verify_git_access("sync")

    def test_unlock_denied_for_seedgo(self, seedgo_dir: Path) -> None:
        with pytest.raises(PermissionError, match="not authorized"):
            verify_git_access("unlock")

    def test_pr_denied_for_seedgo(self, seedgo_dir: Path) -> None:
        with pytest.raises(PermissionError, match="not authorized"):
            verify_git_access("pr")


class TestVerifyGitAccessPrOwnerOnly:
    """PR command should be allowed for devpulse, denied for others."""

    def test_pr_allowed_for_devpulse(self, devpulse_dir: Path) -> None:
        result = verify_git_access("pr")
        assert result == "devpulse"

    def test_pr_denied_for_seedgo(self, seedgo_dir: Path) -> None:
        with pytest.raises(PermissionError, match="not authorized"):
            verify_git_access("pr")


class TestVerifyGitAccessUnknown:
    """Unknown commands should be denied."""

    def test_unknown_command_denied(self, devpulse_dir: Path) -> None:
        with pytest.raises(PermissionError, match="Unknown git command"):
            verify_git_access("nonexistent")


# ===========================================================================
# 3. diff_handler
# ===========================================================================


class TestDiffHandler:
    """Scoped git diff tests."""

    def test_basic_diff(self, repo_dir: Path) -> None:
        diff_output = (
            "diff --git a/src/aipass/api/foo.py b/src/aipass/api/foo.py\n"
            "--- a/src/aipass/api/foo.py\n"
            "+++ b/src/aipass/api/foo.py\n"
            "@@ -1,3 +1,4 @@\n"
            "+new line\n"
            "diff --git a/src/aipass/drone/bar.py b/src/aipass/drone/bar.py\n"
            "--- a/src/aipass/drone/bar.py\n"
            "+++ b/src/aipass/drone/bar.py\n"
        )
        mock_result = MagicMock(returncode=0, stdout=diff_output, stderr="")
        branch_dir = repo_dir / "src" / "aipass" / "api"

        with patch("aipass.drone.apps.handlers.git.diff_handler.subprocess.run", return_value=mock_result):
            result = get_branch_diff(branch_dir)

        assert result["files_changed"] == 1
        assert "src/aipass/api/foo.py" in result["diff"]
        assert "src/aipass/drone/bar.py" not in result["diff"]

    def test_staged_diff(self, repo_dir: Path) -> None:
        mock_result = MagicMock(returncode=0, stdout="", stderr="")
        branch_dir = repo_dir / "src" / "aipass" / "api"

        with patch("aipass.drone.apps.handlers.git.diff_handler.subprocess.run", return_value=mock_result) as mock_run:
            get_branch_diff(branch_dir, staged=True)

        cmd = mock_run.call_args[0][0]
        assert "--staged" in cmd

    def test_empty_diff(self, repo_dir: Path) -> None:
        mock_result = MagicMock(returncode=0, stdout="", stderr="")
        branch_dir = repo_dir / "src" / "aipass" / "api"

        with patch("aipass.drone.apps.handlers.git.diff_handler.subprocess.run", return_value=mock_result):
            result = get_branch_diff(branch_dir)

        assert result["files_changed"] == 0
        assert result["diff"] == ""

    def test_git_failure(self, repo_dir: Path) -> None:
        mock_result = MagicMock(returncode=128, stderr="fatal: not a git repo", stdout="")
        branch_dir = repo_dir / "src" / "aipass" / "api"

        with patch("aipass.drone.apps.handlers.git.diff_handler.subprocess.run", return_value=mock_result):
            result = get_branch_diff(branch_dir)

        assert result["files_changed"] == 0
        assert "error" in result["message"].lower()

    def test_os_error(self, repo_dir: Path) -> None:
        branch_dir = repo_dir / "src" / "aipass" / "api"

        with patch("aipass.drone.apps.handlers.git.diff_handler.subprocess.run", side_effect=OSError("git not found")):
            result = get_branch_diff(branch_dir)

        assert result["files_changed"] == 0
        assert "failed" in result["message"].lower()


# ===========================================================================
# 4. log_handler
# ===========================================================================


class TestLogHandler:
    """Git log tests."""

    def test_basic_log(self, repo_dir: Path) -> None:
        log_output = "abc1234 feat: first\ndef5678 fix: second\n"
        mock_result = MagicMock(returncode=0, stdout=log_output, stderr="")

        with patch("aipass.drone.apps.handlers.git.log_handler.subprocess.run", return_value=mock_result):
            result = get_git_log(count=5)

        assert result["count"] == 2
        assert len(result["entries"]) == 2

    def test_custom_count_passed_to_git(self, repo_dir: Path) -> None:
        mock_result = MagicMock(returncode=0, stdout="", stderr="")

        with patch("aipass.drone.apps.handlers.git.log_handler.subprocess.run", return_value=mock_result) as mock_run:
            get_git_log(count=25)

        cmd = mock_run.call_args[0][0]
        assert "-25" in cmd

    def test_git_failure(self, repo_dir: Path) -> None:
        mock_result = MagicMock(returncode=128, stderr="fatal: bad default", stdout="")

        with patch("aipass.drone.apps.handlers.git.log_handler.subprocess.run", return_value=mock_result):
            result = get_git_log()

        assert result["count"] == 0
        assert "error" in result["message"].lower()

    def test_os_error(self, repo_dir: Path) -> None:
        with patch("aipass.drone.apps.handlers.git.log_handler.subprocess.run", side_effect=OSError("git not found")):
            result = get_git_log()

        assert result["count"] == 0
        assert "failed" in result["message"].lower()


# ===========================================================================
# 5. commit_handler
# ===========================================================================


class TestStageBranchDir:
    """Shared staging utility tests."""

    def test_stage_success(self, repo_dir: Path) -> None:
        mock_result = MagicMock(returncode=0, stderr="")
        branch_dir = repo_dir / "src" / "aipass" / "api"

        with patch("aipass.drone.apps.handlers.git.commit_handler.subprocess.run", return_value=mock_result):
            result = stage_branch_dir(branch_dir, repo_dir)

        assert result["success"] is True

    def test_stage_failure(self, repo_dir: Path) -> None:
        mock_result = MagicMock(returncode=1, stderr="fatal: pathspec error")
        branch_dir = repo_dir / "src" / "aipass" / "api"

        with patch("aipass.drone.apps.handlers.git.commit_handler.subprocess.run", return_value=mock_result):
            result = stage_branch_dir(branch_dir, repo_dir)

        assert result["success"] is False
        assert "failed" in result["message"].lower()


def _assert_ordered_calls(mock_run: MagicMock, expected: list[tuple[tuple[str, ...], tuple[str, ...]]]) -> None:
    """Assert subprocess.run's recorded calls match expected (required, forbidden) argv markers, in order.

    An ordered side_effect list feeds canned results by position, not by argv match. If
    commit_handler gains, drops, or reorders a subprocess call, a canned result silently
    feeds the wrong step and the test can keep passing while testing nonsense. This checks
    the real argv at each position against the step it was written for.
    """
    calls = mock_run.call_args_list
    assert len(calls) == len(expected), (
        f"expected {len(expected)} subprocess.run calls, got {len(calls)}: {[c.args[0] for c in calls]}"
    )
    for call, (required, forbidden) in zip(calls, expected):
        argv = call.args[0]
        for marker in required:
            assert marker in argv, f"expected {marker!r} in argv {argv!r} (call order mismatch?)"
        for marker in forbidden:
            assert marker not in argv, f"unexpected {marker!r} in argv {argv!r} (call order mismatch?)"


_RUFF_FIX = (("check", "--fix"), ())
_RUFF_FORMAT = (("format",), ("--fix",))
_RUFF_GATE = (("check",), ("--fix",))
_GIT_STATUS = (("status", "--porcelain"), ())
_PYTEST = (("-m", "pytest"), ())
_GIT_ADD_ALL = (("add", "-A"), ())
_GIT_DIFF_CACHED = (("diff", "--cached"), ())
_GIT_COMMIT = (("commit", "-m"), ())


class TestCommitChanges:
    """Commit handler tests."""

    def test_commit_staged(self, repo_dir: Path) -> None:
        mock_diff = MagicMock(returncode=1, stdout="", stderr="")
        mock_commit = MagicMock(returncode=0, stdout="[main abc123] test commit", stderr="")

        with patch(
            "aipass.drone.apps.handlers.git.commit_handler.subprocess.run",
            side_effect=[mock_diff, mock_commit],
        ) as mock_run:
            result = commit_changes("test commit")

        assert result["exit_code"] == 0
        assert "abc123" in result["stdout"]
        _assert_ordered_calls(mock_run, [_GIT_DIFF_CACHED, _GIT_COMMIT])

    def test_commit_nothing_staged(self, repo_dir: Path) -> None:
        mock_diff = MagicMock(returncode=0, stdout="", stderr="")

        with patch("aipass.drone.apps.handlers.git.commit_handler.subprocess.run", return_value=mock_diff):
            result = commit_changes("test commit")

        assert result["exit_code"] == 1
        assert "nothing to commit" in result["stderr"].lower()

    def test_commit_all_stages_first(self, repo_dir: Path) -> None:
        mock_ruff_fix = MagicMock(returncode=0, stdout="", stderr="")
        mock_ruff_format = MagicMock(returncode=0, stdout="", stderr="")
        mock_ruff_gate = MagicMock(returncode=0, stdout="", stderr="")
        mock_status = MagicMock(returncode=0, stdout=" M src/aipass/api/app.py\n", stderr="")
        mock_add = MagicMock(returncode=0, stderr="")
        mock_diff = MagicMock(returncode=1, stdout="", stderr="")
        mock_commit = MagicMock(returncode=0, stdout="[main def456] all commit", stderr="")

        branch_dir = repo_dir / "src" / "aipass" / "api"

        with (
            patch("shutil.which", return_value="/usr/bin/ruff"),
            patch(
                "aipass.drone.apps.handlers.git.commit_handler.subprocess.run",
                side_effect=[
                    mock_ruff_fix,
                    mock_ruff_format,
                    mock_ruff_gate,
                    mock_status,
                    mock_add,
                    mock_diff,
                    mock_commit,
                ],
            ) as mock_run,
        ):
            result = commit_changes("all commit", branch_dir=branch_dir, all_files=True)

        assert result["exit_code"] == 0
        _assert_ordered_calls(
            mock_run,
            [_RUFF_FIX, _RUFF_FORMAT, _RUFF_GATE, _GIT_STATUS, _GIT_ADD_ALL, _GIT_DIFF_CACHED, _GIT_COMMIT],
        )

    def test_commit_all_blocks_on_test_failure(self, repo_dir: Path) -> None:
        mock_ruff_fix = MagicMock(returncode=0, stdout="", stderr="")
        mock_ruff_format = MagicMock(returncode=0, stdout="", stderr="")
        mock_ruff_gate = MagicMock(returncode=0, stdout="", stderr="")
        mock_status = MagicMock(
            returncode=0,
            stdout=" M src/aipass/drone/apps/handlers/git/commit_handler.py\n",
            stderr="",
        )
        mock_pytest = MagicMock(
            returncode=1,
            stdout="FAILED test_foo.py::test_bar - assert 1 == 2\n1 failed",
            stderr="",
        )

        drone_dir = repo_dir / "src" / "aipass" / "drone"
        drone_dir.mkdir(parents=True)
        (drone_dir / ".trinity").mkdir()
        test_dir = drone_dir / "tests"
        test_dir.mkdir()

        with (
            patch("shutil.which", return_value="/usr/bin/ruff"),
            patch(
                "aipass.drone.apps.handlers.git.commit_handler.subprocess.run",
                side_effect=[mock_ruff_fix, mock_ruff_format, mock_ruff_gate, mock_status, mock_pytest],
            ) as mock_run,
        ):
            result = commit_changes("fail commit", all_files=True)

        assert result["exit_code"] == 1
        assert "Test failures" in result["stderr"]
        assert "drone" in result["stderr"]
        _assert_ordered_calls(mock_run, [_RUFF_FIX, _RUFF_FORMAT, _RUFF_GATE, _GIT_STATUS, _PYTEST])

    def test_commit_all_passes_with_green_tests(self, repo_dir: Path) -> None:
        mock_ruff_fix = MagicMock(returncode=0, stdout="", stderr="")
        mock_ruff_format = MagicMock(returncode=0, stdout="", stderr="")
        mock_ruff_gate = MagicMock(returncode=0, stdout="", stderr="")
        mock_status = MagicMock(
            returncode=0,
            stdout=" M src/aipass/drone/apps/handlers/git/commit_handler.py\n",
            stderr="",
        )
        mock_pytest = MagicMock(returncode=0, stdout="3 passed", stderr="")
        mock_add = MagicMock(returncode=0, stderr="")
        mock_diff = MagicMock(returncode=1, stdout="", stderr="")
        mock_commit = MagicMock(returncode=0, stdout="[main abc999] green commit", stderr="")

        drone_dir = repo_dir / "src" / "aipass" / "drone"
        drone_dir.mkdir(parents=True)
        (drone_dir / ".trinity").mkdir()
        test_dir = drone_dir / "tests"
        test_dir.mkdir()

        with (
            patch("shutil.which", return_value="/usr/bin/ruff"),
            patch(
                "aipass.drone.apps.handlers.git.commit_handler.subprocess.run",
                side_effect=[
                    mock_ruff_fix,
                    mock_ruff_format,
                    mock_ruff_gate,
                    mock_status,
                    mock_pytest,
                    mock_add,
                    mock_diff,
                    mock_commit,
                ],
            ) as mock_run,
        ):
            result = commit_changes("green commit", all_files=True)

        assert result["exit_code"] == 0
        _assert_ordered_calls(
            mock_run,
            [_RUFF_FIX, _RUFF_FORMAT, _RUFF_GATE, _GIT_STATUS, _PYTEST, _GIT_ADD_ALL, _GIT_DIFF_CACHED, _GIT_COMMIT],
        )

    def test_commit_all_skips_branches_without_tests(self, repo_dir: Path) -> None:
        mock_ruff_fix = MagicMock(returncode=0, stdout="", stderr="")
        mock_ruff_format = MagicMock(returncode=0, stdout="", stderr="")
        mock_ruff_gate = MagicMock(returncode=0, stdout="", stderr="")
        mock_status = MagicMock(
            returncode=0,
            stdout=" M src/aipass/flow/apps/module.py\n",
            stderr="",
        )
        mock_add = MagicMock(returncode=0, stderr="")
        mock_diff = MagicMock(returncode=1, stdout="", stderr="")
        mock_commit = MagicMock(returncode=0, stdout="[main skip77] no tests", stderr="")

        with (
            patch("shutil.which", return_value="/usr/bin/ruff"),
            patch(
                "aipass.drone.apps.handlers.git.commit_handler.subprocess.run",
                side_effect=[
                    mock_ruff_fix,
                    mock_ruff_format,
                    mock_ruff_gate,
                    mock_status,
                    mock_add,
                    mock_diff,
                    mock_commit,
                ],
            ) as mock_run,
        ):
            result = commit_changes("no tests commit", all_files=True)

        assert result["exit_code"] == 0
        _assert_ordered_calls(
            mock_run,
            [_RUFF_FIX, _RUFF_FORMAT, _RUFF_GATE, _GIT_STATUS, _GIT_ADD_ALL, _GIT_DIFF_CACHED, _GIT_COMMIT],
        )

    def test_commit_os_error(self, repo_dir: Path) -> None:
        mock_diff = MagicMock(returncode=1, stdout="", stderr="")

        with patch(
            "aipass.drone.apps.handlers.git.commit_handler.subprocess.run",
            side_effect=[mock_diff, OSError("git not found")],
        ) as mock_run:
            result = commit_changes("test commit")

        assert result["exit_code"] == 1
        assert "failed" in result["stderr"].lower()
        _assert_ordered_calls(mock_run, [_GIT_DIFF_CACHED, _GIT_COMMIT])


# ===========================================================================
# 6. checkout_handler
# ===========================================================================


class TestCheckoutHandler:
    """Branch checkout with hard guard tests."""

    def test_checkout_main_allowed(self, repo_dir: Path) -> None:
        mock_status = MagicMock(returncode=0, stdout="", stderr="")
        mock_checkout = MagicMock(returncode=0, stdout="", stderr="Switched to branch 'main'")

        with patch(
            "aipass.drone.apps.handlers.git.checkout_handler.subprocess.run",
            side_effect=[mock_status, mock_checkout],
        ):
            result = checkout_branch("main")

        assert result["exit_code"] == 0
        assert result["current_branch"] == "main"

    def test_checkout_dev_allowed(self, repo_dir: Path) -> None:
        mock_status = MagicMock(returncode=0, stdout="", stderr="")
        mock_checkout = MagicMock(returncode=0, stdout="", stderr="Switched to branch 'dev'")

        with patch(
            "aipass.drone.apps.handlers.git.checkout_handler.subprocess.run",
            side_effect=[mock_status, mock_checkout],
        ):
            result = checkout_branch("dev")

        assert result["exit_code"] == 0
        assert result["current_branch"] == "dev"

    def test_checkout_feature_branch_denied(self) -> None:
        result = checkout_branch("feat/my-feature")
        assert result["exit_code"] == 1
        assert "denied" in result["stderr"].lower()
        assert result["current_branch"] == ""

    def test_checkout_arbitrary_branch_denied(self) -> None:
        result = checkout_branch("release/v2")
        assert result["exit_code"] == 1
        assert "denied" in result["stderr"].lower()

    def test_checkout_dirty_tree_aborts(self, repo_dir: Path) -> None:
        mock_status = MagicMock(returncode=0, stdout=" M some/file.py\n", stderr="")

        with patch("aipass.drone.apps.handlers.git.checkout_handler.subprocess.run", return_value=mock_status):
            result = checkout_branch("main")

        assert result["exit_code"] == 1
        assert "uncommitted" in result["stderr"].lower()

    def test_checkout_git_failure(self, repo_dir: Path) -> None:
        mock_status = MagicMock(returncode=0, stdout="", stderr="")
        mock_checkout = MagicMock(returncode=1, stdout="", stderr="error: pathspec 'main' did not match")
        mock_create = MagicMock(returncode=0, stdout="Switched to a new branch 'main'", stderr="")

        with patch(
            "aipass.drone.apps.handlers.git.checkout_handler.subprocess.run",
            side_effect=[mock_status, mock_checkout, mock_create],
        ):
            result = checkout_branch("main")

        assert result["exit_code"] == 0
        assert result["current_branch"] == "main"


# ===========================================================================
# 7. PR deprecation through handle_command
# ===========================================================================


class TestPrCommand:
    """PR command routes to create_branch_pr for authorized callers."""

    def test_pr_no_args_shows_usage(self, devpulse_dir: Path) -> None:
        result = handle_command("pr")
        assert result["exit_code"] == 1
        assert "usage" in result["stderr"].lower()

    @patch("aipass.drone.apps.handlers.git.dev_pr_handler.create_branch_pr")
    def test_pr_with_description_calls_handler(self, mock_pr: MagicMock, devpulse_dir: Path) -> None:
        mock_pr.return_value = {"success": True, "message": "PR created", "pr_url": "https://example.com"}
        handle_command("pr", ["test description"])
        mock_pr.assert_called_once()


# ===========================================================================
# 8. New commands via handle_command routing
# ===========================================================================


class TestNewCommandRouting:
    """Verify new commands route through handle_command correctly."""

    @patch("aipass.drone.apps.plugins.devpulse_ops.auth.verify_git_access", return_value="test_branch")
    def test_diff_routes(self, _mock_auth: MagicMock, repo_dir: Path) -> None:
        trinity = repo_dir / ".trinity"
        trinity.mkdir()
        passport = trinity / "passport.json"
        passport.write_text(json.dumps({"branch_info": {"branch_name": "test_branch"}}))

        mock_result = MagicMock(returncode=0, stdout="", stderr="")
        with patch("aipass.drone.apps.handlers.git.diff_handler.subprocess.run", return_value=mock_result):
            result = handle_command("diff")
        assert result["exit_code"] == 0

    @patch("aipass.drone.apps.plugins.devpulse_ops.auth.verify_git_access", return_value="test_branch")
    def test_log_routes(self, _mock_auth: MagicMock, repo_dir: Path) -> None:
        mock_result = MagicMock(returncode=0, stdout="abc123 test\n", stderr="")
        with patch("aipass.drone.apps.handlers.git.log_handler.subprocess.run", return_value=mock_result):
            result = handle_command("log")
        assert result["exit_code"] == 0
        assert "abc123" in result["stdout"]

    @patch("aipass.drone.apps.plugins.devpulse_ops.auth.verify_git_access", return_value="devpulse")
    def test_commit_no_args_error(self, _mock_auth: MagicMock) -> None:
        result = handle_command("commit")
        assert result["exit_code"] == 1
        assert "usage" in result["stderr"].lower()

    @patch("aipass.drone.apps.plugins.devpulse_ops.auth.verify_git_access", return_value="devpulse")
    def test_checkout_no_args_error(self, _mock_auth: MagicMock) -> None:
        result = handle_command("checkout")
        assert result["exit_code"] == 1
        assert "usage" in result["stderr"].lower()

    @patch("aipass.drone.apps.plugins.devpulse_ops.auth.verify_git_access", return_value="devpulse")
    def test_checkout_routes_to_handler(self, _mock_auth: MagicMock, repo_dir: Path) -> None:
        mock_status = MagicMock(returncode=0, stdout="", stderr="")
        mock_checkout = MagicMock(returncode=0, stdout="", stderr="")
        with patch(
            "aipass.drone.apps.handlers.git.checkout_handler.subprocess.run",
            side_effect=[mock_status, mock_checkout],
        ):
            result = handle_command("checkout", ["main"])
        assert result["exit_code"] == 0

    @patch("aipass.drone.apps.plugins.devpulse_ops.auth.verify_git_access", return_value="devpulse")
    def test_checkout_guard_rejects_feature(self, _mock_auth: MagicMock) -> None:
        result = handle_command("checkout", ["feat/bad"])
        assert result["exit_code"] == 1
        assert "denied" in result["stderr"].lower()


# ===========================================================================
# 9. Help text includes new commands and tiers
# ===========================================================================


class TestUpdatedHelp:
    """Help and introspection reflect new commands and tiers."""

    def test_help_includes_diff(self) -> None:
        from aipass.drone.apps.modules.git_module import get_help

        text = get_help()
        assert "diff" in text

    def test_help_includes_log(self) -> None:
        from aipass.drone.apps.modules.git_module import get_help

        text = get_help()
        assert "log" in text

    def test_help_includes_commit(self) -> None:
        from aipass.drone.apps.modules.git_module import get_help

        text = get_help()
        assert "commit" in text

    def test_help_includes_checkout(self) -> None:
        from aipass.drone.apps.modules.git_module import get_help

        text = get_help()
        assert "checkout" in text

    def test_help_shows_tier_sections(self) -> None:
        from aipass.drone.apps.modules.git_module import get_help

        text = get_help()
        assert "global" in text.lower()
        assert "owner" in text.lower()

    def test_help_includes_pr_command(self) -> None:
        from aipass.drone.apps.modules.git_module import get_help

        text = get_help()
        assert "pr" in text.lower()

    def test_introspection_includes_new_handlers(self) -> None:
        from aipass.drone.apps.modules.git_module import get_introspective

        text = get_introspective()
        assert "diff_handler" in text
        assert "log_handler" in text
        assert "commit_handler" in text
        assert "checkout_handler" in text

    def test_introspection_shows_tiers(self) -> None:
        from aipass.drone.apps.modules.git_module import get_introspective

        text = get_introspective()
        assert "global" in text.lower()
        assert "owner" in text.lower()


# ===========================================================================
# 10. gh passthrough commands (issue, run, workflow)
# ===========================================================================


class TestGhPassthroughTierConfig:
    """Passthrough commands are in the global tier."""

    def test_issue_in_global_tier(self) -> None:
        assert "issue" in GIT_ACCESS_TIERS["global"]["commands"]

    def test_run_in_global_tier(self) -> None:
        assert "run" in GIT_ACCESS_TIERS["global"]["commands"]

    def test_workflow_in_global_tier(self) -> None:
        assert "workflow" in GIT_ACCESS_TIERS["global"]["commands"]

    def test_passthrough_not_in_owner_tier(self) -> None:
        owner_cmds = GIT_ACCESS_TIERS["owner"]["commands"]
        assert "issue" not in owner_cmds
        assert "run" not in owner_cmds
        assert "workflow" not in owner_cmds


class TestGhPassthroughAccess:
    """Global-tier access for passthrough commands."""

    def test_issue_allowed_for_any_branch(self, seedgo_dir: Path) -> None:
        assert verify_git_access("issue") == "seedgo"

    def test_run_allowed_for_any_branch(self, seedgo_dir: Path) -> None:
        assert verify_git_access("run") == "seedgo"

    def test_workflow_allowed_for_any_branch(self, seedgo_dir: Path) -> None:
        assert verify_git_access("workflow") == "seedgo"


class TestGhPassthroughRouting:
    """handle_command routes passthrough to subprocess."""

    @patch("aipass.drone.apps.plugins.devpulse_ops.auth.verify_git_access", return_value="test_branch")
    @patch("aipass.drone.apps.modules.git_module.subprocess.run")
    def test_issue_list(self, mock_run: MagicMock, _mock_auth: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=0, stdout="Issue #1\nIssue #2\n", stderr="")
        result = handle_command("issue", ["list"])
        assert result["exit_code"] == 0
        assert "Issue #1" in result["stdout"]
        mock_run.assert_called_once_with(
            ["gh", "issue", "list"],
            capture_output=True,
            text=True,
            timeout=60,
        )

    @patch("aipass.drone.apps.plugins.devpulse_ops.auth.verify_git_access", return_value="test_branch")
    @patch("aipass.drone.apps.modules.git_module.subprocess.run")
    def test_run_list(self, mock_run: MagicMock, _mock_auth: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=0, stdout="run 123\n", stderr="")
        result = handle_command("run", ["list"])
        assert result["exit_code"] == 0
        mock_run.assert_called_once_with(
            ["gh", "run", "list"],
            capture_output=True,
            text=True,
            timeout=60,
        )

    @patch("aipass.drone.apps.plugins.devpulse_ops.auth.verify_git_access", return_value="test_branch")
    @patch("aipass.drone.apps.modules.git_module.subprocess.run")
    def test_workflow_list(self, mock_run: MagicMock, _mock_auth: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=0, stdout="CI workflow\n", stderr="")
        result = handle_command("workflow", ["list"])
        assert result["exit_code"] == 0
        mock_run.assert_called_once_with(
            ["gh", "workflow", "list"],
            capture_output=True,
            text=True,
            timeout=60,
        )

    @patch("aipass.drone.apps.plugins.devpulse_ops.auth.verify_git_access", return_value="test_branch")
    @patch("aipass.drone.apps.modules.git_module.subprocess.run")
    def test_passthrough_no_args(self, mock_run: MagicMock, _mock_auth: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=0, stdout="usage info\n", stderr="")
        result = handle_command("issue")
        assert result["exit_code"] == 0
        mock_run.assert_called_once_with(
            ["gh", "issue"],
            capture_output=True,
            text=True,
            timeout=60,
        )

    @patch("aipass.drone.apps.plugins.devpulse_ops.auth.verify_git_access", return_value="test_branch")
    @patch("aipass.drone.apps.modules.git_module.subprocess.run")
    def test_passthrough_returns_stderr(self, mock_run: MagicMock, _mock_auth: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="not authenticated")
        result = handle_command("issue", ["list"])
        assert result["exit_code"] == 1
        assert "not authenticated" in result["stderr"]

    @patch("aipass.drone.apps.plugins.devpulse_ops.auth.verify_git_access", return_value="test_branch")
    @patch("aipass.drone.apps.modules.git_module.subprocess.run", side_effect=FileNotFoundError("gh"))
    def test_passthrough_gh_not_found(self, _mock_run: MagicMock, _mock_auth: MagicMock) -> None:
        result = handle_command("issue", ["list"])
        assert result["exit_code"] == 1
        assert "gh CLI not found" in result["stderr"]

    @patch("aipass.drone.apps.plugins.devpulse_ops.auth.verify_git_access", return_value="test_branch")
    @patch(
        "aipass.drone.apps.modules.git_module.subprocess.run",
        side_effect=__import__("subprocess").TimeoutExpired(["gh", "issue"], 60),
    )
    def test_passthrough_timeout(self, _mock_run: MagicMock, _mock_auth: MagicMock) -> None:
        result = handle_command("issue", ["list"])
        assert result["exit_code"] == 1
        assert "timed out" in result["stderr"]

    @patch("aipass.drone.apps.plugins.devpulse_ops.auth.verify_git_access", return_value="test_branch")
    @patch("aipass.drone.apps.modules.git_module.subprocess.run")
    def test_passthrough_multiple_args(self, mock_run: MagicMock, _mock_auth: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        handle_command("issue", ["create", "--title", "Bug", "--body", "Details"])
        mock_run.assert_called_once_with(
            ["gh", "issue", "create", "--title", "Bug", "--body", "Details"],
            capture_output=True,
            text=True,
            timeout=60,
        )


class TestGhPassthroughHelp:
    """Help text includes passthrough commands."""

    def test_help_includes_issue(self) -> None:
        from aipass.drone.apps.modules.git_module import get_help

        assert "issue" in get_help()

    def test_help_includes_run(self) -> None:
        from aipass.drone.apps.modules.git_module import get_help

        assert "run" in get_help()

    def test_help_includes_workflow(self) -> None:
        from aipass.drone.apps.modules.git_module import get_help

        assert "workflow" in get_help()

    def test_per_command_help_issue(self) -> None:
        from aipass.drone.apps.modules.git_module import get_help

        text = get_help("issue")
        assert "gh issue" in text
        assert "global" in text.lower()

    def test_per_command_help_run(self) -> None:
        from aipass.drone.apps.modules.git_module import get_help

        text = get_help("run")
        assert "gh run" in text

    def test_per_command_help_workflow(self) -> None:
        from aipass.drone.apps.modules.git_module import get_help

        text = get_help("workflow")
        assert "gh workflow" in text

    def test_introspection_includes_passthrough(self) -> None:
        from aipass.drone.apps.modules.git_module import get_introspective

        text = get_introspective()
        assert "issue" in text
        assert "run" in text
        assert "workflow" in text
