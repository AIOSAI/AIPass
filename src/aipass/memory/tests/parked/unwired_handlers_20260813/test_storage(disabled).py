# ===================AIPASS====================
# META DATA HEADER
# Name: tests/test_storage.py
# Date: 2026-04-03
# Version: 1.0.0
# Category: memory/tests
# =============================================

"""Tests for Chroma vector storage handler.

Covers:
  - storage/chroma.py  ChromaService class (init, get_collection_name,
    store_vectors, get_collection_stats, list_all_collections)
  - storage/chroma.py  Public API functions (store_vectors, get_collection_stats,
    list_all_collections, get_database_info, search_vectors)
  - storage/chroma.py  Singleton management (get_client, _get_service, global reset)

All tests use mocks/tmp_path -- no live ChromaDB or filesystem access.
"""

import sys
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Import helper -- chromadb must be mocked before importing chroma module
# ---------------------------------------------------------------------------


def _import_chroma(monkeypatch):
    """Import chroma module with mocked chromadb dependency."""
    mock_chromadb = MagicMock()
    monkeypatch.setitem(sys.modules, "chromadb", mock_chromadb)

    # Clear any cached module so we get a fresh import
    sys.modules.pop("aipass.memory.apps.handlers.storage.chroma", None)
    parent = sys.modules.get("aipass.memory.apps.handlers.storage")
    if parent is not None and hasattr(parent, "chroma"):
        delattr(parent, "chroma")

    from aipass.memory.apps.handlers.storage import chroma

    return chroma, mock_chromadb


def _reset_globals(chroma):
    """Reset module-level singletons between tests."""
    setattr(chroma, "_chroma_service", None)
    setattr(chroma, "_local_services", {})
    setattr(chroma, "_chroma_clients", {})


# ===========================================================================
# Tests: ChromaService class
# ===========================================================================


class TestChromaServiceCollectionName:
    """Test ChromaService.get_collection_name."""

    def test_returns_lowercase_combination(self, monkeypatch, tmp_path):
        chroma, mock_chromadb = _import_chroma(monkeypatch)
        _reset_globals(chroma)

        mock_client = MagicMock()
        mock_chromadb.PersistentClient.return_value = mock_client

        service = chroma.ChromaService(db_path=tmp_path / ".chroma")
        result = service.get_collection_name("SEEDGO", "Observations")

        assert result == "seedgo_observations"

    def test_handles_already_lowercase(self, monkeypatch, tmp_path):
        chroma, mock_chromadb = _import_chroma(monkeypatch)
        _reset_globals(chroma)

        mock_client = MagicMock()
        mock_chromadb.PersistentClient.return_value = mock_client

        service = chroma.ChromaService(db_path=tmp_path / ".chroma")
        result = service.get_collection_name("cli", "local")

        assert result == "cli_local"

    def test_mixed_case_branch_and_type(self, monkeypatch, tmp_path):
        chroma, mock_chromadb = _import_chroma(monkeypatch)
        _reset_globals(chroma)

        mock_client = MagicMock()
        mock_chromadb.PersistentClient.return_value = mock_client

        service = chroma.ChromaService(db_path=tmp_path / ".chroma")
        result = service.get_collection_name("DevPulse", "LOCAL")

        assert result == "devpulse_local"


class TestChromaServiceStoreVectors:
    """Test ChromaService.store_vectors."""

    def test_stores_vectors_and_returns_result(self, monkeypatch, tmp_path):
        chroma, mock_chromadb = _import_chroma(monkeypatch)
        _reset_globals(chroma)

        mock_collection = MagicMock()
        mock_collection.count.return_value = 3  # count after upsert

        mock_client = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_collection
        mock_chromadb.PersistentClient.return_value = mock_client

        service = chroma.ChromaService(db_path=tmp_path / ".chroma")

        embeddings = [[0.1, 0.2], [0.3, 0.4], [0.5, 0.6]]
        documents = ["doc1", "doc2", "doc3"]
        metadatas = [{"k": "v1"}, {"k": "v2"}, {"k": "v3"}]

        result = service.store_vectors("SEEDGO", "observations", embeddings, documents, metadatas)

        assert result["collection"] == "seedgo_observations"
        assert result["count"] == 3
        assert result["total_vectors"] == 3
        assert len(result["ids"]) == 3
        mock_collection.upsert.assert_called_once()


