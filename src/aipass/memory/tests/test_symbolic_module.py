# ===================AIPASS====================
# META DATA HEADER
# Name: tests/test_symbolic_module.py
# Date: 2026-04-25
# Version: 1.0.0
# Category: memory/tests
# =============================================

"""Tests for untested public functions in apps/modules/symbolic.py.

Covers the 25 public functions listed below.  The module under test is a thin
delegation layer: most functions forward to handler sub-modules.  We mock those
handlers so tests stay lightweight with no live ChromaDB / filesystem / API.

Thin wrappers:
  from aipass.memory.apps.modules.symbolic import analyze_conversation
  from aipass.memory.apps.modules.symbolic import store_fragment
  from aipass.memory.apps.modules.symbolic import store_fragments_batch
  from aipass.memory.apps.modules.symbolic import flatten_dimensions
  from aipass.memory.apps.modules.symbolic import store_llm_fragment
  from aipass.memory.apps.modules.symbolic import store_llm_fragments_batch
  from aipass.memory.apps.modules.symbolic import deduplicate_fragment
  from aipass.memory.apps.modules.symbolic import extract_and_store_llm
  from aipass.memory.apps.modules.symbolic import retrieve_fragments
  from aipass.memory.apps.modules.symbolic import search_fragments_by_vector
  from aipass.memory.apps.modules.symbolic import search_fragments_by_dimensions
  from aipass.memory.apps.modules.symbolic import search_fragments_by_triggers
  from aipass.memory.apps.modules.symbolic import extract_conversation_context
  from aipass.memory.apps.modules.symbolic import find_relevant_fragments
  from aipass.memory.apps.modules.symbolic import format_fragment_recall
  from aipass.memory.apps.modules.symbolic import should_surface_fragment
  from aipass.memory.apps.modules.symbolic import process_hook
  from aipass.memory.apps.modules.symbolic import load_hook_config
  from aipass.memory.apps.modules.symbolic import reset_hook_session
  from aipass.memory.apps.modules.symbolic import get_hook_session_state

CLI/display:
  from aipass.memory.apps.modules.symbolic import run_demo
  from aipass.memory.apps.modules.symbolic import search_fragments_cli
  from aipass.memory.apps.modules.symbolic import run_hook_test
  from aipass.memory.apps.modules.symbolic import analyze_file
  from aipass.memory.apps.modules.symbolic import bootstrap_from_jsonl
"""

# ---------------------------------------------------------------------------
# PARKED 2026-08-14 — Patrick's ruling. The symbolic fragments tier is disabled
# (unused; the Agent Memory Atlas review flagged the AUDN deduplicator for acting
# on an LLM Delete verdict with no record of what was removed). These tests are
# KEPT, not deleted: they document the feature for revival.
# Active curated-truth piece: Compass — drone @devpulse compass.
# Revive: tests/parked/symbolic_20260814/README.md
# ---------------------------------------------------------------------------
import pytest as _parked

_parked.skip(
    "symbolic fragments tier PARKED 2026-08-14 (Patrick's ruling) — "
    "active piece is Compass; revive via tests/parked/symbolic_20260814/README.md",
    allow_module_level=True,
)

import sys
import types
import pytest
from pathlib import Path
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# Module-level mock namespace -- tests read handler mocks from here
# ---------------------------------------------------------------------------

