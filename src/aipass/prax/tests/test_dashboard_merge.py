#!/usr/bin/env python3
# =================== AIPass ====================
# Name: test_dashboard_merge.py
# Description: quick_status has many writers — none may delete another's key
# Version: 1.0.0
# Created: 2026-08-13
# Modified: 2026-08-13
# =============================================

"""Regression cover for the 2026-08-12 quick_status clobber (@flow, DPLAN-0290 item 4).

DASHBOARD.local.json's quick_status block has several writers. Each one used to
build a fresh dict and assign it over the whole block, so every writer silently
deleted the keys it did not know about. Patrick saw the symptom on his devpulse
card: 0 todos while local.json held 9. @flow fixed their push and found the
mirror here — prax refresh drops their ``commons_mentions`` on every run.

The invariant both sides now hold: **no writer deletes a key it did not write.**

Second defect, same file: the calculator existed in THREE near-identical copies
(status.py, refresh.py, operations.py) and only one had grown a guard for a
list-shaped ``active_plans``. flow's section writes a list, so the two unguarded
copies raise TypeError on it. The copies are the reason one guard was missing,
so the drift is pinned shut here too.

Modules are imported inside each test — conftest.py installs autouse sys.modules
mocks that must be in place first.
"""

import importlib
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest


STATUS_PATH = "aipass.prax.apps.handlers.dashboard.status"
REFRESH_PATH = "aipass.prax.apps.handlers.dashboard.refresh"
OPS_PATH = "aipass.prax.apps.handlers.dashboard.operations"
PUSHER_PATH = "aipass.prax.apps.handlers.dashboard.template_pusher"


def _load(module_path: str):
    """Import (or reimport) a dashboard handler under the active mocks."""
    sys.modules.pop(module_path, None)
    module = importlib.import_module(module_path)
    return importlib.reload(module)


# A key only @flow writes. prax must carry it through untouched.
FOREIGN = {"commons_mentions": 4}


def _seed_branch(tmp_path: Path, quick_status: dict, todos: int = 2) -> Path:
    """Build a branch dir with a dashboard, a local.json and an inbox."""
    branch = tmp_path / "prax"
    (branch / ".trinity").mkdir(parents=True)
    (branch / ".ai_mail.local").mkdir(parents=True)

    (branch / "DASHBOARD.local.json").write_text(
        json.dumps(
            {
                "branch": "PRAX",
                "quick_status": quick_status,
                "sections": {"flow": {"managed_by": "flow", "active_plans": 3}},
            }
        ),
        encoding="utf-8",
    )
    (branch / ".trinity" / "local.json").write_text(
        json.dumps({"todos": [{"task": f"t{i}"} for i in range(todos)]}), encoding="utf-8"
    )
    (branch / ".ai_mail.local" / "inbox.json").write_text(
        json.dumps({"messages": [{"status": "new"}, {"status": "opened"}]}), encoding="utf-8"
    )
    return branch


def _read_quick_status(branch: Path) -> dict:
    return json.loads((branch / "DASHBOARD.local.json").read_text(encoding="utf-8"))["quick_status"]


# ---------------------------------------------------------------------------
# Finding 1 — no writer deletes a key it did not write
# ---------------------------------------------------------------------------


