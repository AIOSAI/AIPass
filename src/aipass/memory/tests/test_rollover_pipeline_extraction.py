# =================== AIPass ====================
# Name: test_rollover_pipeline_extraction.py
# Description: Rollover pipeline - the orchestrator's subprocess lanes and chroma path, and extraction
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-23
# Category: memory/tests
# =============================================

"""Tests for apps/handlers/rollover/orchestrator.py and extractor.py — subprocess lanes, chroma path, extraction."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(external) — the real encoder and vector store behind store_vectors_subprocess()

import json
import subprocess
import sys
from unittest.mock import MagicMock, patch

from aipass.memory.apps.handlers import write_fence
from aipass.memory.tests.support_rollover_pipeline import _import_extractor


def _import_orchestrator(monkeypatch):
    """Import orchestrator with mocked infrastructure dependencies."""
    mock_detector = MagicMock()
    mock_detector._read_registry = MagicMock(return_value=[])
    mock_detector.check_all_branches = MagicMock(return_value={"success": True, "triggers": []})

    mock_extractor = MagicMock()

    monitor_pkg = MagicMock()

    monitor_pkg.detector = mock_detector

    rollover_pkg = MagicMock()

    rollover_pkg.extractor = mock_extractor

    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.monitor", monitor_pkg)
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.monitor.detector", mock_detector)
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.rollover.extractor", mock_extractor)

    # Through monkeypatch: a bare pop left the mock-built copy cached for later files.
    monkeypatch.delitem(sys.modules, "aipass.memory.apps.handlers.rollover.orchestrator", raising=False)
    parent = sys.modules.get("aipass.memory.apps.handlers.rollover")
    if parent is not None:
        monkeypatch.delattr(parent, "orchestrator", raising=False)

    from aipass.memory.apps.handlers.rollover import orchestrator

    return orchestrator, {
        "detector": mock_detector,
        "extractor": mock_extractor,
    }


class TestStoreVectorsSubprocess:
    """Test store_vectors_subprocess calls subprocess and returns dict."""

    def test_success_returns_parsed_json(self, monkeypatch, tmp_path):
        # tmp_path, not tempfile.gettempdir(): the write fence admits only its own root.
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
                db_path=str(tmp_path / "test.chroma"),
            )

        assert result["success"] is True
        assert result["collection"] == "test_col"
        mock_run.assert_called_once()

    def test_a_local_store_outside_the_aipass_root_never_starts_the_subprocess(self, monkeypatch, tmp_path):
        """A local store outside the root is refused in THIS process, before the writing child starts."""

        orch, _ = _import_orchestrator(monkeypatch)
        monkeypatch.setattr(write_fence, "ROOT", tmp_path / "aipass")

        with patch.object(subprocess, "run") as mock_run:
            result = orch.store_vectors_subprocess(
                branch="X",
                memory_type="local",
                embeddings=[[0.1]],
                documents=["doc1"],
                metadatas=[{}],
                db_path=str(tmp_path / "other_root" / "src" / "x" / ".chroma"),
            )

        assert result["success"] is False
        mock_run.assert_not_called()

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
        call_kwargs = mock_run.call_args
        input_data = json.loads(call_kwargs.kwargs.get("input", call_kwargs[1].get("input", "")))
        assert input_data["embeddings"] == [[0.1, 0.2, 0.3]]


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

    def test_a_branch_outside_the_aipass_root_gets_no_chroma_directory(self, monkeypatch, tmp_path):
        """No path handed out, no directory made — the auto-create was the first write."""

        orch, mocks = _import_orchestrator(monkeypatch)
        monkeypatch.setattr(write_fence, "ROOT", tmp_path / "aipass")
        branch_dir = tmp_path / "other_root" / "src" / "x"
        branch_dir.mkdir(parents=True)
        mocks["detector"]._read_registry.return_value = [{"name": "X", "path": str(branch_dir)}]

        assert orch.get_branch_local_chroma_path("X") is None
        assert not (branch_dir / ".chroma").exists()

    def test_an_existing_foreign_chroma_directory_is_not_handed_out_either(self, monkeypatch, tmp_path):
        """Existing is not permission: the store call would write straight into it."""

        orch, mocks = _import_orchestrator(monkeypatch)
        monkeypatch.setattr(write_fence, "ROOT", tmp_path / "aipass")
        branch_dir = tmp_path / "other_root" / "src" / "x"
        (branch_dir / ".chroma").mkdir(parents=True)
        mocks["detector"]._read_registry.return_value = [{"name": "X", "path": str(branch_dir)}]

        assert orch.get_branch_local_chroma_path("X") is None


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

    def test_extracts_from_note_field(self, monkeypatch):
        """An observation's text is its note; the dict repr is what 758 live vectors held instead."""
        orch, _ = _import_orchestrator(monkeypatch)
        memories = [{"date": "2026-10-23", "note": "the note", "tags": ["t"], "number": 58}]
        texts = orch.extract_text_from_memories(memories)
        assert texts == ["the note"]

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

        branch_name = tmp_path.name.lower()

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
        # True, not None: the real writer returns a boolean, and a laxer stand-in hides the guard.
        mocks["memory_files"].write_memory_file_simple.return_value = True

        result = ext.extract_with_metadata(file_path)

        assert result["success"] is True
        assert "entries" in result
        assert result["branch"] is not None
        assert result["type"] is not None
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
        assert result["success"] is True
        # All three together: an `or` hid a rebuilt dict where only one half survived.
        assert result["skipped"] is True
        assert result["count"] == 0
        assert result["entries"] == []
