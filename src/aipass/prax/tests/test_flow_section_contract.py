#!/usr/bin/env python3
# =================== AIPass ====================
# Name: test_flow_section_contract.py
# Description: sections.flow has two writers — both must build the same shape
# Version: 1.0.0
# Created: 2026-08-16
# Modified: 2026-08-16
# =============================================

"""Contract cover for the 2026-08-16 sections.flow handoff (@devpulse dispatch).

``sections.flow`` is written by TWO services: @flow's ``push_flow_to_branch_dashboard``
and prax's dashboard refresh. Both assign the section wholesale, so last writer
wins. @flow's module went to 2.0.0 with a five-key contract
(``managed_by``/``active_plans``/``open_recent``/``recently_closed``/``total_plans``);
prax's refresh still built the old three-key block, so every refresh silently
deleted ``open_recent`` and ``total_plans`` until flow's next push.

The invariant, same species as the quick_status one in test_dashboard_merge.py:
**no writer deletes a key it did not write** — applied here at section level.

Two things this file pins that the dispatch did not ask for, both found while
building it:

1. The old ``_extract_flow_section`` read the central's TOP-LEVEL ``recently_closed``,
   which is the newest 5 closed plans FLEET-WIDE. Every branch's dashboard was
   published other branches' closed plans. The per-branch block was there the
   whole time at ``branches.<name>``.
2. ``total_plans`` is NOT derivable from PLANS.central.json. The only per-branch
   closed number there (``branches.<name>.statistics.total_closed``) is capped at
   5 by construction, so prax preserves flow's value rather than inventing one.

Modules are imported inside each test — conftest.py installs autouse sys.modules
mocks that must be in place first.
"""

import importlib
import sys
from datetime import datetime, timedelta, timezone

import pytest


REFRESH_PATH = "aipass.prax.apps.handlers.dashboard.refresh"

# @flow's published contract, pinned in their
# tests/test_push_branch_dashboard.py::test_full_section_key_set_is_exactly_the_contract.
# ``last_updated`` is not in flow's builder — write_section stamps it — but prax's
# refresh writes the file directly, so it stamps its own.
FLOW_CONTRACT_KEYS = {"managed_by", "active_plans", "open_recent", "recently_closed", "total_plans"}


def _load(module_path: str):
    """Import (or reimport) a dashboard handler under the active mocks."""
    sys.modules.pop(module_path, None)
    module = importlib.import_module(module_path)
    return importlib.reload(module)


def _plan(plan_id: str, branch: str, created: str, subject: str = "A plan") -> dict:
    """An open-plan row shaped the way PLANS.central.json carries it."""
    return {
        "plan_id": plan_id,
        "subject": subject,
        "status": "open",
        "created": created,
        "branch": branch,
        "relative_path": branch,
    }


def _recent(days_ago: float = 1) -> str:
    """An ISO close timestamp inside @flow's 7-day publish window."""
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


def _closed(plan_id: str, branch: str, closed: str = "", subject: str = "Done") -> dict:
    """A closed-plan row shaped the way PLANS.central.json carries it."""
    return {
        "plan_id": plan_id,
        "subject": subject,
        "status": "closed",
        "created": "2026-08-01T00:00:00+00:00",
        "closed": closed or _recent(),
        "branch": branch,
        "relative_path": branch,
    }


def _centrals(branch: str = "prax", active=None, closed=None, extra_branches=None) -> dict:
    """Build a centrals dict with the per-branch block the real file carries."""
    active = active if active is not None else []
    closed = closed if closed is not None else []
    branches = {
        branch: {
            "branch_name": branch.upper(),
            "active_plans": active,
            "recently_closed": closed,
            "statistics": {"active_count": len(active), "total_closed": len(closed)},
            "last_updated": "2026-08-16T20:00:00+00:00",
        }
    }
    if extra_branches:
        branches.update(extra_branches)

    # Top-level arrays are the FLEET-WIDE roll-up — every branch's rows, mixed.
    all_active = [p for b in branches.values() for p in b.get("active_plans", [])]
    all_closed = [p for b in branches.values() for p in b.get("recently_closed", [])]
    return {
        "plans": {
            "generated_at": "2026-08-16T20:00:00+00:00",
            "branches": branches,
            "active_plans": all_active,
            "recently_closed": all_closed,
        }
    }


