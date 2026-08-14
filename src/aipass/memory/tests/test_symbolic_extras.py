# =================== AIPass ====================
# Name: test_symbolic_extras.py
# Description: Tests for symbolic handler public functions
# Version: 1.0.0
# Created: 2026-04-25
# Modified: 2026-04-25
# =============================================

"""Tests for 23 untested public functions in symbolic handler files.

Covers imports required by the seedgo test scanner:
    from aipass.memory.apps.handlers.symbolic.hook import save_config
    from aipass.memory.apps.handlers.symbolic.hook import extract_conversation_context
    from aipass.memory.apps.handlers.symbolic.hook import find_relevant_fragments
    from aipass.memory.apps.handlers.symbolic.hook import format_fragment_recall
    from aipass.memory.apps.handlers.symbolic.hook import format_multiple_recalls
    from aipass.memory.apps.handlers.symbolic.hook import should_surface_fragment
    from aipass.memory.apps.handlers.symbolic.hook import record_surface
    from aipass.memory.apps.handlers.symbolic.hook import record_message
    from aipass.memory.apps.handlers.symbolic.hook import reset_session
    from aipass.memory.apps.handlers.symbolic.hook import get_session_state
    from aipass.memory.apps.handlers.symbolic.hook import process_hook
    from aipass.memory.apps.handlers.symbolic.storage import flatten_dimensions
    from aipass.memory.apps.handlers.symbolic.storage import store_fragment
    from aipass.memory.apps.handlers.symbolic.storage import store_fragments_batch
    from aipass.memory.apps.handlers.symbolic.storage import store_llm_fragment
    from aipass.memory.apps.handlers.symbolic.storage import store_llm_fragments_batch
    from aipass.memory.apps.handlers.symbolic.storage import delete_fragment
    from aipass.memory.apps.handlers.symbolic.deduplicator import deduplicate_fragment
    from aipass.memory.apps.handlers.symbolic.chroma_client import get_chroma_client
    from aipass.memory.apps.handlers.symbolic.retriever import search_by_vector
    from aipass.memory.apps.handlers.symbolic.retriever import search_by_dimensions
    from aipass.memory.apps.handlers.symbolic.retriever import search_by_triggers
    from aipass.memory.apps.handlers.symbolic.retriever import retrieve_fragments
"""

# ---------------------------------------------------------------------------
# PARKED 2026-08-14 — Patrick's ruling. The symbolic fragments tier is disabled
# (unused; the Agent Memory Atlas review flagged the AUDN deduplicator for acting
# on an LLM Delete verdict with no record of what was removed). These tests are
# KEPT, not deleted: they document the feature for revival.
# Active curated-truth piece: Compass — drone @devpulse compass.
# Revive: .archive/parked_symbolic_20260814/README.md
# ---------------------------------------------------------------------------
import pytest as _parked

_parked.skip(
    "symbolic fragments tier PARKED 2026-08-14 (Patrick's ruling) — "
    "active piece is Compass; revive via .archive/parked_symbolic_20260814/README.md",
    allow_module_level=True,
)

import json
import sys
import time
import types
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _mock_handler_deps(monkeypatch):
    """Mock heavy handler-level imports used directly by the handler files.

    Builds on the conftest autouse ``_mock_infrastructure`` which already mocks
    prax logger, json_handler, and trigger at the sys.modules level.

    Here we additionally mock:
    - memory_files (used by hook.py save_config/load_config)
    - embedder (used by storage.py and retriever.py)
    - chromadb (used by chroma_client.py)
    - api keys (used by deduplicator.py)
    """
    # -- memory_files (used by hook) ----------------------------------------
    mock_memory_files = MagicMock()
    mock_memory_files.write_memory_file = MagicMock(return_value={"success": True})
    mock_memory_files.read_memory_file = MagicMock(
        return_value={"success": True, "data": {"enabled": True, "threshold": 0.3}}
    )
    monkeypatch.setitem(
        sys.modules,
        "aipass.memory.apps.handlers.json.memory_files",
        mock_memory_files,
    )

    # -- embedder (used by storage + retriever) -----------------------------
    mock_embedder = MagicMock()
    mock_embedder.encode_batch = MagicMock(return_value={"success": True, "embeddings": [[0.1, 0.2, 0.3]]})
    vector_pkg = MagicMock()
    vector_pkg.embedder = mock_embedder
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.vector", vector_pkg)
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.vector.embedder", mock_embedder)

    # -- chromadb (used by chroma_client) -----------------------------------
    mock_chromadb = MagicMock()
    monkeypatch.setitem(sys.modules, "chromadb", mock_chromadb)

    # -- api keys (used by deduplicator) ------------------------------------
    mock_keys = MagicMock()
    mock_keys.get_api_key = MagicMock(return_value="test-api-key")
    monkeypatch.setitem(sys.modules, "aipass.api", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.api.apps", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.api.apps.handlers", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.api.apps.handlers.auth", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.api.apps.handlers.auth.keys", mock_keys)

    # Force-clear cached handler modules so they re-import with mocks
    for mod_name in [
        "aipass.memory.apps.handlers.symbolic.hook",
        "aipass.memory.apps.handlers.symbolic.storage",
        "aipass.memory.apps.handlers.symbolic.retriever",
        "aipass.memory.apps.handlers.symbolic.deduplicator",
        "aipass.memory.apps.handlers.symbolic.chroma_client",
    ]:
        monkeypatch.delitem(sys.modules, mod_name, raising=False)


