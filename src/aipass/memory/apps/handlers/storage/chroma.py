# ===================AIPASS====================
# META DATA HEADER
# Name: chroma.py - Chroma Vector Storage Handler
# Date: 2025-11-16
# Version: 0.3.0
# Category: memory/handlers/storage
#
# CHANGELOG (Max 5 entries):
#   - v0.3.0 (2026-03-06): Adapted for AIPass public repo - optional chromadb
#   - v0.2.0 (2026-02-15): Use shared singleton client, cosine distance,
#     embedding_function=None on all collection access
#   - v0.1.0 (2025-11-16): Initial version - Chroma collection management
#
# CODE STANDARDS:
#   - Handler independence: No module imports
#   - Error handling: Return status dicts (3-tier architecture)
#   - File size: <300 lines target
#   - Best practices: Collection-per-branch, batch inserts
# =============================================

"""
Chroma Vector Storage Handler

Manages Chroma vector database collections for Memory Bank.
Stores embeddings with metadata for semantic search.

Purpose:
    Store 384-dim embeddings from rollover in branch-specific collections.
    Enables fast local search per branch and global search across all branches.

Best Practices Applied:
    - PersistentClient for local-first architecture
    - Collection-per-branch strategy (fast local search)
    - Batch inserts (100-150 optimal)
    - Metadata for filtering (branch, type, date)
    - Singleton pattern (client initialized once)

Dependencies (optional):
    - chromadb
"""

import logging
from typing import List, Dict, Any
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)

# Resolve paths relative to handler location
_MEMORY_ROOT = Path(__file__).resolve().parents[3]

# ChromaDB client - create inline since the old symbolic.chroma_client
# was an internal singleton wrapper
_chroma_clients: Dict[str, Any] = {}

def get_client(db_path: Path):
    """
    Get or create a ChromaDB PersistentClient for the given path.
    Singleton per path to prevent write contention.

    Args:
        db_path: Path to ChromaDB database directory

    Returns:
        chromadb.PersistentClient instance

    Raises:
        ImportError: If chromadb is not installed
    """
    path_str = str(db_path)
    if path_str not in _chroma_clients:
        try:
            import chromadb
        except ImportError:
            raise ImportError(
                "chromadb is required for vector storage. "
                "Install with: pip install chromadb"
            )
        db_path.mkdir(parents=True, exist_ok=True)
        _chroma_clients[path_str] = chromadb.PersistentClient(path=str(db_path))
    return _chroma_clients[path_str]


# =============================================================================
# CHROMA SERVICE (Singleton)
# =============================================================================

