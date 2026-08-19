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
    - fastembed
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

        json_handler.log_operation(
            "vector_list_collections",
            {"count": len(collections), "success": True},
        )
        return {"success": True, "collections": collections, "count": len(collections), "db_path": str(service.db_path)}

    except Exception as e:
        logger.error(f"[vector_search] Failed to list collections: {e}")
        return {"success": False, "error": f"Failed to list collections: {e}"}
