# ===================AIPASS====================
# META DATA HEADER
# Name: tests/test_vector.py
# Date: 2026-04-03
# Version: 2.0.0
# Category: memory/tests
# =============================================

"""Tests for vector embedding handler.

Covers:
  - vector/embedder.py  EmbeddingService class (init, encode_batch with
    pre-sort by length and order restoration)
  - vector/embedder.py  Public API functions (encode_batch, encode_memories,
    get_model_info)
  - vector/embedder.py  Singleton management (_get_service, global reset)

All tests use mocks/tmp_path -- no live fastembed or ONNX access.
"""

# ---------------------------------------------------------------------------
# PARKED 2026-08-14 — @devpulse's ruling, following Patrick's symbolic-tier park.
# vector/embedder.py had exactly two importers, symbolic/storage.py and
# symbolic/retriever.py, and both went into .archive/parked_symbolic_20260814/.
# The live lane runs vector/embed_subprocess.py by path instead — it is
# self-contained and imports nothing from the package. These tests are KEPT, not
# deleted: they document the utility for revival.
# Active curated-truth piece: Compass — drone @devpulse compass.
# Revive: .archive/parked_symbolic_20260814/README.md
# ---------------------------------------------------------------------------
import pytest as _parked

_parked.skip(
    "vector/embedder.py PARKED 2026-08-14 with the symbolic fragments tier — "
    "its only importers were the parked handlers; the live lane runs embed_subprocess.py "
    "by path. Revive via .archive/parked_symbolic_20260814/README.md",
    allow_module_level=True,
)

import sys
from typing import Any
from unittest.mock import MagicMock

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("chromadb")


# ---------------------------------------------------------------------------
# Import helper -- fastembed must be mocked
# ---------------------------------------------------------------------------


def _import_embedder(monkeypatch):
    """Import embedder module with mocked ML dependencies.

    Returns:
        Tuple of (embedder module, dict of mock objects)
    """
    mock_fastembed = MagicMock()
    mock_model = MagicMock()
    mock_fastembed.TextEmbedding.return_value = mock_model
    monkeypatch.setitem(sys.modules, "fastembed", mock_fastembed)

    # Clear cached module for fresh import
    sys.modules.pop("aipass.memory.apps.handlers.vector.embedder", None)
    parent = sys.modules.get("aipass.memory.apps.handlers.vector")
    if parent is not None and hasattr(parent, "embedder"):
        delattr(parent, "embedder")

    from aipass.memory.apps.handlers.vector import embedder

    return embedder, {
        "fastembed": mock_fastembed,
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

        fake_embeddings = [np.array([0.1, 0.2, 0.3]), np.array([0.4, 0.5, 0.6])]
        mocks["model"].embed.return_value = iter(fake_embeddings)

        result = embedder.encode_batch(["hello world", "test text"])

        assert result["success"] is True
        assert result["count"] == 2
        assert result["dimension"] == 384

    def test_service_failure_returns_error(self, monkeypatch):
        embedder, mocks = _import_embedder(monkeypatch)
        _reset_globals(embedder)

        mocks["model"].embed.side_effect = RuntimeError("ONNX runtime error")

        result = embedder.encode_batch(["some text"])

        assert result["success"] is False
        assert "Encoding failed" in result["error"]

    def test_service_init_failure_returns_error(self, monkeypatch):
        embedder, mocks = _import_embedder(monkeypatch)
        _reset_globals(embedder)

        mocks["fastembed"].TextEmbedding.side_effect = RuntimeError("Model not found")

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

        fake_embeddings = [np.array([0.1, 0.2])]
        mocks["model"].embed.return_value = iter(fake_embeddings)

        memories = [{"content": "Important observation", "timestamp": "2026-01-01"}]
        result = embedder.encode_memories(memories)

        assert result["success"] is True
        assert result["count"] == 1
        assert result["memories"] == memories
        call_args = mocks["model"].embed.call_args
        texts_passed = call_args[0][0]
        assert texts_passed == ["Important observation"]

    def test_extracts_text_field(self, monkeypatch):
        embedder, mocks = _import_embedder(monkeypatch)
        _reset_globals(embedder)

        fake_embeddings = [np.array([0.1, 0.2])]
        mocks["model"].embed.return_value = iter(fake_embeddings)

        memories = [{"text": "Session summary", "date": "2026-02-01"}]
        result = embedder.encode_memories(memories)

        assert result["success"] is True
        assert result["count"] == 1
        call_args = mocks["model"].embed.call_args
        texts_passed = call_args[0][0]
        assert texts_passed == ["Session summary"]

    def test_falls_back_to_str_representation(self, monkeypatch):
        embedder, mocks = _import_embedder(monkeypatch)
        _reset_globals(embedder)

        fake_embeddings = [np.array([0.1, 0.2])]
        mocks["model"].embed.return_value = iter(fake_embeddings)

        memories = [{"arbitrary_key": "value123", "number": 42}]
        result = embedder.encode_memories(memories)

        assert result["success"] is True
        assert result["count"] == 1
        call_args = mocks["model"].embed.call_args
        texts_passed = call_args[0][0]
        assert "arbitrary_key" in texts_passed[0]

    def test_encoding_failure_propagates(self, monkeypatch):
        embedder, mocks = _import_embedder(monkeypatch)
        _reset_globals(embedder)

        mocks["model"].embed.side_effect = RuntimeError("Encoding crashed")

        memories = [{"content": "test memory"}]
        result = embedder.encode_memories(memories)

        assert result["success"] is False

    def test_multiple_memories_mixed_fields(self, monkeypatch):
        embedder, mocks = _import_embedder(monkeypatch)
        _reset_globals(embedder)

        fake_embeddings = [np.array([0.1]), np.array([0.2]), np.array([0.3])]
        mocks["model"].embed.return_value = iter(fake_embeddings)

        memories = [
            {"content": "first"},
            {"text": "second"},
            {"other": "third"},
        ]
        result = embedder.encode_memories(memories)

        assert result["success"] is True
        assert result["count"] == 3
        assert result["memories"] is memories

        call_args = mocks["model"].embed.call_args
        texts_passed = call_args[0][0]
        assert texts_passed[0] == "first"
        assert texts_passed[1] == "second"
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
        assert result["model_name"] == "sentence-transformers/all-MiniLM-L6-v2"
        assert result["dimension"] == 384

    def test_service_init_failure_returns_error(self, monkeypatch):
        embedder, mocks = _import_embedder(monkeypatch)
        _reset_globals(embedder)

        mocks["fastembed"].TextEmbedding.side_effect = ImportError("no model")

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

        received_texts: list[Any] = []

        def fake_embed(texts):
            received_texts.append(list(texts))
            return iter([np.array([float(i)] * 3) for i in range(len(texts))])

        mocks["model"].embed.side_effect = fake_embed

        service = embedder.EmbeddingService()
        texts = ["long text here", "ab", "medium text"]
        result = service.encode_batch(texts)

        assert received_texts[0] == ["ab", "medium text", "long text here"]

        assert result["count"] == 3
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

        mocks["model"].embed.return_value = iter([np.array([0.5, 0.6])])

        service = embedder.EmbeddingService()
        result = service.encode_batch(["only one"])

        assert result["count"] == 1
        np.testing.assert_array_equal(result["embeddings"][0], [0.5, 0.6])
