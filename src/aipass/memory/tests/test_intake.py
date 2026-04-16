# ===================AIPASS====================
# META DATA HEADER
# Name: tests/test_intake.py
# Date: 2026-04-03
# Version: 1.0.0
# Category: memory/tests
# =============================================

"""Tests for the intake/pool_processor handler.

Covers:
  - pool_processor.find_source_file (active pool, archive, not found)
  - pool_processor.load_config (success, missing file)
  - pool_processor.get_pool_files (no files, sorted by mtime)
  - pool_processor.read_file_content (success, failure)
  - pool_processor.chunk_content (short text, long text, paragraph breaks)
  - pool_processor.process_file_to_vectors (mocked chromadb)
  - pool_processor.archive_old_files (under limit, moves old, duplicate names)
  - pool_processor.process_memory_pool (disabled, no files)
  - pool_processor.get_pool_status (mocked chromadb)

All tests use mocks/tmp_path -- no live filesystem or infrastructure access.
"""

import json
import sys
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Import helper
# ---------------------------------------------------------------------------


def _import_pool_processor(monkeypatch):
    """Import pool_processor with mocked dependencies."""
    sys.modules.pop("aipass.memory.apps.handlers.intake.pool_processor", None)
    parent = sys.modules.get("aipass.memory.apps.handlers.intake")
    if parent is not None and hasattr(parent, "pool_processor"):
        delattr(parent, "pool_processor")

    from aipass.memory.apps.handlers.intake import pool_processor

    return pool_processor


# ===========================================================================
# Tests: find_source_file
# ===========================================================================


class TestFindSourceFile:
    """Test find_source_file function."""

    def test_found_in_active_pool(self, monkeypatch, tmp_path):
        mod = _import_pool_processor(monkeypatch)
        pool = tmp_path / "memory_pool"
        pool.mkdir()
        target = pool / "notes.md"
        target.write_text("content", encoding="utf-8")
        monkeypatch.setattr(mod, "MEMORY_POOL_PATH", pool)

        result = mod.find_source_file("notes.md")

        assert result == target

    def test_found_in_archive(self, monkeypatch, tmp_path):
        mod = _import_pool_processor(monkeypatch)
        pool = tmp_path / "memory_pool"
        archive = pool / ".archive"
        archive.mkdir(parents=True)
        target = archive / "old_notes.md"
        target.write_text("archived content", encoding="utf-8")
        monkeypatch.setattr(mod, "MEMORY_POOL_PATH", pool)

        result = mod.find_source_file("old_notes.md")

        assert result == target

    def test_not_found_returns_none(self, monkeypatch, tmp_path):
        mod = _import_pool_processor(monkeypatch)
        pool = tmp_path / "memory_pool"
        pool.mkdir()
        monkeypatch.setattr(mod, "MEMORY_POOL_PATH", pool)

        result = mod.find_source_file("nonexistent.md")

        assert result is None

    def test_prefers_active_over_archive(self, monkeypatch, tmp_path):
        mod = _import_pool_processor(monkeypatch)
        pool = tmp_path / "memory_pool"
        archive = pool / ".archive"
        archive.mkdir(parents=True)
        active_file = pool / "notes.md"
        archive_file = archive / "notes.md"
        active_file.write_text("active", encoding="utf-8")
        archive_file.write_text("archived", encoding="utf-8")
        monkeypatch.setattr(mod, "MEMORY_POOL_PATH", pool)

        result = mod.find_source_file("notes.md")

        assert result == active_file


# ===========================================================================
# Tests: load_config
# ===========================================================================


