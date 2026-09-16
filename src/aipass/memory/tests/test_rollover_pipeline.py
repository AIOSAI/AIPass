# ===================AIPASS====================
# META DATA HEADER
# Name: tests/test_rollover_pipeline.py
# Date: 2026-04-25
# Version: 1.2.1
# Modified: 2026-09-15
# Category: memory/tests
# =============================================

"""Tests for untested public functions in the rollover pipeline.

Covers:
  from aipass.memory.apps.handlers.rollover.orchestrator import store_vectors_subprocess
  from aipass.memory.apps.handlers.rollover.orchestrator import encode_batch_subprocess
  from aipass.memory.apps.handlers.rollover.orchestrator import get_branch_local_chroma_path
  from aipass.memory.apps.handlers.rollover.orchestrator import extract_text_from_memories
  from aipass.memory.apps.handlers.rollover.extractor import extract_with_metadata
  from aipass.memory.apps.modules.rollover import run_rollover
  from aipass.memory.apps.modules.rollover import show_status
  from aipass.memory.apps.modules.rollover import check_triggers
  from aipass.memory.apps.handlers.schema.normalize import normalize_all_memory_files
  from aipass.memory.apps.handlers.tracking.line_counter import update_all_memory_files
  from aipass.memory.apps.handlers.learnings.manager import process_all_branches

All tests use mocks or tmp_path -- no live filesystem or infrastructure access.
"""

import json
import logging
import subprocess
import tempfile
import types
import sys
from datetime import datetime
from pathlib import Path
import pytest
from types import ModuleType
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Import helpers -- each handler has module-level imports that need mocking
# ---------------------------------------------------------------------------


def _import_orchestrator(monkeypatch):
    """Import orchestrator with mocked infrastructure dependencies."""
    mock_detector = MagicMock()
    mock_detector._read_registry = MagicMock(return_value=[])
    mock_detector.check_all_branches = MagicMock(return_value={"success": True, "triggers": []})

    mock_extractor = MagicMock()
    mock_line_counter = MagicMock()

    monitor_pkg = MagicMock()

    # (test_import_isolation.py) — a bare MagicMock has none, and any lazy

    # submodule import under it then dies with "is not a package".

    monitor_pkg.detector = mock_detector

    rollover_pkg = MagicMock()

    # (test_import_isolation.py) — a bare MagicMock has none, and any lazy

    # submodule import under it then dies with "is not a package".

    rollover_pkg.extractor = mock_extractor

    tracking_pkg = MagicMock()

    # (test_import_isolation.py) — a bare MagicMock has none, and any lazy

    # submodule import under it then dies with "is not a package".

    tracking_pkg.line_counter = mock_line_counter

    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.monitor", monitor_pkg)
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.monitor.detector", mock_detector)
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.rollover.extractor", mock_extractor)
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.tracking", tracking_pkg)
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.tracking.line_counter", mock_line_counter)

    sys.modules.pop("aipass.memory.apps.handlers.rollover.orchestrator", None)
    parent = sys.modules.get("aipass.memory.apps.handlers.rollover")
    if parent is not None and hasattr(parent, "orchestrator"):
        delattr(parent, "orchestrator")

    from aipass.memory.apps.handlers.rollover import orchestrator

    return orchestrator, {
        "detector": mock_detector,
        "extractor": mock_extractor,
        "line_counter": mock_line_counter,
    }


def _import_extractor(monkeypatch):
    """Import extractor with mocked infrastructure dependencies."""
    mock_json_handler = MagicMock()
    mock_json_handler.log_operation = MagicMock(return_value=True)
    mock_memory_files = MagicMock()
    mock_memory_files.read_memory_file_data = MagicMock(return_value=None)
    mock_memory_files.write_memory_file_simple = MagicMock()

    mock_config_loader = MagicMock()
    mock_config_loader.section.return_value = {"defaults": {}, "per_branch": {}}

    json_pkg = MagicMock()
    # Impersonating a package means answering __path__ — a bare MagicMock does not,
    # and every lazy submodule import under it then dies. See test_import_isolation.py.
    json_pkg.__path__ = [str(Path(__file__).resolve().parent.parent / "apps" / "handlers" / "json")]
    json_pkg.json_handler = mock_json_handler
    json_pkg.config_loader = mock_config_loader

    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.json", json_pkg)
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.json.json_handler", mock_json_handler)
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.json.memory_files", mock_memory_files)
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.json.config_loader", mock_config_loader)

    sys.modules.pop("aipass.memory.apps.handlers.rollover.extractor", None)
    parent = sys.modules.get("aipass.memory.apps.handlers.rollover")
    if parent is not None and hasattr(parent, "extractor"):
        delattr(parent, "extractor")

    from aipass.memory.apps.handlers.rollover import extractor

    return extractor, {
        "json_handler": mock_json_handler,
        "memory_files": mock_memory_files,
        "config_loader": mock_config_loader,
    }


def _import_rollover_module(monkeypatch):
    """Import the rollover module with mocked infrastructure dependencies."""
    # FIRST LINE OF THE FIXTURE, before a single mock reaches sys.modules.
    # The `config` verbs live in modules/rollover_config.py and `_Json`,
    # `_emit` and `_refuse` in modules/rollover_json.py; rollover.py re-exports
    # both sets. BOTH modules must be first-imported against the REAL
    # aipass.cli, because whatever `console` and `error` each binds at import
    # time it keeps FOREVER — the module stays cached long after teardown
    # restores sys.modules. Standing one line below the cli stand-in was enough
    # to hand 191 of test_config_verbs.py's tests a MagicMock console that
    # printed nothing, in serial order only: --dist loadscope split the two
    # files across workers and no CI run ever saw it (2026-09-16).
    import importlib

    real_rollover_config = importlib.import_module("aipass.memory.apps.modules.rollover_config")
    real_rollover_json = importlib.import_module("aipass.memory.apps.modules.rollover_json")

    # rich
    mock_panel = MagicMock()
    mock_box = MagicMock()
    rich_panel_mod = MagicMock()
    rich_panel_mod.Panel = mock_panel
    rich_box_mod = MagicMock()
    rich_box_mod.box = mock_box
    monkeypatch.setitem(sys.modules, "rich.panel", rich_panel_mod)
    monkeypatch.setitem(sys.modules, "rich", MagicMock())

    # aipass.cli console / error / warning
    mock_console = MagicMock()
    mock_error = MagicMock()
    mock_warning = MagicMock()
    cli_modules_mod = MagicMock()
    cli_modules_mod.console = mock_console
    cli_modules_mod.error = mock_error
    cli_modules_mod.warning = mock_warning
    monkeypatch.setitem(sys.modules, "aipass.cli", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.cli.apps", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.cli.apps.modules", cli_modules_mod)

    # aipass.memory handler sub-packages
    mock_detector = MagicMock()
    mock_detector.check_all_branches = MagicMock(return_value={"success": True, "triggers": []})
    mock_detector.get_rollover_stats = MagicMock(
        return_value={
            "success": True,
            "total_branches": 0,
            "files_checked": 0,
            "files_ready": 0,
            "branches": {},
        }
    )

    mock_orchestrator = MagicMock()
    mock_orchestrator.execute_rollover = MagicMock(return_value={"success": True, "triggers_count": 0})
    mock_orchestrator.sync_line_counts = MagicMock(return_value={"success": True, "updated": 0, "failed": 0})

    monitor_pkg = MagicMock()
    monitor_pkg.detector = mock_detector

    rollover_pkg = MagicMock()
    rollover_pkg.orchestrator = mock_orchestrator

    # The todo-pad reports resolve a branch and read a pad: stubbed to the
    # honest "nothing resolved" line so these tests never touch a real pad.
    mock_todo_report = MagicMock()
    no_branch = {"level": "line", "text": "Todos: no branch resolved (harness) - no todo pad checked"}
    mock_todo_report.check_pad = MagicMock(return_value=no_branch)
    mock_todo_report.roll_pad = MagicMock(return_value=no_branch)
    rollover_pkg.todo_report = mock_todo_report

    # A real ModuleType, not a MagicMock: the stand-in has to survive being
    # treated as a package by the import machinery, and a MagicMock raises
    # AttributeError for __spec__ the moment importlib asks.
    handlers_pkg = ModuleType("aipass.memory.apps.handlers")
    # A package stand-in must carry a __path__ that reaches the REAL package
    # (test_import_isolation.py) — a bare MagicMock has none, and any lazy
    # submodule import under it then dies with "is not a package". modules/
    # rollover.py imports handlers.cli.help_flags, which this harness does not
    # stand in for, so without this line the whole file only passes when some
    # earlier test file happens to have imported handlers for real.
    handlers_pkg.__path__ = [str(Path(__file__).resolve().parents[1] / "apps" / "handlers")]
    setattr(handlers_pkg, "monitor", monitor_pkg)
    setattr(handlers_pkg, "rollover", rollover_pkg)

    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers", handlers_pkg)
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.monitor", monitor_pkg)
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.monitor.detector", mock_detector)
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.rollover", rollover_pkg)
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.rollover.orchestrator", mock_orchestrator)
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.rollover.todo_report", mock_todo_report)
    # Patched attribute by attribute rather than through the sys.modules
    # stand-in, because `_refuse` reads `error` from ITS OWN globals - without
    # these the mock error() never hears the refusal. monkeypatch restores each.
    monkeypatch.setattr(real_rollover_config, "console", mock_console)
    monkeypatch.setattr(real_rollover_config, "error", mock_error)
    monkeypatch.setattr(real_rollover_config, "detector", mock_detector)
    # And the same two on rollover_json, which is where `_emit` reads `console`
    # and `_refuse` reads `error` now — a patch on rollover_config no longer
    # reaches either of them. No `detector` there: that module never took one.
    monkeypatch.setattr(real_rollover_json, "console", mock_console)
    monkeypatch.setattr(real_rollover_json, "error", mock_error)

    # Recorded first, the way test_rollover.py's _import_rollover evicts. This re-import binds rollover
    # to the MagicMock cli; a bare pop and a bare delattr left that module cached AND named by the
    # modules package after teardown, so test_contracts' in-process `rollover <bogus>` on the same
    # worker exited 0 instead of 2 (-n 3 --dist loadscope, 2026-09-15).
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.modules.rollover", None)
    del sys.modules["aipass.memory.apps.modules.rollover"]
    parent = sys.modules.get("aipass.memory.apps.modules")
    if parent is not None:
        monkeypatch.setattr(parent, "rollover", None, raising=False)
        delattr(parent, "rollover")

    from aipass.memory.apps.modules import rollover

    return rollover, {
        "console": mock_console,
        "error": mock_error,
        "warning": mock_warning,
        "detector": mock_detector,
        "orchestrator": mock_orchestrator,
        "todo_report": mock_todo_report,
    }


class TestPipelineRolloverImportIsUndoneAtTeardown:
    """The rollover module _import_rollover_module binds to a MagicMock cli must not outlive its test.

    It did: under -n 3 --dist loadscope a worker ran TestRunRollover, then test_contracts'
    in-process `rollover <bogus>` routed through the mock error() and exited 0 instead of 2.
    """

    def test_sys_modules_and_the_parent_attribute_are_restored(self) -> None:
        import importlib

        name = "aipass.memory.apps.modules.rollover"
        parent = importlib.import_module("aipass.memory.apps.modules")
        module_before = sys.modules.get(name)
        attr_before = getattr(parent, "rollover", None)

        with pytest.MonkeyPatch.context() as mp:
            rollover, mocks = _import_rollover_module(mp)
            # Guard the guard: the re-import really is bound to the mock.
            assert rollover.error is mocks["error"]
            assert rollover is not module_before

        assert sys.modules.get(name) is module_before, "the mock-bound rollover outlived its test"
        assert getattr(parent, "rollover", None) is attr_before, (
            "the modules package still names the mock-bound rollover"
        )


def _import_normalize(monkeypatch):
    """Import normalize with mocked infrastructure dependencies."""
    mock_json_handler = MagicMock()
    mock_json_handler.log_operation = MagicMock(return_value=True)

    json_pkg = MagicMock()
    # Impersonating a package means answering __path__ — a bare MagicMock does not,
    # and every lazy submodule import under it then dies. See test_import_isolation.py.
    json_pkg.__path__ = [str(Path(__file__).resolve().parent.parent / "apps" / "handlers" / "json")]
    json_pkg.json_handler = mock_json_handler

    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.json", json_pkg)
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.json.json_handler", mock_json_handler)

    sys.modules.pop("aipass.memory.apps.handlers.schema.normalize", None)
    parent = sys.modules.get("aipass.memory.apps.handlers.schema")
    if parent is not None and hasattr(parent, "normalize"):
        delattr(parent, "normalize")

    from aipass.memory.apps.handlers.schema import normalize

    return normalize, {
        "json_handler": mock_json_handler,
    }


def _import_line_counter(monkeypatch):
    """Import line_counter with mocked infrastructure dependencies."""
    mock_json_handler = MagicMock()
    mock_json_handler.log_operation = MagicMock(return_value=True)
    mock_memory_files = MagicMock()
    mock_memory_files.update_metadata = MagicMock(return_value={"success": True})

    json_pkg = MagicMock()
    # Impersonating a package means answering __path__ — a bare MagicMock does not,
    # and every lazy submodule import under it then dies. See test_import_isolation.py.
    json_pkg.__path__ = [str(Path(__file__).resolve().parent.parent / "apps" / "handlers" / "json")]
    json_pkg.json_handler = mock_json_handler

    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.json", json_pkg)
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.json.json_handler", mock_json_handler)
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.json.memory_files", mock_memory_files)

    sys.modules.pop("aipass.memory.apps.handlers.tracking.line_counter", None)
    parent = sys.modules.get("aipass.memory.apps.handlers.tracking")
    if parent is not None and hasattr(parent, "line_counter"):
        delattr(parent, "line_counter")

    from aipass.memory.apps.handlers.tracking import line_counter

    return line_counter, {
        "json_handler": mock_json_handler,
        "memory_files": mock_memory_files,
    }


# ===========================================================================
# Tests: orchestrator.store_vectors_subprocess
# ===========================================================================


class TestStoreVectorsSubprocess:
    """Test store_vectors_subprocess calls subprocess and returns dict."""

    def test_success_returns_parsed_json(self, monkeypatch):
        orch, _ = _import_orchestrator(monkeypatch)
        expected = {"success": True, "collection": "test_col", "total_vectors": 5}
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps(expected)

        with patch.object(subprocess, "run", return_value=mock_result) as mock_run:
            result = orch.store_vectors_subprocess(
                branch="TEST",
                memory_type="sessions",
                embeddings=[[0.1, 0.2]],
                documents=["doc1"],
                metadatas=[{"key": "val"}],
                db_path=str(Path(tempfile.gettempdir()) / "test.chroma"),
            )

        assert result["success"] is True
        assert result["collection"] == "test_col"
        mock_run.assert_called_once()

    def test_nonzero_returncode_returns_failure(self, monkeypatch):
        orch, _ = _import_orchestrator(monkeypatch)
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "some error"

        with patch.object(subprocess, "run", return_value=mock_result):
            result = orch.store_vectors_subprocess(
                branch="TEST",
                memory_type="sessions",
                embeddings=[[0.1]],
                documents=["doc1"],
                metadatas=[{}],
            )

        assert result["success"] is False
        assert "some error" in result["error"]

    def test_timeout_returns_failure(self, monkeypatch):
        orch, _ = _import_orchestrator(monkeypatch)

        with patch.object(subprocess, "run", side_effect=subprocess.TimeoutExpired(cmd="test", timeout=60)):
            result = orch.store_vectors_subprocess(
                branch="TEST",
                memory_type="sessions",
                embeddings=[[0.1]],
                documents=["doc1"],
                metadatas=[{}],
            )

        assert result["success"] is False
        assert "timed out" in result["error"]

    def test_invalid_json_response_returns_failure(self, monkeypatch):
        orch, _ = _import_orchestrator(monkeypatch)
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "not valid json"

        with patch.object(subprocess, "run", return_value=mock_result):
            result = orch.store_vectors_subprocess(
                branch="TEST",
                memory_type="sessions",
                embeddings=[[0.1]],
                documents=["doc1"],
                metadatas=[{}],
            )

        assert result["success"] is False
        assert "Invalid JSON" in result["error"]

    def test_numpy_array_tolist_conversion(self, monkeypatch):
        """Embeddings with tolist() method get serialized correctly."""
        orch, _ = _import_orchestrator(monkeypatch)
        expected = {"success": True}
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps(expected)

        # Simulate a numpy array with tolist method
        mock_embedding = MagicMock()
        mock_embedding.tolist.return_value = [0.1, 0.2, 0.3]

        with patch.object(subprocess, "run", return_value=mock_result) as mock_run:
            result = orch.store_vectors_subprocess(
                branch="TEST",
                memory_type="sessions",
                embeddings=[mock_embedding],
                documents=["doc1"],
                metadatas=[{}],
            )

        assert result["success"] is True
        mock_embedding.tolist.assert_called_once()
        # Verify the serialized data includes the converted list
        call_kwargs = mock_run.call_args
        input_data = json.loads(call_kwargs.kwargs.get("input", call_kwargs[1].get("input", "")))
        assert input_data["embeddings"] == [[0.1, 0.2, 0.3]]


