# ===================AIPASS====================
# META DATA HEADER
# Name: tests/test_symbolic.py
# Date: 2026-03-24
# Version: 1.0.0
# Category: memory/tests
# =============================================

"""Tests for the symbolic memory orchestration module (apps/modules/symbolic.py).

Covers: from aipass.memory.apps.modules.symbolic import extract_technical_flow

The module under test is a thin delegation layer: each public function forwards
to an identically-named function on one of the handler sub-modules (extractor,
storage, retriever).  We mock those handler modules via ``sys.modules`` so
the tests stay lightweight and never touch real ChromaDB / filesystem.
"""

import sys
import types
import pytest
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Module-level mock namespace -- tests read handler mocks from here
# ---------------------------------------------------------------------------

_handler_mocks = types.SimpleNamespace(
    extractor=MagicMock(),
    storage=MagicMock(),
    retriever=MagicMock(),
    trigger=MagicMock(),
)


# ---------------------------------------------------------------------------
# Autouse fixture -- mock all heavy imports before symbolic.py is loaded
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _mock_symbolic_infrastructure(monkeypatch):
    """Replace handler modules with MagicMock before importing symbolic.py."""

    # -- prax logger --------------------------------------------------------
    mock_prax = MagicMock()
    mock_prax.logger = MagicMock()
    monkeypatch.setitem(sys.modules, "aipass.prax", mock_prax)
    monkeypatch.setitem(sys.modules, "aipass.prax.apps", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.prax.apps.modules", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.prax.apps.modules.logger", MagicMock())

    # -- cli display helpers ------------------------------------------------
    cli_modules = MagicMock()
    monkeypatch.setitem(sys.modules, "aipass.cli", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.cli.apps", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.cli.apps.modules", cli_modules)

    # -- memory json handler ------------------------------------------------
    mock_json_handler = MagicMock()
    mock_json_handler.log_operation = MagicMock(return_value=True)
    json_pkg = MagicMock()
    json_pkg.json_handler = mock_json_handler
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.json", json_pkg)
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.json.json_handler", mock_json_handler)

    # -- symbolic handler sub-modules (the delegation targets) --------------
    mock_extractor = MagicMock()
    mock_storage = MagicMock()
    mock_retriever = MagicMock()
    mock_hook = MagicMock()
    mock_deduplicator = MagicMock()

    symbolic_pkg = MagicMock()
    symbolic_pkg.extractor = mock_extractor
    symbolic_pkg.storage = mock_storage
    symbolic_pkg.retriever = mock_retriever
    symbolic_pkg.hook = mock_hook
    symbolic_pkg.deduplicator = mock_deduplicator

    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.symbolic", symbolic_pkg)
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.symbolic.extractor", mock_extractor)
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.symbolic.storage", mock_storage)
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.symbolic.retriever", mock_retriever)
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.symbolic.hook", mock_hook)
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.symbolic.deduplicator", mock_deduplicator)

    # -- vector embedder (imported by storage handler) ----------------------
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.vector", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.vector.embedder", MagicMock())

    # -- trigger (lazy import inside create_fragment) -----------------------
    mock_trigger_core = MagicMock()
    mock_trigger = MagicMock()
    mock_trigger_core.trigger = mock_trigger
    monkeypatch.setitem(sys.modules, "aipass.trigger", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.trigger.apps", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.trigger.apps.modules", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.trigger.apps.modules.core", mock_trigger_core)

    # Force fresh import every test
    monkeypatch.delitem(sys.modules, "aipass.memory.apps.modules.symbolic", raising=False)

    # Expose mocks on the module-level namespace for test-level assertions
    _handler_mocks.extractor = mock_extractor
    _handler_mocks.storage = mock_storage
    _handler_mocks.retriever = mock_retriever
    _handler_mocks.trigger = mock_trigger


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sample_chat() -> list:
    """Return a minimal chat history list."""
    return [
        {"role": "user", "content": "I found a bug in the parser"},
        {"role": "assistant", "content": "Let me debug that for you"},
    ]


def _import_symbolic():
    """Import symbolic module after mocks are in place.

    Must also clear the parent package's cached attribute so Python
    re-executes the module code with fresh mocks.
    """

    # Remove from sys.modules if still present
    sys.modules.pop("aipass.memory.apps.modules.symbolic", None)

    # Clear the parent package's cached attribute so `from ... import symbolic`
    # triggers a fresh import rather than returning the stale attribute.
    parent = sys.modules.get("aipass.memory.apps.modules")
    if parent is not None and hasattr(parent, "symbolic"):
        delattr(parent, "symbolic")

    from aipass.memory.apps.modules import symbolic

    return symbolic


# ===========================================================================
# EXTRACTION DELEGATION TESTS
# ===========================================================================


class TestExtractTechnicalFlow:
    """extract_technical_flow delegates to extractor handler."""

    def test_delegates_to_extractor(self):
        symbolic = _import_symbolic()
        expected = {"success": True, "patterns": ["debugging_session"]}
        _handler_mocks.extractor.extract_technical_flow.return_value = expected

        result = symbolic.extract_technical_flow(_sample_chat())

        _handler_mocks.extractor.extract_technical_flow.assert_called_once_with(_sample_chat())
        assert result == expected

    def test_returns_handler_result_unchanged(self):
        symbolic = _import_symbolic()
        handler_result = {"success": False, "error": "parse failure"}
        _handler_mocks.extractor.extract_technical_flow.return_value = handler_result

        assert symbolic.extract_technical_flow([]) == handler_result


class TestExtractEmotionalJourney:
    """extract_emotional_journey delegates to extractor handler."""

    def test_delegates_to_extractor(self):
        symbolic = _import_symbolic()
        expected = {"success": True, "arc": ["curious", "frustrated", "relieved"]}
        _handler_mocks.extractor.extract_emotional_journey.return_value = expected

        result = symbolic.extract_emotional_journey(_sample_chat())

        _handler_mocks.extractor.extract_emotional_journey.assert_called_once_with(_sample_chat())
        assert result == expected


class TestExtractCollaborationPatterns:
    """extract_collaboration_patterns delegates to extractor handler."""

    def test_delegates_to_extractor(self):
        symbolic = _import_symbolic()
        expected = {"success": True, "patterns": ["pair_debugging"]}
        _handler_mocks.extractor.extract_collaboration_patterns.return_value = expected

        result = symbolic.extract_collaboration_patterns(_sample_chat())

        _handler_mocks.extractor.extract_collaboration_patterns.assert_called_once_with(_sample_chat())
        assert result == expected


class TestExtractKeyLearnings:
    """extract_key_learnings delegates to extractor handler."""

    def test_delegates_to_extractor(self):
        symbolic = _import_symbolic()
        expected = {"success": True, "insights": ["parser edge case"]}
        _handler_mocks.extractor.extract_key_learnings.return_value = expected

        result = symbolic.extract_key_learnings(_sample_chat())

        _handler_mocks.extractor.extract_key_learnings.assert_called_once_with(_sample_chat())
        assert result == expected


class TestExtractContextTriggers:
    """extract_context_triggers delegates to extractor handler."""

    def test_delegates_to_extractor(self):
        symbolic = _import_symbolic()
        expected = {"success": True, "triggers": ["parser", "bug"]}
        _handler_mocks.extractor.extract_context_triggers.return_value = expected

        result = symbolic.extract_context_triggers(_sample_chat())

        _handler_mocks.extractor.extract_context_triggers.assert_called_once_with(_sample_chat())
        assert result == expected


class TestExtractSymbolicDimensions:
    """extract_symbolic_dimensions delegates to extractor handler."""

    def test_delegates_to_extractor(self):
        symbolic = _import_symbolic()
        expected = {
            "success": True,
            "technical_flow": {"patterns": []},
            "emotional_journey": {"arc": []},
        }
        _handler_mocks.extractor.extract_symbolic_dimensions.return_value = expected

        result = symbolic.extract_symbolic_dimensions(_sample_chat())

        _handler_mocks.extractor.extract_symbolic_dimensions.assert_called_once_with(_sample_chat())
        assert result == expected


# ===========================================================================
# STORAGE DELEGATION TESTS
# ===========================================================================


class TestCreateFragment:
    """create_fragment delegates to storage handler and fires trigger."""

    def test_delegates_to_storage(self):
        symbolic = _import_symbolic()
        analysis = {"dimensions": {"technical": "debug"}}
        fragment_result = {
            "success": True,
            "fragment": {"id": "frag-001", "content": "test"},
        }
        _handler_mocks.storage.create_fragment.return_value = fragment_result

        result = symbolic.create_fragment(analysis, content="hello", source_branch="memory")

        _handler_mocks.storage.create_fragment.assert_called_once_with(analysis, "hello", "memory")
        assert result == fragment_result

    def test_fires_trigger_on_success(self):
        symbolic = _import_symbolic()
        _handler_mocks.storage.create_fragment.return_value = {
            "success": True,
            "fragment": {"id": "frag-002"},
        }
        _handler_mocks.trigger.reset_mock()

        symbolic.create_fragment({}, content="x", source_branch="drone")

        _handler_mocks.trigger.fire.assert_called_once_with(
            "fragment_created", fragment_id="frag-002", source_branch="drone"
        )

    def test_no_trigger_on_failure(self):
        symbolic = _import_symbolic()
        _handler_mocks.storage.create_fragment.return_value = {
            "success": False,
            "error": "bad input",
        }
        _handler_mocks.trigger.reset_mock()

        symbolic.create_fragment({})

        _handler_mocks.trigger.fire.assert_not_called()

    def test_trigger_exception_caught_gracefully(self):
        """When trigger.fire raises, create_fragment still returns the result."""
        symbolic = _import_symbolic()
        _handler_mocks.storage.create_fragment.return_value = {
            "success": True,
            "fragment": {"id": "frag-003"},
        }
        _handler_mocks.trigger.fire.side_effect = RuntimeError("trigger boom")

        result = symbolic.create_fragment({}, source_branch="test")

        assert result["success"] is True
        assert result["fragment"]["id"] == "frag-003"

    def test_default_source_branch_is_unknown(self):
        """When source_branch is None, trigger receives 'unknown'."""
        symbolic = _import_symbolic()
        _handler_mocks.storage.create_fragment.return_value = {
            "success": True,
            "fragment": {"id": "frag-004"},
        }
        _handler_mocks.trigger.reset_mock()

        symbolic.create_fragment({})

        _handler_mocks.trigger.fire.assert_called_once_with(
            "fragment_created", fragment_id="frag-004", source_branch="unknown"
        )


# ===========================================================================
# EMPTY INPUT / EDGE CASE TESTS
# ===========================================================================


class TestEmptyChatHistory:
    """Verify wrapper functions forward empty lists without crashing."""

    def test_extract_technical_flow_empty(self):
        symbolic = _import_symbolic()
        expected = {"success": True, "patterns": ["no_conversation"]}
        _handler_mocks.extractor.extract_technical_flow.return_value = expected

        result = symbolic.extract_technical_flow([])

        _handler_mocks.extractor.extract_technical_flow.assert_called_once_with([])
        assert result == expected

    def test_extract_emotional_journey_empty(self):
        symbolic = _import_symbolic()
        expected = {"success": True, "arc": []}
        _handler_mocks.extractor.extract_emotional_journey.return_value = expected

        result = symbolic.extract_emotional_journey([])

        assert result == expected

    def test_extract_collaboration_patterns_empty(self):
        symbolic = _import_symbolic()
        expected = {"success": True, "patterns": []}
        _handler_mocks.extractor.extract_collaboration_patterns.return_value = expected

        result = symbolic.extract_collaboration_patterns([])

        assert result == expected

    def test_extract_key_learnings_empty(self):
        symbolic = _import_symbolic()
        expected = {"success": True, "insights": []}
        _handler_mocks.extractor.extract_key_learnings.return_value = expected

        result = symbolic.extract_key_learnings([])

        assert result == expected

    def test_extract_context_triggers_empty(self):
        symbolic = _import_symbolic()
        expected = {"success": True, "triggers": []}
        _handler_mocks.extractor.extract_context_triggers.return_value = expected

        result = symbolic.extract_context_triggers([])

        assert result == expected

    def test_extract_symbolic_dimensions_empty(self):
        symbolic = _import_symbolic()
        expected = {"success": True}
        _handler_mocks.extractor.extract_symbolic_dimensions.return_value = expected

        result = symbolic.extract_symbolic_dimensions([])

        assert result == expected