class TestLoadConfig:
    """Test load_config function."""

    def test_loads_valid_config(self, monkeypatch, tmp_path):
        mod = _import_pool_processor(monkeypatch)
        config_file = tmp_path / "memory_bank.config.json"
        config_file.write_text(
            json.dumps({"memory_pool": {"enabled": True, "keep_recent": 5, "collection_name": "test_pool"}}),
            encoding="utf-8",
        )
        monkeypatch.setattr(mod, "CONFIG_PATH", config_file)

        result = mod.load_config()

        assert result["enabled"] is True
        assert result["keep_recent"] == 5
        assert result["collection_name"] == "test_pool"

    def test_returns_disabled_when_file_missing(self, monkeypatch, tmp_path):
        mod = _import_pool_processor(monkeypatch)
        monkeypatch.setattr(mod, "CONFIG_PATH", tmp_path / "missing.json")

        result = mod.load_config()

        assert result["enabled"] is False
        assert "error" in result

    def test_returns_empty_when_no_memory_pool_key(self, monkeypatch, tmp_path):
        mod = _import_pool_processor(monkeypatch)
        config_file = tmp_path / "memory_bank.config.json"
        config_file.write_text(json.dumps({"rollover": {}}), encoding="utf-8")
        monkeypatch.setattr(mod, "CONFIG_PATH", config_file)

        result = mod.load_config()

        assert result == {}


# ===========================================================================
# Tests: get_pool_files
# ===========================================================================


class TestGetPoolFiles:
    """Test get_pool_files function."""

    def test_returns_empty_when_no_directory(self, monkeypatch, tmp_path):
        mod = _import_pool_processor(monkeypatch)
        monkeypatch.setattr(mod, "MEMORY_POOL_PATH", tmp_path / "nonexistent")

        result = mod.get_pool_files()

        assert result == []

    def test_returns_empty_when_no_matching_files(self, monkeypatch, tmp_path):
        mod = _import_pool_processor(monkeypatch)
        pool = tmp_path / "memory_pool"
        pool.mkdir()
        (pool / "image.png").write_text("not text", encoding="utf-8")
        monkeypatch.setattr(mod, "MEMORY_POOL_PATH", pool)

        result = mod.get_pool_files()

        assert result == []

    def test_returns_sorted_by_mtime_newest_first(self, monkeypatch, tmp_path):
        mod = _import_pool_processor(monkeypatch)
        pool = tmp_path / "memory_pool"
        pool.mkdir()

        old_file = pool / "old.md"
        old_file.write_text("old content", encoding="utf-8")
        import os

        os.utime(str(old_file), (1000000, 1000000))

        new_file = pool / "new.md"
        new_file.write_text("new content", encoding="utf-8")
        os.utime(str(new_file), (2000000, 2000000))

        monkeypatch.setattr(mod, "MEMORY_POOL_PATH", pool)

        result = mod.get_pool_files()

        assert len(result) == 2
        assert result[0].name == "new.md"
        assert result[1].name == "old.md"

    def test_filters_by_custom_extensions(self, monkeypatch, tmp_path):
        mod = _import_pool_processor(monkeypatch)
        pool = tmp_path / "memory_pool"
        pool.mkdir()
        (pool / "doc.md").write_text("md", encoding="utf-8")
        (pool / "notes.txt").write_text("txt", encoding="utf-8")
        (pool / "data.json").write_text("{}", encoding="utf-8")
        monkeypatch.setattr(mod, "MEMORY_POOL_PATH", pool)

        result = mod.get_pool_files(extensions=[".json"])

        assert len(result) == 1
        assert result[0].name == "data.json"


# ===========================================================================
# Tests: read_file_content
# ===========================================================================


class TestReadFileContent:
    """Test read_file_content function."""

    def test_reads_successfully(self, monkeypatch, tmp_path):
        mod = _import_pool_processor(monkeypatch)
        test_file = tmp_path / "test.md"
        test_file.write_text("Hello, world!", encoding="utf-8")

        result = mod.read_file_content(test_file)

        assert result["success"] is True
        assert result["content"] == "Hello, world!"
        assert result["metadata"]["filename"] == "test.md"
        assert result["metadata"]["extension"] == ".md"
        assert result["metadata"]["size"] > 0

    def test_returns_failure_for_missing_file(self, monkeypatch, tmp_path):
        mod = _import_pool_processor(monkeypatch)
        missing = tmp_path / "nonexistent.md"

        result = mod.read_file_content(missing)

        assert result["success"] is False
        assert "error" in result