# ===========================================================================
# Tests: orchestrator.encode_batch_subprocess
# ===========================================================================


class TestEncodeBatchSubprocess:
    """Test encode_batch_subprocess calls subprocess for embedding."""

    def test_success_returns_embeddings(self, monkeypatch):
        orch, _ = _import_orchestrator(monkeypatch)
        expected = {"success": True, "embeddings": [[0.1, 0.2]], "count": 1, "dimension": 2}
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps(expected)

        with patch.object(subprocess, "run", return_value=mock_result):
            result = orch.encode_batch_subprocess(["hello world"])

        assert result["success"] is True
        assert result["embeddings"] == [[0.1, 0.2]]

    def test_nonzero_returncode_returns_failure(self, monkeypatch):
        orch, _ = _import_orchestrator(monkeypatch)
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "embedding error"

        with patch.object(subprocess, "run", return_value=mock_result):
            result = orch.encode_batch_subprocess(["text"])

        assert result["success"] is False
        assert "embedding error" in result["error"]

    def test_timeout_returns_failure(self, monkeypatch):
        orch, _ = _import_orchestrator(monkeypatch)

        with patch.object(subprocess, "run", side_effect=subprocess.TimeoutExpired(cmd="test", timeout=120)):
            result = orch.encode_batch_subprocess(["text"])

        assert result["success"] is False
        assert "timed out" in result["error"]

    def test_invalid_json_returns_failure(self, monkeypatch):
        orch, _ = _import_orchestrator(monkeypatch)
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "bad json"

        with patch.object(subprocess, "run", return_value=mock_result):
            result = orch.encode_batch_subprocess(["text"])

        assert result["success"] is False
        assert "Invalid JSON" in result["error"]

    def test_generic_exception_returns_failure(self, monkeypatch):
        orch, _ = _import_orchestrator(monkeypatch)

        with patch.object(subprocess, "run", side_effect=OSError("no such file")):
            result = orch.encode_batch_subprocess(["text"])

        assert result["success"] is False
        assert "no such file" in result["error"]


# ===========================================================================
# Tests: orchestrator.get_branch_local_chroma_path
# ===========================================================================


class TestGetBranchLocalChromaPath:
    """Test get_branch_local_chroma_path looks up branch in registry."""

    def test_returns_chroma_path_for_existing_branch(self, monkeypatch, tmp_path):
        orch, mocks = _import_orchestrator(monkeypatch)
        branch_dir = tmp_path / "my_branch"
        branch_dir.mkdir()

        mocks["detector"]._read_registry.return_value = [
            {"name": "MY_BRANCH", "path": str(branch_dir)},
        ]

        result = orch.get_branch_local_chroma_path("MY_BRANCH")

        assert result is not None
        assert result == branch_dir / ".chroma"
        assert result.exists()  # auto-created

    def test_returns_none_for_empty_name(self, monkeypatch):
        orch, _ = _import_orchestrator(monkeypatch)
        assert orch.get_branch_local_chroma_path("") is None

    def test_returns_none_for_unknown_branch(self, monkeypatch):
        orch, mocks = _import_orchestrator(monkeypatch)
        mocks["detector"]._read_registry.return_value = [
            {"name": "OTHER", "path": "/nonexistent"},
        ]
        result = orch.get_branch_local_chroma_path("MISSING_BRANCH")
        assert result is None

    def test_case_insensitive_lookup(self, monkeypatch, tmp_path):
        orch, mocks = _import_orchestrator(monkeypatch)
        branch_dir = tmp_path / "branch"
        branch_dir.mkdir()

        mocks["detector"]._read_registry.return_value = [
            {"name": "My_Branch", "path": str(branch_dir)},
        ]

        result = orch.get_branch_local_chroma_path("my_branch")
        assert result is not None
        assert result == branch_dir / ".chroma"

    def test_returns_existing_chroma_dir(self, monkeypatch, tmp_path):
        orch, mocks = _import_orchestrator(monkeypatch)
        branch_dir = tmp_path / "branch"
        chroma_dir = branch_dir / ".chroma"
        chroma_dir.mkdir(parents=True)

        mocks["detector"]._read_registry.return_value = [
            {"name": "BRANCH", "path": str(branch_dir)},
        ]

        result = orch.get_branch_local_chroma_path("BRANCH")
        assert result == chroma_dir


# ===========================================================================
# Tests: orchestrator.extract_text_from_memories
# ===========================================================================


class TestExtractTextFromMemories:
    """Test extract_text_from_memories extracts text from memory items."""

    def test_extracts_from_activities(self, monkeypatch):
        orch, _ = _import_orchestrator(monkeypatch)
        memories = [{"activities": ["task 1", "task 2"]}]
        texts = orch.extract_text_from_memories(memories)
        assert len(texts) == 1
        assert "task 1" in texts[0]
        assert "task 2" in texts[0]

    def test_extracts_from_summary(self, monkeypatch):
        orch, _ = _import_orchestrator(monkeypatch)
        memories = [{"summary": "Session summary text"}]
        texts = orch.extract_text_from_memories(memories)
        assert texts == ["Session summary text"]

    def test_extracts_from_key_learning(self, monkeypatch):
        orch, _ = _import_orchestrator(monkeypatch)
        memories = [{"_type": "key_learning", "key": "pattern", "value": "use pathlib"}]
        texts = orch.extract_text_from_memories(memories)
        assert len(texts) == 1
        assert "pattern" in texts[0]
        assert "use pathlib" in texts[0]

    def test_extracts_from_content_field(self, monkeypatch):
        orch, _ = _import_orchestrator(monkeypatch)
        memories = [{"content": "some content"}]
        texts = orch.extract_text_from_memories(memories)
        assert texts == ["some content"]

    def test_extracts_from_text_field(self, monkeypatch):
        orch, _ = _import_orchestrator(monkeypatch)
        memories = [{"text": "raw text"}]
        texts = orch.extract_text_from_memories(memories)
        assert texts == ["raw text"]

    def test_extracts_from_message_field(self, monkeypatch):
        orch, _ = _import_orchestrator(monkeypatch)
        memories = [{"message": "a message"}]
        texts = orch.extract_text_from_memories(memories)
        assert texts == ["a message"]

    def test_fallback_to_string_representation(self, monkeypatch):
        orch, _ = _import_orchestrator(monkeypatch)
        memories = [{"unknown_field": 42}]
        texts = orch.extract_text_from_memories(memories)
        assert len(texts) == 1
        assert "unknown_field" in texts[0]

    def test_empty_list_returns_empty(self, monkeypatch):
        orch, _ = _import_orchestrator(monkeypatch)
        assert orch.extract_text_from_memories([]) == []

    def test_multiple_memory_types(self, monkeypatch):
        orch, _ = _import_orchestrator(monkeypatch)
        memories = [
            {"summary": "session 1"},
            {"content": "observation"},
            {"_type": "key_learning", "key": "k", "value": "v"},
        ]
        texts = orch.extract_text_from_memories(memories)
        assert len(texts) == 3


# ===========================================================================
# Tests: extractor.extract_with_metadata
# ===========================================================================


class TestExtractWithMetadata:
    """Test extract_with_metadata enriches extracted items."""

    def test_returns_failure_for_nonexistent_file(self, monkeypatch, tmp_path):
        ext, _ = _import_extractor(monkeypatch)
        result = ext.extract_with_metadata(tmp_path / "nonexistent.json")
        assert result["success"] is False
        assert "not found" in result["error"].lower()

    def test_returns_failure_when_file_cannot_be_parsed(self, monkeypatch, tmp_path):
        ext, mocks = _import_extractor(monkeypatch)
        file_path = tmp_path / "bad.json"
        file_path.write_text("{}", encoding="utf-8")
        mocks["memory_files"].read_memory_file_data.return_value = None

        result = ext.extract_with_metadata(file_path)
        assert result["success"] is False

    def test_v2_extraction_enriches_entries(self, monkeypatch, tmp_path):
        """v2 schema extraction adds _metadata to each extracted entry."""
        ext, mocks = _import_extractor(monkeypatch)

        # Branch name derived from parent of .trinity: tmp_path name (lowercase)
        branch_name = tmp_path.name.lower()

        # Provision limits via config per_branch
        mocks["config_loader"].section.return_value = {
            "defaults": {},
            "per_branch": {
                branch_name: {
                    "local": {"sessions": {"count": 2}},
                },
            },
        }

        data = {
            "document_metadata": {
                "schema_version": "2.0.0",
                "status": {},
            },
            "sessions": [
                {"session_number": 1, "summary": "newest"},
                {"session_number": 2, "summary": "middle"},
                {"session_number": 3, "summary": "oldest"},
            ],
        }
        file_path = tmp_path / ".trinity" / "local.json"
        file_path.parent.mkdir(parents=True)
        file_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

        mocks["memory_files"].read_memory_file_data.return_value = data
        # True, not None: the real writer returns a success boolean, and a
        # stand-in more generous than the thing it stands in for is how a guard
        # stops being observable. `None` read as "don't care" only while the
        # return value was being discarded — which was the defect.
        mocks["memory_files"].write_memory_file_simple.return_value = True

        result = ext.extract_with_metadata(file_path)

        assert result["success"] is True
        assert "entries" in result
        assert result["branch"] is not None
        assert result["type"] is not None
        # Enriched entries should have _metadata
        for entry in result.get("entries", []):
            assert "_metadata" in entry
            assert "branch" in entry["_metadata"]
            assert "extracted_at" in entry["_metadata"]

    def test_v2_extracts_when_observations_at_limit(self, monkeypatch, tmp_path):
        """v2 file at entry-count limit should extract, not skip."""
        ext, mocks = _import_extractor(monkeypatch)

        observations = [
            {"date": f"2026-01-{i:02d}", "session": i, "entries": [{"title": f"obs {i}"}]} for i in range(1, 11)
        ]
        data = {
            "document_metadata": {
                "schema_version": "3.0.0",
                "status": {},
            },
            "observations": observations,
        }
        file_path = tmp_path / ".trinity" / "observations.json"
        file_path.parent.mkdir(parents=True)
        file_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

        branch_key = tmp_path.name.lower()
        mocks["config_loader"].section.return_value = {
            "defaults": {},
            "per_branch": {branch_key: {"observations": {"observations": {"count": 5}}}},
        }
        mocks["memory_files"].read_memory_file_data.return_value = data

        def fake_write(fp, d):
            fp.write_text(json.dumps(d, indent=2), encoding="utf-8")

        monkeypatch.setattr(ext, "_write_memory_file", fake_write)

        result = ext.extract_items(file_path)
        assert result["success"] is True
        assert result.get("skipped") is not True
        assert result["extracted_count"] > 0

    def test_skipped_result_passes_through(self, monkeypatch, tmp_path):
        """When extract_items returns skipped (under limit), extract_with_metadata passes it."""
        ext, mocks = _import_extractor(monkeypatch)

        # v2 file under limits (no extraction needed)
        data = {
            "document_metadata": {
                "schema_version": "3.0.0",
                "status": {},
            },
            "sessions": [{"session_number": 1, "summary": "only one"}],
        }
        file_path = tmp_path / ".trinity" / "local.json"
        file_path.parent.mkdir(parents=True)
        file_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

        branch_key = tmp_path.name.lower()
        mocks["config_loader"].section.return_value = {
            "defaults": {},
            "per_branch": {branch_key: {"local": {"sessions": {"count": 10}}}},
        }
        mocks["memory_files"].read_memory_file_data.return_value = data

        result = ext.extract_with_metadata(file_path)
        # _extract_items_v2 returns skipped when under limit; extract_with_metadata
        # passes the result dict through unchanged when nothing was extracted
        assert result["success"] is True
        # The passthrough is the WHOLE contract: skipped stays true, nothing was
        # counted and nothing was extracted. An `or` between those hid the case
        # where the dict was rebuilt and only one half survived.
        assert result["skipped"] is True
        assert result["count"] == 0
        assert result["entries"] == []


# ===========================================================================
# Tests: rollover/extractor.py -- safety valve + auto-compact snapshot budget
# ===========================================================================


class TestRolloverSafetyValve:
    """Entries dated today or numbered above the head must never be archived as 'oldest'."""

    def test_skips_archiving_entry_dated_today(self, monkeypatch, tmp_path):
        ext, mocks = _import_extractor(monkeypatch)
        branch_key = tmp_path.name.lower()
        today = datetime.now().strftime("%Y-%m-%d")

        data = {
            "document_metadata": {"schema_version": "3.0.0", "status": {}},
            "sessions": [
                {"number": 4, "date": "2026-01-04", "summary": "newest", "status": "completed"},
                {"number": 3, "date": "2026-01-03", "summary": "second", "status": "completed"},
                {"number": 1, "date": today, "summary": "fresh-write-at-tail", "status": "completed"},
                {"number": 2, "date": "2026-01-01", "summary": "oldest-real", "status": "completed"},
            ],
        }
        file_path = tmp_path / ".trinity" / "local.json"
        file_path.parent.mkdir(parents=True)
        file_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

        mocks["config_loader"].section.return_value = {
            "defaults": {},
            "per_branch": {branch_key: {"local": {"sessions": {"count": 2}}}},
        }
        mocks["memory_files"].read_memory_file_data.return_value = data

        result = ext.extract_items(file_path)

        assert result["success"] is True
        assert result.get("skipped") is not True
        archived_summaries = [e["summary"] for e in result["extracted"]]
        assert "fresh-write-at-tail" not in archived_summaries
        assert "oldest-real" in archived_summaries
        remaining_summaries = [e["summary"] for e in data["sessions"]]
        assert "fresh-write-at-tail" in remaining_summaries

    def test_skips_archiving_entry_numbered_above_head(self, monkeypatch, tmp_path):
        """A tail entry numbered higher than the head is a misplaced write, not oldest history."""
        ext, mocks = _import_extractor(monkeypatch)
        branch_key = tmp_path.name.lower()

        data = {
            "document_metadata": {"schema_version": "3.0.0", "status": {}},
            "sessions": [
                {"number": 5, "date": "2026-01-05", "summary": "newest", "status": "completed"},
                {"number": 4, "date": "2026-01-04", "summary": "second", "status": "completed"},
                {"number": 9, "date": "2020-01-01", "summary": "misplaced-high-number", "status": "completed"},
                {"number": 3, "date": "2026-01-01", "summary": "oldest-real", "status": "completed"},
            ],
        }
        file_path = tmp_path / ".trinity" / "local.json"
        file_path.parent.mkdir(parents=True)
        file_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

        mocks["config_loader"].section.return_value = {
            "defaults": {},
            "per_branch": {branch_key: {"local": {"sessions": {"count": 2}}}},
        }
        mocks["memory_files"].read_memory_file_data.return_value = data

        result = ext.extract_items(file_path)

        assert result["success"] is True
        assert result.get("skipped") is not True
        archived_summaries = [e["summary"] for e in result["extracted"]]
        assert "misplaced-high-number" not in archived_summaries
        assert "oldest-real" in archived_summaries
        remaining_summaries = [e["summary"] for e in data["sessions"]]
        assert "misplaced-high-number" in remaining_summaries

    def test_archives_genuinely_old_entry_normally(self, monkeypatch, tmp_path):
        """Sanity check: a plain old-dated, correctly-numbered tail entry still archives."""
        ext, mocks = _import_extractor(monkeypatch)
        branch_key = tmp_path.name.lower()

        data = {
            "document_metadata": {"schema_version": "3.0.0", "status": {}},
            "sessions": [
                {"number": 3, "date": "2026-01-03", "summary": "newest", "status": "completed"},
                {"number": 2, "date": "2026-01-02", "summary": "middle", "status": "completed"},
                {"number": 1, "date": "2026-01-01", "summary": "oldest", "status": "completed"},
            ],
        }
        file_path = tmp_path / ".trinity" / "local.json"
        file_path.parent.mkdir(parents=True)
        file_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

        mocks["config_loader"].section.return_value = {
            "defaults": {},
            "per_branch": {branch_key: {"local": {"sessions": {"count": 2}}}},
        }
        mocks["memory_files"].read_memory_file_data.return_value = data

        result = ext.extract_items(file_path)

        assert result["success"] is True
        archived_summaries = [e["summary"] for e in result["extracted"]]
        assert archived_summaries == ["oldest"]