class TestForeignKeysSurviveEveryWriter:
    """commons_mentions is flow's. Every prax write path must carry it through."""

    def test_merge_preserves_unknown_keys(self):
        status = _load(STATUS_PATH)
        merged = status.merge_quick_status(
            {"commons_mentions": 4, "new_mail": 9}, {"new_mail": 1, "summary": "1 new emails"}
        )
        assert merged["commons_mentions"] == 4

    def test_merge_lets_owned_keys_win(self):
        """Preserving foreign keys must not freeze prax's own counters."""
        status = _load(STATUS_PATH)
        merged = status.merge_quick_status({"new_mail": 9}, {"new_mail": 1})
        assert merged["new_mail"] == 1

    def test_merge_tolerates_missing_existing_block(self):
        status = _load(STATUS_PATH)
        assert status.merge_quick_status(None, {"new_mail": 0})["new_mail"] == 0

    def test_write_section_preserves_foreign_key(self, tmp_path):
        ops = _load(OPS_PATH)
        branch = _seed_branch(tmp_path, {"new_mail": 0, **FOREIGN})
        ops.write_section(branch, "memory", {"managed_by": "memory", "vectors_stored": 7})
        assert _read_quick_status(branch)["commons_mentions"] == 4

    def test_update_section_preserves_foreign_key(self, tmp_path):
        ops = _load(OPS_PATH)
        status = _load(STATUS_PATH)
        branch = _seed_branch(tmp_path, {"new_mail": 0, **FOREIGN})
        ops.update_section(branch, "memory", {"managed_by": "memory"}, {}, status.calculate_quick_status)
        assert _read_quick_status(branch)["commons_mentions"] == 4

    def test_refresh_single_preserves_foreign_key(self, tmp_path):
        """The live path: `drone @prax dashboard refresh @prax`."""
        refresh = _load(REFRESH_PATH)
        branch = _seed_branch(tmp_path, {"new_mail": 0, **FOREIGN})
        with patch.object(refresh, "read_all_centrals", return_value={}):
            refresh.refresh_single_dashboard(branch)
        assert _read_quick_status(branch)["commons_mentions"] == 4

    def test_refresh_single_still_recomputes_owned_keys(self, tmp_path):
        """Preservation must not turn refresh into a no-op."""
        refresh = _load(REFRESH_PATH)
        branch = _seed_branch(tmp_path, {"new_mail": 99, "todo_count": 99, **FOREIGN}, todos=2)
        with patch.object(refresh, "read_all_centrals", return_value={}):
            refresh.refresh_single_dashboard(branch)
        quick = _read_quick_status(branch)
        assert quick["todo_count"] == 2
        assert quick["new_mail"] == 1

    def test_canary_plain_assignment_drops_the_key(self):
        """Proof the assertions above can fail: replacing the block is the bug."""
        block = {"new_mail": 0, **FOREIGN}
        block = {"new_mail": 1, "summary": "1 new emails"}
        assert "commons_mentions" not in block


# ---------------------------------------------------------------------------
# Finding 2 — a flow-shaped section must not raise
# ---------------------------------------------------------------------------

# The LEGACY flow shape: active_plans as a list of plan dicts, active_count as
# the int. Retired by @flow's module 2.0.0 (2026-08-16) — both writers now publish
# an int — but dashboards written before that date carry this on disk until their
# next write, so the tolerance must survive.
FLOW_LIST_SECTION = {
    "flow": {
        "managed_by": "flow",
        "active_plans": [{"id": "FPLAN-0001"}, {"id": "FPLAN-0002"}],
        "active_count": 2,
    }
}


def _calculators():
    """Every entry point that computes a quick_status block."""
    return [
        ("status.calculate_quick_status", _load(STATUS_PATH).calculate_quick_status),
        ("refresh._calculate_quick_status", _load(REFRESH_PATH)._calculate_quick_status),
        ("operations._calculate_quick_status_standalone", _load(OPS_PATH)._calculate_quick_status_standalone),
        ("template_pusher._calculate_quick_status", _load(PUSHER_PATH)._calculate_quick_status),
    ]


class TestListShapedActivePlans:
    """flow's own section shape must not raise in any copy of the calculator."""

    @pytest.mark.parametrize("name,calc", _calculators())
    def test_list_shape_does_not_raise(self, name, calc, tmp_path):
        branch = _seed_branch(tmp_path, {})
        assert calc(FLOW_LIST_SECTION, branch)["active_plans"] == 2, name

    @pytest.mark.parametrize("name,calc", _calculators())
    def test_int_shape_still_works(self, name, calc, tmp_path):
        branch = _seed_branch(tmp_path, {})
        assert calc({"flow": {"active_plans": 3}}, branch)["active_plans"] == 3, name

    @pytest.mark.parametrize("name,calc", _calculators())
    def test_missing_flow_section_is_zero(self, name, calc, tmp_path):
        branch = _seed_branch(tmp_path, {})
        assert calc({}, branch)["active_plans"] == 0, name

    def test_every_calculator_agrees(self, tmp_path):
        """One calculation, four doors. Drift here is what lost the guard."""
        branch = _seed_branch(tmp_path, {})
        results = [calc(FLOW_LIST_SECTION, branch) for _name, calc in _calculators()]
        assert all(r == results[0] for r in results[1:])

    def test_canary_unguarded_comparison_raises(self):
        """Proof the guard is load-bearing: the old expression still explodes."""
        active_plans = FLOW_LIST_SECTION["flow"]["active_plans"]
        with pytest.raises(TypeError):
            _ = active_plans > 0


