# ===================AIPASS====================
# META DATA HEADER
# Name: tests/test_chroma_source_match.py
# Date: 2026-08-23
# Version: 1.0.0
# Category: memory/tests
# =============================================

"""Tests for source_file matching in the ChromaDB subprocess handler.

Covers: _source_matches, _check_plan, _get_by_source, _delete_by_source

The defect these pin: `plan_label in source_file` is an unanchored substring
test, so DPLAN-0012 matches a TDPLAN-0012 filename and the exact-match pin
promotes the wrong plan. A label only counts when the character before it is
not alphanumeric.

All tests use a fake collection -- no live ChromaDB.
"""

import pytest

from aipass.memory.apps.handlers.storage import chroma_subprocess


# ---------------------------------------------------------------------------
# Fake ChromaDB collection
# ---------------------------------------------------------------------------


class _FakeCollection:
    """Minimal stand-in for a Chroma collection backed by source_file names."""

    def __init__(self, source_files):
        self._sources = list(source_files)
        self.deleted = []

    def get(self, include=None):
        return {
            "metadatas": [{"source_file": s} for s in self._sources],
            "documents": [f"body of {s}" for s in self._sources],
            "ids": [f"id_{i}" for i in range(len(self._sources))],
        }

    def delete(self, ids=None):
        self.deleted.extend(ids or [])


class _FakeClient:
    def __init__(self, collection):
        self._collection = collection

    def get_collection(self, name, embedding_function=None):
        return self._collection


@pytest.fixture
def fake_collection(monkeypatch):
    """Install a fake client and return a factory for seeding source files."""

    def _install(source_files):
        collection = _FakeCollection(source_files)
        monkeypatch.setattr(chroma_subprocess, "_get_client", lambda db_path=None: _FakeClient(collection))
        return collection

    return _install


# ---------------------------------------------------------------------------
# 1. _source_matches() -- the anchored predicate
# ---------------------------------------------------------------------------


class TestSourceMatches:
    """The boundary rule: the character before the label must not be alphanumeric."""

    def test_label_at_start_of_filename_matches(self):
        assert chroma_subprocess._source_matches("DPLAN-0012_hook_management.md", "DPLAN-0012")

    @pytest.mark.parametrize("prefix", ["_", "-", " ", "/", "."])
    def test_non_alphanumeric_predecessor_matches(self, prefix):
        source = f"archive{prefix}DPLAN-0012_hook.md"
        assert chroma_subprocess._source_matches(source, "DPLAN-0012")

    def test_alphabetic_predecessor_is_rejected(self):
        """The reported collision: TDPLAN-0012 must not answer to DPLAN-0012."""
        assert not chroma_subprocess._source_matches("TDPLAN-0012_hook_management.md", "DPLAN-0012")

    def test_digit_predecessor_is_rejected(self):
        assert not chroma_subprocess._source_matches("9DPLAN-0012_hook.md", "DPLAN-0012")

    def test_later_anchored_occurrence_still_matches(self):
        """A rejected first hit must not stop the scan -- keep looking."""
        source = "TDPLAN-0012_supersedes_DPLAN-0012.md"
        assert chroma_subprocess._source_matches(source, "DPLAN-0012")

    def test_absent_label_does_not_match(self):
        assert not chroma_subprocess._source_matches("FPLAN-0449_watchdog.md", "DPLAN-0012")

    def test_empty_pattern_matches_nothing(self):
        """Guard the destructive path: an empty pattern must not select every row."""
        assert not chroma_subprocess._source_matches("DPLAN-0012_hook.md", "")

    def test_missing_source_does_not_match(self):
        assert not chroma_subprocess._source_matches("", "DPLAN-0012")


# ---------------------------------------------------------------------------
# 2. _check_plan() -- vectorization verification
# ---------------------------------------------------------------------------


class TestCheckPlanAnchoring:
    """is_plan_vectorized() must not count another plan's chunks as its own."""

    def test_does_not_count_longer_prefix_family(self, fake_collection):
        fake_collection(["TDPLAN-0012_hook.md", "TDPLAN-0012_hook.md"])

        result = chroma_subprocess._check_plan("DPLAN-0012")

        assert result["success"] is True
        assert result["found"] is False
        assert result["count"] == 0
        assert result["source_files"] == []

    def test_counts_only_its_own_chunks_in_a_mixed_collection(self, fake_collection):
        fake_collection(
            [
                "DPLAN-0012_hook_management.md",
                "TDPLAN-0012_hook_management.md",
                "DPLAN-0012_hook_management.md",
            ]
        )

        result = chroma_subprocess._check_plan("DPLAN-0012")

        assert result["found"] is True
        assert result["count"] == 2
        assert result["source_files"] == ["DPLAN-0012_hook_management.md"]

    def test_the_longer_label_still_finds_itself(self, fake_collection):
        fake_collection(["TDPLAN-0012_hook.md", "DPLAN-0012_hook.md"])

        result = chroma_subprocess._check_plan("TDPLAN-0012")

        assert result["found"] is True
        assert result["count"] == 1
        assert result["source_files"] == ["TDPLAN-0012_hook.md"]


