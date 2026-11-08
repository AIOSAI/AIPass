# =================== AIPass ====================
# Name: test_git_module_handlers.py
# Description: Tests for the handlers @git drives — lock, repo root, status, sync, PR, remote set, uncommit and init
# Version: 1.3.0
# Created: 2026-10-08
# Modified: 2026-11-08
# =============================================

"""Tests for the lock, status, sync, PR, remote, uncommit and init handlers that apps/modules/git_module.py drives."""

# The declared pass — what is NOT tested here, and what covers it instead:
# sentry: no-test-needed(stdlib) — subprocess.run, which every git and gh call here reaches as a recorded stub

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from aipass.drone.apps.handlers.git.lock_handler import (
    check_lock_status,
    find_repo_root,
    force_unlock,
    release_lock,
)
from aipass.drone.apps.handlers.git.status_handler import get_branch_status
from aipass.drone.apps.handlers.git.sync_handler import sync_main, sync_main_ref
from aipass.drone.apps.handlers.git import init_handler, remote_handler, repo_door
from aipass.drone.apps.modules.git_module import handle_command

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


def _hold_lock(lock_dir: Path, branch: str) -> None:
    """Leave the lock file a holder in this process would leave."""
    data = {"branch": branch, "started": datetime.now(timezone.utc).isoformat(), "pid": os.getpid()}
    (lock_dir / ".git_pr.lock").write_text(json.dumps(data), encoding="utf-8")


# ===========================================================================
# 1. lock_handler — release / status / stale / orphan
# ===========================================================================


