# =================== AIPass ====================
# Name: test_user_paths.py
# Description: Tests for absolute mailbox_path resolution in user functions
# Version: 1.0.3
# Created: 2026-03-17
# Modified: 2026-10-17
# =============================================

"""Tests for apps/handlers/users/user.py and apps/handlers/paths.py's find_repo_root()."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(stdlib) — json.JSONDecodeError's contract on a malformed file, not re-verified

import json
import pytest
from pathlib import Path
from unittest.mock import patch

from aipass.ai_mail.apps.handlers import paths
from aipass.ai_mail.apps.handlers.registry.read import RegistryUnreadable
from aipass.ai_mail.apps.handlers.users.user import get_all_users, get_current_user, get_user_by_email


@pytest.fixture
def relative_path_registry(tmp_path):
    """Create a registry with relative paths (production format); returns (registry_path, repo_root)."""
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
    """Create a registry where paths are already absolute; returns (registry_path, branch_dir)."""
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
    """Create a registry using dict format (legacy)."""
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
            assert result is not None and result["email_address"] == "@trigger"
            path = result["mailbox_path"].replace("\\", "/")
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

    def test_a_missing_registry_answers_none(self, tmp_path):
        """No registry file is an answer: nobody is known, so nobody is found."""
        missing = tmp_path / "AIPASS_REGISTRY.json"
        with patch("aipass.ai_mail.apps.handlers.users.branch_detection.BRANCH_REGISTRY_PATH", missing):
            assert get_user_by_email("@ai_mail") is None

    def test_a_corrupt_registry_raises_naming_itself(self, tmp_path):
        """A registry that exists and cannot be parsed is a fault, never "no such user"."""
        broken = tmp_path / "AIPASS_REGISTRY.json"
        broken.write_text("{not json", encoding="utf-8")
        with patch("aipass.ai_mail.apps.handlers.users.branch_detection.BRANCH_REGISTRY_PATH", broken):
            with pytest.raises(RegistryUnreadable) as raised:
                get_user_by_email("@ai_mail")
        assert str(broken) in str(raised.value)


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
            # The floor: every other assertion sits in the loop, so an empty result would pass silently.
            assert len(users) == 3, f"the registry fixture plants 3 users, got {len(users)}"
            for email, info in users.items():
                assert info["mailbox_path"].endswith(".ai_mail.local"), (
                    f"mailbox_path for {email} should end with .ai_mail.local, got: {info['mailbox_path']}"
                )

    def test_no_doubled_paths_in_any_entry(self, relative_path_registry):
        """No entry should have a doubled relative segment."""
        registry_path, _ = relative_path_registry
        with patch("aipass.ai_mail.apps.handlers.users.branch_detection.BRANCH_REGISTRY_PATH", registry_path):
            users = get_all_users()
            # The floor — see test_all_paths_end_with_ai_mail_local above.
            assert len(users) == 3, f"the registry fixture plants 3 users, got {len(users)}"
            for email, info in users.items():
                path = info["mailbox_path"].replace("\\", "/")
                assert path.count("src/aipass") == 1, f"Path for {email} contains doubled 'src/aipass': {path}"

    def test_paths_resolve_against_repo_root(self, relative_path_registry):
        """Resolved paths should be rooted at the registry's parent dir."""
        registry_path, repo_root = relative_path_registry
        with patch("aipass.ai_mail.apps.handlers.users.branch_detection.BRANCH_REGISTRY_PATH", registry_path):
            users = get_all_users()
            # The floor — see test_all_paths_end_with_ai_mail_local above.
            assert len(users) == 3, f"the registry fixture plants 3 users, got {len(users)}"
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

    def test_unreadable_registry_raises_not_empty(self, tmp_path):
        """A registry that exists and cannot be parsed raises, naming itself: "no users" is not "unknown"."""
        broken = tmp_path / "AIPASS_REGISTRY.json"
        broken.write_text("{not json", encoding="utf-8")
        with patch("aipass.ai_mail.apps.handlers.users.branch_detection.BRANCH_REGISTRY_PATH", broken):
            with pytest.raises(RegistryUnreadable) as raised:
                get_all_users()
        assert str(broken) in str(raised.value)


# drone runs the target with cwd=<target branch>, so Path.cwd() is always valid; identity comes from AIPASS_CALLER_*.


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

        A tree with neither marker is broken: the warning must be findable and must not repeat per call.
        """
        import logging

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
        monkeypatch.setattr(paths, "_CWD_FALLBACK_WARNED", False)
        monkeypatch.setattr(paths, "__file__", str(tmp_path / "nowhere" / "paths.py"))
        monkeypatch.chdir(tmp_path)

        assert paths.find_repo_root() == tmp_path


class TestTheFreshCheckoutFindsTheRightRoot:
    """@devpulse's standing item (dc764d49): "find_repo_root's return Path.cwd(). Fix it."

    AIPASS_REGISTRY.json is untracked, so a fresh checkout finds the root by the tracked pyproject.toml.
    """

    def test_a_checkout_with_no_registry_still_finds_its_own_root(self, monkeypatch, tmp_path):
        """The regression test for the actual defect: right root, wrong cwd."""
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
        """Order matters: the live registry is authoritative, pyproject is the stand-in."""
        # Markers at different levels, so the assertion can only pass for one of them.
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

        monkeypatch.setattr(paths, "_CWD_FALLBACK_WARNED", False)
        monkeypatch.setattr(paths, "__file__", str(tmp_path / "bare" / "paths.py"))
        monkeypatch.chdir(tmp_path)

        with caplog.at_level(logging.WARNING):
            assert paths.find_repo_root() == tmp_path

        assert any("falling back to the current directory" in r.getMessage() for r in caplog.records)
