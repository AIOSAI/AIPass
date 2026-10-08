# =================== AIPass ====================
# Name: test_symbolic_extras_storage.py
# Description: Tests for symbolic handler storage and search - store, delete, dedupe, chroma client, retrieval
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-08
# =============================================

"""Tests for apps/handlers/symbolic/storage.py, deduplicator.py, chroma_client.py, retriever.py and extractor.py."""

# Split from test_symbolic_extras.py on 2026-10-08 (oversize_test_file): the
# storage-and-search half, one subject - how a fragment is flattened, stored,
# deleted, deduplicated and found again, and the extractor's operation log.
# The recall-and-surfacing half (hook.py) stays in test_symbolic_extras.py.
#
# Covers imports required by the seedgo test scanner:
#     from aipass.memory.apps.handlers.symbolic.storage import flatten_dimensions
#     from aipass.memory.apps.handlers.symbolic.storage import store_fragment
#     from aipass.memory.apps.handlers.symbolic.storage import store_fragments_batch
#     from aipass.memory.apps.handlers.symbolic.storage import store_llm_fragment
#     from aipass.memory.apps.handlers.symbolic.storage import store_llm_fragments_batch
#     from aipass.memory.apps.handlers.symbolic.storage import delete_fragment
#     from aipass.memory.apps.handlers.symbolic.deduplicator import deduplicate_fragment
#     from aipass.memory.apps.handlers.symbolic.chroma_client import get_chroma_client
#     from aipass.memory.apps.handlers.symbolic.retriever import search_by_vector
#     from aipass.memory.apps.handlers.symbolic.retriever import search_by_dimensions
#     from aipass.memory.apps.handlers.symbolic.retriever import search_by_triggers
#     from aipass.memory.apps.handlers.symbolic.retriever import retrieve_fragments

# ---------------------------------------------------------------------------
# PARKED 2026-08-14 — the owner's ruling. The symbolic fragments tier is disabled
# (unused; the Agent Memory Atlas review flagged the AUDN deduplicator for acting
# on an LLM Delete verdict with no record of what was removed). These tests are
# KEPT, not deleted: they document the feature for revival.
# Active curated-truth piece: Compass — drone @devpulse compass.
# Revive: tests/parked/symbolic_20260814/README.md
# ---------------------------------------------------------------------------

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(covered_elsewhere) — SymbolicTierParked, the parked import; tests/test_symbolic_parked.py

import pytest as _parked

_parked.skip(
    "symbolic fragments tier PARKED 2026-08-14 (the owner's ruling) — "
    "active piece is Compass; revive via tests/parked/symbolic_20260814/README.md",
    allow_module_level=True,
)

import json
import sys
import types
from unittest.mock import MagicMock, patch

from aipass.memory.tests.support_symbolic_extras import _mock_handler_deps as _mock_handler_deps
from aipass.memory.tests.support_symbolic_extras import _reset_chroma_clients as _reset_chroma_clients
from aipass.memory.tests.support_symbolic_extras import _reset_hook_session as _reset_hook_session


# ---------------------------------------------------------------------------
# Import helpers (must be called inside tests, after mocks are installed)
# ---------------------------------------------------------------------------


def _import_storage():
    sys.modules.pop("aipass.memory.apps.handlers.symbolic.storage", None)
    from aipass.memory.apps.handlers.symbolic.storage import (
        delete_fragment,
        flatten_dimensions,
        store_fragment,
        store_fragments_batch,
        store_llm_fragment,
        store_llm_fragments_batch,
    )

    return {
        "flatten_dimensions": flatten_dimensions,
        "store_fragment": store_fragment,
        "store_fragments_batch": store_fragments_batch,
        "store_llm_fragment": store_llm_fragment,
        "store_llm_fragments_batch": store_llm_fragments_batch,
        "delete_fragment": delete_fragment,
    }


def _import_deduplicator():
    sys.modules.pop("aipass.memory.apps.handlers.symbolic.deduplicator", None)
    from aipass.memory.apps.handlers.symbolic.deduplicator import deduplicate_fragment

    return deduplicate_fragment


def _import_chroma_client():
    sys.modules.pop("aipass.memory.apps.handlers.symbolic.chroma_client", None)
    from aipass.memory.apps.handlers.symbolic.chroma_client import get_chroma_client

    return get_chroma_client


