# =================== AIPass ====================
# Name: embedder.py
# Description: Vector Embedding Handler
# Version: 0.3.0
# Created: 2025-11-16
# Modified: 2026-05-07
# =============================================

"""
Vector Embedding Handler

Generates semantic embeddings using fastembed/all-MiniLM-L6-v2 (ONNX).

Purpose:
    Convert text memories into 384-dimensional vectors for semantic search.
    Optimized for batch processing (100 lines during rollover).

Dependencies (optional):
    - fastembed
"""

from typing import List, Dict, Any

from aipass.prax.apps.modules.logger import get_system_logger
from aipass.memory.apps.handlers.json import json_handler

logger = get_system_logger()


class EmbeddingService:
    """Embedding service using fastembed (ONNX runtime, no torch dependency)."""

    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2"):
        try:
            from fastembed import TextEmbedding
        except ImportError as e:
            logger.info(f"[embedder] Optional ML dependencies not available: {e}")
            raise ImportError(f"Embedding requires fastembed. Install with: pip install fastembed. Original error: {e}")

        self.model_name = model_name
        self.model = TextEmbedding(model_name)
        self.dimension = 384

    def encode_batch(self, texts: List[str]) -> Dict[str, Any]:
        """Encode texts to embeddings with pre-sort optimization."""
        if not texts:
            return {"embeddings": [], "count": 0, "dimension": self.dimension}

        sorted_pairs = sorted(enumerate(texts), key=lambda x: len(x[1]))
        sorted_indices: list[int] = [p[0] for p in sorted_pairs]
        sorted_text_list: list[str] = [p[1] for p in sorted_pairs]

        embeddings = list(self.model.embed(sorted_text_list))

        ordered_embeddings: List[Any] = [None] * len(texts)
        for original_idx, sorted_idx in enumerate(sorted_indices):
            ordered_embeddings[sorted_idx] = embeddings[original_idx]

        return {"embeddings": ordered_embeddings, "count": len(ordered_embeddings), "dimension": self.dimension}


_embedding_service = None


def _get_service() -> EmbeddingService:
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService()
    return _embedding_service


def encode_batch(texts: List[str]) -> Dict[str, Any]:
    """
    Encode batch of texts to embeddings.

    Args:
        texts: List of text strings to encode

    Returns:
        Dict with embeddings and metadata
    """
    if not texts:
        return {"success": True, "embeddings": [], "count": 0, "message": "No texts provided"}

    try:
        service = _get_service()
        result = service.encode_batch(texts)

        json_handler.log_operation(
            "vector_encode_batch",
            {"count": result.get("count", 0), "dimension": result.get("dimension", 0), "success": True},
        )
        return {"success": True, **result}

    except Exception as e:
        logger.error(f"[embedder] Batch encoding failed: {e}")
        return {"success": False, "error": f"Encoding failed: {e}"}


def encode_memories(memories: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Encode memory entries to embeddings.

    Args:
        memories: List of memory entry dicts (from extraction)

    Returns:
        Dict with embeddings and original memories
    """
    if not memories:
        return {"success": True, "embeddings": [], "memories": [], "count": 0, "message": "No memories provided"}

    texts = []
    for memory in memories:
        text = memory.get("content") or memory.get("text") or memory.get("message") or str(memory)
        texts.append(text)

    encode_result = encode_batch(texts)

    if not encode_result["success"]:
        return encode_result

    return {
        "success": True,
        "embeddings": encode_result["embeddings"],
        "memories": memories,
        "count": len(memories),
        "dimension": encode_result["dimension"],
    }


def get_model_info() -> Dict[str, Any]:
    """Get embedding model information."""
    try:
        service = _get_service()

        return {
            "success": True,
            "model_name": service.model_name,
            "dimension": service.dimension,
        }
    except Exception as e:
        logger.warning(f"[embedder] Failed to get model info: {e}")
        return {"success": False, "error": f"Failed to get model info: {e}"}
