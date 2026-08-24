# =================== AIPass ====================
# Name: test_user_paths.py
# Description: Tests for absolute mailbox_path resolution in user functions
# Version: 1.0.0
# Created: 2026-03-17
# Modified: 2026-03-17
# =============================================

"""
Tests for mailbox_path Absolute Resolution

Bug: get_user_by_email() and get_all_users() returned relative paths like
"src/aipass/ai_mail/.ai_mail.local" instead of absolute paths.
get_current_user() was already correct (resolved against _repo_root).

Fix: Both functions now resolve relative registry paths against _repo_root
(the parent of BRANCH_REGISTRY_PATH), matching get_current_user()'s pattern.

These tests verify:
1. get_user_by_email() returns an absolute mailbox_path
2. get_all_users() returns absolute mailbox_path for every entry
3. Paths are never doubled (no src/aipass/.../src/aipass/...)
4. Absolute paths in the registry are preserved as-is
"""

import json
import pytest
from pathlib import Path
from unittest.mock import patch

from aipass.ai_mail.apps.handlers.users.user import get_all_users, get_current_user, get_user_by_email


# ─── Fixtures ────────────────────────────────────────────


@pytest.fixture
def relative_path_registry(tmp_path):
    """Create a registry with relative paths (production format).

    Production AIPASS_REGISTRY.json uses list format with relative paths:
        "path": "src/aipass/ai_mail"

    The registry sits at tmp_path/AIPASS_REGISTRY.json, so _repo_root
    is tmp_path. Resolved paths should be tmp_path / "src/aipass/..." .

    Returns (registry_path, expected_repo_root).
    """
    registry = {
        "branches": [
            {
                "name": "AI_MAIL",
                "path": "src/aipass/ai_mail",
                "email": "@ai_mail",
                "status": "active",
                "description": "Agent-to-agent messaging system",
            },
            {
                "name": "SPAWN",
                "path": "src/aipass/spawn",
                "email": "@spawn",
                "status": "active",
                "description": "Branch spawner",
            },
            {
                "name": "TRIGGER",
                "path": "src/aipass/trigger",
                "email": "@trigger",
                "status": "active",
                "description": "Event trigger system",
            },
        ]
    }
    registry_path = tmp_path / "AIPASS_REGISTRY.json"
    registry_path.write_text(json.dumps(registry, indent=2), encoding="utf-8")
    return registry_path, tmp_path


@pytest.fixture
def absolute_path_registry(tmp_path):
    """Create a registry where paths are already absolute.

    Ensures absolute paths pass through without double-resolution.
    Returns (registry_path, branch_dir).
    """
    branch_dir = tmp_path / "src" / "aipass" / "solo_branch"
    registry = {
        "branches": [
            {
                "name": "SOLO",
                "path": str(branch_dir),
                "email": "@solo",
                "status": "active",
                "description": "Branch with absolute path",
            },
        ]
    }
    registry_path = tmp_path / "AIPASS_REGISTRY.json"
    registry_path.write_text(json.dumps(registry, indent=2), encoding="utf-8")
    return registry_path, branch_dir


@pytest.fixture
def dict_format_registry(tmp_path):
    """Create a registry using dict format (legacy).

    Tests that the dict->list normalization via _get_branches_list still
    produces absolute paths.
    """
    registry = {
        "branches": {
            "devpulse": {
                "name": "DEVPULSE",
                "path": "src/aipass/devpulse",
                "email": "@devpulse",
                "status": "active",
                "description": "DevPulse branch",
            },
            "backup": {
                "name": "BACKUP",
                "path": "src/aipass/backup",
                "email": "@backup",
                "status": "active",
                "description": "Backup branch",
            },
        }
    }
    registry_path = tmp_path / "AIPASS_REGISTRY.json"
    registry_path.write_text(json.dumps(registry, indent=2), encoding="utf-8")
    return registry_path, tmp_path


# ─── get_user_by_email() tests ───────────────────────────


