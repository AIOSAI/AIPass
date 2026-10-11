# =================== AIPass ====================
# Name: support_close_ops.py
# Description: Shared helpers for the close_ops test files (split from test_close_ops.py, leg 12)
# Version: 1.0.0
# Created: 2026-10-06
# Modified: 2026-10-06
# =============================================

"""Shared helpers for the tests of apps/handlers/plan/close_ops.py (no test_ prefix: never collected)."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that the module parses and imports

from unittest.mock import MagicMock


def _scope(tmp_path, **overrides) -> dict:
    """Scope dependencies for close_all: caller in <tmp_path>/proj, every row in it.

    Injected explicitly in every close_all test. The fence is not optional and
    an un-injected default would let a test pass while saying nothing about
    which project it was standing in.
    """
    proj = tmp_path / "proj"
    deps = {"caller_project": proj, "resolve_project_fn": lambda _path: proj}
    deps.update(overrides)
    return deps


def _make_deps(**overrides) -> dict:
    """Build a full set of injected dependency kwargs with MagicMock defaults."""
    deps = {
        "normalize_plan_number": MagicMock(side_effect=lambda x: str(x).split("-")[-1].lstrip("0") or "0"),
        "load_registry": MagicMock(),
        "save_registry": MagicMock(),
        "validate_plan_exists": MagicMock(return_value=(True, None)),
        "confirm_plan_deletion": MagicMock(return_value=True),
        "is_template_content": MagicMock(return_value=False),
        "update_dashboard_local": MagicMock(return_value=True),
        "push_to_plans_central": MagicMock(return_value=True),
        "push_flow_to_branch_dashboard": MagicMock(return_value=True),
        "close_all_plans_fn": MagicMock(),
        "archive_plan_fn": MagicMock(return_value=True),
        "trigger_fire_fn": MagicMock(),
    }
    deps.update(overrides)
    return deps


def _closed_ids(mock_close) -> list:
    """Extract the plan_num argument from every close_plan_fn call."""
    return [c.kwargs.get("plan_num") for c in mock_close.call_args_list]


def _held_ids(result) -> list:
    return result.get("held_ids", [])
