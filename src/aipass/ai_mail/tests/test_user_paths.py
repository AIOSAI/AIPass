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

from aipass.ai_mail.apps.handlers.users.user import get_user_by_email, get_all_users


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
            path = result["mailbox_path"]
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
                path = info["mailbox_path"]
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