def _import_retriever():
    sys.modules.pop("aipass.memory.apps.handlers.symbolic.retriever", None)
    from aipass.memory.apps.handlers.symbolic.retriever import (
        retrieve_fragments,
        search_by_dimensions,
        search_by_triggers,
        search_by_vector,
    )

    return {
        "search_by_vector": search_by_vector,
        "search_by_dimensions": search_by_dimensions,
        "search_by_triggers": search_by_triggers,
        "retrieve_fragments": retrieve_fragments,
    }


# ---------------------------------------------------------------------------
# Sample data helpers
# ---------------------------------------------------------------------------


def _v1_fragment():
    return {
        "id": "frag_20260401_120000_abcd1234",
        "content": "Technical debugging session",
        "dimensions": {
            "technical": ["debugging_session"],
            "emotional": ["frustration_to_breakthrough"],
            "collaboration": ["pair_debugging"],
            "learnings": ["edge_case_handling"],
            "triggers": ["parser", "bug", "fix"],
        },
        "metadata": {
            "timestamp": "2026-04-01T12:00:00",
            "message_count": 10,
            "depth": "deep",
            "total_words": 500,
            "source_branch": "test",
        },
    }


def _v2_fragment():
    return {
        "id": "frag_20260402_130000_efgh5678",
        "content": "LLM extracted fragment content",
        "metadata": {
            "schema_version": "v2",
            "summary": "Debugged a parser edge case",
            "insight": "Always check boundary conditions",
            "type": "episodic",
            "emotional_tone": "determined",
            "technical_domain": "parsing",
            "triggers": "parser,bug,edge",
            "timestamp": "2026-04-02T13:00:00",
        },
    }


def _mock_collection():
    """Create a mock ChromaDB collection with standard methods."""
    coll = MagicMock()
    coll.count.return_value = 5
    coll.upsert = MagicMock()
    coll.delete = MagicMock()
    coll.get = MagicMock(return_value={"ids": [], "documents": [], "metadatas": []})
    coll.query = MagicMock(
        return_value={
            "ids": [["id1"]],
            "documents": [["doc content"]],
            "metadatas": [[{"triggers": "parser,bug"}]],
            "distances": [[0.25]],
        }
    )
    return coll


def _mock_chroma_client(collection=None):
    """Create a mock ChromaDB client."""
    client = MagicMock()
    coll = collection or _mock_collection()
    client.get_or_create_collection.return_value = coll
    client.get_collection.return_value = coll
    return client


# ===========================================================================
# 12. storage.flatten_dimensions
# ===========================================================================


class TestFlattenDimensions:
    """Tests for storage.flatten_dimensions."""

    def test_flattens_dimension_lists(self):
        """Verify nested dimensions are flattened to indexed keys."""
        s = _import_storage()
        frag = _v1_fragment()

        result = s["flatten_dimensions"](frag)

        assert result["success"] is True
        meta = result["metadata"]
        assert meta["technical_0"] == "debugging_session"
        assert meta["emotional_0"] == "frustration_to_breakthrough"
        assert "parser,bug,fix" in meta["triggers"]

    def test_empty_fragment_fails(self):
        """Verify None fragment returns failure."""
        s = _import_storage()
        result = s["flatten_dimensions"](None)

        assert result["success"] is False

    def test_includes_metadata_fields(self):
        """Verify metadata fields are preserved in flat output."""
        s = _import_storage()
        frag = _v1_fragment()

        result = s["flatten_dimensions"](frag)
        meta = result["metadata"]

        assert meta["timestamp"] == "2026-04-01T12:00:00"
        assert meta["message_count"] == 10
        assert meta["depth"] == "deep"
        assert meta["source_branch"] == "test"

    def test_limits_to_5_per_dimension(self):
        """Verify dimensions are limited to 5 values."""
        s = _import_storage()
        frag = {
            "dimensions": {
                "technical": [f"tech_{i}" for i in range(10)],
                "triggers": [],
            },
            "metadata": {},
        }
        result = s["flatten_dimensions"](frag)
        meta = result["metadata"]

        assert "technical_4" in meta
        assert "technical_5" not in meta


# ===========================================================================
# 13. storage.store_fragment
# ===========================================================================