class TestAutoCompactSnapshotBudget:
    """AUTO-COMPACT SNAPSHOT entries get a small dedicated cap, separate from the session keep budget."""

    def test_auto_compact_entries_capped_independently(self, monkeypatch, tmp_path):
        ext, mocks = _import_extractor(monkeypatch)
        branch_key = tmp_path.name.lower()

        # 4 auto-compact snapshots (cap 3) + 2 regular sessions (count limit 10, well under)
        sessions = [
            {"number": 6, "date": "2026-01-06", "summary": "AUTO-COMPACT SNAPSHOT: d", "status": "auto-compact"},
            {"number": 5, "date": "2026-01-05", "summary": "regular newest", "status": "completed"},
            {"number": 4, "date": "2026-01-04", "summary": "AUTO-COMPACT SNAPSHOT: c", "status": "auto-compact"},
            {"number": 3, "date": "2026-01-03", "summary": "AUTO-COMPACT SNAPSHOT: b", "status": "auto-compact"},
            {"number": 2, "date": "2026-01-02", "summary": "regular oldest", "status": "completed"},
            {"number": 1, "date": "2026-01-01", "summary": "AUTO-COMPACT SNAPSHOT: a", "status": "auto-compact"},
        ]
        data = {
            "document_metadata": {"schema_version": "3.0.0", "status": {}},
            "sessions": sessions,
        }
        file_path = tmp_path / ".trinity" / "local.json"
        file_path.parent.mkdir(parents=True)
        file_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

        mocks["config_loader"].section.return_value = {
            "defaults": {},
            "per_branch": {
                branch_key: {"local": {"sessions": {"count": 10, "auto_compact_cap": 3}}},
            },
        }
        mocks["memory_files"].read_memory_file_data.return_value = data

        result = ext.extract_items(file_path)

        assert result["success"] is True
        archived_summaries = {e["summary"] for e in result["extracted"]}
        # Only the single oldest auto-compact snapshot beyond the cap of 3 is archived
        assert archived_summaries == {"AUTO-COMPACT SNAPSHOT: a"}
        # Regular sessions untouched (well under count limit of 10)
        remaining_summaries = {e["summary"] for e in data["sessions"]}
        assert "regular newest" in remaining_summaries
        assert "regular oldest" in remaining_summaries

    def test_auto_compact_entries_do_not_count_against_regular_budget(self, monkeypatch, tmp_path):
        """Auto-compact snapshots must not push regular sessions out early."""
        ext, mocks = _import_extractor(monkeypatch)
        branch_key = tmp_path.name.lower()

        # 3 regular sessions OVER count limit 2 -- triggers, archives one --
        # plus 3 auto-compact well under cap 5. Keep-2 keeps 2, so the budget
        # has to be exceeded for anything to move (B4, 2026-08-25).
        sessions = [
            {"number": 6, "date": "2026-01-06", "summary": "regular newest", "status": "completed"},
            {"number": 5, "date": "2026-01-05", "summary": "AUTO-COMPACT SNAPSHOT: c", "status": "auto-compact"},
            {"number": 4, "date": "2026-01-04", "summary": "regular middle", "status": "completed"},
            {"number": 3, "date": "2026-01-03", "summary": "AUTO-COMPACT SNAPSHOT: b", "status": "auto-compact"},
            {"number": 2, "date": "2026-01-02", "summary": "regular oldest", "status": "completed"},
            {"number": 1, "date": "2026-01-01", "summary": "AUTO-COMPACT SNAPSHOT: a", "status": "auto-compact"},
        ]
        data = {
            "document_metadata": {"schema_version": "3.0.0", "status": {}},
            "sessions": sessions,
        }
        file_path = tmp_path / ".trinity" / "local.json"
        file_path.parent.mkdir(parents=True)
        file_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

        mocks["config_loader"].section.return_value = {
            "defaults": {},
            "per_branch": {
                branch_key: {"local": {"sessions": {"count": 2, "auto_compact_cap": 5}}},
            },
        }
        mocks["memory_files"].read_memory_file_data.return_value = data

        result = ext.extract_items(file_path)

        assert result["success"] is True
        archived_summaries = {e["summary"] for e in result["extracted"]}
        # Regular budget (count=2) triggers on 3 regular entries > 2 -> archives the oldest regular one only
        assert archived_summaries == {"regular oldest"}
        remaining_summaries = {e["summary"] for e in data["sessions"]}
        assert "AUTO-COMPACT SNAPSHOT: a" in remaining_summaries
        assert "AUTO-COMPACT SNAPSHOT: b" in remaining_summaries
        assert "AUTO-COMPACT SNAPSHOT: c" in remaining_summaries
        assert "regular newest" in remaining_summaries
        assert "regular middle" in remaining_summaries


class TestAutoCompactSameDaySnapshots:
    """DPLAN-0290 item 3 — the snapshot lane must drain even when every snapshot is dated today.

    Snapshots are machine-written several times in one day, so at cap the oldest
    one is essentially always dated today. The safety valve's date rule refused
    exactly those entries, so the detector re-fired on the same file forever
    while the extractor archived nothing: the skip loop.
    """

    @staticmethod
    def _setup(ext, mocks, tmp_path, sessions, cap=3, count=10):
        data = {
            "document_metadata": {"schema_version": "3.0.0", "status": {}},
            "sessions": sessions,
        }
        file_path = tmp_path / ".trinity" / "local.json"
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

        mocks["config_loader"].section.return_value = {
            "defaults": {},
            "per_branch": {tmp_path.name.lower(): {"local": {"sessions": {"count": count, "auto_compact_cap": cap}}}},
        }
        mocks["memory_files"].read_memory_file_data.return_value = data
        return file_path, data

    def test_same_day_snapshots_drain_over_cap(self, monkeypatch, tmp_path):
        """4 snapshots, all written today, cap 3 -> the oldest one archives.

        The point of this test is the DATE, not the count: every candidate is
        dated today, and the valve must still let the snapshot lane drain. The
        lane is now driven one entry OVER the cap because keep-3 keeps 3 (B4).
        """
        ext, mocks = _import_extractor(monkeypatch)
        today = datetime.now().strftime("%Y-%m-%d")
        sessions = [
            {"number": 30, "date": today, "summary": "regular newest", "status": "completed"},
            {"number": 29, "date": today, "summary": "AUTO-COMPACT SNAPSHOT: d", "status": "auto-compact"},
            {"number": 27, "date": today, "summary": "AUTO-COMPACT SNAPSHOT: c", "status": "auto-compact"},
            {"number": 25, "date": today, "summary": "AUTO-COMPACT SNAPSHOT: b", "status": "auto-compact"},
            {"number": 22, "date": today, "summary": "AUTO-COMPACT SNAPSHOT: a", "status": "auto-compact"},
        ]
        file_path, data = self._setup(ext, mocks, tmp_path, sessions)

        result = ext.extract_items(file_path)

        assert result["success"] is True
        assert result.get("skipped") is not True, "snapshot lane skipped — the file cannot drain"
        assert {e["summary"] for e in result["extracted"]} == {"AUTO-COMPACT SNAPSHOT: a"}
        assert "regular newest" in {e["summary"] for e in data["sessions"]}

    def test_skip_loop_terminates(self, monkeypatch, tmp_path):
        """Repeated runs must reach a steady state AT the cap, not re-trigger forever.

        The steady state moved with B4 (2026-08-25): the lane now settles at
        the cap rather than one below it, because keep-3 keeps 3. That is the
        whole point of the fix — the old floor archived an entry the standard
        said to keep, so every capped lane in the fleet rested one short.

        What this test is actually guarding is unchanged: repeated runs must
        CONVERGE. A lane that keeps draining past its cap and a lane that never
        drains are both failures; only "reaches the cap and then stops" is
        correct, and the last two iterations below prove the stop.
        """
        ext, mocks = _import_extractor(monkeypatch)
        today = datetime.now().strftime("%Y-%m-%d")
        sessions = [{"number": 40, "date": today, "summary": "regular newest", "status": "completed"}]
        sessions += [
            {"number": 30 - i, "date": today, "summary": f"snap-{i}", "status": "auto-compact"} for i in range(5)
        ]
        file_path, data = self._setup(ext, mocks, tmp_path, sessions)

        # The write path is mocked here, so `data` (mutated in place by each run)
        # is what the next run would read on a live system.
        archived_total = 0
        per_run = []
        for _ in range(5):
            result = ext.extract_items(file_path)
            assert result["success"] is True
            archived = len(result.get("extracted", []))
            archived_total += archived
            per_run.append(archived)

        snapshots = [e for e in data["sessions"] if e.get("status") == "auto-compact"]
        assert archived_total > 0, "nothing ever archived — the skip loop is live"
        assert len(snapshots) == 3, f"snapshot lane did not settle at the cap: {len(snapshots)} left"
        assert per_run[-1] == 0 and per_run[-2] == 0, f"lane never stopped draining: {per_run}"

    def test_snapshot_numbered_above_head_is_still_refused(self, monkeypatch, tmp_path):
        """Relaxing the date rule must not relax the ordering rule."""
        ext, mocks = _import_extractor(monkeypatch)
        today = datetime.now().strftime("%Y-%m-%d")
        sessions = [
            {"number": 30, "date": today, "summary": "regular newest", "status": "completed"},
            {"number": 29, "date": today, "summary": "AUTO-COMPACT SNAPSHOT: c", "status": "auto-compact"},
            {"number": 28, "date": today, "summary": "AUTO-COMPACT SNAPSHOT: b", "status": "auto-compact"},
            {"number": 99, "date": today, "summary": "misplaced-high-number", "status": "auto-compact"},
        ]
        file_path, data = self._setup(ext, mocks, tmp_path, sessions)

        result = ext.extract_items(file_path)

        archived = {e["summary"] for e in result.get("extracted", [])}
        assert "misplaced-high-number" not in archived
        assert "misplaced-high-number" in {e["summary"] for e in data["sessions"]}

    def test_snapshot_without_a_number_keeps_the_date_guard(self, monkeypatch, tmp_path):
        """When ordering cannot decide, the conservative date rule still applies."""
        ext, mocks = _import_extractor(monkeypatch)
        today = datetime.now().strftime("%Y-%m-%d")
        sessions = [
            {"number": 30, "date": today, "summary": "regular newest", "status": "completed"},
            {"number": 29, "date": today, "summary": "AUTO-COMPACT SNAPSHOT: c", "status": "auto-compact"},
            {"number": 28, "date": today, "summary": "AUTO-COMPACT SNAPSHOT: b", "status": "auto-compact"},
            {"date": today, "summary": "numberless-fresh-snapshot", "status": "auto-compact"},
        ]
        file_path, data = self._setup(ext, mocks, tmp_path, sessions)

        result = ext.extract_items(file_path)

        archived = {e["summary"] for e in result.get("extracted", [])}
        assert "numberless-fresh-snapshot" not in archived
        assert "numberless-fresh-snapshot" in {e["summary"] for e in data["sessions"]}

    def test_regular_session_dated_today_is_still_refused(self, monkeypatch, tmp_path):
        """DPLAN-0278 protection for the regular lane is untouched by the snapshot relaxation."""
        ext, mocks = _import_extractor(monkeypatch)
        today = datetime.now().strftime("%Y-%m-%d")
        sessions = [
            {"number": 4, "date": "2026-01-04", "summary": "regular newest", "status": "completed"},
            {"number": 3, "date": "2026-01-03", "summary": "regular second", "status": "completed"},
            {"number": 9, "date": today, "summary": "AUTO-COMPACT SNAPSHOT: fresh", "status": "auto-compact"},
            {"number": 1, "date": today, "summary": "fresh-write-at-tail", "status": "completed"},
        ]
        file_path, data = self._setup(ext, mocks, tmp_path, sessions, cap=3, count=2)

        result = ext.extract_items(file_path)

        archived = {e["summary"] for e in result.get("extracted", [])}
        assert "fresh-write-at-tail" not in archived
        assert "fresh-write-at-tail" in {e["summary"] for e in data["sessions"]}

    def test_is_misplaced_entry_date_guard_matrix(self, monkeypatch):
        """Pin the helper directly: what each guard mode decides."""
        ext, _ = _import_extractor(monkeypatch)
        today = datetime.now().strftime("%Y-%m-%d")

        fresh_today = {"number": 5, "date": today}
        above_head = {"number": 99, "date": "2020-01-01"}
        numberless = {"date": today}

        # Date guard on (regular lanes) — unchanged behaviour. An unknown
        # head_date reads as "not today", the conservative default.
        assert ext._is_misplaced_entry(fresh_today, 10) is True
        assert ext._is_misplaced_entry(above_head, 10) is True
        assert ext._is_misplaced_entry(numberless, 10) is True

        # ...and a head that is ITSELF dated today makes "dated today" stop
        # separating anything, so ordering decides for entries below it.
        assert ext._is_misplaced_entry(fresh_today, 10, head_date=today) is False
        assert ext._is_misplaced_entry(above_head, 10, head_date=today) is True
        assert ext._is_misplaced_entry(numberless, 10, head_date=today) is True

        # Date guard off (snapshot lane) — ordering decides, date does not
        assert ext._is_misplaced_entry(fresh_today, 10, date_guard=False) is False
        assert ext._is_misplaced_entry(above_head, 10, date_guard=False) is True
        # ...unless ordering cannot decide, then the date rule still protects
        assert ext._is_misplaced_entry(numberless, 10, date_guard=False) is True


class TestARefusedWriteMustNotReadAsASuccessfulRollover:
    """Found live 2026-08-30 against @seedgo's real memory file.

    `write_memory_file` enforces the trinity entry caps and REFUSES the whole
    file when any entry is over — correct behaviour. `_write_memory_file`
    called it and threw the boolean away, so the refusal reached nobody:

      1. rollover extracts 12 key_learnings (in memory)
      2. the write-back is refused, because an UNRELATED array — sessions[0],
         a 343-char summary against a 300 cap — puts the document over
      3. the discarded False means no exception, so the caller's except cannot fire
      4. the orchestrator reads success, old_lines == new_lines, and proceeds
      5. it vectorizes and stores those 12 entries in ChromaDB
      6. the file is untouched, so the next run extracts the SAME 12 and stores
         them AGAIN

    That is not a skip loop, it is a duplicate-vector loop: @seedgo's global
    count climbed every run while their file never moved. A silent write
    failure in an archiver is the one failure mode that must never be silent,
    because the archive keeps accepting what the source never gave up.
    """

    def test_a_refused_write_raises_instead_of_returning_quietly(self, monkeypatch, tmp_path):
        ext, _ = _import_extractor(monkeypatch)
        target = tmp_path / "local.json"
        target.write_text("{}", encoding="utf-8")

        monkeypatch.setattr(ext, "write_memory_file_simple", lambda *a, **k: False)

        with pytest.raises(OSError):
            ext._write_memory_file(target, {"sessions": []})

    def test_a_successful_write_still_returns_quietly(self, monkeypatch, tmp_path):
        ext, _ = _import_extractor(monkeypatch)
        target = tmp_path / "local.json"
        target.write_text("{}", encoding="utf-8")

        monkeypatch.setattr(ext, "write_memory_file_simple", lambda *a, **k: True)

        assert ext._write_memory_file(target, {"sessions": []}) is None

    def test_the_refusal_reaches_the_caller_as_a_failed_extraction(self, monkeypatch, tmp_path):
        """The whole point: a refused write must NOT be reported as archived.

        Without this the orchestrator vectorizes entries the file still holds.
        """
        ext, mocks = _import_extractor(monkeypatch)
        branch_key = tmp_path.name.lower()
        data = {
            "document_metadata": {"schema_version": "3.0.0", "status": {}},
            "sessions": [
                {"number": n, "date": "2026-01-0%d" % (n % 9 + 1), "summary": f"s{n}", "status": "completed"}
                for n in range(6, 0, -1)
            ],
        }
        file_path = tmp_path / ".trinity" / "local.json"
        file_path.parent.mkdir(parents=True)
        file_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

        mocks["config_loader"].section.return_value = {
            "defaults": {},
            "per_branch": {branch_key: {"local": {"sessions": {"count": 2}}}},
        }
        mocks["memory_files"].read_memory_file_data.return_value = data
        monkeypatch.setattr(ext, "write_memory_file_simple", lambda *a, **k: False)

        result = ext.extract_items(file_path)

        assert result["success"] is False
        # A refused write returns the failure and NOTHING ELSE -- no `extracted`
        # key at all, so no caller can read partial work out of a dead run.
        assert sorted(result) == ["error", "success"], sorted(result)


