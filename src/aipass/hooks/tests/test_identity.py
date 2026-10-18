# =================== AIPass ====================
# Name: test_identity.py
# Version: 1.3.3
# Description: Tests for identity prompt handler (cadence-gated 1.1.0, char budget enforced 1.2.0)
# Branch: hooks
# Created: 2026-05-22
# Modified: 2026-10-17
# =============================================

"""Tests for apps/handlers/prompt/identity.py."""

# handle() is cadence-gated; the gate is held open for every test here so the render
# tests pin formatting alone. TestCadenceGate pins the gate itself.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that handlers/prompt/identity.py parses and imports
# seedgo: no-test-needed(documentation) — the module docstring's account of the cadence period
# seedgo: no-test-needed(stdlib) — importlib.import_module resolving the cadence module by name

import json
from pathlib import Path

import pytest

from aipass.hooks.apps.handlers.prompt.identity import handle
from aipass.hooks.apps.modules.grounding_content import FACET_CHAR_BUDGET, IDENTITY_CHAR_BUDGET

_CADENCE_MODULE = "aipass.hooks.apps.modules.cadence"


@pytest.fixture(autouse=True)
def _cadence_fires(monkeypatch):
    """Hold the cadence gate open so render tests never depend on the live turn counter.

    Open for the identity loader only: a handler that asked under another name would render nothing.
    """
    monkeypatch.setattr(f"{_CADENCE_MODULE}.should_fire", lambda loader_name, *_a, **_k: loader_name == "identity")


class TestCadenceGate:
    """handle() honours the cadence gate exactly like the kernel and navmap loaders."""

    @staticmethod
    def _write_passport(tmp_path: Path) -> None:
        trinity = tmp_path / ".trinity"
        trinity.mkdir()
        (trinity / "passport.json").write_text(json.dumps(SAMPLE_PASSPORT), encoding="utf-8")

    def test_skips_on_cadence_skip(self, tmp_path, monkeypatch):

        self._write_passport(tmp_path)
        seen: list[str] = []

        def _skip(loader_name, _hook_data=None):
            seen.append(loader_name)
            return False

        monkeypatch.setattr(f"{_CADENCE_MODULE}.should_fire", _skip)

        result = handle({"cwd": str(tmp_path)})

        assert seen == ["identity"]
        assert result == {"stdout": "", "exit_code": 0}

    def test_fires_on_cadence_fire(self, tmp_path):

        self._write_passport(tmp_path)

        result = handle({"cwd": str(tmp_path)})

        assert "devpulse Identity" in result["stdout"]
        assert result["sound"] == "identity"

    def test_is_withheld_when_cadence_check_raises(self, tmp_path, monkeypatch, caplog):
        """The degraded fail mode (DPLAN-0347): identity waits, the kernel fires alone and says why."""

        self._write_passport(tmp_path)

        def _boom(*_a, **_k):
            raise RuntimeError("cadence state unreadable")

        monkeypatch.setattr(f"{_CADENCE_MODULE}.should_fire", _boom)

        result = handle({"cwd": str(tmp_path)})

        assert result == {"stdout": "", "exit_code": 0}
        assert "identity DEGRADED loader=identity" in caplog.text


# Schema 1.0.0 shape — principles at the TOP LEVEL; still live, so it must keep rendering.
SAMPLE_PASSPORT = {
    "branch_info": {
        "branch_name": "devpulse",
        "path": "src/aipass/devpulse",
        "email": "unknown",
    },
    "identity": {
        "role": "orchestration_hub",
        "purpose": "The user's primary AI collaborator",
        "traits": ["Pragmatic", "Direct"],
        "what_i_do": ["Plan", "Design", "Debug"],
        "what_i_dont_do": ["Full rebuilds"],
    },
    "principles": ["Fail honestly", "Memory is everything"],
}

# Schema 2.0.0 shape — principles inside identity; must render byte-identically to SAMPLE_PASSPORT.
SAMPLE_PASSPORT_V2 = {
    "branch_info": {
        "branch_name": "devpulse",
        "path": "src/aipass/devpulse",
        "email": "unknown",
    },
    "citizenship": {"registered": True, "residency": "core"},
    "identity": {
        "role": "orchestration_hub",
        "purpose": "The user's primary AI collaborator",
        "what_i_do": ["Plan", "Design", "Debug"],
        "what_i_dont_do": ["Full rebuilds"],
        "traits": ["Pragmatic", "Direct"],
        "principles": ["Fail honestly", "Memory is everything"],
    },
}


