# =================== AIPass ====================
# Name: test_artifact_laws.py - the publishing laws, enforced not trusted
# Description: closed group list, not_applicable never 0, no single overall number
# Version: 0.1.0
# Created: 2026-08-29
# =============================================

"""The artifact's own laws (S1-S5, S7).

Both this month's confidently-wrong-number incidents produced artifacts that
looked fine, so these test the validator that reads the document rather than the
intention of the code that wrote it.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROTOTYPE_ROOT = Path(__file__).resolve().parent.parent
if str(PROTOTYPE_ROOT) not in sys.path:
    sys.path.insert(0, str(PROTOTYPE_ROOT))

from audit_tests_lib import artifact  # type: ignore[import-not-found]  # noqa: E402
from conftest import CLEAN_TEST  # type: ignore[import-not-found]  # noqa: E402


@pytest.fixture
def document(make_target, audit):
    return audit(make_target("laws", CLEAN_TEST))


def test_the_group_list_is_closed_and_exact(document):
    """S4: six groups, in order, no more and no fewer."""
    assert tuple(document["groups"]) == artifact.GROUPS
    assert document["group_list"] == list(artifact.GROUPS)
    assert len(artifact.GROUPS) == 6


def test_unbuilt_groups_are_present_with_a_reason_and_no_score(document):
    """S1 and S3 together: not-run is not_applicable, never 0, and never dropped."""
    for name in ("oracle_execution", "ai_advisory"):
        group = document["groups"][name]
        assert group["status"] == "not_applicable"
        # Spelled out, never imported (Law T2). Comparing against
        # artifact.NOT_BUILT_REASON made the assertion true by construction:
        # a mutation of the constant changed both sides and killed nothing.
        assert group["reason"] == "not built in MVP"
        assert "score" not in group


def test_nothing_in_the_artifact_reads_as_one_number(document):
    """S2, checked by walking the whole document rather than the top level."""
    artifact.validate(document)
    seen = [key for _path, node in artifact._walk(document) if isinstance(node, dict) for key in node]
    assert not [k for k in seen if "overall" in k.lower()]
    scored = [name for name, g in document["groups"].items() if "score" in g]
    assert scored == ["hygiene"]


def test_cache_provenance_is_stamped(document):
    """S5: the MVP always runs live, and says so rather than leaving it implied."""
    assert document["cache"] == "none (MVP always runs live)"


def test_static_groups_are_labelled_nominated_and_unconvicted(document):
    """S7 in the artifact's own words - the label a reader acts on."""
    for name in ("static_ruff_pt", "static_self_skip", "static_mock_drift"):
        group = document["groups"][name]
        assert group.get("verdict_shape") == "nominated (unconvicted)"


def test_an_overall_number_is_rejected_by_the_validator(document):
    """The validator has to be able to fail, or it is decoration (T10)."""
    document["overall_score"] = 84
    with pytest.raises(artifact.LawViolation, match="S2"):
        artifact.validate(document)


def test_a_dropped_group_is_rejected(document):
    """S3: dropping a group must never be a way to raise anything."""
    del document["groups"]["ai_advisory"]
    with pytest.raises(artifact.LawViolation, match="S4"):
        artifact.validate(document)


def test_a_not_applicable_group_carrying_a_zero_is_rejected(document):
    """S1 is the one that produced two wrong numbers this month."""
    document["groups"]["oracle_execution"]["score"] = 0
    with pytest.raises(artifact.LawViolation, match="S1"):
        artifact.validate(document)


def test_a_scored_nominating_group_is_rejected(document):
    """S7: 'this test is worthless' may nominate and may never be scored."""
    document["groups"]["static_self_skip"]["score"] = 40
    with pytest.raises(artifact.LawViolation, match="S7"):
        artifact.validate(document)


def test_the_artifact_round_trips_to_disk(document, tmp_path):
    """It is written as JSON, and validated again on the way out."""
    import json

    path = artifact.write(document, tmp_path / "out" / "artifact.json")
    assert json.loads(path.read_text())["group_list"] == list(artifact.GROUPS)
