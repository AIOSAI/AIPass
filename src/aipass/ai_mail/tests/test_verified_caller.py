# =================== AIPass ====================
# Name: test_verified_caller.py
# Description: Tests for the verified-caller rail (FPLAN-0401 Phase 1)
# Version: 1.0.0
# Created: 2026-08-12
# Modified: 2026-08-12
# =============================================

"""Tests for the verified-caller rail.

The rail exists because ``--from`` / ``--sender`` are unauthenticated strings:
before this, ``dispatch @manager --from @daemon`` resolved ``sender="@daemon"``
and unlocked the manager wake lane for any caller. Identity that gates a
privilege may only come from the env drone stamps from real process ancestry.
"""

import re
from pathlib import Path

import pytest

from aipass.ai_mail.apps.handlers.users.verified_caller import (
    PRIVILEGED_SENDERS,
    resolve_verified_caller,
    sender_claim_refusal,
    resolve_wake_sender,
)


@pytest.fixture(autouse=True)
def _clear_caller_env(monkeypatch):
    """Every test states its own caller env — an ambient one would decide for it."""
    monkeypatch.delenv("AIPASS_CALLER_BRANCH", raising=False)
    monkeypatch.delenv("AIPASS_CALLER_CWD", raising=False)


def _make_branch(tmp_path: Path, name: str) -> Path:
    """Create a passport-bearing branch directory."""
    branch = tmp_path / name
    (branch / ".trinity").mkdir(parents=True)
    (branch / ".trinity" / "passport.json").write_text("{}", encoding="utf-8")
    return branch


class TestResolveVerifiedCaller:
    """The rail itself: env only, never this process's own cwd."""

    def test_caller_branch_env_is_primary(self, monkeypatch):
        """AIPASS_CALLER_BRANCH wins — drone sets it from real process ancestry."""
        monkeypatch.setenv("AIPASS_CALLER_BRANCH", "seedgo")
        assert resolve_verified_caller() == "@seedgo"

    def test_caller_branch_is_normalized(self, monkeypatch):
        """Address form is @lowercase whatever the env carries."""
        monkeypatch.setenv("AIPASS_CALLER_BRANCH", "@SeedGo")
        assert resolve_verified_caller() == "@seedgo"

    def test_caller_cwd_passport_walk_is_the_fallback(self, tmp_path, monkeypatch):
        """No branch env — walk AIPASS_CALLER_CWD up to a passport."""
        branch = _make_branch(tmp_path, "daemon")
        nested = branch / "apps" / "modules"
        nested.mkdir(parents=True)
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(nested))
        assert resolve_verified_caller() == "@daemon"

    def test_env_branch_beats_cwd_walk(self, tmp_path, monkeypatch):
        """Both signals present and disagreeing: the assigned identity wins."""
        branch = _make_branch(tmp_path, "daemon")
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(branch))
        monkeypatch.setenv("AIPASS_CALLER_BRANCH", "seedgo")
        assert resolve_verified_caller() == "@seedgo"

    def test_no_rail_returns_empty(self):
        """No caller env at all — unprovable, and that is not an error."""
        assert resolve_verified_caller() == ""

    def test_bare_process_cwd_is_never_the_answer(self, tmp_path, monkeypatch):
        """THE rule: this process's own cwd cannot satisfy a privilege check.

        ai_mail runs with cwd=<its own tree> under drone, and a dispatched agent
        runs with cwd=<the target branch> — a bare-cwd walk would hand back an
        identity that says nothing about who called.
        """
        branch = _make_branch(tmp_path, "daemon")
        monkeypatch.chdir(branch)
        assert resolve_verified_caller() == ""

    def test_caller_cwd_outside_any_branch_returns_empty(self, tmp_path, monkeypatch):
        """A caller standing outside every passport tree stays unproven."""
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(tmp_path))
        assert resolve_verified_caller() == ""


