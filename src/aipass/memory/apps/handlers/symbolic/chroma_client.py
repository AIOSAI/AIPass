#!/home/aipass/MEMORY_BANK/.venv/bin/python3

# ===================AIPASS====================
# META DATA HEADER
# Name: chroma_client.py - Shared ChromaDB Client Handler
# Date: 2026-02-04
# Version: 0.2.0
# Category: memory_bank/handlers/symbolic
#
# CHANGELOG (Max 5 entries):
#   - v0.2.0 (2026-02-15): Canonical singleton client for all ChromaDB access,
#     added get_client() alias, embedding_function=None, cosine distance metadata
#   - v0.1.0 (2026-02-04): Initial version - shared singleton ChromaDB client
#
# CODE STANDARDS:
#   - Handler independence: No module imports
#   - Error handling: Return status dicts (3-tier architecture)
# =============================================

"""
Shared ChromaDB Client Handler - THE canonical singleton for all of Memory Bank

Provides a singleton ChromaDB PersistentClient per database path to prevent
write contention from multiple competing PersistentClient instances against
the same .chroma/ directory.

ALL handlers that need ChromaDB access MUST import from here:
    from MEMORY_BANK.apps.handlers.symbolic.chroma_client import get_client

Key Functions:
    - get_client(db_path) - get singleton PersistentClient (preferred)
    - get_chroma_client(db_path) - alias for get_client (backward compat)
    - get_collection() - get or create a collection with correct settings
"""

import sys
from typing import Dict, Any
from pathlib import Path

# Infrastructure setup
AIPASS_ROOT = Path.home() / "aipass_core"
sys.path.insert(0, str(AIPASS_ROOT))
sys.path.insert(0, str(Path.home()))


# =============================================================================
# CONSTANTS
# =============================================================================

DEFAULT_DB_PATH = Path.home() / "MEMORY_BANK" / ".chroma"

# Singleton client cache - keyed by resolved path string
_clients: Dict[str, Any] = {}


# =============================================================================
# CLIENT MANAGEMENT
# =============================================================================

def get_client(db_path: Path | str | None = None):
    """
    Get or create a shared ChromaDB PersistentClient (singleton per path)

    This is THE canonical way to get a ChromaDB client in Memory Bank.
    All handlers must use this function instead of creating their own
    PersistentClient instances to avoid write contention on .chroma/.

    Args:
        db_path: Optional path to ChromaDB (default: MEMORY_BANK/.chroma)
                 Accepts Path or str.

    Returns:
        ChromaDB PersistentClient instance
    """
    import chromadb

    if db_path is None:
        db_path = DEFAULT_DB_PATH

    if isinstance(db_path, str):
        db_path = Path(db_path)

    # Resolve to absolute path for consistent cache keys
    path_str = str(db_path.resolve())

    if path_str not in _clients:
        db_path.mkdir(parents=True, exist_ok=True)
        # Use simple PersistentClient without Settings to avoid pydantic compatibility issues
        _clients[path_str] = chromadb.PersistentClient(path=path_str)

    return _clients[path_str]


# Backward-compatible alias
def get_chroma_client(db_path: Path | str | None = None):
    """Alias for get_client() - backward compatibility"""
    return get_client(db_path)


def get_collection(
    collection_name: str,
    db_path: Path | None = None,
    create: bool = True,
    metadata: Dict[str, Any] | None = None
):
    """
    Get a collection from the shared ChromaDB client

    Args:
        collection_name: Name of the collection
        db_path: Optional path to ChromaDB
        create: If True, create collection if it doesn't exist
        metadata: Optional collection metadata (default adds cosine distance)

    Returns:
        Dict with 'success', 'collection' or 'error'
    """
    try:
        client = get_client(db_path)

        if create:
            # Default metadata includes cosine distance for similarity search
            if metadata is None:
                metadata = {"hnsw:space": "cosine"}

            collection = client.get_or_create_collection(
                name=collection_name,
                metadata=metadata,
                embedding_function=None
            )
        else:
            collection = client.get_collection(
                collection_name,
                embedding_function=None
            )

        return {
            'success': True,
            'collection': collection
        }

    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }
