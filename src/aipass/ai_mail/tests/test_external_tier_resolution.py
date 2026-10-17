# =================== AIPass ====================
# Name: test_external_tier_resolution.py
# Description: resolve_branch reaches the declared-roots external tier (FPLAN-0460)
# Version: 1.0.2
# Created: 2026-08-30
# Modified: 2026-10-17
# =============================================

"""Tests for apps/handlers/dispatch/wake.py -- the external tier, through my door."""

# The seam is ``_REPO_ROOT``, not a patched gateway: @memory's gateway reads AIPASS_ROOTS.json
# at the root it is handed, so both world states run through the REAL gateway code in tmp_path.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(shared) — resolve_wake_model()'s ModelDecision, unrelated here: tests/test_wake.py

import json
from pathlib import Path

import pytest

import aipass.ai_mail.apps.handlers.dispatch.wake as wake_mod
import aipass.ai_mail.apps.handlers.registry.read as read_mod


@pytest.fixture(autouse=True)
def _clear_caller_env(monkeypatch):
    """Step 2 must not reach a real project registry from whoever ran the suite."""
    monkeypatch.delenv("AIPASS_CALLER_BRANCH", raising=False)
    monkeypatch.delenv("AIPASS_CALLER_CWD", raising=False)


def _citizen(root: Path, rel: str, email: str) -> Path:
    """A branch on disk with the one thing external membership requires: a passport."""
    path = root / rel
    (path / ".trinity").mkdir(parents=True)
    (path / ".trinity" / "passport.json").write_text(
        json.dumps({"branch_info": {"branch_name": path.name, "email": email}}),
        encoding="utf-8",
    )
    return path


def _registry(root: Path, name: str, rows: list) -> None:
    """A top-level ``*_REGISTRY.json`` — the only thing the external walk globs."""
    (root / name).write_text(json.dumps({"branches": rows}), encoding="utf-8")


@pytest.fixture
def home(tmp_path, monkeypatch):
    """AIPass home, with one local citizen and no declared roots yet."""
    home = tmp_path / "AIPass"
    home.mkdir()
    local = home / "src" / "aipass" / "ai_mail"
    local.mkdir(parents=True)
    _registry(home, "AIPASS_REGISTRY.json", [{"name": "AI_MAIL", "email": "@ai_mail", "path": "src/aipass/ai_mail"}])
    monkeypatch.setattr(wake_mod, "_REPO_ROOT", home)
    monkeypatch.setattr(wake_mod, "BRANCH_REGISTRY", home / "AIPASS_REGISTRY.json")
    return home


@pytest.fixture
def vera_studio(tmp_path):
    """A sibling repo with its own registry and two citizens — @vera among them."""
    root = tmp_path / "Vera-Studio"
    root.mkdir()
    vera = _citizen(root, "src/vera_studio/vera", "@vera")
    _citizen(root, "src/vera_studio/writer", "@writer")
    _registry(
        root,
        "VERA-STUDIO_REGISTRY.json",
        [
            {"name": "vera", "email": "@vera", "status": "active", "path": str(vera)},
            {"name": "writer", "email": "@writer", "status": "active", "path": str(root / "src/vera_studio/writer")},
        ],
    )
    return root


def _declare(home: Path, *roots: Path, status: str = "active") -> None:
    """Write the machine anchor. Relative paths, as the live file carries them."""
    (home / "AIPASS_ROOTS.json").write_text(
        json.dumps(
            {"roots": [{"path": f"../{root.name}", "label": root.name.lower(), "status": status} for root in roots]}
        ),
        encoding="utf-8",
    )


