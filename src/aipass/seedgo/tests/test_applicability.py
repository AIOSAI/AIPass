"""Tests for standard applicability (production / tests / everywhere) across both lanes."""

# =================== META ====================
# Name: test_applicability.py
# Description: Unit tests for aipass_standards/applicability.py and its two consumers
# Version: 1.0.0
# Created: 2026-08-09
# Modified: 2026-08-09
# =============================================

from types import SimpleNamespace

import pytest

from aipass.seedgo.apps.handlers.aipass_standards import applicability
from aipass.seedgo.apps.handlers.aipass_standards.skip_dirs import SOURCE_SKIP_DIRS
from aipass.seedgo.apps.handlers.bypass.ignore_handler import AUDIT_IGNORE_PATTERNS


@pytest.fixture(autouse=True)
def _clear_path_caches():
    """The path predicates are lru_cached; tmp_path names differ per test but be explicit."""
    applicability.is_test_path.cache_clear()
    applicability.is_retired_path.cache_clear()
    yield


def _checker(applies_to=None, **attrs):
    """A stand-in checker module carrying only the constants the lanes read."""
    if applies_to is not None:
        attrs["APPLIES_TO"] = applies_to
    return SimpleNamespace(__name__="fake_check", **attrs)


# ---------------------------------------------------------------------------
# Path classification
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "/repo/trigger/tests/test_events.py",
        "/repo/trigger/tests/unit/test_events.py",
        "/repo/spawn/tests/conftest.py",
        "/repo/spawn/conftest.py",
        r"C:\repo\trigger\tests\test_events.py",
    ],
)
def test_is_test_path_matches_test_trees_on_both_separators(path):
    assert applicability.is_test_path(path) is True


def test_is_test_path_does_not_match_a_production_module_named_test_something():
    """test_map.py is a real seedgo module — a filename heuristic would exempt it silently."""
    assert applicability.is_test_path("/repo/seedgo/apps/modules/test_map.py") is False
    assert applicability.is_test_path("/repo/seedgo/apps/handlers/test_map/function_scanner.py") is False


@pytest.mark.parametrize(
    "path",
    [
        "/repo/trigger/apps/handlers/events/.archive/bulletin_created.py",
        "/repo/commons/apps/modules/.archive/feed_module.py",
        "/repo/x/apps/deprecated/old.py",
        r"C:\repo\trigger\apps\handlers\events\.archive\bulletin_created.py",
    ],
)
def test_is_retired_path_matches_archived_trees_on_both_separators(path):
    assert applicability.is_retired_path(path) is True


def test_is_retired_path_leaves_live_source_alone():
    assert applicability.is_retired_path("/repo/trigger/apps/handlers/events/bulletin_created.py") is False


def test_retired_dirs_stay_in_step_with_the_lists_they_mirror():
    """RETIRED_DIRS must not become a third scope list that drifts from the other two."""
    assert {".archive", ".sorting_unprocessed"} <= SOURCE_SKIP_DIRS
    assert {".archive", ".sorting_unprocessed"} <= applicability.RETIRED_DIRS
    audit_patterns = "".join(AUDIT_IGNORE_PATTERNS)
    for name in (".archive", ".backup", "deprecated"):
        assert name in audit_patterns


# ---------------------------------------------------------------------------
# The declaration itself
# ---------------------------------------------------------------------------


def test_a_checker_with_no_declaration_applies_everywhere():
    """Fail-open: forgetting the constant costs noise, never a missed bug."""
    assert applicability.applies_to(_checker()) == applicability.EVERYWHERE


def test_an_unrecognised_declaration_falls_back_to_everywhere():
    assert applicability.applies_to(_checker("prod")) == applicability.EVERYWHERE


def test_an_unrecognised_declaration_is_reported_not_swallowed(monkeypatch):
    warnings = []
    monkeypatch.setattr(applicability.logger, "warning", lambda *a, **k: warnings.append(a))
    applicability.applies_to(_checker("prod"))
    assert warnings, "a typo'd APPLIES_TO must announce itself"


@pytest.mark.parametrize(
    "declared,production,tests",
    [
        (None, True, True),
        ("everywhere", True, True),
        ("production", True, False),
        ("tests", False, True),
    ],
)
def test_applies_to_file_matrix(declared, production, tests):
    checker = _checker(declared)
    assert applicability.applies_to_file(checker, "/repo/b/apps/modules/thing.py") is production
    assert applicability.applies_to_file(checker, "/repo/b/tests/test_thing.py") is tests


