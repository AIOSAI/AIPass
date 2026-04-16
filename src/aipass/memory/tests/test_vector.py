# ===================AIPASS====================
# META DATA HEADER
# Name: tests/test_vector.py
# Date: 2026-04-03
# Version: 1.0.0
# Category: memory/tests
# =============================================

"""Tests for vector embedding handler.

Covers:
  - vector/embedder.py  EmbeddingService class (init, encode_batch with
    pre-sort by length and order restoration, GPU cleanup path)
  - vector/embedder.py  Public API functions (encode_batch, encode_memories,
    get_model_info)
  - vector/embedder.py  Singleton management (_get_service, global reset)

All tests use mocks/tmp_path -- no live sentence-transformers, torch, or GPU access.
"""

import sys
from typing import Any
from unittest.mock import MagicMock

import numpy as np


# ---------------------------------------------------------------------------
# Import helper -- torch and sentence_transformers must be mocked
# ---------------------------------------------------------------------------


def _import_embedder(monkeypatch):
    """Import embedder module with mocked ML dependencies.

    Returns:
        Tuple of (embedder module, dict of mock objects)
    """
    mock_torch = MagicMock()
    mock_torch.cuda.is_available.return_value = False
    monkeypatch.setitem(sys.modules, "torch", mock_torch)

    mock_st = MagicMock()
    mock_model = MagicMock()
    mock_st.SentenceTransformer.return_value = mock_model
    monkeypatch.setitem(sys.modules, "sentence_transformers", mock_st)

    # Clear cached module for fresh import
    sys.modules.pop("aipass.memory.apps.handlers.vector.embedder", None)
    parent = sys.modules.get("aipass.memory.apps.handlers.vector")
    if parent is not None and hasattr(parent, "embedder"):
        delattr(parent, "embedder")

    from aipass.memory.apps.handlers.vector import embedder

    return embedder, {
        "torch": mock_torch,
        "st": mock_st,
        "model": mock_model,
    }


def _reset_globals(embedder) -> None:
    """Reset module-level singleton between tests."""
    setattr(embedder, "_embedding_service", None)


# ===========================================================================
# Tests: Public API -- encode_batch
# ===========================================================================


class TestPublicEncodeBatch:
    """Test public encode_batch function."""

    def test_empty_list_returns_success_zero_count(self, monkeypatch):
        embedder, _ = _import_embedder(monkeypatch)
        _reset_globals(embedder)

        result = embedder.encode_batch([])

        assert result["success"] is True
        assert result["count"] == 0
        assert result["embeddings"] == []

    def test_successful_encoding(self, monkeypatch):
        embedder, mocks = _import_embedder(monkeypatch)
        _reset_globals(embedder)

        fake_embeddings = np.array([[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]])
        mocks["model"].encode.return_value = fake_embeddings

        result = embedder.encode_batch(["hello world", "test text"])

        assert result["success"] is True
        assert result["count"] == 2
        assert result["dimension"] == 384

    def test_service_failure_returns_error(self, monkeypatch):
        embedder, mocks = _import_embedder(monkeypatch)
        _reset_globals(embedder)

        mocks["model"].encode.side_effect = RuntimeError("CUDA out of memory")

        result = embedder.encode_batch(["some text"])

        assert result["success"] is False
        assert "Encoding failed" in result["error"]

    def test_service_init_failure_returns_error(self, monkeypatch):
        embedder, mocks = _import_embedder(monkeypatch)
        _reset_globals(embedder)

        mocks["st"].SentenceTransformer.side_effect = RuntimeError("Model not found")

        result = embedder.encode_batch(["some text"])

        assert result["success"] is False
        assert "failed" in result["error"].lower()


# ===========================================================================
# Tests: Public API -- encode_memories
# ===========================================================================