@pytest.fixture(autouse=True)
def _reset_hook_session():
    """Reset hook SESSION_STATE before each test."""
    yield
    # Post-test cleanup: if the module was loaded, reset its state
    hook_mod = sys.modules.get("aipass.memory.apps.handlers.symbolic.hook")
    if hook_mod and hasattr(hook_mod, "reset_session"):
        hook_mod.reset_session()


@pytest.fixture(autouse=True)
def _reset_chroma_clients():
    """Clear the chroma_client singleton cache between tests."""
    yield
    cc_mod = sys.modules.get("aipass.memory.apps.handlers.symbolic.chroma_client")
    if cc_mod and hasattr(cc_mod, "_clients"):
        cc_mod._clients.clear()


# ---------------------------------------------------------------------------
# Import helpers (must be called inside tests, after mocks are installed)
# ---------------------------------------------------------------------------


def _import_hook():  # noqa: D103
    sys.modules.pop("aipass.memory.apps.handlers.symbolic.hook", None)
    from aipass.memory.apps.handlers.symbolic.hook import (  # noqa: E402
        extract_conversation_context,
        find_relevant_fragments,
        format_fragment_recall,
        format_multiple_recalls,
        get_session_state,
        process_hook,
        record_message,
        record_surface,
        reset_session,
        save_config,
        should_surface_fragment,
    )

    return {
        "save_config": save_config,
        "extract_conversation_context": extract_conversation_context,
        "find_relevant_fragments": find_relevant_fragments,
        "format_fragment_recall": format_fragment_recall,
        "format_multiple_recalls": format_multiple_recalls,
        "should_surface_fragment": should_surface_fragment,
        "record_surface": record_surface,
        "record_message": record_message,
        "reset_session": reset_session,
        "get_session_state": get_session_state,
        "process_hook": process_hook,
    }