# ===========================================================================
# Tests: chunk_content
# ===========================================================================


class TestChunkContent:
    """Test chunk_content function."""

    def test_short_text_single_chunk(self, monkeypatch):
        mod = _import_pool_processor(monkeypatch)

        result = mod.chunk_content("Short text.", chunk_size=1000)

        assert len(result) == 1
        assert result[0]["text"] == "Short text."
        assert result[0]["chunk_index"] == 0

    def test_long_text_multiple_chunks(self, monkeypatch):
        mod = _import_pool_processor(monkeypatch)
        # Create text longer than chunk_size
        content = "word " * 300  # ~1500 chars

        result = mod.chunk_content(content, chunk_size=500, overlap=50)

        assert len(result) > 1
        # All chunks have sequential indices
        indices = [c["chunk_index"] for c in result]
        assert indices == list(range(len(result)))

    def test_chunk_indices_are_sequential(self, monkeypatch):
        mod = _import_pool_processor(monkeypatch)
        content = "A" * 2500

        result = mod.chunk_content(content, chunk_size=1000, overlap=100)

        for i, chunk in enumerate(result):
            assert chunk["chunk_index"] == i

    def test_paragraph_break_splitting(self, monkeypatch):
        mod = _import_pool_processor(monkeypatch)
        # Build content with a paragraph break in the right spot
        # chunk_size=100, so we need content > 100 chars
        # Place a paragraph break after the midpoint (>50 chars in)
        first_para = "A" * 70
        second_para = "B" * 70
        content = first_para + "\n\n" + second_para

        result = mod.chunk_content(content, chunk_size=100, overlap=10)

        # Should have split at the paragraph break
        assert len(result) >= 2

    def test_empty_content_returns_single_chunk(self, monkeypatch):
        mod = _import_pool_processor(monkeypatch)

        result = mod.chunk_content("", chunk_size=1000)

        # Empty string <= chunk_size, returns single chunk
        assert len(result) == 1
        assert result[0]["text"] == ""

    def test_exact_chunk_size_single_chunk(self, monkeypatch):
        mod = _import_pool_processor(monkeypatch)
        content = "X" * 100

        result = mod.chunk_content(content, chunk_size=100, overlap=10)

        assert len(result) == 1
        assert result[0]["text"] == content


# ===========================================================================
# Tests: process_file_to_vectors
# ===========================================================================


class TestProcessFileToVectors:
    """Test process_file_to_vectors with mocked chromadb."""

    def test_processes_file_with_mocked_chromadb(self, monkeypatch, tmp_path):
        mod = _import_pool_processor(monkeypatch)
        monkeypatch.setattr(mod, "CHROMA_PATH", tmp_path / ".chroma")

        test_file = tmp_path / "test.md"
        test_file.write_text("Test content for vectorization.", encoding="utf-8")

        # Mock chromadb
        mock_collection = MagicMock()
        mock_collection.upsert = MagicMock()
        mock_client = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_collection
        mock_chromadb = MagicMock()
        mock_chromadb.PersistentClient.return_value = mock_client

        # Mock sentence_transformers
        mock_model = MagicMock()
        mock_model.encode.return_value = MagicMock(tolist=MagicMock(return_value=[[0.1, 0.2]]))
        mock_st = MagicMock()
        mock_st.SentenceTransformer.return_value = mock_model

        monkeypatch.setitem(sys.modules, "chromadb", mock_chromadb)
        monkeypatch.setitem(sys.modules, "sentence_transformers", mock_st)

        result = mod.process_file_to_vectors(test_file, "test_collection")

        assert result["success"] is True
        assert result["chunks_stored"] >= 1
        assert result["collection"] == "test_collection"
        mock_collection.upsert.assert_called_once()

    def test_returns_failure_when_file_unreadable(self, monkeypatch, tmp_path):
        mod = _import_pool_processor(monkeypatch)
        missing = tmp_path / "nonexistent.md"

        result = mod.process_file_to_vectors(missing, "test_collection")

        assert result["success"] is False

    def test_returns_failure_when_chromadb_import_fails(self, monkeypatch, tmp_path):
        mod = _import_pool_processor(monkeypatch)

        test_file = tmp_path / "test.md"
        test_file.write_text("Some content here.", encoding="utf-8")

        # Remove chromadb from modules so the import inside the function fails
        monkeypatch.delitem(sys.modules, "chromadb", raising=False)
        monkeypatch.delitem(sys.modules, "sentence_transformers", raising=False)

        # Patch the builtins __import__ to raise for chromadb
        original_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__

        def fake_import(name, *args, **kwargs):
            if name == "chromadb":
                raise ImportError("chromadb not installed")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr("builtins.__import__", fake_import)

        result = mod.process_file_to_vectors(test_file, "test_collection")

        assert result["success"] is False
        assert "error" in result