def test_no_checker_applies_to_retired_code():
    for declared in (None, "everywhere", "production", "tests"):
        assert applicability.applies_to_file(_checker(declared), "/repo/b/apps/.archive/old.py") is False


# ---------------------------------------------------------------------------
# The declarations the pack actually ships
# ---------------------------------------------------------------------------


def test_structural_standards_are_declared_production_only():
    """These failed on 25-96% of every branch's test files before they were scoped."""
    from aipass.seedgo.apps.handlers.audit.branch_audit import discover_checkers

    checkers = discover_checkers()
    for name in ("architecture", "encapsulation", "handlers", "modules", "meta", "documentation", "cli"):
        assert applicability.applies_to(checkers[name]) == applicability.PRODUCTION, name


def test_bug_finding_standards_still_apply_to_tests():
    """Scoping, not muting: Windows CI runs the whole suite, so a bad path in a test is real."""
    from aipass.seedgo.apps.handlers.audit.branch_audit import discover_checkers

    checkers = discover_checkers()
    for name in ("windows_compat", "hardcoded_path", "silent_catch", "hardcoded_key", "ruff"):
        assert applicability.applies_to(checkers[name]) == applicability.EVERYWHERE, name


def test_trigger_is_production_only():
    """A fixture unlinking its own scratch file is not a system state change.

    All 19 test-file hits fleet-wide were that; a test that fired real events to
    satisfy the standard would pollute the bus for every other branch.
    """
    from aipass.seedgo.apps.handlers.audit.branch_audit import discover_checkers

    assert applicability.applies_to(discover_checkers()["trigger"]) == applicability.PRODUCTION


def test_test_quality_is_the_one_tests_only_standard():
    from aipass.seedgo.apps.handlers.audit.branch_audit import discover_checkers

    checkers = discover_checkers()
    tests_only = [n for n, c in checkers.items() if applicability.applies_to(c) == applicability.TESTS]
    assert tests_only == ["test_quality"]


# ---------------------------------------------------------------------------
# Both lanes consult it
# ---------------------------------------------------------------------------


def test_checklist_lane_honours_the_declaration():
    from aipass.seedgo.apps.modules import checklist

    production_only = _checker("production", AUDIT_SCOPE="all_files", check_module=lambda *a, **k: {})
    everywhere = _checker(None, AUDIT_SCOPE="all_files", check_module=lambda *a, **k: {})

    assert checklist._is_applicable(production_only, "/repo/b/apps/modules/thing.py") is True
    assert checklist._is_applicable(production_only, "/repo/b/tests/test_thing.py") is False
    assert checklist._is_applicable(everywhere, "/repo/b/tests/test_thing.py") is True


def test_checklist_lane_skips_retired_files(tmp_path, monkeypatch):
    """The audit lane always skipped .archive/; this lane used to flag it.

    tmp_path lives under the system temp dir, which both lanes skip as
    throwaway before anything else — neutered here so the retired rule is what
    is actually under test.
    """
    from aipass.seedgo.apps.modules import checklist

    monkeypatch.setattr(checklist, "is_throwaway_path", lambda _p: False)

    archived = tmp_path / "apps" / "handlers" / ".archive" / "bulletin_created.py"
    archived.parent.mkdir(parents=True)
    archived.write_text("x=1\n", encoding="utf-8")

    results = checklist.run_checklist(str(archived))
    assert [r["standard"] for r in results] == ["(skip)"]
    assert "Retired" in results[0]["detail"]


def test_audit_lane_does_not_collect_retired_files(tmp_path, monkeypatch):
    from aipass.seedgo.apps.handlers.audit import branch_audit

    monkeypatch.setattr(branch_audit, "is_throwaway_path", lambda _p: False)

    live = tmp_path / "apps" / "modules" / "live.py"
    live.parent.mkdir(parents=True)
    live.write_text("x=1\n", encoding="utf-8")
    archived = tmp_path / "apps" / "modules" / ".archive" / "old.py"
    archived.parent.mkdir(parents=True)
    archived.write_text("x=1\n", encoding="utf-8")

    collected = {f["name"] for f in branch_audit._collect_py_files(tmp_path)}
    assert collected == {"live.py"}
