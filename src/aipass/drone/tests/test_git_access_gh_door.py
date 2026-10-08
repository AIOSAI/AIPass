# =================== AIPass ====================
# Name: test_git_access_gh_door.py
# Description: Tests for the gh passthrough verbs and the external-repo door (--repo)
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-08
# =============================================

"""Tests for apps/handlers/git/repo_door.py and the gh passthrough verbs of apps/modules/git_module.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(stdlib) — subprocess.run; gh is stubbed, git runs only in the tmp_path repos of the door tests

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from aipass.drone.apps.plugins.devpulse_ops.auth import (
    GIT_ACCESS_TIERS,
    verify_git_access,
)
from aipass.drone.apps.handlers.git import repo_door
from aipass.drone.apps.modules.git_module import get_help, get_introspective, handle_command

from .conftest import make_owner_project


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