# ---------------------------------------------------------------------------
# Finding 3 — push-template is a fourth writer, and it deletes on purpose
# ---------------------------------------------------------------------------


class TestPushTemplateIsNotAWreckingBall:
    """`dashboard push-template` writes every branch's dashboard, fleet-wide.

    It carried its own self-contained calculator (no todo_count, no merge) and a
    deprecation list naming ``commons_mentions`` — a key @flow OWNS and writes
    (``flow/apps/handlers/dashboard/push_branch_dashboard.py``). prax used to own
    that key and retired it; the list outlived the ownership change, so one push
    would have deleted flow's key from every branch by declared policy.
    """

    def test_commons_mentions_is_not_deprecated(self):
        pusher = _load(PUSHER_PATH)
        assert "commons_mentions" not in pusher.DEPRECATED_QUICK_STATUS_KEYS

    def test_structural_update_preserves_foreign_key(self, tmp_path):
        pusher = _load(PUSHER_PATH)
        branch = _seed_branch(tmp_path, {"new_mail": 0, **FOREIGN})
        data = json.loads((branch / "DASHBOARD.local.json").read_text(encoding="utf-8"))
        pusher._apply_structural_updates(data, {}, [], branch)
        assert data["quick_status"]["commons_mentions"] == 4

    def test_structural_update_keeps_todo_count(self, tmp_path):
        """The pusher's own calculator had no todo_count at all, so it dropped it."""
        pusher = _load(PUSHER_PATH)
        branch = _seed_branch(tmp_path, {"new_mail": 0, "todo_count": 99}, todos=2)
        data = json.loads((branch / "DASHBOARD.local.json").read_text(encoding="utf-8"))
        pusher._apply_structural_updates(data, {}, [], branch)
        assert data["quick_status"]["todo_count"] == 2

    def test_structural_update_without_a_branch_stays_placeholder(self, tmp_path):
        """spawn's builder template has no .trinity/ or inbox — it must not gain counts."""
        pusher = _load(PUSHER_PATH)
        data = {"quick_status": {}, "sections": {"flow": {"active_plans": 0}}}
        pusher._apply_structural_updates(data, {}, [], None)
        assert data["quick_status"]["todo_count"] == 0
        assert data["quick_status"]["new_mail"] == 0

    def test_canary_deprecation_list_still_deletes(self):
        """Proof the first assertion can fail: the removal loop is real."""
        qs = {"commons_mentions": 4, "pending_bulletins": 1}
        for key in ["pending_bulletins", "commons_mentions"]:
            qs.pop(key, None)
        assert qs == {}


# ---------------------------------------------------------------------------
# Finding 4 — action_required must agree with the summary beside it
# ---------------------------------------------------------------------------


class TestActionRequiredMatchesItsOwnSummary:
    """@flow measured prax writing ``action_required: False`` next to ``1 todos``.

    Identical counts, opposite flag from the two writers — the same clobber
    species as Finding 1, moved out of a key and into a boolean, and it is the
    field Patrick's card reads for 'needs attention'.
    """

    @pytest.mark.parametrize("name,calc", _calculators())
    def test_todos_alone_require_action(self, name, calc, tmp_path):
        branch = _seed_branch(tmp_path, {}, todos=1)
        (branch / ".ai_mail.local" / "inbox.json").write_text(json.dumps({"messages": []}), encoding="utf-8")
        result = calc({}, branch)
        assert result["todo_count"] == 1, name
        assert result["action_required"] is True, name

    @pytest.mark.parametrize("name,calc", _calculators())
    def test_all_clear_requires_no_action(self, name, calc, tmp_path):
        branch = _seed_branch(tmp_path, {}, todos=0)
        (branch / ".ai_mail.local" / "inbox.json").write_text(json.dumps({"messages": []}), encoding="utf-8")
        result = calc({}, branch)
        assert result["summary"] == "All clear", name
        assert result["action_required"] is False, name

    def test_canary_old_rule_disagrees_with_its_summary(self):
        """Proof of the reported defect: the retired expression ignores todos."""
        new_mail, active_plans, todo_count = 0, 0, 1
        assert (new_mail > 0 or active_plans > 0) is False
        assert f"{todo_count} todos"
