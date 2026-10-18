# =================== AIPass ====================
# Name: test_flow_section_contract.py
# Description: sections.flow has two writers — both must build the same shape
# Version: 1.2.0
# Created: 2026-08-16
# Modified: 2026-10-17
# =============================================

"""Tests for apps/handlers/dashboard/refresh.py."""

# sections.flow has two writers (@flow's push and prax's refresh), each assigning it
# wholesale, so last writer wins: no writer may delete a key it did not write.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(through_the_command) — refresh_all_dashboards, covered by tests/test_operations.py
# seedgo: no-test-needed(through_the_command) — _calculate_quick_status, covered by tests/test_dashboard_merge.py
# seedgo: no-test-needed(through_the_command) — plugin refresh(), covered by tests/test_devpulse_dashboard_plugin.py
# seedgo: no-test-needed(dead_code) — _extract_ai_mail_section's block, which refresh pops before save
# seedgo: no-test-needed(json_structure) — refresh_all_dashboards' log_operation record, covered by that row

import json
from datetime import datetime, timedelta, timezone

import pytest

from aipass.prax.apps.handlers.dashboard import operations
from aipass.prax.apps.handlers.dashboard import refresh

#: The world _flow_section refreshes in: this test's tmp_path and monkeypatch.
_WORLD: dict = {}


@pytest.fixture(autouse=True)
def _refresh_world(monkeypatch, tmp_path) -> None:
    """Hand _flow_section this test's tmp_path; refresh reads the centrals it was handed."""
    monkeypatch.setitem(_WORLD, "tmp_path", tmp_path)
    monkeypatch.setitem(_WORLD, "calls", 0)
    monkeypatch.setitem(_WORLD, "centrals", {})
    monkeypatch.setattr(refresh, "read_all_centrals", lambda: _WORLD["centrals"])


def _flow_section(centrals: dict, branch_name: str, existing: "dict | None" = None) -> dict:
    """sections.flow as refresh_single_dashboard writes it for a fresh branch under tmp_path."""
    _WORLD["calls"] += 1
    branch = _WORLD["tmp_path"] / f"refresh_{_WORLD['calls']}" / branch_name.lower()
    branch.mkdir(parents=True)
    if existing is not None:
        (branch / "DASHBOARD.local.json").write_text(json.dumps({"sections": {"flow": existing}}), encoding="utf-8")
    _WORLD["centrals"] = centrals

    result = refresh.refresh_single_dashboard(branch)

    assert result == {"status": "success", "branch": branch_name}
    return json.loads((branch / "DASHBOARD.local.json").read_text(encoding="utf-8"))["sections"]["flow"]


# @flow's contract, pinned in their test_push_branch_dashboard.py; last_updated is
# outside it because prax's refresh writes the file directly and stamps its own.
FLOW_CONTRACT_KEYS = {"managed_by", "active_plans", "open_recent", "recently_closed", "total_plans"}


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


class TestFiveKeyContract:
    """prax's refresh must build the same key set @flow's push builds."""

    def test_section_carries_every_contract_key(self):
        """open_recent and total_plans must be present alongside the older keys."""
        section = _flow_section(_centrals(active=[_plan("FPLAN-0001", "prax", "2026-08-10")]), "PRAX")

        assert FLOW_CONTRACT_KEYS <= set(section), f"missing: {FLOW_CONTRACT_KEYS - set(section)}"

    def test_section_invents_no_key_outside_the_contract(self):
        """New keys are a deliberate act, not a drift — last_updated excepted."""
        section = _flow_section(_centrals(), "PRAX")

        assert set(section) - FLOW_CONTRACT_KEYS == {"last_updated"}

    def test_managed_by_still_names_flow(self):
        """prax builds the block; @flow owns it."""
        assert _flow_section(_centrals(), "PRAX")["managed_by"] == "flow"

    def test_empty_central_still_matches_the_contract(self):
        """The no-plans path is a shape too — it used to return three keys."""
        section = _flow_section({}, "PRAX")

        assert FLOW_CONTRACT_KEYS <= set(section)
        assert section["active_plans"] == 0
        assert section["open_recent"] == []
        assert section["recently_closed"] == []


class TestActivePlansCount:
    """active_plans is an int, and it counts THIS branch only."""

    def test_active_plans_is_an_int_count(self):
        centrals = _centrals(active=[_plan(f"FPLAN-000{i}", "prax", f"2026-08-1{i}") for i in range(1, 4)])
        section = _flow_section(centrals, "PRAX")

        assert section["active_plans"] == 3
        assert isinstance(section["active_plans"], int)

    def test_other_branches_plans_are_not_counted(self):
        """The per-branch block is the source; the fleet roll-up is not."""
        centrals = _centrals(
            active=[_plan("FPLAN-0001", "prax", "2026-08-10")],
            extra_branches={
                "devpulse": {
                    "active_plans": [_plan(f"DPLAN-030{i}", "devpulse", "2026-08-15") for i in range(4)],
                    "recently_closed": [],
                }
            },
        )
        section = _flow_section(centrals, "PRAX")

        assert section["active_plans"] == 1