class TestStoreFragment:
    """Tests for storage.store_fragment."""

    def test_stores_valid_fragment(self):
        """Verify valid fragment is stored successfully."""
        s = _import_storage()
        client = _mock_chroma_client()

        with patch(
            "aipass.memory.apps.handlers.symbolic.chroma_client.get_client",
            return_value=client,
        ):
            result = s["store_fragment"](_v1_fragment())

        assert result["success"] is True
        assert "fragment_id" in result

    def test_fails_on_empty_fragment(self):
        """Verify None fragment returns failure."""
        s = _import_storage()
        result = s["store_fragment"](None)

        assert result["success"] is False

    def test_fails_on_missing_content(self):
        """Verify fragment without content returns failure."""
        s = _import_storage()
        result = s["store_fragment"]({"id": "frag-1", "content": ""})

        assert result["success"] is False

    def test_handles_embedding_failure(self):
        """Verify embedding failure is reported correctly."""
        s = _import_storage()
        embedder_mod = sys.modules["aipass.memory.apps.handlers.vector.embedder"]
        setattr(
            embedder_mod,
            "encode_batch",
            MagicMock(return_value={"success": False, "error": "model not loaded"}),
        )

        result = s["store_fragment"](_v1_fragment())

        assert result["success"] is False
        assert "Embedding failed" in result["error"]


# ===========================================================================
# 14. storage.store_fragments_batch
# ===========================================================================


class TestStoreFragmentsBatch:
    """Tests for storage.store_fragments_batch."""

    def test_stores_multiple_fragments(self):
        """Verify batch storage stores all valid fragments."""
        s = _import_storage()
        client = _mock_chroma_client()
        embedder_mod = sys.modules["aipass.memory.apps.handlers.vector.embedder"]
        setattr(
            embedder_mod,
            "encode_batch",
            MagicMock(
                return_value={
                    "success": True,
                    "embeddings": [[0.1, 0.2], [0.3, 0.4]],
                }
            ),
        )

        frags = [_v1_fragment(), _v1_fragment()]
        frags[1]["id"] = "frag_20260401_120001_wxyz9012"

        with patch(
            "aipass.memory.apps.handlers.symbolic.chroma_client.get_client",
            return_value=client,
        ):
            result = s["store_fragments_batch"](frags)

        assert result["success"] is True
        assert result["stored"] == 2

    def test_empty_list_returns_zero(self):
        """Verify empty list returns zero stored."""
        s = _import_storage()
        result = s["store_fragments_batch"]([])

        assert result["success"] is True
        assert result["stored"] == 0

    def test_fails_on_embedding_count_mismatch(self):
        """Verify embedding count mismatch is caught."""
        s = _import_storage()
        embedder_mod = sys.modules["aipass.memory.apps.handlers.vector.embedder"]
        setattr(
            embedder_mod,
            "encode_batch",
            MagicMock(return_value={"success": True, "embeddings": [[0.1]]}),
        )

        frags = [_v1_fragment(), _v1_fragment()]
        frags[1]["id"] = "frag_20260401_120001_wxyz9012"

        result = s["store_fragments_batch"](frags)

        assert result["success"] is False
        assert "mismatch" in result["error"]


# ===========================================================================
# 15. storage.store_llm_fragment
# ===========================================================================


class TestStoreLlmFragment:
    """Tests for storage.store_llm_fragment."""

    def test_stores_v2_fragment(self):
        """Verify v2 LLM fragment is stored successfully."""
        s = _import_storage()
        client = _mock_chroma_client()

        llm_frag = {
            "summary": "Debugged parser edge case",
            "insight": "Check boundary conditions",
            "type": "episodic",
            "emotional_tone": "determined",
            "technical_domain": "parsing",
            "triggers": ["parser", "boundary"],
        }

        with patch(
            "aipass.memory.apps.handlers.symbolic.chroma_client.get_client",
            return_value=client,
        ):
            result = s["store_llm_fragment"](llm_frag, source_branch="memory")

        assert result["success"] is True
        assert "fragment_id" in result

    def test_fails_on_empty_fragment(self):
        """Verify None fragment returns failure."""
        s = _import_storage()
        result = s["store_llm_fragment"](None)

        assert result["success"] is False

    def test_fails_on_missing_summary(self):
        """Verify fragment without summary returns failure."""
        s = _import_storage()
        result = s["store_llm_fragment"]({"insight": "no summary"})

        assert result["success"] is False
        assert "missing summary" in result["error"]


# ===========================================================================
# 16. storage.store_llm_fragments_batch
# ===========================================================================


