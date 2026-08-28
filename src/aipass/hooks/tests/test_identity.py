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
