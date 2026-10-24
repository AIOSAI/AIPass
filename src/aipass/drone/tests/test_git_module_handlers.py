# =================== AIPass ====================
# Name: test_git_module_handlers.py
# Description: Tests for the handlers @git drives — lock, repo root, status, sync and PR
# Version: 1.0.1
# Created: 2026-10-08
# Modified: 2026-10-24
# =============================================

"""Tests for the lock, status, sync and PR handlers under apps/handlers/git/ that apps/modules/git_module.py drives."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(stdlib) — subprocess.run, which every git and gh call here reaches as a recorded stub

from __future__ import annotations

import json
import os
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