class TestChromaServiceGetCollectionStats:
    """Test ChromaService.get_collection_stats."""

    def test_returns_stats_for_existing_collection(self, monkeypatch, tmp_path):
        chroma, mock_chromadb = _import_chroma(monkeypatch)
        _reset_globals(chroma)

        mock_collection = MagicMock()
        mock_collection.count.return_value = 42

        mock_client = MagicMock()
        mock_client.get_collection.return_value = mock_collection
        mock_chromadb.PersistentClient.return_value = mock_client

        service = chroma.ChromaService(db_path=tmp_path / ".chroma")
        result = service.get_collection_stats("seedgo", "observations")

        assert result["exists"] is True
        assert result["vector_count"] == 42
        assert result["collection"] == "seedgo_observations"

    def test_returns_not_exists_when_collection_missing(self, monkeypatch, tmp_path):
        chroma, mock_chromadb = _import_chroma(monkeypatch)
        _reset_globals(chroma)

        mock_client = MagicMock()
        mock_client.get_collection.side_effect = Exception("Collection not found")
        mock_chromadb.PersistentClient.return_value = mock_client

        service = chroma.ChromaService(db_path=tmp_path / ".chroma")
        result = service.get_collection_stats("missing", "local")

        assert result["exists"] is False
        assert result["vector_count"] == 0


class TestChromaServiceListCollections:
    """Test ChromaService.list_all_collections."""

    def test_returns_collection_names(self, monkeypatch, tmp_path):
        chroma, mock_chromadb = _import_chroma(monkeypatch)
        _reset_globals(chroma)

        mock_col1 = MagicMock()
        mock_col1.name = "seedgo_observations"
        mock_col2 = MagicMock()
        mock_col2.name = "cli_local"

        mock_client = MagicMock()
        mock_client.list_collections.return_value = [mock_col1, mock_col2]
        mock_chromadb.PersistentClient.return_value = mock_client

        service = chroma.ChromaService(db_path=tmp_path / ".chroma")
        result = service.list_all_collections()

        assert result == ["seedgo_observations", "cli_local"]


# ===========================================================================
# Tests: Public API — store_vectors
# ===========================================================================