# ═══════════════════════════════════════════════════════════
# 1. The five-key contract
# ═══════════════════════════════════════════════════════════


class TestFiveKeyContract:
    """prax's refresh must build the same key set @flow's push builds."""

    def test_section_carries_every_contract_key(self):
        """RED before this round: open_recent and total_plans were absent."""
        refresh = _load(REFRESH_PATH)
        section = refresh._extract_flow_section(_centrals(active=[_plan("FPLAN-0001", "prax", "2026-08-10")]), "PRAX")

        assert FLOW_CONTRACT_KEYS <= set(section), f"missing: {FLOW_CONTRACT_KEYS - set(section)}"

    def test_section_invents_no_key_outside_the_contract(self):
        """New keys are a deliberate act, not a drift — last_updated excepted."""
        refresh = _load(REFRESH_PATH)
        section = refresh._extract_flow_section(_centrals(), "PRAX")

        assert set(section) - FLOW_CONTRACT_KEYS == {"last_updated"}

    def test_managed_by_still_names_flow(self):
        """prax builds the block; @flow owns it."""
        refresh = _load(REFRESH_PATH)
        assert refresh._extract_flow_section(_centrals(), "PRAX")["managed_by"] == "flow"

    def test_empty_central_still_matches_the_contract(self):
        """The no-plans path is a shape too — it used to return three keys."""
        refresh = _load(REFRESH_PATH)
        section = refresh._extract_flow_section({}, "PRAX")

        assert FLOW_CONTRACT_KEYS <= set(section)
        assert section["active_plans"] == 0
        assert section["open_recent"] == []
        assert section["recently_closed"] == []


# ═══════════════════════════════════════════════════════════
# 2. active_plans — the int count
# ═══════════════════════════════════════════════════════════


class TestActivePlansCount:
    """active_plans is an int, and it counts THIS branch only."""

    def test_active_plans_is_an_int_count(self):
        refresh = _load(REFRESH_PATH)
        centrals = _centrals(active=[_plan(f"FPLAN-000{i}", "prax", f"2026-08-1{i}") for i in range(1, 4)])
        section = refresh._extract_flow_section(centrals, "PRAX")

        assert section["active_plans"] == 3
        assert isinstance(section["active_plans"], int)

    def test_other_branches_plans_are_not_counted(self):
        """The per-branch block is the source; the fleet roll-up is not."""
        refresh = _load(REFRESH_PATH)
        centrals = _centrals(
            active=[_plan("FPLAN-0001", "prax", "2026-08-10")],
            extra_branches={
                "devpulse": {
                    "active_plans": [_plan(f"DPLAN-030{i}", "devpulse", "2026-08-15") for i in range(4)],
                    "recently_closed": [],
                }
            },
        )
        section = refresh._extract_flow_section(centrals, "PRAX")

        assert section["active_plans"] == 1


# ═══════════════════════════════════════════════════════════
# 3. open_recent — the bounded window
# ═══════════════════════════════════════════════════════════