class TestGetUserByEmailPaths:
    """Verify get_user_by_email() returns absolute mailbox_path values."""

    def test_returns_absolute_mailbox_path(self, relative_path_registry):
        """Relative registry paths must be resolved to absolute mailbox_path."""
        registry_path, _ = relative_path_registry
        with patch("aipass.ai_mail.apps.handlers.users.branch_detection.BRANCH_REGISTRY_PATH", registry_path):
            result = get_user_by_email("@ai_mail")
            assert result is not None
            mailbox = Path(result["mailbox_path"])
            assert mailbox.is_absolute(), f"mailbox_path must be absolute, got: {result['mailbox_path']}"

    def test_path_rooted_at_repo_root(self, relative_path_registry):
        """Resolved path should start from the repo root (registry parent)."""
        registry_path, repo_root = relative_path_registry
        with patch("aipass.ai_mail.apps.handlers.users.branch_detection.BRANCH_REGISTRY_PATH", registry_path):
            result = get_user_by_email("@spawn")
            assert result is not None
            expected = str((repo_root / "src" / "aipass" / "spawn" / ".ai_mail.local").resolve())
            assert result["mailbox_path"] == expected

    def test_no_doubled_relative_path(self, relative_path_registry):
        """Path must not contain the relative prefix twice (the old bug)."""
        registry_path, _ = relative_path_registry
        with patch("aipass.ai_mail.apps.handlers.users.branch_detection.BRANCH_REGISTRY_PATH", registry_path):
            result = get_user_by_email("@trigger")
            assert result is not None
            # Normalize to forward slashes for consistent counting on all platforms
            path = result["mailbox_path"].replace("\\", "/")
            # Count occurrences of the relative segment
            assert path.count("src/aipass/trigger") == 1, f"Path contains doubled segment: {path}"

    def test_absolute_path_preserved(self, absolute_path_registry):
        """Registry entries with absolute paths should not be re-rooted."""
        registry_path, branch_dir = absolute_path_registry
        with patch("aipass.ai_mail.apps.handlers.users.branch_detection.BRANCH_REGISTRY_PATH", registry_path):
            result = get_user_by_email("@solo")
            assert result is not None
            expected = str((branch_dir / ".ai_mail.local").resolve())
            assert result["mailbox_path"] == expected

    def test_returns_none_for_unknown_email(self, relative_path_registry):
        """Unknown email should return None, not crash."""
        registry_path, _ = relative_path_registry
        with patch("aipass.ai_mail.apps.handlers.users.branch_detection.BRANCH_REGISTRY_PATH", registry_path):
            result = get_user_by_email("@nonexistent_branch_xyz")
            assert result is None

    def test_dict_format_returns_absolute_path(self, dict_format_registry):
        """Dict-format registry should also produce absolute paths."""
        registry_path, repo_root = dict_format_registry
        with patch("aipass.ai_mail.apps.handlers.users.branch_detection.BRANCH_REGISTRY_PATH", registry_path):
            result = get_user_by_email("@devpulse")
            assert result is not None
            mailbox = Path(result["mailbox_path"])
            assert mailbox.is_absolute(), f"mailbox_path must be absolute (dict format), got: {result['mailbox_path']}"
            expected = str((repo_root / "src" / "aipass" / "devpulse" / ".ai_mail.local").resolve())
            assert result["mailbox_path"] == expected


# ─── get_all_users() tests ───────────────────────────────


class TestGetAllUsersPaths:
    """Verify get_all_users() returns absolute mailbox_path for every entry."""

    def test_all_paths_are_absolute(self, relative_path_registry):
        """Every user returned must have an absolute mailbox_path."""
        registry_path, _ = relative_path_registry
        with patch("aipass.ai_mail.apps.handlers.users.branch_detection.BRANCH_REGISTRY_PATH", registry_path):
            users = get_all_users()
            assert len(users) == 3, f"Expected 3 users, got {len(users)}"
            for email, info in users.items():
                mailbox = Path(info["mailbox_path"])
                assert mailbox.is_absolute(), f"mailbox_path for {email} must be absolute, got: {info['mailbox_path']}"

    def test_all_paths_end_with_ai_mail_local(self, relative_path_registry):
        """Every mailbox_path should end with .ai_mail.local."""
        registry_path, _ = relative_path_registry
        with patch("aipass.ai_mail.apps.handlers.users.branch_detection.BRANCH_REGISTRY_PATH", registry_path):
            users = get_all_users()
            for email, info in users.items():
                assert info["mailbox_path"].endswith(".ai_mail.local"), (
                    f"mailbox_path for {email} should end with .ai_mail.local, got: {info['mailbox_path']}"
                )

    def test_no_doubled_paths_in_any_entry(self, relative_path_registry):
        """No entry should have a doubled relative segment."""
        registry_path, _ = relative_path_registry
        with patch("aipass.ai_mail.apps.handlers.users.branch_detection.BRANCH_REGISTRY_PATH", registry_path):
            users = get_all_users()
            for email, info in users.items():
                # Normalize to forward slashes for consistent counting on all platforms
                path = info["mailbox_path"].replace("\\", "/")
                # The relative prefix "src/aipass" should appear exactly once
                assert path.count("src/aipass") == 1, f"Path for {email} contains doubled 'src/aipass': {path}"

    def test_paths_resolve_against_repo_root(self, relative_path_registry):
        """Resolved paths should be rooted at the registry's parent dir."""
        registry_path, repo_root = relative_path_registry
        with patch("aipass.ai_mail.apps.handlers.users.branch_detection.BRANCH_REGISTRY_PATH", registry_path):
            users = get_all_users()
            for email, info in users.items():
                assert info["mailbox_path"].startswith(str(repo_root)), (
                    f"Path for {email} should start with repo root {repo_root}, got: {info['mailbox_path']}"
                )

    def test_absolute_paths_preserved(self, absolute_path_registry):
        """Entries with absolute paths should pass through unchanged."""
        registry_path, branch_dir = absolute_path_registry
        with patch("aipass.ai_mail.apps.handlers.users.branch_detection.BRANCH_REGISTRY_PATH", registry_path):
            users = get_all_users()
            assert "@solo" in users
            expected = str((branch_dir / ".ai_mail.local").resolve())
            assert users["@solo"]["mailbox_path"] == expected

    def test_dict_format_all_absolute(self, dict_format_registry):
        """Dict-format registry should produce absolute paths for all entries."""
        registry_path, _ = dict_format_registry
        with patch("aipass.ai_mail.apps.handlers.users.branch_detection.BRANCH_REGISTRY_PATH", registry_path):
            users = get_all_users()
            assert len(users) == 2
            for email, info in users.items():
                mailbox = Path(info["mailbox_path"])
                assert mailbox.is_absolute(), (
                    f"mailbox_path for {email} must be absolute (dict format), got: {info['mailbox_path']}"
                )

    def test_empty_registry_returns_empty_dict(self, tmp_path):
        """Missing registry file should return empty dict, not crash."""
        fake_path = tmp_path / "nonexistent_registry.json"
        with patch("aipass.ai_mail.apps.handlers.users.branch_detection.BRANCH_REGISTRY_PATH", fake_path):
            users = get_all_users()
            assert users == {}