class TestTodayIsNotEvidenceAgainstANumberedEntry:
    """The skip loop the valve's own alarm predicted, met in the wild 2026-08-30.

    @memory wrote 27 key_learnings in one very long day across three sessions.
    Every entry was correctly prepended, strictly newest-first, monotonically
    numbered 135 down to 109 — and every entry was dated today, because it WAS
    today. So all 12 archivable candidates were refused as "fresh writes", the
    file stayed at 27/15, and the detector re-fired on it every single run.
    Three branches were in that state at once (memory, seedgo, daemon).

    The valve's job is catching a fresh write that landed at the WRONG END. The
    number is what says which end an entry is at; the date was only ever a proxy
    for lanes where the number cannot answer. When both numbers are usable and
    the candidate is strictly below the head, ordering has already decided, and
    a proxy that overrules the thing it stands in for is not a safety valve.

    What is deliberately NOT weakened: an entry numbered ABOVE the head is still
    refused (that is the real convention-loss shape — prepend became append, so
    numbers ascend into the tail), and an entry with no usable number on either
    side is still refused on its date, because there ordering genuinely cannot
    decide.
    """

    def test_a_days_worth_of_correctly_ordered_entries_can_drain(self, monkeypatch, caplog):
        ext, _ = _import_extractor(monkeypatch)
        today = datetime.now().strftime("%Y-%m-%d")
        entries = [{"number": n, "date": today} for n in range(135, 108, -1)]
        assert len(entries) == 27

        with caplog.at_level(logging.WARNING):
            archivable = ext._extract_tail_excess(
                entries, 15, entries[0]["number"], "key_learnings", "memory", head_date=today
            )

        assert [e["number"] for e in archivable] == list(range(120, 108, -1))
        assert "NOTHING DRAINED" not in caplog.text

    def test_an_entry_numbered_above_the_head_is_still_refused(self, monkeypatch):
        """The real convention-loss shape survives the narrowing."""
        ext, _ = _import_extractor(monkeypatch)
        today = datetime.now().strftime("%Y-%m-%d")
        entries = [{"number": n, "date": today} for n in range(20, 10, -1)]
        entries.append({"number": 99, "date": today, "why": "prepend became append"})

        archivable = ext._extract_tail_excess(
            entries, 5, entries[0]["number"], "key_learnings", "victim", head_date=today
        )

        assert 99 not in [e["number"] for e in archivable]

    def test_a_tail_entry_numbered_equal_to_the_head_is_still_refused(self, monkeypatch):
        """The `<` in `number < head_number` is load-bearing and nothing pinned it.

        A duplicate of the head sitting at the tail is the one shape ordering
        genuinely cannot separate: it is not above the head, so the
        convention-loss rule misses it, and it is not below the head either, so
        it has no claim to being older. The date rule has to decide, even when
        the head is dated today.

        Caught by a mutant that forced the ordering flag to True — which passed
        the whole suite until this existed.
        """
        ext, _ = _import_extractor(monkeypatch)
        today = datetime.now().strftime("%Y-%m-%d")
        entries = [{"number": n, "date": today} for n in range(20, 10, -1)]
        entries.append({"number": 20, "date": today, "why": "duplicate of the head, at the tail"})

        archivable = ext._extract_tail_excess(
            entries, 5, entries[0]["number"], "key_learnings", "victim", head_date=today
        )

        assert all("why" not in e for e in archivable), archivable

    def test_key_learnings_drain_end_to_end_when_the_whole_array_is_todays(self, monkeypatch, tmp_path):
        """The head_date WIRING, not just the predicate.

        The predicate tests call `_extract_tail_excess` directly and pass
        head_date themselves, so they cannot see whether `_extract_items_v2`
        actually threads it. A mutant passing head_date=None for key_learnings
        survived the entire suite. This drives the real path: @memory's live
        shape on 2026-08-30 — every key_learning correctly ordered, every one
        dated today.
        """
        ext, mocks = _import_extractor(monkeypatch)
        branch_key = tmp_path.name.lower()
        today = datetime.now().strftime("%Y-%m-%d")
        data = {
            "document_metadata": {"schema_version": "3.0.0", "status": {}},
            "key_learnings": [{"number": n, "date": today, "key": f"k{n}", "value": f"v{n}"} for n in range(27, 0, -1)],
        }
        file_path = tmp_path / ".trinity" / "local.json"
        file_path.parent.mkdir(parents=True)
        file_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

        mocks["config_loader"].section.return_value = {
            "defaults": {},
            "per_branch": {branch_key: {"local": {"key_learnings": {"count": 15}}}},
        }
        mocks["memory_files"].read_memory_file_data.return_value = data
        mocks["memory_files"].write_memory_file_simple.return_value = True

        result = ext.extract_items(file_path)

        assert result["success"] is True
        assert result.get("skipped") is not True, "the whole point is that it does NOT skip"
        assert result["extracted_count"] == 12, result.get("extracted_count")
        assert [e["number"] for e in result["extracted"]] == list(range(12, 0, -1))

    def test_a_numberless_entry_dated_today_is_still_refused(self, monkeypatch):
        """Where ordering cannot decide, the date rule is all there is."""
        ext, _ = _import_extractor(monkeypatch)
        today = datetime.now().strftime("%Y-%m-%d")
        entries = [{"number": n, "date": "2020-01-01"} for n in range(20, 10, -1)]
        entries.append({"date": today, "summary": "no number at all"})

        archivable = ext._extract_tail_excess(
            entries, 5, entries[0]["number"], "key_learnings", "victim", head_date=today
        )

        assert all("summary" not in e for e in archivable)


class TestNewestFirstOrderingGuard:
    """Rollover must not trust stored order — the tail is only 'oldest' if the array is newest-first."""

    def test_oldest_first_array_is_reordered_before_archiving(self, monkeypatch, tmp_path):
        """An oldest-first sessions[] must be re-sorted so the newest entry is never archived."""
        ext, mocks = _import_extractor(monkeypatch)
        branch_key = tmp_path.name.lower()

        # Stored OLDEST-first: #1 at head, #4 (newest) at the tail
        data = {
            "document_metadata": {"schema_version": "3.0.0", "status": {}},
            "sessions": [
                {"number": 1, "date": "2026-01-01", "summary": "oldest", "status": "completed"},
                {"number": 2, "date": "2026-01-02", "summary": "second", "status": "completed"},
                {"number": 3, "date": "2026-01-03", "summary": "third", "status": "completed"},
                {"number": 4, "date": "2026-01-04", "summary": "NEWEST", "status": "completed"},
            ],
        }
        file_path = tmp_path / ".trinity" / "local.json"
        file_path.parent.mkdir(parents=True)
        file_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

        mocks["config_loader"].section.return_value = {
            "defaults": {},
            "per_branch": {branch_key: {"local": {"sessions": {"count": 3}}}},
        }
        mocks["memory_files"].read_memory_file_data.return_value = data

        result = ext.extract_items(file_path)

        assert result["success"] is True
        archived = [e["summary"] for e in result["extracted"]]
        # Without the guard the tail (#4 NEWEST) would have been archived
        assert "NEWEST" not in archived
        assert archived == ["oldest"]
        assert [e["number"] for e in data["sessions"]] == [4, 3, 2]

    def test_commons_mixed_order_regression(self, monkeypatch, tmp_path):
        """Regression: newest correctly prepended above an oldest-first legacy block.

        This is the live @commons shape that the safety valve alone could not catch —
        head #16 makes the misordered legacy tail (#13) look like plausible old history.
        """
        ext, mocks = _import_extractor(monkeypatch)
        branch_key = tmp_path.name.lower()

        sessions = [{"number": 16, "date": "2026-08-07", "summary": "newest prepended", "status": "completed"}]
        sessions += [
            {"number": n, "date": "2026-03-28", "summary": f"legacy-{n}", "status": "completed"} for n in range(1, 14)
        ]
        data = {"document_metadata": {"schema_version": "3.0.0", "status": {}}, "sessions": sessions}
        file_path = tmp_path / ".trinity" / "local.json"
        file_path.parent.mkdir(parents=True)
        file_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

        mocks["config_loader"].section.return_value = {
            "defaults": {},
            "per_branch": {branch_key: {"local": {"sessions": {"count": 13}}}},
        }
        mocks["memory_files"].read_memory_file_data.return_value = data

        result = ext.extract_items(file_path)

        assert result["success"] is True
        archived = [e["summary"] for e in result["extracted"]]
        # legacy-13 was the stored tail and would have been eaten as "oldest"
        assert "legacy-13" not in archived
        assert archived == ["legacy-1"]
        assert data["sessions"][0]["number"] == 16
        assert data["sessions"][-1]["number"] == 2

    def test_order_repair_persisted_when_nothing_archived(self, monkeypatch, tmp_path):
        """A reorder with no excess must still be written, or the fault recurs next run."""
        ext, mocks = _import_extractor(monkeypatch)
        branch_key = tmp_path.name.lower()

        data = {
            "document_metadata": {"schema_version": "3.0.0", "status": {}},
            "sessions": [
                {"number": 1, "date": "2026-01-01", "summary": "oldest", "status": "completed"},
                {"number": 2, "date": "2026-01-02", "summary": "newest", "status": "completed"},
            ],
        }
        file_path = tmp_path / ".trinity" / "local.json"
        file_path.parent.mkdir(parents=True)
        file_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

        # count=10 -> nothing exceeds the limit, so nothing is archived
        mocks["config_loader"].section.return_value = {
            "defaults": {},
            "per_branch": {branch_key: {"local": {"sessions": {"count": 10}}}},
        }
        mocks["memory_files"].read_memory_file_data.return_value = data

        writer = mocks["memory_files"].write_memory_file_simple
        writer.reset_mock()

        result = ext.extract_items(file_path)

        assert result["success"] is True
        assert result.get("skipped") is True
        # the repair must be handed to the writer even though nothing was archived
        writer.assert_called_once()
        written_data = writer.call_args[0][1]
        assert [e["number"] for e in written_data["sessions"]] == [2, 1]

    def test_correctly_ordered_array_is_left_untouched(self, monkeypatch, tmp_path):
        """No spurious rewrite when the array is already newest-first."""
        ext, mocks = _import_extractor(monkeypatch)
        branch_key = tmp_path.name.lower()

        data = {
            "document_metadata": {"schema_version": "3.0.0", "status": {}},
            "sessions": [
                {"number": 3, "date": "2026-01-03", "summary": "newest", "status": "completed"},
                {"number": 2, "date": "2026-01-02", "summary": "middle", "status": "completed"},
                {"number": 1, "date": "2026-01-01", "summary": "oldest", "status": "completed"},
            ],
        }
        file_path = tmp_path / ".trinity" / "local.json"
        file_path.parent.mkdir(parents=True)
        file_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

        mocks["config_loader"].section.return_value = {
            "defaults": {},
            "per_branch": {branch_key: {"local": {"sessions": {"count": 10}}}},
        }
        mocks["memory_files"].read_memory_file_data.return_value = data

        writer = mocks["memory_files"].write_memory_file_simple
        writer.reset_mock()

        result = ext.extract_items(file_path)

        assert result["success"] is True
        assert result.get("skipped") is True
        # already correct — no repair write should be issued at all
        writer.assert_not_called()
        assert [e["number"] for e in data["sessions"]] == [3, 2, 1]

    def test_entries_without_numbers_are_not_reordered(self, monkeypatch, tmp_path):
        """Arrays lacking numeric 'number' fields must pass through unchanged."""
        ext, _ = _import_extractor(monkeypatch)
        entries = [{"summary": "a"}, {"summary": "b"}]
        result, repaired = ext._ensure_newest_first(entries, "sessions", "test")
        assert repaired is False
        assert result == entries


# ===========================================================================
# Tests: modules.rollover.run_rollover
# ===========================================================================


class TestRunRollover:
    """Test run_rollover delegates to handler and renders Rich output."""

    def test_returns_true_when_no_triggers(self, monkeypatch):
        rollover, mocks = _import_rollover_module(monkeypatch)
        mocks["orchestrator"].execute_rollover.return_value = {
            "success": True,
            "triggers_count": 0,
            "success_count": 0,
            "failed": [],
            "results": [],
        }
        result = rollover.run_rollover()
        assert result is True

    def test_returns_false_on_handler_exception(self, monkeypatch):
        rollover, mocks = _import_rollover_module(monkeypatch)
        mocks["orchestrator"].execute_rollover.side_effect = RuntimeError("boom")
        result = rollover.run_rollover()
        assert result is False
        mocks["error"].assert_called()

    def test_returns_false_on_error_result(self, monkeypatch):
        rollover, mocks = _import_rollover_module(monkeypatch)
        mocks["orchestrator"].execute_rollover.return_value = {
            "success": False,
            "error": "Registry missing",
            "triggers_count": 0,
        }
        result = rollover.run_rollover()
        assert result is False

    def test_returns_true_with_successful_rollover(self, monkeypatch):
        rollover, mocks = _import_rollover_module(monkeypatch)
        mocks["orchestrator"].execute_rollover.return_value = {
            "success": True,
            "triggers_count": 1,
            "success_count": 1,
            "failed": [],
            "results": [
                {
                    "trigger": "TEST.local.json",
                    "memories_count": 5,
                    "old_lines": 600,
                    "new_lines": 400,
                    "global_collection": "test_col",
                    "global_total": 50,
                    "local_stored": True,
                }
            ],
        }
        result = rollover.run_rollover()
        assert result is True

    def test_displays_failure_details(self, monkeypatch):
        rollover, mocks = _import_rollover_module(monkeypatch)
        mocks["orchestrator"].execute_rollover.return_value = {
            "success": False,
            "triggers_count": 1,
            "success_count": 0,
            "failed": [{"trigger": "BAD.local.json", "stage": "embedding", "error": "model not found"}],
            "results": [],
        }
        rollover.run_rollover()
        mocks["error"].assert_called()

    def test_a_run_where_everything_failed_still_states_its_score(self, monkeypatch):
        """0/1 is a result. Printing nothing lets a total failure read as a quiet run.

        The completion line was gated on `success_count > 0`, so a rollover in
        which every trigger failed ended on a blank line under "Found 1 files
        ready for rollover". The per-failure detail was there, but the run never
        said what it had achieved overall — and "no summary" is the same shape
        on screen as "nothing needed doing".
        """
        rollover, mocks = _import_rollover_module(monkeypatch)
        mocks["orchestrator"].execute_rollover.return_value = {
            "success": False,
            "triggers_count": 3,
            "success_count": 0,
            "failed": [{"trigger": "BAD.local.json", "stage": "extraction", "error": "write refused"}],
            "results": [],
        }

        rollover.run_rollover()

        printed = " ".join(str(c) for c in mocks["console"].print.call_args_list)
        assert "0/3" in printed, printed


# ===========================================================================
# Tests: modules.rollover.show_status
# ===========================================================================


