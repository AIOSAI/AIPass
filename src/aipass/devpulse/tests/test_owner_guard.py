# =================== AIPass ====================
# Name: test_owner_guard.py
# Description: Tests for the shared owner-capability caller guard (#681)
# Version: 1.0.0
# Created: 2026-07-10
# Modified: 2026-09-27
# =============================================

"""Tests for apps/handlers/owner/guard.py through guard_owner_caller, against a stubbed sealed registry."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(stdlib) — Path.parents' walk order behind the passport and devpulse-tree lookups

import pytest

import aipass.spawn.apps.handlers.registry as reg
from aipass.devpulse.apps.handlers.owner import guard as guard_mod


@pytest.fixture(autouse=True)
def _clear_caller_env(monkeypatch):
    """Start each test with no caller env; tests set exactly what they need."""
    monkeypatch.delenv("AIPASS_CALLER_BRANCH", raising=False)
    monkeypatch.delenv("AIPASS_CALLER_CWD", raising=False)


def _patch_registry(monkeypatch, owner_email):
    """Patch spawn's owner resolver. owner_email=None => no sealed owner.

    Returns the list of (email, start_path) pairs is_owner was asked about.
    """
    asked = []

    def fake_get_owner(start_path=None):
        """Stand-in for get_owner: owner entry dict, or None when unsealed."""
        return {"email": owner_email} if owner_email else None

    def _norm(email):
        """Normalize an email to lowercase with a leading '@'."""
        return (email if email.startswith("@") else f"@{email}").lower()

    def fake_is_owner(email, start_path=None):
        """Stand-in for is_owner: True iff email matches the sealed owner; records each question."""
        asked.append((email, start_path))
        if not owner_email or not email:
            return False
        return _norm(email) == _norm(owner_email)

    monkeypatch.setattr(reg, "get_owner", fake_get_owner)
    monkeypatch.setattr(reg, "is_owner", fake_is_owner)
    return asked


# ------------------------------------------------------------------
# Caller resolution, read off what the owner check is asked
# ------------------------------------------------------------------


class TestResolveCaller:
    """Caller identity resolution from the env drone sets."""

    def test_uses_branch_env(self, monkeypatch, tmp_path):
        """AIPASS_CALLER_BRANCH becomes the '@branch' email directly."""
        asked = _patch_registry(monkeypatch, "@flow")
        monkeypatch.setenv("AIPASS_CALLER_BRANCH", "flow")
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(tmp_path))
        assert guard_mod.guard_owner_caller("watchdog") is True
        assert asked == [("@flow", tmp_path)]

    def test_strips_and_lowercases(self, monkeypatch, tmp_path):
        """A '@Mixed' branch env normalizes to lowercase, single leading '@'."""
        asked = _patch_registry(monkeypatch, "@devpulse")
        monkeypatch.setenv("AIPASS_CALLER_BRANCH", "@DevPulse")
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(tmp_path))
        assert guard_mod.guard_owner_caller("watchdog") is True
        assert asked == [("@devpulse", tmp_path)]

    def test_walks_up_for_passport(self, monkeypatch, tmp_path):
        """With no branch env, walk up the caller cwd to the passport dir name."""
        branch = tmp_path / "mybranch"
        (branch / ".trinity").mkdir(parents=True)
        (branch / ".trinity" / "passport.json").write_text("{}", encoding="utf-8")
        sub = branch / "apps" / "modules"
        sub.mkdir(parents=True)
        asked = _patch_registry(monkeypatch, "@mybranch")
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(sub))
        assert guard_mod.guard_owner_caller("watchdog") is True
        assert asked == [("@mybranch", sub)]

    def test_empty_when_no_branch_and_no_passport(self, monkeypatch, tmp_path):
        """No branch env and no passport anywhere above => empty email, never put to is_owner."""
        asked = _patch_registry(monkeypatch, "@devpulse")
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(tmp_path))
        assert guard_mod.guard_owner_caller("watchdog") is False
        assert asked == []


# ------------------------------------------------------------------
# The legacy heuristic, reached with no sealed owner
# ------------------------------------------------------------------


class TestLegacyHeuristic:
    """The pre-owner fail-safe: allow only a caller in the devpulse tree."""

    def test_allows_devpulse_subtree(self, monkeypatch, tmp_path):
        """A path with a 'devpulse' ancestor is allowed."""
        _patch_registry(monkeypatch, None)
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(tmp_path / "devpulse" / "apps"))
        assert guard_mod.guard_owner_caller("watchdog") is True

    def test_allows_devpulse_leaf(self, monkeypatch, tmp_path):
        """A path whose leaf dir is 'devpulse' is allowed."""
        _patch_registry(monkeypatch, None)
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(tmp_path / "devpulse"))
        assert guard_mod.guard_owner_caller("watchdog") is True

    def test_rejects_other_branch(self, monkeypatch, tmp_path):
        """A path with no 'devpulse' component is rejected."""
        _patch_registry(monkeypatch, None)
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(tmp_path / "flow" / "apps"))
        assert guard_mod.guard_owner_caller("watchdog") is False


# ------------------------------------------------------------------
# The owner decision (stubbed resolver)
# ------------------------------------------------------------------


class TestOwnerDecision:
    """The core owner check against a (patched) sealed registry."""

    def test_allows_owner(self, monkeypatch, tmp_path):
        """The sealed owner's email is allowed, asked of the caller's own project."""
        project = tmp_path / "project" / "deep"
        asked = _patch_registry(monkeypatch, "@devpulse")
        monkeypatch.setenv("AIPASS_CALLER_BRANCH", "devpulse")
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(project))
        assert guard_mod.guard_owner_caller("watchdog") is True
        assert asked == [("@devpulse", project)]

    def test_rejects_non_owner(self, monkeypatch, tmp_path):
        """A non-owner email is rejected when an owner is sealed."""
        asked = _patch_registry(monkeypatch, "@devpulse")
        monkeypatch.setenv("AIPASS_CALLER_BRANCH", "flow")
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(tmp_path))
        assert guard_mod.guard_owner_caller("watchdog") is False
        assert asked == [("@flow", tmp_path)]

    def test_cross_project_owner(self, monkeypatch, tmp_path):
        """Owner is per-project: @vera owns elsewhere, devpulse does not."""
        _patch_registry(monkeypatch, "@vera")
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(tmp_path))
        monkeypatch.setenv("AIPASS_CALLER_BRANCH", "vera")
        assert guard_mod.guard_owner_caller("watchdog") is True
        monkeypatch.setenv("AIPASS_CALLER_BRANCH", "devpulse")
        assert guard_mod.guard_owner_caller("watchdog") is False

    def test_no_sealed_owner_falls_back_to_heuristic(self, monkeypatch, tmp_path):
        """No sealed owner => legacy devpulse-path heuristic decides."""
        _patch_registry(monkeypatch, None)  # get_owner -> None
        monkeypatch.setenv("AIPASS_CALLER_BRANCH", "anyone")
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(tmp_path / "x" / "devpulse" / "y"))
        assert guard_mod.guard_owner_caller("watchdog") is True
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(tmp_path / "x" / "flow" / "y"))
        assert guard_mod.guard_owner_caller("watchdog") is False

    def test_empty_email_rejected_when_owner_sealed(self, monkeypatch, tmp_path):
        """An unresolved caller (empty email) is rejected when owner is sealed, even inside the devpulse tree."""
        _patch_registry(monkeypatch, "@devpulse")
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(tmp_path / "devpulse"))
        assert guard_mod.guard_owner_caller("watchdog") is False


# ------------------------------------------------------------------
# guard_owner_caller / is_owner_caller (end to end via env)
# ------------------------------------------------------------------


class TestGuardOwnerCaller:
    """End-to-end gate behavior driven by the drone caller env."""

    def test_allows_owner(self, monkeypatch, tmp_path):
        """Owner caller => guard allows."""
        _patch_registry(monkeypatch, "@devpulse")
        monkeypatch.setenv("AIPASS_CALLER_BRANCH", "devpulse")
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(tmp_path))
        assert guard_mod.guard_owner_caller("watchdog") is True

    def test_denies_non_owner(self, monkeypatch, tmp_path):
        """Non-owner caller => guard denies (and audit-logs)."""
        _patch_registry(monkeypatch, "@devpulse")
        monkeypatch.setenv("AIPASS_CALLER_BRANCH", "flow")
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(tmp_path))
        assert guard_mod.guard_owner_caller("feedback") is False

    def test_cross_project_owner_end_to_end(self, monkeypatch, tmp_path):
        """A non-devpulse owner (@vera) is allowed in its own project."""
        _patch_registry(monkeypatch, "@vera")
        monkeypatch.setenv("AIPASS_CALLER_BRANCH", "vera")
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(tmp_path))
        assert guard_mod.guard_owner_caller("watchdog") is True
