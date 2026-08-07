# =================== AIPass ====================
# Name: test_git_module.py
# Description: Tests for the @git module — lock, status, sync, PR, and routing
# Version: 1.0.0
# Created: 2026-04-21
# Modified: 2026-04-21
# =============================================

"""Tests for the @git module — lock, status, sync, PR, and routing."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from aipass.drone.apps.handlers.git.lock_handler import (
    acquire_lock,
    check_lock_status,
    find_repo_root,
    force_unlock,
    release_lock,
)
from aipass.drone.apps.handlers.git.status_handler import get_branch_status
from aipass.drone.apps.handlers.git.sync_handler import sync_main
from aipass.drone.apps.handlers.git.pr_handler import (
    _diagnose_push_failure,
    _has_credential_helper,
    create_pr,
)
from aipass.drone.apps.modules.git_module import (
    DRONE_MODULE,
    _detect_branch_dir,
    get_help,
    get_introspective,
    handle_command,
)
from aipass.trigger.apps.modules import core as trigger_core

from .conftest import make_owner_project


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture()
def lock_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Set up a temporary directory with AIPASS_REGISTRY.json for lock tests."""
    registry = tmp_path / "AIPASS_REGISTRY.json"
    registry.write_text("{}", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    return tmp_path


# ===========================================================================
# 1. lock_handler — acquire / release / double acquire / stale / orphan
# ===========================================================================


class TestLockAcquire:
    """Lock acquisition tests."""

    def test_acquire_succeeds(self, lock_dir: Path) -> None:
        """First acquire on a clean directory succeeds."""
        result = acquire_lock("@api")
        assert result["success"] is True
        assert "acquired" in result["message"].lower()
        assert (lock_dir / ".git_pr.lock").exists()

    def test_lock_file_contains_valid_json(self, lock_dir: Path) -> None:
        """The lock file is valid JSON with expected keys."""
        acquire_lock("@api")
        data = json.loads((lock_dir / ".git_pr.lock").read_text(encoding="utf-8"))
        assert data["branch"] == "@api"
        assert "started" in data
        assert data["pid"] == os.getpid()

    def test_double_acquire_blocked(self, lock_dir: Path) -> None:
        """Second acquire is blocked when lock is already held."""
        acquire_lock("@api")
        result = acquire_lock("@memory")
        assert result["success"] is False
        assert "blocked" in result["message"].lower()


class TestLockRelease:
    """Lock release tests."""

    def test_release_own_lock(self, lock_dir: Path) -> None:
        """Releasing a lock held by the current PID succeeds."""
        acquire_lock("@api")
        result = release_lock()
        assert result["success"] is True
        assert not (lock_dir / ".git_pr.lock").exists()

    def test_release_no_lock(self, lock_dir: Path) -> None:
        """Releasing when no lock exists is a no-op success."""
        result = release_lock()
        assert result["success"] is True
        assert "no lock" in result["message"].lower()

    def test_release_wrong_pid_blocked(self, lock_dir: Path) -> None:
        """Releasing a lock held by a different PID is blocked without force."""
        acquire_lock("@api")
        # Overwrite the lock file with a different PID
        lock_path = lock_dir / ".git_pr.lock"
        data = json.loads(lock_path.read_text(encoding="utf-8"))
        data["pid"] = 99999999
        lock_path.write_text(json.dumps(data), encoding="utf-8")

        result = release_lock(force=False)
        assert result["success"] is False
        assert "99999999" in result["message"]

    def test_release_force_overrides_pid_check(self, lock_dir: Path) -> None:
        """Force release removes lock regardless of PID."""
        acquire_lock("@api")
        lock_path = lock_dir / ".git_pr.lock"
        data = json.loads(lock_path.read_text(encoding="utf-8"))
        data["pid"] = 99999999
        lock_path.write_text(json.dumps(data), encoding="utf-8")

        result = release_lock(force=True)
        assert result["success"] is True
        assert not lock_path.exists()


class TestLockStatus:
    """Lock status check tests."""

    def test_status_no_lock(self, lock_dir: Path) -> None:
        """Status reports no active lock when file is absent."""
        result = check_lock_status()
        assert result["locked"] is False
        assert result["branch"] == ""

    def test_status_with_lock(self, lock_dir: Path) -> None:
        """Status reports lock info when file is present."""
        acquire_lock("@drone")
        result = check_lock_status()
        assert result["locked"] is True
        assert result["branch"] == "@drone"
        assert result["pid"] == os.getpid()
        assert result["orphaned"] is False

    def test_stale_detection(self, lock_dir: Path) -> None:
        """Lock older than threshold is detected as stale."""
        acquire_lock("@api")
        # Overwrite with an old timestamp
        lock_path = lock_dir / ".git_pr.lock"
        data = json.loads(lock_path.read_text(encoding="utf-8"))
        data["started"] = "2020-01-01T00:00:00+00:00"
        lock_path.write_text(json.dumps(data), encoding="utf-8")

        result = check_lock_status()
        assert result["stale"] is True
        assert result["age_seconds"] > 600

    def test_orphan_detection(self, lock_dir: Path) -> None:
        """Lock with a non-existent PID is detected as orphaned."""
        acquire_lock("@api")
        lock_path = lock_dir / ".git_pr.lock"
        data = json.loads(lock_path.read_text(encoding="utf-8"))
        data["pid"] = 99999999  # PID that almost certainly doesn't exist
        lock_path.write_text(json.dumps(data), encoding="utf-8")

        result = check_lock_status()
        assert result["orphaned"] is True


class TestForceUnlock:
    """Force unlock tests."""

    def test_force_unlock_removes_lock(self, lock_dir: Path) -> None:
        """Force unlock removes the lock file."""
        acquire_lock("@api")
        result = force_unlock()
        assert result["success"] is True
        assert not (lock_dir / ".git_pr.lock").exists()

    def test_force_unlock_no_lock(self, lock_dir: Path) -> None:
        """Force unlock when no lock is a no-op success."""
        result = force_unlock()
        assert result["success"] is True


class TestFindRepoRoot:
    """Repository root detection tests."""

    def test_finds_registry_file(self, lock_dir: Path) -> None:
        """Finds repo root by walking up to AIPASS_REGISTRY.json."""
        subdir = lock_dir / "a" / "b" / "c"
        subdir.mkdir(parents=True)
        # monkeypatch.chdir already set to lock_dir; chdir to subdir
        os.chdir(str(subdir))
        root = find_repo_root()
        assert root == lock_dir

    def test_finds_external_project_registry(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Any *_REGISTRY.json marks a root, not only AIPass's own (DPLAN-0281).

        External projects name theirs after themselves. Matching only the AIPass
        filename sent them to the rev-parse fallback while registry resolution
        (find_registry, which globs) found the real root — so the lock and the
        registry could disagree about where the project even is.
        """
        (tmp_path / "VERA-STUDIO_REGISTRY.json").write_text("{}", encoding="utf-8")
        subdir = tmp_path / "src" / "vera"
        subdir.mkdir(parents=True)
        monkeypatch.chdir(subdir)
        assert find_repo_root() == tmp_path

    def test_fallback_to_git(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Falls back to git rev-parse when no registry found."""
        monkeypatch.chdir(tmp_path)
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = str(tmp_path)

        with patch("aipass.drone.apps.handlers.git.lock_handler.subprocess.run", return_value=mock_result):
            root = find_repo_root()
        assert root == tmp_path


# ===========================================================================
# 2. status_handler — parsing and filtering
# ===========================================================================


class TestStatusHandler:
    """Scoped git status tests."""

    def test_filters_to_branch_dir(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Only files under branch_dir are included."""
        registry = tmp_path / "AIPASS_REGISTRY.json"
        registry.write_text("{}", encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        porcelain_output = (
            " M src/aipass/api/handlers/foo.py\n"
            " M src/aipass/api/module.py\n"
            " M src/aipass/drone/handlers/bar.py\n"
            "?? src/aipass/api/new_file.py\n"
        )
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = porcelain_output

        branch_dir = tmp_path / "src" / "aipass" / "api"

        with patch("aipass.drone.apps.handlers.git.status_handler.subprocess.run", return_value=mock_result):
            result = get_branch_status(branch_dir)

        assert result["total"] == 3
        paths = [f["path"] for f in result["files"]]
        assert "src/aipass/api/handlers/foo.py" in paths
        assert "src/aipass/api/module.py" in paths
        assert "src/aipass/api/new_file.py" in paths
        # drone file should NOT be included
        assert "src/aipass/drone/handlers/bar.py" not in paths

    def test_empty_status(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """No changes returns empty file list."""
        registry = tmp_path / "AIPASS_REGISTRY.json"
        registry.write_text("{}", encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""

        with patch("aipass.drone.apps.handlers.git.status_handler.subprocess.run", return_value=mock_result):
            result = get_branch_status(tmp_path / "src" / "aipass" / "api")

        assert result["total"] == 0
        assert result["files"] == []

    def test_git_failure(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """git status failure returns error message."""
        registry = tmp_path / "AIPASS_REGISTRY.json"
        registry.write_text("{}", encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        mock_result = MagicMock()
        mock_result.returncode = 128
        mock_result.stderr = "fatal: not a git repository"
        mock_result.stdout = ""

        with patch("aipass.drone.apps.handlers.git.status_handler.subprocess.run", return_value=mock_result):
            result = get_branch_status(tmp_path / "src" / "aipass" / "api")

        assert result["total"] == 0
        assert "error" in result["message"].lower()


# ===========================================================================
# 3. sync_handler — success and failure paths
# ===========================================================================


class TestSyncHandler:
    """Safe main sync tests."""

    def test_sync_success(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Successful sync returns success=True."""
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
            result = sync_main()

        assert result["success"] is True
        assert "already up to date" in result["message"].lower()

    def test_sync_checkout_failure(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Checkout failure returns success=False."""
        registry = tmp_path / "AIPASS_REGISTRY.json"
        registry.write_text("{}", encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "error: Your local changes would be overwritten"

        with patch(
            "aipass.drone.apps.handlers.git.sync_handler.subprocess.run",
            return_value=mock_result,
        ):
            result = sync_main()

        assert result["success"] is False
        assert "checkout main" in result["message"].lower() or "overwritten" in result["message"].lower()

    def test_sync_pull_failure(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Pull failure returns success=False."""
        registry = tmp_path / "AIPASS_REGISTRY.json"
        registry.write_text("{}", encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        mock_head = MagicMock(returncode=0, stdout="main", stderr="")
        mock_fetch = MagicMock(returncode=0, stdout="", stderr="")
        mock_rev_list = MagicMock(returncode=0, stdout="0\t1\n", stderr="")
        mock_pull = MagicMock(returncode=1, stdout="", stderr="fatal: unable to access remote")

        with patch(
            "aipass.drone.apps.handlers.git.sync_handler.subprocess.run",
            side_effect=[mock_head, mock_fetch, mock_rev_list, mock_pull],
        ):
            result = sync_main()

        assert result["success"] is False
        assert "pull" in result["message"].lower()

    def test_sync_os_error(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """OSError during sync returns success=False."""
        registry = tmp_path / "AIPASS_REGISTRY.json"
        registry.write_text("{}", encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        with patch(
            "aipass.drone.apps.handlers.git.sync_handler.subprocess.run",
            side_effect=OSError("git not found"),
        ):
            result = sync_main()

        assert result["success"] is False
        assert "failed" in result["message"].lower()


class TestSyncDev:
    """Sync from dev branch — fast-forward, not rebase."""

    def test_sync_dev_ff_success(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Sync on dev fast-forwards cleanly when behind main."""
        registry = tmp_path / "AIPASS_REGISTRY.json"
        registry.write_text("{}", encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        mock_head = MagicMock(returncode=0, stdout="dev", stderr="")
        mock_fetch = MagicMock(returncode=0, stdout="", stderr="")
        mock_merge = MagicMock(returncode=0, stdout="Updating abc..def\nFast-forward", stderr="")

        with patch(
            "aipass.drone.apps.handlers.git.sync_handler.subprocess.run",
            side_effect=[mock_head, mock_fetch, mock_merge],
        ):
            result = sync_main()

        assert result["success"] is True
        assert "dev" in result["message"].lower()

    def test_sync_dev_stays_on_dev(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Sync on dev does NOT checkout main — no git checkout call."""
        registry = tmp_path / "AIPASS_REGISTRY.json"
        registry.write_text("{}", encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        mock_head = MagicMock(returncode=0, stdout="dev", stderr="")
        mock_fetch = MagicMock(returncode=0, stdout="", stderr="")
        mock_merge = MagicMock(returncode=0, stdout="Already up to date.", stderr="")

        with patch(
            "aipass.drone.apps.handlers.git.sync_handler.subprocess.run",
            side_effect=[mock_head, mock_fetch, mock_merge],
        ) as mock_run:
            sync_main()

        cmds = [call[0][0] for call in mock_run.call_args_list]
        assert not any("checkout" in cmd for cmd in cmds), "sync on dev must not checkout"

    def test_sync_dev_uses_ff_only(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Sync on dev uses git merge --ff-only, not git pull --rebase."""
        registry = tmp_path / "AIPASS_REGISTRY.json"
        registry.write_text("{}", encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        mock_head = MagicMock(returncode=0, stdout="dev", stderr="")
        mock_fetch = MagicMock(returncode=0, stdout="", stderr="")
        mock_merge = MagicMock(returncode=0, stdout="Fast-forward", stderr="")

        with patch(
            "aipass.drone.apps.handlers.git.sync_handler.subprocess.run",
            side_effect=[mock_head, mock_fetch, mock_merge],
        ) as mock_run:
            sync_main()

        merge_call = mock_run.call_args_list[2][0][0]
        assert "merge" in merge_call, "should use git merge"
        assert "--ff-only" in merge_call, "should use --ff-only"
        assert "--rebase" not in str(mock_run.call_args_list), "must NOT use rebase"

    def test_sync_dev_refuses_on_diverge(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Sync on dev fails loud when dev has diverged (not fast-forwardable)."""
        registry = tmp_path / "AIPASS_REGISTRY.json"
        registry.write_text("{}", encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        mock_head = MagicMock(returncode=0, stdout="dev", stderr="")
        mock_fetch = MagicMock(returncode=0, stdout="", stderr="")
        mock_merge = MagicMock(returncode=1, stdout="", stderr="fatal: Not possible to fast-forward, aborting.")

        with patch(
            "aipass.drone.apps.handlers.git.sync_handler.subprocess.run",
            side_effect=[mock_head, mock_fetch, mock_merge],
        ):
            result = sync_main()

        assert result["success"] is False
        assert "fast-forward" in result["message"].lower() or "diverged" in result["message"].lower()

    def test_sync_dev_autostash(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Sync on dev with --autostash stashes and pops."""
        registry = tmp_path / "AIPASS_REGISTRY.json"
        registry.write_text("{}", encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        mock_head = MagicMock(returncode=0, stdout="dev", stderr="")
        mock_stash = MagicMock(returncode=0, stdout="Saved working directory", stderr="")
        mock_fetch = MagicMock(returncode=0, stdout="", stderr="")
        mock_merge = MagicMock(returncode=0, stdout="Fast-forward", stderr="")
        mock_pop = MagicMock(returncode=0, stdout="Restored", stderr="")

        with patch(
            "aipass.drone.apps.handlers.git.sync_handler.subprocess.run",
            side_effect=[mock_head, mock_stash, mock_fetch, mock_merge, mock_pop],
        ) as mock_run:
            result = sync_main(autostash=True)

        assert result["success"] is True
        cmds = [call[0][0] for call in mock_run.call_args_list]
        assert any(cmd == ["git", "stash"] for cmd in cmds)
        assert any(cmd == ["git", "stash", "pop"] for cmd in cmds)

    def test_sync_dev_fetch_failure(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Fetch failure in dev sync returns error."""
        registry = tmp_path / "AIPASS_REGISTRY.json"
        registry.write_text("{}", encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        mock_head = MagicMock(returncode=0, stdout="dev", stderr="")
        mock_fetch = MagicMock(returncode=1, stdout="", stderr="fatal: unable to access remote")

        with patch(
            "aipass.drone.apps.handlers.git.sync_handler.subprocess.run",
            side_effect=[mock_head, mock_fetch],
        ):
            result = sync_main()

        assert result["success"] is False
        assert "fetch" in result["message"].lower()


class TestSyncMainRef:
    """Sync local main ref without checkout."""

    def test_sync_main_ref_success(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """sync_main_ref updates local main ref."""
        from aipass.drone.apps.handlers.git.sync_handler import sync_main_ref

        registry = tmp_path / "AIPASS_REGISTRY.json"
        registry.write_text("{}", encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        mock_result = MagicMock(returncode=0, stdout="", stderr="")
        with patch(
            "aipass.drone.apps.handlers.git.sync_handler.subprocess.run",
            return_value=mock_result,
        ):
            result = sync_main_ref()

        assert result["success"] is True

    def test_sync_main_ref_failure(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """sync_main_ref fails on non-fast-forward."""
        from aipass.drone.apps.handlers.git.sync_handler import sync_main_ref

        registry = tmp_path / "AIPASS_REGISTRY.json"
        registry.write_text("{}", encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        mock_result = MagicMock(returncode=1, stdout="", stderr="! [rejected] main -> main (non-fast-forward)")
        with patch(
            "aipass.drone.apps.handlers.git.sync_handler.subprocess.run",
            return_value=mock_result,
        ):
            result = sync_main_ref()

        assert result["success"] is False
        assert "main" in result["message"].lower()


# ===========================================================================
# 4. pr_handler — error paths (no actual git)
# ===========================================================================


def _run_nothing_staged(cmd: list[str], **kwargs: object) -> MagicMock:
    """Subprocess mock: on main, nothing staged (diff --cached returns 0)."""
    r = MagicMock()
    r.returncode = 0
    r.stderr = ""
    r.stdout = "main\n" if cmd[1:3] == ["rev-parse", "--abbrev-ref"] else ""
    return r


def _run_cleanup_early_exit(cmd: list[str], **kwargs: object) -> MagicMock:
    """Subprocess mock: on main, nothing staged — triggers early exit path."""
    r = MagicMock()
    r.returncode = 0
    r.stderr = ""
    r.stdout = "main\n" if cmd[1:3] == ["rev-parse", "--abbrev-ref"] else ""
    return r


def _run_with_staged(cmd: list[str], **kwargs: object) -> MagicMock:
    """Subprocess mock: on main, staged changes, successful commit/push/PR."""
    r = MagicMock()
    r.returncode = 0
    r.stderr = ""
    r.stdout = ""
    if cmd[1:3] == ["rev-parse", "--abbrev-ref"]:
        r.stdout = "main\n"
    elif cmd[1:3] == ["diff", "--cached"]:
        r.returncode = 1  # 1 = something staged
    elif cmd[0] == "git" and cmd[1] == "commit":
        r.stdout = "[main abc1234] feat(api): test"
    elif cmd[0] == "gh":
        r.stdout = "https://github.com/test/repo/pull/1"
    return r


class TestPRHandler:
    """PR workflow error path tests."""

    def test_not_on_main_errors(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """PR creation fails if not on main branch."""
        registry = tmp_path / "AIPASS_REGISTRY.json"
        registry.write_text("{}", encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "feat/something\n"

        with patch("aipass.drone.apps.handlers.git.pr_handler.subprocess.run", return_value=mock_result):
            result = create_pr("api", "test description", tmp_path / "src" / "aipass" / "api")

        assert result["success"] is False
        assert "not on main" in result["message"].lower()

    def test_lock_blocked_errors(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """PR creation fails if lock is already held."""
        registry = tmp_path / "AIPASS_REGISTRY.json"
        registry.write_text("{}", encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        # Return "main" for rev-parse, then block lock
        mock_rev = MagicMock()
        mock_rev.returncode = 0
        mock_rev.stdout = "main\n"

        with patch("aipass.drone.apps.handlers.git.pr_handler.subprocess.run", return_value=mock_rev):
            with patch(
                "aipass.drone.apps.handlers.git.pr_handler.acquire_lock",
                return_value={"success": False, "message": "Lock blocked: already held by @memory"},
            ):
                result = create_pr("api", "test desc", tmp_path / "src" / "aipass" / "api")

        assert result["success"] is False
        assert "blocked" in result["message"].lower()

    def test_nothing_staged_errors(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """PR creation fails if nothing is staged."""
        registry = tmp_path / "AIPASS_REGISTRY.json"
        registry.write_text("{}", encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        with patch("aipass.drone.apps.handlers.git.pr_handler.subprocess.run", side_effect=_run_nothing_staged):
            with patch(
                "aipass.drone.apps.handlers.git.pr_handler.acquire_lock",
                return_value={"success": True, "message": "ok"},
            ):
                with patch("aipass.drone.apps.handlers.git.pr_handler.release_lock"):
                    result = create_pr("api", "test desc", tmp_path / "src" / "aipass" / "api")

        assert result["success"] is False
        assert "nothing to commit" in result["message"].lower()

    def test_cleanup_always_runs(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Release lock happens even on errors (never leaves main)."""
        registry = tmp_path / "AIPASS_REGISTRY.json"
        registry.write_text("{}", encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        release_mock = MagicMock(return_value={"success": True, "message": "ok"})

        with patch("aipass.drone.apps.handlers.git.pr_handler.subprocess.run", side_effect=_run_cleanup_early_exit):
            with patch(
                "aipass.drone.apps.handlers.git.pr_handler.acquire_lock",
                return_value={"success": True, "message": "ok"},
            ):
                with patch("aipass.drone.apps.handlers.git.pr_handler.release_lock", release_mock):
                    result = create_pr("api", "test desc", tmp_path / "src" / "aipass" / "api")

        assert result["success"] is False
        # Lock must always be released, even on early exit
        release_mock.assert_called_once_with(force=True)

    def test_commit_uses_pathspec_not_whole_index(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Commit is scoped to branch_dir — pre-staged files outside it are excluded.

        Regression test for FPLAN-0190: concurrent drone @git pr calls could
        contaminate each other's commits because git commit with no pathspec
        commits the entire index, not just files staged in this invocation.
        """
        registry = tmp_path / "AIPASS_REGISTRY.json"
        registry.write_text("{}", encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        with patch(
            "aipass.drone.apps.handlers.git.pr_handler.subprocess.run", side_effect=_run_with_staged
        ) as mock_run:
            with patch(
                "aipass.drone.apps.handlers.git.pr_handler.acquire_lock",
                return_value={"success": True, "message": "ok"},
            ):
                with patch("aipass.drone.apps.handlers.git.pr_handler.release_lock"):
                    create_pr("api", "test desc", tmp_path / "src" / "aipass" / "api")

        # The commit command must include '--' separator + pathspec to scope to branch_dir
        commit_calls = [
            c.args[0] for c in mock_run.call_args_list if c.args and c.args[0][0] == "git" and c.args[0][1] == "commit"
        ]
        assert commit_calls, "commit was never called"
        commit_cmd = commit_calls[0]
        assert "--" in commit_cmd, "commit missing '--' pathspec separator"
        pathspec_idx = commit_cmd.index("--")
        pathspec = commit_cmd[pathspec_idx + 1]
        assert "src/aipass/api" in pathspec.replace(os.sep, "/"), f"pathspec should target branch_dir, got: {pathspec}"


class TestDiagnosePushFailure:
    """Tests for _has_credential_helper and _diagnose_push_failure."""

    def test_has_credential_helper_true(self) -> None:
        """Returns True when git credential.helper is configured."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "store\n"
        with patch("aipass.drone.apps.handlers.git.pr_handler.subprocess.run", return_value=mock_result):
            assert _has_credential_helper() is True

    def test_has_credential_helper_false_no_config(self) -> None:
        """Returns False when git config returns non-zero (no helper set)."""
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        with patch("aipass.drone.apps.handlers.git.pr_handler.subprocess.run", return_value=mock_result):
            assert _has_credential_helper() is False

    def test_has_credential_helper_false_empty_stdout(self) -> None:
        """Returns False when git config returns 0 but stdout is whitespace-only."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "   \n"
        with patch("aipass.drone.apps.handlers.git.pr_handler.subprocess.run", return_value=mock_result):
            assert _has_credential_helper() is False

    def test_has_credential_helper_oserror(self) -> None:
        """Returns False when subprocess raises OSError."""
        with patch(
            "aipass.drone.apps.handlers.git.pr_handler.subprocess.run",
            side_effect=OSError("git not found"),
        ):
            assert _has_credential_helper() is False

    def test_diagnose_no_credential_helper(self) -> None:
        """Suggests gh auth setup-git when no credential helper is configured."""
        with patch("aipass.drone.apps.handlers.git.pr_handler._has_credential_helper", return_value=False):
            msg = _diagnose_push_failure("fatal: could not read Username", "feat/test")
        assert "no git credential helper configured" in msg.lower()
        assert "gh auth setup-git" in msg

    def test_diagnose_auth_error_403(self) -> None:
        """Identifies 403 as an authentication/token error."""
        with patch("aipass.drone.apps.handlers.git.pr_handler._has_credential_helper", return_value=True):
            msg = _diagnose_push_failure("The requested URL returned error: 403", "feat/test")
        assert "authentication error" in msg.lower()
        assert "gh auth login" in msg

    def test_diagnose_auth_error_terminal_prompts(self) -> None:
        """Identifies terminal prompts disabled as an auth error."""
        with patch("aipass.drone.apps.handlers.git.pr_handler._has_credential_helper", return_value=True):
            msg = _diagnose_push_failure("terminal prompts disabled", "feat/test")
        assert "authentication error" in msg.lower()

    def test_diagnose_permission_denied(self) -> None:
        """Identifies permission denied as a repo access issue."""
        with patch("aipass.drone.apps.handlers.git.pr_handler._has_credential_helper", return_value=True):
            msg = _diagnose_push_failure("Permission denied to AIOSAI/repo", "feat/test")
        assert "permission denied" in msg.lower()
        assert "feat/test" in msg

    def test_diagnose_unknown_error_passthrough(self) -> None:
        """Passes through unrecognized errors with stderr content."""
        with patch("aipass.drone.apps.handlers.git.pr_handler._has_credential_helper", return_value=True):
            msg = _diagnose_push_failure("some unknown git error", "feat/test")
        assert msg == "Push failed: some unknown git error"

    def test_diagnose_credential_check_takes_priority(self) -> None:
        """No credential helper is checked first, even if stderr also matches auth indicators."""
        with patch("aipass.drone.apps.handlers.git.pr_handler._has_credential_helper", return_value=False):
            msg = _diagnose_push_failure("403 forbidden", "feat/test")
        assert "credential helper" in msg.lower()
        assert "403" not in msg


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


class TestDetectBranchDir:
    """Branch directory detection tests."""

    def test_detects_branch_from_passport(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Detects branch name and dir by walking up to .trinity/passport.json."""
        # Create a fake branch directory with passport
        branch_dir = tmp_path / "mybranch"
        trinity = branch_dir / ".trinity"
        trinity.mkdir(parents=True)
        passport = trinity / "passport.json"
        passport.write_text(
            json.dumps(
                {
                    "branch_info": {"branch_name": "mybranch"},
                }
            )
        )

        # CWD is inside a subdirectory of the branch
        sub_dir = branch_dir / "apps" / "modules"
        sub_dir.mkdir(parents=True)
        monkeypatch.chdir(sub_dir)

        detected = _detect_branch_dir()
        assert detected is not None
        name, bdir = detected
        assert name == "mybranch"
        assert bdir == branch_dir.resolve()

    def test_returns_none_for_unrecognized_path(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Returns None when CWD has no .trinity/passport.json above it."""
        monkeypatch.chdir(tmp_path)
        detected = _detect_branch_dir()
        assert detected is None

    def test_detects_non_aipass_branch(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Detects branches outside src/aipass/ (e.g. commons, skills)."""
        branch_dir = tmp_path / "src" / "commons"
        trinity = branch_dir / ".trinity"
        trinity.mkdir(parents=True)
        passport = trinity / "passport.json"
        passport.write_text(
            json.dumps(
                {
                    "branch_info": {"branch_name": "commons"},
                }
            )
        )

        monkeypatch.chdir(branch_dir)

        detected = _detect_branch_dir()
        assert detected is not None
        name, bdir = detected
        assert name == "commons"
        assert bdir == branch_dir.resolve()


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
        """git module is registered in _INTERNAL_MODULES."""
        from aipass.drone.apps.handlers.module_registry_handler import _INTERNAL_MODULES

        assert "git" in _INTERNAL_MODULES
        assert _INTERNAL_MODULES["git"] == "aipass.drone.apps.modules.git_module"

    def test_module_importable(self) -> None:
        """The registered module path is importable."""
        import importlib

        mod = importlib.import_module("aipass.drone.apps.modules.git_module")
        assert hasattr(mod, "DRONE_MODULE")
        assert hasattr(mod, "handle_command")
        assert hasattr(mod, "get_help")
        assert hasattr(mod, "get_introspective")


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
        # Pin module identity: create_pr lazily does `from ...core import trigger`,
        # which resolves via sys.modules — patch through the file-top module object
        # and pin that same object into sys.modules so both paths agree even if an
        # earlier test on this worker disturbed trigger's module state.
        monkeypatch.setitem(sys.modules, "aipass.trigger.apps.modules.core", trigger_core)
        monkeypatch.setattr(trigger_core, "trigger", mock_trigger)

        with patch("aipass.drone.apps.handlers.git.pr_handler.subprocess.run", side_effect=_run_pr_created_success):
            with patch(
                "aipass.drone.apps.handlers.git.pr_handler.acquire_lock",
                return_value={"success": True, "message": "ok"},
            ):
                with patch("aipass.drone.apps.handlers.git.pr_handler.release_lock"):
                    result = create_pr("api", "test trigger", tmp_path / "src" / "aipass" / "api")

        assert result["success"] is True
        mock_trigger.fire.assert_any_call("pr_created", branch="api", pr_url="https://github.com/org/repo/pull/99")

    def test_pr_handler_continues_if_trigger_fails(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """pr_handler.create_pr succeeds even if trigger.fire raises."""
        registry = tmp_path / "AIPASS_REGISTRY.json"
        registry.write_text("{}", encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        mock_trigger = MagicMock()
        mock_trigger.fire.side_effect = RuntimeError("trigger broken")
        monkeypatch.setitem(sys.modules, "aipass.trigger.apps.modules.core", trigger_core)
        monkeypatch.setattr(trigger_core, "trigger", mock_trigger)

        with patch("aipass.drone.apps.handlers.git.pr_handler.subprocess.run", side_effect=_run_pr_trigger_resilience):
            with patch(
                "aipass.drone.apps.handlers.git.pr_handler.acquire_lock",
                return_value={"success": True, "message": "ok"},
            ):
                with patch("aipass.drone.apps.handlers.git.pr_handler.release_lock"):
                    result = create_pr("api", "test resilience", tmp_path / "src" / "aipass" / "api")

        assert result["success"] is True  # PR still succeeds despite trigger failure

    def test_merge_plugin_fires_pr_merged(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """merge_plugin.merge_pr fires pr_merged event on success."""
        from aipass.drone.apps.plugins.devpulse_ops.merge_plugin import merge_pr

        registry = tmp_path / "AIPASS_REGISTRY.json"
        registry.write_text("{}", encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        mock_trigger = MagicMock()
        monkeypatch.setitem(sys.modules, "aipass.trigger.apps.modules.core", trigger_core)
        monkeypatch.setattr(trigger_core, "trigger", mock_trigger)

        with patch(
            "aipass.drone.apps.plugins.devpulse_ops.merge_plugin.subprocess.run", side_effect=_run_merge_success
        ):
            result = merge_pr("42", "devpulse")

        assert result["success"] is True
        mock_trigger.fire.assert_any_call("pr_merged", pr_number="42", title="Fix the thing")


# ===========================================================================
# Fix 1 & 2: Protected-branch merge + return-to-dev (#625)
# ===========================================================================

_MERGE_MOD = "aipass.drone.apps.plugins.devpulse_ops.merge_plugin"


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

    def test_dev_head_no_delete_branch(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """When PR head is dev, merge command must NOT include --delete-branch."""
        from aipass.drone.apps.plugins.devpulse_ops.merge_plugin import merge_pr

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

    def test_temp_branch_has_delete_branch(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """When PR head is a temp branch, merge command includes --delete-branch."""
        from aipass.drone.apps.plugins.devpulse_ops.merge_plugin import merge_pr

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

    def test_unknown_head_ref_fails_safe_no_delete(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """When the PR head ref can't be determined (empty), fail SAFE: never delete.

        Guards the exact path that destroyed `dev` in S183 — if gh can't report
        the head ref we must not fall back to deleting the branch.
        """
        from aipass.drone.apps.plugins.devpulse_ops.merge_plugin import merge_pr

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


class TestMergeReturnToDev:
    """Fix 2: After merge+sync, checkout dev (or warn if can't)."""

    def test_checkout_dev_after_merge(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """merge_pr issues 'git checkout dev' when not already on dev."""
        from aipass.drone.apps.plugins.devpulse_ops.merge_plugin import merge_pr

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

    def test_no_checkout_when_already_on_dev(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """merge_pr skips checkout dev when already on dev."""
        from aipass.drone.apps.plugins.devpulse_ops.merge_plugin import merge_pr

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


# ===========================================================================
# Fix 3: Live-remote branches — fetch --prune before listing (#625)
# ===========================================================================

_BRANCHES_MOD = "aipass.drone.apps.handlers.git.branches_handler"


class TestBranchesFetchPrune:
    """Fix 3: list_remote_branches runs fetch --prune before git branch -r."""

    def test_fetch_prune_before_list(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """fetch --prune is called before git branch -r."""
        from aipass.drone.apps.handlers.git.branches_handler import list_remote_branches

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
        from aipass.drone.apps.handlers.git.branches_handler import list_remote_branches

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
        from aipass.drone.apps.handlers.git.branches_handler import list_remote_branches

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
        from aipass.drone.apps.handlers.git.branches_handler import prune_temp_branches

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
        from aipass.drone.apps.handlers.git.branches_handler import prune_temp_branches

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
            with patch(f"{_GIT_MOD}.sys.stdin") as mock_stdin:
                mock_stdin.isatty.return_value = False
                result = handle_command("merge", ["123"])

        assert result["exit_code"] == 1
        assert "requires explicit confirmation" in result["stderr"]
        assert "--confirm" in result["stderr"]
        mock_merge.assert_not_called()

    @patch(_AUTH, return_value="devpulse")
    def test_confirm_flag_proceeds(self, _mock_auth: MagicMock) -> None:
        """--confirm merges without prompting, even headless."""
        with patch(_MERGE_PR, return_value=dict(_MERGE_OK)) as mock_merge:
            with patch(f"{_GIT_MOD}.sys.stdin") as mock_stdin:
                mock_stdin.isatty.return_value = False
                result = handle_command("merge", ["123", "--confirm"])

        assert result["exit_code"] == 0
        mock_merge.assert_called_once_with("123", "devpulse")

    @patch(_AUTH, return_value="devpulse")
    def test_confirm_flag_position_agnostic(self, _mock_auth: MagicMock) -> None:
        """--confirm before the PR number still resolves the right PR."""
        with patch(_MERGE_PR, return_value=dict(_MERGE_OK)) as mock_merge:
            with patch(f"{_GIT_MOD}.sys.stdin") as mock_stdin:
                mock_stdin.isatty.return_value = False
                result = handle_command("merge", ["--confirm", "123"])

        assert result["exit_code"] == 0
        mock_merge.assert_called_once_with("123", "devpulse")

    @patch(_AUTH, return_value="devpulse")
    def test_tty_yes_proceeds(self, _mock_auth: MagicMock) -> None:
        """Interactive terminal answering y merges."""
        with patch(_MERGE_PR, return_value=dict(_MERGE_OK)) as mock_merge:
            with patch(f"{_GIT_MOD}.sys.stdin") as mock_stdin:
                mock_stdin.isatty.return_value = True
                with patch("builtins.input", return_value="y"):
                    result = handle_command("merge", ["123"])

        assert result["exit_code"] == 0
        mock_merge.assert_called_once_with("123", "devpulse")

    @patch(_AUTH, return_value="devpulse")
    def test_tty_default_aborts(self, _mock_auth: MagicMock) -> None:
        """Interactive terminal hitting enter (default N) aborts."""
        with patch(_MERGE_PR) as mock_merge:
            with patch(f"{_GIT_MOD}.sys.stdin") as mock_stdin:
                mock_stdin.isatty.return_value = True
                with patch("builtins.input", return_value=""):
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
