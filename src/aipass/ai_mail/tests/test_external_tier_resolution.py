# =================== AIPass ====================
# Name: test_external_tier_resolution.py
# Description: resolve_branch reaches the declared-roots external tier (FPLAN-0460)
# Version: 1.0.0
# Created: 2026-08-30
# Modified: 2026-08-30
# =============================================

"""The external tier, through my door.

@vera's first supervised fire failed at ``resolve: Branch not found: @vera``.
Job DISCOVERY already knew the tier — @daemon reads @memory's fleet gateway —
but the FIRE path came through ``wake.resolve_branch``, which knew three
sources and none of them looked outside this repo. Discoverable but not
wakeable: the tier was half-plumbed.

THE SEAM IS ``_REPO_ROOT``, not a patched gateway. @memory's
``external_branches(repo_root=...)`` reads ``AIPASS_ROOTS.json`` at whatever
root it is handed, so pointing wake's ``_REPO_ROOT`` at a tmp home gives both
world states — anchor present and anchor absent — through the REAL gateway
code. Patching the gateway instead would have proven only that my mock returns
what I told it to, and the live defect was in whether the call happens at all.
Nothing here reads the real machine; every root, registry and passport below is
built in tmp_path.
"""

import json
from pathlib import Path

import pytest

import aipass.ai_mail.apps.handlers.dispatch.wake as wake_mod


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
        """WORLD STATE B — no AIPASS_ROOTS.json. @vera stays unresolvable.

        The pre-tier behaviour, pinned. An installation that declares nothing
        participates in nothing, and that is the ordinary state of a fresh
        clone rather than a fault.
        """
        assert not (home / "AIPASS_ROOTS.json").exists()

        assert wake_mod.resolve_branch("@vera") is None

    def test_external_citizen_resolves_through_the_anchor(self, home, vera_studio):
        """WORLD STATE A — the root is declared. @vera resolves to its real path.

        This is the live failure: same call, same tree, one blessed file apart.
        """
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

        The caller's input is lowercased at the top of resolve_branch, so a
        fixture that varies only the INPUT proves nothing about the address
        stored in someone else's registry. A dropped ``.lower()`` on the
        citizen's email survived that test and dies against this one. Casing
        genuinely disagrees across the fleet — the core registry already spells
        BACKUP and backup — and an external repo owes us no convention at all.
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

        @memory passes the address through rather than deriving one from the
        directory name, so ``email`` is legitimately None for a path-only
        citizen. Comparing ``None.lower()`` would raise, be swallowed by the
        containment guard, and turn every OTHER external in that root into an
        unresolvable — one addressless row taking out a whole tier.
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

        import aipass.ai_mail.apps.handlers.registry.read as read_mod

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
        """The daemon fires unverified. Declaration is the credential, not a grant.

        Deliberate and stated: the anchor is a machine-managed file Patrick
        blessed, so an external root is already an authorised destination. The
        admin sweep of ``projects/*`` is a different question and stays gated.
        """
        _declare(home, vera_studio)

        assert wake_mod.resolve_branch("@vera", admin=False) is not None


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

    def test_the_first_DECLARED_root_wins_not_the_first_alphabetically(self, home, tmp_path, caplog):
        """The fleet's tie-break, proven end to end through @memory's gateway.

        This pin used to assert the opposite. ``declared_roots()`` returned
        ``sorted(found)`` — resolved-path order — so the winner was whatever
        someone happened to name a directory, and the tie-break the ruling names
        was not available at this door. Rather than re-read the anchor to
        recover it (a second reader of the file the gateway exists to own), the
        collision was made loud and the disagreement raised with @memory, who
        dropped the sort in registry_scope 4.1.0. Zulu is declared first and
        sorts last, so only declaration order can produce this answer.
        """
        alpha = self._twin_in(tmp_path, "Alpha")
        zulu = self._twin_in(tmp_path, "Zulu")
        _declare(home, zulu, alpha)

        result = wake_mod.resolve_branch("@twin")

        assert result is not None
        assert result[0] == zulu / "src" / "twin"

    def test_the_control_case_where_both_orders_agree(self, home, tmp_path, caplog):
        """Declared Alpha-first, which is ALSO alphabetical — so this passes even
        under a re-sorted gateway. It is here as the twin of the test above:
        alone it proves nothing, and together they separate the two orders."""
        alpha = self._twin_in(tmp_path, "Alpha")
        zulu = self._twin_in(tmp_path, "Zulu")
        _declare(home, alpha, zulu)

        result = wake_mod.resolve_branch("@twin")

        assert result is not None
        assert result[0] == alpha / "src" / "twin"

    def test_every_losing_claimant_is_named_in_the_log(self, home, tmp_path, caplog):
        """A tie-break being correct does not make a collision expected. Two
        roots claiming one address is worth an error line naming both, or a
        resolution nobody logged reads exactly like a citizen with one home."""
        alpha = self._twin_in(tmp_path, "Alpha")
        zulu = self._twin_in(tmp_path, "Zulu")
        _declare(home, zulu, alpha)

        result = wake_mod.resolve_branch("@twin")

        assert result is not None
        assert "@twin" in caplog.text
        assert str(alpha / "src" / "twin") in caplog.text, "the loser must be named, not just the winner"
        assert "DECLARATION ORDER" in caplog.text