class TestOpenRecent:
    """Entry shape and ordering must match @flow's _build_open_recent exactly."""

    def test_entry_shape_matches_flow(self):
        """flow publishes {plan_id, subject, created} — nothing more."""
        refresh = _load(REFRESH_PATH)
        centrals = _centrals(active=[_plan("FPLAN-0001", "prax", "2026-08-10T09:00:00+00:00", "Log rotation")])
        entry = refresh._extract_flow_section(centrals, "PRAX")["open_recent"][0]

        assert entry == {
            "plan_id": "FPLAN-0001",
            "subject": "Log rotation",
            "created": "2026-08-10T09:00:00+00:00",
        }

    def test_newest_first(self):
        refresh = _load(REFRESH_PATH)
        centrals = _centrals(
            active=[
                _plan("FPLAN-0001", "prax", "2026-08-01T00:00:00+00:00"),
                _plan("FPLAN-0003", "prax", "2026-08-03T00:00:00+00:00"),
                _plan("FPLAN-0002", "prax", "2026-08-02T00:00:00+00:00"),
            ]
        )
        section = refresh._extract_flow_section(centrals, "PRAX")

        assert [e["plan_id"] for e in section["open_recent"]] == ["FPLAN-0003", "FPLAN-0002", "FPLAN-0001"]

    def test_capped_at_five_while_the_count_tells_the_truth(self):
        """The window is bounded; active_plans is what stops 5 rows reading as all."""
        refresh = _load(REFRESH_PATH)
        centrals = _centrals(active=[_plan(f"FPLAN-{i:04d}", "prax", f"2026-08-{i:02d}") for i in range(1, 23)])
        section = refresh._extract_flow_section(centrals, "PRAX")

        assert len(section["open_recent"]) == 5
        assert section["active_plans"] == 22

    def test_missing_created_sorts_last_instead_of_raising(self):
        """flow's builder tolerates it; so must this one."""
        refresh = _load(REFRESH_PATH)
        undated = _plan("FPLAN-0099", "prax", "")
        undated.pop("created")
        centrals = _centrals(active=[undated, _plan("FPLAN-0001", "prax", "2026-08-01T00:00:00+00:00")])
        section = refresh._extract_flow_section(centrals, "PRAX")

        assert [e["plan_id"] for e in section["open_recent"]] == ["FPLAN-0001", "FPLAN-0099"]
        assert section["open_recent"][-1]["created"] == ""

    def test_no_unbounded_list_ships_anywhere_in_the_section(self):
        """Patrick's ruling, applied to prax's writer too."""
        refresh = _load(REFRESH_PATH)
        centrals = _centrals(active=[_plan(f"FPLAN-{i:04d}", "prax", f"2026-08-{i:02d}") for i in range(1, 23)])
        section = refresh._extract_flow_section(centrals, "PRAX")

        oversized = [k for k, v in section.items() if isinstance(v, list) and len(v) > 5]
        assert oversized == [], f"unbounded list still published: {oversized}"


# ═══════════════════════════════════════════════════════════
# 4. recently_closed — the misattribution bug
# ═══════════════════════════════════════════════════════════


class TestRecentlyClosed:
    """The bug found while building: every branch published the fleet's closures."""

    def test_only_this_branchs_closures_are_published(self):
        """RED before this round: the fleet-wide top-level list went to everyone."""
        refresh = _load(REFRESH_PATH)
        centrals = _centrals(
            closed=[_closed("FPLAN-0378", "prax", subject="Mine")],
            extra_branches={
                "baud": {
                    "active_plans": [],
                    "recently_closed": [_closed(f"FPLAN-042{i}", "baud", subject="Not mine") for i in range(4)],
                }
            },
        )
        section = refresh._extract_flow_section(centrals, "PRAX")

        assert [e["id"] for e in section["recently_closed"]] == ["FPLAN-0378"]
        assert all(e["subject"] == "Mine" for e in section["recently_closed"])

    def test_entry_shape_matches_flow(self):
        """flow publishes {id, subject, closed}; prax used to write {plan_id, subject}."""
        refresh = _load(REFRESH_PATH)
        closed_at = _recent()
        centrals = _centrals(closed=[_closed("FPLAN-0378", "prax", closed_at, "Log rotation")])
        entry = refresh._extract_flow_section(centrals, "PRAX")["recently_closed"][0]

        assert entry == {"id": "FPLAN-0378", "subject": "Log rotation", "closed": closed_at}

    def test_newest_first_and_capped_at_five(self):
        refresh = _load(REFRESH_PATH)
        centrals = _centrals(closed=[_closed(f"FPLAN-{i:04d}", "prax", _recent(i * 0.5)) for i in range(1, 9)])
        section = refresh._extract_flow_section(centrals, "PRAX")

        assert len(section["recently_closed"]) == 5
        assert [e["id"] for e in section["recently_closed"]][0] == "FPLAN-0001"


