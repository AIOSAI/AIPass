# =================== AIPass ====================
# Name: test_system_pr.py
# Description: Tests for devpulse_ops plugin — auth and system PR workflow
# Version: 1.0.0
# Created: 2026-03-30
# Modified: 2026-03-30
# =============================================

"""Tests for devpulse_ops plugin — auth and system PR workflow."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from aipass.drone.apps.plugins.devpulse_ops.auth import (
    ALLOWED_CALLERS,
    verify_caller,
)
from aipass.drone.apps.plugins.devpulse_ops.pr_plugin import (
    create_system_pr,
    slugify,
)


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture()
def devpulse_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a temp directory with a devpulse passport."""
    trinity = tmp_path / ".trinity"
    trinity.mkdir()
    passport = trinity / "passport.json"
    passport.write_text(
        json.dumps(
            {
                "branch_info": {"branch_name": "devpulse"},
                "identity": {"name": "devpulse"},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture()
def seedgo_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a temp directory with a seedgo passport (unauthorized)."""
    trinity = tmp_path / ".trinity"
    trinity.mkdir()
    passport = trinity / "passport.json"
    passport.write_text(
        json.dumps(
            {
                "branch_info": {"branch_name": "seedgo"},
                "identity": {"name": "seedgo"},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture()
def no_passport_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a temp directory with no passport."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture()
def repo_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a temp repo root with AIPASS_REGISTRY.json."""
    registry = tmp_path / "AIPASS_REGISTRY.json"
    registry.write_text("{}", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    return tmp_path


# ===========================================================================
# 1. auth.verify_caller tests
# ===========================================================================


class TestVerifyCallerAuthorized:
    """verify_caller should return the branch name for devpulse."""

    def test_verify_caller_with_devpulse_passport(self, devpulse_dir: Path) -> None:
        result = verify_caller()
        assert result == "devpulse"
        assert result in ALLOWED_CALLERS


class TestVerifyCallerUnauthorized:
    """verify_caller should raise PermissionError for non-devpulse branches."""

    def test_verify_caller_unauthorized(self, seedgo_dir: Path) -> None:
        with pytest.raises(PermissionError, match="not authorized"):
            verify_caller()

    def test_error_message_includes_branch_name(self, seedgo_dir: Path) -> None:
        with pytest.raises(PermissionError, match="seedgo"):
            verify_caller()


class TestVerifyCallerNoPassport:
    """verify_caller should raise PermissionError when no passport exists."""

    def test_verify_caller_no_passport(self, no_passport_dir: Path) -> None:
        with pytest.raises(PermissionError, match="No .trinity/passport.json"):
            verify_caller()


# ===========================================================================
# 2. slugify tests
# ===========================================================================


class TestSlugify:
    """Test the slugify function with various inputs."""

    def test_basic_slugify(self) -> None:
        assert slugify("Update all configs") == "update-all-configs"

    def test_special_characters_removed(self) -> None:
        assert slugify("fix: broken pipe!") == "fix-broken-pipe"

    def test_multiple_spaces_collapse(self) -> None:
        assert slugify("too   many   spaces") == "too-many-spaces"

    def test_max_length_truncation(self) -> None:
        long_desc = "a" * 100
        result = slugify(long_desc)
        assert len(result) <= 50

    def test_leading_trailing_hyphens_stripped(self) -> None:
        assert slugify("  --hello world--  ") == "hello-world"

    def test_empty_string(self) -> None:
        assert slugify("") == ""

    def test_all_special_chars(self) -> None:
        assert slugify("!!!@@@###") == ""

    def test_mixed_case(self) -> None:
        assert slugify("Hello World FOO") == "hello-world-foo"


# ===========================================================================
# 3. create_system_pr — not on main
# ===========================================================================


class TestSystemPrNotOnMain:
    """create_system_pr should fail when not on main branch."""

    @patch("aipass.drone.apps.plugins.devpulse_ops.pr_plugin.find_repo_root")
    @patch("aipass.drone.apps.plugins.devpulse_ops.pr_plugin.subprocess.run")
    def test_system_pr_not_on_main(self, mock_run: MagicMock, mock_root: MagicMock, tmp_path: Path) -> None:
        mock_root.return_value = tmp_path

        # Simulate being on a feature branch
        proc = MagicMock()
        proc.stdout = "feature/something\n"
        proc.returncode = 0
        mock_run.return_value = proc

        result = create_system_pr("test description", "devpulse")

        assert result["success"] is False
        assert "Not on main branch" in result["message"]


# ===========================================================================
# 4. create_system_pr — nothing to commit
# ===========================================================================


class TestSystemPrNothingToCommit:
    """create_system_pr should fail when there are no changes to PR."""

    @patch("aipass.drone.apps.plugins.devpulse_ops.pr_plugin.release_lock")
    @patch("aipass.drone.apps.plugins.devpulse_ops.pr_plugin.acquire_lock")
    @patch("aipass.drone.apps.plugins.devpulse_ops.pr_plugin.find_repo_root")
    @patch("aipass.drone.apps.plugins.devpulse_ops.pr_plugin.subprocess.run")
    def test_system_pr_nothing_to_commit(
        self,
        mock_run: MagicMock,
        mock_root: MagicMock,
        mock_acquire: MagicMock,
        mock_release: MagicMock,
        tmp_path: Path,
    ) -> None:
        mock_root.return_value = tmp_path
        mock_acquire.return_value = {"success": True, "message": "Lock acquired"}

        def side_effect(cmd: list[str], **kwargs: object) -> MagicMock:
            proc = MagicMock()
            if cmd[:3] == ["git", "rev-parse", "--abbrev-ref"]:
                proc.stdout = "main\n"
                proc.returncode = 0
            elif cmd[:3] == ["git", "add", "-u"]:
                proc.stdout = ""
                proc.stderr = ""
                proc.returncode = 0
            elif cmd[:3] == ["git", "diff", "--cached"]:
                # returncode 0 means nothing staged
                proc.stdout = ""
                proc.stderr = ""
                proc.returncode = 0
            elif cmd[:3] == ["git", "fetch", "origin"]:
                proc.stdout = ""
                proc.stderr = ""
                proc.returncode = 0
            elif cmd[:3] == ["git", "rev-list", "--count"]:
                # 0 commits ahead
                proc.stdout = "0\n"
                proc.stderr = ""
                proc.returncode = 0
            else:
                proc.stdout = ""
                proc.stderr = ""
                proc.returncode = 0
            return proc

        mock_run.side_effect = side_effect

        result = create_system_pr("test description", "devpulse")

        assert result["success"] is False
        assert "Nothing to PR" in result["message"]


# ===========================================================================
# 5. git_module routing for system-pr
# ===========================================================================


class TestGitModuleSystemPrRouting:
    """Test that git_module routes system-pr correctly."""

    def test_system_pr_in_commands(self) -> None:
        from aipass.drone.apps.modules.git_module import _COMMANDS

        assert "system-pr" in _COMMANDS

    def test_get_help_includes_system_pr(self) -> None:
        from aipass.drone.apps.modules.git_module import get_help

        help_text = get_help()
        assert "system-pr" in help_text

    def test_get_help_system_pr_specific(self) -> None:
        from aipass.drone.apps.modules.git_module import get_help

        help_text = get_help("system-pr")
        assert "devpulse" in help_text

    def test_get_introspective_includes_plugin(self) -> None:
        from aipass.drone.apps.modules.git_module import get_introspective

        intro = get_introspective()
        assert "devpulse_ops" in intro

    @patch("aipass.drone.apps.plugins.devpulse_ops.auth.verify_caller")
    def test_handle_system_pr_no_args(self, mock_verify: MagicMock) -> None:
        from aipass.drone.apps.modules.git_module import handle_command

        result = handle_command("system-pr", [])
        assert result["exit_code"] == 1
        assert "Usage" in result["stderr"]

    @patch("aipass.drone.apps.plugins.devpulse_ops.auth.verify_caller")
    def test_handle_system_pr_unauthorized(self, mock_verify: MagicMock) -> None:
        from aipass.drone.apps.modules.git_module import handle_command

        mock_verify.side_effect = PermissionError("not authorized")
        result = handle_command("system-pr", ["test"])
        assert result["exit_code"] == 1
        assert "not authorized" in result["stderr"]
