"""Tests for aggregate_ops -- helper functions and aggregation implementation."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ─── Patch targets ───────────────────────────────────────
_MOD = "aipass.flow.apps.handlers.plan.aggregate_ops"


# ─── Import helpers ──────────────────────────────────────

def _import(name: str):
    """Import a function from aggregate_ops inside each test."""
    import aipass.flow.apps.handlers.plan.aggregate_ops as mod
    return getattr(mod, name)


# ═══════════════════════════════════════════════════════════
# 1. find_branch_registry
# ═══════════════════════════════════════════════════════════

class TestFindBranchRegistry:

    def test_returns_none_when_branch_path_missing(self, tmp_path):
        find_branch_registry = _import("find_branch_registry")
        missing = tmp_path / "no_such_dir"
        assert find_branch_registry(missing, "flow") is None

    def test_pattern1_flow_json(self, tmp_path):
        find_branch_registry = _import("find_branch_registry")
        registry = tmp_path / "flow_json" / "flow_registry.json"
        registry.parent.mkdir(parents=True)
        registry.write_text("{}", encoding="utf-8")
        result = find_branch_registry(tmp_path, "flow")
        assert result == registry

    def test_pattern2_branch_json(self, tmp_path):
        find_branch_registry = _import("find_branch_registry")
        registry = tmp_path / "drone_json" / "drone_registry.json"
        registry.parent.mkdir(parents=True)
        registry.write_text("{}", encoding="utf-8")
        result = find_branch_registry(tmp_path, "drone")
        assert result == registry

    def test_pattern3_bare_registry(self, tmp_path):
        find_branch_registry = _import("find_branch_registry")
        registry = tmp_path / "registry.json"
        registry.write_text("{}", encoding="utf-8")
        result = find_branch_registry(tmp_path, "any_branch")
        assert result == registry

    def test_pattern1_takes_priority(self, tmp_path):
        """Pattern 1 should be found before pattern 3."""
        find_branch_registry = _import("find_branch_registry")
        p1 = tmp_path / "flow_json" / "flow_registry.json"
        p1.parent.mkdir(parents=True)
        p1.write_text("{}", encoding="utf-8")
        p3 = tmp_path / "registry.json"
        p3.write_text("{}", encoding="utf-8")
        result = find_branch_registry(tmp_path, "flow")
        assert result == p1

    def test_returns_none_when_no_registry_files(self, tmp_path):
        find_branch_registry = _import("find_branch_registry")
        assert find_branch_registry(tmp_path, "flow") is None


# ═══════════════════════════════════════════════════════════
# 2. load_branch_registry
# ═══════════════════════════════════════════════════════════

class TestLoadBranchRegistry:

    def test_loads_valid_json(self, tmp_path):
        load_branch_registry = _import("load_branch_registry")
        data = {"plans": {"1": {"status": "open"}}, "next_number": 2}
        reg_file = tmp_path / "registry.json"
        reg_file.write_text(json.dumps(data), encoding="utf-8")
        result = load_branch_registry(reg_file)
        assert result == data

    def test_returns_empty_structure_on_invalid_json(self, tmp_path):
        load_branch_registry = _import("load_branch_registry")
        reg_file = tmp_path / "registry.json"
        reg_file.write_text("not json", encoding="utf-8")
        result = load_branch_registry(reg_file)
        assert result == {"plans": {}, "next_number": 1}

    def test_returns_empty_structure_on_missing_file(self, tmp_path):
        load_branch_registry = _import("load_branch_registry")
        result = load_branch_registry(tmp_path / "nonexistent.json")
        assert result == {"plans": {}, "next_number": 1}


# ═══════════════════════════════════════════════════════════
# 3. save_branch_registry
# ═══════════════════════════════════════════════════════════

class TestSaveBranchRegistry:

    def test_saves_valid_json(self, tmp_path):
        save_branch_registry = _import("save_branch_registry")
        reg_file = tmp_path / "registry.json"
        data = {"plans": {"1": {"status": "open"}}, "next_number": 2}
        result = save_branch_registry(reg_file, data)
        assert result is True
        saved = json.loads(reg_file.read_text(encoding="utf-8"))
        assert saved["plans"] == data["plans"]
        assert "last_updated" in saved

    def test_adds_last_updated_timestamp(self, tmp_path):
        save_branch_registry = _import("save_branch_registry")
        reg_file = tmp_path / "registry.json"
        data = {"plans": {}}
        save_branch_registry(reg_file, data)
        saved = json.loads(reg_file.read_text(encoding="utf-8"))
        assert "last_updated" in saved
        # Should be an ISO format string
        assert "T" in saved["last_updated"]

    def test_returns_false_on_write_error(self, tmp_path):
        save_branch_registry = _import("save_branch_registry")
        # Path to a directory that doesn't exist
        bad_path = tmp_path / "no_dir" / "sub" / "registry.json"
        result = save_branch_registry(bad_path, {"plans": {}})
        assert result is False


# ═══════════════════════════════════════════════════════════
# 4. extract_plan_number
# ═══════════════════════════════════════════════════════════

class TestExtractPlanNumber:

    def test_valid_plan_id(self):
        extract_plan_number = _import("extract_plan_number")
        assert extract_plan_number("FPLAN-0148") == "0148"

    def test_valid_plan_single_digit(self):
        extract_plan_number = _import("extract_plan_number")
        assert extract_plan_number("FPLAN-1") == "1"

    def test_empty_string(self):
        extract_plan_number = _import("extract_plan_number")
        assert extract_plan_number("") is None

    def test_none_input(self):
        extract_plan_number = _import("extract_plan_number")
        assert extract_plan_number(None) is None

    def test_wrong_prefix(self):
        extract_plan_number = _import("extract_plan_number")
        assert extract_plan_number("DPLAN-0001") is None

    def test_no_dash(self):
        extract_plan_number = _import("extract_plan_number")
        assert extract_plan_number("FPLAN0001") is None


# ═══════════════════════════════════════════════════════════
# 5. auto_close_plan
# ═══════════════════════════════════════════════════════════

class TestAutoClosePlan:

    def _make_registry(self, tmp_path, plans: dict) -> Path:
        reg_file = tmp_path / "registry.json"
        data = {"plans": plans, "next_number": 10}
        reg_file.write_text(json.dumps(data), encoding="utf-8")
        return reg_file

    def test_closes_open_plan(self, tmp_path):
        auto_close_plan = _import("auto_close_plan")
        reg = self._make_registry(tmp_path, {
            "0148": {"status": "open", "subject": "Test"}
        })
        result = auto_close_plan(reg, "FPLAN-0148", "flow")
        assert result is True
        saved = json.loads(reg.read_text(encoding="utf-8"))
        assert saved["plans"]["0148"]["status"] == "closed"
        assert saved["plans"]["0148"]["closed_reason"] == "auto_closed_missing_file"

    def test_returns_false_for_already_closed(self, tmp_path):
        auto_close_plan = _import("auto_close_plan")
        reg = self._make_registry(tmp_path, {
            "0001": {"status": "closed", "subject": "Done"}
        })
        result = auto_close_plan(reg, "FPLAN-0001", "flow")
        assert result is False

    def test_returns_false_for_missing_plan(self, tmp_path):
        auto_close_plan = _import("auto_close_plan")
        reg = self._make_registry(tmp_path, {})
        result = auto_close_plan(reg, "FPLAN-9999", "flow")
        assert result is False

    def test_returns_false_for_invalid_plan_id(self, tmp_path):
        auto_close_plan = _import("auto_close_plan")
        reg = self._make_registry(tmp_path, {})
        result = auto_close_plan(reg, "INVALID", "flow")
        assert result is False

    def test_returns_false_on_save_failure(self, tmp_path):
        auto_close_plan = _import("auto_close_plan")
        reg = self._make_registry(tmp_path, {
            "0001": {"status": "open", "subject": "Test"}
        })
        with patch(f"{_MOD}.save_branch_registry", return_value=False):
            result = auto_close_plan(reg, "FPLAN-0001", "flow")
        assert result is False


# ═══════════════════════════════════════════════════════════
# 6. validate_and_heal_branch
# ═══════════════════════════════════════════════════════════

class TestValidateAndHealBranch:

    def test_valid_plans_kept(self, tmp_path):
        validate_and_heal_branch = _import("validate_and_heal_branch")
        # Create an actual plan file on disk
        plan_file = tmp_path / "FPLAN-0001.md"
        plan_file.write_text("plan content", encoding="utf-8")

        branch_data = {
            "branch_path": str(tmp_path),
            "active_plans": [
                {"plan_id": "FPLAN-0001", "file_path": str(plan_file), "created": "2026-03-01"}
            ],
            "recently_closed": [],
        }
        valid, closed = validate_and_heal_branch("test", branch_data, heal=False)
        assert len(valid) == 1
        assert len(closed) == 0

    def test_missing_plans_removed_no_heal(self, tmp_path):
        validate_and_heal_branch = _import("validate_and_heal_branch")
        branch_data = {
            "branch_path": str(tmp_path),
            "active_plans": [
                {"plan_id": "FPLAN-0001", "file_path": str(tmp_path / "missing.md"), "created": "2026-03-01"}
            ],
            "recently_closed": [],
        }
        valid, closed = validate_and_heal_branch("test", branch_data, heal=False)
        assert len(valid) == 0
        assert len(closed) == 0  # heal=False so nothing auto-closed

    def test_missing_plans_healed(self, tmp_path):
        validate_and_heal_branch = _import("validate_and_heal_branch")

        # Set up a registry for auto_close_plan to work with
        reg_dir = tmp_path / "flow_json"
        reg_dir.mkdir()
        reg_file = reg_dir / "test_registry.json"
        reg_data = {
            "plans": {"0001": {"status": "open", "subject": "Test"}},
            "next_number": 2,
        }
        reg_file.write_text(json.dumps(reg_data), encoding="utf-8")

        branch_data = {
            "branch_path": str(tmp_path),
            "active_plans": [
                {"plan_id": "FPLAN-0001", "file_path": str(tmp_path / "missing.md"), "created": "2026-03-01"}
            ],
            "recently_closed": [],
        }
        with patch(f"{_MOD}.find_branch_registry", return_value=reg_file):
            valid, closed = validate_and_heal_branch("test", branch_data, heal=True)
        assert len(valid) == 0
        assert len(closed) == 1
        assert closed[0]["status"] == "closed"
        assert closed[0]["closed_reason"] == "auto_closed_missing_file"

    def test_recently_closed_preserved(self, tmp_path):
        validate_and_heal_branch = _import("validate_and_heal_branch")
        existing_closed = [
            {"plan_id": "FPLAN-0010", "status": "closed", "closed": "2026-03-20"}
        ]
        branch_data = {
            "branch_path": str(tmp_path),
            "active_plans": [],
            "recently_closed": existing_closed,
        }
        valid, closed = validate_and_heal_branch("test", branch_data, heal=False)
        assert len(valid) == 0
        assert len(closed) == 1
        assert closed[0]["plan_id"] == "FPLAN-0010"

    def test_heal_without_registry_warns(self, tmp_path):
        """When heal=True but no registry found, plans are just dropped."""
        validate_and_heal_branch = _import("validate_and_heal_branch")
        branch_data = {
            "branch_path": str(tmp_path),
            "active_plans": [
                {"plan_id": "FPLAN-0001", "file_path": str(tmp_path / "missing.md"), "created": "2026-03-01"}
            ],
            "recently_closed": [],
        }
        # No registry file on disk, find_branch_registry returns None
        valid, closed = validate_and_heal_branch("test", branch_data, heal=True)
        assert len(valid) == 0
        assert len(closed) == 0


# ═══════════════════════════════════════════════════════════
# 7. load_central
# ═══════════════════════════════════════════════════════════

class TestLoadCentral:

    def test_loads_valid_file(self, tmp_path):
        load_central = _import("load_central")
        data = {
            "generated_at": "2026-03-28T00:00:00",
            "active_plans": [{"plan_id": "FPLAN-0001"}],
            "recently_closed": [],
            "statistics": {"active_count": 1, "total_closed": 0, "recently_closed_included": 0},
            "branches": {},
            "global_statistics": {"total_active": 1, "total_closed": 0, "branches_reporting": 0},
        }
        central = tmp_path / "PLANS.central.json"
        central.write_text(json.dumps(data), encoding="utf-8")
        result = load_central(central)
        assert result["active_plans"] == data["active_plans"]

    def test_returns_empty_structure_when_missing(self, tmp_path):
        load_central = _import("load_central")
        result = load_central(tmp_path / "nope.json")
        assert result["active_plans"] == []
        assert result["branches"] == {}
        assert result["global_statistics"]["total_active"] == 0

    def test_returns_empty_structure_on_corrupt_file(self, tmp_path):
        load_central = _import("load_central")
        central = tmp_path / "PLANS.central.json"
        central.write_text("{{invalid", encoding="utf-8")
        result = load_central(central)
        assert result["active_plans"] == []
        assert result["branches"] == {}


# ═══════════════════════════════════════════════════════════
# 8. save_central
# ═══════════════════════════════════════════════════════════

class TestSaveCentral:

    def test_saves_valid_json(self, tmp_path):
        save_central = _import("save_central")
        central_dir = tmp_path / ".ai_central"
        central_file = central_dir / "PLANS.central.json"
        data = {"active_plans": [], "branches": {}}
        result = save_central(central_file, central_dir, data)
        assert result is True
        assert central_file.exists()
        saved = json.loads(central_file.read_text(encoding="utf-8"))
        assert saved == data

    def test_creates_directory_if_needed(self, tmp_path):
        save_central = _import("save_central")
        central_dir = tmp_path / "deep" / "nested" / ".ai_central"
        central_file = central_dir / "PLANS.central.json"
        result = save_central(central_file, central_dir, {"test": True})
        assert result is True
        assert central_dir.exists()

    def test_returns_false_on_error(self):
        save_central = _import("save_central")
        # Use a path that cannot be created
        bad_dir = Path("/proc/fake_dir_no_write")
        bad_file = bad_dir / "PLANS.central.json"
        result = save_central(bad_file, bad_dir, {})
        assert result is False


# ═══════════════════════════════════════════════════════════
# 9. aggregate_central_impl
# ═══════════════════════════════════════════════════════════

class TestAggregateCentralImpl:

    def test_returns_false_when_paths_none(self):
        aggregate_central_impl = _import("aggregate_central_impl")
        result = aggregate_central_impl(heal=True, central_file=None, central_dir=None)
        assert result is False

    def test_returns_true_with_empty_branches(self, tmp_path):
        aggregate_central_impl = _import("aggregate_central_impl")
        central_dir = tmp_path / ".ai_central"
        central_dir.mkdir()
        central_file = central_dir / "PLANS.central.json"
        data = {
            "generated_at": "",
            "active_plans": [],
            "recently_closed": [],
            "statistics": {},
            "branches": {},
            "global_statistics": {},
        }
        central_file.write_text(json.dumps(data), encoding="utf-8")
        result = aggregate_central_impl(
            heal=True, central_file=central_file, central_dir=central_dir
        )
        assert result is True

    def test_aggregates_active_plans_across_branches(self, tmp_path):
        aggregate_central_impl = _import("aggregate_central_impl")

        # Create plan files on disk so they pass validation
        plan1 = tmp_path / "branch_a" / "FPLAN-0001.md"
        plan1.parent.mkdir(parents=True)
        plan1.write_text("plan a", encoding="utf-8")
        plan2 = tmp_path / "branch_b" / "FPLAN-0002.md"
        plan2.parent.mkdir(parents=True)
        plan2.write_text("plan b", encoding="utf-8")

        central_dir = tmp_path / ".ai_central"
        central_dir.mkdir()
        central_file = central_dir / "PLANS.central.json"
        data = {
            "generated_at": "",
            "active_plans": [],
            "recently_closed": [],
            "statistics": {},
            "branches": {
                "branch_a": {
                    "branch_path": str(tmp_path / "branch_a"),
                    "active_plans": [
                        {"plan_id": "FPLAN-0001", "file_path": str(plan1), "created": "2026-03-01"}
                    ],
                    "recently_closed": [],
                },
                "branch_b": {
                    "branch_path": str(tmp_path / "branch_b"),
                    "active_plans": [
                        {"plan_id": "FPLAN-0002", "file_path": str(plan2), "created": "2026-03-02"}
                    ],
                    "recently_closed": [],
                },
            },
            "global_statistics": {},
        }
        central_file.write_text(json.dumps(data), encoding="utf-8")

        with patch(f"{_MOD}.trigger", create=True):
            result = aggregate_central_impl(
                heal=False, central_file=central_file, central_dir=central_dir
            )
        assert result is True

        saved = json.loads(central_file.read_text(encoding="utf-8"))
        assert saved["statistics"]["active_count"] == 2
        assert saved["global_statistics"]["total_active"] == 2
        assert saved["global_statistics"]["branches_reporting"] == 2
        # Sorted newest first by created
        assert saved["active_plans"][0]["plan_id"] == "FPLAN-0002"

    def test_recently_closed_limited_to_5(self, tmp_path):
        aggregate_central_impl = _import("aggregate_central_impl")

        central_dir = tmp_path / ".ai_central"
        central_dir.mkdir()
        central_file = central_dir / "PLANS.central.json"

        # Build 7 closed plans in a single branch
        closed_plans = [
            {"plan_id": f"FPLAN-{i:04d}", "status": "closed", "closed": f"2026-03-{i:02d}"}
            for i in range(1, 8)
        ]
        data = {
            "generated_at": "",
            "active_plans": [],
            "recently_closed": [],
            "statistics": {},
            "branches": {
                "testbranch": {
                    "branch_path": str(tmp_path),
                    "active_plans": [],
                    "recently_closed": closed_plans,
                },
            },
            "global_statistics": {},
        }
        central_file.write_text(json.dumps(data), encoding="utf-8")

        with patch(f"{_MOD}.trigger", create=True):
            result = aggregate_central_impl(
                heal=False, central_file=central_file, central_dir=central_dir
            )
        assert result is True

        saved = json.loads(central_file.read_text(encoding="utf-8"))
        assert len(saved["recently_closed"]) == 5

    def test_returns_false_on_save_failure(self, tmp_path):
        aggregate_central_impl = _import("aggregate_central_impl")

        central_dir = tmp_path / ".ai_central"
        central_dir.mkdir()
        central_file = central_dir / "PLANS.central.json"
        data = {
            "generated_at": "",
            "active_plans": [],
            "recently_closed": [],
            "statistics": {},
            "branches": {"b": {
                "branch_path": str(tmp_path),
                "active_plans": [],
                "recently_closed": [],
            }},
            "global_statistics": {},
        }
        central_file.write_text(json.dumps(data), encoding="utf-8")

        with patch(f"{_MOD}.save_central", return_value=False):
            result = aggregate_central_impl(
                heal=True, central_file=central_file, central_dir=central_dir
            )
        assert result is False

    def test_returns_false_on_exception(self):
        aggregate_central_impl = _import("aggregate_central_impl")
        with patch(f"{_MOD}.load_central", side_effect=RuntimeError("boom")):
            result = aggregate_central_impl(
                heal=True,
                central_file=Path("/fake/PLANS.central.json"),
                central_dir=Path("/fake"),
            )
        assert result is False

    def test_updates_generated_at(self, tmp_path):
        aggregate_central_impl = _import("aggregate_central_impl")
        central_dir = tmp_path / ".ai_central"
        central_dir.mkdir()
        central_file = central_dir / "PLANS.central.json"
        data = {
            "generated_at": "",
            "active_plans": [],
            "recently_closed": [],
            "statistics": {},
            "branches": {"b": {
                "branch_path": str(tmp_path),
                "active_plans": [],
                "recently_closed": [],
            }},
            "global_statistics": {},
        }
        central_file.write_text(json.dumps(data), encoding="utf-8")

        with patch(f"{_MOD}.trigger", create=True):
            aggregate_central_impl(
                heal=False, central_file=central_file, central_dir=central_dir
            )

        saved = json.loads(central_file.read_text(encoding="utf-8"))
        assert saved["generated_at"] != ""
        assert "T" in saved["generated_at"]
