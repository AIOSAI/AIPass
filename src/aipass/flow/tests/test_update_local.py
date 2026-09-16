# =================== AIPass ====================
# Name: test_update_local.py
# Description: Tests for update_local handler — Flow dashboard updates
# Version: 2.0.0
# Created: 2026-04-26
# Modified: 2026-09-15
# =============================================

"""
Tests for update_local handler — Flow's own dashboard card.

As of 2026-09-15 (DPLAN-0347 / FPLAN-0593 Phase 2) this handler no longer
builds a card of its own: it delegates to push_flow_to_branch_dashboard, the
one writer of the flow section, pointed at Flow's own root. The builders it
used to own — registry merge, plan extraction, statistics, dashboard assembly —
live in push_branch_dashboard.py and are pinned by test_push_branch_dashboard.py.

What is pinned here is the delegation itself and the defect that motivated it:
the top-level ``flow_plans`` key must never come back. It was written outside
``sections``, where the dashboard's preserve and budget logic cannot see it, so
@prax's refresh dropped it and the next plan operation re-added it — a flap
measured on Flow's own dashboard the day this landed.
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

import aipass.flow.apps.handlers.dashboard.update_local as update_local
import aipass.flow.apps.handlers.dashboard.push_branch_dashboard as push_mod

_MOD = "aipass.flow.apps.handlers.dashboard.update_local"


@pytest.fixture
def flow_root(tmp_path, monkeypatch):
    """A Flow root with a dashboard and a registry the section writer can read."""
    root = tmp_path / "flow"
    flow_json = root / "flow_json"
    flow_json.mkdir(parents=True)

    monkeypatch.setattr(update_local, "FLOW_ROOT", root)
    monkeypatch.setattr(push_mod, "FLOW_JSON_DIR", flow_json)
    monkeypatch.setattr(push_mod, "REGISTRY_FILE", flow_json / "fplan_registry.json")

    (flow_json / "template_registry.json").write_text(
        json.dumps({"types": {"flow_plans": {"prefix": "FPLAN"}}}), encoding="utf-8"
    )
    (flow_json / "fplan_registry.json").write_text(
        json.dumps(
            {
                "plans": {
                    "0001": {
                        "subject": "An open plan",
                        "status": "open",
                        "created": "2026-09-15T10:00:00+00:00",
                        "location": str(root),
                        "file_path": str(root / "FPLAN-0001_an_open_plan_2026-09-15.md"),
                    }
                },
                "next_number": 2,
            }
        ),
        encoding="utf-8",
    )
    return root


def _write_dashboard(root: Path, data: dict | None = None) -> Path:
    """Put a dashboard file in place so the section writer will write to it."""
    path = root / "DASHBOARD.local.json"
    path.write_text(json.dumps(data if data is not None else {"branch": "FLOW", "sections": {}}), encoding="utf-8")
    return path


class TestDelegation:
    """update_dashboard_local is the section writer aimed at Flow's own root."""

    def test_calls_section_writer_with_flow_root(self, flow_root):
        with patch(f"{_MOD}.push_flow_to_branch_dashboard", return_value=True) as writer:
            assert update_local.update_dashboard_local() is True
        writer.assert_called_once_with(flow_root)

    def test_returns_false_when_writer_fails(self, flow_root):
        with patch(f"{_MOD}.push_flow_to_branch_dashboard", return_value=False):
            assert update_local.update_dashboard_local() is False

    def test_returns_false_when_flow_has_no_dashboard(self, flow_root):
        """No dashboard file means no branch to write to — refuse, never create."""
        assert update_local.update_dashboard_local() is False
        assert not (flow_root / "DASHBOARD.local.json").exists()


class TestNoTopLevelFlowPlansKey:
    """The regression this delegation exists to end."""

    def test_write_leaves_no_top_level_flow_plans_key(self, flow_root):
        path = _write_dashboard(flow_root)

        assert update_local.update_dashboard_local() is True

        written = json.loads(path.read_text(encoding="utf-8"))
        assert "flow_plans" not in written
        assert written["sections"]["flow"]["managed_by"] == "flow"
        assert written["sections"]["flow"]["active_plans"] == 1

    def test_existing_top_level_key_is_not_re_added_after_removal(self, flow_root):
        """A card carrying the old key keeps whatever is on disk, but we never add it."""
        path = _write_dashboard(flow_root, {"branch": "FLOW", "sections": {}})

        update_local.update_dashboard_local()
        first = json.loads(path.read_text(encoding="utf-8"))
        update_local.update_dashboard_local()
        second = json.loads(path.read_text(encoding="utf-8"))

        assert "flow_plans" not in first
        assert "flow_plans" not in second

    def test_other_sections_are_preserved(self, flow_root):
        path = _write_dashboard(
            flow_root,
            {"branch": "FLOW", "sections": {"memory": {"managed_by": "memory", "vectors_stored": 265}}},
        )

        assert update_local.update_dashboard_local() is True

        written = json.loads(path.read_text(encoding="utf-8"))
        assert written["sections"]["memory"]["vectors_stored"] == 265
        assert "flow" in written["sections"]
