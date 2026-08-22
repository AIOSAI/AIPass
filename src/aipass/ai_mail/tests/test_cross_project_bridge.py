# =================== AIPass ====================
# Name: test_cross_project_bridge.py
# Description: Tests for the verified-admin cross-project bridge + reply return path (FPLAN-0401 ph5/5b)
# Version: 1.1.0
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
here it is the seam, patched to a verdict. Phase 5b adds the return path: a
reply is always deliverable to the mail it answers.
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
    devpulse_seat = tmp_path / "src" / "aipass" / "devpulse"
    (devpulse_seat / ".trinity").mkdir(parents=True)
    # Every real citizen carries a passport; a seat without one is a shape that
    # does not exist on disk. The identity fence proves the caller by walking
    # AIPASS_CALLER_CWD up to this file, so a passport-less fixture made the
    # admin caller unprovable for a reason no live tree could reproduce.
    (devpulse_seat / ".trinity" / "passport.json").write_text(
        json.dumps({"branch_info": {"branch_name": "devpulse", "email": "@devpulse"}}),
        encoding="utf-8",
    )

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


class TestReplyReturnPath:
    """The return path: a reply is always deliverable to the mail it answers.

    The inbound message sitting in the sender's OWN mailbox is the proof the
    channel was sanctioned — replying is answering, not initiating. Initiation
    across projects stays admin-only, inbound only.
    """

    def _boundary(self, recipient: Path, sender_email: str = "@baud", email_data=None, to_branch: str = "@devpulse"):
        from aipass.ai_mail.apps.handlers.email.delivery import _check_cross_project_boundary

        return _check_cross_project_boundary(recipient, sender_email, email_data=email_data, to_branch=to_branch)

    @pytest.fixture
    def baud(self, repo, monkeypatch):
        """@baud, standing in its own project, holding one mail from @devpulse."""
        seat = repo / "projects" / "baud"
        (seat / ".ai_mail.local").mkdir(parents=True, exist_ok=True)
        (seat / ".ai_mail.local" / "inbox.json").write_text(
            json.dumps({"messages": [{"id": "abc123", "from": "@devpulse", "subject": "Admin dispatch"}]}),
            encoding="utf-8",
        )
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(seat))
        monkeypatch.setenv("AIPASS_CALLER_BRANCH", "baud")
        return seat

    def test_reply_to_the_original_sender_is_delivered(self, repo, baud):
        """The happy path: @baud answers devpulse's admin dispatch, mail lands."""
        refused, msg = self._boundary(
            repo / "src" / "aipass" / "devpulse",
            email_data={"in_reply_to": "abc123", "from": "@baud"},
        )
        assert refused is False
        assert msg == ""

    def test_forged_in_reply_to_is_refused(self, repo, baud):
        """An id that is in no mailbox proves nothing."""
        refused, msg = self._boundary(
            repo / "src" / "aipass" / "devpulse",
            email_data={"in_reply_to": "not-a-real-id", "from": "@baud"},
        )
        assert refused is True
        assert "Cross-project mail refused" in msg

    def test_reply_addressed_elsewhere_is_refused(self, repo, baud):
        """No laundering a new recipient through a reply."""
        refused, msg = self._boundary(
            repo / "src" / "aipass" / "devpulse",
            email_data={"in_reply_to": "abc123", "from": "@baud"},
            to_branch="@someone-else",
        )
        assert refused is True
        assert "Cross-project mail refused" in msg

    def test_non_reply_initiation_still_refused(self, repo, baud):
        """Initiation stays admin-only inbound — an outbound with no in_reply_to is not a reply."""
        refused, msg = self._boundary(
            repo / "src" / "aipass" / "devpulse",
            email_data={"from": "@baud", "subject": "unsolicited"},
        )
        assert refused is True
        assert "Cross-project mail refused" in msg

    def test_no_email_data_behaves_exactly_as_before(self, repo, baud):
        """Callers that pass nothing get today's refusal, unchanged."""
        refused, msg = self._boundary(repo / "src" / "aipass" / "devpulse")
        assert refused is True
        assert "Cross-project mail refused" in msg

    def test_original_reply_to_is_an_accepted_destination(self, repo, baud):
        """reply.py routes to `reply_to or from`; the exemption mirrors that rule.

        The replier never picks this address — only the ORIGINAL sender could
        have written it — so it is still the sanctioned channel, not laundering.
        """
        seat = repo / "projects" / "baud"
        (seat / ".ai_mail.local" / "inbox.json").write_text(
            json.dumps({"messages": [{"id": "abc123", "from": "@devpulse", "reply_to": "@flow", "subject": "Admin"}]}),
            encoding="utf-8",
        )
        refused, _ = self._boundary(
            repo / "src" / "aipass" / "devpulse",
            email_data={"in_reply_to": "abc123", "from": "@baud"},
            to_branch="@flow",
        )
        assert refused is False

    def test_sender_with_no_mailbox_is_refused(self, repo, monkeypatch):
        """No mailbox, no proof."""
        seat = repo / "projects" / "earmark"
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(seat))
        monkeypatch.setenv("AIPASS_CALLER_BRANCH", "earmark")
        refused, msg = self._boundary(
            repo / "src" / "aipass" / "devpulse",
            sender_email="@earmark",
            email_data={"in_reply_to": "abc123", "from": "@earmark"},
        )
        assert refused is True
        assert "Cross-project mail refused" in msg

    def test_unreadable_mailbox_is_refused_not_crashed(self, repo, baud):
        """A corrupt inbox fails closed."""
        (baud / ".ai_mail.local" / "inbox.json").write_text("{not json", encoding="utf-8")
        refused, _ = self._boundary(
            repo / "src" / "aipass" / "devpulse",
            email_data={"in_reply_to": "abc123", "from": "@baud"},
        )
        assert refused is True

    def test_same_project_reply_never_reads_a_mailbox(self, repo, baud):
        """Ordinary same-project replies are untouched — the check is not reached."""
        refused, _ = self._boundary(
            repo / "projects" / "baud",
            email_data={"in_reply_to": "abc123", "from": "@baud"},
            to_branch="@baud",
        )
        assert refused is False


