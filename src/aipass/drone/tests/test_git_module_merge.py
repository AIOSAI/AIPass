# =================== AIPass ====================
# Name: test_git_module_merge.py
# Description: Tests for the merge, dev-pr and branches lanes — protected-branch merge, return to dev, external repos
# Version: 1.3.0
# Created: 2026-10-08
# Modified: 2026-11-17
# =============================================

"""Tests for apps/plugins/devpulse_ops/merge_plugin.py and the merge, dev-pr, pr and branches handlers it pairs with."""

# The declared pass — what is NOT tested here, and what covers it instead:
# sentry: no-test-needed(stdlib) — subprocess.run, which every git and gh call here reaches as a recorded stub

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any, Iterator
from unittest.mock import patch, MagicMock

import pytest

from aipass.drone.apps.handlers.git import external_pr_handler, repo_door
from aipass.drone.apps.handlers.git.branches_handler import list_remote_branches, prune_temp_branches
from aipass.drone.apps.handlers.git.commit_handler import subject_refusal
from aipass.drone.apps.handlers.git.dev_pr_handler import DEV_PR_OUTCOME
from aipass.drone.apps.modules.git_module import handle_command
from aipass.drone.apps.plugins.devpulse_ops.merge_plugin import merge_pr

from .conftest import make_owner_project


# ===========================================================================
# Fix 1 & 2: Protected-branch merge + return-to-dev (#625)
# ===========================================================================

_MERGE_MOD = "aipass.drone.apps.plugins.devpulse_ops.merge_plugin"


@pytest.fixture
def merge_bus() -> Iterator[MagicMock]:
    """Stand a recorder where merge_pr binds the bus, so no merge test fires the live one.

    merge_pr imports ``trigger`` through trigger's door at call time; replacing the door's
    name is what the call reaches (the leg-3 bus probe counted these five on the bus).
    """
    bus = MagicMock()
    # patch, not monkeypatch.setattr: its undo would store the name on trigger's package for the whole run.
    with patch("aipass.trigger.trigger", bus):
        yield bus


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
                r.stdout = "  main\n  dev\n  citizen/drone-fix\n  citizen/sentry-pr\n"
            elif cmd[1:3] == ["branch", "-d"]:
                r.stdout = f"Deleted branch {cmd[3]}\n"
            return r

        with patch(f"{_BRANCHES_MOD}.subprocess.run", side_effect=_run):
            result = prune_temp_branches()

        assert result["count"] == 2
        assert "citizen/drone-fix" in result["pruned"]
        assert "citizen/sentry-pr" in result["pruned"]

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


# ===========================================================================
# dev-pr and merge in an external project's repo, from its manager's seat
# ===========================================================================

_REAL_RUN = subprocess.run
_GITHUB_URL = "https://github.com/acme/baud.git"
_SLUG = "acme/baud"
_PR_URL = "https://github.com/acme/baud/pull/7"
_MERGE_SHA = "f00dbabe" * 5


def _git(cwd: Path, *argv: str) -> str:
    """Run git in *cwd* for fixture setup and read-back; raises on failure."""
    return _REAL_RUN(
        ["git", *argv], cwd=str(cwd), capture_output=True, text=True, encoding="utf-8", check=True
    ).stdout.strip()


