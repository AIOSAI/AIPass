"""Tests for the @git module — lock, status, sync, PR, and routing."""

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
from aipass.drone.apps.handlers.git.sync_handler import sync_main
from aipass.drone.apps.handlers.git.pr_handler import create_pr
from aipass.drone.apps.modules.git_module import (
    DRONE_MODULE,
    _detect_branch_dir,
    get_help,
    get_introspective,
    handle_command,
)


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

        mock_checkout = MagicMock()
        mock_checkout.returncode = 0
        mock_checkout.stdout = "Switched to branch 'main'"
        mock_checkout.stderr = ""

        mock_pull = MagicMock()
        mock_pull.returncode = 0
        mock_pull.stdout = "Already up to date."
        mock_pull.stderr = ""

        with patch(
            "aipass.drone.apps.handlers.git.sync_handler.subprocess.run",
            side_effect=[mock_checkout, mock_pull],
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

        mock_checkout = MagicMock()
        mock_checkout.returncode = 0
        mock_checkout.stdout = ""
        mock_checkout.stderr = ""

        mock_pull = MagicMock()
        mock_pull.returncode = 1
        mock_pull.stdout = ""
        mock_pull.stderr = "fatal: unable to access remote"

        with patch(
            "aipass.drone.apps.handlers.git.sync_handler.subprocess.run",
            side_effect=[mock_checkout, mock_pull],
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


# ===========================================================================
# 4. pr_handler — error paths (no actual git)
# ===========================================================================


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

        call_count = 0

        def mock_subprocess_run(cmd, **kwargs):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            result.stderr = ""
            result.stdout = ""

            if cmd[1:3] == ["rev-parse", "--abbrev-ref"]:
                result.returncode = 0
                result.stdout = "main\n"
            elif cmd[1:3] == ["checkout", "-b"]:
                result.returncode = 0
            elif cmd[0] == "git" and cmd[1] == "add":
                result.returncode = 0
            elif cmd[1:3] == ["diff", "--cached"]:
                result.returncode = 0  # 0 means nothing staged
            elif cmd[1] == "checkout" and cmd[2] == "main":
                result.returncode = 0
            elif cmd[1] == "pull":
                result.returncode = 0
            else:
                result.returncode = 0
            return result

        with patch("aipass.drone.apps.handlers.git.pr_handler.subprocess.run", side_effect=mock_subprocess_run):
            with patch("aipass.drone.apps.handlers.git.pr_handler.acquire_lock", return_value={"success": True, "message": "ok"}):
                with patch("aipass.drone.apps.handlers.git.pr_handler.release_lock"):
                    result = create_pr("api", "test desc", tmp_path / "src" / "aipass" / "api")

        assert result["success"] is False
        assert "nothing to commit" in result["message"].lower()

    def test_cleanup_always_runs(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Release lock happens even on errors (never leaves main)."""
        registry = tmp_path / "AIPASS_REGISTRY.json"
        registry.write_text("{}", encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        def mock_subprocess_run(cmd, **kwargs):
            result = MagicMock()
            result.stderr = ""
            result.stdout = ""

            if cmd[1:3] == ["rev-parse", "--abbrev-ref"]:
                result.returncode = 0
                result.stdout = "main\n"
            elif cmd[0] == "git" and cmd[1] == "add":
                result.returncode = 0
            elif cmd[1:3] == ["diff", "--cached"]:
                # Nothing staged — triggers early exit
                result.returncode = 0
            else:
                result.returncode = 0
            return result

        release_mock = MagicMock(return_value={"success": True, "message": "ok"})

        with patch("aipass.drone.apps.handlers.git.pr_handler.subprocess.run", side_effect=mock_subprocess_run):
            with patch(
                "aipass.drone.apps.handlers.git.pr_handler.acquire_lock",
                return_value={"success": True, "message": "ok"},
            ):
                with patch("aipass.drone.apps.handlers.git.pr_handler.release_lock", release_mock):
                    result = create_pr("api", "test desc", tmp_path / "src" / "aipass" / "api")

        assert result["success"] is False
        # Lock must always be released, even on early exit
        release_mock.assert_called_once_with(force=True)


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
        assert "pr" in result["stderr"]

    def test_lock_routes_to_handler(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """lock command routes to check_lock_status."""
        registry = tmp_path / "AIPASS_REGISTRY.json"
        registry.write_text("{}", encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        result = handle_command("lock")
        assert result["exit_code"] == 0
        data = json.loads(result["stdout"])
        assert data["locked"] is False

    def test_unlock_requires_force(self) -> None:
        """unlock without --force returns error."""
        result = handle_command("unlock")
        assert result["exit_code"] == 1
        assert "--force" in result["stderr"]

    def test_unlock_with_force(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """unlock --force routes to force_unlock."""
        registry = tmp_path / "AIPASS_REGISTRY.json"
        registry.write_text("{}", encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        result = handle_command("unlock", ["--force"])
        assert result["exit_code"] == 0

    def test_sync_routes_to_handler(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """sync command routes to sync_main."""
        registry = tmp_path / "AIPASS_REGISTRY.json"
        registry.write_text("{}", encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        mock_checkout = MagicMock()
        mock_checkout.returncode = 0
        mock_checkout.stdout = ""
        mock_checkout.stderr = ""

        mock_pull = MagicMock()
        mock_pull.returncode = 0
        mock_pull.stdout = "Already up to date."
        mock_pull.stderr = ""

        with patch(
            "aipass.drone.apps.handlers.git.sync_handler.subprocess.run",
            side_effect=[mock_checkout, mock_pull],
        ):
            result = handle_command("sync")

        assert result["exit_code"] == 0

    def test_status_no_branch_dir(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """status outside a branch directory returns error."""
        monkeypatch.chdir(tmp_path)
        result = handle_command("status")
        assert result["exit_code"] == 1
        assert "cannot detect" in result["stderr"].lower()

    def test_pr_no_args(self) -> None:
        """pr with no arguments returns usage error."""
        result = handle_command("pr")
        assert result["exit_code"] == 1
        assert "usage" in result["stderr"].lower()

    def test_pr_no_branch_dir(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """pr outside a branch directory returns error."""
        monkeypatch.chdir(tmp_path)
        result = handle_command("pr", ["some description"])
        assert result["exit_code"] == 1
        assert "cannot detect" in result["stderr"].lower()


class TestDetectBranchDir:
    """Branch directory detection tests."""

    def test_detects_branch_from_passport(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Detects branch name and dir by walking up to .trinity/passport.json."""
        # Create a fake branch directory with passport
        branch_dir = tmp_path / "mybranch"
        trinity = branch_dir / ".trinity"
        trinity.mkdir(parents=True)
        passport = trinity / "passport.json"
        passport.write_text(json.dumps({
            "branch_info": {"branch_name": "mybranch"},
        }))

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
        passport.write_text(json.dumps({
            "branch_info": {"branch_name": "commons"},
        }))

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
        text = get_help("pr")
        assert "pr" in text.lower()
        assert "description" in text.lower()

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