class TestLaneDarkMeansNoWidening:
    """A dark lane closes both halves, end to end.

    These simulate the grant failing rather than asserting the real world has no
    key — Patrick's ceremony has since happened, so the key exists and the world
    answers True. What must stay true is that a FAILING grant widens nothing.
    """

    def test_a_dark_lane_means_no_resolution_widening(self, repo, monkeypatch):
        """Even claiming to be devpulse, a failing grant resolves nothing new."""
        monkeypatch.setenv("AIPASS_CALLER_BRANCH", "devpulse")
        monkeypatch.setattr(wake_mod, "_REPO_ROOT", repo)
        monkeypatch.setattr(wake_mod, "BRANCH_REGISTRY", repo / "AIPASS_REGISTRY.json")

        with _admin(False):
            assert is_verified_admin_caller() is False
            assert wake_mod.resolve_branch("@baud", admin=is_verified_admin_caller()) is None

    def test_a_dark_lane_means_the_boundary_still_refuses(self, repo, monkeypatch):
        """The delivery half of the same reality."""
        from aipass.ai_mail.apps.handlers.email.delivery import _check_cross_project_boundary

        monkeypatch.setenv("AIPASS_CALLER_BRANCH", "devpulse")
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(repo / "src" / "aipass" / "devpulse"))

        with _admin(False):
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