class TestPublicStoreVectors:
    """Test public store_vectors function."""

    def test_empty_embeddings_returns_success_zero_count(self, monkeypatch):
        chroma, _ = _import_chroma(monkeypatch)
        _reset_globals(chroma)

        result = chroma.store_vectors("SEEDGO", "observations", [], [], [])

        assert result["success"] is True
        assert result["count"] == 0

    def test_length_mismatch_returns_failure(self, monkeypatch):
        chroma, _ = _import_chroma(monkeypatch)
        _reset_globals(chroma)

        result = chroma.store_vectors(
            "SEEDGO",
            "observations",
            embeddings=[[0.1, 0.2]],
            documents=["doc1", "doc2"],
            metadatas=[{"k": "v"}],
        )

        assert result["success"] is False
        assert "Length mismatch" in result["error"]

    def test_successful_store_delegates_to_service(self, monkeypatch, tmp_path):
        chroma, mock_chromadb = _import_chroma(monkeypatch)
        _reset_globals(chroma)

        mock_collection = MagicMock()
        mock_collection.count.side_effect = [0, 2]

        mock_client = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_collection
        mock_chromadb.PersistentClient.return_value = mock_client

        result = chroma.store_vectors(
            "SEEDGO",
            "observations",
            embeddings=[[0.1, 0.2], [0.3, 0.4]],
            documents=["doc1", "doc2"],
            metadatas=[{"branch": "SEEDGO"}, {"branch": "SEEDGO"}],
            db_path=tmp_path / ".chroma",
        )

        assert result["success"] is True
        assert result["count"] == 2
        assert result["collection"] == "seedgo_observations"

    def test_string_db_path_converts_to_path(self, monkeypatch, tmp_path):
        chroma, mock_chromadb = _import_chroma(monkeypatch)
        _reset_globals(chroma)

        mock_collection = MagicMock()
        mock_collection.count.side_effect = [0, 1]

        mock_client = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_collection
        mock_chromadb.PersistentClient.return_value = mock_client

        str_path = str(tmp_path / ".chroma")
        result = chroma.store_vectors(
            "CLI",
            "local",
            embeddings=[[0.1]],
            documents=["doc1"],
            metadatas=[{"branch": "CLI"}],
            db_path=str_path,
        )

        assert result["success"] is True
        # Verify PersistentClient was called with a string (Path converted internally)
        mock_chromadb.PersistentClient.assert_called()

    def test_service_exception_returns_failure(self, monkeypatch):
        chroma, mock_chromadb = _import_chroma(monkeypatch)
        _reset_globals(chroma)

        mock_chromadb.PersistentClient.side_effect = RuntimeError("DB error")

        result = chroma.store_vectors(
            "SEEDGO",
            "observations",
            embeddings=[[0.1]],
            documents=["doc1"],
            metadatas=[{"k": "v"}],
        )

        assert result["success"] is False
        assert "Storage failed" in result["error"]


# ===========================================================================
# Tests: Public API — get_collection_stats
# ===========================================================================


class TestPublicGetCollectionStats:
    """Test public get_collection_stats function."""

    def test_success_returns_stats(self, monkeypatch, tmp_path):
        chroma, mock_chromadb = _import_chroma(monkeypatch)
        _reset_globals(chroma)

        mock_collection = MagicMock()
        mock_collection.count.return_value = 10

        mock_client = MagicMock()
        mock_client.get_collection.return_value = mock_collection
        mock_chromadb.PersistentClient.return_value = mock_client

        # Pre-create the global service so _get_service uses our mock
        setattr(chroma, "_chroma_service", chroma.ChromaService(db_path=tmp_path / ".chroma"))

        result = chroma.get_collection_stats("seedgo", "observations")

        assert result["success"] is True
        assert result["exists"] is True
        assert result["vector_count"] == 10

    def test_nonexistent_collection_still_succeeds(self, monkeypatch, tmp_path):
        chroma, mock_chromadb = _import_chroma(monkeypatch)
        _reset_globals(chroma)

        mock_client = MagicMock()
        mock_client.get_collection.side_effect = Exception("not found")
        mock_chromadb.PersistentClient.return_value = mock_client

        setattr(chroma, "_chroma_service", chroma.ChromaService(db_path=tmp_path / ".chroma"))

        result = chroma.get_collection_stats("missing", "local")

        assert result["success"] is True
        assert result["exists"] is False
        assert result["vector_count"] == 0


# ===========================================================================
# Tests: Public API — list_all_collections
# ===========================================================================


class TestPublicListAllCollections:
    """Test public list_all_collections function."""

    def test_returns_collection_list(self, monkeypatch, tmp_path):
        chroma, mock_chromadb = _import_chroma(monkeypatch)
        _reset_globals(chroma)

        mock_col = MagicMock()
        mock_col.name = "seedgo_observations"

        mock_client = MagicMock()
        mock_client.list_collections.return_value = [mock_col]
        mock_chromadb.PersistentClient.return_value = mock_client

        setattr(chroma, "_chroma_service", chroma.ChromaService(db_path=tmp_path / ".chroma"))

        result = chroma.list_all_collections()

        assert result["success"] is True
        assert result["collections"] == ["seedgo_observations"]
        assert result["count"] == 1


# ===========================================================================
# Tests: Public API — get_database_info
# ===========================================================================