class TestStoreLlmFragmentsBatch:
    """Tests for storage.store_llm_fragments_batch."""

    def test_stores_multiple_v2_fragments(self):
        """Verify batch v2 storage stores all valid fragments."""
        s = _import_storage()
        client = _mock_chroma_client()
        embedder_mod = sys.modules["aipass.memory.apps.handlers.vector.embedder"]
        setattr(
            embedder_mod,
            "encode_batch",
            MagicMock(return_value={"success": True, "embeddings": [[0.1], [0.2]]}),
        )

        frags = [
            {
                "summary": "First memory",
                "insight": "insight A",
                "type": "episodic",
                "triggers": ["test"],
            },
            {
                "summary": "Second memory",
                "insight": "",
                "type": "semantic",
                "triggers": [],
            },
        ]

        with patch(
            "aipass.memory.apps.handlers.symbolic.chroma_client.get_client",
            return_value=client,
        ):
            result = s["store_llm_fragments_batch"](frags, source_branch="test")

        assert result["success"] is True
        assert result["stored"] == 2

    def test_empty_list_returns_zero(self):
        """Verify empty list returns zero stored."""
        s = _import_storage()
        result = s["store_llm_fragments_batch"]([])

        assert result["success"] is True
        assert result["stored"] == 0

    def test_skips_fragments_without_summary(self):
        """Verify fragments without summary are rejected."""
        s = _import_storage()
        frags = [{"insight": "no summary here"}, {"insight": "also no summary"}]
        result = s["store_llm_fragments_batch"](frags)

        assert result["success"] is False
        assert "No valid" in result["error"]


# ===========================================================================
# 17. storage.delete_fragment
# ===========================================================================


class TestDeleteFragment:
    """Tests for storage.delete_fragment."""

    def test_deletes_by_id(self):
        """Verify fragment is deleted by ID."""
        s = _import_storage()
        client = _mock_chroma_client()

        # Re-import chroma_client so mock.patch and the code resolve to the
        # same module object.  The autouse fixture deletes it from sys.modules;
        # on Python 3.10 mock._dot_lookup finds a stale parent attribute.
        import importlib

        importlib.import_module("aipass.memory.apps.handlers.symbolic.chroma_client")

        with patch(
            "aipass.memory.apps.handlers.symbolic.chroma_client.get_client",
            return_value=client,
        ):
            result = s["delete_fragment"]("frag-to-delete")

        assert result["success"] is True
        assert result["deleted_id"] == "frag-to-delete"
        client.get_or_create_collection.return_value.delete.assert_called_once_with(ids=["frag-to-delete"])

    def test_handles_chroma_exception(self):
        """Verify ChromaDB exception is caught gracefully."""
        s = _import_storage()
        client = _mock_chroma_client()
        client.get_or_create_collection.side_effect = RuntimeError("db locked")

        import importlib

        importlib.import_module("aipass.memory.apps.handlers.symbolic.chroma_client")

        with patch(
            "aipass.memory.apps.handlers.symbolic.chroma_client.get_client",
            return_value=client,
        ):
            result = s["delete_fragment"]("frag-missing")

        assert result["success"] is False
        assert "failed" in result["error"].lower()


# ===========================================================================
# 18. deduplicator.deduplicate_fragment
# ===========================================================================


