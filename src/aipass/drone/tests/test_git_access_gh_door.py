# =================== AIPass ====================
# Name: test_git_access_gh_door.py
# Description: Tests for the gh passthrough verbs, release edit and the external-repo door (--repo)
# Version: 1.7.0
# Created: 2026-10-08
# Modified: 2026-10-19
# =============================================

"""Tests for apps/handlers/git/repo_door.py, the gh verbs and release edit of apps/modules/git_module.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(stdlib) — subprocess.run; gh is stubbed, git runs only in the tmp_path repos of the door tests

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from aipass.drone.apps.plugins.devpulse_ops.auth import (
    GIT_ACCESS_TIERS,
    verify_git_access,
)
from aipass.drone.apps.handlers.git import release_handler, repo_door, untrack_handler
from aipass.drone.apps.modules.git_module import get_help, get_introspective, handle_command

from .conftest import GITHUB_SLUG, chore_ledger, github_stand_in, make_owner_project


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
        assert "issue" in get_help()

    def test_help_includes_run(self) -> None:
        assert "run" in get_help()

    def test_help_includes_workflow(self) -> None:
        assert "workflow" in get_help()

    def test_per_command_help_issue(self) -> None:
        text = get_help("issue")
        assert "gh issue" in text
        assert "global" in text.lower()

    def test_per_command_help_run(self) -> None:
        text = get_help("run")
        assert "gh run" in text

    def test_per_command_help_workflow(self) -> None:
        text = get_help("workflow")
        assert "gh workflow" in text

    def test_introspection_includes_passthrough(self) -> None:
        text = get_introspective()
        assert "issue" in text
        assert "run" in text
        assert "workflow" in text


# ===========================================================================
# External-repo door — --repo <path>, admin seat only (DPLAN-0344)
# ===========================================================================

_RAIL = "aipass.ai_mail.apps.modules.door_verified_caller"


def _git(cwd: Path, *argv: str) -> str:
    """Run git in *cwd* for fixture setup and read-back; raises on failure."""
    return subprocess.run(
        ["git", *argv], cwd=str(cwd), capture_output=True, text=True, encoding="utf-8", check=True
    ).stdout.strip()


def _ledger(tmp_path: Path) -> list[dict]:
    """The door's records, read from beside this test's isolated deletion log."""
    path = tmp_path / "git_repo_door.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


@pytest.fixture()
def door_world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """An AIPass-shaped root with a devpulse seat, and an external repo with its own origin.

    Git runs with no host config, a fixed identity, and a ceiling at tmp_path, so
    no repository above the sandbox can answer for a directory inside it. The
    caller env is cleared: this suite runs inside agent sessions whose
    AIPASS_BRANCH_NAME would otherwise decide who the door sees.
    """
    empty_config = tmp_path / "gitconfig"
    empty_config.write_text("", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(empty_config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", os.pathsep.join(sorted({str(tmp_path), str(tmp_path.resolve())})))
    for name in ("GIT_AUTHOR_NAME", "GIT_COMMITTER_NAME"):
        monkeypatch.setenv(name, "Door Test")
    for name in ("GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL"):
        monkeypatch.setenv(name, "door@test.invalid")
    for name in ("AIPASS_BRANCH_NAME", "AIPASS_CALLER_CWD", "AIPASS_CALLER_BRANCH", "AIPASS_CALLER_IDENTITY_SOURCE"):
        monkeypatch.delenv(name, raising=False)

    root = tmp_path / "aipass"
    seat = make_owner_project(root, branch_dir=root / "src" / "aipass" / "devpulse")
    ext = root / "projects" / "ext"
    ext.mkdir(parents=True)
    _git(ext, "init", "-q", "-b", "main")
    (ext / "README.md").write_text("ext\n", encoding="utf-8")
    _git(ext, "add", "README.md")
    _git(ext, "commit", "-q", "-m", "seed")
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", str(origin))
    _git(ext, "remote", "add", "origin", str(origin))
    _git(ext, "push", "-q", "origin", "main")
    monkeypatch.chdir(seat)
    return {"root": root, "seat": seat, "ext": ext, "origin": origin}


class TestRepoDoorRefusals:
    """--repo refuses by name before it touches the repo, and records every refusal."""

    def test_a_project_manager_standing_in_its_own_repo_is_refused(
        self, door_world: dict[str, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """baud's manager, inside baud, owner of baud, is still not the admin seat. Real rail, nothing patched."""
        ext = door_world["ext"]
        make_owner_project(ext, branch="baud", registry_name="BAUD_REGISTRY.json")
        monkeypatch.chdir(ext)
        head = _git(ext, "rev-parse", "HEAD")

        result = handle_command("commit", ["release", "--all", "--repo", str(ext)])

        assert result == {"stdout": "", "stderr": repo_door.REFUSE_NOT_ADMIN.format(caller="@baud"), "exit_code": 1}
        assert "@baud holds no admin grant" in result["stderr"]
        assert _git(ext, "rev-parse", "HEAD") == head
        assert _git(ext, "diff", "--cached", "--name-only") == ""
        [record] = _ledger(tmp_path)
        assert (record["outcome"], record["caller"], record["verb"], record["exit_code"]) == (
            "refused",
            "@baud",
            "commit",
            1,
        )
        assert record["reason"] == result["stderr"]
        assert "AIPASS_CALLER_BRANCH" not in os.environ
        assert "AIPASS_CALLER_CWD" not in os.environ

    def test_the_devpulse_seat_without_a_verified_grant_is_refused(self, door_world: dict[str, Path]) -> None:
        """Standing in the devpulse seat buys nothing: the grant decides, not the directory."""
        ext, origin = door_world["ext"], door_world["origin"]
        seed = _git(ext, "rev-parse", "HEAD")
        (ext / "new.txt").write_text("new\n", encoding="utf-8")
        _git(ext, "add", "new.txt")
        _git(ext, "commit", "-q", "-m", "local only")

        with patch(f"{_RAIL}.is_verified_admin_caller", return_value=False):
            result = handle_command("push", ["--repo", "projects/ext"])

        assert result == {"stdout": "", "stderr": repo_door.REFUSE_NOT_ADMIN.format(caller="@devpulse"), "exit_code": 1}
        assert _git(origin, "rev-parse", "main") == seed

    @pytest.mark.parametrize("shape", ["another_checkout_carrying_the_registry", "the_callers_own_root_without_one"])
    def test_the_aipass_repo_is_refused_even_for_the_admin(self, door_world: dict[str, Path], shape: str) -> None:
        """Either fact alone marks AIPass: a clean clone carries no registry, and a copy elsewhere is not our root."""
        if shape == "another_checkout_carrying_the_registry":
            target = door_world["root"].parent / "aipass-clone"
            target.mkdir()
            (target / "AIPASS_REGISTRY.json").write_text("{}", encoding="utf-8")
        else:
            target = door_world["root"]
            (target / "AIPASS_REGISTRY.json").unlink()
        _git(target, "init", "-q", "-b", "main")

        with patch(f"{_RAIL}.is_verified_admin_caller", return_value=True):
            result = handle_command("status", ["--repo", str(target)])

        assert result == {"stdout": "", "stderr": repo_door.REFUSE_AIPASS.format(path=str(target)), "exit_code": 1}

    def test_a_directory_that_is_not_a_repo_is_refused(self, door_world: dict[str, Path]) -> None:
        (door_world["root"] / "projects" / "plain").mkdir()

        with patch(f"{_RAIL}.is_verified_admin_caller", return_value=True):
            result = handle_command("log", ["--repo", "projects/plain"])

        assert result == {
            "stdout": "",
            "stderr": repo_door.REFUSE_NOT_REPO.format(path="projects/plain"),
            "exit_code": 1,
        }

    def test_git_that_cannot_run_is_named_not_read_as_no_repo(
        self, door_world: dict[str, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Mutant: _git_toplevel's except returns None — git failing to run reads as "not a git repository"."""
        (door_world["root"] / "projects" / "plain").mkdir()
        monkeypatch.setenv("PATH", "")

        with patch(f"{_RAIL}.is_verified_admin_caller", return_value=True):
            result = handle_command("log", ["--repo", "projects/plain"])

        assert result["exit_code"] == 1
        assert result["stderr"] != repo_door.REFUSE_NOT_REPO.format(path="projects/plain")
        assert result["stderr"].startswith("--repo projects/plain: git could not run")

    def test_a_path_that_does_not_exist_is_refused(self, door_world: dict[str, Path], tmp_path: Path) -> None:
        with patch(f"{_RAIL}.is_verified_admin_caller", return_value=True):
            result = handle_command("tag", ["v0.2.0", "--repo", "projects/nowhere"])

        assert result == {
            "stdout": "",
            "stderr": repo_door.REFUSE_MISSING.format(path="projects/nowhere"),
            "exit_code": 1,
        }
        [record] = _ledger(tmp_path)
        assert (record["outcome"], record["caller"], record["verb"]) == ("refused", "@devpulse", "tag")

    def test_a_folder_inside_the_repo_is_refused_rather_than_widened(self, door_world: dict[str, Path]) -> None:
        (door_world["ext"] / "docs").mkdir()

        with patch(f"{_RAIL}.is_verified_admin_caller", return_value=True):
            result = handle_command("status", ["--repo", "projects/ext/docs"])

        expected = repo_door.REFUSE_NOT_TOP.format(path="projects/ext/docs", toplevel=door_world["ext"].resolve())
        assert result == {"stdout": "", "stderr": expected, "exit_code": 1}

    @pytest.mark.parametrize(
        ("command", "args", "expected"),
        [
            ("merge", ["12", "--confirm", "--repo", "projects/ext"], repo_door.REFUSE_VERB.format(verb="merge")),
            ("status", ["--repo"], repo_door.REFUSE_NO_VALUE),
            ("status", ["--repo", "projects/ext", "--repo=projects/ext"], repo_door.REFUSE_TWICE),
            ("push", ["--force", "--repo", "projects/ext"], repo_door.REFUSE_PUSH_ARGS),
        ],
    )
    def test_the_door_refuses_what_it_does_not_serve(
        self, door_world: dict[str, Path], command: str, args: list[str], expected: str
    ) -> None:
        head = _git(door_world["origin"], "rev-parse", "main")

        with patch(f"{_RAIL}.is_verified_admin_caller", return_value=True):
            result = handle_command(command, args)

        assert result == {"stdout": "", "stderr": expected, "exit_code": 1}
        assert _git(door_world["origin"], "rev-parse", "main") == head

    def test_help_prints_the_refusals_the_door_prints(self) -> None:
        text = get_help()
        assert repo_door.REFUSE_NOT_ADMIN.format(caller="<caller>") in text
        assert repo_door.REFUSE_AIPASS.format(path="<path>") in text
        assert "push --repo <path>" in text


class TestRepoDoorHappyPath:
    """The admin seat reads, commits, pushes and tags a real repo with a real origin."""

    def test_the_door_record_lands_in_aipass_and_nothing_new_in_the_target_repo(
        self, door_world: dict[str, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Mutant: the ledger follows the caller's directory — a project's own .ai_central gets AIPass's audit."""
        ext = door_world["ext"]
        (ext / "EXT_REGISTRY.json").write_text("{}", encoding="utf-8")
        before = sorted(p.relative_to(ext) for p in ext.rglob("*") if ".git" not in p.parts)
        monkeypatch.delenv("AIPASS_DELETION_LOG", raising=False)
        monkeypatch.setenv("AIPASS_HOME", str(door_world["root"]))
        monkeypatch.chdir(ext)

        with patch(f"{_RAIL}.is_verified_admin_caller", return_value=True):
            handle_command("status", ["--repo", str(ext)])

        after = sorted(p.relative_to(ext) for p in ext.rglob("*") if ".git" not in p.parts)
        assert after == before
        [row] = [
            json.loads(line)
            for line in (door_world["root"] / ".ai_central" / "git_repo_door.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        assert (row["verb"], row["repo"]) == ("status", str(ext.resolve()))

    def test_the_admin_lands_a_release_in_an_external_repo(self, door_world: dict[str, Path], tmp_path: Path) -> None:
        root, ext, origin = door_world["root"], door_world["ext"], door_world["origin"]
        seed = _git(ext, "rev-parse", "HEAD")
        (ext / "release.yml").write_text("on: push\n", encoding="utf-8")

        with patch(f"{_RAIL}.is_verified_admin_caller", return_value=True):
            status = handle_command("status", ["--repo", "projects/ext"])
            commit = handle_command("commit", ["add release workflow", "release.yml", "--repo", "projects/ext"])
            origin_after_commit = _git(origin, "rev-parse", "main")
            push = handle_command("push", ["--repo=projects/ext"])
            tag = handle_command("tag", ["v0.2.0", "--repo", "projects/ext"])
            log = handle_command("log", ["1", "--repo", "projects/ext"])
        head = _git(ext, "rev-parse", "HEAD")

        assert status["exit_code"] == 0
        assert "?? release.yml" in status["stdout"]
        assert commit["exit_code"] == 0
        assert _git(ext, "log", "-1", "--format=%P %s") == f"{seed} add release workflow"
        assert origin_after_commit == seed, "commit must never push"
        assert push["exit_code"] == 0
        assert _git(origin, "rev-parse", "main") == head
        assert tag == {
            "stdout": f"Tagged v0.2.0 at ext HEAD ({head}) and pushed to origin.",
            "stderr": "",
            "exit_code": 0,
        }
        assert _git(origin, "rev-parse", "v0.2.0^{commit}") == head
        assert log["exit_code"] == 0
        assert log["stdout"].startswith(head[:7]) and log["stdout"].endswith(" add release workflow")
        assert not (root / ".git_pr.lock").exists()

        records = _ledger(tmp_path)
        assert [(r["verb"], r["outcome"], r["exit_code"], r["caller"]) for r in records] == [
            ("status", "ran", 0, "@devpulse"),
            ("commit", "ran", 0, "@devpulse"),
            ("push", "ran", 0, "@devpulse"),
            ("tag", "ran", 0, "@devpulse"),
            ("log", "ran", 0, "@devpulse"),
        ]
        assert (records[1]["head_before"], records[1]["head_after"]) == (seed, head)
        assert (records[2]["head_before"], records[2]["head_after"]) == (head, head)
        assert {r["repo"] for r in records} == {str(ext.resolve())}
        assert records[1]["args"] == ["add release workflow", "release.yml"]


def _remote_commit(world: dict[str, Path], name: str) -> str:
    """Land one commit on origin's main from a second clone, as another machine would; return its sha."""
    other = world["origin"].parent / "other"
    if not other.exists():
        _git(other.parent, "clone", "-q", "-b", "main", str(world["origin"]), str(other))
    (other / name).write_text(f"{name}\n", encoding="utf-8")
    _git(other, "add", name)
    _git(other, "commit", "-q", "-m", f"remote {name}")
    _git(other, "push", "-q", "origin", "main")
    return _git(other, "rev-parse", "HEAD")


def _local_commit(ext: Path, name: str) -> str:
    """One commit in the door's repo that origin does not have; return its sha."""
    (ext / name).write_text(f"{name}\n", encoding="utf-8")
    _git(ext, "add", name)
    _git(ext, "commit", "-q", "-m", f"local {name}")
    return _git(ext, "rev-parse", "HEAD")


@pytest.fixture()
def tracked_world(door_world: dict[str, Path]) -> dict[str, Path]:
    """door_world with ext's main tracking origin/main, as a clone made by `git clone` would."""
    _git(door_world["ext"], "branch", "-q", "--set-upstream-to=origin/main", "main")
    return door_world


class TestRepoDoorFetchAndSync:
    """fetch shows what the remote has; sync fast-forwards onto it or refuses, never rebasing or merging."""

    def test_fetch_prints_ahead_behind_and_the_behind_commits_and_moves_nothing_local(
        self, tracked_world: dict[str, Path], tmp_path: Path
    ) -> None:
        """Mutant: _commit_lines' range reversed for behind — the remote's commit is not listed."""
        ext = tracked_world["ext"]
        head = _git(ext, "rev-parse", "HEAD")
        remote = _remote_commit(tracked_world, "upstream.txt")

        with patch(f"{_RAIL}.is_verified_admin_caller", return_value=True):
            result = handle_command("fetch", ["--repo", "projects/ext"])

        assert result["exit_code"] == 0
        assert result["stdout"] == (
            f"Fetched origin in {ext.resolve()}.\n"
            "'main' against origin/main: ahead 0, behind 1.\n"
            "Behind: on origin/main, not here (newest first):\n"
            f"  {remote[:7]} remote upstream.txt"
        )
        assert _git(ext, "rev-parse", "HEAD") == head
        assert _git(ext, "rev-parse", "origin/main") == remote
        assert not (ext / "upstream.txt").exists()
        [record] = _ledger(tmp_path)
        assert (record["verb"], record["outcome"], record["head_before"], record["head_after"]) == (
            "fetch",
            "ran",
            head,
            head,
        )

    def test_sync_fast_forwards_when_only_behind(self, tracked_world: dict[str, Path], tmp_path: Path) -> None:
        ext = tracked_world["ext"]
        head = _git(ext, "rev-parse", "HEAD")
        remote = _remote_commit(tracked_world, "upstream.txt")
        (ext / "scratch.aipass-new").write_text("untracked\n", encoding="utf-8")

        with patch(f"{_RAIL}.is_verified_admin_caller", return_value=True):
            result = handle_command("sync", ["--repo=projects/ext"])

        assert result == {
            "stdout": (
                f"Fast-forwarded 'main' onto origin/main in {ext.resolve()}: 1 commit(s).\n"
                "Now here (newest first):\n"
                f"  {remote[:7]} remote upstream.txt"
            ),
            "stderr": "",
            "exit_code": 0,
        }
        assert _git(ext, "rev-parse", "HEAD") == remote
        assert _git(ext, "log", "-1", "--format=%P") == head, "a fast-forward makes no merge commit"
        assert (ext / "scratch.aipass-new").exists(), "an untracked file neither blocks nor is touched"
        [record] = _ledger(tmp_path)
        assert (record["verb"], record["head_before"], record["head_after"]) == ("sync", head, remote)

    def test_sync_refuses_a_diverged_branch_printing_both_lists(self, tracked_world: dict[str, Path]) -> None:
        """Mutant: the divergence check removed — git's own ff-only error comes back instead of the refusal."""
        ext = tracked_world["ext"]
        remote = _remote_commit(tracked_world, "upstream.txt")
        local = _local_commit(ext, "here.txt")

        with patch(f"{_RAIL}.is_verified_admin_caller", return_value=True):
            result = handle_command("sync", ["--repo", "projects/ext"])

        refusal = repo_door.REFUSE_DIVERGED.format(
            branch="main", upstream="origin/main", repo=ext.resolve(), ahead=1, behind=1
        )
        assert result == {
            "stdout": "",
            "stderr": (
                f"{refusal}\n"
                "Behind: on origin/main, not here (newest first):\n"
                f"  {remote[:7]} remote upstream.txt\n"
                "Ahead: here, not on origin/main (newest first):\n"
                f"  {local[:7]} local here.txt"
            ),
            "exit_code": 1,
        }
        assert _git(ext, "rev-parse", "HEAD") == local
        assert _git(ext, "rev-parse", "origin/main") == remote

    def test_sync_refuses_a_tracked_change_before_fetching(self, tracked_world: dict[str, Path]) -> None:
        """Mutant: the dirty check removed — the fetch runs and the branch fast-forwards over the edit."""
        ext = tracked_world["ext"]
        head = _git(ext, "rev-parse", "HEAD")
        _remote_commit(tracked_world, "upstream.txt")
        (ext / "README.md").write_text("edited\n", encoding="utf-8")

        with patch(f"{_RAIL}.is_verified_admin_caller", return_value=True):
            result = handle_command("sync", ["--repo", "projects/ext"])

        refusal = repo_door.REFUSE_DIRTY.format(verb="sync", repo=ext.resolve())
        expected = {"stdout": "", "stderr": refusal, "exit_code": 1}
        assert result == expected
        assert _git(ext, "rev-parse", "HEAD") == head
        assert _git(ext, "rev-parse", "origin/main") == head, "nothing was fetched"
        assert (ext / "README.md").read_text(encoding="utf-8") == "edited\n"

    def test_no_configured_upstream_compares_against_origin_by_name_and_writes_no_config(
        self, door_world: dict[str, Path]
    ) -> None:
        """Mutant: the by-name lookup removed — a branch created locally beside origin/main is refused."""
        ext = door_world["ext"]
        config = (ext / ".git" / "config").read_text(encoding="utf-8")
        remote = _remote_commit(door_world, "upstream.txt")

        with patch(f"{_RAIL}.is_verified_admin_caller", return_value=True):
            result = handle_command("fetch", ["--repo", "projects/ext"])

        assert result["stdout"] == (
            f"Fetched origin in {ext.resolve()}.\n"
            f"'main' against origin/main{repo_door.BY_NAME_NOTE}: ahead 0, behind 1.\n"
            "Behind: on origin/main, not here (newest first):\n"
            f"  {remote[:7]} remote upstream.txt"
        )
        assert (ext / ".git" / "config").read_text(encoding="utf-8") == config

    def test_sync_fast_forwards_onto_origin_by_name_when_none_is_configured(self, door_world: dict[str, Path]) -> None:
        ext = door_world["ext"]
        remote = _remote_commit(door_world, "upstream.txt")

        with patch(f"{_RAIL}.is_verified_admin_caller", return_value=True):
            result = handle_command("sync", ["--repo", "projects/ext"])

        assert result["exit_code"] == 0
        assert _git(ext, "rev-parse", "HEAD") == remote

    def test_a_branch_with_neither_an_upstream_nor_an_origin_twin_is_refused_by_name(
        self, door_world: dict[str, Path]
    ) -> None:
        """Mutant: the by-name ref unverified — git is asked to compare against a ref that does not exist."""
        ext = door_world["ext"]
        _git(ext, "checkout", "-q", "-b", "solo")

        with patch(f"{_RAIL}.is_verified_admin_caller", return_value=True):
            result = handle_command("fetch", ["--repo", "projects/ext"])

        expected = repo_door.REFUSE_NO_UPSTREAM.format(
            verb="fetch", branch="solo", repo=ext.resolve(), fetched="origin"
        )
        assert result == {"stdout": "", "stderr": expected, "exit_code": 1}

    @pytest.mark.parametrize("verb", ["fetch", "sync"])
    def test_both_refuse_without_a_repo_path_and_with_arguments(self, door_world: dict[str, Path], verb: str) -> None:
        with patch(f"{_RAIL}.is_verified_admin_caller", return_value=True):
            bare = handle_command(verb, ["--repo"])
            extra = handle_command(verb, ["origin", "--repo", "projects/ext"])

        assert bare == {"stdout": "", "stderr": repo_door.REFUSE_NO_VALUE, "exit_code": 1}
        assert extra == {"stdout": "", "stderr": repo_door.REFUSE_NO_ARGS.format(verb=verb), "exit_code": 1}

    def test_sync_on_the_aipass_repo_is_refused_as_every_door_verb_is(self, door_world: dict[str, Path]) -> None:
        target = door_world["root"]
        _git(target, "init", "-q", "-b", "main")

        with patch(f"{_RAIL}.is_verified_admin_caller", return_value=True):
            result = handle_command("sync", ["--repo", str(target)])

        assert result == {"stdout": "", "stderr": repo_door.REFUSE_AIPASS.format(path=str(target)), "exit_code": 1}

    def test_fetch_without_the_door_points_at_it(self, door_world: dict[str, Path]) -> None:
        """At home there is no fetch verb: the refusal names the door rather than dead-ending."""
        result = handle_command("fetch", [])

        assert result["exit_code"] == 1
        assert result["stderr"].startswith("Unknown git command: 'fetch'.")
        assert "'fetch --repo <path>' (admin seat only)" in result["stderr"]

    def test_help_names_fetch_and_sync_on_the_door(self) -> None:
        text = get_help()
        assert "  fetch | sync  --repo <path>\n  merge-upstream  --repo <path> [--theirs <path> ...]\n" in text
        assert repo_door.REFUSE_THEIRS_NO_PATH in text and repo_door.REFUSE_MERGE_ARGS in text
        assert (
            repo_door.REFUSE_DIVERGED.format(
                branch="<branch>", upstream="<upstream>", repo="<repo>", ahead="<n>", behind="<m>"
            )
            in text
        )
        assert repo_door.REFUSE_CONFLICT.format(branch="<branch>", upstream="<upstream>", repo="<repo>") in text


def _same_line_on_both_sides(world: dict[str, Path]) -> None:
    """Change README.md's one line on origin (from 'other') and locally, so the merge must conflict."""
    other = world["origin"].parent / "other"
    _git(other.parent, "clone", "-q", "-b", "main", str(world["origin"]), str(other))
    (other / "README.md").write_text("theirs\n", encoding="utf-8")
    _git(other, "commit", "-q", "-am", "remote readme")
    _git(other, "push", "-q", "origin", "main")
    (world["ext"] / "README.md").write_text("ours\n", encoding="utf-8")
    _git(world["ext"], "commit", "-q", "-am", "local readme")


def _conflict_in(world: dict[str, Path], *names: str) -> tuple[str, str]:
    """Seed each file, then change its one line on origin and locally: the merge conflicts on every one.

    Returns (local HEAD, origin HEAD).
    """
    ext, other = world["ext"], world["origin"].parent / "other"
    for name in names:
        (ext / name).parent.mkdir(parents=True, exist_ok=True)
        (ext / name).write_text("base\n", encoding="utf-8")
    _git(ext, "add", *names)
    _git(ext, "commit", "-q", "-m", "seed")
    _git(ext, "push", "-q", "origin", "main")
    _git(other.parent, "clone", "-q", "-b", "main", str(world["origin"]), str(other))
    for repo, side in ((other, "theirs"), (ext, "ours")):
        for name in names:
            (repo / name).write_text(f"{side}\n", encoding="utf-8")
        _git(repo, "commit", "-q", "-am", side)
    _git(other, "push", "-q", "origin", "main")
    return _git(ext, "rev-parse", "HEAD"), _git(other, "rev-parse", "HEAD")


class TestRepoDoorMergeUpstreamTheirs:
    """--theirs: listed conflicts take the upstream's side and the merge completes; anything else aborts."""

    def test_listed_conflicts_take_theirs_and_complete_one_merge_commit_of_both_parents(
        self, door_world: dict[str, Path], tmp_path: Path
    ) -> None:
        """Mutant: checkout --ours for --theirs — the merge completes and keeps the local side."""
        ext, origin = door_world["ext"], door_world["origin"]
        local, remote = _conflict_in(door_world, "app/package.json", "app/package-lock.json")
        paths = ["app/package.json", "app/package-lock.json"]

        with patch(f"{_RAIL}.is_verified_admin_caller", return_value=True):
            result = handle_command("merge-upstream", ["--repo", "projects/ext", "--theirs", *paths])

        merge = _git(ext, "rev-parse", "HEAD")
        assert result["exit_code"] == 0, result
        assert f"merge commit {merge[:7]}" in result["stdout"]
        assert "Took origin/main's side for:\n  app/package.json\n  app/package-lock.json" in result["stdout"]
        assert f"HEAD is now {merge[:7]}." in result["stdout"]
        assert _git(ext, "log", "-1", "--format=%P") == f"{local} {remote}"
        assert [(ext / p).read_text(encoding="utf-8") for p in paths] == ["theirs\n", "theirs\n"]
        assert _git(ext, "status", "--porcelain") == ""
        assert _git(origin, "rev-parse", "main") == remote, "merge-upstream never pushes"
        [record] = _ledger(tmp_path)
        assert (record["head_after"], record["theirs_taken"]) == (merge, paths)

    def test_an_unlisted_conflict_aborts_and_names_every_conflicted_path(self, door_world: dict[str, Path]) -> None:
        """Mutant: the subset check is any() — the listed path is taken and the unlisted one committed with markers."""
        ext = door_world["ext"]
        local, _ = _conflict_in(door_world, "app/package.json", "app/package-lock.json")

        with patch(f"{_RAIL}.is_verified_admin_caller", return_value=True):
            result = handle_command("merge-upstream", ["--repo", "projects/ext", "--theirs", "app/package.json"])

        refusal = repo_door.REFUSE_CONFLICT.format(branch="main", upstream="origin/main", repo=ext.resolve())
        named = "\n  app/package-lock.json (not in --theirs)\n  app/package.json"
        assert result == {"stdout": "", "stderr": refusal + named, "exit_code": 1}
        assert _git(ext, "rev-parse", "HEAD") == local
        assert _git(ext, "status", "--porcelain") == ""
        assert not (ext / ".git" / "MERGE_HEAD").exists()

    def test_a_listed_path_that_did_not_conflict_is_reported_not_needed(self, tracked_world: dict[str, Path]) -> None:
        """Mutant: the subset check is set equality — the unconflicted listed path aborts the merge."""
        ext = tracked_world["ext"]
        _same_line_on_both_sides(tracked_world)

        with patch(f"{_RAIL}.is_verified_admin_caller", return_value=True):
            result = handle_command("merge-upstream", ["--repo", "projects/ext", "--theirs", "README.md", "docs/x.md"])

        assert result["exit_code"] == 0, result
        assert "Took origin/main's side for:\n  README.md\n" in result["stdout"]
        assert "Not needed (did not conflict):\n  docs/x.md\n" in result["stdout"]
        assert (ext / "README.md").read_text(encoding="utf-8") == "theirs\n"

    def test_the_flag_without_a_path_and_a_path_outside_the_repo_are_refused_before_fetching(
        self, tracked_world: dict[str, Path]
    ) -> None:
        """Mutant: the no-path check removed — a bare --theirs merges as if it were absent."""
        ext = tracked_world["ext"]
        head = _git(ext, "rev-parse", "HEAD")
        _remote_commit(tracked_world, "upstream.txt")
        door = ["--repo", "projects/ext"]

        with patch(f"{_RAIL}.is_verified_admin_caller", return_value=True):
            bare = handle_command("merge-upstream", [*door, "--theirs"])
            slash = handle_command("merge-upstream", [*door, "--theirs", "/etc/hosts"])
            above = handle_command("merge-upstream", [*door, "--theirs", "app/../../x"])
            inside = handle_command("merge-upstream", [*door, "--theirs", str(ext / "README.md")])

        assert bare == {"stdout": "", "stderr": repo_door.REFUSE_THEIRS_NO_PATH, "exit_code": 1}
        assert slash["stderr"] == repo_door.REFUSE_THEIRS_OUTSIDE.format(path="/etc/hosts", repo=ext.resolve())
        assert above["stderr"] == repo_door.REFUSE_THEIRS_OUTSIDE.format(path="app/../../x", repo=ext.resolve())
        assert inside["stderr"] == repo_door.REFUSE_THEIRS_OUTSIDE.format(
            path=str(ext / "README.md"), repo=ext.resolve()
        )
        assert _git(ext, "rev-parse", "origin/main") == head, "nothing was fetched"


class TestRepoDoorMergeUpstream:
    """merge-upstream: one merge commit for a diverged branch, an abort for a conflict, nothing ever pushed."""

    def test_a_clean_diverged_merge_makes_one_merge_commit_with_both_sides(
        self, tracked_world: dict[str, Path], tmp_path: Path
    ) -> None:
        """Mutant: the diverged arm runs --ff-only instead of --no-edit — git refuses and nothing merges."""
        ext, origin = tracked_world["ext"], tracked_world["origin"]
        remote = _remote_commit(tracked_world, "upstream.txt")
        local = _local_commit(ext, "here.txt")

        with patch(f"{_RAIL}.is_verified_admin_caller", return_value=True):
            result = handle_command("merge-upstream", ["--repo", "projects/ext"])

        merge = _git(ext, "rev-parse", "HEAD")
        assert result == {
            "stdout": (
                f"Merged origin/main into 'main' in {ext.resolve()}: "
                f"merge commit {merge[:7]}, 1 commit(s) brought in.\n"
                "Brought in (newest first):\n"
                f"  {remote[:7]} remote upstream.txt\n"
                "Nothing was pushed: push is its own verb (drone @git push --repo <path>)."
            ),
            "stderr": "",
            "exit_code": 0,
        }
        assert _git(ext, "log", "-1", "--format=%P") == f"{local} {remote}"
        assert (ext / "upstream.txt").exists() and (ext / "here.txt").exists()
        assert _git(origin, "rev-parse", "main") == remote, "merge-upstream never pushes"
        [record] = _ledger(tmp_path)
        assert (record["verb"], record["head_before"], record["head_after"]) == ("merge-upstream", local, merge)

    def test_a_conflict_aborts_names_the_path_and_leaves_head_index_and_tree_as_they_were(
        self, tracked_world: dict[str, Path]
    ) -> None:
        """Mutant: the abort dropped — MERGE_HEAD and the conflict markers stay behind."""
        ext = tracked_world["ext"]
        _same_line_on_both_sides(tracked_world)
        head = _git(ext, "rev-parse", "HEAD")

        with patch(f"{_RAIL}.is_verified_admin_caller", return_value=True):
            result = handle_command("merge-upstream", ["--repo", "projects/ext"])

        refusal = repo_door.REFUSE_CONFLICT.format(branch="main", upstream="origin/main", repo=ext.resolve())
        assert result == {"stdout": "", "stderr": f"{refusal}\n  README.md", "exit_code": 1}
        assert _git(ext, "rev-parse", "HEAD") == head
        assert _git(ext, "status", "--porcelain") == ""
        assert not (ext / ".git" / "MERGE_HEAD").exists()
        assert (ext / "README.md").read_text(encoding="utf-8") == "ours\n"

    def test_behind_only_fast_forwards_without_a_merge_commit(self, tracked_world: dict[str, Path]) -> None:
        """Mutant: the behind-only arm removed — a merge --no-edit of a pure fast-forward reports a merge commit."""
        ext = tracked_world["ext"]
        head = _git(ext, "rev-parse", "HEAD")
        remote = _remote_commit(tracked_world, "upstream.txt")

        with patch(f"{_RAIL}.is_verified_admin_caller", return_value=True):
            result = handle_command("merge-upstream", ["--repo", "projects/ext"])

        assert result["exit_code"] == 0
        assert result["stdout"].startswith(
            f"Fast-forwarded 'main' onto origin/main in {ext.resolve()}: 1 commit(s); no merge commit was needed."
        )
        assert _git(ext, "rev-parse", "HEAD") == remote
        assert _git(ext, "log", "-1", "--format=%P") == head

    def test_nothing_behind_is_nothing_to_merge(self, tracked_world: dict[str, Path]) -> None:
        ext = tracked_world["ext"]
        local = _local_commit(ext, "here.txt")

        with patch(f"{_RAIL}.is_verified_admin_caller", return_value=True):
            result = handle_command("merge-upstream", ["--repo", "projects/ext"])

        assert result["exit_code"] == 0
        assert result["stdout"].startswith(f"Nothing to merge in {ext.resolve()}. 'main' against origin/main: ahead 1")
        assert _git(ext, "rev-parse", "HEAD") == local

    def test_a_tracked_change_is_refused_before_fetching(self, tracked_world: dict[str, Path]) -> None:
        """Mutant: the dirty check removed — the fetch runs and origin/main moves."""
        ext = tracked_world["ext"]
        head = _git(ext, "rev-parse", "HEAD")
        _remote_commit(tracked_world, "upstream.txt")
        (ext / "README.md").write_text("edited\n", encoding="utf-8")

        with patch(f"{_RAIL}.is_verified_admin_caller", return_value=True):
            result = handle_command("merge-upstream", ["--repo", "projects/ext"])

        refusal = repo_door.REFUSE_DIRTY.format(verb="merge-upstream", repo=ext.resolve())
        assert result == {"stdout": "", "stderr": refusal, "exit_code": 1}
        assert _git(ext, "rev-parse", "origin/main") == head, "nothing was fetched"

    def test_the_aipass_repo_and_extra_arguments_are_refused(self, door_world: dict[str, Path]) -> None:
        target = door_world["root"]
        _git(target, "init", "-q", "-b", "main")

        with patch(f"{_RAIL}.is_verified_admin_caller", return_value=True):
            aipass = handle_command("merge-upstream", ["--repo", str(target)])
            extra = handle_command("merge-upstream", ["origin/main", "--repo", "projects/ext"])

        assert aipass["stderr"] == repo_door.REFUSE_AIPASS.format(path=str(target))
        assert extra["stderr"] == repo_door.REFUSE_MERGE_ARGS


# ===========================================================================
# run list | view | watch --repo <path> — gh's read side through the door
# ===========================================================================

_REAL_RUN = subprocess.run


def _gh_recorder(calls: list[list[str]], stdout: str = "ok\n"):
    """A subprocess.run that records each gh argv and answers it, and runs git for real.

    Patching ``git_module.subprocess.run`` replaces the one subprocess module every
    door handler shares, so the door's own git reads must still reach git.
    """

    def run(argv: list[str], *args: Any, **kwargs: Any) -> subprocess.CompletedProcess:
        if argv[0] != "gh":
            return _REAL_RUN(argv, *args, **kwargs)
        calls.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="")

    return run


@pytest.fixture()
def github_world(door_world: dict[str, Path]) -> dict[str, Path]:
    """door_world with the external repo's origin URL pointing at github.com over ssh."""
    _git(door_world["ext"], "remote", "set-url", "origin", "git@github.com:AIOSAI/ext.git")
    return door_world


class TestRepoDoorRunReads:
    """The door hands gh --repo OWNER/NAME from the repo's origin, for reads only."""

    @pytest.mark.parametrize(
        "url",
        [
            "https://github.com/AIOSAI/baud",
            "https://github.com/AIOSAI/baud.git",
            "https://x-access-token:abc@github.com/AIOSAI/baud.git",
            "git@github.com:AIOSAI/baud.git",
            "git@github.com:AIOSAI/baud",
            "ssh://git@github.com/AIOSAI/baud.git",
        ],
    )
    def test_owner_name_comes_from_https_and_ssh_urls_with_or_without_git(self, url: str) -> None:
        assert repo_door.github_slug(url) == "AIOSAI/baud"

    @pytest.mark.parametrize(
        "url",
        ["/srv/origin.git", "https://gitlab.com/AIOSAI/baud.git", "git@github.com:AIOSAI", "https://github.com/a/b/c"],
    )
    def test_a_url_that_names_no_github_repo_gives_none(self, url: str) -> None:
        assert repo_door.github_slug(url) is None

    @pytest.mark.parametrize(
        ("args", "argv"),
        [
            (["list"], ["gh", "run", "list", "--repo", "AIOSAI/ext"]),
            (["view", "123", "--log-failed"], ["gh", "run", "view", "123", "--log-failed", "--repo", "AIOSAI/ext"]),
            (["watch", "123"], ["gh", "run", "watch", "123", "--repo", "AIOSAI/ext"]),
        ],
    )
    def test_the_door_hands_gh_the_origins_owner_name(
        self, github_world: dict[str, Path], tmp_path: Path, args: list[str], argv: list[str]
    ) -> None:
        """Mutant: the slug left off gh_run_args' return — gh is asked about the standing repo."""
        calls: list[list[str]] = []
        with (
            patch(f"{_RAIL}.is_verified_admin_caller", return_value=True),
            patch("aipass.drone.apps.modules.git_module.subprocess.run", side_effect=_gh_recorder(calls)),
        ):
            result = handle_command("run", [*args, "--repo", "projects/ext"])

        assert result == {"stdout": "ok\n", "stderr": "", "exit_code": 0}
        assert calls == [argv]
        [record] = _ledger(tmp_path)
        assert (record["outcome"], record["verb"], record["args"]) == ("ran", "run", args)

    @pytest.mark.parametrize("sub", ["rerun", "cancel", "delete", "download"])
    def test_the_write_subcommands_are_refused_and_gh_is_never_called(
        self, github_world: dict[str, Path], sub: str
    ) -> None:
        """Mutant: rerun added to RUN_READS — gh is called to rerun another repo's run."""
        calls: list[list[str]] = []
        with (
            patch(f"{_RAIL}.is_verified_admin_caller", return_value=True),
            patch("aipass.drone.apps.modules.git_module.subprocess.run", side_effect=_gh_recorder(calls)),
        ):
            result = handle_command("run", [sub, "123", "--repo", "projects/ext"])

        assert result == {"stdout": "", "stderr": repo_door.REFUSE_RUN_SUB.format(sub=sub), "exit_code": 1}
        assert calls == []

    def test_the_aipass_repo_is_refused_and_gh_is_never_called(self, door_world: dict[str, Path]) -> None:
        target = door_world["root"]
        _git(target, "init", "-q", "-b", "main")
        calls: list[list[str]] = []
        with (
            patch(f"{_RAIL}.is_verified_admin_caller", return_value=True),
            patch("aipass.drone.apps.modules.git_module.subprocess.run", side_effect=_gh_recorder(calls)),
        ):
            result = handle_command("run", ["list", "--repo", str(target)])

        assert result == {"stdout": "", "stderr": repo_door.REFUSE_AIPASS.format(path=str(target)), "exit_code": 1}
        assert calls == []

    def test_an_origin_that_is_not_github_and_a_second_repo_flag_are_refused(self, door_world: dict[str, Path]) -> None:
        """door_world's origin is a local bare repo: there is no OWNER/NAME to hand gh."""
        calls: list[list[str]] = []
        with (
            patch(f"{_RAIL}.is_verified_admin_caller", return_value=True),
            patch("aipass.drone.apps.modules.git_module.subprocess.run", side_effect=_gh_recorder(calls)),
        ):
            local = handle_command("run", ["list", "--repo", "projects/ext"])
            short = handle_command("run", ["list", "-R", "AIOSAI/other", "--repo", "projects/ext"])

        assert local["stderr"] == repo_door.REFUSE_NO_GITHUB.format(repo=door_world["ext"].resolve())
        assert short["stderr"] == repo_door.REFUSE_RUN_SHORT_FLAG
        assert calls == []

    def test_an_owner_name_that_is_not_a_directory_still_reaches_gh_untouched(
        self, door_world: dict[str, Path], tmp_path: Path
    ) -> None:
        """Mutant: run_aims_at_door answers True — gh's own --repo is swallowed by the door."""
        calls: list[list[str]] = []
        with (
            patch("aipass.drone.apps.plugins.devpulse_ops.auth.verify_git_access", return_value="devpulse"),
            patch("aipass.drone.apps.modules.git_module.subprocess.run", side_effect=_gh_recorder(calls)),
        ):
            result = handle_command("run", ["list", "--repo", "AIOSAI/ext"])

        assert result["exit_code"] == 0
        assert calls == [["gh", "run", "list", "--repo", "AIOSAI/ext"]]
        assert _ledger(tmp_path) == []

    def test_help_names_the_run_reads_and_their_refusals(self) -> None:
        text = get_help()
        assert "  gh run list | view <id> [--log | --log-failed] | watch <id>  --repo <path>\n" in text
        assert "  list | view | watch --repo <path> reads another repo's runs (admin seat)\n" in get_help("run")
        assert repo_door.REFUSE_RUN_SUB.format(sub="<sub>") in text
        assert repo_door.REFUSE_NO_GITHUB.format(repo="<repo>") in text

    @pytest.mark.parametrize(
        "short", [["-R", "AIOSAI/other"], ["-R=AIOSAI/other"], ["-RAIOSAI/other"]], ids=["spaced", "equals", "attached"]
    )
    def test_every_form_of_gh_short_repo_flag_beside_the_door_is_refused(
        self, github_world: dict[str, Path], short: list[str]
    ) -> None:
        """Red first: the attached -RAIOSAI/other passed and named a second repo beside --repo <path>."""
        calls: list[list[str]] = []
        with (
            patch(f"{_RAIL}.is_verified_admin_caller", return_value=True),
            patch("aipass.drone.apps.modules.git_module.subprocess.run", side_effect=_gh_recorder(calls)),
        ):
            result = handle_command("run", ["list", *short, "--repo", "projects/ext"])

        assert result == {"stdout": "", "stderr": repo_door.REFUSE_RUN_SHORT_FLAG, "exit_code": 1}
        assert calls == []


# ===========================================================================
# The door's git runner: a time budget per verb, and no terminal prompt
# ===========================================================================

# The two reads the door makes outside its runner: the ledger's HEAD and the repo's top level.
_OUTSIDE_THE_RUNNER = (["git", "rev-parse", "--verify", "-q", "HEAD"], ["git", "rev-parse", "--show-toplevel"])


def _git_recorder(calls: list[tuple[list[str], dict]], hang: str | None = None):
    """A subprocess.run that records every git call's argv and keywords and runs it, or times out on *hang*."""

    def run(argv: list[str], *args: Any, **kwargs: Any) -> subprocess.CompletedProcess:
        if argv not in _OUTSIDE_THE_RUNNER:
            calls.append((list(argv), kwargs))
        if hang is not None and argv[:2] == ["git", hang]:
            raise subprocess.TimeoutExpired(argv, kwargs.get("timeout") or 0)
        return _REAL_RUN(argv, *args, **kwargs)

    return run


class TestRepoDoorGitRunner:
    """Every git call the runner makes carries a timeout and GIT_TERMINAL_PROMPT=0; a timeout names verb and seconds."""

    def test_fetch_gets_the_network_budget_and_the_local_reads_the_local_one_never_prompting(
        self, tracked_world: dict[str, Path]
    ) -> None:
        """Mutants: timeout dropped; env not passed; fetch given the local number."""
        calls: list[tuple[list[str], dict]] = []
        with (
            patch(f"{_RAIL}.is_verified_admin_caller", return_value=True),
            patch("aipass.drone.apps.handlers.git.repo_door.subprocess.run", side_effect=_git_recorder(calls)),
        ):
            result = handle_command("fetch", ["--repo", "projects/ext"])

        assert result["exit_code"] == 0
        assert [(argv[1], kwargs.get("timeout")) for argv, kwargs in calls] == [
            ("symbolic-ref", 60),
            ("fetch", 120),
            ("rev-parse", 60),
            ("log", 60),
            ("log", 60),
        ]
        for _argv, kwargs in calls:
            assert kwargs["env"]["GIT_TERMINAL_PROMPT"] == "0"
            assert kwargs["env"]["GIT_CONFIG_GLOBAL"] == os.environ["GIT_CONFIG_GLOBAL"], "a copy of os.environ"

    def test_merge_gets_the_network_budget(self, tracked_world: dict[str, Path]) -> None:
        _remote_commit(tracked_world, "r1.txt")
        calls: list[tuple[list[str], dict]] = []
        with (
            patch(f"{_RAIL}.is_verified_admin_caller", return_value=True),
            patch("aipass.drone.apps.handlers.git.repo_door.subprocess.run", side_effect=_git_recorder(calls)),
        ):
            result = handle_command("merge-upstream", ["--repo", "projects/ext"])

        assert result["exit_code"] == 0
        [merge] = [kwargs for argv, kwargs in calls if argv[1] == "merge"]
        assert merge["timeout"] == 120

    @pytest.mark.parametrize("verb", ["fetch", "sync", "merge-upstream"])
    def test_a_fetch_that_hangs_fails_naming_the_verb_and_the_seconds(
        self, tracked_world: dict[str, Path], verb: str
    ) -> None:
        """Red first: the TimeoutExpired was never raised, and with no timeout a dead remote hung drone."""
        ext = tracked_world["ext"].resolve()
        with (
            patch(f"{_RAIL}.is_verified_admin_caller", return_value=True),
            patch("aipass.drone.apps.handlers.git.repo_door.subprocess.run", side_effect=_git_recorder([], "fetch")),
        ):
            result = handle_command(verb, ["--repo", "projects/ext"])

        assert result == {
            "stdout": "",
            "stderr": f"{verb} failed in {ext}: git fetch timed out after 120 s in {ext}",
            "exit_code": 1,
        }


# ===========================================================================
# tracked | untrack --repo <path>: a staged file out of another repo's index
# ===========================================================================


@pytest.fixture()
def restaged_world(door_world: dict[str, Path]) -> dict[str, Path]:
    """door_world where a catch-all commit swept in an ignored file and a soft reset left it staged."""
    ext = door_world["ext"]
    (ext / ".gitignore").write_text("*.jsonl\n", encoding="utf-8")
    _git(ext, "add", ".gitignore")
    _git(ext, "commit", "-q", "-m", "ignore ledgers")
    (ext / "ledger.jsonl").write_text("{}\n", encoding="utf-8")
    _git(ext, "add", "-f", "ledger.jsonl")
    _git(ext, "commit", "-q", "-m", "catch-all")
    _git(ext, "reset", "-q", "--soft", "HEAD~1")
    return door_world


class TestRepoDoorTrackedAndUntrack:
    """Through the door, tracked and untrack run their home handlers rooted at the named repo."""

    def test_a_soft_reset_restaged_ignored_file_leaves_the_index_and_stays_on_disk(
        self, restaged_world: dict[str, Path], tmp_path: Path
    ) -> None:
        """Red first: untrack was refused with REFUSE_VERB, so the staged file had no drone way out."""
        ext = restaged_world["ext"]
        head = _git(ext, "rev-parse", "HEAD")

        with patch(f"{_RAIL}.is_verified_admin_caller", return_value=True):
            before = handle_command("tracked", ["ledger.jsonl", "--repo", "projects/ext"])
            result = handle_command("untrack", ["ledger.jsonl", "--repo", "projects/ext"])
            after = handle_command("tracked", ["ledger.jsonl", "--repo", "projects/ext"])

        assert before == {"stdout": "tracked    ledger.jsonl", "stderr": "", "exit_code": 0}
        assert result == {
            "stdout": "left the index  ledger.jsonl\n" + untrack_handler.NEXT_STEP.format(count=1),
            "stderr": "",
            "exit_code": 0,
        }
        assert after["stdout"] == "ignored    ledger.jsonl"
        assert _git(ext, "diff", "--cached", "--name-only") == ""
        assert (ext / "ledger.jsonl").read_text(encoding="utf-8") == "{}\n"
        assert _git(ext, "rev-parse", "HEAD") == head, "untrack never commits"
        assert [(r["verb"], r["outcome"], r["exit_code"]) for r in _ledger(tmp_path)] == [
            ("tracked", "ran", 0),
            ("untrack", "ran", 0),
            ("tracked", "ran", 0),
        ]

    def test_a_path_is_read_against_the_named_repo_not_the_callers_directory(
        self, restaged_world: dict[str, Path]
    ) -> None:
        """Mutant: the door hands the caller's cwd on, and ledger.jsonl is looked for in the devpulse seat."""
        (restaged_world["seat"] / "ledger.jsonl").write_text("seat's own\n", encoding="utf-8")

        with patch(f"{_RAIL}.is_verified_admin_caller", return_value=True):
            result = handle_command("untrack", ["ledger.jsonl", "--repo", "projects/ext"])

        assert result["exit_code"] == 0
        assert result["stdout"].splitlines()[0] == "left the index  ledger.jsonl"

    def test_untrack_without_the_admin_grant_is_refused_and_the_index_is_untouched(
        self, restaged_world: dict[str, Path]
    ) -> None:
        ext = restaged_world["ext"]

        with patch(f"{_RAIL}.is_verified_admin_caller", return_value=False):
            result = handle_command("untrack", ["ledger.jsonl", "--repo", "projects/ext"])

        assert result["exit_code"] == 1
        assert "admin" in result["stderr"]
        assert _git(ext, "diff", "--cached", "--name-only") == "ledger.jsonl"

    def test_help_names_both_verbs_on_the_door(self) -> None:
        assert "  tracked <path ...> | untrack [--recursive] <path ...>  --repo <path>" in get_help()
        assert "tracked" in repo_door.DOOR_VERBS and "untrack" in repo_door.DOOR_VERBS


# ===========================================================================
# release edit and the chores through the door: the owner tier's GitHub chores
# ===========================================================================

_SLUG = GITHUB_SLUG
_CHANGELOG = (
    "# Changelog\n\n"
    "## [Unreleased]\n\n- **next** not shipped\n\n---\n\n"
    "## [2026-10-17] — v2.8.20: the comments say why\n\n- **fix** one\n---\n- **fix** two\n\n"
    "## [2026-09-01] — v2.8.2: the old one\n\n- **old** entry\n"
)
_V2820 = "## [2026-10-17] — v2.8.20: the comments say why\n\n- **fix** one\n- **fix** two\n\n"


def _chore(command: str, args: list[str], answers: dict[str, object], calls: list) -> dict:
    with patch("aipass.drone.apps.modules.git_module.subprocess.run", side_effect=github_stand_in(answers, calls)):
        return handle_command(command, args)


@pytest.fixture()
def released_root(aipass_github: Path) -> Path:
    """aipass_github with a CHANGELOG.md whose blocks sit under [Unreleased], v2.8.20 and v2.8.2."""
    (aipass_github / "CHANGELOG.md").write_text(_CHANGELOG, encoding="utf-8")
    return aipass_github


class TestReleaseEdit:
    """release edit: the tag's own CHANGELOG block becomes the release's notes, by publish.yml's rule."""

    def test_the_owner_rewrites_the_notes_with_the_tags_block_and_prints_both_lengths(
        self, released_root: Path, tmp_path: Path
    ) -> None:
        """Mutant: every header keeps the block — [Unreleased] and v2.8.2 ship as v2.8.20's notes."""
        calls: list = []
        answers = {
            f"api repos/{_SLUG}/releases/tags/v2.8.20": {"tag_name": "v2.8.20", "body": "## [Unreleased]"},
            f"release edit v2.8.20 --repo {_SLUG} --notes-file -": "",
        }

        result = _chore("release", ["edit", "v2.8.20"], answers, calls)

        assert result == {
            "stdout": f"Release v2.8.20 of github.com/{_SLUG}: notes rewritten from CHANGELOG.md, 15 -> {len(_V2820)} characters.",
            "stderr": "",
            "exit_code": 0,
        }
        assert calls[-1] == ([*"release edit v2.8.20 --repo".split(), _SLUG, "--notes-file", "-"], _V2820)
        [record] = chore_ledger(tmp_path)
        assert (record["verb"], record["caller"], record["tag"], record["old_length"], record["new_length"]) == (
            "release edit",
            "devpulse",
            "v2.8.20",
            15,
            len(_V2820),
        )

    def test_v2_8_2_never_claims_v2_8_20s_block(self, released_root: Path) -> None:
        """Mutant: the trailing boundary dropped from the header match — v2.8.2 takes v2.8.20's block too."""
        calls: list = []
        answers = {
            f"api repos/{_SLUG}/releases/tags/v2.8.2": {"tag_name": "v2.8.2", "body": ""},
            f"release edit v2.8.2 --repo {_SLUG} --notes-file -": "",
        }

        _chore("release", ["edit", "v2.8.2"], answers, calls)

        assert calls[-1][1] == "## [2026-09-01] — v2.8.2: the old one\n\n- **old** entry\n"

    def test_a_block_over_the_cap_is_cut_on_an_entry_and_points_at_the_full_block(self, released_root: Path) -> None:
        """Mutant: the cut is taken at the cap itself — the last entry is sliced mid-line."""
        entry = "- **entry** " + "x" * 988 + "\n"
        big = "## [2026-10-19] — v9.9.9: big\n\n" + entry * 130
        (released_root / "CHANGELOG.md").write_text(big, encoding="utf-8")
        calls: list = []
        answers = {
            f"api repos/{_SLUG}/releases/tags/v9.9.9": {"tag_name": "v9.9.9", "body": ""},
            f"release edit v9.9.9 --repo {_SLUG} --notes-file -": "",
        }

        _chore("release", ["edit", "v9.9.9"], answers, calls)

        notes = calls[-1][1]
        body, pointer = notes.split("\n\n---\n\n")
        assert len(notes) <= release_handler.NOTES_CAP
        assert body.endswith("x" * 988) and len(body.splitlines()) - 2 == body.count("- **entry**")
        assert pointer == (
            f"*Release notes truncated: the full block is {len(big):,} characters and GitHub caps a release "
            "body at 125,000. The complete entry is `## [2026-10-19] — v9.9.9: big…` in "
            f"[CHANGELOG.md](https://github.com/{_SLUG}/blob/v9.9.9/CHANGELOG.md).*\n"
        )

    def test_a_tag_no_header_carries_and_a_tag_with_no_published_release_are_refused_and_nothing_is_edited(
        self, released_root: Path, tmp_path: Path
    ) -> None:
        """Mutant: the release check skipped — gh release edit is sent for a tag GitHub never published."""
        calls: list = []

        no_block = _chore("release", ["edit", "v7.0.0"], {}, calls)
        unpublished = _chore("release", ["edit", "v2.8.20"], {}, calls)

        assert no_block["stderr"] == release_handler.REFUSE_NO_SECTION.format(tag="v7.0.0")
        assert unpublished["stderr"] == release_handler.REFUSE_NOT_PUBLISHED.format(tag="v2.8.20", slug=_SLUG)
        assert [argv[0] for argv, _ in calls] == ["api"]
        assert chore_ledger(tmp_path) == []

    def test_a_seat_that_does_not_own_the_repo_is_refused_before_gh(self, builder_seat: Path) -> None:
        """Mutant: edit left out of the write list — the global tier lets a builder rewrite a release."""
        calls: list = []

        result = _chore("release", ["edit", "v2.8.20"], {}, calls)

        assert result["exit_code"] == 1 and "seedgo" in result["stderr"]
        assert calls == []


class TestChoresThroughTheDoor:
    """--repo <path> runs a chore on the external repo's own GitHub, for the admin seat only."""

    def test_the_admin_creates_a_label_on_the_external_repos_github_and_both_ledgers_say_so(
        self, github_world: dict[str, Path], tmp_path: Path
    ) -> None:
        """Mutant: the door hands the chore the AIPass root — the label lands on AIPass's GitHub."""
        calls: list = []
        answers = {
            "label list --repo AIOSAI/ext --limit 1000 --json name,color,description": [],
            "label create ci --repo AIOSAI/ext": "",
        }

        with patch(f"{_RAIL}.is_verified_admin_caller", return_value=True):
            result = _chore("label", ["create", "ci", "--repo", "projects/ext"], answers, calls)

        assert result == {"stdout": "Created label 'ci' on github.com/AIOSAI/ext.", "stderr": "", "exit_code": 0}
        [door] = _ledger(tmp_path)
        [chore] = chore_ledger(tmp_path)
        assert (door["verb"], door["outcome"], chore["github"], chore["caller"]) == (
            "label",
            "ran",
            "AIOSAI/ext",
            "@devpulse",
        )

    def test_release_edit_takes_the_external_repos_own_changelog(self, github_world: dict[str, Path]) -> None:
        ext = github_world["ext"]
        (ext / "CHANGELOG.md").write_text("## [1.0.0] — v1.0.0: ext\n\n- **ext** only\n", encoding="utf-8")
        calls: list = []
        answers = {
            "api repos/AIOSAI/ext/releases/tags/v1.0.0": {"tag_name": "v1.0.0", "body": ""},
            "release edit v1.0.0 --repo AIOSAI/ext --notes-file -": "",
        }

        with patch(f"{_RAIL}.is_verified_admin_caller", return_value=True):
            result = _chore("release", ["edit", "v1.0.0", "--repo", "projects/ext"], answers, calls)

        assert result["exit_code"] == 0, result
        assert calls[-1][1] == "## [1.0.0] — v1.0.0: ext\n\n- **ext** only\n"

    def test_a_chore_without_the_admin_grant_is_refused_and_gh_is_never_called(
        self, github_world: dict[str, Path]
    ) -> None:
        calls: list = []

        with patch(f"{_RAIL}.is_verified_admin_caller", return_value=False):
            result = _chore(
                "alerts",
                ["dismiss", "1", "--reason", "wont_fix", "--comment", "x", "--repo", "projects/ext"],
                {},
                calls,
            )

        assert result["exit_code"] == 1 and "admin" in result["stderr"]
        assert calls == []

    def test_release_list_keeps_repo_as_githubs_owner_name(self, aipass_github: Path) -> None:
        """Mutant: every release --repo sent to the door — release list --repo AIOSAI/AIPass is refused as a path."""
        calls: list = []
        answers = {
            "api repos/AIOSAI/AIPass": {"private": False},
            "api repos/AIOSAI/AIPass/releases?per_page=100&page=1": [],
        }

        result = _chore("release", ["list", "--repo", "AIOSAI/AIPass"], answers, calls)

        assert result == {"stdout": "No published releases of github.com/AIOSAI/AIPass.", "stderr": "", "exit_code": 0}
