# =================== AIPass ====================
# Name: test_release_notify_managers.py
# Description: Tests for release_notify manager discovery's declared roots
# Version: 1.0.0
# Created: 2026-11-09
# Modified: 2026-11-09
# =============================================

"""Tests for apps/handlers/release_notify/managers.py: declared roots come through memory's door."""

# The declared pass — what is NOT tested here, and what covers it instead:
# sentry: no-test-needed(ruff) — that handlers/release_notify/managers.py parses and imports
# sentry: no-test-needed(covered_elsewhere) — which AIPASS_ROOTS.json rows the door refuses: memory's own tests

import json
from pathlib import Path

from aipass.devpulse.apps.handlers.release_notify import managers
from aipass.memory.apps.modules import fleet


def test_discover_managers_lists_a_declared_root_through_the_door(monkeypatch, tmp_path):
    """A root declared outside the repo is searched, asked of fleet.declared_roots; a home-overlapping row is not."""
    repo = tmp_path / "repo"
    repo.mkdir()
    ext = tmp_path / "elsewhere" / "vera"
    trinity = ext / "src" / "vera" / ".trinity"
    trinity.mkdir(parents=True)
    (ext / "VERA_REGISTRY.json").write_text(
        json.dumps({"branches": [{"name": "VERA", "email": "@vera", "path": "src/vera"}]}), encoding="utf-8"
    )
    (trinity / "passport.json").write_text(
        json.dumps({"branch_info": {"branch_name": "VERA", "email": "@vera"}, "citizen_class": "manager"}),
        encoding="utf-8",
    )
    # "." is AIPass home itself: the door refuses it, a private parser would walk the whole repo.
    rows = [{"path": str(ext), "status": "active"}, {"path": ".", "status": "active"}]
    (repo / "AIPASS_ROOTS.json").write_text(json.dumps({"roots": rows}), encoding="utf-8")

    asked: list[Path] = []
    door = fleet.declared_roots
    monkeypatch.setattr(fleet, "declared_roots", lambda root=None: asked.append(root) or door(root))
    monkeypatch.setattr(managers, "aipass_root", lambda: repo)

    discovery = managers.discover_managers()

    assert asked == [repo]
    assert discovery["roots"] == [str(ext.resolve())]
    assert [entry["address"] for entry in discovery["managers"]] == ["@vera"]