class TestSenderClaimRefusal:
    """A privilege-bearing claim must be proven; everything else is free."""

    def test_privileged_claim_from_other_caller_is_refused(self, monkeypatch):
        """The live hole: @seedgo claiming @daemon."""
        monkeypatch.setenv("AIPASS_CALLER_BRANCH", "seedgo")
        reason = sender_claim_refusal("@daemon")
        assert reason is not None
        assert "@daemon" in reason and "@seedgo" in reason

    def test_privileged_claim_from_the_real_caller_is_allowed(self, monkeypatch):
        """@daemon claiming @daemon, proven by the rail."""
        monkeypatch.setenv("AIPASS_CALLER_BRANCH", "daemon")
        assert sender_claim_refusal("@daemon") is None

    def test_privileged_claim_without_the_rail_is_refused(self):
        """Unprovable is refused, not waved through. Fail closed."""
        reason = sender_claim_refusal("@daemon")
        assert reason is not None
        assert "unverified" in reason.lower()

    def test_privileged_claim_proven_by_passport_walk(self, tmp_path, monkeypatch):
        """The documented fallback leg proves the claim too."""
        branch = _make_branch(tmp_path, "daemon")
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(branch))
        assert sender_claim_refusal("@daemon") is None

    def test_privileged_claim_not_proven_by_bare_cwd(self, tmp_path, monkeypatch):
        """Standing in the daemon tree is not being the daemon."""
        branch = _make_branch(tmp_path, "daemon")
        monkeypatch.chdir(branch)
        assert sender_claim_refusal("@daemon") is not None

    def test_claim_is_normalized_before_comparison(self, monkeypatch):
        """Case and the leading @ are not a bypass."""
        monkeypatch.setenv("AIPASS_CALLER_BRANCH", "seedgo")
        assert sender_claim_refusal("DAEMON") is not None
        assert sender_claim_refusal("@DaEmOn") is not None

    def test_non_privileged_claim_is_never_refused(self, monkeypatch):
        """--from @spawn from @seedgo stays legal: it gates nothing."""
        monkeypatch.setenv("AIPASS_CALLER_BRANCH", "seedgo")
        assert sender_claim_refusal("@spawn") is None

    def test_empty_claim_is_never_refused(self, monkeypatch):
        """No --from at all is not a claim."""
        monkeypatch.setenv("AIPASS_CALLER_BRANCH", "seedgo")
        assert sender_claim_refusal("") is None
        assert sender_claim_refusal(None) is None


class TestResolveWakeSender:
    """What actually reaches wake_branch(sender=...)."""

    def test_verified_caller_wins_over_the_claim(self, monkeypatch):
        """The claimed identity is display metadata; the rail decides the wake."""
        monkeypatch.setenv("AIPASS_CALLER_BRANCH", "seedgo")
        assert resolve_wake_sender("@spawn") == "@seedgo"

    def test_claim_is_the_fallback_when_unverifiable(self):
        """No rail: fall back to the claim, which the refusal has already
        guaranteed is not privilege-bearing."""
        assert resolve_wake_sender("@spawn") == "@spawn"

    def test_empty_claim_and_no_rail_stays_empty(self):
        """Nothing invented — an empty sender is wake-back's chain terminator."""
        assert resolve_wake_sender("") == ""


class TestPrivilegedSendersCoverage:
    """PRIVILEGED_SENDERS must not drift from the lanes it protects."""

    def test_set_contains_daemon(self):
        """@daemon unlocks the manager wake lane at wake.py Step 3."""
        assert "@daemon" in PRIVILEGED_SENDERS

    def test_every_sender_literal_wake_gates_on_is_listed(self):
        """Structural canary: any `sender == "@x"` decision in wake.py must be
        a listed privileged value, or dispatch.py stops guarding it.

        Scans executable lines only (comment lines are stripped) — prose about
        a gate is not a gate. Phase 4 adds the admin identity to that tree; this
        goes red if the set is not updated with it.
        """
        wake_src = (Path(__file__).resolve().parents[1] / "apps" / "handlers" / "dispatch" / "wake.py").read_text(
            encoding="utf-8"
        )
        code = "\n".join(line for line in wake_src.splitlines() if not line.strip().startswith("#"))
        gated = {m.lower() for m in re.findall(r"""sender\s*==\s*["']([^"']+)["']""", code)}
        assert gated, "expected at least one sender gate in wake.py"
        assert gated <= set(PRIVILEGED_SENDERS), f"unguarded sender gate(s): {gated - set(PRIVILEGED_SENDERS)}"
