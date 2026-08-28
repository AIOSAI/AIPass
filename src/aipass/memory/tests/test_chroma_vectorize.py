# ===================AIPASS====================
# META DATA HEADER
# Name: tests/test_chroma_vectorize.py
# Date: 2026-08-23
# Version: 1.0.0
# Category: memory/tests
# =============================================

"""Tests for the text-in vectorize_and_store operation.

Covers: _vectorize_and_store

The gap this closes: callers had to pre-encode their own texts, which meant each
caller picked an embedding model. Two callers picking differently put vectors
from two models in one collection, which is silently unsearchable. The model
choice belongs to the branch that owns the store.

All tests stub the embedder subprocess -- no live model load or ChromaDB.
"""

import json

from aipass.memory.apps.handlers.storage import chroma_subprocess


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeCompleted:
    def __init__(self, stdout, returncode=0, stderr=""):
        self.stdout = stdout
        self.returncode = returncode
        self.stderr = stderr


def _stub_embedder(monkeypatch, payload, returncode=0, stderr=""):
    """Stand in for the embed subprocess; capture what it was asked to encode."""
    seen = {}

    def _run(cmd, input=None, capture_output=None, text=None, timeout=None):
        seen["texts"] = json.loads(input)["texts"]
        seen["timeout"] = timeout
        return _FakeCompleted(json.dumps(payload) if payload is not None else "", returncode, stderr)

    monkeypatch.setattr(chroma_subprocess.subprocess, "run", _run)
    return seen


def _stub_store(monkeypatch):
    """Capture what reached the storage layer."""
    seen = {}

    def _store(branch, memory_type, embeddings, documents, metadatas, db_path=None):
        seen.update(
            branch=branch, memory_type=memory_type, embeddings=embeddings, documents=documents, metadatas=metadatas
        )
        return {"success": True, "collection": f"{branch.lower()}_{memory_type.lower()}", "count": len(documents)}

    monkeypatch.setattr(chroma_subprocess, "_store_vectors", _store)
    return seen


# ---------------------------------------------------------------------------
# 1. The happy path
# ---------------------------------------------------------------------------


class TestVectorizeAndStore:
    def test_encodes_then_stores(self, monkeypatch):
        embed = _stub_embedder(monkeypatch, {"success": True, "embeddings": [[0.1, 0.2], [0.3, 0.4]]})
        store = _stub_store(monkeypatch)

        result = chroma_subprocess._vectorize_and_store(
            branch="AI_MAIL",
            memory_type="email_sent",
            texts=["first mail", "second mail"],
            metadatas=[{"subject": "a"}, {"subject": "b"}],
        )

        assert result["success"] is True
        assert embed["texts"] == ["first mail", "second mail"]
        assert store["embeddings"] == [[0.1, 0.2], [0.3, 0.4]]
        assert store["documents"] == ["first mail", "second mail"]
        assert store["branch"] == "AI_MAIL"

    def test_empty_texts_is_a_no_op_success(self, monkeypatch):
        _stub_store(monkeypatch)
        result = chroma_subprocess._vectorize_and_store("AI_MAIL", "email_sent", [], [])
        assert result["success"] is True
        assert result["count"] == 0

    def test_embedder_timeout_scales_with_volume(self, monkeypatch):
        embed = _stub_embedder(monkeypatch, {"success": True, "embeddings": [[0.1]] * 50})
        _stub_store(monkeypatch)

        chroma_subprocess._vectorize_and_store("AI_MAIL", "email_sent", ["t"] * 50, [{}] * 50)

        assert embed["timeout"] >= 50


# ---------------------------------------------------------------------------
# 2. Failing loud -- the whole point of the operation
# ---------------------------------------------------------------------------


class TestVectorizeFailsLoud:
    """Every failure returns success:false with a reason. Nothing is guessed."""

    def test_embedder_nonzero_exit_is_reported(self, monkeypatch):
        _stub_embedder(monkeypatch, None, returncode=1, stderr="fastembed exploded")
        _stub_store(monkeypatch)

        result = chroma_subprocess._vectorize_and_store("AI_MAIL", "email_sent", ["x"], [{}])

        assert result["success"] is False
        assert "fastembed exploded" in result["error"]

    def test_embedder_refusal_is_reported(self, monkeypatch):
        _stub_embedder(monkeypatch, {"success": False, "error": "model missing"})
        _stub_store(monkeypatch)

        result = chroma_subprocess._vectorize_and_store("AI_MAIL", "email_sent", ["x"], [{}])

        assert result["success"] is False
        assert "model missing" in result["error"]

    def test_unreadable_embedder_output_is_not_success(self, monkeypatch):
        _stub_embedder(monkeypatch, None)
        _stub_store(monkeypatch)

        result = chroma_subprocess._vectorize_and_store("AI_MAIL", "email_sent", ["x"], [{}])

        assert result["success"] is False

    def test_embedding_count_mismatch_is_refused(self, monkeypatch):
        """Two texts in, one vector out -- storing that would misalign every row."""
        _stub_embedder(monkeypatch, {"success": True, "embeddings": [[0.1]]})
        store = _stub_store(monkeypatch)

        result = chroma_subprocess._vectorize_and_store("AI_MAIL", "email_sent", ["a", "b"], [{}, {}])

        assert result["success"] is False
        assert store == {}

    def test_metadata_count_mismatch_is_refused(self, monkeypatch):
        """zip() would truncate silently and drop a row's provenance."""
        _stub_embedder(monkeypatch, {"success": True, "embeddings": [[0.1], [0.2]]})
        store = _stub_store(monkeypatch)

        result = chroma_subprocess._vectorize_and_store("AI_MAIL", "email_sent", ["a", "b"], [{}])

        assert result["success"] is False
        assert store == {}

    def test_missing_branch_is_refused(self, monkeypatch):
        _stub_embedder(monkeypatch, {"success": True, "embeddings": [[0.1]]})
        _stub_store(monkeypatch)

        result = chroma_subprocess._vectorize_and_store("", "email_sent", ["a"], [{}])

        assert result["success"] is False


# ---------------------------------------------------------------------------
# 3. Reachable as an operation -- the wire ai_mail actually calls
# ---------------------------------------------------------------------------


class TestOperationIsRouted:
    def test_vectorize_and_store_is_a_known_operation(self):
        source = chroma_subprocess.__file__
        with open(source, encoding="utf-8") as fh:
            body = fh.read()
        assert 'operation == "vectorize_and_store"' in body