# ===========================================================================
# Tests: archive_old_files
# ===========================================================================


class TestArchiveOldFiles:
    """Test archive_old_files function."""

    def test_no_archiving_when_under_limit(self, monkeypatch, tmp_path):
        mod = _import_pool_processor(monkeypatch)
        pool = tmp_path / "memory_pool"
        pool.mkdir()
        (pool / "file1.md").write_text("content1", encoding="utf-8")
        (pool / "file2.md").write_text("content2", encoding="utf-8")
        monkeypatch.setattr(mod, "MEMORY_POOL_PATH", pool)
        monkeypatch.setattr(mod, "_MEMORY_ROOT", tmp_path)

        # Mock load_config to return supported extensions
        monkeypatch.setattr(mod, "load_config", lambda: {"supported_extensions": [".md", ".txt"]})

        result = mod.archive_old_files(keep_recent=5)

        assert result["success"] is True
        assert result["archived_count"] == 0
        assert result["kept_count"] == 2

    def test_moves_old_files_to_archive(self, monkeypatch, tmp_path):
        mod = _import_pool_processor(monkeypatch)
        pool = tmp_path / "memory_pool"
        pool.mkdir()
        monkeypatch.setattr(mod, "MEMORY_POOL_PATH", pool)
        monkeypatch.setattr(mod, "_MEMORY_ROOT", tmp_path)

        import os

        # Create 4 files with distinct mtimes
        for i in range(4):
            f = pool / f"file{i}.md"
            f.write_text(f"content {i}", encoding="utf-8")
            os.utime(str(f), (1000000 + (3 - i) * 1000, 1000000 + (3 - i) * 1000))

        monkeypatch.setattr(mod, "load_config", lambda: {"supported_extensions": [".md"]})

        archive_dir_name = "test_archive"
        result = mod.archive_old_files(keep_recent=2, archive_path=archive_dir_name)

        assert result["success"] is True
        assert result["archived_count"] == 2
        assert result["kept_count"] == 2

        archive_dir = tmp_path / archive_dir_name
        assert archive_dir.exists()
        archived_files = list(archive_dir.iterdir())
        assert len(archived_files) == 2

    def test_handles_duplicate_names_in_archive(self, monkeypatch, tmp_path):
        mod = _import_pool_processor(monkeypatch)
        pool = tmp_path / "memory_pool"
        pool.mkdir()
        monkeypatch.setattr(mod, "MEMORY_POOL_PATH", pool)
        monkeypatch.setattr(mod, "_MEMORY_ROOT", tmp_path)

        import os

        # Create files
        for i in range(3):
            f = pool / f"file{i}.md"
            f.write_text(f"content {i}", encoding="utf-8")
            os.utime(str(f), (1000000 + (2 - i) * 1000, 1000000 + (2 - i) * 1000))

        # Pre-create a file in archive with the same name as one that will be archived
        archive_dir = tmp_path / "test_archive"
        archive_dir.mkdir()
        (archive_dir / "file2.md").write_text("pre-existing", encoding="utf-8")

        monkeypatch.setattr(mod, "load_config", lambda: {"supported_extensions": [".md"]})

        result = mod.archive_old_files(keep_recent=1, archive_path="test_archive")

        assert result["success"] is True
        assert result["archived_count"] == 2

        # All files in archive (pre-existing + 2 moved, one renamed with timestamp)
        archived = list(archive_dir.iterdir())
        assert len(archived) == 3