# ---------------------------------------------------------------------------
# 3. _get_by_source() -- the exact-match pin's data source
# ---------------------------------------------------------------------------


class TestGetBySourceAnchoring:
    """The search pin fetches through this -- a wrong row here is pinned at 100%."""

    def test_skips_longer_prefix_family(self, fake_collection):
        fake_collection(["TDPLAN-0012_hook.md"])

        result = chroma_subprocess._get_by_source("flow_plans", "DPLAN-0012")

        assert result["success"] is True
        assert result["count"] == 0
        assert result["results"] == []

    def test_returns_only_the_requested_plan(self, fake_collection):
        fake_collection(["TDPLAN-0012_hook.md", "DPLAN-0012_hook.md"])

        result = chroma_subprocess._get_by_source("flow_plans", "DPLAN-0012")

        assert result["count"] == 1
        assert result["results"][0]["metadata"]["source_file"] == "DPLAN-0012_hook.md"

    def test_n_results_still_caps_matches(self, fake_collection):
        fake_collection(["DPLAN-0012_a.md", "DPLAN-0012_b.md", "DPLAN-0012_c.md"])

        result = chroma_subprocess._get_by_source("flow_plans", "DPLAN-0012", n_results=2)

        assert result["count"] == 2


# ---------------------------------------------------------------------------
# 4. _delete_by_source() -- same predicate, destructive
# ---------------------------------------------------------------------------


class TestDeleteBySourceAnchoring:
    """Unanchored matching here deletes another plan's vectors outright."""

    def test_does_not_delete_longer_prefix_family(self, fake_collection):
        collection = fake_collection(["TDPLAN-0012_hook.md"])

        result = chroma_subprocess._delete_by_source("flow_plans", "DPLAN-0012")

        assert result["success"] is True
        assert result["deleted"] == 0
        assert collection.deleted == []

    def test_deletes_only_the_requested_plan(self, fake_collection):
        collection = fake_collection(["TDPLAN-0012_hook.md", "DPLAN-0012_hook.md"])

        result = chroma_subprocess._delete_by_source("flow_plans", "DPLAN-0012")

        assert result["deleted"] == 1
        assert collection.deleted == ["id_1"]


# ---------------------------------------------------------------------------
# 5. The search pin -- both layers composed
# ---------------------------------------------------------------------------


class TestPinComposition:
    """The pin has two layers: extract the label, then fetch by that label.

    The extractor was already correct (\\b keeps TDPLAN whole); the fetch was
    not. These pin the pair so a regression in either surfaces here.
    """

    def _query_executor(self):
        from aipass.memory.apps.handlers.search import query_executor

        return query_executor

    def test_extractor_keeps_the_longer_prefix_whole(self):
        qe = self._query_executor()
        assert qe._extract_plan_id("TDPLAN-0012 Hook Management") == "TDPLAN-0012"
        assert qe._extract_plan_id("DPLAN-0012 Hook Management") == "DPLAN-0012"

    def test_pin_passes_the_label_through_unaltered(self, monkeypatch):
        """Whatever the extractor produced is what the fetch anchors on."""
        qe = self._query_executor()
        seen = {}

        def _capture(plan_id, n_results):
            seen["plan_id"] = plan_id
            return []

        monkeypatch.setattr(qe, "_fetch_plan_by_metadata", _capture)
        qe._pin_plan_id_matches("DPLAN-0012 Hook Management", [], 5)

        assert seen["plan_id"] == "DPLAN-0012"

    def test_wrong_family_plan_is_not_pinned(self, monkeypatch):
        """End to end: a TDPLAN-only collection yields nothing to pin for DPLAN."""
        qe = self._query_executor()
        collection = _FakeCollection(["TDPLAN-0012_hook.md"])
        monkeypatch.setattr(chroma_subprocess, "_get_client", lambda db_path=None: _FakeClient(collection))

        def _through_handler(plan_id, n_results):
            return chroma_subprocess._get_by_source("flow_plans", plan_id, n_results)["results"]

        monkeypatch.setattr(qe, "_fetch_plan_by_metadata", _through_handler)
        existing = [{"id": "real", "similarity": 0.86}]
        pinned = qe._pin_plan_id_matches("DPLAN-0012 Hook Management", existing, 5)

        assert pinned == existing
        assert not any(r.get("similarity") == 1.0 for r in pinned)