class TestShowStatus:
    """Test show_status calls detector.get_rollover_stats and prints output."""

    def test_displays_error_on_failure(self, monkeypatch):
        rollover, mocks = _import_rollover_module(monkeypatch)
        mocks["detector"].get_rollover_stats.return_value = {
            "success": False,
            "error": "Registry not found",
        }
        rollover.show_status()
        mocks["error"].assert_called()

    def test_displays_v2_branch_details(self, monkeypatch):
        rollover, mocks = _import_rollover_module(monkeypatch)
        mocks["detector"].get_rollover_stats.return_value = {
            "success": True,
            "total_branches": 1,
            "files_checked": 1,
            "files_ready": 1,
            "branches": {
                "V2BRANCH": {
                    "local": {
                        "current": 25,
                        "ready": True,
                        "schema_version": "3.0.0",
                        "v2_reason": "sessions: 25/20",
                    }
                }
            },
        }
        rollover.show_status()
        # Should have printed without error
        mocks["error"].assert_not_called()


# ===========================================================================
# Tests: modules.rollover.check_triggers
# ===========================================================================


class TestCheckTriggers:
    """Test check_triggers calls detector.check_all_branches and prints output."""

    def test_no_triggers_prints_clean(self, monkeypatch):
        rollover, mocks = _import_rollover_module(monkeypatch)
        mocks["detector"].check_all_branches.return_value = {"success": True, "triggers": []}
        rollover.check_triggers()
        mocks["error"].assert_not_called()

    def test_displays_triggers_when_found(self, monkeypatch):
        rollover, mocks = _import_rollover_module(monkeypatch)
        mock_trigger = MagicMock()
        mock_trigger.__str__ = MagicMock(return_value="TEST.local.json (650/600 lines)")
        mocks["detector"].check_all_branches.return_value = {
            "success": True,
            "triggers": [mock_trigger],
        }
        rollover.check_triggers()
        mocks["error"].assert_not_called()

    def test_displays_error_on_failure(self, monkeypatch):
        rollover, mocks = _import_rollover_module(monkeypatch)
        mocks["detector"].check_all_branches.return_value = {
            "success": False,
            "error": "Cannot read registry",
        }
        rollover.check_triggers()
        mocks["error"].assert_called()


# ===========================================================================
# Tests: normalize.normalize_all_memory_files
# ===========================================================================


class TestNormalizeAllMemoryFiles:
    """Test normalize_all_memory_files iterates registry branches."""

    def test_returns_error_when_registry_not_found(self, monkeypatch):
        norm, _ = _import_normalize(monkeypatch)
        with patch.object(norm, "_find_repo_root", return_value=Path("/nonexistent")):
            result = norm.normalize_all_memory_files()
        assert result["success"] is False
        assert "not found" in result["error"]

    def test_normalizes_files_for_existing_branches(self, monkeypatch, tmp_path):
        norm, _ = _import_normalize(monkeypatch)

        # Create registry
        branch_dir = tmp_path / "src" / "aipass" / "test_branch"
        branch_dir.mkdir(parents=True)

        # Create memory file that needs normalization (root-level limits)
        memory_data = {
            "limits": {"max_lines": 600},
            "document_metadata": {"status": {}},
            "sessions": [],
        }
        file_path = branch_dir / "TEST_BRANCH.local.json"
        file_path.write_text(json.dumps(memory_data, indent=2), encoding="utf-8")

        registry = {
            "branches": [
                {"name": "TEST_BRANCH", "path": str(branch_dir)},
            ]
        }
        registry_path = tmp_path / "AIPASS_REGISTRY.json"
        registry_path.write_text(json.dumps(registry), encoding="utf-8")

        with patch.object(norm, "_find_repo_root", return_value=tmp_path):
            result = norm.normalize_all_memory_files()

        assert result["success"] is True
        assert result["files_checked"] >= 1

    def test_skips_branches_with_missing_paths(self, monkeypatch, tmp_path):
        norm, _ = _import_normalize(monkeypatch)

        registry = {
            "branches": [
                {"name": "MISSING", "path": str(tmp_path / "nonexistent")},
            ]
        }
        registry_path = tmp_path / "AIPASS_REGISTRY.json"
        registry_path.write_text(json.dumps(registry), encoding="utf-8")

        with patch.object(norm, "_find_repo_root", return_value=tmp_path):
            result = norm.normalize_all_memory_files()

        assert result["success"] is True
        assert result["files_checked"] == 0

    def test_dry_run_does_not_modify_files(self, monkeypatch, tmp_path):
        norm, _ = _import_normalize(monkeypatch)

        branch_dir = tmp_path / "branch"
        branch_dir.mkdir()

        memory_data = {
            "limits": {"max_lines": 600},
            "document_metadata": {"status": {}},
            "sessions": [],
        }
        file_path = branch_dir / "BRANCH.local.json"
        original_content = json.dumps(memory_data, indent=2)
        file_path.write_text(original_content, encoding="utf-8")

        registry = {"branches": [{"name": "BRANCH", "path": str(branch_dir)}]}
        registry_path = tmp_path / "AIPASS_REGISTRY.json"
        registry_path.write_text(json.dumps(registry), encoding="utf-8")

        with patch.object(norm, "_find_repo_root", return_value=tmp_path):
            result = norm.normalize_all_memory_files(dry_run=True)

        assert result["dry_run"] is True
        # File content should not be changed in dry_run
        assert file_path.read_text(encoding="utf-8") == original_content


# ===========================================================================
# Tests: line_counter.update_all_memory_files
# ===========================================================================


class TestUpdateAllMemoryFiles:
    """Test update_all_memory_files iterates registry branches."""

    def test_returns_empty_when_no_branches(self, monkeypatch):
        lc, _ = _import_line_counter(monkeypatch)

        mock_read_registry = MagicMock(return_value=[])
        mock_get_path = MagicMock(return_value=None)

        with (
            patch(
                "aipass.memory.apps.handlers.monitor.detector._read_registry",
                mock_read_registry,
            ),
            patch(
                "aipass.memory.apps.handlers.monitor.detector._get_memory_file_path",
                mock_get_path,
            ),
        ):
            result = lc.update_all_memory_files()

        assert result["success"] is True
        assert result["updated"] == 0

    def test_updates_existing_files(self, monkeypatch, tmp_path):
        lc, mocks = _import_line_counter(monkeypatch)

        file_path = tmp_path / "local.json"
        file_path.write_text('{\n  "test": true\n}\n', encoding="utf-8")

        branch = {"name": "TEST", "path": str(tmp_path)}

        def mock_get_path(b, mem_type):
            if mem_type == "local":
                return file_path
            return None

        import importlib

        detector = importlib.import_module("aipass.memory.apps.handlers.monitor.detector")
        monkeypatch.setattr(detector, "_read_registry", lambda: [branch])
        monkeypatch.setattr(detector, "_get_memory_file_path", mock_get_path)

        result = lc.update_all_memory_files()

        assert result["success"] is True
        assert result["updated"] >= 1

    def test_tracks_failures(self, monkeypatch, tmp_path):
        lc, _mocks = _import_line_counter(monkeypatch)

        # The old failure injection was a mocked update_metadata write error.
        # That write is gone (health stamping removed 2026-08-25), so the only
        # way update_line_count can fail now is a file that is not there —
        # which is the honest remaining failure mode to track.
        file_path = tmp_path / "local.json"

        branch = {"name": "TEST", "path": str(tmp_path)}

        def mock_get_path(b, mem_type):
            if mem_type == "local":
                return file_path
            return None

        import importlib

        detector = importlib.import_module("aipass.memory.apps.handlers.monitor.detector")
        monkeypatch.setattr(detector, "_read_registry", lambda: [branch])
        monkeypatch.setattr(detector, "_get_memory_file_path", mock_get_path)

        result = lc.update_all_memory_files()

        assert result["success"] is True
        assert result["failed"] >= 1


# ===========================================================================
# The safety valve must not become a runaway log (incident 2026-08-16)
# ===========================================================================


class TestValveLoggingIsBounded:
    """@trigger raised memory_extractor.log CRITICAL at 634 lines/min.

    The valve was correct — it was refusing entries an external branch had
    written at the wrong end of the array — but it logged one WARNING per
    refused entry, each carrying the entire entry (~800 bytes). One rollover
    pass over one file produced 97 warning lines in a single second.

    A refusal is normal and can be routine at scale, so it gets ONE summary
    line per array per run. The per-entry detail drops to DEBUG, where it is
    recoverable while debugging without flooding a routine run.
    """

    @staticmethod
    def _run(entries, limit, head):
        """Substitute the extractor's logger and read the calls off it.

        Neither caplog nor a real logging.Handler works here: the suite runs
        with prax mocked, so `extractor.logger` is not a live Logger and
        addHandler silently does nothing — a capture-based assertion would
        pass vacuously, reading zero emitted lines as zero warnings. Replacing
        the logger measures the calls the code actually made.
        """
        from unittest.mock import MagicMock, patch

        from aipass.memory.apps.handlers.rollover import extractor

        fake = MagicMock()
        with patch.object(extractor, "logger", fake):
            kept = extractor._extract_tail_excess(entries, limit, head, "key_learnings", "victim")

        warnings = [c.args[0] for c in fake.warning.call_args_list]
        debugs = [c.args[0] for c in fake.debug.call_args_list]
        return kept, warnings, debugs

    @staticmethod
    def _misplaced(n):
        """n entries that all trip the valve: dated today, numbered above head."""
        today = datetime.now().strftime("%Y-%m-%d")
        return [{"number": 1000 + i, "date": today, "value": "x" * 800} for i in range(n)]

    def test_one_warning_per_array_not_one_per_entry(self):
        entries = [{"number": 65, "date": "2026-01-01", "value": "head"}] + self._misplaced(96)
        _kept, warnings, _debugs = self._run(entries, 15, 65)
        assert len(warnings) == 1

    def test_the_refused_count_is_in_the_summary(self):
        entries = [{"number": 65, "date": "2026-01-01", "value": "head"}] + self._misplaced(96)
        _kept, warnings, _debugs = self._run(entries, 15, 65)
        assert "82 of 82" in warnings[0]

    def test_per_entry_detail_survives_at_debug(self):
        entries = [{"number": 65, "date": "2026-01-01", "value": "head"}] + self._misplaced(96)
        _kept, _warnings, debugs = self._run(entries, 15, 65)
        assert len(debugs) == 82

    def test_nothing_drained_names_the_skip_loop(self):
        """The alarm worth having: over limit + nothing archivable = the
        detector re-fires on this file forever. It used to be invisible,
        buried in the very wall of lines it produced."""
        entries = [{"number": 65, "date": "2026-01-01", "value": "head"}] + self._misplaced(96)
        _kept, warnings, _debugs = self._run(entries, 15, 65)
        assert "NOTHING DRAINED" in warnings[0]

    def test_a_partial_refusal_is_not_called_a_skip_loop(self):
        """Some drained means the lane still moves — warn, but do not alarm."""
        old = [{"number": 60 - i, "date": "2026-01-01", "value": "old"} for i in range(40)]
        # Misplaced entries at the very END so they land inside the candidate
        # tail alongside genuinely-old ones — the mixed case.
        entries = [{"number": 65, "date": "2026-01-01", "value": "head"}] + old + self._misplaced(5)
        kept, warnings, _debugs = self._run(entries, 15, 65)
        assert kept
        assert len(warnings) == 1
        assert "NOTHING DRAINED" not in warnings[0]

    def test_no_refusals_logs_nothing(self):
        entries = [{"number": 100 - i, "date": "2026-01-01", "value": "v"} for i in range(40)]
        kept, warnings, debugs = self._run(entries, 15, 100)
        assert kept
        assert not warnings
        assert not debugs

    def test_the_valve_still_holds_every_misplaced_entry_back(self):
        """Log volume changed; the protection must not have."""
        entries = [{"number": 65, "date": "2026-01-01", "value": "head"}] + self._misplaced(96)
        kept, _warnings, _debugs = self._run(entries, 15, 65)
        assert kept == []


class TestASkippedTriggerIsNotSilentlyDropped:
    """A trigger counted as neither success nor failure is a hole in the tally.

    Same species as the 0/N silence fixed earlier: the detector says a file is
    ready, the extractor finds nothing to archive, and the loop ``continue``s
    without touching ``success_count`` OR ``failed``. The run then reports
    ``0/1 successful`` with an empty failure list — a number that says something
    went wrong and a list that says nothing did. Whoever reads that output has
    to guess, and the file is left in whatever state the detector objected to.

    The extractor's own skip path can even have WRITTEN the file (a newest-first
    order repair with nothing to archive persists), so "skipped" is not reliably
    "nothing happened" either.
    """

    @staticmethod
    def _trigger(name="guinea.local"):
        trigger = MagicMock()
        setattr(trigger, "__str__", lambda self: name)
        trigger.file_path = Path(tempfile.gettempdir()) / "does-not-matter" / "local.json"
        trigger.branch = "guinea"
        trigger.memory_type = "local"
        return trigger

    def _run_with_skip(self):
        from aipass.memory.apps.handlers.rollover import orchestrator

        with (
            patch.object(
                orchestrator.detector,
                "check_all_branches",
                return_value={"success": True, "triggers": [self._trigger()]},
            ),
            patch.object(
                orchestrator.extractor,
                "create_rollover_backup",
                return_value={"success": True, "message": "backed up"},
            ),
            patch.object(
                orchestrator.extractor,
                "extract_with_metadata",
                return_value={"success": True, "skipped": True, "message": "No entries exceed v2 limits"},
            ),
        ):
            return orchestrator.execute_rollover()

    def test_a_skipped_trigger_is_reported_somewhere(self):
        result = self._run_with_skip()
        accounted = result["success_count"] + len(result["failed"]) + len(result.get("skipped", []))
        assert accounted == result["triggers_count"], (
            f"1 trigger in, {accounted} accounted for: {result['success_count']} succeeded, "
            f"{len(result['failed'])} failed, {len(result.get('skipped', []))} skipped"
        )

    def test_the_skip_carries_the_reason_the_extractor_gave(self):
        skipped = self._run_with_skip().get("skipped", [])
        assert skipped, "the skip must be reported, not dropped"
        assert "exceed" in skipped[0]["reason"], skipped[0]

    def test_a_skipped_trigger_is_not_counted_as_a_success(self):
        """The file was not archived. Calling it a success would be the lie."""
        assert self._run_with_skip()["success_count"] == 0

    def test_a_run_that_only_skipped_did_not_fail(self):
        """Nothing broke — 'nothing to do' is a legitimate outcome, just a named one."""
        assert self._run_with_skip()["success"] is True


class TestASkippedTriggerIsVisibleOnScreen:
    """The handler counting it is only half — the operator has to be able to read it."""

    def test_the_skip_and_its_reason_are_printed(self, monkeypatch):
        rollover, mocks = _import_rollover_module(monkeypatch)
        mocks["orchestrator"].execute_rollover.return_value = {
            "success": True,
            "triggers_count": 1,
            "success_count": 0,
            "failed": [],
            "skipped": [{"trigger": "guinea.local (16/15 sessions)", "reason": "No entries exceed v2 limits"}],
            "results": [],
        }

        rollover.run_rollover()

        printed = " ".join(str(c) for c in mocks["console"].print.call_args_list)
        assert "0/1" in printed, printed
        assert "guinea.local" in printed and "skipped" in printed, printed

    def test_a_run_with_no_skips_prints_no_skip_line(self, monkeypatch):
        """The absence of a category must not print an empty heading."""
        rollover, mocks = _import_rollover_module(monkeypatch)
        mocks["orchestrator"].execute_rollover.return_value = {
            "success": True,
            "triggers_count": 1,
            "success_count": 1,
            "failed": [],
            "skipped": [],
            "results": [],
        }

        rollover.run_rollover()

        assert "skipped" not in " ".join(str(c) for c in mocks["console"].print.call_args_list)


# ===========================================================================
# THE LANE AGAINST THE REAL WRITE GATE (2026-08-30)
# ===========================================================================
#
# Every test above imports the extractor with `memory_files` MOCKED — correct
# for testing extraction logic, and blind to the one thing that actually took
# this lane down.
#
# On 2026-08-30 the cap gate refused rollover's write for an entry in the head
# it never touched, and the lane re-failed identically every 20 minutes for
# three hours against @seedgo's real file. When the rule was fixed, restoring
# the defect as a mutant killed exactly three tests — all of them in
# test_changed_entries.py, at the WRITER. Not one rollover test died. The suite
# for the lane that broke could not see what broke it, because it mocks the
# component that refused.
#
# @hooks found the mirror image of this in their own tree the same evening: a
# mutant that made their checker return NOTHING left all 115 of their
# end-to-end tests green, because the union ran @memory's real diff. When two
# halves overlap, a suite that cannot tell them apart proves neither.
#
# So this class mocks NOTHING below the extractor. Real memory_files, real
# entry_limits, real caps, a real file on disk — and it asserts on what is
# actually written, because "success" is what the lane reported for three
# hours while the file never changed.


