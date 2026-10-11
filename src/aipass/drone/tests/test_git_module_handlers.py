# =================== AIPass ====================
# Name: test_git_module_handlers.py
# Description: Tests for the handlers @git drives — lock, repo root, status, sync and PR
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-08
# =============================================

"""Tests for the lock, status, sync and PR handlers under apps/handlers/git/ that apps/modules/git_module.py drives."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(stdlib) — subprocess.run, which every git and gh call here reaches as a recorded stub

from __future__ import annotations

import json
import os
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
from aipass.drone.apps.handlers.git.sync_handler import sync_main, sync_main_ref
from aipass.drone.apps.handlers.git.commit_handler import SUBJECT_CAP
from aipass.drone.apps.handlers.git.pr_handler import create_pr
from aipass.drone.tests.support_git_module import _done
from aipass.trigger.apps.modules import core as trigger_core


# ===========================================================================
# Fixtures
# ===========================================================================


_CREATE_EXCLUSIVE = "aipass.drone.apps.handlers.git.lock_handler._create_exclusive"


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

    @staticmethod
    def _deny_lock_create(attempts: list[str]):
        """A lock_handler._create_exclusive that answers the way Windows does for
        a lock another process is mid-removing (delete pending): ACCESS DENIED,
        not FILE EXISTS. Only the lock's own create is replaced — no os.open."""

        def fake_create(path: str) -> int:
            attempts.append(path)
            raise PermissionError(13, "Permission denied", path)

        return fake_create

    def test_a_create_denied_mid_release_answers_blocked_not_an_exception(self, lock_dir: Path) -> None:
        """The Windows race: a release in flight denies the acquire's create.

        It used to escape acquire_lock as an uncaught PermissionError, out of the
        door every PR crosses. It answers blocked instead, once — the door never
        waits — and names the denial, so a repo root that is truly unwritable
        still surfaces rather than passing for a busy lock.

        Mutant (runner): acquire_lock calls os.open directly instead of the
        _create_exclusive seam — the real create succeeds, the test sees success.
        """
        attempts: list[str] = []
        with patch(_CREATE_EXCLUSIVE, new=self._deny_lock_create(attempts)):
            result = acquire_lock("@memory")

        assert result["success"] is False
        assert result["message"].startswith("Lock blocked:")
        assert "retry" in result["message"]
        assert "Permission denied" in result["message"]
        assert len(attempts) == 1
        assert not (lock_dir / ".git_pr.lock").exists()

    def test_a_create_denied_names_the_holder_when_the_lock_still_reads(self, lock_dir: Path) -> None:
        """A denied create against a lock file that still reads is that holder's
        lock: the same blocked answer the FileExistsError arm gives.

        Mutant (runner): acquire_lock calls os.open directly instead of the
        _create_exclusive seam — the create is never the one denied (attempts == 0).
        """
        (lock_dir / ".git_pr.lock").write_text(json.dumps({"branch": "@api", "pid": 1}), encoding="utf-8")
        attempts: list[str] = []
        with patch(_CREATE_EXCLUSIVE, new=self._deny_lock_create(attempts)):
            result = acquire_lock("@memory")

        assert result == {"success": False, "message": "Lock blocked: already held by @api"}
        assert len(attempts) == 1


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

    def test_finds_registry_file(self, lock_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Finds repo root by walking up to AIPASS_REGISTRY.json."""
        subdir = lock_dir / "a" / "b" / "c"
        subdir.mkdir(parents=True)
        monkeypatch.chdir(subdir)
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
        # The handler's own line, carrying git's stderr verbatim. Both clauses of
        # the `or` this replaces held: the first on the handler's prefix, the
        # second on the stderr this test wrote itself.
        assert result["message"] == "Failed to checkout main: error: Your local changes would be overwritten"

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
        # The refusal in full, including the door it points at. Both clauses of
        # the `or` this replaces held.
        assert result["message"] == (
            "Dev has diverged from main — cannot fast-forward. Use 'drone @git fix' to resolve."
        )

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
                with patch("aipass.drone.apps.handlers.git.pr_handler.release_lock") as mock_release:
                    result = create_pr("api", "test desc", tmp_path / "src" / "aipass" / "api")

        assert result["success"] is False
        assert "nothing to commit" in result["message"].lower()
        mock_release.assert_called_once_with(force=True)

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

        Regression test for FPLAN-0190: concurrent drone @git pr calls could contaminate
        each other's commits, because git commit with no pathspec commits the entire
        shared index, not just the files staged in this invocation.

        Mutant: pathspec `str(rel_dir) + "/.."` at pr_handler.py:211 — the commit escapes branch_dir.
        """
        registry = tmp_path / "AIPASS_REGISTRY.json"
        registry.write_text("{}", encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        mock_trigger = MagicMock()
        monkeypatch.setattr(trigger_core, "trigger", mock_trigger)

        with patch(
            "aipass.drone.apps.handlers.git.pr_handler.subprocess.run", side_effect=_run_with_staged
        ) as mock_run:
            with patch(
                "aipass.drone.apps.handlers.git.pr_handler.acquire_lock",
                return_value={"success": True, "message": "ok"},
            ):
                with patch("aipass.drone.apps.handlers.git.pr_handler.release_lock") as mock_release:
                    create_pr("api", "test desc", tmp_path / "src" / "aipass" / "api")

        commit_calls = [
            c.args[0] for c in mock_run.call_args_list if c.args and c.args[0][0] == "git" and c.args[0][1] == "commit"
        ]
        # One commit, and its argv ends in the '--' separator plus the branch dir alone.
        assert [cmd[-2:] for cmd in commit_calls] == [["--", str(Path("src/aipass/api")) + "/"]]
        mock_release.assert_called_once_with(force=True)
        mock_trigger.fire.assert_called_once_with(
            "pr_created", branch="api", pr_url="https://github.com/test/repo/pull/1"
        )

    def test_essay_description_refused_before_the_lock(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """A PR commit lands in the same oneline log, so it obeys the same cap.

        The refusal comes before acquire_lock: a refused subject that has taken
        the repo-wide PR lock blocks every other citizen while it teaches.
        """
        registry = tmp_path / "AIPASS_REGISTRY.json"
        registry.write_text("{}", encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        essay = "x" * (SUBJECT_CAP + 1)
        lock_mock = MagicMock(return_value={"success": True, "message": ""})

        with (
            patch("aipass.drone.apps.handlers.git.pr_handler.subprocess.run") as mock_run,
            patch("aipass.drone.apps.handlers.git.pr_handler.acquire_lock", lock_mock),
        ):
            result = create_pr("api", essay, tmp_path / "src" / "aipass" / "api")

        assert result["success"] is False
        assert str(SUBJECT_CAP) in result["message"]
        assert lock_mock.call_count == 0, "a refused subject must not take the PR lock"
        assert mock_run.call_count == 0

    def test_short_description_reaches_the_lock(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """The cap refuses essays only — a normal description walks straight past it."""
        registry = tmp_path / "AIPASS_REGISTRY.json"
        registry.write_text("{}", encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        lock_mock = MagicMock(return_value={"success": False, "message": "Lock blocked: already held by @memory"})

        with (
            patch("aipass.drone.apps.handlers.git.pr_handler.subprocess.run", side_effect=_run_nothing_staged),
            patch("aipass.drone.apps.handlers.git.pr_handler.acquire_lock", lock_mock),
        ):
            result = create_pr("api", "the subject cap refusal", tmp_path / "src" / "aipass" / "api")

        assert lock_mock.call_count == 1
        assert "blocked" in result["message"].lower()


def _pr_push_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, push_stderr: str, helper: MagicMock | Exception
) -> tuple[str, str]:
    """Run create_pr to a refused push; answer `git config credential.helper` with *helper*.

    Every git and gh call goes to a recording stub; the lock is a recorder too.
    Returns the PR's message and the feature branch the push named.
    """
    (tmp_path / "AIPASS_REGISTRY.json").write_text("{}", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    calls: list[list[str]] = []

    def _run(cmd: list[str], **_kwargs: object) -> MagicMock:
        calls.append(list(cmd))
        if cmd[:3] == ["git", "config", "--get-all"]:
            if isinstance(helper, Exception):
                raise helper
            return helper
        if cmd[1:3] == ["rev-parse", "--abbrev-ref"]:
            return _done("main\n")
        if cmd[1:3] == ["diff", "--cached"]:
            return _done(returncode=1)
        if cmd[1:2] == ["push"]:
            return _done(returncode=1, stderr=push_stderr)
        return _done()

    with (
        patch("aipass.drone.apps.handlers.git.pr_handler.subprocess.run", side_effect=_run),
        patch(
            "aipass.drone.apps.handlers.git.pr_handler.acquire_lock",
            return_value={"success": True, "message": "ok"},
        ),
        patch("aipass.drone.apps.handlers.git.pr_handler.release_lock") as mock_release,
    ):
        result = create_pr("api", "test desc", tmp_path / "src" / "aipass" / "api")

    mock_release.assert_called_once_with(force=True)
    assert result["success"] is False
    pushes = [cmd for cmd in calls if cmd[1:2] == ["push"]]
    assert len(pushes) == 1
    assert not any(cmd[:2] == ["gh", "pr"] for cmd in calls), "a refused push must not open a PR"
    return result["message"], pushes[0][-1]


_NO_HELPER = "Push failed: no git credential helper configured."
_AUTH_ERROR = "Push failed: authentication error"


class TestDiagnosePushFailure:
    """A refused push, diagnosed through create_pr: the credential helper first, then the stderr."""

    def test_has_credential_helper_true(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Mutant: _has_credential_helper returns False — a configured helper is reported missing."""
        msg, _ = _pr_push_failure(tmp_path, monkeypatch, "fatal: could not read Username", _done("store\n"))
        assert msg.startswith(_AUTH_ERROR)

    def test_has_credential_helper_false_no_config(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Mutant: the returncode check dropped — a failing `git config` with output counts as a helper."""
        msg, _ = _pr_push_failure(tmp_path, monkeypatch, "403", _done("store\n", returncode=1))
        assert msg.startswith(_NO_HELPER)

    def test_has_credential_helper_false_empty_stdout(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Mutant: stdout not stripped — whitespace-only output counts as a helper."""
        msg, _ = _pr_push_failure(tmp_path, monkeypatch, "403", _done("   \n"))
        assert msg.startswith(_NO_HELPER)

    def test_has_credential_helper_oserror(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Mutant: the OSError handler answers True — an unrunnable git counts as a helper."""
        msg, _ = _pr_push_failure(tmp_path, monkeypatch, "403", OSError("git not found"))
        assert msg.startswith(_NO_HELPER)

    def test_diagnose_no_credential_helper(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Suggests gh auth setup-git when no credential helper is configured."""
        msg, _ = _pr_push_failure(tmp_path, monkeypatch, "fatal: could not read Username", _done(returncode=1))
        assert "no git credential helper configured" in msg.lower()
        assert "gh auth setup-git" in msg

    def test_diagnose_auth_error_403(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Identifies 403 as an authentication/token error."""
        msg, _ = _pr_push_failure(tmp_path, monkeypatch, "The requested URL returned error: 403", _done("store\n"))
        assert "authentication error" in msg.lower()
        assert "gh auth login" in msg

    def test_diagnose_auth_error_terminal_prompts(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Mutant: "terminal prompts disabled" dropped from auth_indicators — read as a plain failure."""
        msg, _ = _pr_push_failure(tmp_path, monkeypatch, "terminal prompts disabled", _done("store\n"))
        assert msg.startswith(_AUTH_ERROR)

    def test_diagnose_permission_denied(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Permission denied is diagnosed as a repo access issue, naming the refused branch.

        Mutant: the message names `branch` as "" — the refused branch is not named.
        """
        msg, feature_branch = _pr_push_failure(
            tmp_path, monkeypatch, "Permission denied to AIOSAI/repo", _done("store\n")
        )
        assert "permission denied" in msg.lower()
        assert f"branch '{feature_branch}'" in msg

    def test_diagnose_unknown_error_passthrough(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Passes through unrecognized errors with stderr content."""
        msg, _ = _pr_push_failure(tmp_path, monkeypatch, "some unknown git error", _done("store\n"))
        assert msg == "Push failed: some unknown git error"

    def test_diagnose_credential_check_takes_priority(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """No credential helper is checked first, even if stderr also matches auth indicators."""
        msg, _ = _pr_push_failure(tmp_path, monkeypatch, "403 forbidden", _done(returncode=1))
        assert "credential helper" in msg.lower()
        assert "403" not in msg
