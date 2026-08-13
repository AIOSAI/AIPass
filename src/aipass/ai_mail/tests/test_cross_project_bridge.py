# =================== AIPass ====================
# Name: test_cross_project_bridge.py
# Description: Tests for the verified-admin cross-project bridge (FPLAN-0401 Phase 5)
# Version: 1.0.0
# Created: 2026-08-12
# Modified: 2026-08-12
# =============================================

"""Tests for the cross-project bridge.

Two blockers stood between the devpulse seat and a citizen in projects/*:
resolution only ever walked the CALLER's ancestor tree, and delivery actively
refused mail across project roots. Both now have a verified-admin exemption —
and only a verified-admin one. Everyone else must be byte-identical, so most of
these tests assert that nothing happened.

The 5-leg verifier itself is devpulse's and is covered in test_admin_lane.py;
here it is the seam, patched to a verdict. One test uses the REAL verifier to
prove today's reality: no key, no widening.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import aipass.ai_mail.apps.handlers.dispatch.wake as wake_mod
from aipass.ai_mail.apps.handlers.registry.read import get_project_tree_branches
from aipass.ai_mail.apps.handlers.users.verified_caller import is_verified_admin_caller

_H_VERIFIED = "aipass.ai_mail.apps.handlers.users.verified_caller"
_H_DELIVERY = "aipass.ai_mail.apps.handlers.email.delivery"


@pytest.fixture(autouse=True)
def _clear_caller_env(monkeypatch):
    """Every test states its own caller env."""
    monkeypatch.delenv("AIPASS_CALLER_BRANCH", raising=False)
    monkeypatch.delenv("AIPASS_CALLER_CWD", raising=False)


@pytest.fixture
def repo(tmp_path):
    """A repo root with an AIPass registry and two sealed project registries."""
    (tmp_path / "AIPASS_REGISTRY.json").write_text(
        json.dumps({"branches": [{"name": "DEVPULSE", "email": "@devpulse", "path": "src/aipass/devpulse"}]}),
        encoding="utf-8",
    )
    (tmp_path / "src" / "aipass" / "devpulse").mkdir(parents=True)

    for project, seat in (("baud", "baud"), ("earmark", "earmark")):
        seat_path = tmp_path / "projects" / project
        seat_path.mkdir(parents=True)
        (seat_path / f"{project.upper()}_REGISTRY.json").write_text(
            json.dumps({"branches": [{"name": seat.upper(), "email": f"@{seat}", "path": str(seat_path)}]}),
            encoding="utf-8",
        )
    return tmp_path


def _admin(verdict: bool):
    """Patch the 5-leg verifier to a fixed verdict (its own tests live elsewhere)."""
    return patch(f"{_H_VERIFIED}.verify_admin_caller", MagicMock(return_value=(verdict, "patched")))


class TestProjectTreeBranches:
    """The discovery primitive: projects/*/ *_REGISTRY.json under the repo root."""

    def test_globs_every_sealed_project_registry(self, repo):
        """Each project's seat resolves to its absolute path."""
        found = get_project_tree_branches(repo)
        assert found["@baud"] == str(repo / "projects" / "baud")
        assert found["@earmark"] == str(repo / "projects" / "earmark")

    def test_missing_projects_dir_is_empty_not_an_error(self, tmp_path):
        """A repo with no projects/ tree yields nothing and does not raise."""
        assert get_project_tree_branches(tmp_path) == {}

    def test_unreadable_registry_is_skipped_not_fatal(self, repo):
        """One corrupt registry must not hide the healthy ones."""
        (repo / "projects" / "baud" / "BAUD_REGISTRY.json").write_text("{not json", encoding="utf-8")
        found = get_project_tree_branches(repo)
        assert "@earmark" in found
        assert "@baud" not in found

    def test_does_not_reach_outside_the_projects_tree(self, repo):
        """Only projects/*/ — a registry elsewhere in the repo is not swept in."""
        stray = repo / "src" / "aipass" / "devpulse"
        (stray / "STRAY_REGISTRY.json").write_text(
            json.dumps({"branches": [{"name": "STRAY", "email": "@stray", "path": str(stray)}]}),
            encoding="utf-8",
        )
        assert "@stray" not in get_project_tree_branches(repo)


class TestResolveBranchWidening:
    """wake.resolve_branch: the widening is admin-only."""

    def test_admin_resolves_a_projects_target(self, repo, monkeypatch):
        """@baud resolves from the devpulse seat under a verified admin dispatch."""
        monkeypatch.setattr(wake_mod, "_REPO_ROOT", repo)
        monkeypatch.setattr(wake_mod, "BRANCH_REGISTRY", repo / "AIPASS_REGISTRY.json")

        result = wake_mod.resolve_branch("@baud", admin=True)

        assert result is not None
        path, email = result
        assert email == "@baud"
        assert path == repo / "projects" / "baud"

    def test_non_admin_cannot_resolve_a_projects_target(self, repo, monkeypatch):
        """Unchanged refusal — no resolution widening for anyone unverified."""
        monkeypatch.setattr(wake_mod, "_REPO_ROOT", repo)
        monkeypatch.setattr(wake_mod, "BRANCH_REGISTRY", repo / "AIPASS_REGISTRY.json")

        assert wake_mod.resolve_branch("@baud") is None
        assert wake_mod.resolve_branch("@baud", admin=False) is None

    def test_admin_default_is_false(self):
        """Callers that know nothing about admin keep today's behaviour."""
        import inspect

        assert inspect.signature(wake_mod.resolve_branch).parameters["admin"].default is False

    def test_admin_does_not_shadow_the_aipass_registry(self, repo, monkeypatch):
        """A local branch still resolves locally — the glob is a fallback, not a preempt."""
        monkeypatch.setattr(wake_mod, "_REPO_ROOT", repo)
        monkeypatch.setattr(wake_mod, "BRANCH_REGISTRY", repo / "AIPASS_REGISTRY.json")

        result = wake_mod.resolve_branch("@devpulse", admin=True)

        assert result is not None
        assert result[0] == repo / "src" / "aipass" / "devpulse"