class TestExternalTierIsReachable:
    """The defect and its fix, in the two world states."""

    def test_external_citizen_unreachable_without_the_anchor(self, home, vera_studio):
        """WORLD STATE B — no AIPASS_ROOTS.json. @vera stays unresolvable."""
        assert not (home / "AIPASS_ROOTS.json").exists()

        assert wake_mod.resolve_branch("@vera") is None

    def test_external_citizen_resolves_through_the_anchor(self, home, vera_studio):
        """WORLD STATE A — the root is declared. @vera resolves to its real path."""
        _declare(home, vera_studio)

        result = wake_mod.resolve_branch("@vera")

        assert result is not None
        path, email = result
        assert email == "@vera"
        assert path == vera_studio / "src" / "vera_studio" / "vera"

    def test_resolution_is_case_insensitive_across_the_fence(self, home, vera_studio):
        """@VERA is @vera. The canonical lowercase address comes back either way."""
        _declare(home, vera_studio)

        result = wake_mod.resolve_branch("@VERA")

        assert result is not None
        assert result[1] == "@vera"

    def test_the_registry_side_is_case_folded_too(self, home, tmp_path):
        """BOTH sides fold, and only this pins the far one.

        The input is lowercased up front, so only a mixed-case REGISTRY email pins the far side.
        """
        root = tmp_path / "Shouty"
        root.mkdir()
        seat = _citizen(root, "src/loud", "@Loud")
        _registry(
            root, "SHOUTY_REGISTRY.json", [{"name": "loud", "email": "@LOUD", "status": "active", "path": str(seat)}]
        )
        _declare(home, root)

        result = wake_mod.resolve_branch("@loud")

        assert result is not None
        assert result[0] == seat
        assert result[1] == "@loud"

    def test_a_root_declared_inactive_is_not_consulted(self, home, vera_studio):
        """``status`` is the anchor's own off switch and it survives my step."""
        _declare(home, vera_studio, status="parked")

        assert wake_mod.resolve_branch("@vera") is None

    def test_an_unknown_external_address_still_returns_none(self, home, vera_studio):
        """The tier widens WHO resolves, never WHETHER a miss is a miss."""
        _declare(home, vera_studio)

        assert wake_mod.resolve_branch("@ghost") is None

    def test_a_registry_row_without_a_passport_is_refused(self, home, tmp_path):
        """Membership is PRESENCE — a registry may list what disk does not carry."""
        root = tmp_path / "Hollow"
        root.mkdir()
        _registry(
            root,
            "HOLLOW_REGISTRY.json",
            [{"name": "ghosted", "email": "@ghosted", "status": "active", "path": str(root / "src" / "ghosted")}],
        )
        (root / "src" / "ghosted").mkdir(parents=True)
        _declare(home, root)

        assert wake_mod.resolve_branch("@ghosted") is None

    def test_an_addressless_citizen_does_not_break_the_search(self, home, tmp_path):
        """A registry row may carry no email at all, and it must not crash the walk.

        A raising ``None.lower()`` would be swallowed and make every other external in the root unresolvable.
        """
        root = tmp_path / "Quiet"
        root.mkdir()
        mute = _citizen(root, "src/mute", "@mute")
        named = _citizen(root, "src/named", "@named")
        _registry(
            root,
            "QUIET_REGISTRY.json",
            [
                {"name": "mute", "status": "active", "path": str(mute)},
                {"name": "named", "email": "@named", "status": "active", "path": str(named)},
            ],
        )
        _declare(home, root)

        assert wake_mod.resolve_branch("@mute") is None
        result = wake_mod.resolve_branch("@named")
        assert result is not None
        assert result[0] == named