def _import_storage():  # noqa: D103
    sys.modules.pop("aipass.memory.apps.handlers.symbolic.storage", None)
    from aipass.memory.apps.handlers.symbolic.storage import (  # noqa: E402
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


def _import_deduplicator():  # noqa: D103
    sys.modules.pop("aipass.memory.apps.handlers.symbolic.deduplicator", None)
    from aipass.memory.apps.handlers.symbolic.deduplicator import deduplicate_fragment  # noqa: E402

    return deduplicate_fragment


def _import_chroma_client():  # noqa: D103
    sys.modules.pop("aipass.memory.apps.handlers.symbolic.chroma_client", None)
    from aipass.memory.apps.handlers.symbolic.chroma_client import get_chroma_client  # noqa: E402

    return get_chroma_client


def _import_retriever():  # noqa: D103
    sys.modules.pop("aipass.memory.apps.handlers.symbolic.retriever", None)
    from aipass.memory.apps.handlers.symbolic.retriever import (  # noqa: E402
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


def _sample_messages():  # noqa: D103
    return [
        {"role": "user", "content": "I found an error in the module"},
        {"role": "assistant", "content": "Let me debug that issue for you"},
    ]


def _v1_fragment():  # noqa: D103
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


def _v2_fragment():  # noqa: D103
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
# 1. hook.save_config
# ===========================================================================


class TestSaveConfig:
    """Tests for hook.save_config."""

    def test_saves_via_memory_files(self, tmp_path):
        """Verify save_config delegates to memory_files.write_memory_file."""
        h = _import_hook()
        hook_mod = sys.modules["aipass.memory.apps.handlers.symbolic.hook"]
        mock_mf = MagicMock()
        mock_mf.write_memory_file = MagicMock(return_value={"success": True})
        setattr(hook_mod, "memory_files", mock_mf)  # noqa: B010

        config = {"enabled": True, "threshold": 0.5}
        path = tmp_path / "config.json"

        result = h["save_config"](config, config_path=path)

        assert result["success"] is True
        mock_mf.write_memory_file.assert_called_once_with(path, config)

    def test_creates_parent_directories(self, tmp_path):
        """Verify save_config creates missing parent directories."""
        h = _import_hook()
        path = tmp_path / "deep" / "nested" / "config.json"

        h["save_config"]({"enabled": True}, config_path=path)

        assert path.parent.exists()


# ===========================================================================
# 2. hook.extract_conversation_context
# ===========================================================================


class TestExtractConversationContext:
    """Tests for hook.extract_conversation_context."""

    def test_extracts_keywords_from_messages(self):
        """Verify keywords are extracted from message content."""
        h = _import_hook()
        result = h["extract_conversation_context"](_sample_messages())

        assert result["success"] is True
        assert isinstance(result["keywords"], list)
        assert "error" in result["keywords"] or "debug" in result["keywords"]
        assert result["analyzed_messages"] == 2

    def test_empty_messages_returns_neutral(self):
        """Verify empty messages produce neutral defaults."""
        h = _import_hook()
        result = h["extract_conversation_context"]([])

        assert result["success"] is True
        assert result["keywords"] == []
        assert result["mood"] == "neutral"

    def test_max_messages_limits_analysis(self):
        """Verify max_messages parameter limits analyzed messages."""
        h = _import_hook()
        msgs = [{"role": "user", "content": f"msg {i}"} for i in range(20)]
        result = h["extract_conversation_context"](msgs, max_messages=3)

        assert result["analyzed_messages"] == 3

    def test_mood_detection(self):
        """Verify frustrated mood is detected from content."""
        h = _import_hook()
        msgs = [{"role": "user", "content": "I'm frustrated and stuck on this ugh"}]
        result = h["extract_conversation_context"](msgs)

        assert result["mood"] == "frustrated"

    def test_theme_extraction(self):
        """Verify debugging theme is extracted from content."""
        h = _import_hook()
        msgs = [{"role": "user", "content": "debug the error and fix the trace bug"}]
        result = h["extract_conversation_context"](msgs)

        assert "debugging" in result["themes"]


# ===========================================================================
# 3. hook.find_relevant_fragments
# ===========================================================================


class TestFindRelevantFragments:
    """Tests for hook.find_relevant_fragments."""

    def test_returns_empty_when_no_context(self):
        """Verify empty context returns no fragments."""
        h = _import_hook()
        context = {"keywords": [], "mood": "neutral", "themes": []}

        result = h["find_relevant_fragments"](context)

        assert result["success"] is True
        assert result["fragments"] == []

    def test_calls_retriever_with_query(self):
        """Verify retriever is called with extracted context."""
        h = _import_hook()
        hook_mod = sys.modules["aipass.memory.apps.handlers.symbolic.hook"]
        mock_retriever = MagicMock()
        mock_retriever.retrieve_fragments = MagicMock(
            return_value={
                "success": True,
                "results": [{"id": "frag1", "relevance_score": 0.8, "content": "test"}],
            }
        )
        setattr(hook_mod, "retriever", mock_retriever)  # noqa: B010

        context = {
            "keywords": ["error", "debug"],
            "mood": "frustrated",
            "themes": ["debugging"],
        }
        result = h["find_relevant_fragments"](context)

        assert result["success"] is True
        mock_retriever.retrieve_fragments.assert_called_once()

    def test_filters_below_threshold(self):
        """Verify fragments below threshold are filtered out."""
        h = _import_hook()
        hook_mod = sys.modules["aipass.memory.apps.handlers.symbolic.hook"]
        mock_retriever = MagicMock()
        mock_retriever.retrieve_fragments = MagicMock(
            return_value={
                "success": True,
                "results": [
                    {"id": "frag1", "relevance_score": 0.1, "content": "low score"},
                ],
            }
        )
        setattr(hook_mod, "retriever", mock_retriever)  # noqa: B010

        context = {"keywords": ["error"], "mood": "neutral", "themes": ["debugging"]}
        result = h["find_relevant_fragments"](context)

        assert result["success"] is True
        assert len(result["fragments"]) == 0


# ===========================================================================
# 4. hook.format_fragment_recall
# ===========================================================================


class TestFormatFragmentRecall:
    """Tests for hook.format_fragment_recall."""

    def test_v1_fragment_basic_format(self):
        """Verify v1 fragments format with dimension metadata."""
        h = _import_hook()
        frag = {
            "content": "Short content",
            "metadata": {
                "emotional_0": "frustration_to_breakthrough",
                "technical_0": "debugging_session",
                "learnings_0": "edge_case_handling",
            },
        }
        result = h["format_fragment_recall"](frag)

        assert "frustration" in result
        assert "debugging session" in result
        assert "edge case handling" in result

    def test_v2_fragment_episodic_format(self):
        """Verify v2 episodic fragments use correct prefix."""
        h = _import_hook()
        frag = {
            "content": "test",
            "metadata": {
                "schema_version": "v2",
                "summary": "Debugged parser",
                "insight": "Check boundaries",
                "type": "episodic",
            },
        }
        result = h["format_fragment_recall"](frag)

        assert "During a session" in result
        assert "Debugged parser" in result
        assert "Check boundaries" in result

    def test_v2_procedural_type(self):
        """Verify v2 procedural fragments use learned-how-to prefix."""
        h = _import_hook()
        frag = {
            "content": "",
            "metadata": {
                "schema_version": "v2",
                "summary": "Use pathlib for paths",
                "insight": "",
                "type": "procedural",
            },
        }
        result = h["format_fragment_recall"](frag)

        assert "We learned how to:" in result

    def test_v2_no_insight_ends_with_period(self):
        """Verify v2 recall without insight ends with period."""
        h = _import_hook()
        frag = {
            "content": "",
            "metadata": {
                "schema_version": "v2",
                "summary": "Something happened",
                "insight": "",
                "type": "semantic",
            },
        }
        result = h["format_fragment_recall"](frag)

        assert result.endswith(".")

    def test_v1_fragment_no_metadata(self):
        """Verify v1 fragments with empty metadata use default text."""
        h = _import_hook()
        frag = {"content": "Short", "metadata": {}}
        result = h["format_fragment_recall"](frag)

        assert "This reminds me of a past conversation" in result


# ===========================================================================
# 5. hook.format_multiple_recalls
# ===========================================================================


class TestFormatMultipleRecalls:
    """Tests for hook.format_multiple_recalls."""

    def test_empty_list_returns_empty_string(self):
        """Verify empty list produces empty string."""
        h = _import_hook()
        assert h["format_multiple_recalls"]([]) == ""

    def test_single_fragment(self):
        """Verify single fragment includes schema tag."""
        h = _import_hook()
        frag = {
            "content": "Test",
            "metadata": {
                "schema_version": "v2",
                "summary": "Hello",
                "insight": "",
                "type": "",
            },
        }
        result = h["format_multiple_recalls"]([frag])

        assert "[v2]" in result

    def test_multiple_fragments_separated_by_dividers(self):
        """Verify multiple fragments are separated by dividers."""
        h = _import_hook()
        frags = [
            {"content": "A", "metadata": {}},
            {
                "content": "B",
                "metadata": {
                    "schema_version": "v2",
                    "summary": "B frag",
                    "insight": "",
                    "type": "",
                },
            },
        ]
        result = h["format_multiple_recalls"](frags)

        assert "---" in result
        assert "[v1]" in result
        assert "[v2]" in result


# ===========================================================================
# 6. hook.should_surface_fragment
# ===========================================================================


class TestShouldSurfaceFragment:
    """Tests for hook.should_surface_fragment."""

    def test_disabled_hook(self):
        """Verify disabled hook returns False."""
        h = _import_hook()
        h["reset_session"]()
        can, reason = h["should_surface_fragment"](config={"enabled": False})

        assert can is False
        assert "disabled" in reason

    def test_max_fragments_reached(self):
        """Verify max fragments per session blocks surfacing."""
        h = _import_hook()
        h["reset_session"]()
        hook_mod = sys.modules["aipass.memory.apps.handlers.symbolic.hook"]
        hook_mod.SESSION_STATE["fragments_surfaced"] = 5

        can, reason = h["should_surface_fragment"](
            config={
                "enabled": True,
                "max_fragments_per_session": 5,
                "min_messages_between": 0,
                "cooldown_seconds": 0,
            }
        )
        assert can is False
        assert "Max fragments" in reason

    def test_not_enough_messages(self):
        """Verify insufficient messages blocks surfacing."""
        h = _import_hook()
        h["reset_session"]()
        can, reason = h["should_surface_fragment"](
            config={
                "enabled": True,
                "max_fragments_per_session": 10,
                "min_messages_between": 5,
                "cooldown_seconds": 0,
            }
        )
        assert can is False
        assert "messages since last" in reason

    def test_cooldown_active(self):
        """Verify active cooldown blocks surfacing."""
        h = _import_hook()
        h["reset_session"]()
        hook_mod = sys.modules["aipass.memory.apps.handlers.symbolic.hook"]
        hook_mod.SESSION_STATE["messages_since_last"] = 100
        hook_mod.SESSION_STATE["last_surface_time"] = time.time()

        can, reason = h["should_surface_fragment"](
            config={
                "enabled": True,
                "max_fragments_per_session": 10,
                "min_messages_between": 0,
                "cooldown_seconds": 600,
            }
        )
        assert can is False
        assert "Cooldown" in reason

    def test_already_surfaced_fragment(self):
        """Verify duplicate fragment is blocked."""
        h = _import_hook()
        h["reset_session"]()
        hook_mod = sys.modules["aipass.memory.apps.handlers.symbolic.hook"]
        hook_mod.SESSION_STATE["messages_since_last"] = 100
        hook_mod.SESSION_STATE["surfaced_ids"].add("frag-001")

        can, reason = h["should_surface_fragment"](
            fragment={"id": "frag-001"},
            config={
                "enabled": True,
                "max_fragments_per_session": 10,
                "min_messages_between": 0,
                "cooldown_seconds": 0,
            },
        )
        assert can is False
        assert "already surfaced" in reason

    def test_ready_to_surface(self):
        """Verify all conditions met returns True."""
        h = _import_hook()
        h["reset_session"]()
        hook_mod = sys.modules["aipass.memory.apps.handlers.symbolic.hook"]
        hook_mod.SESSION_STATE["messages_since_last"] = 100

        can, reason = h["should_surface_fragment"](
            config={
                "enabled": True,
                "max_fragments_per_session": 10,
                "min_messages_between": 0,
                "cooldown_seconds": 0,
            }
        )
        assert can is True
        assert "Ready" in reason


# ===========================================================================
# 7. hook.record_surface
# ===========================================================================


class TestRecordSurface:
    """Tests for hook.record_surface."""

    def test_increments_counters(self):
        """Verify surface recording updates all counters."""
        h = _import_hook()
        h["reset_session"]()
        hook_mod = sys.modules["aipass.memory.apps.handlers.symbolic.hook"]
        hook_mod.SESSION_STATE["messages_since_last"] = 15

        h["record_surface"]({"id": "frag-001"})

        state = h["get_session_state"]()
        assert state["fragments_surfaced"] == 1
        assert state["messages_since_last"] == 0
        assert state["surfaced_count"] == 1

    def test_records_fragment_without_id(self):
        """Verify fragment without id does not raise."""
        h = _import_hook()
        h["reset_session"]()
        h["record_surface"]({"content": "no id here"})

        state = h["get_session_state"]()
        assert state["fragments_surfaced"] == 1
        assert state["surfaced_count"] == 0


# ===========================================================================
# 8. hook.record_message
# ===========================================================================


class TestRecordMessage:
    """Tests for hook.record_message."""

    def test_increments_counter(self):
        """Verify message counter increments correctly."""
        h = _import_hook()
        h["reset_session"]()

        h["record_message"]()
        h["record_message"]()
        h["record_message"]()

        state = h["get_session_state"]()
        assert state["messages_since_last"] == 3


# ===========================================================================
# 9. hook.reset_session
# ===========================================================================


class TestResetSession:
    """Tests for hook.reset_session."""

    def test_clears_all_state(self):
        """Verify reset clears all session state fields."""
        h = _import_hook()
        hook_mod = sys.modules["aipass.memory.apps.handlers.symbolic.hook"]

        hook_mod.SESSION_STATE["fragments_surfaced"] = 99
        hook_mod.SESSION_STATE["messages_since_last"] = 99
        hook_mod.SESSION_STATE["last_surface_time"] = 99999
        hook_mod.SESSION_STATE["surfaced_ids"] = {"a", "b", "c"}

        h["reset_session"]()

        state = h["get_session_state"]()
        assert state["fragments_surfaced"] == 0
        assert state["messages_since_last"] == 0
        assert state["last_surface_time"] == 0
        assert state["surfaced_count"] == 0


# ===========================================================================
# 10. hook.get_session_state
# ===========================================================================


class TestGetSessionState:
    """Tests for hook.get_session_state."""

    def test_returns_dict_with_expected_keys(self):
        """Verify returned dict contains all expected keys."""
        h = _import_hook()
        h["reset_session"]()

        state = h["get_session_state"]()

        assert "fragments_surfaced" in state
        assert "messages_since_last" in state
        assert "last_surface_time" in state
        assert "surfaced_count" in state


# ===========================================================================
# 11. hook.process_hook
# ===========================================================================


class TestProcessHook:
    """Tests for hook.process_hook."""

    def test_returns_not_surfaced_when_blocked(self):
        """Verify blocked state returns surfaced=False."""
        h = _import_hook()
        h["reset_session"]()
        result = h["process_hook"](_sample_messages())

        assert result["success"] is True
        assert result["surfaced"] is False

    def test_returns_not_surfaced_when_disabled(self):
        """Verify disabled config returns surfaced=False."""
        h = _import_hook()
        h["reset_session"]()
        result = h["process_hook"](_sample_messages(), config={"enabled": False})

        assert result["success"] is True
        assert result["surfaced"] is False
        assert "disabled" in result["reason"]

    def test_surfaces_when_conditions_met(self):
        """Verify full pipeline surfaces a fragment when conditions are met."""
        h = _import_hook()
        h["reset_session"]()
        hook_mod = sys.modules["aipass.memory.apps.handlers.symbolic.hook"]
        hook_mod.SESSION_STATE["messages_since_last"] = 100

        mock_retriever = MagicMock()
        mock_retriever.retrieve_fragments = MagicMock(
            return_value={
                "success": True,
                "results": [
                    {
                        "id": "frag-surface-1",
                        "content": "Past debugging session",
                        "metadata": {},
                        "relevance_score": 0.9,
                    }
                ],
            }
        )
        setattr(hook_mod, "retriever", mock_retriever)  # noqa: B010

        config = {
            "enabled": True,
            "threshold": 0.3,
            "max_fragments_per_session": 10,
            "min_messages_between": 0,
            "cooldown_seconds": 0,
        }

        result = h["process_hook"](_sample_messages(), config=config)

        assert result["success"] is True
        assert result["surfaced"] is True
        assert "recall" in result

    def test_no_fragments_above_threshold(self):
        """Verify low-scoring fragments are not surfaced."""
        h = _import_hook()
        h["reset_session"]()
        hook_mod = sys.modules["aipass.memory.apps.handlers.symbolic.hook"]
        hook_mod.SESSION_STATE["messages_since_last"] = 100

        mock_retriever = MagicMock()
        mock_retriever.retrieve_fragments = MagicMock(
            return_value={
                "success": True,
                "results": [
                    {
                        "id": "frag-low",
                        "content": "low",
                        "metadata": {},
                        "relevance_score": 0.05,
                    }
                ],
            }
        )
        setattr(hook_mod, "retriever", mock_retriever)  # noqa: B010

        config = {
            "enabled": True,
            "threshold": 0.3,
            "max_fragments_per_session": 10,
            "min_messages_between": 0,
            "cooldown_seconds": 0,
        }

        result = h["process_hook"](_sample_messages(), config=config)

        assert result["success"] is True
        assert result["surfaced"] is False


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
        setattr(keys_mod, "get_api_key", MagicMock(return_value=None))  # noqa: B010

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
        assert "key" in result["reason"].lower() or "unavailable" in result["reason"].lower()


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
        setattr(chromadb_mod, "PersistentClient", MagicMock(return_value=mock_client))  # noqa: B010

        db_path = tmp_path / "test_chroma"
        result = get_chroma_client(db_path)

        assert result == mock_client
        chromadb_mod.PersistentClient.assert_called_once()

    def test_caches_client_by_path(self, tmp_path):
        """Verify same path returns cached client."""
        get_chroma_client = _import_chroma_client()
        chromadb_mod = sys.modules["chromadb"]
        mock_client = MagicMock()
        setattr(chromadb_mod, "PersistentClient", MagicMock(return_value=mock_client))  # noqa: B010

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
        setattr(chromadb_mod, "PersistentClient", MagicMock(return_value=mock_client))  # noqa: B010

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
        assert "Query" in result["error"] or "required" in result["error"]

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