class TestDeduplicateFragment:
    """Tests for deduplicator.deduplicate_fragment."""

    def test_add_when_no_existing(self):
        """Verify ADD action when no existing fragments."""
        deduplicate = _import_deduplicator()
        new_frag = {
            "summary": "New insight",
            "insight": "Fresh",
            "type": "episodic",
            "triggers": [],
        }

        result = deduplicate(new_frag, [])

        assert result["success"] is True
        assert result["action"] == "ADD"

    def test_noop_on_empty_new_fragment(self):
        """Verify NOOP action when new fragment is empty."""
        deduplicate = _import_deduplicator()
        empty_frag: dict = {}  # type: ignore[assignment]
        result = deduplicate(empty_frag, [])

        assert result["action"] == "NOOP"

    def test_llm_returns_update_action(self):
        """Verify UPDATE action merges fragment content."""
        deduplicate = _import_deduplicator()

        llm_response = json.dumps(
            {
                "action": "UPDATE",
                "merged_summary": "Combined summary",
                "merged_insight": "Combined insight",
                "delete_id": "",
                "reason": "Overlapping content",
            }
        )

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"choices": [{"message": {"content": llm_response}}]}).encode("utf-8")
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        new_frag = {
            "summary": "New",
            "insight": "Fresh",
            "type": "episodic",
            "triggers": [],
        }
        existing = [
            {
                "id": "old-1",
                "content": "Old content",
                "metadata": {"summary": "Old"},
            }
        ]

        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = deduplicate(new_frag, existing)

        assert result["success"] is True
        assert result["action"] == "UPDATE"
        assert result["fragment"]["summary"] == "Combined summary"

    def test_falls_back_to_add_on_api_error(self):
        """Verify ADD fallback on API error."""
        deduplicate = _import_deduplicator()

        new_frag = {
            "summary": "New",
            "insight": "",
            "type": "episodic",
            "triggers": [],
        }
        existing = [{"id": "old-1", "content": "Old content", "metadata": {}}]

        import urllib.error

        with patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.URLError("connection refused"),
        ):
            result = deduplicate(new_frag, existing)

        assert result["success"] is True
        assert result["action"] == "ADD"
        assert "failed" in result["reason"].lower()

    def test_falls_back_to_add_when_no_api_key(self):
        """Verify ADD fallback when API key is missing."""
        deduplicate = _import_deduplicator()

        keys_mod = sys.modules["aipass.api.apps.handlers.auth.keys"]
        setattr(keys_mod, "get_api_key", MagicMock(return_value=None))

        new_frag = {
            "summary": "New",
            "insight": "",
            "type": "episodic",
            "triggers": [],
        }
        existing = [{"id": "old-1", "content": "Old", "metadata": {}}]

        result = deduplicate(new_frag, existing)

        assert result["success"] is True
        assert result["action"] == "ADD"
        assert result["reason"] == (
            "No OpenRouter API key found (api branch unavailable or key missing), defaulting to ADD"
        )


# ===========================================================================
# 19. chroma_client.get_chroma_client
# ===========================================================================


class TestGetChromaClient:
    """Tests for chroma_client.get_chroma_client."""

    def test_returns_persistent_client(self, tmp_path):
        """Verify PersistentClient is created and returned."""
        get_chroma_client = _import_chroma_client()
        chromadb_mod = sys.modules["chromadb"]
        mock_client = MagicMock()
        setattr(chromadb_mod, "PersistentClient", MagicMock(return_value=mock_client))

        db_path = tmp_path / "test_chroma"
        result = get_chroma_client(db_path)

        assert result == mock_client
        chromadb_mod.PersistentClient.assert_called_once()

    def test_caches_client_by_path(self, tmp_path):
        """Verify same path returns cached client."""
        get_chroma_client = _import_chroma_client()
        chromadb_mod = sys.modules["chromadb"]
        mock_client = MagicMock()
        setattr(chromadb_mod, "PersistentClient", MagicMock(return_value=mock_client))

        db_path = tmp_path / "cached_chroma"
        client1 = get_chroma_client(db_path)
        client2 = get_chroma_client(db_path)

        assert client1 is client2
        assert chromadb_mod.PersistentClient.call_count == 1

    def test_accepts_string_path(self, tmp_path):
        """Verify string path is accepted and converted."""
        get_chroma_client = _import_chroma_client()
        chromadb_mod = sys.modules["chromadb"]
        mock_client = MagicMock()
        setattr(chromadb_mod, "PersistentClient", MagicMock(return_value=mock_client))

        result = get_chroma_client(str(tmp_path / "str_chroma"))

        assert result == mock_client


# ===========================================================================
# 20. retriever.search_by_vector
# ===========================================================================


class TestSearchByVector:
    """Tests for retriever.search_by_vector."""

    def test_returns_results(self):
        """Verify vector search returns formatted results."""
        r = _import_retriever()
        client = _mock_chroma_client()

        with patch(
            "aipass.memory.apps.handlers.symbolic.retriever.get_chroma_client",
            return_value=client,
        ):
            result = r["search_by_vector"]("debugging session")

        assert result["success"] is True
        assert result["search_type"] == "vector"
        assert len(result["results"]) > 0

    def test_empty_query_fails(self):
        """Verify empty query returns failure."""
        r = _import_retriever()
        result = r["search_by_vector"]("")

        assert result["success"] is False
        assert result["error"] == "Query text required"

    def test_handles_missing_collection(self):
        """Verify missing collection returns empty results."""
        r = _import_retriever()
        client = MagicMock()
        client.get_collection.side_effect = Exception("collection not found")

        with patch(
            "aipass.memory.apps.handlers.symbolic.retriever.get_chroma_client",
            return_value=client,
        ):
            result = r["search_by_vector"]("test query")

        assert result["success"] is True
        assert result["results"] == []


