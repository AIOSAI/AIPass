# =================== AIPass ====================
# Name: test_git_module.py
# Description: Tests for the @git module — routing, help, auth, scope footer, merge gate, gh verbs, untrack and release
# Version: 1.4.0
# Created: 2026-04-21
# Modified: 2026-10-15
# =============================================

"""Tests for apps/modules/git_module.py: command routing, help, the auth gate and the verbs it fronts."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(stdlib) — subprocess.run: a recorded stub (gh too), but untrack's git runs in a tmp_path repo

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from aipass.drone.apps.handlers.git.status_handler import get_branch_status
from aipass.drone.apps.handlers import module_registry_handler
from aipass.drone.apps.handlers.git import release_handler, untrack_handler
from aipass.drone.apps.plugins.devpulse_ops.auth import GIT_ACCESS_TIERS
from aipass.drone.apps.plugins.devpulse_ops.merge_plugin import merge_pr
from aipass.drone.apps.handlers.git.pr_handler import create_pr
from aipass.drone.apps.modules.git_module import (
    DRONE_MODULE,
    get_help,
    get_introspective,
    handle_command,
)
from aipass.drone.tests.support_git_module import _done
from aipass.trigger.apps.modules import core as trigger_core

from .conftest import make_owner_project


# ===========================================================================
# 5. git_module — command routing, unknown commands, help/introspection
# ===========================================================================


class TestGitModuleMetadata:
    """Module metadata tests."""

    def test_drone_module_dict(self) -> None:
        """DRONE_MODULE has required keys."""
        assert DRONE_MODULE["name"] == "git"
        assert "version" in DRONE_MODULE
        assert "description" in DRONE_MODULE


class TestGitModuleRouting:
    """Command routing via handle_command."""

    def test_unknown_command(self) -> None:
        """Unknown command returns error with available commands."""
        result = handle_command("bogus")
        assert result["exit_code"] == 1
        assert "unknown" in result["stderr"].lower()

    @patch(
        "aipass.drone.apps.plugins.devpulse_ops.auth.verify_git_access",
        return_value="test_branch",
    )
    def test_lock_routes_to_handler(
        self, _mock_auth: MagicMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """lock command routes to check_lock_status."""
        registry = tmp_path / "AIPASS_REGISTRY.json"
        registry.write_text("{}", encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        result = handle_command("lock")
        assert result["exit_code"] == 0
        data = json.loads(result["stdout"])
        assert data["locked"] is False

    @patch("aipass.drone.apps.plugins.devpulse_ops.auth.verify_git_access", return_value="devpulse")
    def test_unlock_requires_force(self, _mock_auth: MagicMock) -> None:
        """unlock without --force returns error."""
        result = handle_command("unlock")
        assert result["exit_code"] == 1
        assert "--force" in result["stderr"]

    @patch("aipass.drone.apps.plugins.devpulse_ops.auth.verify_git_access", return_value="devpulse")
    def test_unlock_with_force(self, _mock_auth: MagicMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """unlock --force routes to force_unlock."""
        registry = tmp_path / "AIPASS_REGISTRY.json"
        registry.write_text("{}", encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        result = handle_command("unlock", ["--force"])
        assert result["exit_code"] == 0

    @patch("aipass.drone.apps.plugins.devpulse_ops.auth.verify_git_access", return_value="devpulse")
    def test_sync_routes_to_handler(
        self, _mock_auth: MagicMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """sync command routes to sync_main."""
        registry = tmp_path / "AIPASS_REGISTRY.json"
        registry.write_text("{}", encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        mock_head = MagicMock(returncode=0, stdout="main", stderr="")
        mock_fetch = MagicMock(returncode=0, stdout="", stderr="")
        mock_rev_list = MagicMock(returncode=0, stdout="0\t0\n", stderr="")
        mock_pull = MagicMock(returncode=0, stdout="Already up to date.", stderr="")

        with patch(
            "aipass.drone.apps.handlers.git.sync_handler.subprocess.run",
            side_effect=[mock_head, mock_fetch, mock_rev_list, mock_pull],
        ):
            result = handle_command("sync")

        assert result["exit_code"] == 0

    @patch("aipass.drone.apps.plugins.devpulse_ops.auth.verify_git_access", return_value="devpulse")
    def test_sync_main_ref_routes(self, _mock_auth: MagicMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """sync --main-ref routes to sync_main_ref."""
        registry = tmp_path / "AIPASS_REGISTRY.json"
        registry.write_text("{}", encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        mock_result = MagicMock(returncode=0, stdout="", stderr="")
        with patch(
            "aipass.drone.apps.handlers.git.sync_handler.subprocess.run",
            return_value=mock_result,
        ):
            result = handle_command("sync", ["--main-ref"])

        assert result["exit_code"] == 0

    @patch("aipass.drone.apps.plugins.devpulse_ops.auth.verify_git_access", return_value="test_branch")
    def test_status_no_branch_dir(self, _mock_auth: MagicMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """status outside a branch directory returns error."""
        monkeypatch.chdir(tmp_path)
        result = handle_command("status")
        assert result["exit_code"] == 1
        assert "cannot detect" in result["stderr"].lower()

    def test_pr_no_args(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """pr command without args fails (auth or usage)."""
        monkeypatch.chdir(tmp_path)
        result = handle_command("pr")
        assert result["exit_code"] == 1

    def test_pr_no_branch_dir(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """pr command without passport returns auth error."""
        monkeypatch.chdir(tmp_path)
        result = handle_command("pr", ["some description"])
        assert result["exit_code"] == 1


class TestGitModuleRealAuth:
    """End-to-end routing with the REAL gate — nothing patched.

    Every other test in this file stubs verify_git_access, so a gate that
    authorized nobody at all would still show a green suite. These commands are
    chosen to stop at a harmless error AFTER the auth check, so they exercise the
    real path without touching a repo (DPLAN-0281, dispatch 05b22424).
    """

    def test_owner_reaches_the_handler(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """A genuine manager at home clears auth and lands in the handler.

        The '--force' complaint is the proof: that error is raised past the gate.
        """
        make_owner_project(tmp_path)
        monkeypatch.chdir(tmp_path)
        result = handle_command("unlock")
        assert result["exit_code"] == 1
        assert "--force" in result["stderr"]
        assert "not authorized" not in result["stderr"].lower()

    def test_non_manager_stopped_at_the_gate(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """The same command, one fact broken — refused before the handler runs."""
        make_owner_project(tmp_path, citizen_class="builder")
        monkeypatch.chdir(tmp_path)
        result = handle_command("unlock")
        assert result["exit_code"] == 1
        assert "not authorized" in result["stderr"].lower()
        assert "--force" not in result["stderr"]

    def test_global_tier_needs_no_ownership(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Read-only routing still works for a citizen who owns nothing."""
        make_owner_project(tmp_path, branch="seedgo", citizen_class="builder", owner=False)
        monkeypatch.chdir(tmp_path)
        result = handle_command("lock")
        assert result["exit_code"] == 0
        assert json.loads(result["stdout"])["locked"] is False