class TestIdentityHandler:
    def test_returns_identity_when_passport_found(self, tmp_path):

        trinity = tmp_path / ".trinity"
        trinity.mkdir()
        passport = trinity / "passport.json"
        passport.write_text(json.dumps(SAMPLE_PASSPORT), encoding="utf-8")

        result = handle({"cwd": str(tmp_path)})

        assert result["exit_code"] == 0
        assert "devpulse Identity" in result["stdout"]
        assert "orchestration_hub" in result["stdout"]
        assert "Pragmatic" in result["stdout"]
        assert result["sound"] == "identity"

    def test_a_passport_at_a_symlinked_home_is_not_read(self, tmp_path, monkeypatch):
        """host_portability (PR #774): the resolved walk never met an unresolved home and read home's passport."""
        real = tmp_path / "real_home"
        (real / ".trinity").mkdir(parents=True)
        (real / ".trinity" / "passport.json").write_text(json.dumps(SAMPLE_PASSPORT), encoding="utf-8")
        (real / "work").mkdir()
        (tmp_path / "home").symlink_to(real, target_is_directory=True)
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))

        result = handle({"cwd": str(real / "work")})

        assert result["stdout"] == ""

    def test_returns_empty_when_no_passport(self, tmp_path):

        result = handle({"cwd": str(tmp_path)})

        assert result["exit_code"] == 0
        assert result["stdout"] == ""
        assert "sound" not in result

    def test_walks_up_to_find_passport(self, tmp_path):

        trinity = tmp_path / ".trinity"
        trinity.mkdir()
        passport = trinity / "passport.json"
        passport.write_text(json.dumps(SAMPLE_PASSPORT), encoding="utf-8")
        nested = tmp_path / "apps" / "handlers"
        nested.mkdir(parents=True)

        result = handle({"cwd": str(nested)})

        assert "devpulse Identity" in result["stdout"]

    def test_formats_all_fields(self, tmp_path):

        trinity = tmp_path / ".trinity"
        trinity.mkdir()
        passport = trinity / "passport.json"
        passport.write_text(json.dumps(SAMPLE_PASSPORT), encoding="utf-8")

        result = handle({"cwd": str(tmp_path)})

        out = result["stdout"]
        assert "Path: src/aipass/devpulse" in out
        assert "Email: unknown" in out
        assert "Role: orchestration_hub" in out
        assert "Purpose: The user's primary AI collaborator" in out
        assert "Do: Plan | Design | Debug" in out
        assert "Don't: Full rebuilds" in out
        assert "Principles: Fail honestly * Memory is everything" in out

    def test_handles_minimal_passport(self, tmp_path):

        trinity = tmp_path / ".trinity"
        trinity.mkdir()
        passport = trinity / "passport.json"
        passport.write_text(json.dumps({"branch_info": {"branch_name": "test"}, "identity": {}}), encoding="utf-8")

        result = handle({"cwd": str(tmp_path)})

        assert result["exit_code"] == 0
        assert "test Identity" in result["stdout"]
        assert result["sound"] == "identity"

    def test_empty_hook_data(self, tmp_path, monkeypatch):
        # No cwd in the hook data: the real cwd is read, an empty directory.
        monkeypatch.chdir(tmp_path)
        result = handle({})

        assert result["exit_code"] == 0
        assert result["stdout"] == ""
        assert "sound" not in result

    def test_corrupt_passport_json(self, tmp_path):

        trinity = tmp_path / ".trinity"
        trinity.mkdir()
        passport = trinity / "passport.json"
        passport.write_text("{broken json", encoding="utf-8")

        result = handle({"cwd": str(tmp_path)})

        assert result["exit_code"] == 0
        assert result["stdout"] == ""
        assert "sound" not in result