class TestOpenRecent:
    """Entry shape and ordering must match @flow's _build_open_recent exactly."""

    def test_entry_shape_matches_flow(self):
        """flow publishes {plan_id, subject, created} — nothing more."""
        centrals = _centrals(active=[_plan("FPLAN-0001", "prax", "2026-08-10T09:00:00+00:00", "Log rotation")])
        entry = _flow_section(centrals, "PRAX")["open_recent"][0]

        assert entry == {
            "plan_id": "FPLAN-0001",
            "subject": "Log rotation",
            "created": "2026-08-10T09:00:00+00:00",
        }

    def test_newest_first(self):
        centrals = _centrals(
            active=[
                _plan("FPLAN-0001", "prax", "2026-08-01T00:00:00+00:00"),
                _plan("FPLAN-0003", "prax", "2026-08-03T00:00:00+00:00"),
                _plan("FPLAN-0002", "prax", "2026-08-02T00:00:00+00:00"),
            ]
        )
        section = _flow_section(centrals, "PRAX")

        assert [e["plan_id"] for e in section["open_recent"]] == ["FPLAN-0003", "FPLAN-0002", "FPLAN-0001"]

    def test_capped_at_five_while_the_count_tells_the_truth(self):
        """The window is bounded; active_plans is what stops 5 rows reading as all."""
        centrals = _centrals(active=[_plan(f"FPLAN-{i:04d}", "prax", f"2026-08-{i:02d}") for i in range(1, 23)])
        section = _flow_section(centrals, "PRAX")

        assert len(section["open_recent"]) == 5
        assert section["active_plans"] == 22

    def test_missing_created_sorts_last_instead_of_raising(self):
        """flow's builder tolerates it; so must this one."""
        undated = _plan("FPLAN-0099", "prax", "")
        undated.pop("created")
        centrals = _centrals(active=[undated, _plan("FPLAN-0001", "prax", "2026-08-01T00:00:00+00:00")])
        section = _flow_section(centrals, "PRAX")

        assert [e["plan_id"] for e in section["open_recent"]] == ["FPLAN-0001", "FPLAN-0099"]
        assert section["open_recent"][-1]["created"] == ""

    def test_no_unbounded_list_ships_anywhere_in_the_section(self):
        """No list in the section exceeds five rows, on prax's writer too."""
        centrals = _centrals(active=[_plan(f"FPLAN-{i:04d}", "prax", f"2026-08-{i:02d}") for i in range(1, 23)])
        section = _flow_section(centrals, "PRAX")

        oversized = [k for k, v in section.items() if isinstance(v, list) and len(v) > 5]
        assert oversized == [], f"unbounded list still published: {oversized}"


class TestSubjectCap:
    """A plan subject is a glance: truncate to the cap, never refuse (that drops the plan)."""

    def test_an_essay_subject_is_cut_to_the_cap_in_open_recent(self):
        essay = "FPLAN-0593 " + "startup floor fleet-wide " * 20
        centrals = _centrals(active=[_plan("FPLAN-0593", "prax", "2026-09-15T09:00:00+00:00", essay)])
        subject = _flow_section(centrals, "PRAX")["open_recent"][0]["subject"]

        assert len(essay) > 400, "the row this pins is an essay, not a subject"
        assert len(subject) <= 120
        assert subject.endswith("...")
        assert essay.startswith(subject[: -len("...")].rstrip())

    def test_an_essay_subject_is_cut_to_the_cap_in_recently_closed(self):
        essay = "DPLAN-0339 follow-up: " + "trigger imported inside the fire sites " * 10
        centrals = _centrals(closed=[_closed("FPLAN-0555", "prax", subject=essay)])
        subject = _flow_section(centrals, "PRAX")["recently_closed"][0]["subject"]

        assert len(subject) <= 120
        assert subject.endswith("...")

    def test_a_short_subject_is_published_whole(self):
        """The cap cuts essays; it must not touch the subjects that already fit."""
        centrals = _centrals(
            active=[_plan("FPLAN-0001", "prax", "2026-08-10T09:00:00+00:00", "Log rotation")],
            closed=[_closed("FPLAN-0002", "prax", subject="Done")],
        )
        section = _flow_section(centrals, "PRAX")

        assert section["open_recent"][0]["subject"] == "Log rotation"
        assert section["recently_closed"][0]["subject"] == "Done"

    def test_the_cut_is_the_shared_number_not_a_second_copy(self):
        """One number for every writer: refresh, the devpulse plugin, @flow's push."""
        assert refresh.cap_subject is operations.cap_subject
        assert operations.SUBJECT_CAP == 120