class TestPublicEncodeMemories:
    """Test public encode_memories function."""

    def test_empty_list_returns_success(self, monkeypatch):
        embedder, _ = _import_embedder(monkeypatch)
        _reset_globals(embedder)

        result = embedder.encode_memories([])

        assert result["success"] is True
        assert result["count"] == 0
        assert result["embeddings"] == []
        assert result["memories"] == []

    def test_extracts_content_field(self, monkeypatch):
        embedder, mocks = _import_embedder(monkeypatch)
        _reset_globals(embedder)

        fake_embeddings = np.array([[0.1, 0.2]])
        mocks["model"].encode.return_value = fake_embeddings

        memories = [{"content": "Important observation", "timestamp": "2026-01-01"}]
        result = embedder.encode_memories(memories)

        assert result["success"] is True
        assert result["count"] == 1
        assert result["memories"] == memories
        # Verify the model was called with extracted text
        call_args = mocks["model"].encode.call_args
        texts_passed = call_args[0][0]
        assert texts_passed == ["Important observation"]

    def test_extracts_text_field(self, monkeypatch):
        embedder, mocks = _import_embedder(monkeypatch)
        _reset_globals(embedder)

        fake_embeddings = np.array([[0.1, 0.2]])
        mocks["model"].encode.return_value = fake_embeddings

        memories = [{"text": "Session summary", "date": "2026-02-01"}]
        result = embedder.encode_memories(memories)

        assert result["success"] is True
        assert result["count"] == 1
        call_args = mocks["model"].encode.call_args
        texts_passed = call_args[0][0]
        assert texts_passed == ["Session summary"]

    def test_falls_back_to_str_representation(self, monkeypatch):
        embedder, mocks = _import_embedder(monkeypatch)
        _reset_globals(embedder)

        fake_embeddings = np.array([[0.1, 0.2]])
        mocks["model"].encode.return_value = fake_embeddings

        memories = [{"arbitrary_key": "value123", "number": 42}]
        result = embedder.encode_memories(memories)

        assert result["success"] is True
        assert result["count"] == 1
        # The fallback is str(memory) which includes the full dict repr
        call_args = mocks["model"].encode.call_args
        texts_passed = call_args[0][0]
        assert "arbitrary_key" in texts_passed[0]

    def test_encoding_failure_propagates(self, monkeypatch):
        embedder, mocks = _import_embedder(monkeypatch)
        _reset_globals(embedder)

        mocks["model"].encode.side_effect = RuntimeError("Encoding crashed")

        memories = [{"content": "test memory"}]
        result = embedder.encode_memories(memories)

        assert result["success"] is False

    def test_multiple_memories_mixed_fields(self, monkeypatch):
        embedder, mocks = _import_embedder(monkeypatch)
        _reset_globals(embedder)

        fake_embeddings = np.array([[0.1], [0.2], [0.3]])
        mocks["model"].encode.return_value = fake_embeddings

        memories = [
            {"content": "first"},
            {"text": "second"},
            {"other": "third"},
        ]
        result = embedder.encode_memories(memories)

        assert result["success"] is True
        assert result["count"] == 3
        assert result["memories"] is memories

        call_args = mocks["model"].encode.call_args
        texts_passed = call_args[0][0]
        assert texts_passed[0] == "first"
        assert texts_passed[1] == "second"
        # Third falls back to str()
        assert "third" in texts_passed[2]


# ===========================================================================
# Tests: Public API -- get_model_info
# ===========================================================================


class TestPublicGetModelInfo:
    """Test public get_model_info function."""

    def test_returns_model_metadata(self, monkeypatch):
        embedder, _ = _import_embedder(monkeypatch)
        _reset_globals(embedder)

        result = embedder.get_model_info()

        assert result["success"] is True
        assert result["model_name"] == "all-MiniLM-L6-v2"
        assert result["dimension"] == 384
        assert result["batch_size"] == 16  # CPU batch size (GPU is mocked off)
        assert result["gpu_enabled"] is False

    def test_service_init_failure_returns_error(self, monkeypatch):
        embedder, mocks = _import_embedder(monkeypatch)
        _reset_globals(embedder)

        mocks["st"].SentenceTransformer.side_effect = ImportError("no model")

        result = embedder.get_model_info()

        assert result["success"] is False
        assert "error" in result


