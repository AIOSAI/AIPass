# =================== AIPass ====================
# Name: test_symbolic_extras.py
# Description: Tests for symbolic handler recall and surfacing - the hook's context, recall format and session gates
# Version: 1.1.0
# Created: 2026-04-25
# Modified: 2026-10-08
# =============================================

"""Tests for apps/handlers/symbolic/hook.py — recall and surfacing: context, fragment recall, session gates."""

# Tests for the hook's public functions in the symbolic handler files.
# Split on 2026-10-08 (oversize_test_file): the storage-and-search half
# (storage, deduplicator, chroma_client, retriever, the extractor's log) lives
# in test_symbolic_extras_storage.py; the shared autouse fixtures live in
# support_symbolic_extras.py.
#
# Covers imports required by the seedgo test scanner:
#     from aipass.memory.apps.handlers.symbolic.hook import save_config
#     from aipass.memory.apps.handlers.symbolic.hook import extract_conversation_context
#     from aipass.memory.apps.handlers.symbolic.hook import find_relevant_fragments
#     from aipass.memory.apps.handlers.symbolic.hook import format_fragment_recall
#     from aipass.memory.apps.handlers.symbolic.hook import format_multiple_recalls
#     from aipass.memory.apps.handlers.symbolic.hook import should_surface_fragment
#     from aipass.memory.apps.handlers.symbolic.hook import record_surface
#     from aipass.memory.apps.handlers.symbolic.hook import record_message
#     from aipass.memory.apps.handlers.symbolic.hook import reset_session
#     from aipass.memory.apps.handlers.symbolic.hook import get_session_state
#     from aipass.memory.apps.handlers.symbolic.hook import process_hook

# ---------------------------------------------------------------------------
# PARKED 2026-08-14 — the owner's ruling. The symbolic fragments tier is disabled
# (unused; the Agent Memory Atlas review flagged the AUDN deduplicator for acting
# on an LLM Delete verdict with no record of what was removed). These tests are
# KEPT, not deleted: they document the feature for revival.
# Active curated-truth piece: Compass — drone @devpulse compass.
# Revive: tests/parked/symbolic_20260814/README.md
# ---------------------------------------------------------------------------

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(covered_elsewhere) — write_memory_file(), stood in here; tests/test_changed_entries.py

import pytest as _parked

_parked.skip(
    "symbolic fragments tier PARKED 2026-08-14 (the owner's ruling) — "
    "active piece is Compass; revive via tests/parked/symbolic_20260814/README.md",
    allow_module_level=True,
)

import sys
import time
from unittest.mock import MagicMock

from aipass.memory.tests.support_symbolic_extras import _mock_handler_deps as _mock_handler_deps
from aipass.memory.tests.support_symbolic_extras import _reset_chroma_clients as _reset_chroma_clients
from aipass.memory.tests.support_symbolic_extras import _reset_hook_session as _reset_hook_session


# ---------------------------------------------------------------------------
# Import helpers (must be called inside tests, after mocks are installed)
# ---------------------------------------------------------------------------


def _import_hook():
    sys.modules.pop("aipass.memory.apps.handlers.symbolic.hook", None)
    from aipass.memory.apps.handlers.symbolic.hook import (
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


# ---------------------------------------------------------------------------
# Sample data helpers
# ---------------------------------------------------------------------------


def _sample_messages():
    return [
        {"role": "user", "content": "I found an error in the module"},
        {"role": "assistant", "content": "Let me debug that issue for you"},
    ]


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
        setattr(hook_mod, "memory_files", mock_mf)

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
        # The pattern matches four words in the sample and dedupes through a
        # set, so the CONTENT is exact even though the order is not. An `or`
        # over two of them passed while the other two silently stopped matching.
        assert set(result["keywords"]) == {"error", "module", "debug", "issue"}
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
        setattr(hook_mod, "retriever", mock_retriever)

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
        setattr(hook_mod, "retriever", mock_retriever)

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
        setattr(hook_mod, "retriever", mock_retriever)

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
        setattr(hook_mod, "retriever", mock_retriever)

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