def _project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, registry_name: str) -> Path:
    """A real repo whose manager stands at its root: main pushed to a bare origin, dev one commit ahead.

    Git runs with no host config and a fixed identity; the caller carries no AIPASS_CALLER_CWD stamp.
    """
    empty_config = tmp_path / "gitconfig"
    empty_config.write_text("", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(empty_config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", os.pathsep.join(sorted({str(tmp_path), str(tmp_path.resolve())})))
    for name in ("GIT_AUTHOR_NAME", "GIT_COMMITTER_NAME"):
        monkeypatch.setenv(name, "Baud Test")
    for name in ("GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL"):
        monkeypatch.setenv(name, "baud@test.invalid")
    monkeypatch.delenv("AIPASS_CALLER_CWD", raising=False)

    bare = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(bare))
    work = tmp_path / "baud"
    make_owner_project(work, branch="BAUD", registry_name=registry_name)
    _git(work, "init", "-q", "-b", "main")
    (work / "README.md").write_text("baud\n", encoding="utf-8")
    _git(work, "add", "README.md")
    _git(work, "commit", "-q", "-m", "seed")
    _git(work, "remote", "add", "origin", str(bare))
    _git(work, "push", "-q", "origin", "main")
    _git(work, "checkout", "-q", "-b", "dev")
    _commit(work, "app.txt", "feat: tier prompt")
    monkeypatch.chdir(work)
    return work


def _commit(work: Path, name: str, subject: str) -> str:
    """Commit one new file in *work* and return the new HEAD."""
    (work / name).write_text(f"{subject}\n", encoding="utf-8")
    _git(work, "add", name)
    _git(work, "commit", "-q", "-m", subject)
    return _git(work, "rev-parse", "HEAD")


@pytest.fixture()
def baud_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """BAUD's own repo, its manager at the root."""
    return _project(tmp_path, monkeypatch, "BAUD_REGISTRY.json")


class _GitHub:
    """gh as GitHub answers, origin's URL as github.com names it; every other git call runs for real."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.origin_on_github = True
        self.pr = {"headRefName": "dev", "title": "feat: tier prompt"}
        self.create: tuple[int, str, str] = (0, f"{_PR_URL}\n", "")
        self.merge: tuple[int, str, str] = (0, "", "")
        self.default = "main"

    def __call__(self, argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
        if argv[:4] == ["git", "remote", "get-url", "origin"] and self.origin_on_github:
            return subprocess.CompletedProcess(argv, 0, f"{_GITHUB_URL}\n", "")
        if argv[0] != "gh":
            return _REAL_RUN(argv, **kwargs)
        self.calls.append(list(argv))
        if argv[2] == "create":
            rc, out, err = self.create
        elif argv[2] == "merge":
            rc, out, err = self.merge
        elif argv[1] == "repo":
            rc, out, err = 0, f"{self.default}\n", ""
        elif "mergeCommit" in argv:
            rc, out, err = 0, f"{_MERGE_SHA}\n", ""
        else:
            rc, out, err = 0, json.dumps(self.pr), ""
        return subprocess.CompletedProcess(argv, rc, out, err)


@pytest.fixture()
def github(monkeypatch: pytest.MonkeyPatch) -> _GitHub:
    """Stand the GitHub edge where every git and gh call in the product reaches it."""
    edge = _GitHub()
    monkeypatch.setattr(subprocess, "run", edge)
    return edge


def _origin_dev(work: Path) -> str:
    """origin's dev, read from the bare repo itself ('' when it has none)."""
    found = _REAL_RUN(
        ["git", "rev-parse", "--verify", "-q", "refs/heads/dev"],
        cwd=str(work.parent / "origin.git"),
        capture_output=True,
        text=True,
    )
    return found.stdout.strip()


class TestExternalDevPrOpensThePrOnOriginsRepo:
    """dev-pr from an external repo's manager pushes dev and opens dev -> main on origin's GitHub repo."""

    def test_dev_is_pushed_and_the_pr_opens_on_the_slug_from_origin(self, baud_repo: Path, github: _GitHub) -> None:
        """Mutant: the -R slug dropped — gh would pick a repo from whatever remotes it finds."""
        result = handle_command("dev-pr", ["Adopt", "tier", "prompt"])

        assert result == {"stdout": f"PR created: {_PR_URL}", "stderr": "", "exit_code": 0}
        assert github.calls == [
            [
                "gh",
                "pr",
                "create",
                "-R",
                _SLUG,
                "--head",
                "dev",
                "--base",
                "main",
                "--title",
                "Adopt tier prompt",
                "--body",
                "",
            ]
        ]
        assert _origin_dev(baud_repo) == _git(baud_repo, "rev-parse", "dev")

    def test_an_open_pr_for_dev_answers_its_url_after_the_push(self, baud_repo: Path, github: _GitHub) -> None:
        github.create = (1, "", f'a pull request for branch "dev" into branch "main" already exists:\n{_PR_URL}\n')

        result = handle_command("dev-pr", ["Adopt"])

        assert result == {"stdout": f"Pushed dev. PR already open: {_PR_URL}", "stderr": "", "exit_code": 0}
        assert _origin_dev(baud_repo) == _git(baud_repo, "rev-parse", "dev")

    def test_an_aipass_repo_keeps_its_own_lane(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, github: _GitHub
    ) -> None:
        """Mutant: the lane test inverted — AIPass's own PR would be aimed by origin's slug."""
        _project(tmp_path, monkeypatch, "AIPASS_REGISTRY.json")

        result = handle_command("dev-pr", ["Adopt"])

        assert result["exit_code"] == 0
        assert github.calls == [
            ["gh", "pr", "create", "--head", "dev", "--base", "main", "--title", "Adopt", "--body", ""]
        ]


class TestExternalDevPrRefusesBeforeAnyPush:
    """dev-pr refuses off dev, with tracked changes, with dev level with main, or with no github origin."""

    def test_off_dev_is_refused(self, baud_repo: Path, github: _GitHub) -> None:
        """Mutant: the on-dev check removed — main's tip is pushed as dev."""
        _git(baud_repo, "checkout", "-q", "main")

        result = handle_command("dev-pr", ["Adopt"])

        assert result["stderr"] == external_pr_handler.REFUSE_NOT_ON_DEV.format(branch="main")
        assert result["exit_code"] == 1
        assert (github.calls, _origin_dev(baud_repo)) == ([], "")

    def test_a_modified_tracked_file_is_refused(self, baud_repo: Path, github: _GitHub) -> None:
        """Mutant: the clean-tree check removed — the PR opens without the change the manager made."""
        (baud_repo / "app.txt").write_text("edited\n", encoding="utf-8")
        (baud_repo / "notes.txt").write_text("untracked never blocks\n", encoding="utf-8")

        result = handle_command("dev-pr", ["Adopt"])

        assert result["stderr"] == external_pr_handler.REFUSE_DIRTY.format(count=1)
        assert (github.calls, _origin_dev(baud_repo)) == ([], "")

    def test_dev_level_with_origin_main_is_refused(self, baud_repo: Path, github: _GitHub) -> None:
        """Mutant: the ahead check removed — gh is asked for a PR with no commits."""
        _git(baud_repo, "push", "-q", "origin", "dev:main")

        result = handle_command("dev-pr", ["Adopt"])

        assert result["stderr"] == external_pr_handler.REFUSE_NOT_AHEAD.format(head="dev", base="main")
        assert (github.calls, _origin_dev(baud_repo)) == ([], "")

    def test_an_origin_off_github_is_refused(self, baud_repo: Path, github: _GitHub) -> None:
        """Mutant: the no-slug refusal removed — gh is handed -R None."""
        github.origin_on_github = False

        result = handle_command("dev-pr", ["Adopt"])

        assert result["stderr"] == "dev-pr failed: " + external_pr_handler.REFUSE_NO_GITHUB.format(repo=baud_repo)
        assert (github.calls, _origin_dev(baud_repo)) == ([], "")


class TestDevPrTitleIsCappedAtHome:
    """dev-pr measures its description against the commit subject cap before any push, in either lane."""

    @pytest.mark.parametrize("registry_name", ["AIPASS_REGISTRY.json", "BAUD_REGISTRY.json"])
    def test_a_257_char_description_is_refused_before_the_push(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, github: _GitHub, registry_name: str
    ) -> None:
        """Mutant: the subject_refusal call removed — dev is pushed and GitHub refuses the title after."""
        work = _project(tmp_path, monkeypatch, registry_name)

        result = handle_command("dev-pr", ["x" * 257])

        assert result == {"stdout": "", "stderr": subject_refusal("x" * 257, DEV_PR_OUTCOME), "exit_code": 1}
        assert result["stderr"].endswith("\n\nThe PR title was refused. Nothing was pushed.")
        assert (github.calls, _origin_dev(work)) == ([], "")

    def test_a_100_char_description_opens_the_pr(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, github: _GitHub
    ) -> None:
        """Mutant: the cap measured with < instead of the shared refusal — a title under the cap refused."""
        _project(tmp_path, monkeypatch, "AIPASS_REGISTRY.json")

        result = handle_command("dev-pr", ["y" * 100])

        assert result["exit_code"] == 0
        assert github.calls[0][-3:] == ["y" * 100, "--body", ""]


class TestExternalMergeBringsLocalDevUp:
    """merge from an external repo's manager merges on origin's repo, then fast-forwards local dev."""

    @pytest.fixture()
    def behind(self, baud_repo: Path) -> str:
        """origin/dev one commit past local dev, the manager standing on main; returns origin's dev."""
        _git(baud_repo, "push", "-q", "origin", "dev")
        ahead = _commit(baud_repo, "more.txt", "feat: more")
        _git(baud_repo, "push", "-q", "origin", "dev")
        _git(baud_repo, "reset", "-q", "--hard", "HEAD~1")
        _git(baud_repo, "checkout", "-q", "main")
        return ahead

    def test_the_pr_merges_on_the_slug_and_local_dev_lands_on_origins(
        self, baud_repo: Path, behind: str, github: _GitHub, merge_bus: MagicMock
    ) -> None:
        """Mutants: checkout dropped, fast-forward dropped, or AIPass's pr_merged fired for BAUD's PR."""
        result = handle_command("merge", ["7", "--confirm"])

        assert result == {
            "stdout": f"PR #7 merged: feat: tier prompt ({_MERGE_SHA[:8]}) — local dev is current",
            "stderr": "",
            "exit_code": 0,
        }
        assert ["gh", "pr", "merge", "7", "-R", _SLUG, "--merge"] in github.calls
        assert _git(baud_repo, "rev-parse", "--abbrev-ref", "HEAD") == "dev"
        assert _git(baud_repo, "rev-parse", "HEAD") == behind
        merge_bus.fire.assert_not_called()

    @pytest.mark.parametrize(("head", "deletes"), [("citizen/x", True), ("dev", False), ("main", False), ("", False)])
    def test_only_a_known_unprotected_head_is_deleted(
        self, baud_repo: Path, behind: str, github: _GitHub, merge_bus: MagicMock, head: str, deletes: bool
    ) -> None:
        """Mutant: --delete-branch always passed — a PR from dev would delete dev on GitHub."""
        github.pr = {"headRefName": head, "title": "t"}

        handle_command("merge", ["7", "--confirm"])

        merges = [call for call in github.calls if call[2] == "merge"]
        assert merges == [["gh", "pr", "merge", "7", "-R", _SLUG, "--merge", *(["--delete-branch"] if deletes else [])]]

    def test_a_diverged_local_dev_fails_and_still_names_the_merge(
        self, baud_repo: Path, behind: str, github: _GitHub, merge_bus: MagicMock
    ) -> None:
        """Mutant: the local failure reported as success — the manager is told dev is current when it is not."""
        _git(baud_repo, "checkout", "-q", "dev")
        mine = _commit(baud_repo, "mine.txt", "feat: local only")

        result = handle_command("merge", ["7", "--confirm"])

        assert result["exit_code"] == 1
        assert result["stderr"].startswith(
            f"PR #7 merged on {_SLUG}: feat: tier prompt, but local dev was not brought up:"
        )
        assert _git(baud_repo, "rev-parse", "HEAD") == mine

    def test_a_refused_merge_leaves_the_local_tree_alone(
        self, baud_repo: Path, behind: str, github: _GitHub, merge_bus: MagicMock
    ) -> None:
        github.merge = (1, "", "Pull request acme/baud#7 is not mergeable")

        result = handle_command("merge", ["7", "--confirm"])

        assert result["stderr"].startswith(
            "Merge failed: gh pr merge failed: Pull request acme/baud#7 is not mergeable"
        )
        assert _git(baud_repo, "rev-parse", "--abbrev-ref", "HEAD") == "main"


@pytest.fixture()
def door(baud_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The admin seat in its own home, BAUD on a working branch named neither dev nor main; returns the --repo args."""
    _git(baud_repo, "checkout", "-q", "-b", "work")
    monkeypatch.setattr(repo_door, "admin_verdict", lambda: repo_door.AdminVerdict(True, "devpulse", ""))
    monkeypatch.chdir(make_owner_project(tmp_path / "home"))
    return ["--repo", str(baud_repo)]


def _origin_has(work: Path, branch: str) -> str:
    """*branch* on origin, read from the bare repo itself ('' when it has none)."""
    found = _REAL_RUN(
        ["git", "rev-parse", "--verify", "-q", f"refs/heads/{branch}"],
        cwd=str(work.parent / "origin.git"),
        capture_output=True,
        text=True,
    )
    return found.stdout.strip()


def _door_rows(tmp_path: Path) -> list[tuple[str, str, str]]:
    path = tmp_path / repo_door.LEDGER_NAME
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []
    return [(row["verb"], row["outcome"], row["caller"]) for row in rows]


class TestDoorPrOpensTheCheckedOutBranchToTheDefault:
    """pr --repo pushes the checked-out branch and opens it against the default branch GitHub reports."""

    def test_the_working_branch_opens_against_the_reported_default(
        self, baud_repo: Path, tmp_path: Path, door: list[str], github: _GitHub
    ) -> None:
        """Mutants: head hardcoded to dev, base hardcoded to main, or the -R slug dropped."""
        _git(baud_repo, "push", "-q", "origin", "main:stable")
        github.default = "stable"

        result = handle_command("pr", ["Adopt", "tier", "prompt", *door])

        assert result == {"stdout": f"PR created: {_PR_URL}", "stderr": "", "exit_code": 0}
        assert github.calls[-1] == [
            *("gh", "pr", "create", "-R", _SLUG, "--head", "work", "--base", "stable"),
            *("--title", "Adopt tier prompt", "--body", ""),
        ]
        assert _origin_has(baud_repo, "work") == _git(baud_repo, "rev-parse", "work")
        assert _door_rows(tmp_path) == [("pr", "ran", "devpulse")]

    def test_an_open_pr_for_the_branch_answers_its_url(self, door: list[str], github: _GitHub) -> None:
        github.create = (1, "", f'a pull request for branch "work" into branch "main" already exists:\n{_PR_URL}\n')

        result = handle_command("pr", ["Adopt", *door])

        assert result == {"stdout": f"Pushed work. PR already open: {_PR_URL}", "stderr": "", "exit_code": 0}

    def test_the_default_branch_checked_out_is_refused_before_any_push(
        self, baud_repo: Path, door: list[str], github: _GitHub
    ) -> None:
        """Mutant: the head == base check removed — gh is asked for main -> main after a push."""
        _git(baud_repo, "checkout", "-q", "main")
        before = _origin_has(baud_repo, "main")

        result = handle_command("pr", ["Adopt", *door])

        expected = external_pr_handler.REFUSE_ON_DEFAULT.format(repo=baud_repo.resolve(), branch="main")
        assert (result["stderr"], result["exit_code"]) == (expected, 1)
        assert [call[1] for call in github.calls] == ["repo"]
        assert _origin_has(baud_repo, "main") == before

    def test_a_detached_head_is_refused_before_github_is_asked(
        self, baud_repo: Path, door: list[str], github: _GitHub
    ) -> None:
        """Mutant: the detached check removed — a branch literally named HEAD is pushed."""
        _git(baud_repo, "checkout", "-q", "--detach")

        result = handle_command("pr", ["Adopt", *door])

        assert result["stderr"] == external_pr_handler.REFUSE_DETACHED.format(repo=baud_repo.resolve())
        assert github.calls == []

    def test_an_over_cap_title_is_refused_before_the_push(
        self, baud_repo: Path, door: list[str], github: _GitHub
    ) -> None:
        """Mutant: the subject_refusal call removed — work is pushed and GitHub refuses the title after."""
        result = handle_command("pr", ["x" * 257, *door])

        assert result["stderr"] == subject_refusal("x" * 257, DEV_PR_OUTCOME)
        assert (github.calls, _origin_has(baud_repo, "work")) == ([], "")

    def test_a_seat_without_the_admin_grant_is_refused(
        self, baud_repo: Path, door: list[str], github: _GitHub, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(repo_door, "admin_verdict", lambda: repo_door.AdminVerdict(False, "baud", "not admin"))

        result = handle_command("pr", ["Adopt", *door])

        assert (result["stderr"], github.calls, _origin_has(baud_repo, "work")) == ("not admin", [], "")


class TestDoorMergeKeepsTheWorkingBranch:
    """merge --repo merges on origin's repo as a merge commit, gated; it deletes no branch and moves nothing local."""

    def test_the_pr_merges_and_its_head_branch_is_kept(
        self, baud_repo: Path, tmp_path: Path, door: list[str], github: _GitHub
    ) -> None:
        """Mutant: the door merge deletes an unprotected head — BAUD's working branch would go with it."""
        github.pr = {"headRefName": "work", "title": "feat: tier prompt"}
        head = _git(baud_repo, "rev-parse", "HEAD")

        result = handle_command("merge", ["7", "--confirm", *door])

        assert result == {
            "stdout": f"PR #7 merged on {_SLUG}: feat: tier prompt ({_MERGE_SHA[:8]}). {external_pr_handler.KEPT}",
            "stderr": "",
            "exit_code": 0,
        }
        merges = [call for call in github.calls if call[2] == "merge"]
        assert merges == [["gh", "pr", "merge", "7", "-R", _SLUG, "--merge"]]
        assert _git(baud_repo, "rev-parse", "--abbrev-ref", "HEAD") == "work"
        assert _git(baud_repo, "rev-parse", "HEAD") == head
        assert _door_rows(tmp_path) == [("merge", "ran", "devpulse")]

    def test_headless_without_confirm_is_refused_and_names_the_door(
        self, baud_repo: Path, door: list[str], github: _GitHub
    ) -> None:
        """Mutant: the re-run line without --repo — typed as printed, it merges AIPass's own PR #7."""
        result = handle_command("merge", ["7", *door])

        assert result["exit_code"] == 1
        assert result["stderr"].endswith(f"drone @git merge 7 --repo {baud_repo.resolve()} --confirm")
        assert github.calls == []

    def test_a_red_required_check_refuses_with_ghs_words(self, door: list[str], github: _GitHub) -> None:
        github.merge = (1, "", 'Required status check "ci" is failing')

        result = handle_command("merge", ["7", "--confirm", *door])

        assert result["stderr"] == 'Merge failed: gh pr merge failed: Required status check "ci" is failing'
        assert result["exit_code"] == 1