class TestPrinciplesLayoutFallback:
    """principles must render on BOTH passport layouts (DPLAN-0319).

    A plain ``data.get("principles")`` returns [] on 2.0.0 and the line vanishes silently.
    """

    @staticmethod
    def _render(tmp_path: Path, passport_data: dict) -> str:

        trinity = tmp_path / ".trinity"
        trinity.mkdir(parents=True)
        (trinity / "passport.json").write_text(json.dumps(passport_data), encoding="utf-8")
        return handle({"cwd": str(tmp_path)})["stdout"]

    def test_v2_identity_scoped_principles_render(self, tmp_path):
        out = self._render(tmp_path, SAMPLE_PASSPORT_V2)

        assert "Principles: Fail honestly * Memory is everything" in out

    def test_both_layouts_render_identically(self, tmp_path):
        v1 = self._render(tmp_path / "v1", SAMPLE_PASSPORT)
        v2 = self._render(tmp_path / "v2", SAMPLE_PASSPORT_V2)

        assert v1 == v2

    def test_identity_wins_when_both_locations_present(self, tmp_path):
        """A half-migrated passport must follow the new home, not the stale one."""
        mixed = {
            "branch_info": {"branch_name": "devpulse"},
            "identity": {"principles": ["Migrated"]},
            "principles": ["Stale leftover"],
        }

        out = self._render(tmp_path, mixed)

        assert "Principles: Migrated" in out
        assert "Stale leftover" not in out

    def test_empty_identity_principles_falls_back_to_top_level(self, tmp_path):
        """An empty list is not an answer — fall through, same as the traits read."""
        partial = {
            "branch_info": {"branch_name": "devpulse"},
            "identity": {"principles": []},
            "principles": ["Fail honestly"],
        }

        out = self._render(tmp_path, partial)

        assert "Principles: Fail honestly" in out

    def test_no_principles_anywhere_emits_no_line(self, tmp_path):
        out = self._render(tmp_path, {"branch_info": {"branch_name": "devpulse"}, "identity": {}})

        assert "Principles:" not in out


class TestPersonalityAndAntiTraits:
    """identity.personality and identity.anti_traits reach the model (RPLAN-0005 row 1)."""

    @staticmethod
    def _render(tmp_path: Path, passport_data: dict) -> str:

        trinity = tmp_path / ".trinity"
        trinity.mkdir(parents=True)
        (trinity / "passport.json").write_text(json.dumps(passport_data), encoding="utf-8")
        return handle({"cwd": str(tmp_path)})["stdout"]

    def test_personality_facets_render_one_line_each_in_passport_order(self, tmp_path):
        """Insertion order is the author's argument — sorting would rewrite it."""
        passport = {
            "branch_info": {"branch_name": "vera"},
            "identity": {
                "personality": {
                    "core": "Three brains, one mouth.",
                    "voice": "Clear over clever.",
                    "under_pressure": "Steady.",
                }
            },
        }

        out = self._render(tmp_path, passport)

        assert "Core: Three brains, one mouth." in out
        assert "Voice: Clear over clever." in out
        assert "Under pressure: Steady." in out
        lines = out.splitlines()
        assert [line.split(":")[0] for line in lines if ":" in line][-3:] == ["Core", "Voice", "Under pressure"]

    def test_anti_traits_render_after_the_dont_line(self, tmp_path):
        """Don't names another citizen's tasks; Never names a way of being."""
        passport = {
            "branch_info": {"branch_name": "vera"},
            "identity": {
                "what_i_dont_do": ["Write framework code"],
                "anti_traits": ["Never micromanages", "Never avoids conflict"],
            },
        }

        out = self._render(tmp_path, passport)
        lines = out.splitlines()

        assert "Never: Never micromanages | Never avoids conflict" in out
        dont_at = next(i for i, line in enumerate(lines) if line.startswith("Don't:"))
        never_at = next(i for i, line in enumerate(lines) if line.startswith("Never:"))
        assert never_at == dont_at + 1

    def test_a_passport_without_either_key_renders_unchanged(self, tmp_path):
        """The fleet-wide claim: 172 of 173 passports must be byte-identical."""
        out = self._render(tmp_path, SAMPLE_PASSPORT)

        assert "Never:" not in out
        assert out.splitlines() == [
            "",
            "# devpulse Identity",
            "Path: src/aipass/devpulse",
            "Email: unknown",
            "Role: orchestration_hub",
            "Traits: Pragmatic | Direct",
            "Purpose: The user's primary AI collaborator",
            "Do: Plan | Design | Debug",
            "Don't: Full rebuilds",
            "Principles: Fail honestly * Memory is everything",
        ]

    def test_wrong_shapes_and_empties_emit_nothing(self, tmp_path):
        """A string personality or an empty anti_traits list is not a render.

        A truthiness-only guard would iterate a string personality character by character.
        """
        passport = {
            "branch_info": {"branch_name": "vera"},
            "identity": {"personality": "steady and direct", "anti_traits": []},
        }

        out = self._render(tmp_path, passport)

        assert "Never:" not in out
        assert "steady and direct" not in out
        # Without this, a wrong shape that crashes the renderer to empty still passes.
        assert "# vera Identity" in out

    def test_a_facet_longer_than_its_budget_is_cut_at_a_sentence(self, tmp_path):
        """Truncate rather than drop: every facet stays present, every kept word true."""

        first = "Short opening sentence. "
        long_facet = first + ("Filler words that run past the budget. " * 20)
        passport = {
            "branch_info": {"branch_name": "vera"},
            "identity": {"personality": {"core": long_facet}, "anti_traits": ["Never drifts"]},
        }

        out = self._render(tmp_path, passport)
        core_line = next(line for line in out.splitlines() if line.startswith("Core: "))
        body = core_line[len("Core: ") :]

        assert len(body) <= FACET_CHAR_BUDGET
        assert body.endswith(".")
        assert "Filler" in body
        assert body in long_facet
        assert "Never: Never drifts" in out

    def test_veras_whole_render_stays_under_the_budget(self, tmp_path):
        """The one live passport that exercises this path, at full size.

        The block is injected on EVERY turn, so the budget is a per-turn tax.
        """

        passport = {
            "branch_info": {"branch_name": "VERA", "path": "src/vera_studio/vera", "email": "@vera"},
            "identity": {
                "role": "brand_strategist",
                "purpose": "P" * 300,
                "traits": ["T" * 90] * 7,
                "personality": {f"facet_{i}": "S" * 200 for i in range(6)},
                "what_i_do": ["D" * 70] * 9,
                "what_i_dont_do": ["N" * 70] * 7,
                "anti_traits": ["A" * 80] * 5,
            },
            "principles": ["P" * 60] * 7,
        }

        out = self._render(tmp_path, passport)

        assert len(out) <= IDENTITY_CHAR_BUDGET
        assert out.count("Facet ") == 6


