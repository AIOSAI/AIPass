# ===================AIPASS====================
# META DATA HEADER
# Name: tests/test_symbolic_cli.py
# Date: 2026-04-26
# Version: 1.0.0
# Category: memory/tests
# =============================================

"""Tests for symbolic module CLI/display functions -- line coverage.

Covers: from aipass.memory.apps.modules.symbolic import handle_command
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
from pathlib import Path
from unittest.mock import MagicMock

import pytest

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
    mock_success = MagicMock()
    mock_warning = MagicMock()
    cli_modules = MagicMock()
    cli_modules.console = mock_console
    cli_modules.header = mock_header
    cli_modules.error = mock_error
    cli_modules.success = mock_success
    cli_modules.warning = mock_warning
    monkeypatch.setitem(sys.modules, "aipass.cli", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.cli.apps", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.cli.apps.modules", cli_modules)

    # -- memory json handler ------------------------------------------------
    mock_json_handler = MagicMock()
    mock_json_handler.log_operation = MagicMock(return_value=True)
    json_pkg = MagicMock()
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
    _handler_mocks.success_fn = mock_success
    _handler_mocks.warning_fn = mock_warning
    _handler_mocks.json_handler = mock_json_handler
    _handler_mocks.memory_files = mock_memory_files


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _import_symbolic():
    """Import symbolic module after mocks are in place."""
    sys.modules.pop("aipass.memory.apps.modules.symbolic", None)
    parent = sys.modules.get("aipass.memory.apps.modules")
    if parent is not None and hasattr(parent, "symbolic"):
        delattr(parent, "symbolic")

    from aipass.memory.apps.modules import symbolic

    return symbolic


def _default_analysis_result() -> dict:
    """Standard successful analysis result."""
    return {
        "success": True,
        "dimensions": {
            "technical": [],
            "emotional": [],
            "collaboration": [],
            "learnings": [],
            "triggers": [],
        },
        "metadata": {"total_words": 50, "depth": "shallow", "timestamp": "2026-01-01", "total_chars": 200},
        "message_count": 3,
    }


def _default_extract_store_result() -> dict:
    """Standard successful extract_and_store_llm result."""
    return {
        "success": True,
        "processed": 2,
        "added": 2,
        "updated": 0,
        "skipped": 0,
        "errors": [],
    }


# ===========================================================================
# handle_command routing (lines 637-751)
# ===========================================================================


class TestHandleCommand:
    """Tests for handle_command routing."""

    def test_help_flag(self):
        symbolic = _import_symbolic()
        result = symbolic.handle_command("--help", [])
        assert result is True
        _handler_mocks.console.print.assert_called()

    def test_symbolic_no_args(self):
        symbolic = _import_symbolic()
        result = symbolic.handle_command("symbolic", [])
        assert result is True
        # print_introspection calls console.print multiple times
        assert _handler_mocks.console.print.call_count > 0

    def test_symbolic_help(self):
        symbolic = _import_symbolic()
        result = symbolic.handle_command("symbolic", ["--help"])
        assert result is True
        _handler_mocks.header.assert_called()

    def test_symbolic_demo(self):
        symbolic = _import_symbolic()
        _handler_mocks.extractor.analyze_conversation.return_value = _default_analysis_result()
        _handler_mocks.hook.format_fragment_recall.return_value = "This reminds me of..."
        result = symbolic.handle_command("symbolic", ["demo"])
        assert result is True
        _handler_mocks.extractor.analyze_conversation.assert_called_once()

    def test_symbolic_analyze_no_file(self):
        symbolic = _import_symbolic()
        result = symbolic.handle_command("symbolic", ["analyze"])
        assert result is True
        # Should print error about missing file path
        calls = [str(c) for c in _handler_mocks.error_fn.call_args_list]
        assert any("File path required" in c for c in calls)

    def test_symbolic_analyze_with_file(self, tmp_path):
        symbolic = _import_symbolic()
        chat_file = tmp_path / "chat.json"
        chat_data = [{"role": "user", "content": "hello"}]
        chat_file.write_text(json.dumps(chat_data), encoding="utf-8")

        _handler_mocks.memory_files.read_memory_file.return_value = {"success": True, "data": chat_data}
        _handler_mocks.extractor.analyze_conversation.return_value = _default_analysis_result()

        result = symbolic.handle_command("symbolic", ["analyze", str(chat_file)])
        assert result is True

    def test_symbolic_extract_no_file(self):
        symbolic = _import_symbolic()
        result = symbolic.handle_command("symbolic", ["extract"])
        assert result is True
        calls = [str(c) for c in _handler_mocks.error_fn.call_args_list]
        assert any("File path required" in c for c in calls)

    def test_symbolic_extract_with_branch(self, tmp_path):
        symbolic = _import_symbolic()
        chat_file = tmp_path / "chat.json"
        chat_data = [{"role": "user", "content": "hello"}]
        chat_file.write_text(json.dumps(chat_data), encoding="utf-8")

        _handler_mocks.memory_files.read_memory_file.return_value = {"success": True, "data": chat_data}
        # Mock the full pipeline that extract_file calls internally
        _handler_mocks.extractor.extract_fragments_llm.return_value = {
            "success": True,
            "fragments": [],
            "chunk_count": 0,
        }

        result = symbolic.handle_command("symbolic", ["extract", str(chat_file), "memory"])
        assert result is True

    def test_symbolic_bootstrap(self, monkeypatch):
        symbolic = _import_symbolic()
        monkeypatch.setattr(symbolic, "_find_bootstrap_sessions", lambda max_sessions: [])
        result = symbolic.handle_command("symbolic", ["bootstrap"])
        assert result is True

    def test_symbolic_bootstrap_max(self, monkeypatch):
        symbolic = _import_symbolic()
        monkeypatch.setattr(symbolic, "_find_bootstrap_sessions", lambda max_sessions: [])
        result = symbolic.handle_command("symbolic", ["bootstrap", "--max=3"])
        assert result is True

    def test_symbolic_fragments(self):
        symbolic = _import_symbolic()
        _handler_mocks.retriever.retrieve_fragments.return_value = {
            "success": True,
            "results": [],
            "search_methods": ["vector"],
        }
        result = symbolic.handle_command("symbolic", ["fragments", "query"])
        assert result is True

    def test_symbolic_hook_test(self):
        symbolic = _import_symbolic()
        _handler_mocks.hook.extract_conversation_context.return_value = {
            "success": True,
            "keywords": ["test"],
            "mood": "neutral",
            "themes": ["coding"],
        }
        _handler_mocks.hook.find_relevant_fragments.return_value = {
            "success": True,
            "fragments": [],
            "query_used": "test",
            "threshold_applied": 0.3,
        }
        _handler_mocks.hook.should_surface_fragment.return_value = (False, "no fragments")
        _handler_mocks.hook.process_hook.return_value = {
            "success": True,
            "surfaced": False,
            "reason": "no fragments",
        }
        _handler_mocks.hook.get_session_state.return_value = {
            "fragments_surfaced": 0,
            "messages_since_last": 0,
        }
        result = symbolic.handle_command("symbolic", ["hook-test", "test text"])
        assert result is True

    def test_symbolic_unknown_subcommand_returns_false(self):
        symbolic = _import_symbolic()
        result = symbolic.handle_command("symbolic", ["nonexistent_sub"])
        assert result is False

    # Backward-compat routing

    def test_backward_compat_demo(self):
        symbolic = _import_symbolic()
        _handler_mocks.extractor.analyze_conversation.return_value = _default_analysis_result()
        _handler_mocks.hook.format_fragment_recall.return_value = "This reminds me of..."
        result = symbolic.handle_command("demo", [])
        assert result is True

    def test_backward_compat_analyze(self, tmp_path):
        symbolic = _import_symbolic()
        chat_file = tmp_path / "chat.json"
        chat_data = [{"role": "user", "content": "hello"}]
        chat_file.write_text(json.dumps(chat_data), encoding="utf-8")

        _handler_mocks.memory_files.read_memory_file.return_value = {"success": True, "data": chat_data}
        _handler_mocks.extractor.analyze_conversation.return_value = _default_analysis_result()

        result = symbolic.handle_command("analyze", [str(chat_file)])
        assert result is True

    def test_backward_compat_analyze_no_file(self):
        symbolic = _import_symbolic()
        result = symbolic.handle_command("analyze", [])
        assert result is True
        calls = [str(c) for c in _handler_mocks.error_fn.call_args_list]
        assert any("File path required" in c for c in calls)

    def test_backward_compat_extract(self, tmp_path):
        symbolic = _import_symbolic()
        chat_file = tmp_path / "chat.json"
        chat_data = [{"role": "user", "content": "hello"}]
        chat_file.write_text(json.dumps(chat_data), encoding="utf-8")

        _handler_mocks.memory_files.read_memory_file.return_value = {"success": True, "data": chat_data}
        _handler_mocks.extractor.extract_fragments_llm.return_value = {
            "success": True,
            "fragments": [],
            "chunk_count": 0,
        }
        result = symbolic.handle_command("extract", [str(chat_file)])
        assert result is True

    def test_backward_compat_extract_no_file(self):
        symbolic = _import_symbolic()
        result = symbolic.handle_command("extract", [])
        assert result is True
        calls = [str(c) for c in _handler_mocks.error_fn.call_args_list]
        assert any("File path required" in c for c in calls)

    def test_backward_compat_bootstrap(self, monkeypatch):
        symbolic = _import_symbolic()
        monkeypatch.setattr(symbolic, "_find_bootstrap_sessions", lambda max_sessions: [])
        result = symbolic.handle_command("bootstrap", [])
        assert result is True

    def test_backward_compat_fragments(self):
        symbolic = _import_symbolic()
        _handler_mocks.retriever.retrieve_fragments.return_value = {
            "success": True,
            "results": [],
            "search_methods": ["vector"],
        }
        result = symbolic.handle_command("fragments", ["query"])
        assert result is True

    def test_backward_compat_hook_test(self):
        symbolic = _import_symbolic()
        _handler_mocks.hook.extract_conversation_context.return_value = {
            "success": True,
            "keywords": ["test"],
            "mood": "neutral",
            "themes": ["coding"],
        }
        _handler_mocks.hook.find_relevant_fragments.return_value = {
            "success": True,
            "fragments": [],
            "query_used": "test",
            "threshold_applied": 0.3,
        }
        _handler_mocks.hook.should_surface_fragment.return_value = (False, "no fragments")
        _handler_mocks.hook.process_hook.return_value = {
            "success": True,
            "surfaced": False,
            "reason": "no fragments",
        }
        _handler_mocks.hook.get_session_state.return_value = {
            "fragments_surfaced": 0,
            "messages_since_last": 0,
        }
        result = symbolic.handle_command("hook-test", ["text"])
        assert result is True

    def test_unknown_returns_false(self):
        symbolic = _import_symbolic()
        result = symbolic.handle_command("unknown", [])
        assert result is False


# ===========================================================================
# print_help, print_introspection
# ===========================================================================


class TestPrintHelp:
    """Tests for print_help (lines 754-815)."""

    def test_print_help(self):
        symbolic = _import_symbolic()
        symbolic.print_help()
        _handler_mocks.header.assert_called()
        assert _handler_mocks.console.print.call_count > 10


class TestPrintIntrospection:
    """Tests for print_introspection (lines 604-629)."""

    def test_introspection_with_symbolic_handlers(self, monkeypatch):
        symbolic = _import_symbolic()
        monkeypatch.setattr(
            symbolic,
            "_discover_handlers",
            lambda: {"symbolic": ["extractor.py", "storage.py"]},
        )
        symbolic.print_introspection()
        calls = [str(c) for c in _handler_mocks.console.print.call_args_list]
        assert any("Connected Handlers" in c for c in calls)

    def test_introspection_without_symbolic(self, monkeypatch):
        symbolic = _import_symbolic()
        monkeypatch.setattr(symbolic, "_discover_handlers", lambda: {})
        symbolic.print_introspection()
        calls = [str(c) for c in _handler_mocks.console.print.call_args_list]
        assert any("Subcommands" in c for c in calls)
        # Should NOT contain "Connected Handlers"
        assert not any("Connected Handlers" in c for c in calls)


# ===========================================================================
# run_demo (lines 818-916)
# ===========================================================================


class TestRunDemo:
    """Tests for run_demo."""

    def test_run_demo_success(self):
        symbolic = _import_symbolic()
        _handler_mocks.extractor.analyze_conversation.return_value = _default_analysis_result()
        _handler_mocks.hook.format_fragment_recall.return_value = "This reminds me of..."

        symbolic.run_demo()

        _handler_mocks.extractor.analyze_conversation.assert_called_once()
        _handler_mocks.hook.format_fragment_recall.assert_called()
        calls = [str(c) for c in _handler_mocks.success_fn.call_args_list]
        assert any("Analysis complete" in c for c in calls)

    def test_run_demo_analysis_failure(self):
        symbolic = _import_symbolic()
        _handler_mocks.extractor.analyze_conversation.return_value = {
            "success": False,
            "error": "test failure",
        }
        _handler_mocks.hook.format_fragment_recall.return_value = "This reminds me of..."

        symbolic.run_demo()

        calls = [str(c) for c in _handler_mocks.error_fn.call_args_list]
        assert any("Analysis failed" in c for c in calls)


# ===========================================================================
# search_fragments_cli (lines 919-1077)
# ===========================================================================


class TestSearchFragmentsCli:
    """Tests for search_fragments_cli."""

    def test_search_no_args(self):
        symbolic = _import_symbolic()
        symbolic.search_fragments_cli([])
        calls = [str(c) for c in _handler_mocks.error_fn.call_args_list]
        assert any("query, dimension filter, or trigger required" in c for c in calls)

    def test_search_query_only(self):
        symbolic = _import_symbolic()
        _handler_mocks.retriever.retrieve_fragments.return_value = {
            "success": True,
            "results": [],
            "search_methods": ["vector"],
        }
        symbolic.search_fragments_cli(["test", "query"])
        _handler_mocks.retriever.retrieve_fragments.assert_called_once()
        call_args = _handler_mocks.retriever.retrieve_fragments.call_args
        # Called positionally: retriever.retrieve_fragments(query, dim, trig, n, db)
        assert call_args[0][0] == "test query"

    def test_search_with_dimension_filter(self):
        symbolic = _import_symbolic()
        _handler_mocks.retriever.retrieve_fragments.return_value = {
            "success": True,
            "results": [],
            "search_methods": ["vector"],
        }
        symbolic.search_fragments_cli(["query", "--dimension", "emotional_0=frustrated"])
        call_kwargs = _handler_mocks.retriever.retrieve_fragments.call_args
        assert call_kwargs[1].get("dimension_filters") == {"emotional_0": "frustrated"} or (
            len(call_kwargs[0]) > 1 and call_kwargs[0][1] == {"emotional_0": "frustrated"}
        )

    def test_search_with_trigger(self):
        symbolic = _import_symbolic()
        _handler_mocks.retriever.retrieve_fragments.return_value = {
            "success": True,
            "results": [],
            "search_methods": ["vector"],
        }
        symbolic.search_fragments_cli(["query", "--trigger", "error"])
        _handler_mocks.retriever.retrieve_fragments.assert_called_once()

    def test_search_with_n_results(self):
        symbolic = _import_symbolic()
        _handler_mocks.retriever.retrieve_fragments.return_value = {
            "success": True,
            "results": [],
            "search_methods": ["vector"],
        }
        symbolic.search_fragments_cli(["query", "--n", "10"])
        call_kwargs = _handler_mocks.retriever.retrieve_fragments.call_args
        assert call_kwargs[1].get("n_results") == 10 or (len(call_kwargs[0]) > 3 and call_kwargs[0][3] == 10)

    def test_search_invalid_n(self):
        symbolic = _import_symbolic()
        symbolic.search_fragments_cli(["query", "--n", "abc"])
        calls = [str(c) for c in _handler_mocks.error_fn.call_args_list]
        assert any("Invalid number" in c for c in calls)

    def test_search_invalid_dimension(self):
        symbolic = _import_symbolic()
        symbolic.search_fragments_cli(["query", "--dimension", "bad_format_no_equals"])
        calls = [str(c) for c in _handler_mocks.error_fn.call_args_list]
        assert any("Invalid dimension format" in c for c in calls)

    def test_search_no_results(self):
        symbolic = _import_symbolic()
        _handler_mocks.retriever.retrieve_fragments.return_value = {
            "success": True,
            "results": [],
            "search_methods": ["vector"],
        }
        symbolic.search_fragments_cli(["test"])
        _handler_mocks.warning_fn.assert_called()

    def test_search_failure(self):
        symbolic = _import_symbolic()
        _handler_mocks.retriever.retrieve_fragments.return_value = {
            "success": False,
            "error": "DB unavailable",
        }
        symbolic.search_fragments_cli(["test"])
        calls = [str(c) for c in _handler_mocks.error_fn.call_args_list]
        assert any("DB unavailable" in c for c in calls)

    def test_search_v1_results(self):
        symbolic = _import_symbolic()
        _handler_mocks.retriever.retrieve_fragments.return_value = {
            "success": True,
            "results": [
                {
                    "content": "debugging pattern found",
                    "metadata": {
                        "timestamp": "2026-01-01",
                        "source_branch": "memory",
                        "depth": "deep",
                        "technical_0": "debug",
                        "emotional_0": "frustration",
                    },
                    "relevance_score": 0.85,
                    "_sources": ["vector"],
                    "relevance_tier": "high",
                },
            ],
            "search_methods": ["vector"],
        }
        symbolic.search_fragments_cli(["debug"])
        # Should display a Panel for this result
        assert _handler_mocks.console.print.call_count > 5

    def test_search_v2_results(self):
        symbolic = _import_symbolic()
        _handler_mocks.retriever.retrieve_fragments.return_value = {
            "success": True,
            "results": [
                {
                    "content": "step-by-step debugging",
                    "metadata": {
                        "schema_version": "v2",
                        "summary": "Debugging session breakthrough",
                        "insight": "Step-by-step approach works best",
                        "type": "episodic",
                        "emotional_tone": "excited",
                        "technical_domain": "debugging",
                        "timestamp": "2026-01-01",
                        "source_branch": "memory",
                    },
                    "relevance_score": 0.92,
                    "_sources": ["vector"],
                    "relevance_tier": "high",
                },
            ],
            "search_methods": ["vector"],
        }
        symbolic.search_fragments_cli(["debug"])
        assert _handler_mocks.console.print.call_count > 5


# ===========================================================================
# run_hook_test (lines 1080-1204)
# ===========================================================================


class TestRunHookTest:
    """Tests for run_hook_test."""

    def _setup_hook_mocks(
        self,
        context_success: bool = True,
        fragments: list | None = None,
        surfaced: bool = False,
        hook_success: bool = True,
    ):
        """Configure hook mocks for common test scenarios."""
        _handler_mocks.hook.extract_conversation_context.return_value = {
            "success": context_success,
            "keywords": ["test"],
            "mood": "neutral",
            "themes": ["coding"],
            **({"error": "context extraction failed"} if not context_success else {}),
        }
        _handler_mocks.hook.find_relevant_fragments.return_value = {
            "success": True,
            "fragments": fragments or [],
            "query_used": "test",
            "threshold_applied": 0.3,
        }
        _handler_mocks.hook.should_surface_fragment.return_value = (surfaced, "test reason")
        _handler_mocks.hook.process_hook.return_value = {
            "success": hook_success,
            "surfaced": surfaced,
            "reason": "test reason",
            **(
                {"recall": "I remember debugging...", "fragment_id": "frag-1", "relevance_score": 0.8}
                if surfaced
                else {}
            ),
            **({"error": "hook process failed"} if not hook_success else {}),
        }
        _handler_mocks.hook.format_fragment_recall.return_value = "This reminds me of..."
        _handler_mocks.hook.get_session_state.return_value = {
            "fragments_surfaced": 1 if surfaced else 0,
            "messages_since_last": 0,
        }
        _handler_mocks.hook.reset_session.return_value = None

    def test_hook_test_default_text(self):
        symbolic = _import_symbolic()
        self._setup_hook_mocks()
        symbolic.run_hook_test([])
        # Should use default text
        calls = [str(c) for c in _handler_mocks.console.print.call_args_list]
        assert any("stuck on this error" in c for c in calls)

    def test_hook_test_custom_text(self):
        symbolic = _import_symbolic()
        self._setup_hook_mocks()
        symbolic.run_hook_test(["my", "test", "text"])
        calls = [str(c) for c in _handler_mocks.console.print.call_args_list]
        assert any("my test text" in c for c in calls)

    def test_hook_test_bypass(self):
        symbolic = _import_symbolic()
        self._setup_hook_mocks()
        symbolic.run_hook_test(["text", "--bypass"])
        calls = [str(c) for c in _handler_mocks.console.print.call_args_list]
        assert any("True" in c and "Bypass" in c for c in calls)

    def test_hook_test_context_extraction_fails(self):
        symbolic = _import_symbolic()
        self._setup_hook_mocks(context_success=False)
        symbolic.run_hook_test(["text"])
        calls = [str(c) for c in _handler_mocks.error_fn.call_args_list]
        assert any("Failed" in c for c in calls)

    def test_hook_test_surfaced(self):
        symbolic = _import_symbolic()
        self._setup_hook_mocks(surfaced=True)
        symbolic.run_hook_test(["text"])
        calls = [str(c) for c in _handler_mocks.success_fn.call_args_list]
        assert any("Fragment surfaced" in c for c in calls)

    def test_hook_test_not_surfaced(self):
        symbolic = _import_symbolic()
        self._setup_hook_mocks(surfaced=False)
        symbolic.run_hook_test(["text"])
        calls = [str(c) for c in _handler_mocks.console.print.call_args_list]
        assert any("Not surfaced" in c for c in calls)

    def test_hook_test_hook_fails(self):
        symbolic = _import_symbolic()
        self._setup_hook_mocks(hook_success=False)
        symbolic.run_hook_test(["text"])
        calls = [str(c) for c in _handler_mocks.error_fn.call_args_list]
        assert any("Hook failed" in c for c in calls)

    def test_hook_test_v2_fragments(self):
        symbolic = _import_symbolic()
        v2_frag = {
            "content": "debugging pattern",
            "metadata": {
                "schema_version": "v2",
                "summary": "Debug breakthrough",
                "insight": "Step by step",
                "type": "episodic",
            },
            "relevance_score": 0.85,
        }
        _handler_mocks.hook.extract_conversation_context.return_value = {
            "success": True,
            "keywords": ["test"],
            "mood": "neutral",
            "themes": ["coding"],
        }
        _handler_mocks.hook.find_relevant_fragments.return_value = {
            "success": True,
            "fragments": [v2_frag],
            "query_used": "test",
            "threshold_applied": 0.3,
        }
        _handler_mocks.hook.should_surface_fragment.return_value = (False, "test")
        _handler_mocks.hook.process_hook.return_value = {
            "success": True,
            "surfaced": False,
            "reason": "test",
        }
        _handler_mocks.hook.format_fragment_recall.return_value = "This reminds me of..."
        _handler_mocks.hook.get_session_state.return_value = {
            "fragments_surfaced": 0,
            "messages_since_last": 0,
        }
        _handler_mocks.hook.reset_session.return_value = None

        symbolic.run_hook_test(["text"])
        calls = [str(c) for c in _handler_mocks.console.print.call_args_list]
        # v2 fragment preview path: "Fragment {i} (v2):"
        assert any("(v2)" in c for c in calls)


# ===========================================================================
# analyze_file (lines 1207-1255)
# ===========================================================================


class TestAnalyzeFile:
    """Tests for analyze_file."""

    def test_analyze_file_not_found(self):
        symbolic = _import_symbolic()
        symbolic.analyze_file("/nonexistent/path/to/file.json")
        calls = [str(c) for c in _handler_mocks.error_fn.call_args_list]
        assert any("File not found" in c for c in calls)

    def test_analyze_file_read_fails(self, tmp_path):
        symbolic = _import_symbolic()
        chat_file = tmp_path / "chat.json"
        chat_file.write_text("[]", encoding="utf-8")

        _handler_mocks.memory_files.read_memory_file.return_value = {
            "success": False,
            "error": "Read error",
        }
        symbolic.analyze_file(str(chat_file))
        calls = [str(c) for c in _handler_mocks.error_fn.call_args_list]
        assert any("Read error" in c for c in calls)

    def test_analyze_file_not_list(self, tmp_path):
        symbolic = _import_symbolic()
        chat_file = tmp_path / "chat.json"
        chat_file.write_text("{}", encoding="utf-8")

        _handler_mocks.memory_files.read_memory_file.return_value = {
            "success": True,
            "data": {"not": "a list"},
        }
        symbolic.analyze_file(str(chat_file))
        calls = [str(c) for c in _handler_mocks.error_fn.call_args_list]
        assert any("Expected JSON array" in c for c in calls)

    def test_analyze_file_success(self, tmp_path):
        symbolic = _import_symbolic()
        chat_file = tmp_path / "chat.json"
        chat_data = [{"role": "user", "content": "hello"}]
        chat_file.write_text(json.dumps(chat_data), encoding="utf-8")

        _handler_mocks.memory_files.read_memory_file.return_value = {
            "success": True,
            "data": chat_data,
        }
        _handler_mocks.extractor.analyze_conversation.return_value = _default_analysis_result()

        symbolic.analyze_file(str(chat_file))
        calls = [str(c) for c in _handler_mocks.success_fn.call_args_list]
        assert any("Analysis complete" in c for c in calls)

    def test_analyze_file_failure(self, tmp_path):
        symbolic = _import_symbolic()
        chat_file = tmp_path / "chat.json"
        chat_data = [{"role": "user", "content": "hello"}]
        chat_file.write_text(json.dumps(chat_data), encoding="utf-8")

        _handler_mocks.memory_files.read_memory_file.return_value = {
            "success": True,
            "data": chat_data,
        }
        _handler_mocks.extractor.analyze_conversation.return_value = {
            "success": False,
            "error": "Analysis error",
        }

        symbolic.analyze_file(str(chat_file))
        calls = [str(c) for c in _handler_mocks.error_fn.call_args_list]
        assert any("Analysis failed" in c for c in calls)


# ===========================================================================
# extract_file (lines 1258-1323)
# ===========================================================================


class TestExtractFile:
    """Tests for extract_file."""

    def test_extract_file_not_found(self):
        symbolic = _import_symbolic()
        symbolic.extract_file("/nonexistent/path/to/file.json")
        calls = [str(c) for c in _handler_mocks.error_fn.call_args_list]
        assert any("File not found" in c for c in calls)

    def test_extract_file_read_fails(self, tmp_path):
        symbolic = _import_symbolic()
        chat_file = tmp_path / "chat.json"
        chat_file.write_text("[]", encoding="utf-8")

        _handler_mocks.memory_files.read_memory_file.return_value = {
            "success": False,
            "error": "Read error",
        }
        symbolic.extract_file(str(chat_file))
        calls = [str(c) for c in _handler_mocks.error_fn.call_args_list]
        assert any("Read error" in c for c in calls)

    def test_extract_file_not_list(self, tmp_path):
        symbolic = _import_symbolic()
        chat_file = tmp_path / "chat.json"
        chat_file.write_text("{}", encoding="utf-8")

        _handler_mocks.memory_files.read_memory_file.return_value = {
            "success": True,
            "data": {"not": "a list"},
        }
        symbolic.extract_file(str(chat_file))
        calls = [str(c) for c in _handler_mocks.error_fn.call_args_list]
        assert any("Expected JSON array" in c for c in calls)

    def test_extract_file_success(self, tmp_path):
        symbolic = _import_symbolic()
        chat_file = tmp_path / "chat.json"
        chat_data = [{"role": "user", "content": "hello"}]
        chat_file.write_text(json.dumps(chat_data), encoding="utf-8")

        _handler_mocks.memory_files.read_memory_file.return_value = {
            "success": True,
            "data": chat_data,
        }
        # extract_and_store_llm is called internally by extract_file
        # It calls extractor.extract_fragments_llm, then dedup + store loop
        _handler_mocks.extractor.extract_fragments_llm.return_value = {
            "success": True,
            "fragments": [{"summary": "test frag"}],
            "chunk_count": 1,
        }
        _handler_mocks.retriever.search_by_vector.return_value = {
            "success": True,
            "results": [],
        }
        _handler_mocks.deduplicator.deduplicate_fragment.return_value = {
            "action": "ADD",
            "fragment": {"summary": "test frag"},
            "reason": "new",
        }
        _handler_mocks.storage.store_llm_fragment.return_value = {
            "success": True,
            "fragment_id": "abc123",
        }

        symbolic.extract_file(str(chat_file))
        calls = [str(c) for c in _handler_mocks.success_fn.call_args_list]
        assert any("Pipeline complete" in c for c in calls)

    def test_extract_file_with_branch(self, tmp_path):
        symbolic = _import_symbolic()
        chat_file = tmp_path / "chat.json"
        chat_data = [{"role": "user", "content": "hello"}]
        chat_file.write_text(json.dumps(chat_data), encoding="utf-8")

        _handler_mocks.memory_files.read_memory_file.return_value = {
            "success": True,
            "data": chat_data,
        }
        _handler_mocks.extractor.extract_fragments_llm.return_value = {
            "success": True,
            "fragments": [],
            "chunk_count": 0,
        }

        symbolic.extract_file(str(chat_file), source_branch="memory")
        calls = [str(c) for c in _handler_mocks.console.print.call_args_list]
        assert any("memory" in c for c in calls)

    def test_extract_file_pipeline_fails(self, tmp_path):
        symbolic = _import_symbolic()
        chat_file = tmp_path / "chat.json"
        chat_data = [{"role": "user", "content": "hello"}]
        chat_file.write_text(json.dumps(chat_data), encoding="utf-8")

        _handler_mocks.memory_files.read_memory_file.return_value = {
            "success": True,
            "data": chat_data,
        }
        _handler_mocks.extractor.extract_fragments_llm.return_value = {
            "success": False,
            "error": "LLM unavailable",
        }

        symbolic.extract_file(str(chat_file))
        calls = [str(c) for c in _handler_mocks.error_fn.call_args_list]
        assert any("Pipeline failed" in c for c in calls)

    def test_extract_file_with_errors(self, tmp_path):
        symbolic = _import_symbolic()
        chat_file = tmp_path / "chat.json"
        chat_data = [{"role": "user", "content": "hello"}]
        chat_file.write_text(json.dumps(chat_data), encoding="utf-8")

        _handler_mocks.memory_files.read_memory_file.return_value = {
            "success": True,
            "data": chat_data,
        }
        # Pipeline succeeds but has errors
        _handler_mocks.extractor.extract_fragments_llm.return_value = {
            "success": True,
            "fragments": [{"summary": "frag1"}, {"summary": "frag2"}],
            "chunk_count": 1,
        }
        _handler_mocks.retriever.search_by_vector.return_value = {
            "success": True,
            "results": [],
        }
        _handler_mocks.deduplicator.deduplicate_fragment.return_value = {
            "action": "ADD",
            "fragment": {"summary": "frag"},
            "reason": "new",
        }
        # First store succeeds, second fails
        _handler_mocks.storage.store_llm_fragment.side_effect = [
            {"success": True, "fragment_id": "abc123"},
            {"success": False, "error": "store failed"},
        ]

        symbolic.extract_file(str(chat_file))
        # Pipeline should still complete with errors shown
        calls = [str(c) for c in _handler_mocks.success_fn.call_args_list]
        assert any("Pipeline complete" in c for c in calls)
        calls = [str(c) for c in _handler_mocks.warning_fn.call_args_list]
        assert any("Errors" in c for c in calls)

        # Reset side_effect
        _handler_mocks.storage.store_llm_fragment.side_effect = None


# ===========================================================================
# _parse_jsonl_to_chat_history (lines 1331-1390)
# ===========================================================================


class TestParseJsonlToChatHistory:
    """Tests for _parse_jsonl_to_chat_history."""

    def test_parse_user_text_message(self, tmp_path):
        symbolic = _import_symbolic()
        jsonl_file = tmp_path / "session.jsonl"
        entry = {"type": "user", "message": {"role": "user", "content": "Hello world"}}
        jsonl_file.write_text(json.dumps(entry) + "\n", encoding="utf-8")

        result = symbolic._parse_jsonl_to_chat_history(jsonl_file)
        assert len(result) == 1
        assert result[0]["role"] == "user"
        assert result[0]["content"] == "Hello world"

    def test_parse_assistant_text_message(self, tmp_path):
        symbolic = _import_symbolic()
        jsonl_file = tmp_path / "session.jsonl"
        entry = {"type": "assistant", "message": {"role": "assistant", "content": "I can help"}}
        jsonl_file.write_text(json.dumps(entry) + "\n", encoding="utf-8")

        result = symbolic._parse_jsonl_to_chat_history(jsonl_file)
        assert len(result) == 1
        assert result[0]["role"] == "assistant"
        assert result[0]["content"] == "I can help"

    def test_parse_user_list_content(self, tmp_path):
        symbolic = _import_symbolic()
        jsonl_file = tmp_path / "session.jsonl"
        entry = {
            "type": "user",
            "message": {
                "role": "user",
                "content": [
                    {"type": "text", "text": "First part"},
                    {"type": "text", "text": "Second part"},
                ],
            },
        }
        jsonl_file.write_text(json.dumps(entry) + "\n", encoding="utf-8")

        result = symbolic._parse_jsonl_to_chat_history(jsonl_file)
        assert len(result) == 1
        assert result[0]["content"] == "First part Second part"

    def test_parse_assistant_list_content(self, tmp_path):
        symbolic = _import_symbolic()
        jsonl_file = tmp_path / "session.jsonl"
        entry = {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "Response part 1"},
                    {"type": "text", "text": "Response part 2"},
                ],
            },
        }
        jsonl_file.write_text(json.dumps(entry) + "\n", encoding="utf-8")

        result = symbolic._parse_jsonl_to_chat_history(jsonl_file)
        assert len(result) == 1
        assert result[0]["content"] == "Response part 1 Response part 2"

    def test_parse_skips_malformed_lines(self, tmp_path):
        symbolic = _import_symbolic()
        jsonl_file = tmp_path / "session.jsonl"
        good_entry = {"type": "user", "message": {"role": "user", "content": "valid"}}
        content = "not valid json\n" + json.dumps(good_entry) + "\n" + "{{bad\n"
        jsonl_file.write_text(content, encoding="utf-8")

        result = symbolic._parse_jsonl_to_chat_history(jsonl_file)
        assert len(result) == 1
        assert result[0]["content"] == "valid"

    def test_parse_empty_file(self, tmp_path):
        symbolic = _import_symbolic()
        jsonl_file = tmp_path / "empty.jsonl"
        jsonl_file.write_text("", encoding="utf-8")

        result = symbolic._parse_jsonl_to_chat_history(jsonl_file)
        assert result == []

    def test_parse_os_error(self, tmp_path):
        symbolic = _import_symbolic()
        # Path that does not exist
        bad_path = tmp_path / "nonexistent.jsonl"

        result = symbolic._parse_jsonl_to_chat_history(bad_path)
        assert result == []


# ===========================================================================
# _find_bootstrap_sessions (lines 1393-1466)
# ===========================================================================


class TestFindBootstrapSessions:
    """Tests for _find_bootstrap_sessions."""

    def test_no_projects_dir(self, tmp_path, monkeypatch):
        symbolic = _import_symbolic()
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        # No .claude/projects directory exists
        result = symbolic._find_bootstrap_sessions()
        assert result == []

    def test_finds_priority_branch_files(self, tmp_path, monkeypatch):
        symbolic = _import_symbolic()
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        projects_dir = tmp_path / ".claude" / "projects"
        branch_dir = projects_dir / "-home-patrick-Projects-AIPass-src-aipass-memory"
        branch_dir.mkdir(parents=True)

        # Create a file in the valid size range (100KB-3MB)
        jsonl_file = branch_dir / "session1.jsonl"
        jsonl_file.write_text("x" * 200_000, encoding="utf-8")

        result = symbolic._find_bootstrap_sessions()
        assert len(result) == 1
        assert result[0] == jsonl_file

    def test_skips_agent_files(self, tmp_path, monkeypatch):
        symbolic = _import_symbolic()
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        projects_dir = tmp_path / ".claude" / "projects"
        branch_dir = projects_dir / "-home-patrick-Projects-AIPass-src-aipass-memory"
        branch_dir.mkdir(parents=True)

        # Agent file -- should be skipped
        agent_file = branch_dir / "agent-build.jsonl"
        agent_file.write_text("x" * 200_000, encoding="utf-8")

        result = symbolic._find_bootstrap_sessions()
        assert len(result) == 0

    def test_size_filtering(self, tmp_path, monkeypatch):
        symbolic = _import_symbolic()
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        projects_dir = tmp_path / ".claude" / "projects"
        branch_dir = projects_dir / "-home-patrick-Projects-AIPass-src-aipass-memory"
        branch_dir.mkdir(parents=True)

        # Too small (< 100KB)
        small_file = branch_dir / "small.jsonl"
        small_file.write_text("x" * 50_000, encoding="utf-8")

        # Too large (> 3MB)
        large_file = branch_dir / "large.jsonl"
        large_file.write_text("x" * 4_000_000, encoding="utf-8")

        result = symbolic._find_bootstrap_sessions()
        assert len(result) == 0

    def test_max_sessions_limit(self, tmp_path, monkeypatch):
        symbolic = _import_symbolic()
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        projects_dir = tmp_path / ".claude" / "projects"

        # Create multiple priority branch dirs with valid files
        branches = [
            "-home-patrick-Projects-AIPass-src-aipass-memory",
            "-home-patrick-Projects-AIPass-src-aipass-devpulse",
            "-home-patrick-Projects-AIPass-src-aipass-seedgo",
            "-home-patrick-Projects-AIPass-src-aipass-drone",
        ]
        for branch_name in branches:
            branch_dir = projects_dir / branch_name
            branch_dir.mkdir(parents=True)
            jsonl_file = branch_dir / "session.jsonl"
            jsonl_file.write_text("x" * 200_000, encoding="utf-8")

        result = symbolic._find_bootstrap_sessions(max_sessions=2)
        assert len(result) == 2


# ===========================================================================
# bootstrap_from_jsonl (lines 1469-1586)
# ===========================================================================


class TestBootstrapFromJsonl:
    """Tests for bootstrap_from_jsonl."""

    def test_bootstrap_no_sessions(self, monkeypatch):
        symbolic = _import_symbolic()
        monkeypatch.setattr(symbolic, "_find_bootstrap_sessions", lambda max_sessions: [])

        symbolic.bootstrap_from_jsonl()
        _handler_mocks.error_fn.assert_called()

    def test_bootstrap_success(self, tmp_path, monkeypatch):
        symbolic = _import_symbolic()

        # Create a JSONL file with enough messages
        jsonl_file = tmp_path / "-home-patrick-Projects-AIPass-src-aipass-memory" / "session.jsonl"
        jsonl_file.parent.mkdir(parents=True)
        lines = []
        for i in range(6):
            role = "user" if i % 2 == 0 else "assistant"
            entry = {"type": role, "message": {"role": role, "content": f"Message {i}"}}
            lines.append(json.dumps(entry))
        jsonl_file.write_text("\n".join(lines), encoding="utf-8")

        monkeypatch.setattr(symbolic, "_find_bootstrap_sessions", lambda max_sessions: [jsonl_file])
        monkeypatch.setattr(time, "sleep", lambda _: None)

        # Mock the pipeline
        _handler_mocks.extractor.extract_fragments_llm.return_value = {
            "success": True,
            "fragments": [{"summary": "test frag"}],
            "chunk_count": 1,
        }
        _handler_mocks.retriever.search_by_vector.return_value = {
            "success": True,
            "results": [],
        }
        _handler_mocks.deduplicator.deduplicate_fragment.return_value = {
            "action": "ADD",
            "fragment": {"summary": "test frag"},
            "reason": "new",
        }
        _handler_mocks.storage.store_llm_fragment.return_value = {
            "success": True,
            "fragment_id": "abc123",
        }

        symbolic.bootstrap_from_jsonl()
        assert any("Bootstrap Summary" in str(c) for c in _handler_mocks.header.call_args_list)

    def test_bootstrap_few_messages_skipped(self, tmp_path, monkeypatch):
        symbolic = _import_symbolic()

        # Create a JSONL with too few messages (< 4)
        jsonl_file = tmp_path / "-home-patrick-Projects-AIPass-src-aipass-memory" / "session.jsonl"
        jsonl_file.parent.mkdir(parents=True)
        entry = {"type": "user", "message": {"role": "user", "content": "Just one msg"}}
        jsonl_file.write_text(json.dumps(entry) + "\n", encoding="utf-8")

        monkeypatch.setattr(symbolic, "_find_bootstrap_sessions", lambda max_sessions: [jsonl_file])
        monkeypatch.setattr(time, "sleep", lambda _: None)

        symbolic.bootstrap_from_jsonl()
        calls = [str(c) for c in _handler_mocks.console.print.call_args_list]
        assert any("Too few messages" in c for c in calls)

    def test_bootstrap_pipeline_failure(self, tmp_path, monkeypatch):
        symbolic = _import_symbolic()

        # Create a JSONL file with enough messages
        jsonl_file = tmp_path / "-home-patrick-Projects-AIPass-src-aipass-memory" / "session.jsonl"
        jsonl_file.parent.mkdir(parents=True)
        lines = []
        for i in range(6):
            role = "user" if i % 2 == 0 else "assistant"
            entry = {"type": role, "message": {"role": role, "content": f"Message {i}"}}
            lines.append(json.dumps(entry))
        jsonl_file.write_text("\n".join(lines), encoding="utf-8")

        monkeypatch.setattr(symbolic, "_find_bootstrap_sessions", lambda max_sessions: [jsonl_file])
        monkeypatch.setattr(time, "sleep", lambda _: None)

        # Pipeline fails
        _handler_mocks.extractor.extract_fragments_llm.return_value = {
            "success": False,
            "error": "LLM unavailable",
        }

        symbolic.bootstrap_from_jsonl()
        calls = [str(c) for c in _handler_mocks.error_fn.call_args_list]
        assert any("Failed" in c for c in calls)