class TestPublicGetDatabaseInfo:
    """Test public get_database_info function."""

    def test_returns_db_info(self, monkeypatch, tmp_path):
        chroma, mock_chromadb = _import_chroma(monkeypatch)
        _reset_globals(chroma)

        mock_col1 = MagicMock()
        mock_col1.name = "seedgo_observations"
        mock_col2 = MagicMock()
        mock_col2.name = "cli_local"

        mock_client = MagicMock()
        mock_client.list_collections.return_value = [mock_col1, mock_col2]
        mock_chromadb.PersistentClient.return_value = mock_client

        db_path = tmp_path / ".chroma"
        setattr(chroma, "_chroma_service", chroma.ChromaService(db_path=db_path))

        result = chroma.get_database_info()

        assert result["success"] is True
        assert result["db_path"] == str(db_path)
        assert result["collections_count"] == 2
        assert result["collections"] == ["seedgo_observations", "cli_local"]


# ===========================================================================
# Tests: Public API — search_vectors
# ===========================================================================


class TestPublicSearchVectors:
    """Test public search_vectors function."""

    def test_search_specific_branch_and_type(self, monkeypatch, tmp_path):
        chroma, mock_chromadb = _import_chroma(monkeypatch)
        _reset_globals(chroma)

        mock_collection = MagicMock()
        mock_collection.query.return_value = {
            "documents": [["doc1", "doc2"]],
            "metadatas": [[{"branch": "SEEDGO"}, {"branch": "SEEDGO"}]],
            "distances": [[0.1, 0.3]],
            "ids": [["id1", "id2"]],
        }

        mock_client = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_collection
        mock_client.get_collection.return_value = mock_collection
        mock_chromadb.PersistentClient.return_value = mock_client

        db_path = tmp_path / ".chroma"
        setattr(chroma, "_chroma_service", chroma.ChromaService(db_path=db_path))

        query_emb = [0.1] * 384
        result = chroma.search_vectors(query_emb, branch="SEEDGO", memory_type="observations")

        assert result["success"] is True
        assert result["collections_searched"] == 1
        assert result["total_results"] == 2
        assert result["results"][0]["document"] == "doc1"
        assert result["results"][0]["distance"] == 0.1

    def test_global_search_no_branch_filter(self, monkeypatch, tmp_path):
        chroma, mock_chromadb = _import_chroma(monkeypatch)
        _reset_globals(chroma)

        mock_col1 = MagicMock()
        mock_col1.name = "seedgo_observations"
        mock_col2 = MagicMock()
        mock_col2.name = "cli_local"

        mock_collection = MagicMock()
        mock_collection.query.return_value = {
            "documents": [["result_doc"]],
            "metadatas": [[{"branch": "test"}]],
            "distances": [[0.2]],
            "ids": [["id_global"]],
        }

        mock_client = MagicMock()
        mock_client.list_collections.return_value = [mock_col1, mock_col2]
        mock_client.get_collection.return_value = mock_collection
        mock_chromadb.PersistentClient.return_value = mock_client

        db_path = tmp_path / ".chroma"
        setattr(chroma, "_chroma_service", chroma.ChromaService(db_path=db_path))

        result = chroma.search_vectors([0.1] * 384)

        assert result["success"] is True
        assert result["collections_searched"] == 2
        # Two collections searched, each returns 1 result
        assert result["total_results"] == 2

    def test_search_with_no_matching_collections(self, monkeypatch, tmp_path):
        chroma, mock_chromadb = _import_chroma(monkeypatch)
        _reset_globals(chroma)

        mock_client = MagicMock()
        mock_client.list_collections.return_value = []
        mock_chromadb.PersistentClient.return_value = mock_client

        db_path = tmp_path / ".chroma"
        setattr(chroma, "_chroma_service", chroma.ChromaService(db_path=db_path))

        result = chroma.search_vectors([0.1] * 384)

        assert result["success"] is True
        assert result["results"] == []
        assert "No matching collections" in result.get("message", "")

    def test_search_with_string_db_path(self, monkeypatch, tmp_path):
        chroma, mock_chromadb = _import_chroma(monkeypatch)
        _reset_globals(chroma)

        mock_collection = MagicMock()
        mock_collection.query.return_value = {
            "documents": [["found"]],
            "metadatas": [[{"k": "v"}]],
            "distances": [[0.05]],
            "ids": [["id_str"]],
        }

        mock_client = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_collection
        mock_client.get_collection.return_value = mock_collection
        mock_chromadb.PersistentClient.return_value = mock_client

        str_path = str(tmp_path / ".chroma")
        result = chroma.search_vectors(
            [0.1] * 384,
            branch="CLI",
            memory_type="local",
            db_path=str_path,
        )

        assert result["success"] is True
        assert len(result["results"]) == 1

    def test_search_handles_collection_error_gracefully(self, monkeypatch, tmp_path):
        chroma, mock_chromadb = _import_chroma(monkeypatch)
        _reset_globals(chroma)

        mock_col = MagicMock()
        mock_col.name = "broken_collection"

        mock_client = MagicMock()
        mock_client.list_collections.return_value = [mock_col]
        mock_client.get_collection.side_effect = Exception("Corrupt collection")
        mock_chromadb.PersistentClient.return_value = mock_client

        db_path = tmp_path / ".chroma"
        setattr(chroma, "_chroma_service", chroma.ChromaService(db_path=db_path))

        result = chroma.search_vectors([0.1] * 384)

        assert result["success"] is True
        assert result["total_results"] == 0

    def test_search_results_sorted_by_distance(self, monkeypatch, tmp_path):
        chroma, mock_chromadb = _import_chroma(monkeypatch)
        _reset_globals(chroma)

        mock_collection = MagicMock()
        mock_collection.query.return_value = {
            "documents": [["far_doc", "near_doc", "mid_doc"]],
            "metadatas": [[{"k": "1"}, {"k": "2"}, {"k": "3"}]],
            "distances": [[0.9, 0.1, 0.5]],
            "ids": [["id_far", "id_near", "id_mid"]],
        }

        mock_client = MagicMock()
        mock_client.get_collection.return_value = mock_collection
        mock_chromadb.PersistentClient.return_value = mock_client

        db_path = tmp_path / ".chroma"
        setattr(chroma, "_chroma_service", chroma.ChromaService(db_path=db_path))

        result = chroma.search_vectors(
            [0.1] * 384,
            branch="test",
            memory_type="local",
        )

        assert result["success"] is True
        distances = [r["distance"] for r in result["results"]]
        assert distances == sorted(distances)