class TestIdentityBudgetIsEnforced:
    """DPLAN-0347 row 2: IDENTITY_CHAR_BUDGET stops being documentation.

    Every field counts against it, not only the facets.
    """

    @staticmethod
    def _render(tmp_path: Path, passport_data: dict) -> str:

        trinity = tmp_path / ".trinity"
        trinity.mkdir(parents=True)
        (trinity / "passport.json").write_text(json.dumps(passport_data), encoding="utf-8")
        return handle({"cwd": str(tmp_path)})["stdout"]

    @staticmethod
    def _fat_passport() -> dict:
        return {
            "branch_info": {"branch_name": "fat", "path": "src/aipass/fat", "email": "@fat"},
            "identity": {
                "role": "r" * 400,
                "purpose": "p" * 2000,
                "traits": ["t" * 200] * 12,
                "what_i_do": ["d" * 400] * 4,
                "what_i_dont_do": ["n" * 400] * 3,
                "principles": ["c" * 300] * 9,
            },
        }

    def test_a_passport_with_no_facets_is_capped_too(self, tmp_path):

        out = self._render(tmp_path, self._fat_passport())

        assert len(out) <= IDENTITY_CHAR_BUDGET + 1, f"rendered {len(out)} chars"
        assert f"cut at {IDENTITY_CHAR_BUDGET} chars" in out

    def test_the_cut_names_the_passport_it_came_from(self, tmp_path):
        """A block that simply stops reads as corrupted; a marker turns it into a pointer."""
        out = self._render(tmp_path, self._fat_passport())

        assert str(tmp_path / ".trinity" / "passport.json") in out

    def test_the_head_of_the_block_survives_the_cut(self, tmp_path):
        """Identity, path and email come first on purpose: the cut takes the tail, never the name."""
        out = self._render(tmp_path, self._fat_passport())

        assert out.splitlines()[1] == "# fat Identity"
        assert "Path: src/aipass/fat" in out

    def test_a_normal_passport_renders_whole(self, tmp_path):
        out = self._render(tmp_path, SAMPLE_PASSPORT)

        assert "cut at" not in out
        assert "Principles: Fail honestly * Memory is everything" in out
