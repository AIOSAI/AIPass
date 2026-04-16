# =================== AIPass ====================
# Name: vector_search.py
# Description: Vector Search Handler
# Version: 0.3.0
# Created: 2025-11-27
# Modified: 2026-03-06
# =============================================

"""
Vector Search Handler

Queries ChromaDB collections using semantic embeddings.
Uses same model as embedder.py (all-MiniLM-L6-v2) for query encoding.

Purpose:
    Search memory vectors by semantic similarity.
    Supports filtering by metadata and multi-collection search.

Design:
    - Query encoding uses same model as storage (embedder.py)
    - Singleton pattern for model efficiency
    - Collection-level and database-level search
    - Metadata filtering for targeted queries

Dependencies (optional):
    - chromadb
    - sentence-transformers
    - torch
"""

from typing import List, Dict, Any
from pathlib import Path

from aipass.prax.apps.modules.logger import get_system_logger
from aipass.memory.apps.handlers.json import json_handler

logger = get_system_logger()

# Resolve paths relative to handler location
_MEMORY_ROOT = Path(__file__).resolve().parents[3]

# Shared ChromaDB client (reuse from chroma handler)
from aipass.memory.apps.handlers.storage.chroma import get_client


# =============================================================================
# QUERY ENCODING SERVICE (Singleton)
# =============================================================================


class QueryEncoder:
    """
    Query encoding service using same model as embedder.py

    Ensures query embeddings are compatible with stored embeddings.
    Uses all-MiniLM-L6-v2 model with same settings.
    """

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        """
        Initialize query encoder

        Args:
            model_name: HuggingFace model identifier (must match embedder.py)

        Raises:
            ImportError: If sentence-transformers or torch are not installed
        """
        # Late imports (heavy optional dependencies)
        try:
            import torch
            from sentence_transformers import SentenceTransformer
        except ImportError as e:
            logger.info(f"[vector_search] Optional ML dependencies not available: {e}")
            raise ImportError(
                f"Search requires sentence-transformers and torch. "
                f"Install with: pip install sentence-transformers torch. "
                f"Original error: {e}"
            )

        self.model_name = model_name
        self.model = SentenceTransformer(model_name)

        # GPU optimization if available
        self.use_gpu = torch.cuda.is_available()
        if self.use_gpu:
            self.model = self.model.to("cuda")

        self.dimension = 384  # all-MiniLM-L6-v2 output dimension

    def encode(self, query: str) -> List[float]:
        """
        Encode query text to embedding

        Args:
            query: Query text string

        Returns:
            384-dimensional embedding as list
        """
        import torch

        # Encode with same settings as embedder.py
        embedding = self.model.encode(
            query,
            convert_to_tensor=False,  # Return numpy
            normalize_embeddings=True,  # Critical for L2 distance
            show_progress_bar=False,
        )

        # Cleanup GPU memory if used
        if self.use_gpu:
            torch.cuda.empty_cache()

        return embedding.tolist()


# Global encoder instance (singleton pattern)
_query_encoder = None


def _get_encoder() -> QueryEncoder:
    """
    Get or create query encoder singleton

    Lazy initialization - model loaded on first use
    """
    global _query_encoder
    if _query_encoder is None:
        _query_encoder = QueryEncoder()
    return _query_encoder


# =============================================================================
# CHROMA SEARCH SERVICE
# =============================================================================


class SearchService:
    """
    ChromaDB search service

    Handles connection to ChromaDB and query execution.
    Supports single collection and multi-collection search.
    """

    def __init__(self, db_path: Path | None = None):
        """
        Initialize search service

        Args:
            db_path: Path to ChromaDB database (default: memory/.chroma)
        """
        if db_path is None:
            db_path = _MEMORY_ROOT / ".chroma"

        # Use shared singleton client (prevents write contention)
        self.client = get_client(db_path)
        self.db_path = db_path

    def query_collection(
        self,
        collection_name: str,
        query_embedding: List[float],
        n_results: int = 5,
        where: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        """
        Query a specific collection

        Args:
            collection_name: Name of collection to query
            query_embedding: Query embedding vector
            n_results: Number of results to return
            where: Metadata filter (e.g., {"branch": "SEEDGO"})

        Returns:
            Dict with query results
        """
        try:
            collection = self.client.get_collection(collection_name, embedding_function=None)
        except Exception as e:
            logger.warning(f"[vector_search] Collection lookup failed for '{collection_name}': {e}")
            return {"collection": collection_name, "exists": False, "error": f"Collection not found: {e}"}

        # Query collection
        results = collection.query(query_embeddings=[query_embedding], n_results=n_results, where=where)

        return {
            "collection": collection_name,
            "exists": True,
            "ids": results["ids"][0] if results["ids"] else [],
            "documents": results["documents"][0] if results["documents"] else [],
            "metadatas": results["metadatas"][0] if results["metadatas"] else [],
            "distances": results["distances"][0] if results["distances"] else [],
            "count": len(results["ids"][0]) if results["ids"] else 0,
        }

    def list_collections(self) -> List[str]:
        """
        List all collections in database

        Returns:
            List of collection names
        """
        collections = self.client.list_collections()
        return [col.name for col in collections]


# Global search service instance (singleton pattern)
_search_service = None

# Cache for local branch services
_local_services: Dict[str, SearchService] = {}


def _get_service(db_path: Path | None = None) -> SearchService:
    """
    Get or create search service

    Args:
        db_path: Path to ChromaDB database (None = global default)

    Returns:
        SearchService instance for specified path
    """
    global _search_service

    # Global service (default)
    if db_path is None:
        if _search_service is None:
            _search_service = SearchService()
        return _search_service

    # Local service (branch-specific)
    path_str = str(db_path)
    if path_str not in _local_services:
        _local_services[path_str] = SearchService(db_path)
    return _local_services[path_str]


# =============================================================================
# PUBLIC API
# =============================================================================


def search_collection(
    query_embedding: List[float],
    collection_name: str,
    n_results: int = 5,
    where: Dict[str, Any] | None = None,
    db_path: Path | None = None,
) -> Dict[str, Any]:
    """
    Query a ChromaDB collection with embedding

    Search a specific collection for semantically similar memories.

    Args:
        query_embedding: Pre-encoded query embedding (384-dim list)
        collection_name: Name of collection to search
        n_results: Number of results to return (default: 5)
        where: Optional metadata filter (e.g., {"branch": "SEEDGO"})
        db_path: Path to ChromaDB database (None = global memory/.chroma)

    Returns:
        Dict with success status and search results

    Example:
        # Encode query first
        query_result = encode_query("how does rollover work?")

        # Search collection
        result = search_collection(
            query_embedding=query_result['embedding'],
            collection_name="seed_observations",
            n_results=10
        )

        if result['success']:
            for i, doc in enumerate(result['documents']):
                print(f"{i+1}. {doc[:100]}...")
    """
    # Convert string db_path to Path
    if db_path is not None and isinstance(db_path, str):
        db_path = Path(db_path)

    if not query_embedding:
        return {"success": False, "error": "No query embedding provided"}

    try:
        service = _get_service(db_path)
        result = service.query_collection(
            collection_name=collection_name, query_embedding=query_embedding, n_results=n_results, where=where
        )

        # Check if collection exists
        if not result.get("exists", False):
            return {
                "success": False,
                "error": result.get("error", "Collection not found"),
                "collection": collection_name,
            }

        json_handler.log_operation(
            "vector_search_collection",
            {"collection": collection_name, "count": result.get("count", 0), "success": True},
        )
        return {"success": True, **result}

    except Exception as e:
        logger.error(f"[vector_search] Collection search failed for '{collection_name}': {e}")
        return {"success": False, "error": f"Search failed: {e}"}


def encode_query(query: str) -> Dict[str, Any]:
    """
    Encode query text to embedding using same model as storage

    Uses all-MiniLM-L6-v2 model (same as embedder.py) to ensure
    query embeddings are compatible with stored embeddings.

    Args:
        query: Query text string

    Returns:
        Dict with success status and embedding

    Example:
        result = encode_query("how does memory compression work?")
        if result['success']:
            embedding = result['embedding']  # 384-dim list
            dimension = result['dimension']  # 384
    """
    if not query or not query.strip():
        return {"success": False, "error": "Empty query string"}

    try:
        encoder = _get_encoder()
        embedding = encoder.encode(query)

        return {"success": True, "embedding": embedding, "dimension": len(embedding), "model": encoder.model_name}

    except Exception as e:
        logger.error(f"[vector_search] Query encoding failed: {e}")
        return {"success": False, "error": f"Encoding failed: {e}"}


def list_collections(db_path: Path | None = None) -> Dict[str, Any]:
    """
    List available collections in database

    Args:
        db_path: Path to ChromaDB database (None = global default)

    Returns:
        Dict with success status and collection list

    Example:
        result = list_collections()
        if result['success']:
            for collection in result['collections']:
                print(f"- {collection}")
    """
    # Convert string db_path to Path
    if db_path is not None and isinstance(db_path, str):
        db_path = Path(db_path)

    try:
        service = _get_service(db_path)
        collections = service.list_collections()

        return {"success": True, "collections": collections, "count": len(collections), "db_path": str(service.db_path)}

    except Exception as e:
        logger.error(f"[vector_search] Failed to list collections: {e}")
        return {"success": False, "error": f"Failed to list collections: {e}"}


def search_all_collections(
    query_embedding: List[float], n_results: int = 5, where: Dict[str, Any] | None = None, db_path: Path | None = None
) -> Dict[str, Any]:
    """
    Search across all collections in database

    Queries every collection and aggregates results.
    Useful for cross-branch semantic search.

    Args:
        query_embedding: Pre-encoded query embedding
        n_results: Number of results per collection
        where: Optional metadata filter
        db_path: Path to ChromaDB database (None = global default)

    Returns:
        Dict with success status and aggregated results

    Example:
        # Find similar memories across all branches
        query_result = encode_query("deployment process")
        result = search_all_collections(
            query_embedding=query_result['embedding'],
            n_results=3
        )

        if result['success']:
            for coll_name, coll_results in result['results'].items():
                print(f"\n{coll_name}:")
                for doc in coll_results['documents']:
                    print(f"  - {doc[:80]}...")
    """
    # Convert string db_path to Path
    if db_path is not None and isinstance(db_path, str):
        db_path = Path(db_path)

    if not query_embedding:
        return {"success": False, "error": "No query embedding provided"}

    try:
        service = _get_service(db_path)
        collections = service.list_collections()

        if not collections:
            return {"success": True, "results": {}, "message": "No collections found"}

        # Query each collection
        results = {}
        for collection_name in collections:
            coll_result = service.query_collection(
                collection_name=collection_name, query_embedding=query_embedding, n_results=n_results, where=where
            )

            if coll_result.get("exists", False):
                results[collection_name] = {
                    "documents": coll_result["documents"],
                    "metadatas": coll_result["metadatas"],
                    "distances": coll_result["distances"],
                    "ids": coll_result["ids"],
                    "count": coll_result["count"],
                }

        total = sum(r["count"] for r in results.values())
        json_handler.log_operation(
            "vector_search_all", {"collections": len(results), "total_results": total, "success": True}
        )
        return {"success": True, "results": results, "collections_searched": len(results), "total_results": total}

    except Exception as e:
        logger.error(f"[vector_search] Multi-collection search failed: {e}")
        return {"success": False, "error": f"Multi-collection search failed: {e}"}
