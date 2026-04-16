# =================== AIPass ====================
# Name: embedder.py
# Description: Vector Embedding Handler
# Version: 0.2.0
# Created: 2025-11-16
# Modified: 2026-03-06
# =============================================

"""
Vector Embedding Handler

Generates semantic embeddings using sentence-transformers/all-MiniLM-L6-v2.
Implements production best practices from research.

Purpose:
    Convert text memories into 384-dimensional vectors for semantic search.
    Optimized for batch processing (100 lines during rollover).

Best Practices Applied:
    - Pre-sort by length (30% padding reduction)
    - Built-in normalization (L2 distance requirement)
    - GPU memory cleanup (prevent VRAM leaks)
    - Batch size optimization (64 GPU, 16 CPU)
    - Singleton pattern (model loaded once)

Dependencies (optional):
    - sentence-transformers
    - torch
"""

from typing import List, Dict, Any

from aipass.prax.apps.modules.logger import get_system_logger
from aipass.memory.apps.handlers.json import json_handler

logger = get_system_logger()

# No service imports - handlers are pure workers (3-tier architecture)
# No module imports (handler independence)


# =============================================================================
# EMBEDDING SERVICE (Singleton)
# =============================================================================


class EmbeddingService:
    """
    Production-ready embedding service

    Implements best practices:
    - Batch size optimization (64 GPU, 16 CPU)
    - Pre-sorting by length (reduces padding waste 30%)
    - Built-in normalization (critical for L2 distance)
    - GPU memory cleanup (prevents VRAM leaks)
    """

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        """
        Initialize embedding service

        Args:
            model_name: HuggingFace model identifier

        Raises:
            ImportError: If sentence-transformers or torch are not installed
        """
        # Late imports (heavy optional dependencies)
        try:
            import torch
            from sentence_transformers import SentenceTransformer
        except ImportError as e:
            logger.info(f"[embedder] Optional ML dependencies not available: {e}")
            raise ImportError(
                f"Embedding requires sentence-transformers and torch. "
                f"Install with: pip install sentence-transformers torch. "
                f"Original error: {e}"
            )

        self.model_name = model_name
        self.model = SentenceTransformer(model_name)

        # GPU optimization if available
        self.use_gpu = torch.cuda.is_available()
        if self.use_gpu:
            self.model = self.model.to("cuda")
            self.batch_size = 64
        else:
            self.batch_size = 16

        self.dimension = 384  # all-MiniLM-L6-v2 output dimension

    def encode_batch(self, texts: List[str]) -> Dict[str, Any]:
        """
        Encode batch of texts with all optimizations

        Best practices applied:
        1. Pre-sort by length (reduces padding waste)
        2. Batch processing (optimal batch size)
        3. Built-in normalization (L2 distance requirement)
        4. GPU cleanup (prevent VRAM leaks)

        Args:
            texts: List of text strings to encode

        Returns:
            Dict with embeddings and metadata
        """
        import torch

        if not texts:
            return {"embeddings": [], "count": 0, "dimension": self.dimension}

        # Pre-sort by length (reduces padding waste by 30%)
        sorted_pairs = sorted(enumerate(texts), key=lambda x: len(x[1]))
        sorted_indices: list[int] = [p[0] for p in sorted_pairs]
        sorted_text_list: list[str] = [p[1] for p in sorted_pairs]

        # Encode with optimal settings
        embeddings = self.model.encode(
            sorted_text_list,
            batch_size=self.batch_size,
            convert_to_tensor=False,  # Return numpy for Chroma
            normalize_embeddings=True,  # Critical for L2 distance
            show_progress_bar=False,
        )

        # Restore original order
        ordered_embeddings = [None] * len(texts)
        for original_idx, sorted_idx in enumerate(sorted_indices):
            ordered_embeddings[sorted_idx] = embeddings[original_idx]

        # Cleanup GPU memory if used
        if self.use_gpu:
            torch.cuda.empty_cache()

        return {"embeddings": ordered_embeddings, "count": len(ordered_embeddings), "dimension": self.dimension}


# Global service instance (singleton pattern)
_embedding_service = None


def _get_service() -> EmbeddingService:
    """
    Get or create embedding service singleton

    Lazy initialization - model loaded on first use
    """
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService()
    return _embedding_service


# =============================================================================
# PUBLIC API
# =============================================================================


def encode_batch(texts: List[str]) -> Dict[str, Any]:
    """
    Encode batch of texts to embeddings

    This is the main public API. Delegates to singleton service
    to avoid reloading the model.

    Args:
        texts: List of text strings to encode

    Returns:
        Dict with embeddings and metadata

    Example:
        result = encode_batch(["memory 1", "memory 2"])
        if result['success']:
            embeddings = result['embeddings']
            # Each embedding is 384-dim numpy array
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
    Encode memory entries to embeddings

    Extracts text from memory entries and encodes them.
    Preserves original memory structure for metadata.

    Args:
        memories: List of memory entry dicts (from extraction)

    Returns:
        Dict with embeddings and original memories

    Example:
        memories = [{"content": "...", "timestamp": "..."}]
        result = encode_memories(memories)
        embeddings = result['embeddings']
        original = result['memories']
    """
    if not memories:
        return {"success": True, "embeddings": [], "memories": [], "count": 0, "message": "No memories provided"}

    # Extract text content from memories
    texts = []
    for memory in memories:
        # Try common fields for text content
        text = (
            memory.get("content")
            or memory.get("text")
            or memory.get("message")
            or str(memory)  # Fallback to string representation
        )
        texts.append(text)

    # Encode texts
    encode_result = encode_batch(texts)

    if not encode_result["success"]:
        return encode_result

    # Combine embeddings with original memories
    return {
        "success": True,
        "embeddings": encode_result["embeddings"],
        "memories": memories,
        "count": len(memories),
        "dimension": encode_result["dimension"],
    }


def get_model_info() -> Dict[str, Any]:
    """
    Get embedding model information

    Returns:
        Dict with model metadata
    """
    try:
        service = _get_service()

        return {
            "success": True,
            "model_name": service.model_name,
            "dimension": service.dimension,
            "batch_size": service.batch_size,
            "gpu_enabled": service.use_gpu,
        }
    except Exception as e:
        logger.warning(f"[embedder] Failed to get model info: {e}")
        return {"success": False, "error": f"Failed to get model info: {e}"}