class TestCrossProjectBoundary:
    """delivery._check_cross_project_boundary: exempt the verified admin only."""

    def _boundary(self, recipient: Path, sender_email: str = "@devpulse"):
        from aipass.ai_mail.apps.handlers.email.delivery import _check_cross_project_boundary

        return _check_cross_project_boundary(recipient, sender_email)

    def test_non_admin_cross_project_still_refused(self, repo, monkeypatch):
        """Exactly today's refusal, wording included."""
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(repo / "projects" / "earmark"))
        with _admin(False):
            refused, msg = self._boundary(repo / "projects" / "baud")
        assert refused is True
        assert "Cross-project mail refused" in msg

    def test_verified_admin_is_exempt(self, repo, monkeypatch):
        """The bridge: a verified admin crosses project roots."""
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(repo / "src" / "aipass" / "devpulse"))
        monkeypatch.setenv("AIPASS_CALLER_BRANCH", "devpulse")
        with _admin(True):
            refused, msg = self._boundary(repo / "projects" / "baud")
        assert refused is False
        assert msg == ""

    def test_same_project_never_consults_the_verifier(self, repo, monkeypatch):
        """No key read for ordinary same-project mail — the common path stays free."""
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(repo / "projects" / "baud"))
        verifier = MagicMock(return_value=(True, "patched"))
        with patch(f"{_H_VERIFIED}.verify_admin_caller", verifier):
            refused, _ = self._boundary(repo / "projects" / "baud")
        assert refused is False
        verifier.assert_not_called()


class TestLaneDarkMeansNoWidening:
    """Today's reality, end to end, with the REAL verifier: no key, no bridge."""

    def test_no_key_means_no_resolution_widening(self, repo, monkeypatch):
        """Even claiming to be devpulse, an unsigned world resolves nothing new."""
        monkeypatch.setenv("AIPASS_CALLER_BRANCH", "devpulse")
        monkeypatch.setattr(wake_mod, "_REPO_ROOT", repo)
        monkeypatch.setattr(wake_mod, "BRANCH_REGISTRY", repo / "AIPASS_REGISTRY.json")

        assert is_verified_admin_caller() is False
        assert wake_mod.resolve_branch("@baud", admin=is_verified_admin_caller()) is None

    def test_no_key_means_the_boundary_still_refuses(self, repo, monkeypatch):
        """The delivery half of the same reality."""
        from aipass.ai_mail.apps.handlers.email.delivery import _check_cross_project_boundary

        monkeypatch.setenv("AIPASS_CALLER_BRANCH", "devpulse")
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(repo / "src" / "aipass" / "devpulse"))

        refused, msg = _check_cross_project_boundary(repo / "projects" / "baud", "@devpulse")
        assert refused is True
        assert "Cross-project mail refused" in msg


class TestIsVerifiedAdminCaller:
    """The bool wrapper both halves consume."""

    def test_non_holder_short_circuits_without_verifying(self, monkeypatch):
        """16 other citizens do zero file I/O on every send."""
        monkeypatch.setenv("AIPASS_CALLER_BRANCH", "seedgo")
        verifier = MagicMock(return_value=(True, "patched"))
        with patch(f"{_H_VERIFIED}.verify_admin_caller", verifier):
            assert is_verified_admin_caller() is False
        verifier.assert_not_called()

    def test_holder_with_a_passing_grant_is_admin(self, monkeypatch):
        """Rail says holder + verifier says yes."""
        monkeypatch.setenv("AIPASS_CALLER_BRANCH", "devpulse")
        with _admin(True):
            assert is_verified_admin_caller() is True

    def test_holder_with_a_failing_grant_is_not_admin(self, monkeypatch):
        """Rail alone grants nothing — all five legs or none."""
        monkeypatch.setenv("AIPASS_CALLER_BRANCH", "devpulse")
        with _admin(False):
            assert is_verified_admin_caller() is False

    def test_a_raising_verifier_is_not_admin(self, monkeypatch):
        """Fail closed on an unexpected error, never open."""
        monkeypatch.setenv("AIPASS_CALLER_BRANCH", "devpulse")
        with patch(f"{_H_VERIFIED}.verify_admin_caller", MagicMock(side_effect=RuntimeError("boom"))):
            assert is_verified_admin_caller() is False

    def test_result_is_not_cached_across_calls(self, monkeypatch):
        """A revoked grant must take effect immediately — caching would fail open."""
        monkeypatch.setenv("AIPASS_CALLER_BRANCH", "devpulse")
        verifier = MagicMock(side_effect=[(True, "granted"), (False, "revoked")])
        with patch(f"{_H_VERIFIED}.verify_admin_caller", verifier):
            assert is_verified_admin_caller() is True
            assert is_verified_admin_caller() is False