# ===========================================================================
# Tests: process_memory_pool
# ===========================================================================


class TestProcessMemoryPool:
    """Test process_memory_pool main entry point."""

    def test_returns_error_when_disabled(self, monkeypatch, tmp_path):
        mod = _import_pool_processor(monkeypatch)
        monkeypatch.setattr(mod, "MEMORY_POOL_PATH", tmp_path / "pool")
        monkeypatch.setattr(mod, "load_config", lambda: {"enabled": False})

        result = mod.process_memory_pool()

        assert result["success"] is False
        assert "disabled" in result["error"]

    def test_returns_success_with_no_files(self, monkeypatch, tmp_path):
        mod = _import_pool_processor(monkeypatch)
        pool = tmp_path / "pool"
        monkeypatch.setattr(mod, "MEMORY_POOL_PATH", pool)
        monkeypatch.setattr(
            mod,
            "load_config",
            lambda: {
                "enabled": True,
                "keep_recent": 10,
                "collection_name": "test",
                "chunk_size": 1000,
                "chunk_overlap": 100,
                "supported_extensions": [".md"],
                "archive_path": "archive",
            },
        )
        monkeypatch.setattr(mod, "get_pool_files", lambda extensions=None: [])

        result = mod.process_memory_pool()

        assert result["success"] is True
        assert result["files_processed"] == 0

    def test_processes_files_and_archives(self, monkeypatch, tmp_path):
        mod = _import_pool_processor(monkeypatch)
        pool = tmp_path / "pool"
        pool.mkdir(parents=True)
        monkeypatch.setattr(mod, "MEMORY_POOL_PATH", pool)

        test_file = tmp_path / "test.md"
        test_file.write_text("content", encoding="utf-8")

        monkeypatch.setattr(
            mod,
            "load_config",
            lambda: {
                "enabled": True,
                "keep_recent": 10,
                "collection_name": "test",
                "chunk_size": 1000,
                "chunk_overlap": 100,
                "supported_extensions": [".md"],
                "archive_path": "archive",
            },
        )
        monkeypatch.setattr(mod, "get_pool_files", lambda extensions=None: [test_file])
        monkeypatch.setattr(
            mod,
            "process_file_to_vectors",
            lambda fp, cn, cs=1000, co=100: {"success": True, "file": fp.name, "chunks_stored": 3, "collection": cn},
        )
        monkeypatch.setattr(
            mod,
            "archive_old_files",
            lambda keep, archive_path="": {"success": True, "archived_count": 0, "kept_count": 1},
        )
        monkeypatch.setattr(mod, "_update_central_and_dashboard", lambda: None)

        mock_jh = MagicMock()
        monkeypatch.setattr(mod, "json_handler", mock_jh)

        result = mod.process_memory_pool()

        assert result["success"] is True
        assert result["files_processed"] == 1
        assert result["total_chunks"] == 3
        mock_jh.log_operation.assert_called_once()

    def test_reports_errors_and_notifies(self, monkeypatch, tmp_path):
        mod = _import_pool_processor(monkeypatch)
        pool = tmp_path / "pool"
        pool.mkdir(parents=True)
        monkeypatch.setattr(mod, "MEMORY_POOL_PATH", pool)

        test_file = tmp_path / "bad.md"
        test_file.write_text("content", encoding="utf-8")

        monkeypatch.setattr(
            mod,
            "load_config",
            lambda: {
                "enabled": True,
                "keep_recent": 10,
                "collection_name": "test",
                "chunk_size": 1000,
                "chunk_overlap": 100,
                "supported_extensions": [".md"],
                "archive_path": "archive",
            },
        )
        monkeypatch.setattr(mod, "get_pool_files", lambda extensions=None: [test_file])
        monkeypatch.setattr(
            mod,
            "process_file_to_vectors",
            lambda fp, cn, cs=1000, co=100: {"success": False, "error": "chromadb failed"},
        )
        monkeypatch.setattr(
            mod,
            "archive_old_files",
            lambda keep, archive_path="": {"success": True, "archived_count": 0, "kept_count": 0},
        )
        mock_notify = MagicMock()
        monkeypatch.setattr(mod, "_notify_failure", mock_notify)

        mock_jh = MagicMock()
        monkeypatch.setattr(mod, "json_handler", mock_jh)

        result = mod.process_memory_pool()

        assert result["success"] is False
        assert len(result["errors"]) == 1
        mock_notify.assert_called_once()