_handler_mocks = types.SimpleNamespace(
    extractor=MagicMock(),
    storage=MagicMock(),
    retriever=MagicMock(),
    hook=MagicMock(),
    deduplicator=MagicMock(),
    trigger=MagicMock(),
    console=MagicMock(),
    header=MagicMock(),
    error_fn=MagicMock(),
    warning_fn=MagicMock(),
    json_handler=MagicMock(),
    memory_files=MagicMock(),
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
    mock_console = MagicMock()
    mock_header = MagicMock()
    mock_error = MagicMock()
    mock_warning = MagicMock()
    cli_modules = MagicMock()
    cli_modules.console = mock_console
    cli_modules.header = mock_header
    cli_modules.error = mock_error
    cli_modules.warning = mock_warning
    monkeypatch.setitem(sys.modules, "aipass.cli", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.cli.apps", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.cli.apps.modules", cli_modules)

    # -- memory json handler ------------------------------------------------
    mock_json_handler = MagicMock()
    mock_json_handler.log_operation = MagicMock(return_value=True)
    json_pkg = MagicMock()
    # Impersonating a package means answering __path__ — a bare MagicMock does not,
    # and every lazy submodule import under it then dies. See test_import_isolation.py.
    json_pkg.__path__ = [str(Path(__file__).resolve().parent.parent / "apps" / "handlers" / "json")]
    json_pkg.json_handler = mock_json_handler
    mock_memory_files = MagicMock()
    json_pkg.memory_files = mock_memory_files
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.json", json_pkg)
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.json.json_handler", mock_json_handler)
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.json.memory_files", mock_memory_files)

    # -- symbolic handler sub-modules (the delegation targets) --------------
    mock_extractor = MagicMock()
    mock_storage = MagicMock()
    mock_retriever = MagicMock()
    mock_hook = MagicMock()
    mock_deduplicator = MagicMock()

    # Give hook a SESSION_STATE dict for run_hook_test
    mock_hook.SESSION_STATE = {"messages_since_last": 0, "last_surface_time": 0}

    symbolic_pkg = MagicMock()

    # (test_import_isolation.py) — a bare MagicMock has none, and any lazy

    # submodule import under it then dies with "is not a package".

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
    monkeypatch.setitem(
        sys.modules,
        "aipass.memory.apps.handlers.symbolic.deduplicator",
        mock_deduplicator,
    )

    # -- vector embedder (imported by storage handler) ----------------------
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.vector", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.vector.embedder", MagicMock())

    # -- trigger (lazy import inside create_fragment / store_fragment) ------
    mock_trigger_core = MagicMock()
    mock_trigger = MagicMock()
    mock_trigger_core.trigger = mock_trigger
    monkeypatch.setitem(sys.modules, "aipass.trigger", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.trigger.apps", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.trigger.apps.modules", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.trigger.apps.modules.core", mock_trigger_core)

    # -- trigger error report (lazy import inside extract_and_store_llm) ---
    mock_errors_mod = MagicMock()
    monkeypatch.setitem(sys.modules, "aipass.trigger.apps.modules.errors", mock_errors_mod)

    # -- rich Panel (lazy import in search_fragments_cli / run_hook_test) ---
    monkeypatch.setitem(sys.modules, "rich", MagicMock())
    monkeypatch.setitem(sys.modules, "rich.panel", MagicMock())

    # -- chromadb (used in bootstrap_from_jsonl summary) --------------------
    monkeypatch.setitem(sys.modules, "chromadb", MagicMock())

    # Force fresh import every test
    monkeypatch.delitem(sys.modules, "aipass.memory.apps.modules.symbolic", raising=False)

    # Expose mocks on the module-level namespace for test-level assertions
    _handler_mocks.extractor = mock_extractor
    _handler_mocks.storage = mock_storage
    _handler_mocks.retriever = mock_retriever
    _handler_mocks.hook = mock_hook
    _handler_mocks.deduplicator = mock_deduplicator
    _handler_mocks.trigger = mock_trigger
    _handler_mocks.console = mock_console
    _handler_mocks.header = mock_header
    _handler_mocks.error_fn = mock_error
    _handler_mocks.warning_fn = mock_warning
    _handler_mocks.json_handler = mock_json_handler
    _handler_mocks.memory_files = mock_memory_files


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
    """Import symbolic module after mocks are in place."""
    sys.modules.pop("aipass.memory.apps.modules.symbolic", None)
    parent = sys.modules.get("aipass.memory.apps.modules")
    if parent is not None and hasattr(parent, "symbolic"):
        delattr(parent, "symbolic")

    from aipass.memory.apps.modules import symbolic

    return symbolic


# ===========================================================================
# 1. analyze_conversation
# ===========================================================================


class TestAnalyzeConversation:
    """analyze_conversation delegates to extractor.analyze_conversation."""

    def test_delegates_to_extractor(self):
        symbolic = _import_symbolic()
        expected = {
            "success": True,
            "dimensions": {"technical": ["debug"]},
            "metadata": {"total_words": 20},
            "message_count": 2,
        }
        _handler_mocks.extractor.analyze_conversation.return_value = expected

        result = symbolic.analyze_conversation(_sample_chat())

        _handler_mocks.extractor.analyze_conversation.assert_called_once_with(_sample_chat())
        assert result == expected

    def test_returns_handler_result_unchanged(self):
        symbolic = _import_symbolic()
        handler_result = {"success": False, "error": "bad input"}
        _handler_mocks.extractor.analyze_conversation.return_value = handler_result

        assert symbolic.analyze_conversation([]) == handler_result


# ===========================================================================
# 2. store_fragment
# ===========================================================================


class TestStoreFragment:
    """store_fragment delegates to storage.store_fragment and fires trigger."""

    def test_delegates_to_storage(self):
        symbolic = _import_symbolic()
        expected = {"success": True, "fragment_id": "f-001"}
        _handler_mocks.storage.store_fragment.return_value = expected

        frag = {"id": "f-001", "content": "test data"}
        result = symbolic.store_fragment(frag)

        _handler_mocks.storage.store_fragment.assert_called_once_with(frag, None)
        assert result == expected

    def test_passes_db_path(self):
        symbolic = _import_symbolic()
        db = Path("/tmp/test.chroma")
        _handler_mocks.storage.store_fragment.return_value = {
            "success": True,
            "fragment_id": "f-002",
        }

        symbolic.store_fragment({"id": "f-002"}, db_path=db)

        _handler_mocks.storage.store_fragment.assert_called_once_with({"id": "f-002"}, db)

    def test_fires_trigger_on_success(self):
        symbolic = _import_symbolic()
        _handler_mocks.storage.store_fragment.return_value = {
            "success": True,
            "fragment_id": "f-003",
        }
        _handler_mocks.trigger.reset_mock()

        symbolic.store_fragment({"id": "f-003"})

        _handler_mocks.trigger.fire.assert_called_once_with("fragment_stored", fragment_id="f-003")

    def test_no_trigger_on_failure(self):
        symbolic = _import_symbolic()
        _handler_mocks.storage.store_fragment.return_value = {
            "success": False,
            "error": "db error",
        }
        _handler_mocks.trigger.reset_mock()

        symbolic.store_fragment({"id": "f-bad"})

        _handler_mocks.trigger.fire.assert_not_called()


# ===========================================================================
# 3. store_fragments_batch
# ===========================================================================


class TestStoreFragmentsBatch:
    """store_fragments_batch delegates to storage.store_fragments_batch."""

    def test_delegates_to_storage(self):
        symbolic = _import_symbolic()
        expected = {"success": True, "stored": 3}
        _handler_mocks.storage.store_fragments_batch.return_value = expected

        frags = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
        result = symbolic.store_fragments_batch(frags)

        _handler_mocks.storage.store_fragments_batch.assert_called_once_with(frags, None)
        assert result == expected

    def test_passes_db_path(self):
        symbolic = _import_symbolic()
        db = Path("/tmp/batch.chroma")
        _handler_mocks.storage.store_fragments_batch.return_value = {
            "success": True,
            "stored": 1,
        }

        symbolic.store_fragments_batch([{"id": "x"}], db_path=db)

        _handler_mocks.storage.store_fragments_batch.assert_called_once_with([{"id": "x"}], db)


# ===========================================================================
# 4. flatten_dimensions
# ===========================================================================


class TestFlattenDimensions:
    """flatten_dimensions delegates to storage.flatten_dimensions."""

    def test_delegates_to_storage(self):
        symbolic = _import_symbolic()
        expected = {"success": True, "metadata": {"technical_0": "debug"}}
        _handler_mocks.storage.flatten_dimensions.return_value = expected

        frag = {"dimensions": {"technical": ["debug"]}}
        result = symbolic.flatten_dimensions(frag)

        _handler_mocks.storage.flatten_dimensions.assert_called_once_with(frag)
        assert result == expected


# ===========================================================================
# 5. store_llm_fragment
# ===========================================================================


class TestStoreLlmFragment:
    """store_llm_fragment delegates to storage.store_llm_fragment."""

    def test_delegates_to_storage(self):
        symbolic = _import_symbolic()
        expected = {
            "success": True,
            "fragment_id": "llm-001",
            "collection": "symbolic_fragments",
        }
        _handler_mocks.storage.store_llm_fragment.return_value = expected

        frag = {"summary": "test insight", "type": "episodic"}
        result = symbolic.store_llm_fragment(frag, source_branch="memory")

        _handler_mocks.storage.store_llm_fragment.assert_called_once_with(frag, "memory", None)
        assert result == expected

    def test_passes_all_args(self):
        symbolic = _import_symbolic()
        db = Path("/tmp/llm.chroma")
        _handler_mocks.storage.store_llm_fragment.return_value = {"success": True}

        symbolic.store_llm_fragment({"summary": "x"}, source_branch="drone", db_path=db)

        _handler_mocks.storage.store_llm_fragment.assert_called_once_with({"summary": "x"}, "drone", db)


# ===========================================================================
# 6. store_llm_fragments_batch
# ===========================================================================


class TestStoreLlmFragmentsBatch:
    """store_llm_fragments_batch delegates to storage.store_llm_fragments_batch."""

    def test_delegates_to_storage(self):
        symbolic = _import_symbolic()
        expected = {"success": True, "stored": 2}
        _handler_mocks.storage.store_llm_fragments_batch.return_value = expected

        frags = [{"summary": "a"}, {"summary": "b"}]
        result = symbolic.store_llm_fragments_batch(frags, source_branch="api")

        _handler_mocks.storage.store_llm_fragments_batch.assert_called_once_with(frags, "api", None)
        assert result == expected


# ===========================================================================
# 7. deduplicate_fragment
# ===========================================================================


class TestDeduplicateFragment:
    """deduplicate_fragment delegates to deduplicator.deduplicate_fragment."""

    def test_delegates_to_deduplicator(self):
        symbolic = _import_symbolic()
        expected = {"success": True, "action": "ADD", "fragment": {"summary": "new"}}
        _handler_mocks.deduplicator.deduplicate_fragment.return_value = expected

        new_frag = {"summary": "new insight"}
        existing = [{"summary": "old insight"}]
        result = symbolic.deduplicate_fragment(new_frag, existing)

        _handler_mocks.deduplicator.deduplicate_fragment.assert_called_once_with(new_frag, existing)
        assert result == expected

    def test_noop_action(self):
        symbolic = _import_symbolic()
        expected = {
            "success": True,
            "action": "NOOP",
            "reason": "duplicate",
        }
        _handler_mocks.deduplicator.deduplicate_fragment.return_value = expected

        result = symbolic.deduplicate_fragment({"summary": "dup"}, [{"summary": "dup"}])

        assert result["action"] == "NOOP"


# ===========================================================================
# 8. extract_and_store_llm
# ===========================================================================


class TestExtractAndStoreLlm:
    """extract_and_store_llm runs the end-to-end pipeline."""

    def test_success_with_add_action(self):
        symbolic = _import_symbolic()
        # Step 1: extraction returns fragments
        _handler_mocks.extractor.extract_fragments_llm.return_value = {
            "success": True,
            "fragments": [{"summary": "insight A"}],
        }
        # Step 2: vector search returns no similar
        _handler_mocks.retriever.search_by_vector.return_value = {
            "success": True,
            "results": [],
        }
        # Step 3: dedup says ADD
        _handler_mocks.deduplicator.deduplicate_fragment.return_value = {
            "success": True,
            "action": "ADD",
            "fragment": {"summary": "insight A"},
        }
        # Step 4: store succeeds
        _handler_mocks.storage.store_llm_fragment.return_value = {
            "success": True,
            "fragment_id": "llm-new",
        }

        result = symbolic.extract_and_store_llm(_sample_chat(), source_branch="test")

        assert result["success"] is True
        assert result["added"] == 1
        assert result["updated"] == 0
        assert result["skipped"] == 0

    def test_extraction_failure_returns_error(self):
        symbolic = _import_symbolic()
        _handler_mocks.extractor.extract_fragments_llm.return_value = {
            "success": False,
            "error": "API unavailable",
        }

        result = symbolic.extract_and_store_llm(_sample_chat())

        assert result["success"] is False
        assert result["processed"] == 0
        assert "API unavailable" in result["errors"]

    def test_no_fragments_extracted(self):
        symbolic = _import_symbolic()
        _handler_mocks.extractor.extract_fragments_llm.return_value = {
            "success": True,
            "fragments": [],
        }

        result = symbolic.extract_and_store_llm(_sample_chat())

        assert result["success"] is True
        assert result["processed"] == 0
        assert result["added"] == 0

    def test_noop_action_skips(self):
        symbolic = _import_symbolic()
        _handler_mocks.extractor.extract_fragments_llm.return_value = {
            "success": True,
            "fragments": [{"summary": "duplicate"}],
        }
        _handler_mocks.retriever.search_by_vector.return_value = {
            "success": True,
            "results": [{"summary": "duplicate"}],
        }
        _handler_mocks.deduplicator.deduplicate_fragment.return_value = {
            "success": True,
            "action": "NOOP",
            "reason": "already exists",
        }

        result = symbolic.extract_and_store_llm(_sample_chat())

        assert result["success"] is True
        assert result["skipped"] == 1
        assert result["added"] == 0

    def test_update_action(self):
        symbolic = _import_symbolic()
        _handler_mocks.extractor.extract_fragments_llm.return_value = {
            "success": True,
            "fragments": [{"summary": "updated insight"}],
        }
        _handler_mocks.retriever.search_by_vector.return_value = {
            "success": True,
            "results": [{"summary": "old insight"}],
        }
        _handler_mocks.deduplicator.deduplicate_fragment.return_value = {
            "success": True,
            "action": "UPDATE",
            "fragment": {"summary": "updated insight"},
        }
        _handler_mocks.storage.store_llm_fragment.return_value = {
            "success": True,
            "fragment_id": "llm-upd",
        }

        result = symbolic.extract_and_store_llm(_sample_chat())

        assert result["success"] is True
        assert result["updated"] == 1

    def test_delete_action(self):
        symbolic = _import_symbolic()
        _handler_mocks.extractor.extract_fragments_llm.return_value = {
            "success": True,
            "fragments": [{"summary": "obsolete"}],
        }
        _handler_mocks.retriever.search_by_vector.return_value = {
            "success": True,
            "results": [],
        }
        _handler_mocks.deduplicator.deduplicate_fragment.return_value = {
            "success": True,
            "action": "DELETE",
            "delete_id": "old-id-123",
            "reason": "superseded",
        }
        _handler_mocks.storage.delete_fragment.return_value = {"success": True}

        result = symbolic.extract_and_store_llm(_sample_chat())

        assert result["success"] is True
        assert result["skipped"] == 1
        _handler_mocks.storage.delete_fragment.assert_called_once_with("old-id-123", None)


# ===========================================================================
# 9. retrieve_fragments
# ===========================================================================


class TestRetrieveFragments:
    """retrieve_fragments delegates to retriever.retrieve_fragments."""

    def test_delegates_to_retriever(self):
        symbolic = _import_symbolic()
        expected = {"success": True, "results": [{"content": "frag1"}]}
        _handler_mocks.retriever.retrieve_fragments.return_value = expected

        result = symbolic.retrieve_fragments(query="debug error")

        _handler_mocks.retriever.retrieve_fragments.assert_called_once_with("debug error", None, None, 5, None)
        assert result == expected

    def test_passes_all_filters(self):
        symbolic = _import_symbolic()
        _handler_mocks.retriever.retrieve_fragments.return_value = {
            "success": True,
            "results": [],
        }
        db = Path("/tmp/ret.chroma")

        symbolic.retrieve_fragments(
            query="test",
            dimension_filters={"emotional_0": "frustrated"},
            trigger_keywords=["error"],
            n_results=10,
            db_path=db,
        )

        _handler_mocks.retriever.retrieve_fragments.assert_called_once_with(
            "test", {"emotional_0": "frustrated"}, ["error"], 10, db
        )


# ===========================================================================
# 10. search_fragments_by_vector
# ===========================================================================


class TestSearchFragmentsByVector:
    """search_fragments_by_vector delegates to retriever.search_by_vector."""

    def test_delegates_to_retriever(self):
        symbolic = _import_symbolic()
        expected = {"success": True, "results": []}
        _handler_mocks.retriever.search_by_vector.return_value = expected

        result = symbolic.search_fragments_by_vector("semantic query")

        _handler_mocks.retriever.search_by_vector.assert_called_once_with("semantic query", 5, None)
        assert result == expected


# ===========================================================================
# 11. search_fragments_by_dimensions
# ===========================================================================


class TestSearchFragmentsByDimensions:
    """search_fragments_by_dimensions delegates to retriever.search_by_dimensions."""

    def test_delegates_to_retriever(self):
        symbolic = _import_symbolic()
        expected = {"success": True, "results": [{"content": "matched"}]}
        _handler_mocks.retriever.search_by_dimensions.return_value = expected

        filters = {"technical_0": "debugging_session"}
        result = symbolic.search_fragments_by_dimensions(filters, n_results=3)

        _handler_mocks.retriever.search_by_dimensions.assert_called_once_with(filters, 3, None)
        assert result == expected


# ===========================================================================
# 12. search_fragments_by_triggers
# ===========================================================================


class TestSearchFragmentsByTriggers:
    """search_fragments_by_triggers delegates to retriever.search_by_triggers."""

    def test_delegates_to_retriever(self):
        symbolic = _import_symbolic()
        expected = {"success": True, "results": []}
        _handler_mocks.retriever.search_by_triggers.return_value = expected

        result = symbolic.search_fragments_by_triggers(["error", "debug"], n_results=10)

        _handler_mocks.retriever.search_by_triggers.assert_called_once_with(["error", "debug"], 10, None)
        assert result == expected


# ===========================================================================
# 13. extract_conversation_context
# ===========================================================================


class TestExtractConversationContext:
    """extract_conversation_context delegates to hook.extract_conversation_context."""

    def test_delegates_to_hook(self):
        symbolic = _import_symbolic()
        expected = {
            "success": True,
            "keywords": ["error", "debug"],
            "mood": "frustrated",
            "themes": ["troubleshooting"],
        }
        _handler_mocks.hook.extract_conversation_context.return_value = expected

        msgs = [{"role": "user", "content": "I have an error"}]
        result = symbolic.extract_conversation_context(msgs)

        _handler_mocks.hook.extract_conversation_context.assert_called_once_with(msgs, 5)
        assert result == expected

    def test_custom_max_messages(self):
        symbolic = _import_symbolic()
        _handler_mocks.hook.extract_conversation_context.return_value = {"success": True}

        symbolic.extract_conversation_context([], max_messages=10)

        _handler_mocks.hook.extract_conversation_context.assert_called_once_with([], 10)


# ===========================================================================
# 14. find_relevant_fragments
# ===========================================================================


class TestFindRelevantFragments:
    """find_relevant_fragments delegates to hook.find_relevant_fragments."""

    def test_delegates_to_hook(self):
        symbolic = _import_symbolic()
        expected = {"success": True, "fragments": [{"content": "match"}]}
        _handler_mocks.hook.find_relevant_fragments.return_value = expected

        context = {"keywords": ["debug"], "mood": "neutral"}
        result = symbolic.find_relevant_fragments(context, n_results=5)

        _handler_mocks.hook.find_relevant_fragments.assert_called_once_with(context, 5, None)
        assert result == expected


# ===========================================================================
# 15. format_fragment_recall
# ===========================================================================


class TestFormatFragmentRecall:
    """format_fragment_recall delegates to hook.format_fragment_recall."""

    def test_delegates_to_hook(self):
        symbolic = _import_symbolic()
        expected = "This reminds me of a debugging session..."
        _handler_mocks.hook.format_fragment_recall.return_value = expected

        frag = {"content": "debug session", "metadata": {"type": "episodic"}}
        result = symbolic.format_fragment_recall(frag)

        _handler_mocks.hook.format_fragment_recall.assert_called_once_with(frag)
        assert result == expected


# ===========================================================================
# 16. should_surface_fragment
# ===========================================================================


class TestShouldSurfaceFragment:
    """should_surface_fragment delegates to hook.should_surface_fragment."""

    def test_delegates_to_hook(self):
        symbolic = _import_symbolic()
        expected = (True, "relevance threshold met")
        _handler_mocks.hook.should_surface_fragment.return_value = expected

        frag = {"content": "test", "metadata": {}}
        result = symbolic.should_surface_fragment(frag)

        _handler_mocks.hook.should_surface_fragment.assert_called_once_with(frag, None)
        assert result == expected

    def test_with_config(self):
        symbolic = _import_symbolic()
        _handler_mocks.hook.should_surface_fragment.return_value = (
            False,
            "cooldown active",
        )
        config = {"min_relevance": 0.8}

        result = symbolic.should_surface_fragment(config=config)

        _handler_mocks.hook.should_surface_fragment.assert_called_once_with(None, config)
        assert result[0] is False


# ===========================================================================
# 17. process_hook
# ===========================================================================


class TestProcessHook:
    """process_hook delegates to hook.process_hook."""

    def test_delegates_to_hook(self):
        symbolic = _import_symbolic()
        expected = {"success": True, "surfaced": True, "recall": "I remember..."}
        _handler_mocks.hook.process_hook.return_value = expected

        msgs = [{"role": "user", "content": "debugging"}]
        result = symbolic.process_hook(msgs)

        _handler_mocks.hook.process_hook.assert_called_once_with(msgs, None, None)
        assert result == expected

    def test_passes_config_and_db_path(self):
        symbolic = _import_symbolic()
        _handler_mocks.hook.process_hook.return_value = {"success": True}
        config = {"enabled": True}
        db = Path("/tmp/hook.chroma")

        symbolic.process_hook([], config=config, db_path=db)

        _handler_mocks.hook.process_hook.assert_called_once_with([], config, db)


# ===========================================================================
# 18. load_hook_config
# ===========================================================================


class TestLoadHookConfig:
    """load_hook_config delegates to hook.load_config."""

    def test_delegates_to_hook(self):
        symbolic = _import_symbolic()
        expected = {"enabled": True, "min_relevance": 0.5}
        _handler_mocks.hook.load_config.return_value = expected

        result = symbolic.load_hook_config()

        _handler_mocks.hook.load_config.assert_called_once_with(None)
        assert result == expected

    def test_passes_config_path(self):
        symbolic = _import_symbolic()
        _handler_mocks.hook.load_config.return_value = {}
        p = Path("/tmp/hook_config.json")

        symbolic.load_hook_config(config_path=p)

        _handler_mocks.hook.load_config.assert_called_once_with(p)


# ===========================================================================
# 19. reset_hook_session
# ===========================================================================


class TestResetHookSession:
    """reset_hook_session delegates to hook.reset_session."""

    def test_delegates_to_hook(self):
        symbolic = _import_symbolic()
        _handler_mocks.hook.reset_session.return_value = None

        result = symbolic.reset_hook_session()

        _handler_mocks.hook.reset_session.assert_called_once()
        assert result is None


# ===========================================================================
# 20. get_hook_session_state
# ===========================================================================


class TestGetHookSessionState:
    """get_hook_session_state delegates to hook.get_session_state."""

    def test_delegates_to_hook(self):
        symbolic = _import_symbolic()
        expected = {"fragments_surfaced": 3, "messages_since_last": 12}
        _handler_mocks.hook.get_session_state.return_value = expected

        result = symbolic.get_hook_session_state()

        _handler_mocks.hook.get_session_state.assert_called_once()
        assert result == expected


# ===========================================================================
# 21. run_demo
# ===========================================================================


class TestRunDemo:
    """run_demo runs demo analysis with Rich output."""

    def test_does_not_raise(self):
        symbolic = _import_symbolic()
        # Mock the functions run_demo calls internally
        _handler_mocks.extractor.analyze_conversation.return_value = {
            "success": True,
            "dimensions": {
                "technical": ["debug"],
                "emotional": ["frustrated"],
                "collaboration": ["balanced"],
                "learnings": ["fix"],
                "triggers": ["error"],
            },
            "metadata": {"total_words": 50, "depth": "shallow"},
            "message_count": 5,
        }
        _handler_mocks.hook.format_fragment_recall.return_value = "This reminds me of..."

        # Should not raise
        symbolic.run_demo()

        # Verify console was used
        assert _handler_mocks.console.print.called

    def test_handles_analysis_failure(self):
        symbolic = _import_symbolic()
        _handler_mocks.extractor.analyze_conversation.return_value = {
            "success": False,
            "error": "test error",
        }
        _handler_mocks.hook.format_fragment_recall.return_value = "recall"

        # Should not raise even on failure
        symbolic.run_demo()


# ===========================================================================
# 22. search_fragments_cli
# ===========================================================================


class TestSearchFragmentsCli:
    """search_fragments_cli executes CLI fragment search."""

    def test_basic_query_search(self):
        symbolic = _import_symbolic()
        _handler_mocks.retriever.retrieve_fragments.return_value = {
            "success": True,
            "results": [
                {
                    "content": "debug session",
                    "metadata": {"timestamp": "2026-01-01"},
                    "relevance_score": 0.85,
                    "_sources": ["vector"],
                }
            ],
            "search_methods": ["vector"],
        }

        symbolic.search_fragments_cli(["debug", "error"])

        _handler_mocks.retriever.retrieve_fragments.assert_called_once()
        assert _handler_mocks.console.print.called

    def test_no_args_shows_error(self):
        symbolic = _import_symbolic()

        symbolic.search_fragments_cli([])

        # Should print error about missing query
        assert _handler_mocks.error_fn.called

    def test_dimension_filter_parsing(self):
        symbolic = _import_symbolic()
        _handler_mocks.retriever.retrieve_fragments.return_value = {
            "success": True,
            "results": [],
            "search_methods": ["dimension"],
        }

        symbolic.search_fragments_cli(["query", "--dimension", "emotional_0=frustrated"])

        call_args = _handler_mocks.retriever.retrieve_fragments.call_args
        assert call_args is not None
        # dimension_filters is the second positional arg
        assert call_args[0][1] == {"emotional_0": "frustrated"}

    def test_trigger_keyword_parsing(self):
        symbolic = _import_symbolic()
        _handler_mocks.retriever.retrieve_fragments.return_value = {
            "success": True,
            "results": [],
            "search_methods": ["trigger"],
        }

        symbolic.search_fragments_cli(["--trigger", "error", "--trigger", "debug"])

        call_args = _handler_mocks.retriever.retrieve_fragments.call_args
        assert call_args is not None
        # trigger_keywords is the third positional arg
        assert call_args[0][2] == ["error", "debug"]

    def test_search_failure(self):
        symbolic = _import_symbolic()
        _handler_mocks.retriever.retrieve_fragments.return_value = {
            "success": False,
            "error": "ChromaDB unavailable",
        }

        symbolic.search_fragments_cli(["test query"])

        assert _handler_mocks.console.print.called


# ===========================================================================
# 23. run_hook_test
# ===========================================================================


class TestRunHookTest:
    """run_hook_test tests hook with sample text."""

    def test_does_not_raise(self):
        symbolic = _import_symbolic()
        _handler_mocks.hook.reset_session.return_value = None
        _handler_mocks.hook.extract_conversation_context.return_value = {
            "success": True,
            "keywords": ["error"],
            "mood": "frustrated",
            "themes": ["debugging"],
        }
        _handler_mocks.hook.find_relevant_fragments.return_value = {
            "success": True,
            "fragments": [],
            "query_used": "error debugging",
            "threshold_applied": 0.3,
        }
        _handler_mocks.hook.should_surface_fragment.return_value = (
            False,
            "no fragments",
        )
        _handler_mocks.hook.process_hook.return_value = {
            "success": True,
            "surfaced": False,
            "reason": "no matching fragments",
        }
        _handler_mocks.hook.get_session_state.return_value = {
            "fragments_surfaced": 0,
            "messages_since_last": 0,
        }

        symbolic.run_hook_test(["test", "text"])

        assert _handler_mocks.console.print.called

    def test_bypass_flag(self):
        symbolic = _import_symbolic()
        _handler_mocks.hook.reset_session.return_value = None
        _handler_mocks.hook.extract_conversation_context.return_value = {
            "success": True,
            "keywords": [],
            "mood": "neutral",
            "themes": [],
        }
        _handler_mocks.hook.find_relevant_fragments.return_value = {
            "success": True,
            "fragments": [],
            "query_used": "",
            "threshold_applied": 0.3,
        }
        _handler_mocks.hook.should_surface_fragment.return_value = (
            False,
            "no fragments",
        )
        _handler_mocks.hook.process_hook.return_value = {
            "success": True,
            "surfaced": False,
            "reason": "nothing to surface",
        }
        _handler_mocks.hook.get_session_state.return_value = {
            "fragments_surfaced": 0,
            "messages_since_last": 0,
        }

        # Should not raise with --bypass flag
        symbolic.run_hook_test(["--bypass", "test"])

        assert _handler_mocks.hook.reset_session.called

    def test_context_extraction_failure(self):
        symbolic = _import_symbolic()
        _handler_mocks.hook.reset_session.return_value = None
        _handler_mocks.hook.extract_conversation_context.return_value = {
            "success": False,
            "error": "extraction failed",
        }

        # Should not raise even when extraction fails (returns early)
        symbolic.run_hook_test(["broken input"])

        assert _handler_mocks.console.print.called


# ===========================================================================
# 24. analyze_file
# ===========================================================================


class TestAnalyzeFile:
    """analyze_file analyzes a conversation JSON file."""

    def test_file_not_found(self, tmp_path):
        symbolic = _import_symbolic()
        nonexistent = str(tmp_path / "does_not_exist.json")

        symbolic.analyze_file(nonexistent)

        # Should print error about missing file
        assert _handler_mocks.error_fn.called

    def test_successful_analysis(self, tmp_path):
        symbolic = _import_symbolic()

        # Create a real file so Path(file_path).exists() is True
        chat_file = tmp_path / "chat.json"
        chat_file.write_text("[]", encoding="utf-8")

        _handler_mocks.memory_files.read_memory_file.return_value = {
            "success": True,
            "data": [
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "hi"},
            ],
        }
        _handler_mocks.extractor.analyze_conversation.return_value = {
            "success": True,
            "dimensions": {
                "technical": [],
                "emotional": [],
                "collaboration": [],
                "learnings": [],
                "triggers": [],
            },
            "metadata": {"total_words": 2, "depth": "shallow"},
            "message_count": 2,
        }

        symbolic.analyze_file(str(chat_file))

        assert _handler_mocks.console.print.called

    def test_invalid_json_data(self, tmp_path):
        symbolic = _import_symbolic()

        chat_file = tmp_path / "bad.json"
        chat_file.write_text("{}", encoding="utf-8")

        _handler_mocks.memory_files.read_memory_file.return_value = {
            "success": True,
            "data": {"not": "a list"},
        }

        symbolic.analyze_file(str(chat_file))

        # Should print error about expected array
        assert _handler_mocks.error_fn.called

    def test_read_failure(self, tmp_path):
        symbolic = _import_symbolic()

        chat_file = tmp_path / "unreadable.json"
        chat_file.write_text("[]", encoding="utf-8")

        _handler_mocks.memory_files.read_memory_file.return_value = {
            "success": False,
            "error": "permission denied",
        }

        symbolic.analyze_file(str(chat_file))

        assert _handler_mocks.error_fn.called