# ===========================================================================
# 21. retriever.search_by_dimensions
# ===========================================================================


class TestSearchByDimensions:
    """Tests for retriever.search_by_dimensions."""

    def test_filters_by_dimension(self):
        """Verify dimension filter returns matching fragments."""
        r = _import_retriever()
        coll = _mock_collection()
        coll.get.return_value = {
            "ids": ["frag-1"],
            "documents": ["content here"],
            "metadatas": [{"emotional_0": "frustration"}],
        }
        client = _mock_chroma_client(coll)

        with patch(
            "aipass.memory.apps.handlers.symbolic.retriever.get_chroma_client",
            return_value=client,
        ):
            result = r["search_by_dimensions"]({"emotional_0": "frustration"})

        assert result["success"] is True
        assert result["search_type"] == "dimension_filter"
        assert len(result["results"]) == 1

    def test_empty_filters_fails(self):
        """Verify empty filters returns failure."""
        r = _import_retriever()
        result = r["search_by_dimensions"]({})

        assert result["success"] is False

    def test_handles_missing_collection(self):
        """Verify missing collection returns empty results."""
        r = _import_retriever()
        client = MagicMock()
        client.get_collection.side_effect = Exception("not found")

        with patch(
            "aipass.memory.apps.handlers.symbolic.retriever.get_chroma_client",
            return_value=client,
        ):
            result = r["search_by_dimensions"]({"emotional_0": "curiosity"})

        assert result["success"] is True
        assert result["results"] == []


# ===========================================================================
# 22. retriever.search_by_triggers
# ===========================================================================


class TestSearchByTriggers:
    """Tests for retriever.search_by_triggers."""

    def test_finds_matching_triggers(self):
        """Verify trigger search finds matching fragments."""
        r = _import_retriever()
        coll = _mock_collection()
        coll.get.return_value = {
            "ids": ["frag-1", "frag-2"],
            "documents": ["doc1", "doc2"],
            "metadatas": [
                {"triggers": "parser,bug,fix"},
                {"triggers": "deploy,release"},
            ],
        }
        client = _mock_chroma_client(coll)

        with patch(
            "aipass.memory.apps.handlers.symbolic.retriever.get_chroma_client",
            return_value=client,
        ):
            result = r["search_by_triggers"](["parser"])

        assert result["success"] is True
        assert result["search_type"] == "trigger_keywords"
        assert len(result["results"]) == 1

    def test_empty_keywords_fails(self):
        """Verify empty keywords returns failure."""
        r = _import_retriever()
        result = r["search_by_triggers"]([])

        assert result["success"] is False

    def test_case_insensitive_matching(self):
        """Verify trigger matching is case-insensitive."""
        r = _import_retriever()
        coll = _mock_collection()
        coll.get.return_value = {
            "ids": ["frag-1"],
            "documents": ["doc1"],
            "metadatas": [{"triggers": "Parser,BUG"}],
        }
        client = _mock_chroma_client(coll)

        with patch(
            "aipass.memory.apps.handlers.symbolic.retriever.get_chroma_client",
            return_value=client,
        ):
            result = r["search_by_triggers"](["PARSER"])

        assert result["success"] is True
        assert len(result["results"]) == 1


# ===========================================================================
# 23. retriever.retrieve_fragments
# ===========================================================================


