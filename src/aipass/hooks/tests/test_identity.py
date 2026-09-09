# =================== AIPass ====================
# Name: test_identity.py
# Version: 1.0.0
# Description: Tests for identity prompt handler
# Branch: hooks
# Created: 2026-05-22
# Modified: 2026-05-22
# =============================================

"""Tests for handlers/prompt/identity.py."""

import json
from pathlib import Path
from unittest.mock import patch


# Schema 1.0.0 shape — principles live at the TOP LEVEL. Live on every passport
# in the fleet today, so this layout must keep rendering after the 2.0 migration.
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

# Schema 2.0.0 shape (DPLAN-0319) — principles MOVED INSIDE identity. Block order
# also changes, but every field is read by key, so order costs nothing. Must render
# byte-identically to SAMPLE_PASSPORT.
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
        from aipass.hooks.apps.handlers.prompt.identity import handle

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

    def test_returns_empty_when_no_passport(self, tmp_path):
        from aipass.hooks.apps.handlers.prompt.identity import handle

        result = handle({"cwd": str(tmp_path)})

        assert result["exit_code"] == 0
        assert result["stdout"] == ""
        assert "sound" not in result

    def test_walks_up_to_find_passport(self, tmp_path):
        from aipass.hooks.apps.handlers.prompt.identity import handle

        trinity = tmp_path / ".trinity"
        trinity.mkdir()
        passport = trinity / "passport.json"
        passport.write_text(json.dumps(SAMPLE_PASSPORT), encoding="utf-8")
        nested = tmp_path / "apps" / "handlers"
        nested.mkdir(parents=True)

        result = handle({"cwd": str(nested)})

        assert "devpulse Identity" in result["stdout"]

    def test_formats_all_fields(self, tmp_path):
        from aipass.hooks.apps.handlers.prompt.identity import handle

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
        from aipass.hooks.apps.handlers.prompt.identity import handle

        trinity = tmp_path / ".trinity"
        trinity.mkdir()
        passport = trinity / "passport.json"
        passport.write_text(json.dumps({"branch_info": {"branch_name": "test"}, "identity": {}}), encoding="utf-8")

        result = handle({"cwd": str(tmp_path)})

        assert result["exit_code"] == 0
        assert "test Identity" in result["stdout"]
        assert result["sound"] == "identity"

    def test_empty_hook_data(self):
        from aipass.hooks.apps.handlers.prompt.identity import handle

        with patch("pathlib.Path.cwd", return_value=Path("/tmp/nonexistent")):
            result = handle({})

        assert result["exit_code"] == 0
        assert result["stdout"] == ""
        assert "sound" not in result

    def test_corrupt_passport_json(self, tmp_path):
        from aipass.hooks.apps.handlers.prompt.identity import handle

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

    Schema 2.0.0 moves the top-level ``principles`` array inside ``identity``.
    A plain ``data.get("principles")`` returns [] after that move and the
    Principles line vanishes with no error and no log — the failure is silent,
    which is why it is pinned on both shapes rather than just the new one.
    """

    @staticmethod
    def _render(tmp_path: Path, passport_data: dict) -> str:
        from aipass.hooks.apps.handlers.prompt.identity import handle

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
    """identity.personality and identity.anti_traits reach the model (RPLAN-0005 row 1).

    Both keys existed in passports and were silently dropped by the renderer.
    Measured 2026-09-08 across 173 passports on this machine: 12 carry either
    key and exactly ONE of those is a live citizen (Vera). So the whole fleet's
    render must be unchanged, which is what the last two tests here pin.
    """

    @staticmethod
    def _render(tmp_path: Path, passport_data: dict) -> str:
        from aipass.hooks.apps.handlers.prompt.identity import handle

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
        # The key's underscores become a space and only the first word is capped,
        # so a multi-word facet reads as a label rather than as an identifier.
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
        """The fleet-wide claim: 172 of 173 passports must be byte-identical.

        SAMPLE_PASSPORT carries neither key, so its render is the before-picture.
        """
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

        Guarding on truthiness alone would let a string personality through and
        iterate it character by character, which is a far worse prompt than the
        missing line this change set out to fix.
        """
        passport = {
            "branch_info": {"branch_name": "vera"},
            "identity": {"personality": "steady and direct", "anti_traits": []},
        }

        out = self._render(tmp_path, passport)

        assert "Never:" not in out
        assert "steady and direct" not in out
        # The rest of the block MUST still render. Without this the test passes
        # when the wrong shape CRASHES the renderer to empty, which is how it
        # read against a truthiness-only guard: a str has no .items(), the
        # handler swallowed the AttributeError, and "not in out" held because
        # nothing was in out. Measured — the mutation killed nothing until here.
        assert "# vera Identity" in out

    def test_a_facet_longer_than_its_budget_is_cut_at_a_sentence(self, tmp_path):
        """Truncate rather than drop: every facet stays present, every kept word true."""
        from aipass.hooks.apps.modules.grounding_content import FACET_CHAR_BUDGET

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
        # Cut at a boundary, never mid-word.
        assert body in long_facet
        # The facet is trimmed, not dropped, and the later keys still render.
        assert "Never: Never drifts" in out

    def test_veras_whole_render_stays_under_the_budget(self, tmp_path):
        """The one live passport that exercises this path, at full size.

        The budget is a per-turn tax, not a platform limit: this block is
        injected on EVERY turn, so an unbounded passport quietly costs the whole
        session. Six facets plus five anti-traits is the richest in the fleet.
        """
        from aipass.hooks.apps.modules.grounding_content import IDENTITY_CHAR_BUDGET

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
