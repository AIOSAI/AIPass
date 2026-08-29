# =================== AIPass ====================
# Name: test_hygiene_gate.py - the scored group, end to end
# Description: a planted write is convicted with the right node id; clean stays clean
# Version: 0.1.0
# Created: 2026-08-29
# =============================================

"""End-to-end tests for the hygiene gate.

Every one of these runs the real lane against a throwaway target, because the
thing being tested is whether an audit hook installed in a child process sees a
write and names the test that made it -- and no unit test of the classifier can
answer that.
"""

from __future__ import annotations

from pathlib import Path

from conftest import CLEAN_TEST, DIRTY_TEST  # type: ignore[import-not-found]

# The out-of-tree arm cannot be reached from here: this suite's own targets
# live under /tmp/pytest-of-*, which the sandbox legitimately allows. It is
# covered in test_classifier.py and proved live on daemon, whose
# test_timer_install.py creates ~/.aipass on every run.


def test_planted_write_is_convicted_with_its_node_id(make_target, audit):
    """The gate names the test that wrote, not just that a write happened."""
    target = make_target("dirty", DIRTY_TEST)
    document = audit(target)

    hygiene = document["groups"]["hygiene"]
    assert hygiene["status"] == "measured"
    assert hygiene["passed"] is False
    assert hygiene["score"] == 0
    convicted = hygiene["convicted_nodeids"]
    assert any("test_forges_a_log_in_its_own_tree" in node for node in convicted), convicted
    assert not any("test_stays_clean" in node for node in convicted), convicted
    paths = [v["path"] for v in hygiene["violations"]]
    assert any(p.endswith("operations.jsonl") for p in paths), paths


def test_a_clean_suite_comes_out_clean(make_target, audit):
    """tmp_path writes are the sandbox, not an escape."""
    target = make_target("clean", CLEAN_TEST)
    document = audit(target)

    hygiene = document["groups"]["hygiene"]
    assert hygiene["passed"] is True
    assert hygiene["score"] == 100
    assert hygiene["violations"] == []


def test_the_violation_carries_the_event_and_the_phase(make_target, audit):
    """Attribution is (node id, phase, event, path) - all four, or it is a guess."""
    target = make_target("dirty2", DIRTY_TEST)
    document = audit(target)

    violations = document["groups"]["hygiene"]["violations"]
    forged = [v for v in violations if v["path"].endswith("operations.jsonl")]
    assert forged, violations
    assert forged[0]["event"] == "open"
    assert forged[0]["phase"] == "call"
    assert forged[0]["where"] == "inside_copy"


def test_a_setup_phase_write_is_attributed_to_setup(make_target, audit):
    """A fixture that writes is the fixture's fault, and the record says so."""
    source = """
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent.parent


@pytest.fixture
def dirty_fixture():
    (HERE / "fixture_wrote_this.txt").write_text("from setup")
    yield


def test_uses_the_dirty_fixture(dirty_fixture):
    assert True
"""
    target = make_target("setupdirty", source)
    document = audit(target)

    violations = document["groups"]["hygiene"]["violations"]
    forged = [v for v in violations if v["path"].endswith("fixture_wrote_this.txt")]
    assert forged, violations
    assert forged[0]["phase"] == "setup"
    assert "test_uses_the_dirty_fixture" in forged[0]["nodeid"]


def test_the_real_target_tree_is_not_touched(make_target, audit):
    """Law M10, checked rather than asserted: the original is byte-identical after."""
    target = make_target("dirty3", DIRTY_TEST)
    document = audit(target)

    assert document["harness"]["real_target_tree"]["unchanged"] is True
    assert not (target / "operations.jsonl").exists()


def test_bytecode_and_pytest_cache_do_not_count_as_escapes(make_target, audit):
    """The allowlist that keeps the gate usable, and it is declared, not implicit."""
    target = make_target("clean2", CLEAN_TEST)
    document = audit(target)

    names = [a["name"] for a in document["harness"]["allowances"]]
    assert "pycache_dir" in names and "bytecode" in names
    paths = [v["path"] for v in document["groups"]["hygiene"]["violations"]]
    assert not any("__pycache__" in p or p.endswith(".pyc") for p in paths), paths


def test_a_target_copy_is_what_actually_ran(make_target, audit):
    """The suite must have executed inside the scratch env, not in place."""
    target = make_target("clean3", CLEAN_TEST)
    document = audit(target)

    cwd = document["harness"]["suite"]["cwd"]
    assert not Path(cwd).is_relative_to(target)