# ===========================================================================
# 25. bootstrap_from_jsonl
# ===========================================================================


class TestBootstrapFromJsonl:
    """bootstrap_from_jsonl bootstraps from session JONLs."""

    def test_no_sessions_found(self, monkeypatch):
        symbolic = _import_symbolic()

        # Mock _find_bootstrap_sessions to return empty
        monkeypatch.setattr(symbolic, "_find_bootstrap_sessions", lambda max_sessions: [])

        symbolic.bootstrap_from_jsonl(max_sessions=5)

        # Should print error about no files found
        assert _handler_mocks.error_fn.called or _handler_mocks.console.print.called

    def test_processes_sessions(self, monkeypatch, tmp_path):
        symbolic = _import_symbolic()

        # Create a fake JSONL file
        jsonl_file = tmp_path / "session.jsonl"
        jsonl_file.write_text("", encoding="utf-8")

        # Mock _find_bootstrap_sessions
        monkeypatch.setattr(symbolic, "_find_bootstrap_sessions", lambda max_sessions: [jsonl_file])

        # Mock _parse_jsonl_to_chat_history to return enough messages
        monkeypatch.setattr(
            symbolic,
            "_parse_jsonl_to_chat_history",
            lambda path: [
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "hi"},
                {"role": "user", "content": "test"},
                {"role": "assistant", "content": "response"},
            ],
        )

        # Mock extract_and_store_llm (called internally)
        _handler_mocks.extractor.extract_fragments_llm.return_value = {
            "success": True,
            "fragments": [{"summary": "test"}],
        }
        _handler_mocks.retriever.search_by_vector.return_value = {
            "success": True,
            "results": [],
        }
        _handler_mocks.deduplicator.deduplicate_fragment.return_value = {
            "success": True,
            "action": "ADD",
            "fragment": {"summary": "test"},
        }
        _handler_mocks.storage.store_llm_fragment.return_value = {
            "success": True,
            "fragment_id": "boot-001",
        }

        symbolic.bootstrap_from_jsonl(max_sessions=1)

        assert _handler_mocks.console.print.called

    def test_skips_sessions_with_few_messages(self, monkeypatch, tmp_path):
        symbolic = _import_symbolic()

        jsonl_file = tmp_path / "tiny.jsonl"
        jsonl_file.write_text("", encoding="utf-8")

        monkeypatch.setattr(symbolic, "_find_bootstrap_sessions", lambda max_sessions: [jsonl_file])
        # Only 2 messages -- below the 4-message threshold
        monkeypatch.setattr(
            symbolic,
            "_parse_jsonl_to_chat_history",
            lambda path: [
                {"role": "user", "content": "hi"},
                {"role": "assistant", "content": "hello"},
            ],
        )

        symbolic.bootstrap_from_jsonl(max_sessions=1)

        # extract_and_store_llm should NOT have been called
        _handler_mocks.extractor.extract_fragments_llm.assert_not_called()