class TestLocalAlwaysWins:
    """Precedence: the external tier is consulted only after every local source misses."""

    def test_aipass_registry_preempts_the_external_tier(self, home, tmp_path):
        """A name in both places resolves LOCALLY. The tier is a fallback, not a preempt."""
        impostor = tmp_path / "Impostor"
        impostor.mkdir()
        clash = _citizen(impostor, "src/ai_mail", "@ai_mail")
        _registry(
            impostor,
            "IMPOSTOR_REGISTRY.json",
            [{"name": "ai_mail", "email": "@ai_mail", "status": "active", "path": str(clash)}],
        )
        _declare(home, impostor)

        result = wake_mod.resolve_branch("@ai_mail")

        assert result is not None
        assert result[0] == home / "src" / "aipass" / "ai_mail"

    def test_caller_project_registry_preempts_the_external_tier(self, home, tmp_path, monkeypatch):
        """Step 2 wins too — the ruling is 'local always wins', not 'the core registry wins'."""
        caller_home = tmp_path / "CallerProject"
        caller_seat = caller_home / "src" / "strategy"
        caller_seat.mkdir(parents=True)
        external = tmp_path / "Elsewhere"
        external.mkdir()
        far = _citizen(external, "src/strategy", "@strategy")
        _registry(
            external,
            "ELSEWHERE_REGISTRY.json",
            [{"name": "strategy", "email": "@strategy", "status": "active", "path": str(far)}],
        )
        _declare(home, external)

        monkeypatch.setattr(read_mod, "get_caller_project_branches", lambda cwd: {"@strategy": str(caller_seat)})
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(caller_seat))

        result = wake_mod.resolve_branch("@strategy")

        assert result is not None
        assert result[0] == caller_seat


class TestTheStepIsContained:
    """A tier that cannot answer must never take the resolver down with it."""

    def test_a_raising_gateway_returns_none_not_a_traceback(self, home, vera_studio, monkeypatch):
        """Every caller of resolve_branch expects None on a miss, never an exception."""
        _declare(home, vera_studio)

        def _boom(*_args, **_kwargs):
            raise RuntimeError("gateway down")

        monkeypatch.setattr(wake_mod, "_external_citizens", _boom)

        assert wake_mod.resolve_branch("@vera") is None

    def test_the_external_step_needs_no_admin_grant(self, home, vera_studio):
        """The daemon fires unverified. Declaration is the credential, not a grant."""
        _declare(home, vera_studio)

        assert wake_mod.resolve_branch("@vera", admin=False) == (vera_studio / "src" / "vera_studio" / "vera", "@vera")


class TestCollisionsAreNamedNotGuessed:
    """N-root ties: one answer, and the ambiguity said out loud."""

    def _twin_in(self, tmp_path, name):
        """A root called `name` holding one citizen at @twin."""
        root = tmp_path / name
        root.mkdir()
        seat = _citizen(root, "src/twin", "@twin")
        _registry(
            root,
            f"{name.upper()}_REGISTRY.json",
            [{"name": "twin", "email": "@twin", "status": "active", "path": str(seat)}],
        )
        return root

    def test_the_first_declared_root_wins_not_the_first_alphabetically(self, home, tmp_path, caplog):
        """The fleet's tie-break, proven end to end through @memory's gateway.

        Zulu is declared first and sorts last, so only declaration order can produce this answer.
        """
        alpha = self._twin_in(tmp_path, "Alpha")
        zulu = self._twin_in(tmp_path, "Zulu")
        _declare(home, zulu, alpha)

        result = wake_mod.resolve_branch("@twin")

        assert result is not None
        assert result[0] == zulu / "src" / "twin"

    def test_the_control_case_where_both_orders_agree(self, home, tmp_path, caplog):
        """Declared Alpha-first, which is ALSO alphabetical — so this passes even
        under a re-sorted gateway; with the test above it separates the two orders."""
        alpha = self._twin_in(tmp_path, "Alpha")
        zulu = self._twin_in(tmp_path, "Zulu")
        _declare(home, alpha, zulu)

        result = wake_mod.resolve_branch("@twin")

        assert result is not None
        assert result[0] == alpha / "src" / "twin"

    def test_every_losing_claimant_is_named_in_the_log(self, home, tmp_path, caplog):
        """A tie-break being correct does not make a collision expected. Two
        roots claiming one address get an error line naming both."""
        alpha = self._twin_in(tmp_path, "Alpha")
        zulu = self._twin_in(tmp_path, "Zulu")
        _declare(home, zulu, alpha)

        result = wake_mod.resolve_branch("@twin")

        assert result == (zulu / "src" / "twin", "@twin"), "the first declared root wins the tie"
        assert "@twin" in caplog.text
        assert str(alpha / "src" / "twin") in caplog.text, "the loser must be named, not just the winner"
        assert "DECLARATION ORDER" in caplog.text