# ─── Detection-failure diagnostics (error 0bd8b4f5) ──────
#
# drone runs the target branch with cwd=<target branch>, so Path.cwd() inside
# ai_mail is ALWAYS a valid branch dir and is never the cause of failure.
# Sender identity comes from the AIPASS_CALLER_* env vars. The old message
# blamed the (valid) working directory and sent two investigations chasing a
# phantom passport problem.


class TestDetectionFailureDiagnostics:
    """get_current_user()'s failure message must name the real cause."""

    def test_non_branch_caller_cwd_names_the_env_var(self, tmp_path, monkeypatch):
        """Caller ran drone from outside a branch — say so, and name the path."""
        monkeypatch.delenv("AIPASS_CALLER_BRANCH", raising=False)
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(tmp_path))

        with pytest.raises(RuntimeError) as exc_info:
            get_current_user()

        msg = str(exc_info.value)
        assert "AIPASS_CALLER_CWD" in msg
        assert str(tmp_path) in msg
        assert "not inside a branch" in msg

    def test_failure_message_does_not_blame_the_valid_cwd(self, tmp_path, monkeypatch):
        """The process CWD is valid — it must not be presented as the cause."""
        monkeypatch.delenv("AIPASS_CALLER_BRANCH", raising=False)
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(tmp_path))

        with pytest.raises(RuntimeError) as exc_info:
            get_current_user()

        msg = str(exc_info.value)
        # The old wording told the reader to go look for a passport in cwd
        assert "must be called from within a branch directory" not in msg
        assert "informational only" in msg

    def test_unknown_caller_branch_reported(self, monkeypatch):
        """An unresolvable AIPASS_CALLER_BRANCH is named explicitly."""
        monkeypatch.setenv("AIPASS_CALLER_BRANCH", "ghostbranch")
        monkeypatch.delenv("AIPASS_CALLER_CWD", raising=False)

        with pytest.raises(RuntimeError) as exc_info:
            get_current_user()

        msg = str(exc_info.value)
        assert "ghostbranch" in msg
        assert "not a known sender" in msg

    def test_fingerprint_prefix_preserved(self, tmp_path, monkeypatch):
        """Keep the BRANCH DETECTION FAILED prefix — trigger fingerprints on it."""
        monkeypatch.delenv("AIPASS_CALLER_BRANCH", raising=False)
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(tmp_path))

        with pytest.raises(RuntimeError, match="BRANCH DETECTION FAILED"):
            get_current_user()


