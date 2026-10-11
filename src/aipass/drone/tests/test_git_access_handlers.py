# =================== AIPass ====================
# Name: test_git_access_handlers.py
# Description: Tests for the git door handlers — diff, log, show, commit, checkout, PR routing and help
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-08
# =============================================

"""Tests for apps/handlers/git/commit_handler.py and the diff, log, show and checkout handlers beside it."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(stdlib) — subprocess.run, which every git call here reaches as a recorded stub

from __future__ import annotations

import inspect
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
from aipass.drone.apps.handlers.git.show_handler import show_object
from aipass.prax.apps.modules import dashboard as prax_dashboard
from aipass.drone.apps.handlers.git import commit_handler
from aipass.drone.apps.handlers.git.commit_handler import commit_changes, stage_branch_dir
from aipass.drone.apps.handlers.git.checkout_handler import checkout_branch
from aipass.drone.apps.modules.git_module import get_help, get_introspective, handle_command


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


class TestShowHandler:
    """git show — reading history at global read tier.

    Requested by @seedgo via @devpulse 2026-08-13: auditing a bypass prune means
    reading what was DELETED, and status/diff/log only show the present. Reading
    history is not a write, so every citizen auditing its own past can do it.
    """

    def test_show_ref_only(self, repo_dir: Path) -> None:
        mock_result = MagicMock(returncode=0, stdout="commit abc1234\n\n    feat: thing\n", stderr="")

        with patch("aipass.drone.apps.handlers.git.show_handler.subprocess.run", return_value=mock_result) as run:
            result = show_object("abc1234")

        assert result["success"] is True
        assert "feat: thing" in result["content"]
        assert run.call_args[0][0] == ["git", "show", "abc1234"]

    def test_show_ref_with_path_uses_colon_form(self, repo_dir: Path) -> None:
        """`show <ref> <path>` must read the file AT that commit, not the diff."""
        mock_result = MagicMock(returncode=0, stdout='{"bypass": []}\n', stderr="")

        with patch("aipass.drone.apps.handlers.git.show_handler.subprocess.run", return_value=mock_result) as run:
            result = show_object("abc1234", "src/aipass/prax/.seedgo/bypass.json")

        assert result["success"] is True
        assert run.call_args[0][0] == ["git", "show", "abc1234:src/aipass/prax/.seedgo/bypass.json"]

    def test_show_is_not_scoped_to_callers_branch(self, repo_dir: Path) -> None:
        """A path outside the caller's own branch must be readable.

        The whole point is @seedgo verifying @prax's prune. Scoping this to the
        caller's directory the way status/diff/log do would refuse exactly the
        use case it was granted for.
        """
        mock_result = MagicMock(returncode=0, stdout="content", stderr="")

        with patch("aipass.drone.apps.handlers.git.show_handler.subprocess.run", return_value=mock_result) as run:
            result = show_object("HEAD~5", "src/aipass/memory/apps/memory.py")

        assert result["success"] is True
        assert "src/aipass/memory/apps/memory.py" in run.call_args[0][0][2]

    def test_ref_that_git_would_read_as_a_flag_is_refused(self, repo_dir: Path) -> None:
        """Refuse before any argv is built — the tag_handler lesson (S49)."""
        for bad in ("", "-n", "--output=x.patch", "-"):
            result = show_object(bad)
            assert result["success"] is False, f"accepted flag-like ref {bad!r}"
            assert "content" in result

    def test_path_that_git_would_read_as_a_flag_is_refused(self, repo_dir: Path) -> None:
        result = show_object("abc1234", "--output=pwned.patch")
        assert result["success"] is False

    def test_git_failure_reports_honestly(self, repo_dir: Path) -> None:
        mock_result = MagicMock(returncode=128, stdout="", stderr="fatal: bad object deadbeef")

        with patch("aipass.drone.apps.handlers.git.show_handler.subprocess.run", return_value=mock_result):
            result = show_object("deadbeef")

        assert result["success"] is False
        assert "bad object" in result["message"]

    def test_subprocess_error_is_caught(self, repo_dir: Path) -> None:
        with patch(
            "aipass.drone.apps.handlers.git.show_handler.subprocess.run",
            side_effect=OSError("git missing"),
        ):
            result = show_object("abc1234")

        assert result["success"] is False
        assert "git missing" in result["message"]


class TestShowCommandRouting:
    """`drone @git show` reaches the handler at global tier."""

    def test_show_is_global_tier(self) -> None:
        assert "show" in GIT_ACCESS_TIERS["global"]["commands"]
        assert "show" not in GIT_ACCESS_TIERS["owner"]["commands"]

    def test_non_owner_may_show(self, seedgo_dir: Path) -> None:
        """The requesting citizen is a non-owner — that is the whole point."""
        assert verify_git_access("show") == "seedgo"

    def test_show_dispatches_to_handler(self, seedgo_dir: Path) -> None:
        with patch("aipass.drone.apps.modules.git_module.show_handler.show_object") as mock_show:
            mock_show.return_value = {"success": True, "content": "file body", "message": "ok"}
            result = handle_command("show", ["abc1234", "some/path.py"])

        mock_show.assert_called_once_with("abc1234", "some/path.py")
        assert result["exit_code"] == 0
        assert result["stdout"] == "file body"

    def test_show_without_ref_returns_usage(self, seedgo_dir: Path) -> None:
        result = handle_command("show", [])
        assert result["exit_code"] == 1
        assert "Usage" in result["stderr"]


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


@pytest.fixture()
def ruff_in_venv(repo_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A ruff the commit lane finds on disk: none on PATH, one in the repo's own .venv."""
    empty_path = tmp_path / "empty_path"
    empty_path.mkdir()
    monkeypatch.setenv("PATH", str(empty_path))
    ruff = repo_dir / ".venv" / "bin" / "ruff"
    ruff.parent.mkdir(parents=True)
    ruff.write_text("", encoding="utf-8")
    return ruff


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

    def test_commit_all_stages_first(self, repo_dir: Path, ruff_in_venv: Path) -> None:
        mock_ruff_fix = MagicMock(returncode=0, stdout="", stderr="")
        mock_ruff_format = MagicMock(returncode=0, stdout="", stderr="")
        mock_ruff_gate = MagicMock(returncode=0, stdout="", stderr="")
        mock_status = MagicMock(returncode=0, stdout=" M src/aipass/api/app.py\n", stderr="")
        mock_add = MagicMock(returncode=0, stderr="")
        mock_diff = MagicMock(returncode=1, stdout="", stderr="")
        mock_commit = MagicMock(returncode=0, stdout="[main def456] all commit", stderr="")

        with (
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
            result = commit_changes("all commit", all_files=True)

        assert result["exit_code"] == 0
        _assert_ordered_calls(
            mock_run,
            [_RUFF_FIX, _RUFF_FORMAT, _RUFF_GATE, _GIT_STATUS, _GIT_ADD_ALL, _GIT_DIFF_CACHED, _GIT_COMMIT],
        )

    def test_commit_all_blocks_on_test_failure(self, repo_dir: Path, ruff_in_venv: Path) -> None:
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

    def test_commit_all_passes_with_green_tests(self, repo_dir: Path, ruff_in_venv: Path) -> None:
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

    def test_commit_all_skips_branches_without_tests(self, repo_dir: Path, ruff_in_venv: Path) -> None:
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


class TestCommitSubjectCap:
    """An essay in the subject line is refused at the door (DPLAN-0347)."""

    def test_cap_is_prax_s_number_not_a_copy(self) -> None:
        """A commit subject and a plan subject are the same glance — one number.

        The value alone cannot prove it: CPython interns small ints, so a
        hand-copied 120 passes even an identity check (measured — the mutant
        survived). Where the number comes FROM is a property of the source.
        """
        source = inspect.getsource(commit_handler)
        assert "from aipass.prax.apps.modules.dashboard import SUBJECT_CAP" in source, (
            "the cap must be read from prax, never copied into drone"
        )
        assert commit_handler.SUBJECT_CAP == prax_dashboard.SUBJECT_CAP

    def test_over_cap_subject_refused(self, repo_dir: Path) -> None:
        essay = "feat(drone): " + "x" * commit_handler.SUBJECT_CAP

        with patch("aipass.drone.apps.handlers.git.commit_handler.subprocess.run") as mock_run:
            result = commit_changes(essay)

        assert result["exit_code"] == 1
        assert result["stdout"] == ""
        assert mock_run.call_count == 0, "a refused subject must not reach git"

    def test_refusal_names_the_length_the_cap_and_the_rule(self, repo_dir: Path) -> None:
        """Mutant: a `git status` run ahead of the refusal — the refused commit reaches git."""
        essay = "feat(drone): " + "x" * commit_handler.SUBJECT_CAP
        subject_length = len(essay)

        with patch("aipass.drone.apps.handlers.git.commit_handler.subprocess.run") as mock_run:
            result = commit_changes(essay)

        mock_run.assert_not_called()

        stderr = result["stderr"]
        assert str(subject_length) in stderr, f"refusal must show the offending length: {stderr!r}"
        assert str(commit_handler.SUBJECT_CAP) in stderr, f"refusal must show the cap: {stderr!r}"
        assert "body" in stderr.lower(), f"refusal must teach where the why goes: {stderr!r}"
        assert "Nothing was committed." in stderr

    def test_subject_exactly_at_the_cap_commits(self, repo_dir: Path) -> None:
        subject = "feat(drone): " + "x" * (commit_handler.SUBJECT_CAP - len("feat(drone): "))
        assert len(subject) == commit_handler.SUBJECT_CAP

        mock_diff = MagicMock(returncode=1, stdout="", stderr="")
        mock_commit = MagicMock(returncode=0, stdout="[main cap120] at the cap", stderr="")

        with patch(
            "aipass.drone.apps.handlers.git.commit_handler.subprocess.run",
            side_effect=[mock_diff, mock_commit],
        ) as mock_run:
            result = commit_changes(subject)

        assert result["exit_code"] == 0
        _assert_ordered_calls(mock_run, [_GIT_DIFF_CACHED, _GIT_COMMIT])

    def test_a_body_of_any_length_is_wanted(self, repo_dir: Path) -> None:
        """The cap is on line 1 only — the record keeps the essay."""
        message = "feat(drone): the subject stays short\n\n" + ("the why, at length. " * 200)

        mock_diff = MagicMock(returncode=1, stdout="", stderr="")
        mock_commit = MagicMock(returncode=0, stdout="[main body99] short subject", stderr="")

        with patch(
            "aipass.drone.apps.handlers.git.commit_handler.subprocess.run",
            side_effect=[mock_diff, mock_commit],
        ):
            result = commit_changes(message)

        assert result["exit_code"] == 0

    def test_leading_blank_lines_do_not_hide_an_essay(self, repo_dir: Path) -> None:
        """git's own cleanup drops them before taking line 1; so does the gate."""
        essay = "\n\n   \nfeat(drone): " + "x" * commit_handler.SUBJECT_CAP

        with patch("aipass.drone.apps.handlers.git.commit_handler.subprocess.run") as mock_run:
            result = commit_changes(essay)

        assert result["exit_code"] == 1
        assert mock_run.call_count == 0

    def test_refusal_precedes_the_lint_and_test_lane(self, repo_dir: Path, ruff_in_venv: Path) -> None:
        """--all runs ruff and the suite; a subject refusal must cost neither, with a ruff there to run."""
        essay = "feat(drone): " + "x" * commit_handler.SUBJECT_CAP

        with patch("aipass.drone.apps.handlers.git.commit_handler.subprocess.run") as mock_run:
            result = commit_changes(essay, all_files=True)

        assert result["exit_code"] == 1
        assert mock_run.call_count == 0, "no ruff, no pytest, no git add"

    def test_refusal_precedes_repo_resolution(self, repo_dir: Path) -> None:
        """Nothing is touched — not even the repo the commit would have landed in.

        Mutant: a `git status` run ahead of the refusal — git is reached.
        """
        essay = "feat(drone): " + "x" * commit_handler.SUBJECT_CAP

        with (
            patch("aipass.drone.apps.handlers.git.commit_handler.find_repo_root") as mock_root,
            patch("aipass.drone.apps.handlers.git.commit_handler.subprocess.run") as mock_run,
        ):
            result = commit_changes(essay)

        assert result["exit_code"] == 1
        assert mock_root.call_count == 0
        mock_run.assert_not_called()

    def test_the_external_repo_door_gets_the_same_refusal(self, repo_dir: Path) -> None:
        """--repo names another repo and gets that repo's own seat — cap included."""
        essay = "feat(drone): " + "x" * commit_handler.SUBJECT_CAP

        with patch("aipass.drone.apps.handlers.git.commit_handler.subprocess.run") as mock_run:
            result = commit_changes(essay, repo_root=repo_dir)

        assert result["exit_code"] == 1
        assert str(commit_handler.SUBJECT_CAP) in result["stderr"]
        assert mock_run.call_count == 0


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
        """Mutant: `description = args[0]` in _handle_pr — only the first word reaches the PR."""
        mock_pr.return_value = {"success": True, "message": "PR created", "pr_url": "https://example.com"}
        result = handle_command("pr", ["fix", "the", "thing"])
        mock_pr.assert_called_once_with("fix the thing")
        assert result == {"stdout": "PR created", "stderr": "", "exit_code": 0}


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
        passport.write_text(json.dumps({"branch_info": {"branch_name": "test_branch"}}), encoding="utf-8")

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

    @pytest.mark.parametrize(
        ("args", "expected_flag"),
        [
            (["20"], "-20"),
            (["-n", "20"], "-20"),
            (["--count", "20"], "-20"),
            (["--max-count", "20"], "-20"),
            (["-20"], "-20"),
            ([], "-10"),
        ],
    )
    @patch("aipass.drone.apps.plugins.devpulse_ops.auth.verify_git_access", return_value="test_branch")
    def test_log_count_arg_forms(
        self, _mock_auth: MagicMock, repo_dir: Path, args: list[str], expected_flag: str
    ) -> None:
        """All git count idioms resolve to the same -N flag. `-20` used to emit `--20` (git fatal)."""
        mock_result = MagicMock(returncode=0, stdout="abc123 test\n", stderr="")
        with patch("aipass.drone.apps.handlers.git.log_handler.subprocess.run", return_value=mock_result) as mock_run:
            result = handle_command("log", args)
        assert result["exit_code"] == 0
        assert mock_run.call_args[0][0] == ["git", "log", "--oneline", expected_flag]

    @pytest.mark.parametrize("flag", ["-n", "--count", "--max-count"])
    @patch("aipass.drone.apps.plugins.devpulse_ops.auth.verify_git_access", return_value="test_branch")
    def test_log_count_flags_log_no_warning(self, _mock_auth: MagicMock, repo_dir: Path, flag: str) -> None:
        """Count flags are skipped silently — they used to warn, polluting the logs @trigger watches."""
        mock_result = MagicMock(returncode=0, stdout="abc123 test\n", stderr="")
        with (
            patch("aipass.drone.apps.handlers.git.log_handler.subprocess.run", return_value=mock_result),
            patch("aipass.drone.apps.modules.git_module.logger") as mock_logger,
        ):
            handle_command("log", [flag, "20"])
        mock_logger.warning.assert_not_called()

    @patch("aipass.drone.apps.plugins.devpulse_ops.auth.verify_git_access", return_value="test_branch")
    def test_log_unknown_arg_still_warns(self, _mock_auth: MagicMock, repo_dir: Path) -> None:
        """Unparseable args still warn, by name — the fix narrows the noise, it doesn't silence it.

        Mutant: the warning drops the '%s' argument.
        """
        mock_result = MagicMock(returncode=0, stdout="abc123 test\n", stderr="")
        with (
            patch("aipass.drone.apps.handlers.git.log_handler.subprocess.run", return_value=mock_result),
            patch("aipass.drone.apps.modules.git_module.logger") as mock_logger,
        ):
            handle_command("log", ["--bogus"])
        mock_logger.warning.assert_called_once_with("git log refused unknown argument '%s'", "--bogus")

    @pytest.mark.parametrize("bad_count", ["0", "-n 0"])
    @patch("aipass.drone.apps.plugins.devpulse_ops.auth.verify_git_access", return_value="test_branch")
    def test_log_rejects_non_positive_count(self, _mock_auth: MagicMock, repo_dir: Path, bad_count: str) -> None:
        """Zero/negative count fails honestly instead of handing git a bad flag."""
        result = handle_command("log", bad_count.split())
        assert result["exit_code"] == 1
        assert "must be 1 or greater" in result["stderr"]

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
        text = get_help()
        assert "diff" in text

    def test_help_includes_log(self) -> None:
        text = get_help()
        assert "log" in text

    def test_help_includes_commit(self) -> None:
        text = get_help()
        assert "commit" in text

    def test_help_includes_checkout(self) -> None:
        text = get_help()
        assert "checkout" in text

    def test_help_shows_tier_sections(self) -> None:
        text = get_help()
        assert "global" in text.lower()
        assert "owner" in text.lower()

    def test_help_includes_pr_command(self) -> None:
        text = get_help()
        assert "pr" in text.lower()

    def test_introspection_includes_new_handlers(self) -> None:
        text = get_introspective()
        assert "diff_handler" in text
        assert "log_handler" in text
        assert "commit_handler" in text
        assert "checkout_handler" in text

    def test_introspection_shows_tiers(self) -> None:
        text = get_introspective()
        assert "global" in text.lower()
        assert "owner" in text.lower()