# ===========================================================================
# Tests: EmbeddingService class -- encode_batch internals
# ===========================================================================


class TestEmbeddingServiceEncodeBatch:
    """Test EmbeddingService.encode_batch pre-sort and order restoration."""

    def test_presorts_by_length_and_restores_order(self, monkeypatch):
        embedder, mocks = _import_embedder(monkeypatch)
        _reset_globals(embedder)

        # Track what texts the model receives (should be sorted by length)
        received_texts: list[Any] = []

        def fake_encode(texts, **kwargs):
            received_texts.append(list(texts))
            # Return embeddings matching the sorted input length
            return np.array([[float(i)] * 3 for i in range(len(texts))])

        mocks["model"].encode.side_effect = fake_encode

        service = embedder.EmbeddingService()
        texts = ["long text here", "ab", "medium text"]
        result = service.encode_batch(texts)

        # Model should receive texts sorted by length
        assert received_texts[0] == ["ab", "medium text", "long text here"]

        # But returned embeddings should be in original order
        assert result["count"] == 3
        # Index 0 was "long text here" (sorted position 2) -> embedding [2,2,2]
        # Index 1 was "ab" (sorted position 0) -> embedding [0,0,0]
        # Index 2 was "medium text" (sorted position 1) -> embedding [1,1,1]
        embs = result["embeddings"]
        np.testing.assert_array_equal(embs[0], [2.0, 2.0, 2.0])
        np.testing.assert_array_equal(embs[1], [0.0, 0.0, 0.0])
        np.testing.assert_array_equal(embs[2], [1.0, 1.0, 1.0])

    def test_empty_texts_returns_empty(self, monkeypatch):
        embedder, _ = _import_embedder(monkeypatch)
        _reset_globals(embedder)

        service = embedder.EmbeddingService()
        result = service.encode_batch([])

        assert result["count"] == 0
        assert result["embeddings"] == []
        assert result["dimension"] == 384

    def test_single_text_works(self, monkeypatch):
        embedder, mocks = _import_embedder(monkeypatch)
        _reset_globals(embedder)

        mocks["model"].encode.return_value = np.array([[0.5, 0.6]])

        service = embedder.EmbeddingService()
        result = service.encode_batch(["only one"])

        assert result["count"] == 1
        np.testing.assert_array_equal(result["embeddings"][0], [0.5, 0.6])


# ===========================================================================
# Tests: EmbeddingService -- GPU path
# ===========================================================================


class TestEmbeddingServiceGPU:
    """Test EmbeddingService GPU detection and cleanup."""

    def test_gpu_enabled_sets_larger_batch_size(self, monkeypatch):
        embedder, mocks = _import_embedder(monkeypatch)
        _reset_globals(embedder)

        mocks["torch"].cuda.is_available.return_value = True

        service = embedder.EmbeddingService()

        assert service.use_gpu is True
        assert service.batch_size == 64

    def test_gpu_cache_cleared_after_encode(self, monkeypatch):
        embedder, mocks = _import_embedder(monkeypatch)
        _reset_globals(embedder)

        mocks["torch"].cuda.is_available.return_value = True
        mocks["model"].encode.return_value = np.array([[0.1, 0.2]])

        service = embedder.EmbeddingService()
        service.encode_batch(["test text"])

        mocks["torch"].cuda.empty_cache.assert_called_once()

    def test_cpu_does_not_clear_gpu_cache(self, monkeypatch):
        embedder, mocks = _import_embedder(monkeypatch)
        _reset_globals(embedder)

        mocks["torch"].cuda.is_available.return_value = False
        mocks["model"].encode.return_value = np.array([[0.1, 0.2]])

        service = embedder.EmbeddingService()
        service.encode_batch(["test text"])

        mocks["torch"].cuda.empty_cache.assert_not_called()