class TestRepoRootFallbackIsLoud:
    """The cwd fallback still happens, but it stops being silent."""

    def test_the_fallback_names_itself_once(self, monkeypatch, tmp_path, caplog):
        """Silence here was doing real work — every caller got "wherever I stand".

        Written when the fresh checkout was the ORDINARY way to reach this
        branch. It no longer is: pyproject.toml resolves that case, and the
        class below pins it. What remains is a tree with neither marker, which
        really is broken — so the warning still has to be findable, and still
        must not repeat per call. Flagged by @devpulse alongside the PR 739
        failures (2026-08-23).
        """
        import logging

        from aipass.ai_mail.apps.handlers import paths

        monkeypatch.setattr(paths, "_CWD_FALLBACK_WARNED", False)
        monkeypatch.setattr(paths, "__file__", str(tmp_path / "nowhere" / "paths.py"))
        monkeypatch.chdir(tmp_path)

        with caplog.at_level(logging.WARNING):
            first = paths.find_repo_root()
            paths.find_repo_root()
            paths.find_repo_root()

        assert first == tmp_path, "anchor: the fallback must actually have fired"
        warnings = [r for r in caplog.records if "falling back to the current directory" in r.getMessage()]
        assert len(warnings) == 1, "warned once per process — a line per call is the runaway-log problem"

    def test_it_still_returns_rather_than_raising(self, monkeypatch, tmp_path):
        """Refusing would make every CI run an import-time failure by construction."""
        from aipass.ai_mail.apps.handlers import paths

        monkeypatch.setattr(paths, "_CWD_FALLBACK_WARNED", False)
        monkeypatch.setattr(paths, "__file__", str(tmp_path / "nowhere" / "paths.py"))
        monkeypatch.chdir(tmp_path)

        assert paths.find_repo_root() == tmp_path


class TestTheFreshCheckoutFindsTheRightRoot:
    """@devpulse's standing item (dc764d49): "find_repo_root's return Path.cwd(). Fix it."

    Their framing is what made the fix findable, so it is recorded here: the
    danger was never the register being MISSING — they refuse on that — it is
    the register being FOUND IN THE WRONG PLACE, which no refusal can catch. A
    wire that arms against an empty file in the wrong directory reports perfect
    health and covers nothing.

    AIPASS_REGISTRY.json is UNTRACKED runtime state, so on a fresh checkout it
    exists nowhere and the walk fell through to "wherever this process happens
    to be standing". pyproject.toml is tracked, sits only at the repo root, and
    is on the ancestor chain from this package — so the answer is available, it
    was simply never asked for.
    """

    def test_a_checkout_with_no_registry_still_finds_its_own_root(self, monkeypatch, tmp_path):
        """The regression test for the actual defect: right root, wrong cwd.

        Reds before the pyproject marker exists — find_repo_root returns the
        unrelated cwd, and every path built from it (feed, register, reports)
        lands in a directory that has nothing to do with the checkout.
        """
        from aipass.ai_mail.apps.handlers import paths

        checkout = tmp_path / "fresh-checkout"
        (checkout / "src" / "aipass" / "ai_mail" / "apps" / "handlers").mkdir(parents=True)
        (checkout / "pyproject.toml").write_text("[project]\nname = 'aipass'\n", encoding="utf-8")
        assert not list(checkout.rglob("AIPASS_REGISTRY.json")), "premise: a fresh checkout has no registry"

        elsewhere = tmp_path / "somewhere-else"
        elsewhere.mkdir()

        monkeypatch.setattr(paths, "_CWD_FALLBACK_WARNED", False)
        monkeypatch.setattr(
            paths, "__file__", str(checkout / "src" / "aipass" / "ai_mail" / "apps" / "handlers" / "paths.py")
        )
        monkeypatch.chdir(elsewhere)

        assert paths.find_repo_root() == checkout

    def test_the_registry_still_wins_when_it_is_there(self, monkeypatch, tmp_path):
        """Order matters: the live registry is authoritative, pyproject is the stand-in.

        Both markers present, at DIFFERENT levels, so the assertion can only
        pass for one of them.
        """
        from aipass.ai_mail.apps.handlers import paths

        outer = tmp_path / "outer"
        inner = outer / "inner"
        inner.mkdir(parents=True)
        (inner / "AIPASS_REGISTRY.json").write_text("{}", encoding="utf-8")
        (outer / "pyproject.toml").write_text("[project]\n", encoding="utf-8")

        monkeypatch.setattr(paths, "__file__", str(inner / "paths.py"))

        assert paths.find_repo_root() == inner

    def test_neither_marker_anywhere_still_falls_back_loudly(self, monkeypatch, tmp_path, caplog):
        """The last resort survives — it is just no longer the fresh-checkout path."""
        import logging

        from aipass.ai_mail.apps.handlers import paths

        monkeypatch.setattr(paths, "_CWD_FALLBACK_WARNED", False)
        monkeypatch.setattr(paths, "__file__", str(tmp_path / "bare" / "paths.py"))
        monkeypatch.chdir(tmp_path)

        with caplog.at_level(logging.WARNING):
            assert paths.find_repo_root() == tmp_path

        assert any("falling back to the current directory" in r.getMessage() for r in caplog.records)