class TestLockRelease:
    """Lock release tests."""

    def test_release_own_lock(self, lock_dir: Path) -> None:
        """Releasing a lock held by the current PID succeeds."""
        _hold_lock(lock_dir, "@api")
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
        _hold_lock(lock_dir, "@api")
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
        _hold_lock(lock_dir, "@api")
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
        _hold_lock(lock_dir, "@drone")
        result = check_lock_status()
        assert result["locked"] is True
        assert result["branch"] == "@drone"
        assert result["pid"] == os.getpid()
        assert result["orphaned"] is False

    def test_stale_detection(self, lock_dir: Path) -> None:
        """Lock older than threshold is detected as stale."""
        _hold_lock(lock_dir, "@api")
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
        _hold_lock(lock_dir, "@api")
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
        _hold_lock(lock_dir, "@api")
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

    @pytest.mark.parametrize("branch", ["dev", "main"])
    def test_failed_stash_stops_before_any_pop(
        self, branch: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A stash that failed (index.lock held) stops the sync; no pop can apply an older stash."""
        (tmp_path / "AIPASS_REGISTRY.json").write_text("{}", encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        mock_head = MagicMock(returncode=0, stdout=branch, stderr="")
        mock_stash = MagicMock(returncode=128, stdout="", stderr="fatal: Unable to create '.git/index.lock'")
        with patch(
            "aipass.drone.apps.handlers.git.sync_handler.subprocess.run",
            side_effect=[mock_head, mock_stash],
        ) as mock_run:
            result = sync_main(autostash=True)

        assert result["success"] is False
        assert "git stash failed" in result["message"]
        assert len(mock_run.call_args_list) == 2

    @pytest.mark.parametrize(
        ("branch", "runs"),
        [
            ("dev", ["head", "stash", "fetch", "merge", "pop"]),
            ("main", ["head", "stash", "fetch", "rev", "pull", "pop"]),
        ],
    )
    def test_failed_pop_is_a_failure(
        self, branch: str, runs: list[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A pop that conflicts reports failure and where the changes are, never 'Synced'."""
        (tmp_path / "AIPASS_REGISTRY.json").write_text("{}", encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        answers = {
            "head": MagicMock(returncode=0, stdout=branch, stderr=""),
            "stash": MagicMock(returncode=0, stdout="Saved working directory", stderr=""),
            "fetch": MagicMock(returncode=0, stdout="", stderr=""),
            "merge": MagicMock(returncode=0, stdout="Fast-forward", stderr=""),
            "rev": MagicMock(returncode=0, stdout="0\t1\n", stderr=""),
            "pull": MagicMock(returncode=0, stdout="Updated", stderr=""),
            "pop": MagicMock(returncode=1, stdout="", stderr="CONFLICT (content)"),
        }
        with patch(
            "aipass.drone.apps.handlers.git.sync_handler.subprocess.run",
            side_effect=[answers[r] for r in runs],
        ):
            result = sync_main(autostash=True)

        assert result["success"] is False
        assert "stash@{0}" in result["message"]


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


def _git(repo: Path, *argv: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *argv], cwd=repo, capture_output=True, text=True, encoding="utf-8")


def _remote_ledger(tmp_path: Path) -> list[dict]:
    path = tmp_path / remote_handler.LEDGER_NAME
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


@pytest.fixture()
def seed_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An external project's git repo with SEED's manager seat at its root, standing in it; git sees no host config."""
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "gitconfig"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    for name in ("GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL"):
        monkeypatch.setenv(name, "seed@test.invalid")
    root = make_owner_project(tmp_path / "seed", branch="SEED", registry_name="SEED_REGISTRY.json")
    _git(root, "init", "-q", "-b", "main")
    monkeypatch.chdir(root)
    return root


_SEED = "https://github.com/AIOSAI/SEED.git"


class TestRemoteSet:
    """remote set points a remote at a github.com repo, owner tier, and records the change."""

    def test_a_missing_remote_is_added_and_the_change_is_recorded(self, seed_repo: Path, tmp_path: Path) -> None:
        """Mutant: set-url used when the remote is absent — git refuses 'No such remote'."""
        result = handle_command("remote", ["set", "origin", _SEED])

        assert result["exit_code"] == 0, result["stderr"]
        assert "(none) -> " + _SEED in result["stdout"]
        assert _git(seed_repo, "remote", "get-url", "origin").stdout.strip() == _SEED
        [record] = _remote_ledger(tmp_path)
        assert (record["caller"], record["name"], record["old"], record["new"], record["outcome"]) == (
            "SEED",
            "origin",
            "",
            _SEED,
            "set",
        )

    def test_an_existing_remote_is_re_pointed_and_the_old_url_is_recorded(
        self, seed_repo: Path, tmp_path: Path
    ) -> None:
        old = "https://github.com/AIOSAI/hark.git"
        _git(seed_repo, "remote", "add", "origin", old)

        result = handle_command("remote", ["set", "origin", "git@github.com:AIOSAI/SEED.git"])

        assert result["exit_code"] == 0, result["stderr"]
        assert _git(seed_repo, "remote", "get-url", "origin").stdout.strip() == "git@github.com:AIOSAI/SEED.git"
        assert _remote_ledger(tmp_path)[0]["old"] == old

    def test_the_same_url_again_is_reported_unchanged(self, seed_repo: Path, tmp_path: Path) -> None:
        _git(seed_repo, "remote", "add", "origin", _SEED)

        result = handle_command("remote", ["set", "origin", _SEED])

        assert result["exit_code"] == 0
        assert "already points at" in result["stdout"]
        assert _remote_ledger(tmp_path)[0]["outcome"] == "unchanged"

    @pytest.mark.parametrize(
        "url",
        [
            "http://github.com/AIOSAI/SEED.git",
            "https://ghp_token@github.com/AIOSAI/SEED.git",
            "https://gitlab.com/AIOSAI/SEED.git",
            "git@github.com:AIOSAI",
            "https://github.com/AIOSAI/SEED/extra",
            "ssh://git@evil.example/AIOSAI/SEED.git",
        ],
    )
    def test_a_url_that_is_not_a_plain_github_repo_is_refused_and_nothing_changes(
        self, seed_repo: Path, tmp_path: Path, url: str
    ) -> None:
        """Mutant: the url check dropped — a token lands in .git/config in clear."""
        result = handle_command("remote", ["set", "origin", url])

        assert result["exit_code"] == 1
        assert result["stderr"] == remote_handler.REFUSE_URL
        assert _git(seed_repo, "remote").stdout.strip() == ""
        assert _remote_ledger(tmp_path) == []

    @pytest.mark.parametrize("args", [["-f", _SEED], ["origin"], ["origin", _SEED, "extra"]])
    def test_a_bad_name_or_arity_is_refused_before_git(self, seed_repo: Path, args: list[str]) -> None:
        result = handle_command("remote", ["set", *args])

        assert result["exit_code"] == 1
        assert result["stderr"].startswith(("remote set refused", "Usage: drone @git remote set"))
        assert _git(seed_repo, "remote").stdout.strip() == ""

    def test_a_seat_without_owner_tier_is_refused_and_listing_stays_global(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Mutant: remote set left on the global key — any citizen re-points origin."""
        root = make_owner_project(tmp_path / "seed", branch="scout", citizen_class="specialist")
        monkeypatch.chdir(root)

        refused = handle_command("remote", ["set", "origin", _SEED])

        assert refused["exit_code"] == 1
        assert "not authorized for 'remote-write'" in refused["stderr"]
        with patch("aipass.drone.apps.handlers.git.remote_handler.subprocess.run") as run:
            run.return_value = subprocess.CompletedProcess([], 0, stdout="", stderr="")
            assert handle_command("remote", [])["exit_code"] == 0

    def test_the_admin_door_sets_a_remote_in_another_repo(
        self, seed_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Mutant: remote off DOOR_VERBS — --repo refuses the verb."""
        ext = tmp_path / "ext"
        ext.mkdir()
        _git(ext, "init", "-q", "-b", "main")
        monkeypatch.setattr(repo_door, "admin_verdict", lambda: repo_door.AdminVerdict(True, "devpulse", ""))

        result = handle_command("remote", ["set", "origin", _SEED, "--repo", str(ext)])

        assert result["exit_code"] == 0, result["stderr"]
        assert _git(ext, "remote", "get-url", "origin").stdout.strip() == _SEED
        assert _git(seed_repo, "remote").stdout.strip() == ""
        assert _remote_ledger(tmp_path)[0]["caller"] == "devpulse"


def _head(repo: Path) -> str:
    return _git(repo, "log", "-1", "--format=%s").stdout.strip()


@pytest.fixture()
def unpushed(seed_repo: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """dev tracking origin/dev at 'base' (a.txt, c.txt), then two unpushed commits: 'test' edits a.txt, 'real' adds b.txt."""
    for name in ("GIT_AUTHOR_NAME", "GIT_COMMITTER_NAME"):
        monkeypatch.setenv(name, "Uncommit Test")
    for name, text in (("a.txt", "a one\n"), ("c.txt", "c one\n")):
        (seed_repo / name).write_text(text, encoding="utf-8")
    _git(seed_repo, "add", "a.txt", "c.txt")
    _git(seed_repo, "commit", "-q", "-m", "base")
    _git(seed_repo, "checkout", "-q", "-b", "dev")
    _git(seed_repo, "remote", "add", "origin", _SEED)
    _git(seed_repo, "update-ref", "refs/remotes/origin/dev", "HEAD")
    _git(seed_repo, "branch", "-q", "--set-upstream-to=origin/dev")
    (seed_repo / "a.txt").write_text("a two\n", encoding="utf-8")
    _git(seed_repo, "commit", "-q", "-am", "test")
    (seed_repo / "b.txt").write_text("b one\n", encoding="utf-8")
    _git(seed_repo, "add", "b.txt")
    _git(seed_repo, "commit", "-q", "-m", "real")
    return seed_repo


class TestUncommit:
    """uncommit un-records unpushed commits with a soft reset, and refuses every case a reset would hurt."""

    def test_two_commits_are_un_recorded_and_their_changes_stay_staged(self, unpushed: Path) -> None:
        """Mutant: --mixed instead of --soft — HEAD moves, but nothing is staged for the one re-commit."""
        result = handle_command("uncommit", ["2"])

        assert result["exit_code"] == 0, result["stderr"]
        assert _head(unpushed) == "base"
        assert _git(unpushed, "diff", "--cached", "--name-status").stdout.split() == ["M", "a.txt", "A", "b.txt"]
        assert "real" in result["stdout"].splitlines()[0] and "test" in result["stdout"].splitlines()[1]
        assert "2 commit(s) un-recorded; HEAD is now" in result["stdout"]

    def test_no_count_un_records_one(self, unpushed: Path) -> None:
        assert handle_command("uncommit", [])["exit_code"] == 0
        assert _head(unpushed) == "test"

    def test_a_pushed_commit_is_never_un_recorded(self, unpushed: Path) -> None:
        """Mutant: the upstream check dropped — the refusal is no longer the pushed commit's."""
        result = handle_command("uncommit", ["3"])

        assert result["exit_code"] == 1
        assert "base is already on origin/dev" in result["stderr"]
        assert _head(unpushed) == "real"

    def test_more_than_the_branch_holds_is_refused(self, unpushed: Path) -> None:
        """Mutant: the count check dropped — the reset itself fails past the root commit."""
        _git(
            unpushed,
            "update-ref",
            "refs/remotes/origin/dev",
            _git(unpushed, "commit-tree", "-m", "orphan", _git(unpushed, "write-tree").stdout.strip()).stdout.strip(),
        )

        result = handle_command("uncommit", ["4"])

        assert result["exit_code"] == 1
        assert "4 asked, but dev is 3 commit(s) ahead of origin/dev" in result["stderr"]
        assert _head(unpushed) == "real"

    def test_a_merge_commit_is_refused(self, unpushed: Path) -> None:
        """Mutant: the parent count unread — the merge is un-recorded and its side branch flattened."""
        _git(unpushed, "checkout", "-q", "-b", "side", "HEAD~1")
        (unpushed / "d.txt").write_text("d\n", encoding="utf-8")
        _git(unpushed, "add", "d.txt")
        _git(unpushed, "commit", "-q", "-m", "side work")
        _git(unpushed, "checkout", "-q", "dev")
        _git(unpushed, "merge", "-q", "--no-ff", "-m", "merge side", "side")

        result = handle_command("uncommit", ["1"])

        assert result["exit_code"] == 1
        assert "merge side is a merge commit" in result["stderr"]
        assert _head(unpushed) == "merge side"

    def test_unstaged_edits_to_a_touched_file_refuse_and_unrelated_ones_do_not(self, unpushed: Path) -> None:
        """Mutants: the check dropped (a.txt mixes in); every unstaged file refused (c.txt blocks)."""
        (unpushed / "c.txt").write_text("c mine\n", encoding="utf-8")
        (unpushed / "a.txt").write_text("a mine\n", encoding="utf-8")

        refused = handle_command("uncommit", ["2"])
        (unpushed / "a.txt").write_text("a two\n", encoding="utf-8")
        allowed = handle_command("uncommit", ["2"])

        assert refused["exit_code"] == 1
        assert "unstaged edits to a.txt, which the commits touch" in refused["stderr"]
        assert allowed["exit_code"] == 0, allowed["stderr"]
        assert (unpushed / "c.txt").read_text(encoding="utf-8") == "c mine\n"

    def test_a_branch_with_no_upstream_is_refused(self, unpushed: Path) -> None:
        _git(unpushed, "branch", "-q", "--unset-upstream")

        result = handle_command("uncommit", [])

        assert result["exit_code"] == 1
        assert "dev tracks no remote branch" in result["stderr"]
        assert _head(unpushed) == "real"

    @pytest.mark.parametrize("args", [["0"], ["two"], ["1", "2"], ["--hard"]])
    def test_anything_but_one_whole_count_is_refused(self, unpushed: Path, args: list[str]) -> None:
        result = handle_command("uncommit", args)

        assert result["exit_code"] == 1
        assert "There is no force or hard flag" in result["stderr"]
        assert _head(unpushed) == "real"

    def test_a_seat_without_owner_tier_is_refused(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Mutant: uncommit on the global tier — any citizen rewrites the branch tip."""
        root = make_owner_project(tmp_path / "seed", branch="scout", citizen_class="specialist")
        monkeypatch.chdir(root)

        result = handle_command("uncommit", [])

        assert result["exit_code"] == 1
        assert "not authorized for 'uncommit'" in result["stderr"]


def _door_ledger(tmp_path: Path) -> list[dict]:
    path = tmp_path / repo_door.LEDGER_NAME
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


@pytest.fixture()
def admin_door(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(repo_door, "admin_verdict", lambda: repo_door.AdminVerdict(True, "devpulse", ""))


class TestInitDoor:
    """init --repo makes a brand-new directory outside AIPass a repo on main, and nothing else."""

    def test_a_new_directory_becomes_an_empty_repo_on_main(self, seed_repo: Path, tmp_path: Path, admin_door) -> None:
        """Mutant: -b main dropped — git's own default (master here, no host config) names the branch."""
        seton = tmp_path / "seton"
        seton.mkdir()

        result = handle_command("init", ["--repo", str(seton)])

        assert result["exit_code"] == 0, result["stderr"]
        assert result["stdout"] == init_handler.INITIALIZED.format(path=seton.resolve())
        assert _git(seton, "symbolic-ref", "HEAD").stdout.strip() == "refs/heads/main"
        assert _git(seton, "remote").stdout.strip() == ""
        assert _git(seton, "rev-parse", "--verify", "-q", "HEAD").returncode != 0
        [record] = _door_ledger(tmp_path)
        assert (record["verb"], record["outcome"], record["caller"]) == ("init", "ran", "devpulse")

    def test_a_directory_that_already_holds_a_git_is_refused(self, seed_repo: Path, tmp_path: Path, admin_door) -> None:
        """Mutant: the .git check dropped — git re-initializes the repo and reports success."""
        seton = tmp_path / "seton"
        seton.mkdir()
        _git(seton, "init", "-q", "-b", "dev")

        result = handle_command("init", ["--repo", str(seton)])

        assert result["stderr"] == init_handler.REFUSE_HAS_GIT.format(path=str(seton))
        assert _door_ledger(tmp_path)[0]["outcome"] == "refused"

    def test_a_directory_inside_the_aipass_tree_is_refused(self, seed_repo: Path, admin_door) -> None:
        """Mutant: the AIPass check dropped — the refusal is the nested-repo one, not AIPass's."""
        inner = seed_repo / "newproj"
        inner.mkdir()

        result = handle_command("init", ["--repo", str(inner)])

        assert result["stderr"] == init_handler.REFUSE_IN_AIPASS.format(path=str(inner))
        assert not (inner / ".git").exists()

    def test_a_directory_inside_another_repo_is_refused(self, seed_repo: Path, tmp_path: Path, admin_door) -> None:
        """Mutant: the work-tree check dropped — a repo nests inside another."""
        other = tmp_path / "other"
        (other / "pkg").mkdir(parents=True)
        _git(other, "init", "-q", "-b", "main")

        result = handle_command("init", ["--repo", str(other / "pkg")])

        assert result["exit_code"] == 1
        assert "sits inside the git repository at" in result["stderr"]
        assert not (other / "pkg" / ".git").exists()

    @pytest.mark.parametrize(
        ("extra", "expected"),
        [(["main"], init_handler.REFUSE_ARGS), ([], repo_door.REFUSE_MISSING.format(path="{missing}"))],
    )
    def test_arguments_and_a_missing_directory_are_refused(
        self, seed_repo: Path, tmp_path: Path, admin_door, extra: list[str], expected: str
    ) -> None:
        missing = str(tmp_path / "nowhere")
        seton = tmp_path / "seton"
        seton.mkdir()
        target = missing if not extra else str(seton)

        result = handle_command("init", ["--repo", target, *extra])

        assert result["stderr"] == expected.replace("{missing}", missing)
        assert not (seton / ".git").exists()

    def test_a_seat_without_the_admin_grant_is_refused_before_the_path_is_read(
        self, seed_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Mutant: init dispatched before the WHO check — any seat creates repos."""
        monkeypatch.setattr(repo_door, "admin_verdict", lambda: repo_door.AdminVerdict(False, "scout", "not admin"))
        seton = tmp_path / "seton"
        seton.mkdir()

        result = handle_command("init", ["--repo", str(seton)])

        assert (result["exit_code"], result["stderr"]) == (1, "not admin")
        assert not (seton / ".git").exists()