class TestRetrieveFragments:
    """Tests for retriever.retrieve_fragments."""

    def test_combined_search(self):
        """Verify combined search uses multiple methods."""
        r = _import_retriever()
        client = _mock_chroma_client()
        coll = client.get_collection.return_value
        coll.get.return_value = {
            "ids": ["frag-1"],
            "documents": ["doc1"],
            "metadatas": [{"triggers": "parser,bug"}],
        }

        with patch(
            "aipass.memory.apps.handlers.symbolic.retriever.get_chroma_client",
            return_value=client,
        ):
            result = r["retrieve_fragments"](query="debugging", trigger_keywords=["parser"])

        assert result["success"] is True
        assert len(result["search_methods"]) >= 1

    def test_no_search_params_fails(self):
        """Verify no search params returns failure."""
        r = _import_retriever()
        result = r["retrieve_fragments"]()

        assert result["success"] is False
        assert "At least one" in result["error"]

    def test_query_only_uses_vector(self):
        """Verify query-only search uses vector method."""
        r = _import_retriever()
        client = _mock_chroma_client()

        with patch(
            "aipass.memory.apps.handlers.symbolic.retriever.get_chroma_client",
            return_value=client,
        ):
            result = r["retrieve_fragments"](query="test query")

        assert result["success"] is True
        assert "vector" in result["search_methods"]

    def test_deduplicates_across_methods(self):
        """Verify results are deduplicated across search methods."""
        r = _import_retriever()
        coll = _mock_collection()
        coll.query.return_value = {
            "ids": [["frag-1"]],
            "documents": [["doc1"]],
            "metadatas": [[{"triggers": "parser"}]],
            "distances": [[0.2]],
        }
        coll.get.return_value = {
            "ids": ["frag-1"],
            "documents": ["doc1"],
            "metadatas": [{"triggers": "parser"}],
        }
        client = _mock_chroma_client(coll)

        with patch(
            "aipass.memory.apps.handlers.symbolic.retriever.get_chroma_client",
            return_value=client,
        ):
            result = r["retrieve_fragments"](query="parser", trigger_keywords=["parser"])

        assert result["success"] is True
        frag_ids = [res["id"] for res in result["results"]]
        assert frag_ids.count("frag-1") == 1
        if result["results"]:
            assert result["results"][0].get("relevance_score", 0) > 0


# =============================================================================
# extract_fragments_llm operation logging (extractor.py)
# =============================================================================


class TestExtractFragmentsLlmLogging:
    """extract_fragments_llm() logs every real extraction attempt.

    The key lookup is stubbed via sys.modules, not setattr: extractor imports
    get_api_key inside the function body, and attribute patching let a REAL
    keystore key through to a REAL OpenRouter call (observed: HTTP 401).
    Both tests also hard-block urlopen so this file can never reach the network.
    """

    KEYS_MODULE = "aipass.api.apps.handlers.auth.keys"

    def _block_network(self, monkeypatch):
        import urllib.request

        def _never(req, timeout=30):
            raise AssertionError("test attempted a real network call")

        monkeypatch.setattr(urllib.request, "urlopen", _never)

    def _stub_key(self, monkeypatch, key):
        stub = types.ModuleType(self.KEYS_MODULE)
        setattr(stub, "get_api_key", lambda service: key)
        monkeypatch.setitem(sys.modules, self.KEYS_MODULE, stub)

    def _spy_log(self, monkeypatch):
        from aipass.memory.apps.handlers.symbolic import extractor

        logged = []
        monkeypatch.setattr(
            extractor.json_handler,
            "log_operation",
            lambda op, data: logged.append((op, data)),
        )
        return extractor, logged

    def test_logs_operation_when_all_chunks_fail(self, monkeypatch):
        import urllib.error
        import urllib.request

        extractor, logged = self._spy_log(monkeypatch)
        self._stub_key(monkeypatch, "sk-test-key")

        def _fail(req, timeout=30):
            raise urllib.error.URLError("no network in tests")

        monkeypatch.setattr(urllib.request, "urlopen", _fail)

        result = extractor.extract_fragments_llm([{"role": "user", "content": "hello"}])

        assert result["success"] is False
        assert len(logged) == 1
        op, data = logged[0]
        assert op == "symbolic_extract"
        assert data["success"] is False
        assert data["chunks_failed"] == 1
        assert data["chunks_succeeded"] == 0

    def test_no_log_without_api_key(self, monkeypatch):
        extractor, logged = self._spy_log(monkeypatch)
        self._block_network(monkeypatch)
        self._stub_key(monkeypatch, None)

        result = extractor.extract_fragments_llm([{"role": "user", "content": "hello"}])

        assert result["success"] is False
        assert "No OpenRouter API key" in result["error"]
        assert logged == []

    def test_no_log_for_empty_history(self, monkeypatch):
        extractor, logged = self._spy_log(monkeypatch)
        self._block_network(monkeypatch)

        result = extractor.extract_fragments_llm([])

        assert result["success"] is True
        assert logged == []