class ChromaService:
    """
    Chroma vector database service

    Implements best practices:
    - PersistentClient for local-first
    - Collection-per-branch strategy
    - Batch inserts (optimal for 100-vector rollover)
    - Metadata structure for fast filtering
    """

    def __init__(self, db_path: Path | None = None):
        """
        Initialize Chroma service

        Args:
            db_path: Path to Chroma database (default: memory/.chroma)
        """
        if db_path is None:
            db_path = _MEMORY_ROOT / ".chroma"

        # Use shared singleton client (prevents write contention)
        self.client = get_client(db_path)
        self.db_path = db_path


    def get_collection_name(self, branch: str, memory_type: str) -> str:
        """
        Generate collection name using pattern: {branch}_{type}

        Args:
            branch: Branch name (SEED, CLI, etc.)
            memory_type: Memory type (observations, local)

        Returns:
            Collection name (e.g., 'seed_observations')
        """
        return f"{branch.lower()}_{memory_type.lower()}"


    def store_vectors(
        self,
        branch: str,
        memory_type: str,
        embeddings: List,
        documents: List[str],
        metadatas: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Store vectors in branch-specific collection

        Args:
            branch: Branch name
            memory_type: Memory type
            embeddings: List of embedding vectors (numpy arrays)
            documents: List of text documents
            metadatas: List of metadata dicts

        Returns:
            Dict with storage details
        """
        collection_name = self.get_collection_name(branch, memory_type)

        # Get or create collection
        collection = self.client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine", "branch": branch, "type": memory_type},
            embedding_function=None
        )

        # Get existing count for ID generation
        existing_count = collection.count()

        # Generate unique IDs
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        ids = [
            f"{branch}_{memory_type}_{existing_count + i}_{timestamp}"
            for i in range(len(embeddings))
        ]

        # Convert embeddings to list format (Chroma requirement)
        embeddings_list = [emb.tolist() if hasattr(emb, 'tolist') else emb for emb in embeddings]

        # Batch insert (optimal size: 100-150)
        collection.add(
            embeddings=embeddings_list,
            documents=documents,
            metadatas=metadatas,
            ids=ids
        )

        new_count = collection.count()

        return {
            "collection": collection_name,
            "count": len(embeddings),
            "total_vectors": new_count,
            "ids": ids
        }


    def get_collection_stats(self, branch: str, memory_type: str) -> Dict[str, Any]:
        """
        Get statistics for collection

        Args:
            branch: Branch name
            memory_type: Memory type

        Returns:
            Dict with collection statistics
        """
        collection_name = self.get_collection_name(branch, memory_type)

        try:
            collection = self.client.get_collection(
                collection_name,
                embedding_function=None
            )
            count = collection.count()

            return {
                "collection": collection_name,
                "exists": True,
                "vector_count": count
            }
        except Exception:
            return {
                "collection": collection_name,
                "exists": False,
                "vector_count": 0
            }


    def list_all_collections(self) -> List[str]:
        """
        List all collections in database

        Returns:
            List of collection names
        """
        collections = self.client.list_collections()
        return [col.name for col in collections]


# Global service instance (singleton pattern for default/global)
_chroma_service = None

# Cache for local branch services (one per branch)
_local_services: Dict[str, ChromaService] = {}


def _get_service(db_path: Path | None = None) -> ChromaService:
    """
    Get or create Chroma service

    Args:
        db_path: Path to Chroma database (None = global default)

    Returns:
        ChromaService instance for specified path

    Behavior:
        - If db_path is None: Returns global singleton (memory/.chroma)
        - If db_path specified: Returns cached service for that path or creates new one
    """
    global _chroma_service

    # Global service (default)
    if db_path is None:
        if _chroma_service is None:
            _chroma_service = ChromaService()
        return _chroma_service

    # Local service (branch-specific)
    path_str = str(db_path)
    if path_str not in _local_services:
        _local_services[path_str] = ChromaService(db_path)
    return _local_services[path_str]


# =============================================================================
# PUBLIC API
# =============================================================================

def store_vectors(
    branch: str,
    memory_type: str,
    embeddings: List,
    documents: List[str],
    metadatas: List[Dict[str, Any]],
    db_path: Path | None = None
) -> Dict[str, Any]:
    """
    Store vectors in Chroma collection

    This is the main public API for storing vectors after rollover.
    Creates or uses existing collection for branch + type combination.

    Args:
        branch: Branch name (SEED, CLI, etc.)
        memory_type: Memory type (observations, local)
        embeddings: List of embedding vectors
        documents: List of original text documents
        metadatas: List of metadata dicts for each entry
        db_path: Path to Chroma database (None = global, or specify local branch path)

    Returns:
        Dict with storage details

    Example:
        # Store in global Memory Bank
        result = store_vectors("SEED", "observations", embeddings, texts, metadatas)

        # Store in SEED's local Chroma
        local_path = Path("path/to/seed/.chroma")
        result = store_vectors("SEED", "observations", embeddings, texts, metadatas, local_path)
    """
    # Convert string db_path to Path (subprocess passes strings via JSON)
    if db_path is not None and isinstance(db_path, str):
        db_path = Path(db_path)

    if not embeddings:
        return {
            'success': True,
            'message': 'No vectors provided',
            'count': 0
        }

    if len(embeddings) != len(documents) or len(embeddings) != len(metadatas):
        return {
            'success': False,
            'error': f"Length mismatch: {len(embeddings)} embeddings, "
                    f"{len(documents)} documents, {len(metadatas)} metadatas"
        }

    try:
        service = _get_service(db_path)
        result = service.store_vectors(branch, memory_type, embeddings, documents, metadatas)

        return {
            'success': True,
            **result
        }

    except Exception as e:
        return {
            'success': False,
            'error': f"Storage failed: {e}"
        }


def get_collection_stats(branch: str, memory_type: str) -> Dict[str, Any]:
    """
    Get statistics for collection

    Args:
        branch: Branch name
        memory_type: Memory type

    Returns:
        Dict with collection statistics
    """
    try:
        service = _get_service()
        stats = service.get_collection_stats(branch, memory_type)

        return {
            'success': True,
            **stats
        }

    except Exception as e:
        return {
            'success': False,
            'error': f"Failed to get stats: {e}"
        }


def list_all_collections() -> Dict[str, Any]:
    """
    List all collections in database

    Returns:
        Dict with collection list
    """
    try:
        service = _get_service()
        collections = service.list_all_collections()

        return {
            'success': True,
            'collections': collections,
            'count': len(collections)
        }

    except Exception as e:
        return {
            'success': False,
            'error': f"Failed to list collections: {e}"
        }


def get_database_info() -> Dict[str, Any]:
    """
    Get database information

    Returns:
        Dict with database metadata
    """
    try:
        service = _get_service()
        collections = service.list_all_collections()

        return {
            'success': True,
            'db_path': str(service.db_path),
            'collections_count': len(collections),
            'collections': collections
        }

    except Exception as e:
        return {
            'success': False,
            'error': f"Failed to get database info: {e}"
        }


def search_vectors(
    query_embedding: List[float],
    branch: str | None = None,
    memory_type: str | None = None,
    n_results: int = 5,
    db_path: Path | None = None
) -> Dict[str, Any]:
    """
    Search for similar vectors in Chroma collections

    Args:
        query_embedding: Query vector (384-dim for all-MiniLM-L6-v2)
        branch: Optional branch filter (if None, searches all collections)
        memory_type: Optional memory type filter (observations, local)
        n_results: Number of results to return per collection
        db_path: Path to Chroma database (None = global)

    Returns:
        Dict with search results grouped by collection

    Example:
        # Search specific branch
        results = search_vectors(query_emb, branch="SEED", memory_type="observations")

        # Global search across all branches
        results = search_vectors(query_emb, n_results=10)
    """
    # Convert string db_path to Path (subprocess passes strings via JSON)
    if db_path is not None and isinstance(db_path, str):
        db_path = Path(db_path)

    try:
        service = _get_service(db_path)

        # Determine which collections to search
        if branch and memory_type:
            # Search specific collection
            collection_names = [service.get_collection_name(branch, memory_type)]
        else:
            # Search all collections
            collection_names = service.list_all_collections()

            # Apply filters
            if branch:
                collection_names = [c for c in collection_names if c.startswith(branch.lower())]
            if memory_type:
                collection_names = [c for c in collection_names if c.endswith(memory_type.lower())]

        if not collection_names:
            return {
                'success': True,
                'results': [],
                'message': 'No matching collections found'
            }

        # Search each collection
        all_results = []

        for collection_name in collection_names:
            try:
                collection = service.client.get_collection(
                    collection_name,
                    embedding_function=None
                )

                # Query collection
                results = collection.query(
                    query_embeddings=[query_embedding],
                    n_results=n_results
                )

                # Format results
                if results['documents'] and results['documents'][0]:
                    for i, doc in enumerate(results['documents'][0]):
                        all_results.append({
                            'collection': collection_name,
                            'document': doc,
                            'metadata': results['metadatas'][0][i] if results['metadatas'] else {},
                            'distance': results['distances'][0][i] if results['distances'] else None,
                            'id': results['ids'][0][i] if results['ids'] else None
                        })

            except Exception as e:
                # Collection might not exist - skip it
                continue

        # Sort by distance (lower is better)
        all_results.sort(key=lambda x: x['distance'] if x['distance'] is not None else float('inf'))

        return {
            'success': True,
            'results': all_results[:n_results * len(collection_names)] if all_results else [],
            'collections_searched': len(collection_names),
            'total_results': len(all_results)
        }

    except Exception as e:
        return {
            'success': False,
            'error': f"Search failed: {e}"
        }
