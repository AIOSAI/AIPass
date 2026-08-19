# =================== AIPass ====================
# Name: test_tag_handler.py
# Description: Tests for the tag handler — release tagging with safety guards
# Version: 1.0.0
# Created: 2026-07-02
# Modified: 2026-07-02
# =============================================

"""Tests for the tag handler — release tagging with safety guards."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from aipass.drone.apps.modules.git_module import get_help, handle_command

from .conftest import make_owner_project

_TAG_PATCH = "aipass.drone.apps.handlers.git.tag_handler.subprocess.run"

PYPROJECT_CONTENT = '[project]\nname = "aipass"\nversion = "2.6.1"\n'
INIT_CONTENT = '__version__ = "2.6.1"\n'

_MOCK_RESPONSES: dict[tuple[str, ...], str] = {
    ("git", "fetch", "origin"): "",
    ("git", "show", "origin/main:pyproject.toml"): PYPROJECT_CONTENT,
    ("git", "show", "origin/main:src/aipass/__init__.py"): INIT_CONTENT,
    ("git", "rev-parse", "origin/main"): "abc123def456789",
}


def _make_mock(stdout: str = "", returncode: int = 0, stderr: str = "") -> MagicMock:
    """Build a subprocess result mock."""
    m = MagicMock()
    m.returncode = returncode
    m.stdout = stdout
    m.stderr = stderr
    return m


def _mock_run_success(*args, **kwargs):
    """Route subprocess calls to preset responses for a clean happy path."""
    cmd = tuple(args[0])
    for prefix, stdout in _MOCK_RESPONSES.items():
        if cmd[: len(prefix)] == prefix:
            return _make_mock(stdout=stdout)
    return _make_mock()


def _mock_run_with_overrides(overrides: dict[tuple[str, ...], MagicMock]):
    """Return a side_effect that applies overrides on top of the happy-path defaults."""

    def _side_effect(*args, **kwargs):
        """Match command prefixes against overrides, fall back to happy-path."""
        cmd = tuple(args[0])
        for prefix, mock in overrides.items():
            if cmd[: len(prefix)] == prefix:
                return mock
        return _mock_run_success(*args, **kwargs)

    return _side_effect


_EXTERNAL_MOCK_RESPONSES: dict[tuple[str, ...], str] = {
    ("git", "rev-parse", "HEAD"): "feedfacecafe0001",
}


def _recording_run(
    calls: list[tuple[str, ...]],
    overrides: dict[tuple[str, ...], MagicMock] | None = None,
):
    """Return a side_effect that records every argv and answers external-repo calls."""

    def _side_effect(*args, **kwargs):
        """Record the argv, then answer from overrides or the external happy path."""
        cmd = tuple(args[0])
        calls.append(cmd)
        for prefix, mock in (overrides or {}).items():
            if cmd[: len(prefix)] == prefix:
                return mock
        for prefix, stdout in _EXTERNAL_MOCK_RESPONSES.items():
            if cmd[: len(prefix)] == prefix:
                return _make_mock(stdout=stdout)
        return _mock_run_success(*args, **kwargs)

    return _side_effect


@pytest.fixture()
def repo_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Set up a temporary directory with AIPASS_REGISTRY.json."""
    registry = tmp_path / "AIPASS_REGISTRY.json"
    registry.write_text("{}", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture()
def devpulse_dir(repo_dir: Path) -> Path:
    """Set up a repo_dir where devpulse genuinely holds owner-tier.

    A branch-name-only passport no longer authorizes anything (DPLAN-0281) — the
    owner has to be minted with real credentials for these handlers to be reached.
    """
    make_owner_project(repo_dir)
    return repo_dir


@pytest.fixture()
def drone_dir(repo_dir: Path) -> Path:
    """Set up a repo_dir with a drone passport (non-owner)."""
    trinity = repo_dir / ".trinity"
    trinity.mkdir()
    passport = trinity / "passport.json"
    passport.write_text('{"branch_info": {"branch_name": "drone"}}', encoding="utf-8")
    return repo_dir


# ===========================================================================
# 1. tag — format validation (owner tier, routed through handle_command)
# ===========================================================================


class TestTagFormatValidation:
    """Version format validation tests."""

    def test_rejects_no_v_prefix(self, devpulse_dir: Path) -> None:
        """Version without v prefix is rejected."""
        result = handle_command("tag", ["2.6.1"])
        assert result["exit_code"] == 1
        assert "vX.Y.Z" in result["stderr"]

    def test_rejects_invalid_format(self, devpulse_dir: Path) -> None:
        """Two-part version is rejected."""
        result = handle_command("tag", ["v1.2"])
        assert result["exit_code"] == 1
        assert "Invalid" in result["stderr"]

    def test_rejects_alpha(self, devpulse_dir: Path) -> None:
        """Non-numeric version is rejected."""
        result = handle_command("tag", ["vfoo.bar.baz"])
        assert result["exit_code"] == 1

    def test_accepts_valid_format(self, devpulse_dir: Path) -> None:
        """Valid vX.Y.Z format succeeds end-to-end."""
        with patch(_TAG_PATCH, side_effect=_mock_run_success):
            result = handle_command("tag", ["v2.6.1"])
        assert result["exit_code"] == 0


# ===========================================================================
# 2. tag — version guard
# ===========================================================================


class TestTagVersionGuard:
    """Version mismatch guard tests."""

    def test_pyproject_mismatch_refuses(self, devpulse_dir: Path) -> None:
        """Mismatched pyproject.toml version is refused."""
        overrides = {
            ("git", "show", "origin/main:pyproject.toml"): _make_mock(stdout='version = "9.9.9"\n'),
        }
        with patch(_TAG_PATCH, side_effect=_mock_run_with_overrides(overrides)):
            result = handle_command("tag", ["v2.6.1"])
        assert result["exit_code"] == 1
        assert "mismatch" in result["stderr"].lower()
        assert "9.9.9" in result["stderr"]

    def test_init_mismatch_refuses(self, devpulse_dir: Path) -> None:
        """Mismatched __init__.py version is refused."""
        overrides = {
            ("git", "show", "origin/main:src/aipass/__init__.py"): _make_mock(stdout='__version__ = "0.0.1"\n'),
        }
        with patch(_TAG_PATCH, side_effect=_mock_run_with_overrides(overrides)):
            result = handle_command("tag", ["v2.6.1"])
        assert result["exit_code"] == 1
        assert "mismatch" in result["stderr"].lower()
        assert "0.0.1" in result["stderr"]

    def test_pyproject_unreadable_refuses(self, devpulse_dir: Path) -> None:
        """Unreadable pyproject.toml is refused."""
        overrides = {
            ("git", "show", "origin/main:pyproject.toml"): _make_mock(returncode=128, stderr="fatal: path not found"),
        }
        with patch(_TAG_PATCH, side_effect=_mock_run_with_overrides(overrides)):
            result = handle_command("tag", ["v2.6.1"])
        assert result["exit_code"] == 1
        assert "pyproject" in result["stderr"].lower()

    def test_both_match_passes(self, devpulse_dir: Path) -> None:
        """Matching versions pass the guard."""
        with patch(_TAG_PATCH, side_effect=_mock_run_success):
            result = handle_command("tag", ["v2.6.1"])
        assert result["exit_code"] == 0


# ===========================================================================
# 3. tag — exists guard
# ===========================================================================


class TestTagExistsGuard:
    """Tag existence guard tests."""

    def test_local_tag_exists_refuses(self, devpulse_dir: Path) -> None:
        """Existing local tag is refused."""
        overrides = {
            ("git", "tag", "-l"): _make_mock(stdout="v2.6.1\n"),
        }
        with patch(_TAG_PATCH, side_effect=_mock_run_with_overrides(overrides)):
            result = handle_command("tag", ["v2.6.1"])
        assert result["exit_code"] == 1
        assert "already exists locally" in result["stderr"]

    def test_remote_tag_exists_refuses(self, devpulse_dir: Path) -> None:
        """Existing remote tag is refused."""
        overrides = {
            ("git", "ls-remote", "--tags", "origin"): _make_mock(stdout="abc123\trefs/tags/v2.6.1\n"),
        }
        with patch(_TAG_PATCH, side_effect=_mock_run_with_overrides(overrides)):
            result = handle_command("tag", ["v2.6.1"])
        assert result["exit_code"] == 1
        assert "already exists on remote" in result["stderr"]


# ===========================================================================
# 4. tag — happy path and failures
# ===========================================================================


class TestTagHappyPath:
    """End-to-end tagging tests."""

    def test_creates_and_pushes(self, devpulse_dir: Path) -> None:
        """Full happy path creates and pushes a tag."""
        with patch(_TAG_PATCH, side_effect=_mock_run_success):
            result = handle_command("tag", ["v2.6.1"])
        assert result["exit_code"] == 0
        assert "v2.6.1" in result["stdout"]
        assert "abc123" in result["stdout"]

    def test_fetch_failure(self, devpulse_dir: Path) -> None:
        """Fetch failure returns an error."""
        with patch(_TAG_PATCH, return_value=_make_mock(returncode=1, stderr="network error")):
            result = handle_command("tag", ["v2.6.1"])
        assert result["exit_code"] == 1
        assert "Fetch failed" in result["stderr"]

    def test_push_failure(self, devpulse_dir: Path) -> None:
        """Push failure after tag creation returns an error."""
        overrides = {
            ("git", "push", "origin"): _make_mock(returncode=1, stderr="permission denied"),
        }
        with patch(_TAG_PATCH, side_effect=_mock_run_with_overrides(overrides)):
            result = handle_command("tag", ["v2.6.1"])
        assert result["exit_code"] == 1
        assert "push failed" in result["stderr"].lower()


# ===========================================================================
# 5. tag --list
# ===========================================================================


class TestListTags:
    """Tag listing tests."""

    def test_empty_list(self, devpulse_dir: Path) -> None:
        """Empty repo returns no tags."""
        with patch(_TAG_PATCH, return_value=_make_mock()):
            result = handle_command("tag", ["--list"])
        assert result["exit_code"] == 0

    def test_returns_tags(self, devpulse_dir: Path) -> None:
        """Tags are returned sorted newest-first."""
        with patch(_TAG_PATCH, return_value=_make_mock(stdout="v2.6.1\nv2.6.0\nv2.5.0\n")):
            result = handle_command("tag", ["--list"])
        assert result["exit_code"] == 0
        assert "v2.6.1" in result["stdout"]
        assert "v2.5.0" in result["stdout"]

    def test_git_failure(self, devpulse_dir: Path) -> None:
        """Git failure returns error."""
        with patch(_TAG_PATCH, return_value=_make_mock(returncode=128, stderr="not a git repository")):
            result = handle_command("tag", ["--list"])
        assert result["exit_code"] == 0
        assert result["stdout"] != ""


# ===========================================================================
# 6. tag — access control and help
# ===========================================================================


class TestTagAccessControl:
    """Access tier and help tests."""

    def test_tag_denied_for_non_devpulse(self, drone_dir: Path) -> None:
        """Non-devpulse caller is denied for tag create."""
        result = handle_command("tag", ["v2.6.1"])
        assert result["exit_code"] == 1
        assert "not authorized" in result["stderr"].lower()

    def test_tag_list_allowed_for_any_branch(self, drone_dir: Path) -> None:
        """tag --list is global tier, any caller can use it."""
        with patch(_TAG_PATCH, return_value=_make_mock(stdout="v2.6.1\n")):
            result = handle_command("tag", ["--list"])
        assert result["exit_code"] == 0

    def test_tag_no_args_lists(self, drone_dir: Path) -> None:
        """tag with no args falls back to list (global tier)."""
        with patch(_TAG_PATCH, return_value=_make_mock()):
            result = handle_command("tag", [])
        assert result["exit_code"] == 0

    def test_tag_help(self) -> None:
        """tag help includes usage and guard descriptions."""
        help_text = get_help("tag")
        assert "vX.Y.Z" in help_text
        assert "Version guard" in help_text


# ===========================================================================
# 7. tag — external repo seats (DPLAN-0290 item 1)
# ===========================================================================


class TestExternalRepoTagging:
    """From a projects/* seat, tag releases THAT repo's HEAD — not our dev→PR→main flow."""

    @pytest.fixture()
    def baud_dir(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        """An external project whose own manager holds owner-tier (no AIPASS_REGISTRY.json)."""
        home = make_owner_project(tmp_path, branch="baud", registry_name="BAUD_REGISTRY.json")
        monkeypatch.chdir(home)
        return home

    def test_tags_current_head_and_pushes(self, baud_dir: Path) -> None:
        """The live BAUD failure: v0.1.0 must tag HEAD and push, in one command."""
        calls: list[tuple[str, ...]] = []
        with patch(_TAG_PATCH, side_effect=_recording_run(calls)):
            result = handle_command("tag", ["v0.1.0"])
        assert result["exit_code"] == 0
        assert "v0.1.0" in result["stdout"]
        assert "feedfacecafe0001" in result["stdout"]
        assert ("git", "rev-parse", "HEAD") in calls
        assert ("git", "tag", "-a", "v0.1.0", "-m", "Release v0.1.0") in calls
        assert ("git", "push", "origin", "v0.1.0") in calls

    def test_no_aipass_version_guard(self, baud_dir: Path) -> None:
        """External manifests are the repo owner's business — we never read ours from theirs."""
        calls: list[tuple[str, ...]] = []
        with patch(_TAG_PATCH, side_effect=_recording_run(calls)):
            result = handle_command("tag", ["v0.1.0"])
        assert result["exit_code"] == 0
        assert not [c for c in calls if c[:2] == ("git", "show")]
        assert not [c for c in calls if "origin/main" in c]

    @pytest.mark.parametrize("name", ["v0.1.0-rc1", "1.0.0", "release-2026-08", "app@2.3.4"])
    def test_accepts_the_repos_own_tag_conventions(self, baud_dir: Path, name: str) -> None:
        """vX.Y.Z is AIPass's convention. An external repo names its own releases."""
        with patch(_TAG_PATCH, side_effect=_recording_run([])):
            result = handle_command("tag", [name])
        assert result["exit_code"] == 0
        assert name in result["stdout"]

    def test_duplicate_local_tag_refuses(self, baud_dir: Path) -> None:
        """KEEP the duplicate guard — local half."""
        overrides = {("git", "tag", "-l"): _make_mock(stdout="v0.1.0\n")}
        calls: list[tuple[str, ...]] = []
        with patch(_TAG_PATCH, side_effect=_recording_run(calls, overrides)):
            result = handle_command("tag", ["v0.1.0"])
        assert result["exit_code"] == 1
        assert "already exists locally" in result["stderr"]
        assert not [c for c in calls if c[:3] == ("git", "tag", "-a")]

    def test_duplicate_remote_tag_refuses(self, baud_dir: Path) -> None:
        """KEEP the duplicate guard — remote half."""
        overrides = {("git", "ls-remote"): _make_mock(stdout="abc123\trefs/tags/v0.1.0\n")}
        with patch(_TAG_PATCH, side_effect=_recording_run([], overrides)):
            result = handle_command("tag", ["v0.1.0"])
        assert result["exit_code"] == 1
        assert "already exists on remote" in result["stderr"]

    def test_unreachable_remote_refuses_instead_of_tagging_blind(self, baud_dir: Path) -> None:
        """A remote check that FAILED is not a remote check that found nothing."""
        overrides = {("git", "ls-remote"): _make_mock(returncode=128, stderr="could not read from remote")}
        calls: list[tuple[str, ...]] = []
        with patch(_TAG_PATCH, side_effect=_recording_run(calls, overrides)):
            result = handle_command("tag", ["v0.1.0"])
        assert result["exit_code"] == 1
        assert "remote tag check failed" in result["stderr"].lower()
        assert not [c for c in calls if c[:3] == ("git", "tag", "-a")]

    def test_repo_with_no_commits_refuses(self, baud_dir: Path) -> None:
        """No HEAD, nothing to tag — say so instead of minting a broken ref."""
        overrides = {("git", "rev-parse", "HEAD"): _make_mock(returncode=128, stderr="unknown revision")}
        with patch(_TAG_PATCH, side_effect=_recording_run([], overrides)):
            result = handle_command("tag", ["v0.1.0"])
        assert result["exit_code"] == 1
        assert "HEAD" in result["stderr"]

    def test_invalid_ref_name_refuses(self, baud_dir: Path) -> None:
        """git owns what a tag name may be — we ask it, we don't re-invent the rules."""
        overrides = {("git", "check-ref-format"): _make_mock(returncode=1)}
        calls: list[tuple[str, ...]] = []
        with patch(_TAG_PATCH, side_effect=_recording_run(calls, overrides)):
            result = handle_command("tag", ["bad..name"])
        assert result["exit_code"] == 1
        assert "not a valid tag name" in result["stderr"].lower()
        assert not [c for c in calls if c[:3] == ("git", "tag", "-a")]

    @pytest.mark.parametrize("name", ["-f", "--delete", ""])
    def test_flag_shaped_names_refuse_before_touching_git(self, baud_dir: Path, name: str) -> None:
        """A name git would read as a flag never reaches an argv."""
        calls: list[tuple[str, ...]] = []
        with patch(_TAG_PATCH, side_effect=_recording_run(calls)):
            result = handle_command("tag", [name])
        assert result["exit_code"] == 1
        assert calls == []

    def test_push_failure_reports(self, baud_dir: Path) -> None:
        """A failed push is reported, never swallowed."""
        overrides = {("git", "push", "origin"): _make_mock(returncode=1, stderr="permission denied")}
        with patch(_TAG_PATCH, side_effect=_recording_run([], overrides)):
            result = handle_command("tag", ["v0.1.0"])
        assert result["exit_code"] == 1
        assert "push failed" in result["stderr"].lower()


class TestAipassSeatUnchanged:
    """Regression: translating the verb elsewhere must not move a single call here."""

    def test_aipass_call_sequence_is_unchanged(self, devpulse_dir: Path) -> None:
        """The AIPass release path, argv for argv — version guard, origin/main ref, push."""
        calls: list[tuple[str, ...]] = []
        with patch(_TAG_PATCH, side_effect=_recording_run(calls)):
            result = handle_command("tag", ["v2.6.1"])
        assert result["exit_code"] == 0
        assert calls == [
            ("git", "fetch", "origin"),
            ("git", "show", "origin/main:pyproject.toml"),
            ("git", "show", "origin/main:src/aipass/__init__.py"),
            ("git", "tag", "-l", "v2.6.1"),
            ("git", "ls-remote", "--tags", "origin", "refs/tags/v2.6.1"),
            ("git", "rev-parse", "origin/main"),
            ("git", "tag", "-a", "v2.6.1", "origin/main", "-m", "Release v2.6.1"),
            ("git", "push", "origin", "v2.6.1"),
        ]

    def test_aipass_still_demands_vxyz(self, devpulse_dir: Path) -> None:
        """The looser external naming rule must not leak into our own release lane."""
        calls: list[tuple[str, ...]] = []
        with patch(_TAG_PATCH, side_effect=_recording_run(calls)):
            result = handle_command("tag", ["v2.6.1-rc1"])
        assert result["exit_code"] == 1
        assert "vX.Y.Z" in result["stderr"]
        assert calls == []