class TestRecentlyClosed:
    """Each branch publishes only its own closures, never the fleet's."""

    def test_only_this_branchs_closures_are_published(self):
        """The fleet-wide top-level list must not reach every branch."""
        centrals = _centrals(
            closed=[_closed("FPLAN-0378", "prax", subject="Mine")],
            extra_branches={
                "baud": {
                    "active_plans": [],
                    "recently_closed": [_closed(f"FPLAN-042{i}", "baud", subject="Not mine") for i in range(4)],
                }
            },
        )
        section = _flow_section(centrals, "PRAX")

        assert [e["id"] for e in section["recently_closed"]] == ["FPLAN-0378"]
        assert all(e["subject"] == "Mine" for e in section["recently_closed"])

    def test_entry_shape_matches_flow(self):
        """flow publishes {id, subject, closed}; prax used to write {plan_id, subject}."""
        closed_at = _recent()
        centrals = _centrals(closed=[_closed("FPLAN-0378", "prax", closed_at, "Log rotation")])
        entry = _flow_section(centrals, "PRAX")["recently_closed"][0]

        assert entry == {"id": "FPLAN-0378", "subject": "Log rotation", "closed": closed_at}

    def test_newest_first_and_capped_at_five(self):
        centrals = _centrals(closed=[_closed(f"FPLAN-{i:04d}", "prax", _recent(i * 0.5)) for i in range(1, 9)])
        section = _flow_section(centrals, "PRAX")

        assert len(section["recently_closed"]) == 5
        assert [e["id"] for e in section["recently_closed"]][0] == "FPLAN-0001"


class TestClosedWindow:
    """The age window @flow's push applies; without it cards flicker between writers."""

    def test_plans_closed_before_the_window_are_dropped(self):
        centrals = _centrals(
            closed=[
                _closed("FPLAN-0428", "prax", _recent(2), "This week"),
                _closed("FPLAN-0212", "prax", _recent(95), "Back in May"),
            ]
        )
        section = _flow_section(centrals, "PRAX")

        assert [e["id"] for e in section["recently_closed"]] == ["FPLAN-0428"]

    def test_the_window_is_flows_seven_days(self):
        assert refresh.CLOSED_WINDOW_DAYS == 7

        centrals = _centrals(
            closed=[
                _closed("FPLAN-0001", "prax", _recent(6.9), "Just inside"),
                _closed("FPLAN-0002", "prax", _recent(7.1), "Just outside"),
            ]
        )
        section = _flow_section(centrals, "PRAX")

        assert [e["id"] for e in section["recently_closed"]] == ["FPLAN-0001"]

    def test_a_plan_with_no_close_timestamp_never_ships(self):
        """flow's rule: falsy timestamp is skipped outright."""
        centrals = _centrals(closed=[_closed("FPLAN-0001", "prax", closed="x")])
        centrals["plans"]["branches"]["prax"]["recently_closed"][0]["closed"] = ""

        assert _flow_section(centrals, "PRAX")["recently_closed"] == []

    def test_an_unparseable_timestamp_ships_anyway(self):
        """flow includes it rather than letting a plan vanish on a bad field."""
        centrals = _centrals(closed=[_closed("FPLAN-0001", "prax", "last tuesday")])
        section = _flow_section(centrals, "PRAX")

        assert [e["id"] for e in section["recently_closed"]] == ["FPLAN-0001"]


class TestTotalPlansPreserved:
    """prax cannot compute total_plans, so it carries flow's value instead."""

    def test_flows_value_survives_a_prax_refresh(self):
        """A prax refresh must not clobber flow's total_plans."""
        section = _flow_section(_centrals(), "PRAX", existing={"total_plans": 30})

        assert section["total_plans"] == 30

    def test_absent_existing_section_reports_zero_not_a_guess(self):
        """No prior value and no honest source: 0, never a derived number."""
        assert _flow_section(_centrals(), "PRAX")["total_plans"] == 0

    def test_truncated_central_statistic_is_never_used_as_the_total(self):
        """branches.<name>.statistics.total_closed is capped at 5 by construction."""
        centrals = _centrals(
            active=[_plan("FPLAN-0001", "prax", "2026-08-10")],
            closed=[_closed(f"FPLAN-{i:04d}", "prax", f"2026-08-{i:02d}T10:00:00+00:00") for i in range(1, 6)],
        )
        centrals["plans"]["branches"]["prax"]["statistics"]["total_closed"] = 5

        section = _flow_section(centrals, "PRAX", existing={"total_plans": 105})

        # 1 active + 5 "total_closed" would be 6. The real total is 105.
        assert section["total_plans"] == 105

    def test_a_real_refresh_does_not_delete_flows_keys(self, tmp_path):
        """End-to-end mirror of flow's test_push_preserves_another_services_todo_count."""
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

        section = json.loads((branch / "DASHBOARD.local.json").read_text(encoding="utf-8"))["sections"]["flow"]
        assert section["total_plans"] == 12, "prax refresh deleted a key it cannot write"
        assert FLOW_CONTRACT_KEYS <= set(section)