def _status_branch(expected_dir: Path | None) -> str:
    """The branch `drone @git status --json` answers for from the CWD; status itself is a recorder."""
    answer = {"ok": True, "files": [], "total": 0, "message": "clean"}
    with (
        patch(_AUTH, return_value="drone"),
        patch(f"{_GIT_MOD}.status_handler.get_branch_status", return_value=answer) as mock_status,
    ):
        result = handle_command("status", ["--json"])
    if expected_dir is not None:
        mock_status.assert_called_once_with(expected_dir)
    return json.loads(result["stdout"])["branch"]


class TestDetectBranchDir:
    """Branch directory detection, read through `status --json`."""

    def test_detects_branch_from_passport(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Mutant: the walk stops at CWD (range(1)) — a subdirectory finds no passport."""
        branch_dir = tmp_path / "mybranch"
        (branch_dir / ".trinity").mkdir(parents=True)
        (branch_dir / ".trinity" / "passport.json").write_text(
            json.dumps({"branch_info": {"branch_name": "mybranch"}}), encoding="utf-8"
        )
        sub_dir = branch_dir / "apps" / "modules"
        sub_dir.mkdir(parents=True)
        monkeypatch.chdir(sub_dir)

        assert _status_branch(branch_dir.resolve()) == "mybranch"

    def test_returns_none_for_unrecognized_path(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Mutant: a missing passport answers (cwd.name, cwd) — status runs for a branch that is not there."""
        monkeypatch.chdir(tmp_path)
        with (
            patch(_AUTH, return_value="drone"),
            patch(f"{_GIT_MOD}.status_handler.get_branch_status") as mock_status,
        ):
            result = handle_command("status", ["--json"])

        document = json.loads(result["stdout"])
        mock_status.assert_not_called()
        assert result["exit_code"] == 1
        assert document["branch"] == ""
        assert document["message"].startswith("Cannot detect branch directory from CWD")

    def test_unreadable_passport_is_named_not_read_as_no_branch(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Mutant: the passport except returns None — a corrupt passport reads as "not in a branch"."""
        branch_dir = tmp_path / "src" / "mybranch"
        (branch_dir / ".trinity").mkdir(parents=True)
        (branch_dir / ".trinity" / "passport.json").write_text("{not json", encoding="utf-8")
        monkeypatch.chdir(branch_dir)
        with (
            patch(_AUTH, return_value="drone"),
            patch(f"{_GIT_MOD}.status_handler.get_branch_status") as mock_status,
        ):
            result = handle_command("status", ["--json"])

        document = json.loads(result["stdout"])
        mock_status.assert_not_called()
        assert result["exit_code"] == 1
        assert document["message"].startswith("Unreadable passport")
        assert "passport.json" in document["message"]

    def test_detects_non_aipass_branch(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Branches outside src/aipass/ (e.g. commons, skills) are detected too.

        Mutant: only the passport's identity.name is read — a branch_info-only passport is missed.
        """
        branch_dir = tmp_path / "src" / "commons"
        (branch_dir / ".trinity").mkdir(parents=True)
        (branch_dir / ".trinity" / "passport.json").write_text(
            json.dumps({"branch_info": {"branch_name": "commons"}}), encoding="utf-8"
        )
        monkeypatch.chdir(branch_dir)

        assert _status_branch(branch_dir.resolve()) == "commons"


class TestGitModuleHelp:
    """Help and introspection tests."""

    def test_general_help(self) -> None:
        """General help includes all commands."""
        text = get_help()
        assert "pr" in text
        assert "status" in text
        assert "sync" in text
        assert "lock" in text
        assert "unlock" in text

    def test_specific_command_help(self) -> None:
        """Command-specific help returns relevant text."""
        text = get_help("commit")
        assert "commit" in text.lower()

    def test_introspective(self) -> None:
        """Introspection lists connected handlers."""
        text = get_introspective()
        assert "lock_handler" in text
        assert "status_handler" in text
        assert "sync_handler" in text
        assert "pr_handler" in text


# ===========================================================================
# 6. Module registration
# ===========================================================================


class TestModuleRegistration:
    """Verify git is registered in the module registry."""

    def test_git_in_registry(self) -> None:
        """Mutant: "git" dropped from _INTERNAL_MODULES — the registry has no info for it."""
        info = module_registry_handler.get_module_info("git")

        assert info is not None
        assert info.adapter_path == "aipass.drone.apps.modules.git_module"
        assert info.version == DRONE_MODULE["version"]

    def test_module_importable(self) -> None:
        """Mutant: "git" registered at another module's path — the registry serves that module's help."""
        assert module_registry_handler.get_module_help("git") == get_help(None)
        assert module_registry_handler.get_module_introspective("git") == get_introspective()


# ===========================================================================
# 7. trigger.fire() integration tests
# ===========================================================================


def _run_pr_created_success(cmd: list[str], **kwargs: object) -> MagicMock:
    """Subprocess mock for a full successful pr_handler run (fires pr_created)."""
    r = MagicMock()
    r.returncode = 0
    r.stderr = ""
    r.stdout = ""
    if cmd[1:3] == ["rev-parse", "--abbrev-ref"]:
        r.stdout = "main\n"
    elif cmd[1:3] == ["diff", "--cached"]:
        r.returncode = 1
    elif cmd[0] == "gh" and cmd[1] == "pr":
        r.stdout = "https://github.com/org/repo/pull/99\n"
    return r


def _run_pr_trigger_resilience(cmd: list[str], **kwargs: object) -> MagicMock:
    """Subprocess mock for pr_handler run where trigger.fire raises."""
    r = MagicMock()
    r.returncode = 0
    r.stderr = ""
    r.stdout = ""
    if cmd[1:3] == ["rev-parse", "--abbrev-ref"]:
        r.stdout = "main\n"
    elif cmd[1:3] == ["diff", "--cached"]:
        r.returncode = 1
    elif cmd[0] == "gh" and cmd[1] == "pr":
        r.stdout = "https://github.com/org/repo/pull/100\n"
    return r


def _run_merge_success(cmd: list[str], **kwargs: object) -> MagicMock:
    """Subprocess mock for a successful merge_plugin run (fires pr_merged)."""
    r = MagicMock()
    r.returncode = 0
    r.stderr = ""
    r.stdout = ""
    if cmd[0] == "gh" and cmd[1] == "pr" and cmd[2] == "view":
        if "--jq" in cmd and ".headRefName" in cmd:
            r.stdout = "citizen/test-branch\n"
        else:
            r.stdout = "Fix the thing\n"
    elif cmd[1:3] == ["rev-parse", "HEAD"]:
        r.stdout = "abc123def456\n"
    elif cmd[1:3] == ["rev-parse", "--abbrev-ref"]:
        r.stdout = "dev\n"
    return r


class TestTriggerFireIntegration:
    """Verify trigger.fire() is called after successful PR/merge operations."""

    def test_pr_handler_fires_pr_created(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """pr_handler.create_pr fires pr_created event on success."""
        registry = tmp_path / "AIPASS_REGISTRY.json"
        registry.write_text("{}", encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        mock_trigger = MagicMock()
        monkeypatch.setattr(trigger_core, "trigger", mock_trigger)

        with patch("aipass.drone.apps.handlers.git.pr_handler.subprocess.run", side_effect=_run_pr_created_success):
            with patch(
                "aipass.drone.apps.handlers.git.pr_handler.acquire_lock",
                return_value={"success": True, "message": "ok"},
            ):
                with patch("aipass.drone.apps.handlers.git.pr_handler.release_lock") as mock_release:
                    result = create_pr("api", "test trigger", tmp_path / "src" / "aipass" / "api")

        assert result["success"] is True
        mock_release.assert_called_once_with(force=True)
        mock_trigger.fire.assert_any_call("pr_created", branch="api", pr_url="https://github.com/org/repo/pull/99")

    def test_pr_handler_continues_if_trigger_fails(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """pr_handler.create_pr succeeds even if trigger.fire raises."""
        registry = tmp_path / "AIPASS_REGISTRY.json"
        registry.write_text("{}", encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        mock_trigger = MagicMock()
        mock_trigger.fire.side_effect = RuntimeError("trigger broken")
        monkeypatch.setattr(trigger_core, "trigger", mock_trigger)

        with patch("aipass.drone.apps.handlers.git.pr_handler.subprocess.run", side_effect=_run_pr_trigger_resilience):
            with patch(
                "aipass.drone.apps.handlers.git.pr_handler.acquire_lock",
                return_value={"success": True, "message": "ok"},
            ):
                with patch("aipass.drone.apps.handlers.git.pr_handler.release_lock") as mock_release:
                    result = create_pr("api", "test resilience", tmp_path / "src" / "aipass" / "api")

        assert result["success"] is True  # PR still succeeds despite trigger failure
        mock_release.assert_called_once_with(force=True)
        mock_trigger.fire.assert_called_once_with(
            "pr_created", branch="api", pr_url="https://github.com/org/repo/pull/100"
        )

    def test_merge_plugin_fires_pr_merged(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """merge_plugin.merge_pr fires pr_merged event on success."""
        registry = tmp_path / "AIPASS_REGISTRY.json"
        registry.write_text("{}", encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        mock_trigger = MagicMock()
        monkeypatch.setattr(trigger_core, "trigger", mock_trigger)

        with patch(
            "aipass.drone.apps.plugins.devpulse_ops.merge_plugin.subprocess.run", side_effect=_run_merge_success
        ):
            result = merge_pr("42", "devpulse")

        assert result["success"] is True
        mock_trigger.fire.assert_any_call("pr_merged", pr_number="42", title="Fix the thing")


# ===========================================================================
# Fix 5: Scope clarity footer on status/diff (#623)
# ===========================================================================

_GIT_MOD = "aipass.drone.apps.modules.git_module"


_AUTH = "aipass.drone.apps.plugins.devpulse_ops.auth.verify_git_access"


class TestScopeFooter:
    """Fix 5: Scoped status/diff shows footer, --all does not."""

    @patch(_AUTH, return_value="test_branch")
    def test_status_scoped_shows_footer(
        self, _mock_auth: MagicMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Scoped status output includes scope footer."""
        monkeypatch.chdir(tmp_path)

        with patch(f"{_GIT_MOD}._detect_branch_dir", return_value=("drone", tmp_path / "src" / "drone")):
            with patch(
                f"{_GIT_MOD}.status_handler.get_branch_status",
                return_value={"files": [], "total": 0, "message": "0 file(s) changed under src/drone"},
            ):
                result = handle_command("status", [])

        assert "(showing drone scope" in result["stdout"]
        assert "--all for full repo)" in result["stdout"]

    @patch(_AUTH, return_value="test_branch")
    def test_status_all_no_footer(self, _mock_auth: MagicMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """--all status output does NOT include scope footer."""
        monkeypatch.chdir(tmp_path)

        with patch(f"{_GIT_MOD}._detect_branch_dir", return_value=("drone", tmp_path / "src" / "drone")):
            with patch(f"{_GIT_MOD}.lock_handler.find_repo_root", return_value=tmp_path):
                with patch(
                    f"{_GIT_MOD}.status_handler.get_branch_status",
                    return_value={"files": [], "total": 0, "message": "0 file(s) changed in repo"},
                ):
                    result = handle_command("status", ["--all"])

        assert "showing drone scope" not in result["stdout"]

    @patch(_AUTH, return_value="test_branch")
    def test_diff_scoped_shows_footer(
        self, _mock_auth: MagicMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Scoped diff output includes scope footer."""
        monkeypatch.chdir(tmp_path)

        with patch(f"{_GIT_MOD}._detect_branch_dir", return_value=("drone", tmp_path / "src" / "drone")):
            with patch(
                f"{_GIT_MOD}.diff_handler.get_branch_diff",
                return_value={"diff": "", "files_changed": 0, "message": "0 file(s) changed"},
            ):
                result = handle_command("diff", [])

        assert "(showing drone scope" in result["stdout"]

    @patch(_AUTH, return_value="test_branch")
    def test_diff_all_no_footer(self, _mock_auth: MagicMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """--all diff output does NOT include scope footer."""
        monkeypatch.chdir(tmp_path)

        with patch(f"{_GIT_MOD}._detect_branch_dir", return_value=("drone", tmp_path / "src" / "drone")):
            with patch(f"{_GIT_MOD}.lock_handler.find_repo_root", return_value=tmp_path):
                with patch(
                    f"{_GIT_MOD}.diff_handler.get_branch_diff",
                    return_value={"diff": "some diff", "files_changed": 1, "message": "1 file(s)"},
                ):
                    result = handle_command("diff", ["--all"])

        assert "showing drone scope" not in result["stdout"]

    # ── false-green regression: a git failure must exit non-zero (backlog flag) ──

    _STATUS_ERR = {"ok": False, "files": [], "total": 0, "message": "git status error: fatal: not a git repository"}
    _DIFF_ERR = {"ok": False, "diff": "", "files_changed": 0, "message": "git diff error: fatal: bad revision"}

    @patch(_AUTH, return_value="test_branch")
    def test_status_error_exits_nonzero(
        self, _mock_auth: MagicMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A failed git status exits 1 with the error on stderr — not a clean 0-changes report."""
        monkeypatch.chdir(tmp_path)

        with patch(f"{_GIT_MOD}._detect_branch_dir", return_value=("drone", tmp_path / "src" / "drone")):
            with patch(f"{_GIT_MOD}.status_handler.get_branch_status", return_value=dict(self._STATUS_ERR)):
                result = handle_command("status", [])

        assert result["exit_code"] == 1
        assert "git status error" in result["stderr"]

    @patch(_AUTH, return_value="test_branch")
    def test_status_all_error_not_overwritten(
        self, _mock_auth: MagicMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--all must not reword an error into 'N file(s) changed in repo' (the false-green shape)."""
        monkeypatch.chdir(tmp_path)

        with patch(f"{_GIT_MOD}._detect_branch_dir", return_value=("drone", tmp_path / "src" / "drone")):
            with patch(f"{_GIT_MOD}.lock_handler.find_repo_root", return_value=tmp_path):
                with patch(f"{_GIT_MOD}.status_handler.get_branch_status", return_value=dict(self._STATUS_ERR)):
                    result = handle_command("status", ["--all"])

        assert result["exit_code"] == 1
        assert "git status error" in result["stderr"]
        assert "changed in repo" not in result["stderr"] + result["stdout"]

    @patch(_AUTH, return_value="test_branch")
    def test_diff_error_exits_nonzero(
        self, _mock_auth: MagicMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A failed git diff exits 1 with the error on stderr."""
        monkeypatch.chdir(tmp_path)

        with patch(f"{_GIT_MOD}._detect_branch_dir", return_value=("drone", tmp_path / "src" / "drone")):
            with patch(f"{_GIT_MOD}.diff_handler.get_branch_diff", return_value=dict(self._DIFF_ERR)):
                result = handle_command("diff", [])

        assert result["exit_code"] == 1
        assert "git diff error" in result["stderr"]

    @patch(_AUTH, return_value="test_branch")
    def test_handler_ok_flag_set_on_git_failure(
        self, _mock_auth: MagicMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The status handler itself stamps ok=False when git exits non-zero."""
        import subprocess as _sp

        monkeypatch.chdir(tmp_path)
        fake = _sp.CompletedProcess(args=["git"], returncode=128, stdout="", stderr="fatal: not a git repository")
        with patch("aipass.drone.apps.handlers.git.status_handler.subprocess.run", return_value=fake):
            result = get_branch_status(tmp_path)

        assert result["ok"] is False
        assert "git status error" in result["message"]


# ===========================================================================
# Merge joint-decision gate (DPLAN-0256)
# ===========================================================================

_MERGE_PR = "aipass.drone.apps.plugins.devpulse_ops.merge_plugin.merge_pr"
_MERGE_OK = {
    "success": True,
    "pr_number": "123",
    "title": "t",
    "merge_commit": "abc123",
    "message": "PR #123 merged: t (abc123)",
}


class TestMergeGate:
    """merge must never run without explicit confirmation."""

    @patch(_AUTH, return_value="devpulse")
    def test_headless_without_confirm_refused(self, _mock_auth: MagicMock) -> None:
        """Non-TTY caller without --confirm is refused before the plugin loads."""
        with patch(_MERGE_PR) as mock_merge:
            with patch(f"{_GIT_MOD}._terminal_answer", return_value=None):
                result = handle_command("merge", ["123"])

        assert result["exit_code"] == 1
        assert "requires explicit confirmation" in result["stderr"]
        assert "--confirm" in result["stderr"]
        mock_merge.assert_not_called()

    @patch(_AUTH, return_value="devpulse")
    def test_confirm_flag_proceeds(self, _mock_auth: MagicMock) -> None:
        """--confirm merges without prompting, even headless."""
        with patch(_MERGE_PR, return_value=dict(_MERGE_OK)) as mock_merge:
            with patch(f"{_GIT_MOD}._terminal_answer", return_value=None):
                result = handle_command("merge", ["123", "--confirm"])

        assert result["exit_code"] == 0
        mock_merge.assert_called_once_with("123", "devpulse")

    @patch(_AUTH, return_value="devpulse")
    def test_confirm_flag_position_agnostic(self, _mock_auth: MagicMock) -> None:
        """--confirm before the PR number still resolves the right PR."""
        with patch(_MERGE_PR, return_value=dict(_MERGE_OK)) as mock_merge:
            with patch(f"{_GIT_MOD}._terminal_answer", return_value=None):
                result = handle_command("merge", ["--confirm", "123"])

        assert result["exit_code"] == 0
        mock_merge.assert_called_once_with("123", "devpulse")

    @patch(_AUTH, return_value="devpulse")
    def test_tty_yes_proceeds(self, _mock_auth: MagicMock) -> None:
        """Interactive terminal answering y merges, after the joint-decision prompt.

        The terminal is handed in through _terminal_answer, never by replacing sys.stdin."""
        with (
            patch(f"{_GIT_MOD}._terminal_answer", return_value="y\n") as mock_answer,
            patch(_MERGE_PR, return_value=dict(_MERGE_OK)) as mock_merge,
        ):
            result = handle_command("merge", ["123"])

        assert result["exit_code"] == 0
        mock_answer.assert_called_once_with("Merge PR #123? Merges are a joint decision. [y/N] ")
        mock_merge.assert_called_once_with("123", "devpulse")

    @patch(_AUTH, return_value="devpulse")
    def test_tty_default_aborts(self, _mock_auth: MagicMock) -> None:
        """Interactive terminal hitting enter (default N) aborts."""
        with (
            patch(f"{_GIT_MOD}._terminal_answer", return_value="\n"),
            patch(_MERGE_PR) as mock_merge,
        ):
            result = handle_command("merge", ["123"])

        assert result["exit_code"] == 1
        assert "aborted" in result["stderr"]
        mock_merge.assert_not_called()

    @patch(_AUTH, return_value="devpulse")
    def test_confirm_without_pr_number_is_usage_error(self, _mock_auth: MagicMock) -> None:
        """--confirm alone (no PR number) is a usage error, not a merge."""
        with patch(_MERGE_PR) as mock_merge:
            result = handle_command("merge", ["--confirm"])

        assert result["exit_code"] == 1
        assert "Usage" in result["stderr"]
        mock_merge.assert_not_called()


# ===========================================================================
# issue view — Projects-classic deprecation
# ===========================================================================


def _spawned_issue_args(args: list[str]) -> list[str]:
    """What `drone @git issue <args>` hands gh after 'gh issue', read off a recording subprocess stub."""
    with patch(_AUTH, return_value="drone"), patch(f"{_GIT_MOD}.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="", stderr="", returncode=0)
        handle_command("issue", list(args))
    mock_run.assert_called_once()
    spawned = mock_run.call_args[0][0]
    assert spawned[:2] == ["gh", "issue"]
    return spawned[2:]


class TestIssueViewRewrite:
    """The default issue view render is rejected by GitHub — pin the fields.

    That GraphQL view requests repository.issue.projectCards, a Projects-classic
    field the API now refuses outright: the caller gets a deprecation notice and
    no issue at all. Rendering from explicit --json fields never asks for it.
    """

    def test_bare_view_pins_json_fields(self) -> None:
        """A plain view <n> gains --json/--template and keeps the issue number.

        Mutant: the passthrough skips _rewrite_issue_view — a plain view spawns bare.
        """
        rewritten = _spawned_issue_args(["view", "728"])

        assert rewritten[:2] == ["view", "728"]
        assert "--json" in rewritten
        assert "--template" in rewritten
        fields = rewritten[rewritten.index("--json") + 1]
        assert "projectCards" not in fields
        assert "body" in fields.split(",")

    def test_comments_flag_swapped_for_comments_field(self) -> None:
        """--comments conflicts with --json, so it becomes a requested field."""
        rewritten = _spawned_issue_args(["view", "733", "--comments"])

        assert "--comments" not in rewritten
        assert "comments" in rewritten[rewritten.index("--json") + 1].split(",")
        assert "{{range .comments}}" in rewritten[rewritten.index("--template") + 1]

    def test_short_comments_flag_also_handled(self) -> None:
        """-c is the same flag and conflicts identically."""
        rewritten = _spawned_issue_args(["view", "733", "-c"])

        assert "-c" not in rewritten
        assert "comments" in rewritten[rewritten.index("--json") + 1].split(",")

    def test_unrelated_flags_survive(self) -> None:
        """--repo is not a rendering choice — it must reach the CLI untouched."""
        rewritten = _spawned_issue_args(["view", "728", "--repo", "AIOSAI/AIPass"])

        assert rewritten[:4] == ["view", "728", "--repo", "AIOSAI/AIPass"]
        assert "--json" in rewritten

    @pytest.mark.parametrize("flag", ["--json", "--jq", "-q", "--template", "-t", "--web", "-w"])
    def test_callers_own_rendering_untouched(self, flag: str) -> None:
        """A caller who picked a rendering keeps it — ours would conflict.

        Mutant: the render-flag check removed — a caller's own rendering gets ours appended.
        """
        args = ["view", "728", flag, "x"]

        assert _spawned_issue_args(args) == args

    @pytest.mark.parametrize("args", [["list"], ["create", "--title", "x"], ["close", "728"], []])
    def test_other_issue_subcommands_untouched(self, args: list[str]) -> None:
        """Only view requests projectCards — everything else passes through.

        Mutant: the `args[0] != "view"` test dropped — list/create/close get view's fields.
        """
        spawned = _spawned_issue_args(args)
        assert spawned == args
        assert "--template" not in spawned

    @patch(_AUTH, return_value="drone")
    def test_view_never_spawned_bare(self, _mock_auth: MagicMock) -> None:
        """Canary: the exact command GitHub rejects must never be spawned."""
        with patch(f"{_GIT_MOD}.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="", stderr="", returncode=0)
            handle_command("issue", ["view", "728"])

        spawned = mock_run.call_args[0][0]
        assert spawned[:3] == ["gh", "issue", "view"]
        assert spawned != ["gh", "issue", "view", "728"]
        assert "--json" in spawned

    @patch(_AUTH, return_value="drone")
    def test_run_subcommand_not_rewritten(self, _mock_auth: MagicMock) -> None:
        """The rewrite is scoped to issue — run view is a different command."""
        with patch(f"{_GIT_MOD}.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="", stderr="", returncode=0)
            handle_command("run", ["view", "123"])

        assert mock_run.call_args[0][0] == ["gh", "run", "view", "123"]


# ===========================================================================
# run view --log — gh prints nothing for a job-level log archive
# ===========================================================================

_RUN_JOBS_JQ = '.jobs[] | "\\(.id)\\t\\(.conclusion)\\t\\(.name)"'
_ONE_JOB_JQ = '"\\(.id)\\t\\(.conclusion)\\t\\(.name)"'


def _gh_answers(routes: dict[tuple[str, ...], MagicMock]):
    """A subprocess.run stand-in that answers by exact argv and fails the test on any other call."""

    def _run(argv: list[str], **_kwargs: object) -> MagicMock:
        if tuple(argv) not in routes:
            raise AssertionError(f"unexpected call: {argv}")
        return routes[tuple(argv)]

    return _run


class TestRunLogFallback:
    """gh 2.45 matches per-step files in a run's log archive, and GitHub now ships job-level
    files only, so `run view --log-failed` printed nothing and exited 0 (runs 34730939542 and
    34745763695, @devpulse 2026-09-13). An empty clean answer is read from the jobs API."""

    @patch(_AUTH, return_value="drone")
    def test_log_failed_reads_each_failed_job_from_the_api(self, _mock_auth: MagicMock) -> None:
        routes = {
            ("gh", "run", "view", "34730939542", "--log-failed"): _done(),
            (
                "gh",
                "api",
                "--paginate",
                "repos/{owner}/{repo}/actions/runs/34730939542/jobs",
                "--jq",
                _RUN_JOBS_JQ,
            ): _done("103653482487\tsuccess\tlint\n103653482575\tfailure\ttest (3.10)\n"),
            ("gh", "api", "repos/{owner}/{repo}/actions/jobs/103653482575/logs"): _done(
                "FAILED tests/test_x.py::test_y\n1 failed, 40 passed\n"
            ),
        }
        with patch(f"{_GIT_MOD}.subprocess.run", side_effect=_gh_answers(routes)) as mock_run:
            result = handle_command("run", ["view", "34730939542", "--log-failed"])

        assert result["stdout"] == "test (3.10)\tFAILED tests/test_x.py::test_y\ntest (3.10)\t1 failed, 40 passed"
        assert result["exit_code"] == 0
        assert "Showing the full log of each failed job from the jobs API instead." in result["stderr"]
        assert mock_run.call_count == 3

    @patch(_AUTH, return_value="drone")
    def test_a_job_log_reads_the_named_repo_and_job(self, _mock_auth: MagicMock) -> None:
        routes = {
            ("gh", "run", "view", "--job", "103693306440", "--log", "-R", "AIOSAI/baud"): _done(),
            ("gh", "api", "repos/AIOSAI/baud/actions/jobs/103693306440", "--jq", _ONE_JOB_JQ): _done(
                "103693306440\tsuccess\tbuild\n"
            ),
            ("gh", "api", "repos/AIOSAI/baud/actions/jobs/103693306440/logs"): _done("step one\nstep two\n"),
        }
        with patch(f"{_GIT_MOD}.subprocess.run", side_effect=_gh_answers(routes)):
            result = handle_command("run", ["view", "--job", "103693306440", "--log", "-R", "AIOSAI/baud"])

        assert result["stdout"] == "build\tstep one\nbuild\tstep two"
        assert result["exit_code"] == 0

    @patch(_AUTH, return_value="drone")
    def test_a_log_gh_did_print_is_returned_untouched(self, _mock_auth: MagicMock) -> None:
        routes = {("gh", "run", "view", "123", "--log"): _done("lint\tRun ruff\tAll checks passed!\n")}
        with patch(f"{_GIT_MOD}.subprocess.run", side_effect=_gh_answers(routes)) as mock_run:
            result = handle_command("run", ["view", "123", "--log"])

        assert result == {"stdout": "lint\tRun ruff\tAll checks passed!\n", "stderr": "", "exit_code": 0}
        assert mock_run.call_count == 1

    @patch(_AUTH, return_value="drone")
    def test_a_job_log_the_api_refuses_fails_the_command_by_name(self, _mock_auth: MagicMock) -> None:
        routes = {
            ("gh", "run", "view", "77", "--log-failed"): _done(),
            ("gh", "api", "--paginate", "repos/{owner}/{repo}/actions/runs/77/jobs", "--jq", _RUN_JOBS_JQ): _done(
                "9\tfailure\ttest (3.12)\n"
            ),
            ("gh", "api", "repos/{owner}/{repo}/actions/jobs/9/logs"): _done(returncode=1, stderr="HTTP 410: Gone"),
        }
        with patch(f"{_GIT_MOD}.subprocess.run", side_effect=_gh_answers(routes)):
            result = handle_command("run", ["view", "77", "--log-failed"])

        assert result["exit_code"] == 1
        assert result["stdout"] == ""
        assert result["stderr"].splitlines()[-1] == "job 9 (test (3.12)): HTTP 410: Gone"

    @pytest.mark.parametrize(
        "argv",
        [
            ["run", "list", "--repo", "AIOSAI/baud"],
            ["issue", "list", "--repo=AIOSAI/baud"],
            ["workflow", "list", "--repo", "AIOSAI/baud"],
        ],
    )
    @patch(_AUTH, return_value="drone")
    def test_gh_keeps_its_own_repo_flag(self, _mock_auth: MagicMock, argv: list[str]) -> None:
        """--repo OWNER/NAME on a passthrough is gh's flag, never the external-repo door's."""
        with patch(f"{_GIT_MOD}.subprocess.run", return_value=_done("ok\n")) as mock_run:
            result = handle_command(argv[0], argv[1:])

        assert mock_run.call_args[0][0] == ["gh", *argv]
        assert result == {"stdout": "ok\n", "stderr": "", "exit_code": 0}

    @patch(_AUTH, return_value="drone")
    def test_a_named_attempt_reads_that_attempts_jobs(self, _mock_auth: MagicMock) -> None:
        """Mutant: `attempt = None` at git_module.py:402 — the jobs URL loses /attempts/2."""
        routes = {
            ("gh", "run", "view", "55", "--attempt", "2", "--log"): _done(),
            (
                "gh",
                "api",
                "--paginate",
                "repos/{owner}/{repo}/actions/runs/55/attempts/2/jobs",
                "--jq",
                _RUN_JOBS_JQ,
            ): _done("31\tsuccess\tlint\n"),
            ("gh", "api", "repos/{owner}/{repo}/actions/jobs/31/logs"): _done("second try\n"),
        }
        with patch(f"{_GIT_MOD}.subprocess.run", side_effect=_gh_answers(routes)) as mock_run:
            result = handle_command("run", ["view", "55", "--attempt", "2", "--log"])

        assert result["stdout"] == "lint\tsecond try"
        assert result["exit_code"] == 0
        assert mock_run.call_count == 3


# ===========================================================================
# Flags the module's own verbs parse: diff --staged, sync --autostash
# ===========================================================================


def _passport_branch(root: Path, name: str) -> Path:
    """A branch directory the CWD lookup recognises, built under tmp_path."""
    branch_dir = root / name
    (branch_dir / ".trinity").mkdir(parents=True)
    (branch_dir / ".trinity" / "passport.json").write_text(
        json.dumps({"branch_info": {"branch_name": name}}), encoding="utf-8"
    )
    return branch_dir


class TestVerbFlags:
    """Each flag reaches the handler that acts on it; the handler is a recorder, so no git runs."""

    @patch(_AUTH, return_value="drone")
    def test_diff_staged_asks_the_handler_for_the_index(
        self, _mock_auth: MagicMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Mutant: `staged = False` at git_module.py:776 — the handler is asked for the worktree."""
        branch_dir = _passport_branch(tmp_path, "drone")
        monkeypatch.chdir(branch_dir)
        answer = {"ok": True, "diff": "diff --git a/x b/x\n", "message": ""}
        with patch(f"{_GIT_MOD}.diff_handler.get_branch_diff", return_value=answer) as mock_diff:
            result = handle_command("diff", ["--staged"])

        mock_diff.assert_called_once_with(branch_dir.resolve(), staged=True, stat=False)
        assert result["exit_code"] == 0
        assert result["stdout"].startswith("diff --git a/x b/x")

    @patch(_AUTH, return_value="drone")
    def test_diff_without_staged_asks_for_the_worktree(
        self, _mock_auth: MagicMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Mutant: `staged = True` at git_module.py:776 — a plain diff reads the index."""
        branch_dir = _passport_branch(tmp_path, "drone")
        monkeypatch.chdir(branch_dir)
        answer = {"ok": True, "diff": "", "message": "No changes"}
        with patch(f"{_GIT_MOD}.diff_handler.get_branch_diff", return_value=answer) as mock_diff:
            result = handle_command("diff", [])

        mock_diff.assert_called_once_with(branch_dir.resolve(), staged=False, stat=False)
        assert result["exit_code"] == 0

    @patch(_AUTH, return_value="devpulse")
    def test_sync_autostash_hands_autostash_to_the_sync(self, _mock_auth: MagicMock) -> None:
        """Mutant: `autostash = False` at git_module.py:1000 — the sync runs without the stash."""
        answer = {"success": True, "message": "synced dev with main"}
        with patch(f"{_GIT_MOD}.sync_handler.sync_main", return_value=answer) as mock_sync:
            result = handle_command("sync", ["--autostash"])

        mock_sync.assert_called_once_with(autostash=True)
        assert result == {"stdout": "synced dev with main", "stderr": "", "exit_code": 0}

    @patch(_AUTH, return_value="devpulse")
    def test_sync_without_autostash_leaves_the_tree_alone(self, _mock_auth: MagicMock) -> None:
        """Mutant: `autostash = True` at git_module.py:1000 — a plain sync would stash the caller's work."""
        answer = {"success": False, "message": "dirty tree"}
        with patch(f"{_GIT_MOD}.sync_handler.sync_main", return_value=answer) as mock_sync:
            result = handle_command("sync", [])

        mock_sync.assert_called_once_with(autostash=False)
        assert result == {"stdout": "", "stderr": "dirty tree", "exit_code": 1}


# ===========================================================================
# untrack <path ...>: out of the index, never off the disk, never committed
# ===========================================================================


def _git(cwd: Path, *argv: str) -> str:
    """Run git in *cwd* for fixture setup and read-back; raises on failure."""
    return subprocess.run(
        ["git", *argv], cwd=str(cwd), capture_output=True, text=True, encoding="utf-8", check=True
    ).stdout.strip()


@pytest.fixture()
def untrack_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A real repo holding tracked a.txt, sub/one.txt, sub/two.txt and a force-added, ignored kept.log.

    Git runs with no host config, a fixed identity and a ceiling at tmp_path. The
    caller stands at the repo root with no AIPASS_CALLER_CWD stamp.
    """
    empty_config = tmp_path / "gitconfig"
    empty_config.write_text("", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(empty_config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", os.pathsep.join(sorted({str(tmp_path), str(tmp_path.resolve())})))
    for name in ("GIT_AUTHOR_NAME", "GIT_COMMITTER_NAME"):
        monkeypatch.setenv(name, "Untrack Test")
    for name in ("GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL"):
        monkeypatch.setenv(name, "untrack@test.invalid")
    monkeypatch.delenv("AIPASS_CALLER_CWD", raising=False)

    work = tmp_path / "work"
    (work / "sub").mkdir(parents=True)
    _git(work, "init", "-q", "-b", "dev")
    (work / ".gitignore").write_text("*.log\n", encoding="utf-8")
    for name in ("a.txt", "sub/one.txt", "sub/two.txt", "kept.log"):
        (work / name).write_text(f"{name}\n", encoding="utf-8")
    _git(work, "add", ".gitignore", "a.txt", "sub")
    _git(work, "add", "-f", "kept.log")
    _git(work, "commit", "-q", "-m", "seed")
    monkeypatch.chdir(work)
    return work


def _untrack(work: Path, args: list[str]) -> dict:
    with patch(_AUTH, return_value="devpulse"), patch(f"{_GIT_MOD}.lock_handler.find_repo_root", return_value=work):
        return handle_command("untrack", args)


class TestUntrack:
    """untrack: a tracked file leaves the index and stays on disk; anything else is refused by name."""

    def test_a_tracked_file_leaves_the_index_stays_on_disk_and_nothing_is_committed(self, untrack_repo: Path) -> None:
        """Mutant: --cached dropped — git rm deletes the working-tree file too."""
        work = untrack_repo
        head = _git(work, "rev-parse", "HEAD")

        result = _untrack(work, ["a.txt"])

        assert result == {
            "stdout": "left the index  a.txt\n" + untrack_handler.NEXT_STEP.format(count=1),
            "stderr": "",
            "exit_code": 0,
        }
        assert "a.txt" not in _git(work, "ls-files").splitlines()
        assert (work / "a.txt").read_text(encoding="utf-8") == "a.txt\n"
        assert _git(work, "rev-parse", "HEAD") == head, "untrack never commits"

    def test_untracked_ignored_and_missing_paths_are_refused_by_name_and_the_tracked_one_still_leaves(
        self, untrack_repo: Path
    ) -> None:
        """Mutant: the not-tracked refusal removed — git rm is asked for a path the index never held."""
        work = untrack_repo
        (work / "new.txt").write_text("new\n", encoding="utf-8")
        (work / "x.log").write_text("log\n", encoding="utf-8")

        result = _untrack(work, ["new.txt", "x.log", "gone.txt", "a.txt"])

        assert result["exit_code"] == 1
        assert result["stderr"].splitlines() == [
            untrack_handler.REFUSE_NOT_TRACKED.format(path="new.txt", state="untracked"),
            untrack_handler.REFUSE_NOT_TRACKED.format(path="x.log", state="ignored"),
            untrack_handler.REFUSE_NOT_TRACKED.format(path="gone.txt", state="missing"),
        ]
        assert result["stdout"].splitlines()[0] == "left the index  a.txt"
        assert "a.txt" not in _git(work, "ls-files").splitlines()
        assert (work / "new.txt").exists() and (work / "x.log").exists()

    def test_a_directory_is_refused_without_recursive_and_leaves_whole_with_it(self, untrack_repo: Path) -> None:
        work = untrack_repo

        refused = _untrack(work, ["sub"])
        listed_after_refusal = _git(work, "ls-files", "sub").splitlines()
        recursive = _untrack(work, ["--recursive", "sub"])

        assert refused == {"stdout": "", "stderr": untrack_handler.REFUSE_DIRECTORY.format(path="sub"), "exit_code": 1}
        assert listed_after_refusal == ["sub/one.txt", "sub/two.txt"]
        assert recursive["exit_code"] == 0
        assert recursive["stdout"].splitlines()[0] == "left the index  sub"
        assert _git(work, "ls-files", "sub") == ""
        assert (work / "sub" / "one.txt").exists() and (work / "sub" / "two.txt").exists()

    def test_the_printed_next_step_commits_an_ignored_file_out_and_keeps_it_on_disk(self, untrack_repo: Path) -> None:
        """The ratchet case: tracked before its .gitignore line; commit with paths would stage it back."""
        work = untrack_repo

        untracked = _untrack(work, ["kept.log"])
        with (
            patch(_AUTH, return_value="devpulse"),
            patch("aipass.drone.apps.handlers.git.commit_handler.find_repo_root", return_value=work),
        ):
            commit = handle_command("commit", ["chore: untrack kept.log"])

        assert untracked["exit_code"] == 0
        assert 'drone @git commit "<message>"  (no paths' in untracked["stdout"]
        assert commit["exit_code"] == 0
        assert "kept.log" not in _git(work, "ls-tree", "-r", "--name-only", "HEAD").splitlines()
        assert (work / "kept.log").exists()
        assert _git(work, "status", "--porcelain") == ""

    def test_no_path_and_an_unknown_flag_are_refused_before_git_runs(self, untrack_repo: Path) -> None:
        assert _untrack(untrack_repo, ["--recursive"]) == {
            "stdout": "",
            "stderr": "Usage: drone @git untrack [--recursive] <path ...>",
            "exit_code": 1,
        }
        assert _untrack(untrack_repo, ["-f", "a.txt"]) == {
            "stdout": "",
            "stderr": "Unknown argument for 'untrack': -f",
            "exit_code": 1,
        }
        assert "a.txt" in _git(untrack_repo, "ls-files").splitlines()

    def test_untrack_is_owner_tier_and_the_real_gate_stops_a_builder(self, untrack_repo: Path) -> None:
        make_owner_project(untrack_repo, citizen_class="builder")

        result = handle_command("untrack", ["a.txt"])

        assert "untrack" in GIT_ACCESS_TIERS["owner"]["commands"]
        assert "untrack" not in GIT_ACCESS_TIERS["global"]["commands"]
        assert result["exit_code"] == 1
        assert "not authorized" in result["stderr"].lower()
        assert "a.txt" in _git(untrack_repo, "ls-files").splitlines()

    def test_help_names_the_verb_under_owner_and_its_page_renders_the_refusals(self) -> None:
        owner_part = get_help().split("Owner (devpulse only):\n", 1)[1].split("\n\n", 1)[0]
        page = get_help("untrack")

        assert "  untrack <path ...> " in owner_part
        assert page.startswith("git untrack [--recursive] <path ...> — ")
        assert untrack_handler.REFUSE_DIRECTORY.format(path="<path>") in page
        assert untrack_handler.REFUSE_NOT_TRACKED.format(path="<path>", state="<state>") in page


# ===========================================================================
# release list: published releases and their notes, read-only, every seat
# ===========================================================================

_PUBLIC = {"private": False}
_PAGE = "repos/AIOSAI/AIPass/releases?per_page=100&page={n}"
_RELEASES = [
    {
        "tag_name": "v3",
        "name": "three",
        "published_at": "2026-10-03T00:00:00Z",
        "body": "## v3\r\n\r\n- fix",
        "draft": False,
    },
    {"tag_name": "v3-draft", "name": "unpublished", "published_at": None, "body": "wip", "draft": True},
    {"tag_name": "v2", "name": "two", "published_at": "2026-10-02T00:00:00Z", "body": "", "draft": False},
    {"tag_name": "v1", "name": "one", "published_at": "2026-10-01T00:00:00Z", "body": "first", "draft": False},
]


def _github(answers: dict[str, object], calls: list[str], gh_missing: bool = False):
    """A gh stand-in answering `gh api <path>` from *answers* as GitHub would, 404 for any other path."""

    def run(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess:
        if gh_missing:
            raise FileNotFoundError("gh")
        assert argv[:2] == ["gh", "api"], f"unexpected call: {argv}"
        calls.append(argv[2])
        if argv[2] not in answers:
            return subprocess.CompletedProcess(argv, 1, stdout="", stderr="gh: Not Found (HTTP 404)")
        return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(answers[argv[2]]), stderr="")

    return run


def _release(args: list[str], answers: dict[str, object], calls: list[str], gh_missing: bool = False) -> dict:
    with patch(f"{_RELEASE_MOD}.subprocess.run", side_effect=_github(answers, calls, gh_missing)):
        return handle_command("release", args)


_RELEASE_MOD = "aipass.drone.apps.handlers.git.release_handler"
_AIPASS_RELEASES = {"repos/AIOSAI/AIPass": _PUBLIC, _PAGE.format(n=1): _RELEASES}


class TestReleaseList:
    """release list reads a public repo's published releases through gh api, for every seat."""

    def test_a_citizen_with_no_ownership_reads_aipass_releases_newest_first_with_notes_indented(
        self, seedgo_dir: Path
    ) -> None:
        """The real gate, a builder's passport: the global tier serves it. Drafts are not published."""
        calls: list[str] = []

        result = _release(["list"], _AIPASS_RELEASES, calls)

        assert result == {
            "stdout": (
                "v3  2026-10-03T00:00:00Z  three\n    ## v3\n\n    - fix\n\n"
                "v2  2026-10-02T00:00:00Z  two\n    (no notes)\n\n"
                "v1  2026-10-01T00:00:00Z  one\n    first"
            ),
            "stderr": "",
            "exit_code": 0,
        }
        assert calls == ["repos/AIOSAI/AIPass", _PAGE.format(n=1)]

    def test_since_stops_before_its_tag_and_a_mistyped_tag_is_refused_even_past_the_limit(
        self, seedgo_dir: Path
    ) -> None:
        """Mutant: the limit returns before --since is checked, so a typo came back as a full page."""
        since = _release(["list", "--since", "v1"], _AIPASS_RELEASES, [])
        capped = _release(["list", "--since=v1", "--limit", "1"], _AIPASS_RELEASES, [])
        typo = _release(["list", "--since", "v0", "--limit", "1"], _AIPASS_RELEASES, [])

        assert [line.split("  ")[0] for line in since["stdout"].splitlines() if line.startswith("v")] == ["v3", "v2"]
        assert capped["stdout"].startswith("v3  ") and "\nv2  " not in capped["stdout"]
        assert typo == {
            "stdout": "",
            "stderr": release_handler.REFUSE_SINCE.format(tag="v0", repo="AIOSAI/AIPass"),
            "exit_code": 1,
        }

    def test_a_since_tag_on_the_second_page_is_found(self, seedgo_dir: Path) -> None:
        """Mutant: only page one is read — the tag is never seen and the read is refused."""
        newer = [
            {"tag_name": f"v1.{n}", "name": "", "published_at": "", "body": "", "draft": False}
            for n in range(100, 0, -1)
        ]
        answers = {"repos/AIOSAI/AIPass": _PUBLIC, _PAGE.format(n=1): newer, _PAGE.format(n=2): _RELEASES}

        result = _release(["list", "--since", "v2", "--limit", "2"], answers, [])

        assert result["exit_code"] == 0
        assert [line.split("  ")[0] for line in result["stdout"].splitlines() if line.startswith("v")] == [
            "v1.100",
            "v1.99",
        ]

    def test_json_carries_the_raw_rows_and_a_refusal_is_a_document_too(self, seedgo_dir: Path) -> None:
        result = _release(["list", "--json", "--limit", "1"], _AIPASS_RELEASES, [])
        refused = _release(["list", "--repo", "AIOSAI/gone", "--json"], _AIPASS_RELEASES, [])

        assert json.loads(result["stdout"]) == {
            "ok": True,
            "repo": "AIOSAI/AIPass",
            "count": 1,
            "releases": [
                {"tag": "v3", "published_at": "2026-10-03T00:00:00Z", "name": "three", "body": "## v3\r\n\r\n- fix"}
            ],
            "message": "1 release(s) of github.com/AIOSAI/AIPass",
        }
        assert result["exit_code"] == 0
        assert json.loads(refused["stdout"]) == {
            "ok": False,
            "repo": "AIOSAI/gone",
            "message": release_handler.REFUSE_UNKNOWN.format(repo="AIOSAI/gone"),
        }
        assert refused["exit_code"] == 1

    def test_a_private_repo_an_unknown_repo_and_a_missing_gh_are_refused_by_name(self, seedgo_dir: Path) -> None:
        """Mutant: the privacy check removed — a private repo's releases are read and printed."""
        private_calls: list[str] = []
        answers = {"repos/AIOSAI/secret": {"private": True}, "repos/AIOSAI/secret/releases?per_page=100&page=1": []}

        private = _release(["list", "--repo", "AIOSAI/secret"], answers, private_calls)
        unknown = _release(["list", "--repo", "AIOSAI/gone"], answers, [])
        missing = _release(["list"], answers, [], gh_missing=True)

        assert private["stderr"] == release_handler.REFUSE_PRIVATE.format(repo="AIOSAI/secret")
        assert private_calls == ["repos/AIOSAI/secret"]
        assert unknown["stderr"] == release_handler.REFUSE_UNKNOWN.format(repo="AIOSAI/gone")
        assert missing["stderr"] == release_handler.REFUSE_NO_GH
        assert {private["exit_code"], unknown["exit_code"], missing["exit_code"]} == {1}

    def test_repo_is_gh_owner_name_never_the_external_repo_door(self, seedgo_dir: Path) -> None:
        """Mutant: release left out of the door's exclusion — --repo is read as a path and refused for no grant."""
        calls: list[str] = []
        answers = {"repos/AIOSAI/other": _PUBLIC, "repos/AIOSAI/other/releases?per_page=100&page=1": []}

        result = _release(["list", "--repo", "AIOSAI/other"], answers, calls)

        assert result == {"stdout": "No published releases of github.com/AIOSAI/other.", "stderr": "", "exit_code": 0}
        assert calls == ["repos/AIOSAI/other", "repos/AIOSAI/other/releases?per_page=100&page=1"]

    @pytest.mark.parametrize(
        ("args", "refusal"),
        [
            (["list", "--repo", "not a slug"], release_handler.REFUSE_SLUG.format(repo="not a slug")),
            (["list", "--limit", "0"], release_handler.REFUSE_LIMIT.format(value="0")),
            (["list", "--since"], release_handler.REFUSE_NO_VALUE.format(flag="--since")),
            (["list", "--draft"], release_handler.REFUSE_FLAG.format(arg="--draft")),
            (["create", "v9"], release_handler.REFUSE_SUB.format(sub="create")),
            ([], release_handler.USAGE),
        ],
        ids=["slug", "limit", "no-value", "flag", "write", "bare"],
    )
    def test_a_malformed_call_is_refused_before_gh_runs(self, seedgo_dir: Path, args: list[str], refusal: str) -> None:
        calls: list[str] = []

        result = _release(args, _AIPASS_RELEASES, calls)

        assert result["stderr"] == refusal
        assert result["exit_code"] == 1
        assert calls == []

    def test_release_is_global_tier_and_help_names_it_in_the_page_list_and_twins(self) -> None:
        text = get_help()

        assert "release" in GIT_ACCESS_TIERS["global"]["commands"]
        assert "release" not in GIT_ACCESS_TIERS["owner"]["commands"]
        assert get_help("release").startswith("git release list [--repo OWNER/NAME] [--since TAG] [--limit N] ")
        assert release_handler.REFUSE_PRIVATE.format(repo="<repo>") in get_help("release")
        assert "  release list           Published releases and their notes (release --help)\n" in text
        assert "  gh release list|view       drone @git release list [--repo O/N] [--since TAG]\n" in text