# ===========================================================================
# Tests: Singleton / get_client
# ===========================================================================


class TestGetClient:
    """Test get_client singleton behaviour."""

    def test_caches_client_per_path(self, monkeypatch, tmp_path):
        chroma, mock_chromadb = _import_chroma(monkeypatch)
        _reset_globals(chroma)

        mock_client = MagicMock()
        mock_chromadb.PersistentClient.return_value = mock_client

        path = tmp_path / ".chroma"
        client1 = chroma.get_client(path)
        client2 = chroma.get_client(path)

        assert client1 is client2
        # PersistentClient should only be called once for same path
        assert mock_chromadb.PersistentClient.call_count == 1

    def test_different_paths_get_different_clients(self, monkeypatch, tmp_path):
        chroma, mock_chromadb = _import_chroma(monkeypatch)
        _reset_globals(chroma)

        mock_client_a = MagicMock()
        mock_client_b = MagicMock()
        mock_chromadb.PersistentClient.side_effect = [mock_client_a, mock_client_b]

        path_a = tmp_path / ".chroma_a"
        path_b = tmp_path / ".chroma_b"

        client_a = chroma.get_client(path_a)
        client_b = chroma.get_client(path_b)

        assert client_a is not client_b
        assert mock_chromadb.PersistentClient.call_count == 2