class TestRolloverSurvivesCarriedDebt:
    """The live deadlock, driven through the extractor against the real writer."""

    @pytest.fixture
    def ext(self, monkeypatch):
        """The extractor with its REAL dependencies — the point of this class.

        `_import_extractor` above leaves a cached extractor module bound to a
        MagicMock `memory_files`, and that binding outlives the monkeypatch
        that created it: restoring sys.modules does not re-bind names already
        imported into a cached module. Without this eviction these tests pass
        alone and fail in the suite, reading `read_memory_file_data` as a mock
        returning None.

        Evicted with `monkeypatch.delitem`, never a bare `sys.modules.pop` — a
        bare pop is one-way and outlives the test, which is how two receipt
        tests went red on a single xdist worker in session 163.
        """
        for name in (
            "aipass.memory.apps.handlers.json",
            "aipass.memory.apps.handlers.json.json_handler",
            "aipass.memory.apps.handlers.json.config_loader",
            "aipass.memory.apps.handlers.json.entry_limits",
            "aipass.memory.apps.handlers.json.memory_files",
            "aipass.memory.apps.handlers.rollover.extractor",
        ):
            monkeypatch.delitem(sys.modules, name, raising=False)
        parent = sys.modules.get("aipass.memory.apps.handlers.rollover")
        if parent is not None and hasattr(parent, "extractor"):
            monkeypatch.delattr(parent, "extractor", raising=False)

        from aipass.memory.apps.handlers.rollover import extractor

        # Prove the real writer is wired, not a mock. A test class whose whole
        # purpose is "run against the real gate" must not silently run against
        # a double.
        assert isinstance(extractor.write_memory_file_simple, types.FunctionType), (
            "extractor is bound to a mocked writer — this class would prove nothing"
        )
        return extractor

    @staticmethod
    def _seedgo_shaped_file(tmp_path):
        """A file over its session count, carrying one over-cap summary in the HEAD.

        The 343-char summary is @seedgo's real shape. It sits at the top, where
        rollover archives from the BOTTOM — so the lane can never shrink it,
        and a gate that refuses the document for it can never be satisfied.
        """
        trinity = tmp_path / "standin" / ".trinity"
        trinity.mkdir(parents=True)
        file_path = trinity / "local.json"
        data = {
            "document_metadata": {
                "document_type": "session_history",
                "document_name": "standin.LOCAL",
                "version": "2.0.0",
                "schema_version": "3.0.0",
            },
            "sessions": [{"number": 20, "date": "2026-08-30", "summary": "X" * 343}]
            + [{"number": n, "date": "2026-08-29", "summary": f"session {n}"} for n in range(19, 0, -1)],
        }
        file_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return file_path

    def test_entries_actually_leave_the_file(self, ext, tmp_path):
        """Not "reported success" — MEASURED on disk, which is where the lie was."""
        file_path = self._seedgo_shaped_file(tmp_path)
        before_count = len(json.loads(file_path.read_text(encoding="utf-8"))["sessions"])

        result = ext.extract_items(file_path)

        assert result["success"] is True, result.get("error")
        after = json.loads(file_path.read_text(encoding="utf-8"))["sessions"]
        assert len(after) < before_count, "the lane reported success and the file never shrank"
        assert result["extracted_count"] == before_count - len(after), (
            "extracted count disagrees with what left the file — the 3-hour lie exactly"
        )

    def test_the_carried_entry_is_still_there_and_still_over_cap(self, ext, tmp_path):
        """Rollover must not 'fix' the fat entry — it is not rollover's to touch.

        The cure for a carried entry is its own agent trimming it, or the entry
        ageing into the tail and being archived whole. A shrink lane that
        started editing text to satisfy a cap would be authoring memories.
        """
        file_path = self._seedgo_shaped_file(tmp_path)
        result = ext.extract_items(file_path)

        # Assert the run DID something first. A refused write leaves the file
        # untouched, so "the fat entry is still there" would pass on a run that
        # archived nothing — the test would be green about a dead lane.
        assert result["success"] is True, result.get("error")
        assert result["extracted_count"] > 0, "nothing was archived — this pin would pass vacuously"

        head = json.loads(file_path.read_text(encoding="utf-8"))["sessions"][0]
        assert head["summary"] == "X" * 343, "rollover edited an entry it only moves past"

    def test_a_second_run_is_not_re_archiving_the_same_entries(self, ext, tmp_path):
        """The duplicate-work loop the refusal caused, pinned from the outside.

        While the write was refused the file never changed, so every run
        extracted and vectorised the same entries again. If the file shrinks,
        the second run has strictly less to do.
        """
        file_path = self._seedgo_shaped_file(tmp_path)
        first = ext.extract_items(file_path)
        second = ext.extract_items(file_path)

        assert first["extracted_count"] > 0
        assert second.get("extracted_count", 0) < first["extracted_count"], (
            "the second run extracted as much as the first — the file did not shrink"
        )


# ===========================================================================
# Tests: rollover/todo_roll -- the todo pad rolls to a FILE (DPLAN-0345 row 1)
# ===========================================================================
#
# Behavioural, on tmp_path copies: a minted pad, a throwaway config naming the
# count, and a .backup root under tmp_path. The live tree's pads and the real
# .backup/todo/ are never reachable from here.


def _todo_roll():
    """The real todo_roll handler (the harnesses above stand mocks in per test only)."""
    import importlib

    return importlib.import_module("aipass.memory.apps.handlers.rollover.todo_roll")


def _canon(value) -> str:
    """JSON equality as text: key order ignored, 1 / 1.0 / true kept distinct."""
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _todo(number, task=None, **extra) -> dict:
    """One todo in the pad's shape."""
    todo = {"number": number, "task": task or f"task {number}", "date": "2026-09-01", "priority": "normal"}
    todo.update(extra)
    return todo


def _todo_cap(module) -> int:
    """The live cap on a todo's task, read from the config the gate reads.

    Never a literal: the number moved once already (150 -> 100) and a test
    carrying its own copy would pin the cap that WAS, then pass while the
    refusal it claims to measure stopped matching.
    """
    limits = module.load_entry_limits("guinea")
    return int(limits["entry_types"]["todos"]["max_chars"])


def _mint_pad(root: Path, todos: list, name: str = "guinea") -> Path:
    """A branch directory under *root* whose local memory file holds *todos*; returns that file."""
    local = root / name / ".trinity" / "local.json"
    local.parent.mkdir(parents=True, exist_ok=True)
    document = {"document_metadata": {"document_type": "session_history"}, "sessions": [], "todos": todos}
    local.write_text(json.dumps(document, indent=2), encoding="utf-8")
    return local


def _backlog_file(tmp_path: Path, name: str = "guinea") -> Path:
    """Where the backlog lands under the tmp .backup root."""
    return tmp_path / ".backup" / "todo" / name / "backlog.json"


def _point_todos_count(monkeypatch, tmp_path: Path, tr, count: int) -> None:
    """Give the handler a throwaway config whose todos count is *count*."""
    import copy
    import importlib

    loader = importlib.import_module("aipass.memory.apps.handlers.json.config_loader")
    config = copy.deepcopy(loader.DEFAULT_CONFIG)
    config["rollover"]["defaults"]["local"]["todos"] = {"count": count}
    config["rollover"]["per_branch"] = {}
    path = tmp_path / "custom_config" / "memory.config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    monkeypatch.setattr(loader, "_CONFIG_PATH", path)
    monkeypatch.setattr(tr, "config_loader", loader)


def _scratch_backlogs(tmp_path: Path, monkeypatch) -> None:
    """No pin may reach the repo's real .backup/todo/: an unrouted backlog lands under tmp_path."""
    tr = _todo_roll()
    real = tr.backlog_path_for

    def scratch(branch_dir, backup_root=None):
        return real(branch_dir, tmp_path / ".backup" if backup_root is None else backup_root)

    monkeypatch.setattr(tr, "backlog_path_for", scratch)


def _tab(next_label) -> str:
    """A todos_meta line exactly as memory's renderer writes it for @guinea (count 10, task cap 100)."""
    return (
        "⟦ pad of 10 · oldest roll to .backup/todo/guinea/backlog.json · task ≤100 chars · draft to 80"
        f" · next #{next_label} ⟧ One line of what to do."
    )


class TestTodoRoll:
    """roll_todos: append -> atomic replace -> read back -> only then prune the pad."""

    @pytest.fixture(autouse=True)
    def _backlogs_stay_in_tmp(self, tmp_path, monkeypatch):
        _scratch_backlogs(tmp_path, monkeypatch)

    @pytest.fixture
    def tr(self, tmp_path, monkeypatch):
        module = _todo_roll()
        _point_todos_count(monkeypatch, tmp_path, module, 10)
        return module

    @staticmethod
    def _roll(tr, local: Path, tmp_path: Path) -> dict:
        return tr.roll_todos("guinea", local_path=local, backup_root=tmp_path / ".backup")

    def test_the_oldest_by_number_roll_off_and_the_rest_keep_their_order(self, tr, tmp_path):
        order = [7, 1, 12, 3, 9, 2, 11, 5, 10, 4, 8, 6]
        local = _mint_pad(tmp_path, [_todo(n) for n in order])

        result = self._roll(tr, local, tmp_path)

        assert result["success"] is True, result["error"]
        assert result["numbers"] == [1, 2]
        assert [t["number"] for t in json.loads(local.read_text(encoding="utf-8"))["todos"]] == [
            n for n in order if n not in (1, 2)
        ]
        entries = json.loads(_backlog_file(tmp_path).read_text(encoding="utf-8"))["entries"]
        assert [record["entry"]["number"] for record in entries] == [1, 2]

    def test_the_backlog_is_the_nested_document(self, tr, tmp_path):
        local = _mint_pad(tmp_path, [_todo(n) for n in range(1, 13)])
        self._roll(tr, local, tmp_path)

        document = json.loads(_backlog_file(tmp_path).read_text(encoding="utf-8"))
        assert set(document) == {"document_metadata", "entries"}
        assert document["document_metadata"] == {"managed_by": "memory", "branch": "guinea", "high_water": 12}, (
            "high_water is the highest number on the WHOLE pad as found (the kept #12), not only the rolled #1, #2"
        )
        assert len(document["entries"]) == 2
        for record in document["entries"]:
            assert set(record) == {"rolled", "reason", "entry"}
            assert record["reason"] == "overflow"
            assert datetime.fromisoformat(record["rolled"]).tzinfo is not None

    def test_a_rolled_todo_is_json_identical_to_the_pad_copy(self, tr, tmp_path):
        odd = _todo(
            1, task="café ≤ naïve — “quoted”", tags=["a", "b"], meta={"weight": 1.0, "flag": True, "gone": None}
        )
        local = _mint_pad(tmp_path, [odd] + [_todo(n) for n in range(2, 13)])
        on_the_pad = json.loads(local.read_text(encoding="utf-8"))["todos"][0]

        self._roll(tr, local, tmp_path)

        entry = json.loads(_backlog_file(tmp_path).read_text(encoding="utf-8"))["entries"][0]["entry"]
        assert _canon(entry) == _canon(on_the_pad)

    def test_a_second_roll_appends_and_never_overwrites(self, tr, tmp_path):
        local = _mint_pad(tmp_path, [_todo(n) for n in range(1, 13)])
        self._roll(tr, local, tmp_path)
        first = json.loads(_backlog_file(tmp_path).read_text(encoding="utf-8"))["entries"]

        document = json.loads(local.read_text(encoding="utf-8"))
        document["todos"] += [_todo(n) for n in (13, 14, 15)]
        local.write_text(json.dumps(document, indent=2), encoding="utf-8")
        result = self._roll(tr, local, tmp_path)

        entries = json.loads(_backlog_file(tmp_path).read_text(encoding="utf-8"))["entries"]
        assert result["numbers"] == [3, 4, 5]
        assert entries[:2] == first, "the records already in the backlog were rewritten"
        assert [record["entry"]["number"] for record in entries] == [1, 2, 3, 4, 5]

    def test_a_backlog_that_reads_back_wrong_leaves_the_pad_untouched(self, tr, tmp_path, monkeypatch):
        """THE ORDER: the pad is pruned only after the backlog reads back json-equal."""
        local = _mint_pad(tmp_path, [_todo(n) for n in range(1, 13)])
        before = local.read_bytes()
        real_write = tr._write_document

        def tampering_write(path, document):
            if Path(path).name == "backlog.json":
                document = json.loads(json.dumps(document))
                document["entries"][-1]["entry"]["task"] = "silently changed on the way to disk"
            return real_write(path, document)

        monkeypatch.setattr(tr, "_write_document", tampering_write)
        result = self._roll(tr, local, tmp_path)

        assert result["success"] is False
        assert result["error"].startswith("NOTHING PRUNED - backlog read-back failed"), result["error"]
        assert local.read_bytes() == before

    def test_a_refused_backlog_write_leaves_the_pad_untouched(self, tr, tmp_path, monkeypatch):
        local = _mint_pad(tmp_path, [_todo(n) for n in range(1, 13)])
        before = local.read_bytes()
        real_write = tr._write_document
        monkeypatch.setattr(
            tr,
            "_write_document",
            lambda path, document: "disk full" if Path(path).name == "backlog.json" else real_write(path, document),
        )

        result = self._roll(tr, local, tmp_path)

        assert result["success"] is False
        assert "NOTHING PRUNED" in result["error"] and "disk full" in result["error"]
        assert local.read_bytes() == before

    def test_an_unreadable_backlog_is_refused_and_never_written_over(self, tr, tmp_path):
        local = _mint_pad(tmp_path, [_todo(n) for n in range(1, 13)])
        before = local.read_bytes()
        backlog = _backlog_file(tmp_path)
        backlog.parent.mkdir(parents=True)
        backlog.write_text("{not json", encoding="utf-8")

        result = self._roll(tr, local, tmp_path)

        assert result["success"] is False
        assert "never written over" in result["error"]
        assert backlog.read_text(encoding="utf-8") == "{not json"
        assert local.read_bytes() == before

    def test_a_pad_within_its_count_writes_nothing(self, tr, tmp_path):
        local = _mint_pad(tmp_path, [_todo(n) for n in range(1, 11)])
        before = local.read_bytes()

        result = self._roll(tr, local, tmp_path)

        assert result["success"] is True and result["rolled"] == 0
        assert local.read_bytes() == before
        assert not (tmp_path / ".backup").exists()

    def test_the_count_comes_from_config(self, tr, tmp_path, monkeypatch):
        _point_todos_count(monkeypatch, tmp_path, tr, 4)
        local = _mint_pad(tmp_path, [_todo(n) for n in range(1, 7)])

        result = self._roll(tr, local, tmp_path)

        assert result["count"] == 4
        assert result["numbers"] == [1, 2]

    def test_high_water_is_raised_never_lowered_and_an_old_backlog_still_takes_a_roll(self, tr, tmp_path):
        """A backlog written before high_water existed has no floor, never an error; the roll stamps one."""
        backlog = _backlog_file(tmp_path)
        backlog.parent.mkdir(parents=True)
        earlier = {"rolled": "2026-09-14T23:00:00+00:00", "reason": "overflow", "entry": _todo(1)}
        backlog.write_text(
            json.dumps({"document_metadata": {"managed_by": "memory", "branch": "guinea"}, "entries": [earlier]}),
            encoding="utf-8",
        )
        local = _mint_pad(tmp_path, [_todo(n) for n in range(13, 1, -1)])

        first = self._roll(tr, local, tmp_path)

        assert first["success"] is True, first["error"]
        assert tr.high_water_of(tr.read_backlog(backlog)["document"]) == 13

        document = json.loads(backlog.read_text(encoding="utf-8"))
        document["document_metadata"]["high_water"] = 99
        backlog.write_text(json.dumps(document), encoding="utf-8")
        pad = json.loads(local.read_text(encoding="utf-8"))
        pad["todos"] = [_todo(n) for n in (16, 15, 14)] + pad["todos"]
        local.write_text(json.dumps(pad), encoding="utf-8")

        second = self._roll(tr, local, tmp_path)

        assert second["success"] is True, second["error"]
        back = tr.read_backlog(backlog)
        assert tr.high_water_of(back["document"]) == 99, "a roll never lowers high_water"
        assert [record["entry"]["number"] for record in back["entries"]] == [1, 2, 3, 4, 5, 6]

    def test_a_high_water_that_reads_back_wrong_leaves_the_pad_untouched(self, tr, tmp_path, monkeypatch):
        """high_water is read back like every record: a drifted floor prunes nothing."""
        local = _mint_pad(tmp_path, [_todo(n) for n in range(12, 0, -1)])
        before = local.read_bytes()
        real_write = tr._write_document

        def tampering_write(path, document):
            if Path(path).name == "backlog.json":
                document = json.loads(json.dumps(document))
                document["document_metadata"]["high_water"] = 3
            return real_write(path, document)

        monkeypatch.setattr(tr, "_write_document", tampering_write)
        result = self._roll(tr, local, tmp_path)

        assert result["success"] is False
        assert result["error"].startswith("NOTHING PRUNED - backlog read-back failed"), result["error"]
        assert "document_metadata (high_water) does not read back as written" in result["error"]
        assert local.read_bytes() == before