class TestClosedWindow:
    """The age window @flow's push applies — prax applied none, so cards flickered.

    Live on 2026-08-16: @api's card carried 2 closed rows after a flow push and 5
    after a prax refresh, the oldest from May, with no plan closing in between.
    """

    def test_plans_closed_before_the_window_are_dropped(self):
        refresh = _load(REFRESH_PATH)
        centrals = _centrals(
            closed=[
                _closed("FPLAN-0428", "prax", _recent(2), "This week"),
                _closed("FPLAN-0212", "prax", _recent(95), "Back in May"),
            ]
        )
        section = refresh._extract_flow_section(centrals, "PRAX")

        assert [e["id"] for e in section["recently_closed"]] == ["FPLAN-0428"]

    def test_the_window_is_flows_seven_days(self):
        refresh = _load(REFRESH_PATH)
        assert refresh.CLOSED_WINDOW_DAYS == 7

        centrals = _centrals(
            closed=[
                _closed("FPLAN-0001", "prax", _recent(6.9), "Just inside"),
                _closed("FPLAN-0002", "prax", _recent(7.1), "Just outside"),
            ]
        )
        section = refresh._extract_flow_section(centrals, "PRAX")

        assert [e["id"] for e in section["recently_closed"]] == ["FPLAN-0001"]

    def test_a_plan_with_no_close_timestamp_never_ships(self):
        """flow's rule: falsy timestamp is skipped outright."""
        refresh = _load(REFRESH_PATH)
        centrals = _centrals(closed=[_closed("FPLAN-0001", "prax", closed="x")])
        centrals["plans"]["branches"]["prax"]["recently_closed"][0]["closed"] = ""

        assert refresh._extract_flow_section(centrals, "PRAX")["recently_closed"] == []

    def test_an_unparseable_timestamp_ships_anyway(self):
        """flow includes it rather than letting a plan vanish on a bad field."""
        refresh = _load(REFRESH_PATH)
        centrals = _centrals(closed=[_closed("FPLAN-0001", "prax", "last tuesday")])
        section = refresh._extract_flow_section(centrals, "PRAX")

        assert [e["id"] for e in section["recently_closed"]] == ["FPLAN-0001"]


# ═══════════════════════════════════════════════════════════
# 5. total_plans — the key prax cannot source
# ═══════════════════════════════════════════════════════════


class TestTotalPlansPreserved:
    """prax cannot compute total_plans, so it carries flow's value instead."""

    def test_flows_value_survives_a_prax_refresh(self):
        """THE clobber this round exists to close."""
        refresh = _load(REFRESH_PATH)
        section = refresh._extract_flow_section(_centrals(), "PRAX", existing={"total_plans": 30})

        assert section["total_plans"] == 30

    def test_absent_existing_section_reports_zero_not_a_guess(self):
        """No prior value and no honest source: 0, never a derived number."""
        refresh = _load(REFRESH_PATH)
        assert refresh._extract_flow_section(_centrals(), "PRAX")["total_plans"] == 0

    def test_truncated_central_statistic_is_never_used_as_the_total(self):
        """branches.<name>.statistics.total_closed is capped at 5 by construction.

        Measured 2026-08-16: all 44 branches reported total_closed <= 5 — @flow's
        aggregate feeds the already-capped recently_closed list back in as the
        closed universe. A branch with 104 closed plans reports 5. Deriving
        total_plans from it would publish a knowingly wrong number.
        """
        refresh = _load(REFRESH_PATH)
        centrals = _centrals(
            active=[_plan("FPLAN-0001", "prax", "2026-08-10")],
            closed=[_closed(f"FPLAN-{i:04d}", "prax", f"2026-08-{i:02d}T10:00:00+00:00") for i in range(1, 6)],
        )
        centrals["plans"]["branches"]["prax"]["statistics"]["total_closed"] = 5

        section = refresh._extract_flow_section(centrals, "PRAX", existing={"total_plans": 105})

        # 1 active + 5 "total_closed" would be 6. The real total is 105.
        assert section["total_plans"] == 105

    def test_a_real_refresh_does_not_delete_flows_keys(self, tmp_path):
        """End-to-end mirror of flow's test_push_preserves_another_services_todo_count."""
        refresh = _load(REFRESH_PATH)
        branch = tmp_path / "prax"
        (branch / ".trinity").mkdir(parents=True)
        (branch / ".ai_mail.local").mkdir(parents=True)
        (branch / "DASHBOARD.local.json").write_text(
            '{"branch": "PRAX", "quick_status": {}, "sections": {"flow": '
            '{"managed_by": "flow", "active_plans": 4, "open_recent": [], '
            '"recently_closed": [], "total_plans": 12}}}',
            encoding="utf-8",
        )

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(refresh, "read_all_centrals", lambda: _centrals())
            refresh.refresh_single_dashboard(branch)

        import json

        section = json.loads((branch / "DASHBOARD.local.json").read_text(encoding="utf-8"))["sections"]["flow"]
        assert section["total_plans"] == 12, "prax refresh deleted a key it cannot write"
        assert FLOW_CONTRACT_KEYS <= set(section)