class TestReplyProofMailboxResolution:
    """The proof must be found wherever the replying branch's mailbox actually is.

    @baud's replies to fleet dispatches were refused with the cross-project
    sentence (2026-08-16), and the reply lane itself was never the problem — it
    passes whenever the proof is found. The failure is that two different
    resolvers disagree about *which mailbox is the sender's*:

    ``handle_reply`` finds the original through ``_resolve_branch_path()``
    (env, registry, fallback), so the reply is built and sent. The boundary then
    re-derives the mailbox through ``_resolve_reply_path()``, a walk UP from
    ``AIPASS_CALLER_CWD`` — which finds nothing unless the caller happens to be
    standing in the mailbox directory or below it. Original found, proof not
    found, reply refused.

    ``reply.py`` already saw this coming and stamps ``reply_path`` on every
    reply, derived from ``from_branch_path`` — "the branch actually replying" —
    precisely because the CWD guess "can name the wrong branch entirely". The
    boundary just never read it.

    The real tree is why the old fixture hid this: @baud's seat is
    ``projects/baud/src/baud/baud``, four levels below the project root, so a
    caller standing at ``projects/baud`` walks up past the mailbox and out of
    the project entirely. Every existing test set the CWD to the mailbox
    directory itself, pinning the one condition under which the resolver works.
    """

    def _boundary(self, recipient: Path, email_data, sender_email: str = "@baud", to_branch: str = "@devpulse"):
        from aipass.ai_mail.apps.handlers.email.delivery import _check_cross_project_boundary

        return _check_cross_project_boundary(recipient, sender_email, email_data=email_data, to_branch=to_branch)

    @pytest.fixture
    def deep_seat(self, repo, monkeypatch):
        """@baud's mailbox where it really lives: projects/baud/src/baud/baud."""
        seat = repo / "projects" / "baud" / "src" / "baud" / "baud"
        (seat / ".ai_mail.local").mkdir(parents=True)
        (seat / ".ai_mail.local" / "inbox.json").write_text(
            json.dumps({"messages": [{"id": "abc123", "from": "@devpulse", "subject": "Dispatch"}]}),
            encoding="utf-8",
        )
        # The caller stands at the PROJECT root, not in the mailbox directory.
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(repo / "projects" / "baud"))
        monkeypatch.setenv("AIPASS_CALLER_BRANCH", "baud")
        return seat

    def test_reply_passes_when_the_cwd_walk_up_finds_no_mailbox(self, repo, deep_seat):
        """The reported bug: a real reply, refused because the proof was sought
        in a mailbox the caller does not happen to be standing in."""
        refused, msg = self._boundary(
            repo / "src" / "aipass" / "devpulse",
            email_data={
                "in_reply_to": "abc123",
                "from": "@baud",
                "reply_path": str(deep_seat / ".ai_mail.local" / "inbox.json"),
            },
        )
        assert refused is False, f"a sanctioned reply was refused: {msg}"

    def test_fresh_send_still_refused_from_the_same_seat(self, repo, deep_seat):
        """The wall is not softened: no in_reply_to is still initiation."""
        refused, _ = self._boundary(
            repo / "src" / "aipass" / "devpulse",
            email_data={"from": "@baud", "reply_path": str(deep_seat / ".ai_mail.local" / "inbox.json")},
        )
        assert refused is True

    def test_a_stamped_path_outside_the_senders_project_is_not_proof(self, repo, deep_seat):
        """The fence: reply_path travels with the message, so it cannot be
        allowed to nominate an arbitrary mailbox elsewhere on disk."""
        outsider = repo / "src" / "aipass" / "devpulse" / ".ai_mail.local"
        outsider.mkdir(parents=True, exist_ok=True)
        (outsider / "inbox.json").write_text(
            json.dumps({"messages": [{"id": "forged", "from": "@devpulse"}]}),
            encoding="utf-8",
        )
        refused, _ = self._boundary(
            repo / "src" / "aipass" / "devpulse",
            email_data={
                "in_reply_to": "forged",
                "from": "@baud",
                "reply_path": str(outsider / "inbox.json"),
            },
        )
        assert refused is True, "a reply_path outside the sender's project must not count as proof"

    def test_forged_id_still_refused_even_with_a_valid_path(self, repo, deep_seat):
        """Widening WHERE we look never widens WHAT counts as proof."""
        refused, _ = self._boundary(
            repo / "src" / "aipass" / "devpulse",
            email_data={
                "in_reply_to": "no-such-id",
                "from": "@baud",
                "reply_path": str(deep_seat / ".ai_mail.local" / "inbox.json"),
            },
        )
        assert refused is True

    def test_the_cwd_route_still_works_when_it_resolves(self, repo, monkeypatch):
        """The original resolver stays as a fallback for callers with no stamp."""
        seat = repo / "projects" / "baud"
        (seat / ".ai_mail.local").mkdir(parents=True, exist_ok=True)
        (seat / ".ai_mail.local" / "inbox.json").write_text(
            json.dumps({"messages": [{"id": "abc123", "from": "@devpulse"}]}),
            encoding="utf-8",
        )
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(seat))
        refused, _ = self._boundary(
            repo / "src" / "aipass" / "devpulse",
            email_data={"in_reply_to": "abc123", "from": "@baud"},
        )
        assert refused is False
