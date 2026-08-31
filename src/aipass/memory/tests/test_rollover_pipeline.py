# ===================AIPASS====================
# META DATA HEADER
# Name: tests/test_rollover_pipeline.py
# Date: 2026-04-25
# Version: 1.0.0
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
import sys
from datetime import datetime
from pathlib import Path
import pytest
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

    handlers_pkg = MagicMock()

    # (test_import_isolation.py) — a bare MagicMock has none, and any lazy

    # submodule import under it then dies with "is not a package".

    handlers_pkg.monitor = monitor_pkg
    handlers_pkg.rollover = rollover_pkg

    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers", handlers_pkg)
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.monitor", monitor_pkg)
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.monitor.detector", mock_detector)
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.rollover", rollover_pkg)
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.rollover.orchestrator", mock_orchestrator)

    sys.modules.pop("aipass.memory.apps.modules.rollover", None)
    parent = sys.modules.get("aipass.memory.apps.modules")
    if parent is not None and hasattr(parent, "rollover"):
        delattr(parent, "rollover")

    from aipass.memory.apps.modules import rollover

    return rollover, {
        "console": mock_console,
        "error": mock_error,
        "warning": mock_warning,
        "detector": mock_detector,
        "orchestrator": mock_orchestrator,
    }


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
                db_path="/tmp/test.chroma",
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
        # Either skipped=True (passthrough) or entries is empty (wrapped)
        assert result.get("skipped") is True or result.get("count", 0) == 0


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
        assert "extracted" not in result or not result.get("extracted")


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

    def test_a_tail_entry_numbered_EQUAL_to_the_head_is_still_refused(self, monkeypatch):
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

    def test_displays_stats_on_success(self, monkeypatch):
        rollover, mocks = _import_rollover_module(monkeypatch)
        mocks["detector"].get_rollover_stats.return_value = {
            "success": True,
            "total_branches": 2,
            "files_checked": 4,
            "files_ready": 1,
            "branches": {
                "TEST": {
                    "local": {
                        "current": 500,
                        "ready": False,
                        "schema_version": "3.0.0",
                    }
                }
            },
        }
        rollover.show_status()
        mocks["console"].print.assert_called()

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