class TestTodoTarget:
    """ONE branch, keyed by directory name, from --branch or where the caller stood."""

    @staticmethod
    def _fleet(tmp_path: Path) -> list:
        return [
            {"name": "guinea", "path": str(tmp_path / "src" / "aipass" / "guinea"), "residency": "core"},
            {"name": "pig", "path": str(tmp_path / "projects" / "farm" / "pig"), "residency": "resident"},
        ]

    def test_a_directory_name_shared_by_core_and_resident_is_refused_by_name(self, tmp_path):
        tr = _todo_roll()
        twin = tmp_path / "projects" / "guinea" / "guinea"
        fleet = self._fleet(tmp_path) + [{"name": "guinea", "path": str(twin), "residency": "resident"}]
        local = _mint_pad(tmp_path / "src" / "aipass", [_todo(n) for n in range(1, 13)])
        before = local.read_bytes()

        target = tr.resolve_target("@guinea", fleet=fleet, backup_root=tmp_path / ".backup")
        result = tr.roll_todos("guinea", fleet=fleet, backup_root=tmp_path / ".backup")

        assert target["name"] is None
        assert "REFUSED: directory name 'guinea' is shared by 2 branches" in target["error"]
        assert f"core at {tmp_path / 'src' / 'aipass' / 'guinea'}" in target["error"]
        assert f"resident at {twin}" in target["error"]
        assert result["success"] is False and "REFUSED" in result["error"]
        assert local.read_bytes() == before
        assert not (tmp_path / ".backup").exists()

    def test_the_backlog_is_keyed_by_directory_name(self, tmp_path):
        tr = _todo_roll()
        target = tr.resolve_target("@GUINEA", fleet=self._fleet(tmp_path), backup_root=tmp_path / ".backup")

        assert target["name"] == "guinea"
        assert target["backlog"] == _backlog_file(tmp_path, "guinea")
        assert target["local"] == tmp_path / "src" / "aipass" / "guinea" / ".trinity" / "local.json"

    def test_the_caller_cwd_resolves_the_branch_it_stands_in(self, tmp_path):
        tr = _todo_roll()
        where = tmp_path / "projects" / "farm" / "pig" / "apps" / "modules"

        target = tr.resolve_target(fleet=self._fleet(tmp_path), environ={"AIPASS_CALLER_CWD": str(where)})

        assert target["name"] == "pig"

    def test_the_repo_root_resolves_no_branch(self, tmp_path):
        tr = _todo_roll()

        target = tr.resolve_target(fleet=self._fleet(tmp_path), environ={"AIPASS_CALLER_CWD": str(tmp_path)})

        assert target["name"] is None and target["error"] is None
        assert "is not inside a registered branch directory" in target["reason"]

    def test_a_branch_name_without_a_caller_cwd_is_no_evidence(self, tmp_path, monkeypatch):
        """Drone runs @memory from memory's own directory: that cwd says nothing about the caller."""
        tr = _todo_roll()
        branch = tmp_path / "src" / "aipass" / "guinea"
        branch.mkdir(parents=True)
        monkeypatch.chdir(branch)

        launched = tr.resolve_target(fleet=self._fleet(tmp_path), environ={"AIPASS_BRANCH_NAME": "memory"})
        bare = tr.resolve_target(fleet=self._fleet(tmp_path), environ={})

        assert launched["name"] is None
        assert "AIPASS_BRANCH_NAME is set without AIPASS_CALLER_CWD" in launched["reason"]
        assert bare["name"] == "guinea", "with no launcher at all, the process cwd is the caller's"


def _point_backlog_ceiling(monkeypatch, tmp_path: Path, tr, ceiling) -> None:
    """Rewrite the throwaway config's ``rollover.backlog.max_records`` in place.

    Layered on top of :func:`_point_todos_count`, which already repointed the
    loader at this file. Written rather than monkeypatched onto the accessor so
    the pins measure the CONFIG READ too — a ceiling the loader would not serve
    is a ceiling the fleet does not have. ``config_loader.load`` reads from disk
    on every call, so rewriting the file is the whole update.
    """
    del tr  # the loader is repointed by _point_todos_count; kept for call-site symmetry
    path = tmp_path / "custom_config" / "memory.config.json"
    config = json.loads(path.read_text(encoding="utf-8"))
    if ceiling is None:
        config["rollover"].pop("backlog", None)
    else:
        config["rollover"]["backlog"] = {"max_records": ceiling}
    path.write_text(json.dumps(config, indent=2), encoding="utf-8")