# ===========================================================================
# Tests: get_pool_status
# ===========================================================================


class TestGetPoolStatus:
    """Test get_pool_status function."""

    def test_returns_status_with_mocked_chromadb(self, monkeypatch, tmp_path):
        mod = _import_pool_processor(monkeypatch)
        pool = tmp_path / "memory_pool"
        pool.mkdir()
        (pool / "recent.md").write_text("content", encoding="utf-8")
        monkeypatch.setattr(mod, "MEMORY_POOL_PATH", pool)
        monkeypatch.setattr(mod, "CHROMA_PATH", tmp_path / ".chroma")

        monkeypatch.setattr(
            mod,
            "load_config",
            lambda: {
                "enabled": True,
                "keep_recent": 10,
                "collection_name": "test_pool",
                "supported_extensions": [".md"],
            },
        )

        # Mock chromadb
        mock_collection = MagicMock()
        mock_collection.name = "test_pool"
        mock_collection.count.return_value = 42
        mock_client = MagicMock()
        mock_client.list_collections.return_value = [mock_collection]
        mock_client.get_collection.return_value = mock_collection
        mock_chromadb = MagicMock()
        mock_chromadb.PersistentClient.return_value = mock_client
        monkeypatch.setitem(sys.modules, "chromadb", mock_chromadb)

        result = mod.get_pool_status()

        assert result["enabled"] is True
        assert result["files_in_pool"] == 1
        assert result["vectors_stored"] == 42
        assert result["collection_name"] == "test_pool"
        assert result["newest_file"] == "recent.md"
        assert result["oldest_file"] == "recent.md"

    def test_returns_zero_vectors_when_chromadb_fails(self, monkeypatch, tmp_path):
        mod = _import_pool_processor(monkeypatch)
        pool = tmp_path / "memory_pool"
        pool.mkdir()
        monkeypatch.setattr(mod, "MEMORY_POOL_PATH", pool)
        monkeypatch.setattr(mod, "CHROMA_PATH", tmp_path / ".chroma")

        monkeypatch.setattr(mod, "load_config", lambda: {"enabled": False, "supported_extensions": [".md"]})

        # Make chromadb import raise
        original_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__

        def fake_import(name, *args, **kwargs):
            if name == "chromadb":
                raise ImportError("no chromadb")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr("builtins.__import__", fake_import)

        result = mod.get_pool_status()

        assert result["vectors_stored"] == 0
        assert result["files_in_pool"] == 0
        assert result["newest_file"] is None
        assert result["oldest_file"] is None

    def test_returns_zero_vectors_when_collection_not_found(self, monkeypatch, tmp_path):
        mod = _import_pool_processor(monkeypatch)
        pool = tmp_path / "memory_pool"
        pool.mkdir()
        monkeypatch.setattr(mod, "MEMORY_POOL_PATH", pool)
        monkeypatch.setattr(mod, "CHROMA_PATH", tmp_path / ".chroma")

        monkeypatch.setattr(
            mod,
            "load_config",
            lambda: {"enabled": True, "supported_extensions": [".md"], "collection_name": "test_pool"},
        )

        # chromadb returns empty collection list
        mock_client = MagicMock()
        mock_client.list_collections.return_value = []
        mock_chromadb = MagicMock()
        mock_chromadb.PersistentClient.return_value = mock_client
        monkeypatch.setitem(sys.modules, "chromadb", mock_chromadb)

        result = mod.get_pool_status()

        assert result["vectors_stored"] == 0