class TestTheBacklogTrim:
    """A backlog past its ceiling moves its oldest records to a SIBLING archive.

    The trim exists because nothing bounded the file: @seedgo sat at 72 records
    and would have crossed 100 on its own. What it may not do is drop anything.
    A backlog is the only copy of a rolled todo — never vectorised, by this
    branch's own ruling — so "trim" here means move deeper, never delete, and
    these pins are mostly about the records that leave the working file still
    existing afterwards.
    """

    @pytest.fixture(autouse=True)
    def _backlogs_stay_in_tmp(self, tmp_path, monkeypatch):
        _scratch_backlogs(tmp_path, monkeypatch)

    @pytest.fixture
    def tr(self, tmp_path, monkeypatch):
        module = _todo_roll()
        _point_todos_count(monkeypatch, tmp_path, module, 10)
        return module

    @staticmethod
    def _backlog_of(tmp_path: Path, count: int, start: int = 1) -> Path:
        path = _backlog_file(tmp_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        records = [
            {"rolled": f"2026-09-01T10:00:{index % 60:02d}+00:00", "reason": "overflow", "entry": _todo(index)}
            for index in range(start, start + count)
        ]
        document = {
            "document_metadata": {"managed_by": "memory", "branch": "guinea", "high_water": start + count - 1},
            "entries": records,
        }
        path.write_text(json.dumps(document, indent=2), encoding="utf-8")
        return path

    @staticmethod
    def _numbers(path: Path) -> list:
        if not path.exists():
            return []
        return [record["entry"]["number"] for record in json.loads(path.read_text(encoding="utf-8"))["entries"]]

    def test_a_backlog_within_its_ceiling_is_not_touched(self, tr, tmp_path):
        backlog = self._backlog_of(tmp_path, 5)
        before = backlog.read_bytes()

        result = tr.trim_backlog(backlog, "guinea", ceiling=10)

        assert result["success"] is True
        assert result["archived"] == 0
        assert backlog.read_bytes() == before
        assert not tr.archive_path_for(backlog).exists(), "an archive was created with nothing to put in it"

    def test_a_backlog_exactly_at_its_ceiling_is_not_touched(self, tr, tmp_path):
        backlog = self._backlog_of(tmp_path, 10)

        assert tr.trim_backlog(backlog, "guinea", ceiling=10)["archived"] == 0
        assert len(self._numbers(backlog)) == 10

    def test_the_oldest_records_move_to_the_sibling_archive_and_none_is_lost(self, tr, tmp_path):
        # The whole contract in one measurement: what left the backlog is in
        # the archive, in order, and the two files together still hold all 14.
        backlog = self._backlog_of(tmp_path, 14)

        result = tr.trim_backlog(backlog, "guinea", ceiling=10)

        assert result["success"] is True, result["error"]
        assert result["archived"] == 4
        assert self._numbers(backlog) == [5, 6, 7, 8, 9, 10, 11, 12, 13, 14]
        assert self._numbers(tr.archive_path_for(backlog)) == [1, 2, 3, 4]

    def test_an_archived_record_is_carried_json_equal_not_reshaped(self, tr, tmp_path):
        backlog = self._backlog_of(tmp_path, 12)
        original = json.loads(backlog.read_text(encoding="utf-8"))["entries"][0]

        tr.trim_backlog(backlog, "guinea", ceiling=10)

        archived = json.loads(tr.archive_path_for(backlog).read_text(encoding="utf-8"))["entries"][0]
        assert archived == original, "the archive rewrote the record on its way in"

    def test_the_archive_is_verified_before_the_backlog_is_shortened(self, tr, tmp_path, monkeypatch):
        # Same order as the roll, for the same reason: a record may sit in both
        # files for an instant, and must never sit in neither.
        backlog = self._backlog_of(tmp_path, 12)
        writes = []
        real_write = tr._write_document
        monkeypatch.setattr(
            tr, "_write_document", lambda path, doc: writes.append(Path(path).name) or real_write(path, doc)
        )

        tr.trim_backlog(backlog, "guinea", ceiling=10)

        assert writes == ["backlog.archive.json", "backlog.json"]

    def test_an_archive_that_does_not_land_leaves_the_backlog_whole(self, tr, tmp_path, monkeypatch):
        backlog = self._backlog_of(tmp_path, 12)
        before = backlog.read_bytes()
        real_write = tr._write_document
        monkeypatch.setattr(
            tr,
            "_write_document",
            lambda path, doc: "disk full" if Path(path).name == "backlog.archive.json" else real_write(path, doc),
        )

        result = tr.trim_backlog(backlog, "guinea", ceiling=10)

        assert result["success"] is False
        assert "NOTHING TRIMMED" in result["error"]
        assert backlog.read_bytes() == before, "records left the backlog with nowhere to go"

    def test_high_water_survives_a_trim_so_a_number_is_never_re_issued(self, tr, tmp_path):
        # The archive is unreachable from `todo restore`, so the floor that
        # stops #1 being minted twice has to outlive the record itself.
        backlog = self._backlog_of(tmp_path, 12)

        tr.trim_backlog(backlog, "guinea", ceiling=10)

        document = json.loads(backlog.read_text(encoding="utf-8"))
        assert tr.high_water_of(document) == 12

    def test_a_second_trim_appends_to_the_archive_rather_than_replacing_it(self, tr, tmp_path):
        backlog = self._backlog_of(tmp_path, 12)
        tr.trim_backlog(backlog, "guinea", ceiling=10)
        self._backlog_of(tmp_path, 12, start=13)

        tr.trim_backlog(backlog, "guinea", ceiling=10)

        assert self._numbers(tr.archive_path_for(backlog)) == [1, 2, 13, 14]

    def test_an_archive_belonging_to_another_branch_is_refused(self, tr, tmp_path):
        backlog = self._backlog_of(tmp_path, 12)
        archive = tr.archive_path_for(backlog)
        archive.write_text(
            json.dumps({"document_metadata": {"managed_by": "memory", "branch": "elsewhere"}, "entries": []}),
            encoding="utf-8",
        )

        result = tr.trim_backlog(backlog, "guinea", ceiling=10)

        assert result["success"] is False
        assert "belongs to 'elsewhere'" in result["error"]
        assert len(self._numbers(backlog)) == 12

    def test_the_ceiling_is_read_from_the_config_when_none_is_passed(self, tr, tmp_path, monkeypatch):
        # The CONTROL for the parametrized guard below. Without it those cases
        # would pass vacuously: 12 records sit under the shipped ceiling of
        # 100, so "no trim happened" proves nothing unless a good value in the
        # same file is first shown to trim.
        backlog = self._backlog_of(tmp_path, 12)
        _point_backlog_ceiling(monkeypatch, tmp_path, tr, 10)

        result = tr.trim_backlog(backlog, "guinea")

        assert result["archived"] == 2, result["error"]
        assert self._numbers(tr.archive_path_for(backlog)) == [1, 2]

    @pytest.mark.parametrize("ceiling", [None, 0, -3, "100", True])
    def test_an_unusable_ceiling_means_no_trim_never_a_trim_to_zero(self, tr, tmp_path, monkeypatch, ceiling):
        # The failure mode of this number is "the file stays long", never
        # "the last copy is gone". A config that lost the key must not be read
        # as a ceiling of nothing.
        backlog = self._backlog_of(tmp_path, 12)
        _point_backlog_ceiling(monkeypatch, tmp_path, tr, ceiling)

        result = tr.trim_backlog(backlog, "guinea")

        assert result["archived"] == 0
        assert len(self._numbers(backlog)) == 12
        assert not tr.archive_path_for(backlog).exists()

    def test_a_missing_backlog_is_a_state_not_an_error(self, tr, tmp_path):
        result = tr.trim_backlog(_backlog_file(tmp_path), "guinea", ceiling=10)

        assert result["success"] is True
        assert result["archived"] == 0

    def test_the_roll_trims_on_its_way_past(self, tr, tmp_path, monkeypatch):
        # The trim hangs off append_to_backlog, the one choke point both the
        # roll and the push go through, so it fires at the moment the file
        # grows rather than on a sweep nobody runs.
        _point_backlog_ceiling(monkeypatch, tmp_path, tr, 10)
        self._backlog_of(tmp_path, 10)
        local = _mint_pad(tmp_path, [_todo(n) for n in range(20, 33)])

        result = tr.roll_todos("guinea", local_path=local, backup_root=tmp_path / ".backup")

        assert result["success"] is True, result["error"]
        assert len(self._numbers(_backlog_file(tmp_path))) == 10, "the backlog grew past its ceiling"
        assert self._numbers(tr.archive_path_for(_backlog_file(tmp_path))) == [1, 2, 3]

    def test_a_failed_trim_never_fails_the_append(self, tr, tmp_path, monkeypatch):
        # By the time the trim runs the records are safely on disk and the
        # caller is about to prune the pad on the strength of that. A trim
        # that could veto the append would strand open work on a full pad.
        _point_backlog_ceiling(monkeypatch, tmp_path, tr, 10)
        self._backlog_of(tmp_path, 10)
        monkeypatch.setattr(tr, "trim_backlog", lambda *a, **k: {"success": False, "archived": 0, "error": "boom"})
        local = _mint_pad(tmp_path, [_todo(n) for n in range(20, 33)])

        result = tr.roll_todos("guinea", local_path=local, backup_root=tmp_path / ".backup")

        assert result["success"] is True, result["error"]
        assert [t["number"] for t in json.loads(local.read_text(encoding="utf-8"))["todos"]] == list(range(23, 33))


class TestTodoRestore:
    """restore_todo: pad first, then the backlog - never in neither place."""

    @pytest.fixture(autouse=True)
    def _backlogs_stay_in_tmp(self, tmp_path, monkeypatch):
        _scratch_backlogs(tmp_path, monkeypatch)

    @pytest.fixture
    def tr(self, tmp_path, monkeypatch):
        module = _todo_roll()
        _point_todos_count(monkeypatch, tmp_path, module, 10)
        return module

    @staticmethod
    def _backlog_with(tmp_path: Path, records: list) -> Path:
        path = _backlog_file(tmp_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        document = {"document_metadata": {"managed_by": "memory", "branch": "guinea"}, "entries": records}
        path.write_text(json.dumps(document, indent=2), encoding="utf-8")
        return path

    @staticmethod
    def _record(todo: dict, rolled: str = "2026-09-01T10:00:00+00:00") -> dict:
        return {"rolled": rolled, "reason": "overflow", "entry": todo}

    @staticmethod
    def _restore(tr, number, local: Path, tmp_path: Path) -> dict:
        return tr.restore_todo("guinea", number, local_path=local, backup_root=tmp_path / ".backup")

    def test_restore_reissues_the_next_number_and_carries_every_other_field(self, tr, tmp_path):
        # `tags` used to stand in for "every other field" here. The closed
        # field shape (FPLAN-0593) made that a field a todo may not carry, so
        # the pin now rides on `priority` — a field the shape allows — and the
        # tags case is pinned below for what it actually does now.
        original = _todo(2, task="bring it back", priority="high")
        local = _mint_pad(tmp_path, [_todo(n) for n in (5, 9, 3)])
        backlog = self._backlog_with(
            tmp_path, [self._record(_todo(1)), self._record(original), self._record(_todo(14))]
        )

        result = self._restore(tr, 2, local, tmp_path)

        assert result["success"] is True, result["error"]
        assert result["number"] == 15, "max(pad 9, backlog originals 14) + 1"
        assert json.loads(local.read_text(encoding="utf-8"))["todos"][0] == {**original, "number": 15}
        remaining = json.loads(backlog.read_text(encoding="utf-8"))["entries"]
        assert [record["entry"]["number"] for record in remaining] == [1, 14]

    def test_restoring_a_non_canonical_todo_is_refused_and_the_field_is_named(self, tr, tmp_path):
        # THE DEAD END, pinned rather than hidden (FPLAN-0593). A todo reaches
        # the backlog BECAUSE it is non-canonical, and the closed field shape
        # means putting it back on the pad is a refused write. Restore must not
        # reshape it to get past the gate — that is the one thing the backlog
        # contract forbids — so the honest outcome is a refusal.
        #
        # Phase 5 changed what that refusal SAYS, not whether it happens. The
        # field is named now: two seats hit the bare version the same night and
        # reshaped five records by hand because the only way to learn which
        # field was wrong was to attempt the write and read one refusal at a
        # time. The substring is asserted exactly, not with an `or` over two
        # words — the loose version passed on a refusal that named nothing.
        original = _todo(2, task="bring it back", tags=["x"])
        local = _mint_pad(tmp_path, [_todo(5)])
        backlog = self._backlog_with(tmp_path, [self._record(original)])

        result = self._restore(tr, 2, local, tmp_path)

        assert result["success"] is False
        assert "field 'tags' is not part of the entry shape" in result["error"], result["error"]
        assert "NOTHING RESTORED" in result["error"]
        # The pad and the backlog are both left exactly as found.
        assert [t["number"] for t in json.loads(local.read_text(encoding="utf-8"))["todos"]] == [5]
        assert [r["entry"]["number"] for r in json.loads(backlog.read_text(encoding="utf-8"))["entries"]] == [2]

    def test_every_broken_rule_is_named_in_one_refusal_not_one_per_attempt(self, tr, tmp_path):
        # The whole point of the pre-write check: a seat fixes the record in
        # one pass instead of bisecting it. @flow's five refused restores
        # carried both species at once — a `status` field the shape does not
        # allow, and a `task` past its cap — and the gate reported whichever it
        # reached first.
        cap = _todo_cap(tr)
        original = _todo(2, task="x" * (cap + 17), status="open")
        local = _mint_pad(tmp_path, [_todo(5)])
        self._backlog_with(tmp_path, [self._record(original)])

        error = self._restore(tr, 2, local, tmp_path)["error"]

        assert "field 'status' is not part of the entry shape" in error, error
        assert f"'task' is {cap + 17}/{cap} chars (+17 over)" in error, error

    def test_the_refusal_lands_before_anything_is_written(self, tr, tmp_path, monkeypatch):
        # "Pre-write" is the claim; this measures it. The old path built the
        # pad, called the writer and let the gate refuse — correct, but it
        # spent a write to learn what the shape already knew, and the pad file
        # was rewritten and rolled back on a lane whose whole contract is that
        # a todo is never in neither place.
        writes = []
        monkeypatch.setattr(tr, "_write_document", lambda path, document: writes.append(Path(path).name))
        local = _mint_pad(tmp_path, [_todo(5)])
        self._backlog_with(tmp_path, [self._record(_todo(2, task="bring it back", tags=["x"]))])

        assert self._restore(tr, 2, local, tmp_path)["success"] is False
        assert writes == [], f"the shape check ran after a write: {writes}"

    def test_a_legal_record_passes_the_shape_check_untouched(self, tr, tmp_path):
        # The other half: the check must not refuse what the gate would accept.
        # A pre-flight stricter than the gate it predicts is a new dead end.
        local = _mint_pad(tmp_path, [_todo(5)])
        self._backlog_with(tmp_path, [self._record(_todo(2, task="bring it back", priority="high"))])

        result = self._restore(tr, 2, local, tmp_path)

        assert result["success"] is True, result["error"]

    def test_the_check_reports_and_never_repairs(self, tr, tmp_path):
        # Scope, held deliberately. Whether an over-cap task should be CUT to
        # fit or carried VERBATIM is open (todo 251, the legacy-pad ruling) and
        # is not presumed here: under either answer the refusal text above is
        # the same, so only the reporting half was built. This pins that the
        # repairing half was NOT — a restore that quietly trimmed a task would
        # answer the open question by shipping.
        cap = _todo_cap(tr)
        original = _todo(2, task="x" * (cap + 5))
        local = _mint_pad(tmp_path, [_todo(5)])
        backlog = self._backlog_with(tmp_path, [self._record(original)])

        assert self._restore(tr, 2, local, tmp_path)["success"] is False
        record = json.loads(backlog.read_text(encoding="utf-8"))["entries"][0]["entry"]
        assert record["task"] == "x" * (cap + 5), "the backlog record was reshaped"
        assert json.loads(local.read_text(encoding="utf-8"))["todos"] == [_todo(5)]

    def test_the_pad_is_written_before_the_backlog_is_touched(self, tr, tmp_path, monkeypatch):
        local = _mint_pad(tmp_path, [_todo(3)])
        self._backlog_with(tmp_path, [self._record(_todo(1))])
        real_write = tr._write_document
        writes = []

        def recording_write(path, document):
            writes.append(Path(path).name)
            return real_write(path, document)

        monkeypatch.setattr(tr, "_write_document", recording_write)

        assert self._restore(tr, 1, local, tmp_path)["success"] is True
        assert writes == ["local.json", "backlog.json"]

    def test_a_pad_that_does_not_land_leaves_the_backlog_untouched(self, tr, tmp_path, monkeypatch):
        local = _mint_pad(tmp_path, [_todo(3)])
        backlog = self._backlog_with(tmp_path, [self._record(_todo(1))])
        pad_before, backlog_before = local.read_bytes(), backlog.read_bytes()
        real_write = tr._write_document
        monkeypatch.setattr(
            tr,
            "_write_document",
            lambda path, document: "disk full" if Path(path).name == "local.json" else real_write(path, document),
        )

        result = self._restore(tr, 1, local, tmp_path)

        assert result["success"] is False
        assert result["error"].startswith("NOTHING RESTORED"), result["error"]
        assert backlog.read_bytes() == backlog_before
        assert local.read_bytes() == pad_before

    def test_an_ambiguous_number_is_refused_naming_every_candidate(self, tr, tmp_path):
        local = _mint_pad(tmp_path, [_todo(8)])
        backlog = self._backlog_with(
            tmp_path,
            [
                self._record(_todo(4, task="first four"), rolled="2026-09-01T10:00:00+00:00"),
                self._record(_todo(6)),
                self._record(_todo(4, task="second four"), rolled="2026-09-10T08:30:00+00:00"),
            ],
        )
        pad_before, backlog_before = local.read_bytes(), backlog.read_bytes()

        result = self._restore(tr, 4, local, tmp_path)

        assert result["success"] is False
        assert "todo #4 is ambiguous - 2 backlog records carry it" in result["error"]
        assert "rolled 2026-09-01T10:00:00+00:00: first four" in result["error"]
        assert "rolled 2026-09-10T08:30:00+00:00: second four" in result["error"]
        assert local.read_bytes() == pad_before and backlog.read_bytes() == backlog_before

    def test_a_full_pad_is_refused_at_the_count_config_names(self, tr, tmp_path, monkeypatch):
        _point_todos_count(monkeypatch, tmp_path, tr, 3)
        local = _mint_pad(tmp_path, [_todo(n) for n in (2, 3, 4)])
        backlog = self._backlog_with(tmp_path, [self._record(_todo(1))])
        pad_before, backlog_before = local.read_bytes(), backlog.read_bytes()

        refused = self._restore(tr, 1, local, tmp_path)

        assert refused["success"] is False
        assert refused["error"] == "pad is full (3/3) - finish or delete one before restoring #1"
        assert local.read_bytes() == pad_before and backlog.read_bytes() == backlog_before

        _point_todos_count(monkeypatch, tmp_path, tr, 4)
        assert self._restore(tr, 1, local, tmp_path)["success"] is True, "the count is config's, not a literal"

    def test_an_unknown_number_is_refused(self, tr, tmp_path):
        local = _mint_pad(tmp_path, [_todo(3)])
        backlog = self._backlog_with(tmp_path, [self._record(_todo(1))])

        result = self._restore(tr, 99, local, tmp_path)

        assert result["success"] is False
        assert result["error"] == f"no todo #99 in the backlog at {backlog}"

    def test_no_backlog_is_an_honest_answer_not_an_error(self, tr, tmp_path):
        missing = _backlog_file(tmp_path)
        state = tr.read_backlog(missing)

        assert state["exists"] is False
        assert state["error"] is None
        assert state["entries"] == []
        assert state["message"].startswith(f"no backlog at {missing} - nothing has rolled off this pad")

        local = _mint_pad(tmp_path, [_todo(4)])
        result = self._restore(tr, 1, local, tmp_path)
        assert result["success"] is False and result["error"] == state["message"]
        assert tr.next_number([_todo(4)], state["entries"]) == 5
        assert not (tmp_path / ".backup").exists()

    def test_the_next_number_spans_pad_and_backlog(self, tr, tmp_path):
        assert tr.next_number([], []) == 1
        assert tr.next_number([{"number": 3}], [{"entry": {"number": 9}}]) == 10
        assert tr.next_number([{"number": True}], [{"entry": {"number": "7"}}]) == 1

        backlog = self._backlog_with(tmp_path, [self._record(_todo(11))])
        assert tr.next_number([_todo(2)], tr.read_backlog(backlog)["entries"]) == 12

    def test_the_restored_todo_lands_on_top_and_the_pad_stays_newest_first(self, tr, tmp_path):
        """@canary's audit went 99: a restore appended at the tail - 'number 12 is not below the entry above it'."""
        local = _mint_pad(tmp_path, [_todo(n) for n in (9, 5, 3)])
        self._backlog_with(tmp_path, [self._record(_todo(2, task="bring it back"))])

        result = self._restore(tr, 2, local, tmp_path)

        assert result["success"] is True, result["error"]
        pad = json.loads(local.read_text(encoding="utf-8"))["todos"]
        assert pad[0] == _todo(10, task="bring it back")
        numbers = [todo["number"] for todo in pad]
        assert numbers == sorted(set(numbers), reverse=True) == [10, 9, 5, 3], "strictly descending"

    def test_a_restored_then_deleted_number_is_never_issued_again(self, tr, tmp_path):
        """restore -> delete the restored todo by hand -> the next restore skips its number (high_water)."""
        local = _mint_pad(tmp_path, [_todo(3)])
        backlog = self._backlog_with(tmp_path, [self._record(_todo(1)), self._record(_todo(2))])
        assert tr.high_water_of(tr.read_backlog(backlog)["document"]) is None, "a backlog from before: no floor"

        first = self._restore(tr, 1, local, tmp_path)

        assert first["success"] is True and first["number"] == 4, first
        assert tr.high_water_of(tr.read_backlog(backlog)["document"]) == 4, "restore stamps high_water"

        document = json.loads(local.read_text(encoding="utf-8"))
        document["todos"] = [todo for todo in document["todos"] if todo["number"] != 4]
        local.write_text(json.dumps(document, indent=2), encoding="utf-8")

        second = self._restore(tr, 2, local, tmp_path)

        assert second["success"] is True, second["error"]
        assert second["number"] == 5, "#4 was issued and deleted: it is never handed out again"
        assert [todo["number"] for todo in json.loads(local.read_text(encoding="utf-8"))["todos"]] == [5, 3]
        assert tr.high_water_of(tr.read_backlog(backlog)["document"]) == 5

    def test_the_tab_the_pad_last_rendered_lifts_the_restored_number(self, tr, tmp_path):
        """The pad's own next #20 is a floor: #3..#19 were issued and deleted by hand before this backlog knew."""
        local = _mint_pad(tmp_path, [_todo(3)])
        document = json.loads(local.read_text(encoding="utf-8"))
        document["todos_meta"] = _tab(20)
        local.write_text(json.dumps(document, indent=2), encoding="utf-8")
        backlog = self._backlog_with(tmp_path, [self._record(_todo(1)), self._record(_todo(2))])

        result = self._restore(tr, 1, local, tmp_path)

        assert result["success"] is True and result["number"] == 20, result
        assert tr.high_water_of(tr.read_backlog(backlog)["document"]) == 20

    def test_the_restore_re_renders_the_tab_to_the_number_after_the_fresh_one(self, tr, tmp_path):
        """@canary: restore 3 -> #15 left the tab at next #15 with #15 on the pad - a hand copy would collide."""
        import importlib

        local = _mint_pad(tmp_path, [_todo(n) for n in (14, 11, 4)])
        document = json.loads(local.read_text(encoding="utf-8"))
        document["todos_meta"] = _tab(15)
        local.write_text(json.dumps(document, indent=2), encoding="utf-8")
        backlog = self._backlog_with(tmp_path, [self._record(_todo(3))])

        result = self._restore(tr, 3, local, tmp_path)

        assert result["success"] is True and result["number"] == 15, result
        after = json.loads(local.read_text(encoding="utf-8"))
        assert " · next #16 ⟧ " in after["todos_meta"], after["todos_meta"]
        renderer = importlib.import_module("aipass.memory.apps.handlers.tracking.tab_renderer")
        config = tr.config_loader.load()
        context = renderer.todo_context("guinea", after["todos"], tr.read_backlog(backlog))
        expected = renderer.compose_meta("todos", config["rollover"], config["entry_limits"], "guinea", context)
        assert after["todos_meta"].encode("utf-8") == expected.encode("utf-8")

    def test_a_high_water_that_reads_back_wrong_is_reported_not_silent(self, tr, tmp_path, monkeypatch):
        local = _mint_pad(tmp_path, [_todo(3)])
        self._backlog_with(tmp_path, [self._record(_todo(1))])
        real_write = tr._write_document

        def tampering_write(path, document):
            if Path(path).name == "backlog.json":
                document = json.loads(json.dumps(document))
                document["document_metadata"]["high_water"] = 1
            return real_write(path, document)

        monkeypatch.setattr(tr, "_write_document", tampering_write)
        result = self._restore(tr, 1, local, tmp_path)

        assert result["success"] is False
        assert "document_metadata (high_water) does not read back as written" in result["error"], result["error"]
        assert result["error"].endswith("it is in both places, never in neither")

    def test_the_floors_lift_the_number_and_garbage_is_no_floor(self, tr):
        """high_water and the tab's N - 1 lift next_number; a bool, a string, #? or foreign text do not."""
        assert tr.next_number([_todo(3)], [], high_water=40) == 41
        assert tr.next_number([_todo(3)], [], tab_floor=40) == 41
        assert tr.next_number([_todo(50)], [], high_water=40, tab_floor=12) == 51, "a floor never lowers"
        assert tr.next_number([], [], high_water=True, tab_floor=False) == 1, "a bool is not a number"

        assert tr.high_water_of({"document_metadata": {"managed_by": "memory", "high_water": 7}}) == 7
        for document in (
            {"document_metadata": {"managed_by": "memory"}},
            {"document_metadata": {"high_water": True}},
            {"document_metadata": {"high_water": "7"}},
            {"document_metadata": {"high_water": 7.0}},
            {"document_metadata": "high_water"},
            None,
        ):
            assert tr.high_water_of(document) is None, document

        assert tr.floor_from_tab(_tab(20)) == 19
        assert tr.floor_from_tab("⟦ no pad size configured — nothing rolls · task ≤100 chars · next #3 ⟧ x") == 2
        for garbage in (_tab("?"), _tab(0), _tab(-4), _tab("2x"), "next #20", "see ⟦ a · next #20 ⟧", None, 20):
            assert tr.floor_from_tab(garbage) is None, garbage
